#include "grain.h"

#include <stdlib.h>

#include "gainmap.h"

#define CELL 16  // the smoothness mask's cell size, in pixels
#define CELL_SHIFT 4
#define NOISE_SIGMA 37    // of a grid value: the sum of four uniform values in [-32, 31]
#define SMOOTH_MAD 256    // mean absolute neighbour difference (x256, in levels of 255): full grain below
#define TEXTURED_MAD 640  // ... none above (2.5 levels)
#define PQ8_STEP 257      // one 8-bit PQ step, in 16-bit codes

// A layer of noise: values with a bell-shaped distribution on a grid of
// points 1 << shift pixels apart, each computed from its position (hashed),
// so that nothing is stored.
typedef struct {
  int shift;
  uint32_t seed;
  int32_t sigma;  // the layer's standard deviation at full weight, in 16-bit codes; 0 = no layer
} grid_t;

// An HDR image whose rendered regions get grain.
typedef struct {
  image_t inner;    // the image from gainmap_prepare (its render and owner)
  uint8_t *weight;  // per cell, 0 (textured) to 255 (smooth)
  uint32_t cw, ch;  // cells across and down
  grid_t fine, coarse;
} grained_t;

grain_opts_t grain_auto(float quality) {
  // From the tuning on a sunset skyline (docs/compress-photos-banding-plan.md,
  // package C): lower qualities remove more of the grain, so they get more;
  // the file grows by about 10-15% at each quality. The user chose the
  // lightest of the candidates whose banding looked the same (60+40 at q83);
  // the coarse layer is 2/3 of the fine one.
  grain_opts_t g;
  float fine = 60.0f + (83.0f - quality) * 2.0f;
  if (fine < 40.0f) fine = 40.0f;
  if (fine > 130.0f) fine = 130.0f;
  g.fine = (int)(fine + 0.5f);
  g.coarse = g.fine * 2 / 3;
  return g;
}

// A bell-shaped value in [-128, 124] for a grid point: four uniform values
// in [0, 63] from a hash of its position, minus 128.
static int32_t noise_point(uint32_t seed, uint32_t gx, uint32_t gy) {
  uint32_t h = seed ^ (gx * 0x9E3779B1u) ^ (gy * 0x85EBCA77u);
  h ^= h >> 16;
  h *= 0x7FEB352Du;
  h ^= h >> 15;
  h *= 0x846CA68Bu;
  h ^= h >> 16;
  return (int32_t)(h & 63) + (int32_t)((h >> 6) & 63) + (int32_t)((h >> 12) & 63) + (int32_t)((h >> 18) & 63) - 128;
}

// The smoothness of each cell of the SDR picture: the mean absolute
// difference between horizontal and vertical neighbours of its green
// channel (close to luma), in levels of 255 (x256), turned into a weight.
static int make_weights(grained_t *g, const image_t *base) {
  g->cw = (base->w + CELL - 1) / CELL;
  g->ch = (base->h + CELL - 1) / CELL;
  g->weight = (uint8_t *)malloc((size_t)g->cw * g->ch);
  if (!g->weight) return -1;
  const int ch = base->channels, gc = ch >= 3 ? 1 : 0;
  const uint32_t max = (1u << base->bits) - 1;
  for (uint32_t cy = 0; cy < g->ch; cy++) {
    for (uint32_t cx = 0; cx < g->cw; cx++) {
      const uint32_t x0 = cx * CELL, y0 = cy * CELL;
      const uint32_t x1 = x0 + CELL < base->w ? x0 + CELL : base->w;
      const uint32_t y1 = y0 + CELL < base->h ? y0 + CELL : base->h;
      uint64_t sum = 0, n = 0;
      for (uint32_t y = y0; y < y1; y++) {
        const uint8_t *row8 = base->data + (size_t)y * base->stride;
        const uint16_t *row16 = (const uint16_t *)row8;
        // the row below, only while there is one (no pointer past the buffer)
        const uint8_t *next8 = y + 1 < y1 ? row8 + base->stride : row8;
        const uint16_t *next16 = (const uint16_t *)next8;
        for (uint32_t x = x0; x < x1; x++) {
          const size_t i = (size_t)x * ch + gc;
          const int32_t v = base->bytes_per_sample == 1 ? row8[i] : row16[i];
          if (x + 1 < x1) {
            const int32_t r = base->bytes_per_sample == 1 ? row8[i + ch] : row16[i + ch];
            sum += (uint64_t)(v > r ? v - r : r - v);
            n++;
          }
          if (y + 1 < y1) {
            const int32_t d = base->bytes_per_sample == 1 ? next8[i] : next16[i];
            sum += (uint64_t)(v > d ? v - d : d - v);
            n++;
          }
        }
      }
      // mean difference in levels of 255, x256
      const uint64_t mad = n ? sum * 255 * 256 / (n * max) : 0;
      int w;
      if (mad <= SMOOTH_MAD) {
        w = 255;
      } else if (mad >= TEXTURED_MAD) {
        w = 0;
      } else {
        w = (int)((TEXTURED_MAD - mad) * 255 / (TEXTURED_MAD - SMOOTH_MAD));
      }
      g->weight[(size_t)cy * g->cw + cx] = (uint8_t)w;
    }
  }
  return 0;
}

