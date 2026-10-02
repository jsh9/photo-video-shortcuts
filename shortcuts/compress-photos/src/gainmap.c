#include "gainmap.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint32_t rd32(const uint8_t *p) {
  return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

// ---------------------------------------------------------------------------
// Metadata

static int fraction(const uint8_t *p, int is_signed, double *out) {
  const uint32_t n = rd32(p), d = rd32(p + 4);
  if (d == 0) return -1;
  *out = (is_signed ? (double)(int32_t)n : (double)n) / (double)d;
  return 0;
}

int gainmap_parse(const uint8_t *p, size_t len, gainmap_meta_t *m, char *err, size_t err_len) {
  memset(m, 0, sizeof *m);
  // ToneMapImage: version, then GainMapMetadata (ISO 21496-1, 7.2.2).
  if (len >= 1 && p[0] != 0) {
    snprintf(err, err_len, "unsupported tone map version");
    return -1;
  }
  if (len < 6) {
    snprintf(err, err_len, "malformed gain map metadata");
    return -1;
  }
  const unsigned min_version = (unsigned)(p[1] << 8 | p[2]), writer_version = (unsigned)(p[3] << 8 | p[4]);
  if (min_version > 0 || writer_version < min_version) {
    snprintf(err, err_len, "unsupported gain map version %u", min_version);
    return -1;
  }
  m->channels = (p[5] & 0x80) ? 3 : 1;
  m->use_base_color_space = (p[5] & 0x40) != 0;
  const size_t need = 6 + 16 + (size_t)m->channels * 40;
  // Later writer versions may append fields that version 0 readers skip.
  if (len < need || (writer_version == 0 && len != need)) {
    snprintf(err, err_len, "malformed gain map metadata");
    return -1;
  }
  const uint8_t *q = p + 6;
  int bad = fraction(q, 0, &m->base_headroom) | fraction(q + 8, 0, &m->alternate_headroom);
  q += 16;
  for (int c = 0; c < m->channels; c++, q += 40) {
    bad |= fraction(q, 1, &m->min[c]) | fraction(q + 8, 1, &m->max[c]) | fraction(q + 16, 0, &m->gamma[c]) |
           fraction(q + 24, 1, &m->base_offset[c]) | fraction(q + 32, 1, &m->alternate_offset[c]);
    bad |= !(m->gamma[c] > 0) || m->max[c] < m->min[c] || !(m->max[c] <= GAINMAP_MAX_STOPS);
  }
  bad |= !(m->alternate_headroom <= GAINMAP_MAX_STOPS);
  if (bad) {
    snprintf(err, err_len, "malformed gain map metadata");
    return -1;
  }
  for (int c = m->channels; c < 3; c++) {
    m->min[c] = m->min[0];
    m->max[c] = m->max[0];
    m->gamma[c] = m->gamma[0];
    m->base_offset[c] = m->base_offset[0];
    m->alternate_offset[c] = m->alternate_offset[0];
  }
  return 0;
}

void gainmap_apple_meta(double maker33, double maker48, gainmap_meta_t *m) {
  // Apple's formula, from "Applying Apple HDR effect to your photos"
  double stops;
  if (maker33 < 1.0) {
    stops = maker48 <= 0.01 ? -20.0 * maker48 + 1.8 : -0.101 * maker48 + 1.601;
  } else {
    stops = maker48 <= 0.01 ? -70.0 * maker48 + 3.0 : -0.303 * maker48 + 2.303;
  }
  const double headroom = exp2(stops > 0 ? stops : 0);
  memset(m, 0, sizeof *m);
  m->channels = 1;
  m->use_base_color_space = 1;
  m->alternate_headroom = log2(headroom);
  m->apple_headroom = headroom;
}

double gainmap_peak(const gainmap_meta_t *m) {
  if (m->apple_headroom > 0) return m->apple_headroom;
  double peak = 0;
  for (int c = 0; c < m->channels; c++) {
    const double v = (1 + m->base_offset[c]) * exp2(m->max[c]) - m->alternate_offset[c];
    if (v > peak) peak = v;
  }
  return peak;
}

int gainmap_same_shape(double w1, double h1, double w2, double h2) {
  return w1 > 0 && h1 > 0 && w2 > 0 && h2 > 0 && fabs((w1 / h1) / (w2 / h2) - 1) <= 0.05;
}

// ---------------------------------------------------------------------------
// Color of the SDR image

static double srgb_to_linear(double v) { return v <= 0.04045 ? v / 12.92 : pow((v + 0.055) / 1.055, 2.4); }
static double rec709_to_linear(double v) { return v < 0.081 ? v / 4.5 : pow((v + 0.099) / 1.099, 1 / 0.45); }

// An ICC tag's data, or NULL.
static const uint8_t *icc_tag(const blob_t *icc, const char sig[4], size_t *size) {
  const uint8_t *p = icc->data;
  if (icc->size < 132) return NULL;
  const uint32_t count = rd32(p + 128);
  if (count > (icc->size - 132) / 12) return NULL;
  for (uint32_t i = 0; i < count; i++) {
    const uint8_t *t = p + 132 + 12 * i;
    const uint32_t off = rd32(t + 4), len = rd32(t + 8);
    if (memcmp(t, sig, 4) == 0 && off <= icc->size && len <= icc->size - off) {
      *size = len;
      return p + off;
    }
  }
  return NULL;
}

int gainmap_icc_has_tag(const blob_t *icc, const char sig[4]) {
  size_t size = 0;
  return icc_tag(icc, sig, &size) != NULL;
}

static double s15(const uint8_t *p) { return (double)(int32_t)rd32(p) / 65536.0; }

// Evaluates a 'para' or 'curv' tone curve at x in [0, 1]; returns -1 if unknown.
static double icc_curve(const uint8_t *t, size_t n, double x) {
  if (n >= 12 && memcmp(t, "curv", 4) == 0) {
    const uint32_t count = rd32(t + 8);
    if (count < 2 || count > (n - 12) / 2) return -1;  // 0/1 entries: a plain gamma, not sRGB's
    const double pos = x * (count - 1);
    uint32_t i = (uint32_t)pos;
    if (i >= count - 1) i = count - 2;
    const double a = (t[12 + 2 * i] << 8 | t[13 + 2 * i]) / 65535.0;
    const double b = (t[14 + 2 * i] << 8 | t[15 + 2 * i]) / 65535.0;
    return a + (b - a) * (pos - i);
  }
  if (n >= 12 && memcmp(t, "para", 4) == 0) {
    static const int kParams[5] = {1, 3, 4, 5, 7};
    const unsigned type = (unsigned)(t[8] << 8 | t[9]);
    if (type > 4 || n < 12 + 4 * (size_t)kParams[type]) return -1;
    double g = s15(t + 12), a = 1, b = 0, c = 0, d = 0, e = 0, f = 0;
    if (type >= 1) a = s15(t + 16), b = s15(t + 20);
    if (type == 2) c = s15(t + 24);
    if (type >= 3) c = s15(t + 24), d = s15(t + 28);
    if (type == 4) e = s15(t + 32), f = s15(t + 36);
    switch (type) {
      case 0: return pow(x, g);
      case 1: return x >= -b / a ? pow(a * x + b, g) : 0;
      case 2: return x >= -b / a ? pow(a * x + b, g) + c : c;
      case 3: return x >= d ? pow(a * x + b, g) : c * x;
      default: return x >= d ? pow(a * x + b, g) + e : c * x + f;
    }
  }
  return -1;
}

// 1 if the profile's red, green and blue curves are all sRGB's.
static int icc_is_srgb_curve(const blob_t *icc) {
  static const char *kTags[3] = {"rTRC", "gTRC", "bTRC"};
  for (int i = 0; i < 3; i++) {
    size_t n = 0;
    const uint8_t *t = icc_tag(icc, kTags[i], &n);
    if (!t) return 0;
    for (int k = 0; k <= 64; k++) {
      const double x = k / 64.0, y = icc_curve(t, n, x);
      if (!(y >= 0 && fabs(y - srgb_to_linear(x)) <= 0.002)) return 0;  // also NaN
    }
  }
  return 1;
}