static void make_grid(grid_t *g, int shift, int amount, uint32_t seed) {
  g->shift = shift;
  g->seed = seed;
  g->sigma = amount > 0 ? (int32_t)((int64_t)amount * PQ8_STEP / 100) : 0;
}

// The layer's noise at a pixel, interpolated between its grid points (x256).
static int32_t noise_at(const grid_t *g, uint32_t x, uint32_t y) {
  if (!g->sigma) return 0;
  const uint32_t gx = x >> g->shift, gy = y >> g->shift;
  if (!g->shift) return noise_point(g->seed, gx, gy) * 256;
  const uint32_t span = 1u << g->shift, fx = (x & (span - 1)) * 256 / span, fy = (y & (span - 1)) * 256 / span;
  const int32_t top = noise_point(g->seed, gx, gy) * (int32_t)(256 - fx) + noise_point(g->seed, gx + 1, gy) * (int32_t)fx;
  const int32_t bottom =
      noise_point(g->seed, gx, gy + 1) * (int32_t)(256 - fx) + noise_point(g->seed, gx + 1, gy + 1) * (int32_t)fx;
  return (top * (int32_t)(256 - fy) + bottom * (int32_t)fy) >> 8;
}

// What both layers add at a pixel at full weight, in 16-bit codes (x256).
static int64_t grain_at(const grained_t *g, uint32_t x, uint32_t y) {
  return ((int64_t)noise_at(&g->fine, x, y) * g->fine.sigma + (int64_t)noise_at(&g->coarse, x, y) * g->coarse.sigma) /
         NOISE_SIGMA;
}

// The weight at a pixel, 0 to 255, interpolated between the cells' centres.
static int32_t weight_at(const grained_t *g, uint32_t x, uint32_t y) {
  // The cells' centres are at CELL/2 + k * CELL. Measured from CELL/2 before
  // the first one (no negative numbers to shift), a pixel lies between the
  // centres of cells k - 1 and k, clamped to the cells there are.
  const uint32_t ux = x + CELL / 2, uy = y + CELL / 2;
  const uint32_t fx = (ux % CELL) * 256 / CELL, fy = (uy % CELL) * 256 / CELL;
  const uint32_t kx = ux / CELL, ky = uy / CELL;
  const uint32_t cx0 = kx ? kx - 1 : 0, cy0 = ky ? ky - 1 : 0;
  const uint32_t cx1 = kx < g->cw ? kx : g->cw - 1, cy1 = ky < g->ch ? ky : g->ch - 1;
  const uint8_t *w = g->weight;
  const uint32_t top = w[(size_t)cy0 * g->cw + cx0] * (256 - fx) + w[(size_t)cy0 * g->cw + cx1] * fx;
  const uint32_t bottom = w[(size_t)cy1 * g->cw + cx0] * (256 - fx) + w[(size_t)cy1 * g->cw + cx1] * fx;
  return (int32_t)((top * (256 - fy) + bottom * fy) >> 16);
}

static int render_grained(void *owner, uint32_t x, uint32_t y, uint32_t w, uint32_t h, uint8_t *out,
                          size_t stride) {
  const grained_t *g = (const grained_t *)owner;
  const int rc = g->inner.render(g->inner.owner, x, y, w, h, out, stride);
  if (rc != 0) return rc;
  const int ch = g->inner.channels;
  for (uint32_t yy = 0; yy < h; yy++) {
    uint16_t *row = (uint16_t *)(out + (size_t)yy * stride);
    for (uint32_t xx = 0; xx < w; xx++) {
      const int32_t wgt = weight_at(g, x + xx, y + yy);
      if (!wgt) continue;
      // grain (x256) * weight (0..255) / (256 * 255)
      const int64_t delta = grain_at(g, x + xx, y + yy) * wgt / (256 * 255);
      uint16_t *px = row + (size_t)xx * ch;
      for (int c = 0; c < 3; c++) {
        int32_t v = (int32_t)px[c] + (int32_t)delta;
        px[c] = (uint16_t)(v < 0 ? 0 : v > 65535 ? 65535 : v);
      }
    }
  }
  return 0;
}

static void grained_free(void *owner) {
  grained_t *g = (grained_t *)owner;
  if (!g) return;
  image_free(&g->inner);
  free(g->weight);
  free(g);
}

int grain_attach(image_t *img, const grain_opts_t *opts) {
  if (!opts || (opts->fine <= 0 && opts->coarse <= 0)) return 1;
  const image_t *base = gainmap_base(img);
  if (!img->render || !base || img->channels < 3 || img->bytes_per_sample != 2) return 1;
  grained_t *g = (grained_t *)calloc(1, sizeof *g);
  if (!g) return -1;
  if (make_weights(g, base) != 0) {
    free(g);
    return -1;
  }
  make_grid(&g->fine, 0, opts->fine, 0x9E3779B9u);
  make_grid(&g->coarse, 2, opts->coarse, 0x7F4A7C15u);
  g->inner = *img;
  img->owner = g;
  img->owner_free = grained_free;
  img->render = render_grained;
  return 0;
}