// The red, green and blue colorants (D50-adapted XYZ) of Display P3 and sRGB.
static const double kColorants[2][9] = {
    {0.5151, 0.2412, -0.0011, 0.2920, 0.6922, 0.0419, 0.1571, 0.0666, 0.7841},  // Display P3
    {0.4361, 0.2225, 0.0139, 0.3851, 0.7169, 0.0971, 0.1431, 0.0606, 0.7141},   // sRGB
};

static int icc_primaries(const blob_t *icc) {
  static const char *kTags[3] = {"rXYZ", "gXYZ", "bXYZ"};
  const uint8_t *p = icc->data;
  if (icc->size < 132 || memcmp(p + 36, "acsp", 4) != 0 || memcmp(p + 16, "RGB ", 4) != 0) return 0;
  double xyz[9];
  for (int i = 0; i < 3; i++) {
    size_t n = 0;
    const uint8_t *t = icc_tag(icc, kTags[i], &n);
    if (!t || n < 20 || memcmp(t, "XYZ ", 4) != 0) return 0;
    for (int k = 0; k < 3; k++) xyz[3 * i + k] = s15(t + 8 + 4 * k);
  }
  for (int s = 0; s < 2; s++) {
    int match = 1;
    for (int k = 0; k < 9; k++) match &= fabs(xyz[k] - kColorants[s][k]) < 0.003;
    if (match) return icc_is_srgb_curve(icc) ? (s == 0 ? 12 : 1) : 0;
  }
  return 0;
}

void gainmap_color_name(const color_t *color, char *buf, size_t len) {
  snprintf(buf, len, "%s", color->icc.size ? "ICC profile" : "no profile");
  if (!color->icc.size) {
    if (color->cicp_present) snprintf(buf, len, "CICP %u/%u", color->cicp[0], color->cicp[1]);
    return;
  }
  size_t n = 0;
  const uint8_t *t = icc_tag(&color->icc, "desc", &n);
  const uint8_t *text = NULL;
  size_t chars = 0, step = 1;
  if (t && n >= 12 && memcmp(t, "desc", 4) == 0) {  // ICC v2: ASCII
    chars = rd32(t + 8);
    if (chars > n - 12) chars = n - 12;
    text = t + 12;
  } else if (t && n >= 28 && memcmp(t, "mluc", 4) == 0) {  // v4: UTF-16, first record
    const uint32_t size = rd32(t + 20), offset = rd32(t + 24);
    if (offset <= n && size <= n - offset) {
      text = t + offset + 1;  // the low byte of each big-endian code unit
      chars = size / 2;
      step = 2;
    }
  }
  if (!text) return;
  size_t k = 0;
  for (size_t i = 0; i < chars && k + 1 < len && text[i * step]; i++) {
    const uint8_t c = text[i * step];
    buf[k++] = (char)(c >= 0x20 && c < 0x7f ? c : '?');
  }
  if (k) buf[k] = 0;
}

int gainmap_srgb_primaries(const color_t *color) {
  if (color->icc.size) return icc_primaries(&color->icc);
  // No color, or unspecified (2) code points, as ImageIO writes for sRGB, means
  // sRGB, as for SDR photos.
  if (!color->cicp_present) return 1;
  const int primaries = color->cicp[0] == 2 ? 1 : color->cicp[0];
  const int transfer = color->cicp[1] == 2 ? 13 : color->cicp[1];
  return transfer == 13 && (primaries == 1 || primaries == 12) ? primaries : 0;
}

// ---------------------------------------------------------------------------
// Applying the gain map

#define GAIN_STEPS 4096  // gain table entries (interpolated) over gain map values 0..1
#define PQ_STEPS 6       // PQ table: 2^PQ_STEPS entries per octave (interpolated) ...
#define PQ_OCTAVES 40    // ... from 2^-40 to 1, in units of 10,000 nits

// SMPTE ST 2084 (PQ): y in units of 10,000 nits to a signal in [0, 1].
static double pq_from_linear(double y) {
  const double m1 = 2610.0 / 16384, m2 = 2523.0 / 4096 * 128;
  const double c1 = 3424.0 / 4096, c2 = 2413.0 / 4096 * 32, c3 = 2392.0 / 4096 * 32;
  const double p = pow(y, m1);
  return pow((c1 + c2 * p) / (1 + c3 * p), m2);
}

// Entry i is the 16-bit PQ code of 2^e * (1 + j / 2^PQ_STEPS), for e = i / 2^PQ_STEPS - PQ_OCTAVES
// and j = i % 2^PQ_STEPS: indexed by the bits of a float.
static void pq_table(float *t) {
  for (uint32_t i = 0; i <= (uint32_t)PQ_OCTAVES << PQ_STEPS; i++) {
    const double y = ldexp(1.0 + (double)(i & ((1u << PQ_STEPS) - 1)) / (1 << PQ_STEPS),
                           (int)(i >> PQ_STEPS) - PQ_OCTAVES);
    t[i] = (float)(pq_from_linear(y) * 65535.0);
  }
}

static inline uint16_t pq_code(const float *t, float y) {
  if (!(y > 0x1p-40f)) return 0;  // also NaN
  if (y >= 1.0f) return 65535;
  uint32_t bits;
  memcpy(&bits, &y, sizeof bits);
  const uint32_t i = (bits >> (23 - PQ_STEPS)) - ((127u - PQ_OCTAVES) << PQ_STEPS);
  const float f = (float)(bits & ((1u << (23 - PQ_STEPS)) - 1)) * (1.0f / (float)(1u << (23 - PQ_STEPS)));
  return (uint16_t)(t[i] + (t[i + 1] - t[i]) * f + 0.5f);
}

static inline float gain_at(const float *t, float g) {
  const float x = g * GAIN_STEPS;
  int i = (int)x;
  if (i >= GAIN_STEPS) i = GAIN_STEPS - 1;
  return t[i] + (t[i + 1] - t[i]) * (x - (float)i);
}

// Two gain map rows, enlarged to the output width (horizontal half of the
// bilinear scaling), each reused for the output rows between them.
typedef struct {
  float *row[2];
  long index[2];
} row_cache_t;

static const float *enlarged_row(row_cache_t *cache, const image_t *gm, uint32_t r, const uint32_t *x0,
                                 const float *fx, uint32_t w, float offset, float scale) {
  int slot = cache->index[0] == (long)r ? 0 : cache->index[1] == (long)r ? 1 : -1;
  if (slot >= 0) return cache->row[slot];
  slot = cache->index[0] < cache->index[1] ? 0 : 1;  // replace the older row
  float *out = cache->row[slot];
  const int ch = gm->channels;
  const uint8_t *src8 = gm->data + (size_t)r * gm->stride;
  const uint16_t *src16 = (const uint16_t *)src8;
  const uint32_t last = gm->w - 1;
  for (uint32_t x = 0; x < w; x++) {
    const size_t a = (size_t)x0[x] * ch, b = (size_t)(x0[x] < last ? x0[x] + 1 : last) * ch;
    for (int c = 0; c < ch; c++) {
      const float va = gm->bytes_per_sample == 1 ? src8[a + c] : src16[a + c];
      const float vb = gm->bytes_per_sample == 1 ? src8[b + c] : src16[b + c];
      float v = ((va + (vb - va) * fx[x]) - offset) * scale;
      out[(size_t)x * ch + c] = v < 0 ? 0 : v > 1 ? 1 : v;
    }
  }
  cache->index[slot] = r;
  return out;
}

// Center-aligned bilinear source position of output pixel i, scaling
// [start, end) of the source to out_size pixels: index and weight.
static void source_position(uint32_t i, uint32_t out_size, double start, double end, uint32_t in_size,
                            uint32_t *index, float *weight) {
  double s = start + (i + 0.5) * (end - start) / out_size - 0.5;
  if (s < 0) s = 0;
  if (s > in_size - 1) s = in_size - 1;
  *index = (uint32_t)s;
  *weight = (float)(s - *index);
}

// An HDR image computed on request: the SDR photo, the gain map, and the
// tables to combine them.
typedef struct {
  image_t base, gm;
  float *linear, *gain, *pq;  // sRGB curve, gain per channel, PQ codes
  uint32_t *x0;               // per output column: gain map column and weight
  float *fx;
  float offset, scale;  // gain map values to [0, 1]
  float base_offset[3], alternate_offset[3], to_pq;
  double window_y[2];  // the gain map rows scaled to the photo's height
  uint32_t base_max;
  int meta_channels, per_channel;
} renderer_t;

static void renderer_free(void *owner) {
  renderer_t *r = (renderer_t *)owner;
  if (!r) return;
  image_free(&r->base);
  image_free(&r->gm);
  free(r->linear);
  free(r->gain);
  free(r->pq);
  free(r->x0);
  free(r->fx);
  free(r);
}

// Writes the HDR pixels of the w x h region at (x, y), row by row.
static int render(void *owner, uint32_t x, uint32_t y, uint32_t w, uint32_t h, uint8_t *out, size_t stride) {
  const renderer_t *r = (const renderer_t *)owner;
  const image_t *base = &r->base, *gm = &r->gm;
  const int ch = base->channels, gch = gm->channels;
  row_cache_t cache = {{(float *)malloc((size_t)w * gch * sizeof(float)),
                        (float *)malloc((size_t)w * gch * sizeof(float))},
                       {-1, -1}};
  if (!cache.row[0] || !cache.row[1]) {
    free(cache.row[0]);
    free(cache.row[1]);
    return -1;
  }
  for (uint32_t yy = y; yy < y + h; yy++) {
    uint32_t r0;
    float fy;
    source_position(yy, base->h, r->window_y[0], r->window_y[1], gm->h, &r0, &fy);
    const uint32_t r1 = r0 + 1 < gm->h ? r0 + 1 : r0;
    const float *upper = enlarged_row(&cache, gm, r0, r->x0 + x, r->fx + x, w, r->offset, r->scale);
    const float *lower = enlarged_row(&cache, gm, r1, r->x0 + x, r->fx + x, w, r->offset, r->scale);
    if (r1 == r0) lower = upper;
    const uint8_t *src8 = base->data + (size_t)yy * base->stride + (size_t)x * pixel_size(base);
    const uint16_t *src16 = (const uint16_t *)src8;
    uint16_t *dst = (uint16_t *)(out + (size_t)(yy - y) * stride);
    for (uint32_t xx = 0; xx < w; xx++) {
      float factor[3];
      for (int c = 0; c < (r->per_channel ? 3 : 1); c++) {
        const int gc = gch == 3 ? c : 0;
        const float a = upper[(size_t)xx * gch + gc], b = lower[(size_t)xx * gch + gc];
        factor[c] = gain_at(r->gain + (r->meta_channels == 3 ? c : 0) * (GAIN_STEPS + 1), a + (b - a) * fy);
      }
      if (!r->per_channel) factor[1] = factor[2] = factor[0];
      const size_t i = (size_t)xx * ch;
      for (int c = 0; c < 3; c++) {
        const uint32_t v = base->bytes_per_sample == 1 ? src8[i + c] : src16[i + c];
        // HDR = (SDR + base offset) * gain - alternate offset, linear, 1.0 = SDR white.
        const float hdr = (r->linear[v] + r->base_offset[c]) * factor[c] - r->alternate_offset[c];
        dst[i + c] = pq_code(r->pq, hdr * r->to_pq);
      }
      if (ch == 4) {
        const uint32_t a = base->bytes_per_sample == 1 ? src8[i + 3] : src16[i + 3];
        dst[i + 3] = (uint16_t)(((uint64_t)a * 65535 + r->base_max / 2) / r->base_max);
      }
    }
  }
  free(cache.row[0]);
  free(cache.row[1]);
  return 0;
}

int gainmap_prepare(image_t *base, image_t *gm, const double window[4], int gm_full_range, const gainmap_meta_t *m,
                    image_t *out) {
  memset(out, 0, sizeof *out);
  const uint32_t w = base->w, h = base->h;
  const int ch = base->channels;
  if ((uint64_t)w * h > SIZE_MAX / ((size_t)ch * 2)) return -1;
  renderer_t *r = (renderer_t *)calloc(1, sizeof *r);
  if (!r) return -1;
  r->base_max = (1u << base->bits) - 1;
  const uint32_t gm_bits = gm->bytes_per_sample == 1 ? 8 : (uint32_t)gm->bits;
  // Gain map values to [0, 1], expanding limited range (16-235 at 8 bits).
  const float gm_max = (float)((1u << gm_bits) - 1);
  r->offset = gm_full_range ? 0.0f : (float)(16u << (gm_bits - 8));
  r->scale = gm_full_range ? 1.0f / gm_max : 1.0f / (float)(219u << (gm_bits - 8));
  r->linear = (float *)malloc(((size_t)r->base_max + 1) * sizeof *r->linear);
  r->gain = (float *)malloc(3 * (GAIN_STEPS + 1) * sizeof *r->gain);
  r->pq = (float *)malloc((((size_t)PQ_OCTAVES << PQ_STEPS) + 1) * sizeof *r->pq);
  r->x0 = (uint32_t *)malloc((size_t)w * sizeof *r->x0);
  r->fx = (float *)malloc((size_t)w * sizeof *r->fx);
  if (!r->linear || !r->gain || !r->pq || !r->x0 || !r->fx) {
    renderer_free(r);
    return -1;
  }
  for (uint32_t v = 0; v <= r->base_max; v++) r->linear[v] = (float)srgb_to_linear((double)v / r->base_max);
  for (int c = 0; c < 3; c++) {
    for (int i = 0; i <= GAIN_STEPS; i++) {
      const double v = (double)i / GAIN_STEPS;
      double gain;
      if (m->apple_headroom > 0) {
        // Apple's older gain map: 1 + (headroom - 1) * value, linearized
        // with the inverse Rec. 709 curve.
        gain = 1 + (m->apple_headroom - 1) * rec709_to_linear(v);
      } else {
        // ISO 21496-1: gain (log2) = min + (max - min) * value^(1/gamma), here
        // at full weight (the display's headroom reaching the alternate one).
        gain = exp2(m->min[c] + (m->max[c] - m->min[c]) * pow(v, 1.0 / m->gamma[c]));
      }
      r->gain[c * (GAIN_STEPS + 1) + i] = (float)gain;
    }
  }
  pq_table(r->pq);
  for (uint32_t x = 0; x < w; x++) source_position(x, w, window[0], window[2], gm->w, &r->x0[x], &r->fx[x]);
  r->window_y[0] = window[1];
  r->window_y[1] = window[3];
  r->to_pq = (float)(GAINMAP_SDR_WHITE_NITS / 10000.0);
  for (int c = 0; c < 3; c++) {
    r->base_offset[c] = (float)m->base_offset[c];
    r->alternate_offset[c] = (float)m->alternate_offset[c];
  }
  r->meta_channels = m->channels;
  r->per_channel = m->channels == 3 || gm->channels == 3;
  // The renderer takes over both images.
  r->base = *base;
  r->gm = *gm;

  out->w = w;
  out->h = h;
  out->channels = ch;
  out->bytes_per_sample = 2;
  out->bits = 16;
  out->stride = (size_t)w * ch * 2;
  out->owner = r;
  out->owner_free = renderer_free;
  out->render = render;
  // With alpha, the encoder takes the whole image at once.
  if ((ch == 2 || ch == 4) && image_make_packed(out) != 0) {
    memset(&r->base, 0, sizeof r->base);  // back to the caller
    memset(&r->gm, 0, sizeof r->gm);
    renderer_free(r);
    memset(out, 0, sizeof *out);
    return -1;
  }
  memset(base, 0, sizeof *base);
  memset(gm, 0, sizeof *gm);
  return 0;
}
