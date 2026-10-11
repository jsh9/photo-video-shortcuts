#include "heicout.h"

#include <libheif/heif.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "heifbox.h"
#include "hevcenc.h"
#ifdef JXLBATCH_THREADS
#include <pthread.h>
#endif

// ---------------------------------------------------------------------------
// Encoding the tiles of a picture

// A 4:2:0 picture (or part of one): planes and strides.
typedef struct {
  const uint8_t *y, *u, *v;
  size_t y_stride, c_stride;
  uint32_t w, h;  // the picture; chroma is (w+1)/2 x (h+1)/2
} planes_t;

typedef struct {
  const planes_t *src;
  uint32_t tile_w, tile_h, cols;
  size_t count;
  double rf;
  hevc_vui_t vui;
  hevc_buf_t *ps, *pic;  // per tile
  size_t next;
  int failed;
  char err[256];
#ifdef JXLBATCH_THREADS
  pthread_mutex_t lock;
#endif
} tiles_t;

// Cuts tile `t` (row by row) out of the picture, the edge replicated past
// the picture, into buf (tile_w x tile_h x 3/2 bytes), and encodes it.
static int encode_tile(tiles_t *job, size_t t, uint8_t *buf, hevc_buf_t *ps, hevc_buf_t *pic, char *err,
                       size_t err_len) {
  const planes_t *s = job->src;
  const uint32_t tw = job->tile_w, th = job->tile_h;
  const uint32_t x0 = (uint32_t)(t % job->cols) * tw, y0 = (uint32_t)(t / job->cols) * th;
  uint8_t *ty = buf, *tu = buf + (size_t)tw * th, *tv = tu + (size_t)(tw / 2) * (th / 2);
  for (uint32_t y = 0; y < th; y++) {
    const uint32_t sy = y0 + y < s->h ? y0 + y : s->h - 1;
    const uint8_t *row = s->y + (size_t)sy * s->y_stride;
    uint8_t *dst = ty + (size_t)y * tw;
    const uint32_t avail = x0 < s->w ? s->w - x0 : 0;
    const uint32_t n = avail < tw ? avail : tw;
    if (n) memcpy(dst, row + x0, n);
    if (n < tw) memset(dst + n, row[s->w - 1], tw - n);
  }
  const uint32_t cw = (s->w + 1) / 2, ch = (s->h + 1) / 2, cx0 = x0 / 2, cy0 = y0 / 2;
  for (int plane = 0; plane < 2; plane++) {
    const uint8_t *sp = plane ? s->v : s->u;
    uint8_t *tp = plane ? tv : tu;
    for (uint32_t y = 0; y < th / 2; y++) {
      const uint32_t sy = cy0 + y < ch ? cy0 + y : ch - 1;
      const uint8_t *row = sp + (size_t)sy * s->c_stride;
      uint8_t *dst = tp + (size_t)y * (tw / 2);
      const uint32_t avail = cx0 < cw ? cw - cx0 : 0;
      const uint32_t n = avail < tw / 2 ? avail : tw / 2;
      if (n) memcpy(dst, row + cx0, n);
      if (n < tw / 2) memset(dst + n, row[cw - 1], tw / 2 - n);
    }
  }
  return hevc_encode(ty, tw, tu, tv, tw / 2, tw, th, job->rf, &job->vui, 1, ps, pic, err, err_len);
}

static void *tile_worker(void *arg) {
  tiles_t *job = (tiles_t *)arg;
  uint8_t *buf = (uint8_t *)malloc((size_t)job->tile_w * job->tile_h * 3 / 2);
  for (;;) {
#ifdef JXLBATCH_THREADS
    pthread_mutex_lock(&job->lock);
#endif
    const size_t t = job->next < job->count && !job->failed ? job->next++ : job->count;
#ifdef JXLBATCH_THREADS
    pthread_mutex_unlock(&job->lock);
#endif
    if (t >= job->count) break;
    char err[256] = "";
    const int rc = buf ? encode_tile(job, t, buf, &job->ps[t], &job->pic[t], err, sizeof err) : -1;
    if (rc != 0) {
#ifdef JXLBATCH_THREADS
      pthread_mutex_lock(&job->lock);
#endif
      if (!job->failed) {
        job->failed = 1;
        snprintf(job->err, sizeof job->err, "%s", buf ? err : "out of memory");
      }
#ifdef JXLBATCH_THREADS
      pthread_mutex_unlock(&job->lock);
#endif
    }
  }
  free(buf);
  return NULL;
}

// Encodes all tiles, on `threads` threads where the build has them. On
// success every tile has its parameter sets and picture, and they all share
// the same parameter sets (checked). Returns 0, or -1 with err.
static int encode_tiles(tiles_t *job, int threads, char *err, size_t err_len) {
  job->ps = (hevc_buf_t *)calloc(job->count, sizeof *job->ps);
  job->pic = (hevc_buf_t *)calloc(job->count, sizeof *job->pic);
  if (!job->ps || !job->pic) {
    snprintf(err, err_len, "out of memory");
    return -1;
  }
  job->next = 0;
  job->failed = 0;
  job->err[0] = 0;
#ifdef JXLBATCH_THREADS
  pthread_mutex_init(&job->lock, NULL);
  int started = 0;
  pthread_t tids[64];
  if (threads > 64) threads = 64;
  if (threads > (int)job->count) threads = (int)job->count;
  for (int i = 1; i < threads; i++) {  // this thread works too
    if (pthread_create(&tids[started], NULL, tile_worker, job) != 0) break;
    started++;
  }
  tile_worker(job);
  for (int i = 0; i < started; i++) pthread_join(tids[i], NULL);
  pthread_mutex_destroy(&job->lock);
#else
  (void)threads;
  tile_worker(job);
#endif
  if (job->failed) {
    snprintf(err, err_len, "%s", job->err);
    return -1;
  }
  for (size_t t = 1; t < job->count; t++) {
    if (job->ps[t].len != job->ps[0].len || memcmp(job->ps[t].data, job->ps[0].data, job->ps[0].len) != 0) {
      snprintf(err, err_len, "x265 wrote different parameter sets for different tiles");
      return -1;
    }
  }
  return 0;
}

static void free_tiles(tiles_t *job) {
  for (size_t t = 0; job->ps && t < job->count; t++) free(job->ps[t].data);
  for (size_t t = 0; job->pic && t < job->count; t++) free(job->pic[t].data);
  free(job->ps);
  free(job->pic);
  job->ps = job->pic = NULL;
}

// ---------------------------------------------------------------------------
// Transcoding a file's tiles

typedef struct {
  uint32_t *ids;
  size_t n, cap;
} idset_t;

static int idset_has(const idset_t *s, uint32_t id) {
  for (size_t i = 0; i < s->n; i++) {
    if (s->ids[i] == id) return 1;
  }
  return 0;
}

static int idset_add(idset_t *s, uint32_t id) {
  if (idset_has(s, id)) return 0;
  if (s->n == s->cap) {
    const size_t cap = s->cap ? s->cap * 2 : 32;
    uint32_t *grown = (uint32_t *)realloc(s->ids, cap * sizeof *grown);
    if (!grown) return -1;
    s->ids = grown;
    s->cap = cap;
  }
  s->ids[s->n++] = id;
  return 0;
}

// Adds an image item and, for a grid, its tiles.
static int keep_image(const hb_file_t *f, idset_t *keep, uint32_t id) {
  if (idset_add(keep, id) != 0) return -1;
  size_t n;
  const uint32_t *tiles = hb_refs_from(f, id, FOURCC('d', 'i', 'm', 'g'), &n);
  for (size_t i = 0; i < n; i++) {
    if (idset_add(keep, tiles[i]) != 0) return -1;
  }
  return 0;
}

// Adds the Exif and XMP ('mime') items describing `id`.
static int keep_metadata(const hb_file_t *f, idset_t *keep, uint32_t id) {
  for (size_t i = 0; i < f->num_items; i++) {
    const hb_item_t *item = &f->items[i];
    if (item->type != FOURCC('E', 'x', 'i', 'f') && item->type != FOURCC('m', 'i', 'm', 'e')) continue;
    if (hb_has_ref(f, item->id, FOURCC('c', 'd', 's', 'c'), id) && idset_add(keep, item->id) != 0) return -1;
  }
  return 0;
}

// 1 if the item is a gain map: an auxiliary image of Apple's
// urn:com:apple:photo:2020:aux:hdrgainmap type.
static int is_gain_map(const hb_file_t *f, uint32_t id) {
  const uint32_t idx = hb_item_property(f, id, FOURCC('a', 'u', 'x', 'C'));
  uint32_t t;
  span_t pl;
  if (!idx || !hb_property(f, idx, &t, &pl) || pl.n < 5) return 0;
  const char *s = (const char *)pl.p + 4;
  const size_t n = pl.n - 4;
  const char *want = "hdrgainmap";
  for (size_t i = 0; i + strlen(want) <= n && s[i]; i++) {
    if (strncmp(s + i, want, strlen(want)) == 0) return 1;
  }
  return 0;
}

// The picture's layout: its tiles (one for an 'hvc1' primary) and geometry.
// Returns 0, or 1 with the reason in note when it isn't a grid of 8-bit
// 4:2:0 HEVC pictures sharing one 'hvcC'.
static int picture_layout(const hb_file_t *f, uint32_t primary, const uint32_t **tiles, size_t *num_tiles,
                          uint32_t *rows, uint32_t *cols, uint32_t *tile_w, uint32_t *tile_h, uint32_t *w,
                          uint32_t *h, uint32_t *hvcc_index, char *note, size_t note_len) {
  const hb_item_t *item = hb_item(f, primary);
  static uint32_t single[1];
  if (item->type == FOURCC('h', 'v', 'c', '1')) {
    single[0] = primary;
    *tiles = single;
    *num_tiles = 1;
    *rows = *cols = 1;
  } else if (item->type == FOURCC('g', 'r', 'i', 'd')) {
    *tiles = hb_refs_from(f, primary, FOURCC('d', 'i', 'm', 'g'), num_tiles);
    size_t n;
    uint8_t *grid = hb_item_data(f, primary, &n);
    if (!grid || n < 8 || grid[0] != 0) {
      free(grid);
      snprintf(note, note_len, "its grid can't be read");
      return 1;
    }
    *rows = (uint32_t)grid[2] + 1;
    *cols = (uint32_t)grid[3] + 1;
    const int wide = grid[1] & 1;
    if (wide && n < 12) {
      free(grid);
      snprintf(note, note_len, "its grid can't be read");
      return 1;
    }
    *w = wide ? rd32be(grid + 4) : rd16be(grid + 4);
    *h = wide ? rd32be(grid + 8) : rd16be(grid + 6);
    free(grid);
    if (!*tiles || *num_tiles != (size_t)*rows * *cols || !*num_tiles) {
      snprintf(note, note_len, "its grid has %zu tiles for %ux%u", *num_tiles, *cols, *rows);
      return 1;
    }
  } else {
    snprintf(note, note_len, "its picture is a '%c%c%c%c' item, not HEVC tiles", (char)(item->type >> 24),
             (char)(item->type >> 16), (char)(item->type >> 8), (char)item->type);
    return 1;
  }
  *hvcc_index = 0;
  for (size_t t = 0; t < *num_tiles; t++) {
    const hb_item_t *tile = hb_item(f, (*tiles)[t]);
    if (!tile || tile->type != FOURCC('h', 'v', 'c', '1')) {
      snprintf(note, note_len, "its tiles aren't all HEVC");
      return 1;
    }
    const uint32_t idx = hb_item_property(f, tile->id, FOURCC('h', 'v', 'c', 'C'));
    if (!idx || (*hvcc_index && idx != *hvcc_index)) {
      snprintf(note, note_len, "its tiles don't share one decoder configuration");
      return 1;
    }
    *hvcc_index = idx;
    if (t == 0) {
      const uint32_t ispe = hb_item_property(f, tile->id, FOURCC('i', 's', 'p', 'e'));
      uint32_t pt;
      span_t pl;
      if (!ispe || !hb_property(f, ispe, &pt, &pl) || pl.n < 12) {
        snprintf(note, note_len, "its tiles have no size");
        return 1;
      }
      *tile_w = rd32be(pl.p + 4);
      *tile_h = rd32be(pl.p + 8);
      if (item->type == FOURCC('h', 'v', 'c', '1')) {
        *w = *tile_w;
        *h = *tile_h;
      }
    }
  }
  for (size_t i = 0; i < f->num_items; i++) {  // the 'hvcC' is the tiles' alone
    int is_tile = 0;
    for (size_t t = 0; t < *num_tiles; t++) is_tile |= (*tiles)[t] == f->items[i].id;
    if (!is_tile && hb_item_property(f, f->items[i].id, FOURCC('h', 'v', 'c', 'C')) == *hvcc_index) {
      snprintf(note, note_len, "its tiles share their decoder configuration with another image");
      return 1;
    }
  }
  uint32_t pt;
  span_t hvcc;
  if (!hb_property(f, *hvcc_index, &pt, &hvcc) || hvcc.n < 23) {
    snprintf(note, note_len, "its decoder configuration can't be read");
    return 1;
  }
  if ((hvcc.p[16] & 3) != 1 || (hvcc.p[17] & 7) != 0 || (hvcc.p[18] & 7) != 0) {
    snprintf(note, note_len, "its HEVC is %s", (hvcc.p[17] & 7) ? "more than 8-bit" : "not 4:2:0");
    return 1;
  }
  if (*tile_w % 2 || *tile_h % 2 || !*tile_w || !*tile_h || *tile_w > 16384 || *tile_h > 16384) {
    snprintf(note, note_len, "its tiles are %ux%u", *tile_w, *tile_h);
    return 1;
  }
  if ((uint64_t)*cols * *tile_w < *w || (uint64_t)*rows * *tile_h < *h || !*w || !*h) {
    snprintf(note, note_len, "its grid doesn't cover the picture");
    return 1;
  }
  return 0;
}

int heic_transcode(const uint8_t *buf, size_t len, const heic_opts_t *opt, const uint8_t *exif, size_t exif_len,
                   uint8_t **out, size_t *out_len, heic_info_t *info, char *err, size_t err_len) {
  *out = NULL;
  *out_len = 0;
  memset(info, 0, sizeof *info);
  hb_file_t f;
  if (hb_parse(buf, len, &f, err, err_len) != 0) return -1;
  int rc = -1;
  const uint32_t *tiles = NULL;
  size_t num_tiles = 0;
  uint32_t rows = 0, cols = 0, tile_w = 0, tile_h = 0, w = 0, h = 0, hvcc_index = 0;
  struct heif_context *ctx = NULL;
  struct heif_image_handle *handle = NULL;
  struct heif_image *image = NULL;
  struct heif_decoding_options *options = NULL;
  struct heif_color_profile_nclx *nclx = NULL;
  tiles_t job;
  memset(&job, 0, sizeof job);
  idset_t keep = {NULL, 0, 0};
  hb_replace_t *replace = NULL;
  uint8_t *hvcc = NULL, *exif_item = NULL;
  size_t hvcc_len = 0;

  if (picture_layout(&f, f.primary, &tiles, &num_tiles, &rows, &cols, &tile_w, &tile_h, &w, &h, &hvcc_index,
                     info->note, sizeof info->note) != 0) {
    rc = 1;
    goto done;
  }
  info->w = w;
  info->h = h;
  {  // for the log, the size as shown: turned by the file's own rotation
    const uint32_t irot = hb_item_property(&f, f.primary, FOURCC('i', 'r', 'o', 't'));
    uint32_t pt;
    span_t pl;
    if (irot && hb_property(&f, irot, &pt, &pl) && pl.n >= 1 && (pl.p[0] & 1)) {
      info->w = h;
      info->h = w;
    }
  }

  // The pixels as stored, YCbCr 4:2:0 (what the tiles hold: no conversion).
  ctx = heif_context_alloc();
  if (!ctx) goto oom;
  struct heif_error e = heif_context_read_from_memory_without_copy(ctx, buf, len, NULL);
  if (e.code != heif_error_Ok) {
    snprintf(err, err_len, "unreadable HEIF (%s)", e.message);
    goto done;
  }
  e = heif_context_get_primary_image_handle(ctx, &handle);
  if (e.code != heif_error_Ok) {
    snprintf(err, err_len, "no primary image in HEIF (%s)", e.message);
    goto done;
  }
  if (heif_image_handle_has_alpha_channel(handle)) {
    snprintf(info->note, sizeof info->note, "it has an alpha channel");
    rc = 1;
    goto done;
  }
  options = heif_decoding_options_alloc();
  if (!options) goto oom;
  options->ignore_transformations = 1;
  e = heif_decode_image(handle, &image, heif_colorspace_YCbCr, heif_chroma_420, options);
  if (e.code != heif_error_Ok) {
    snprintf(err, err_len, "HEIF decoding failed (%s)", e.message);
    goto done;
  }
  planes_t src;
  src.y = heif_image_get_plane_readonly2(image, heif_channel_Y, &src.y_stride);
  src.u = heif_image_get_plane_readonly2(image, heif_channel_Cb, &src.c_stride);
  size_t cr_stride = 0;
  src.v = heif_image_get_plane_readonly2(image, heif_channel_Cr, &cr_stride);
  src.w = (uint32_t)heif_image_get_width(image, heif_channel_Y);
  src.h = (uint32_t)heif_image_get_height(image, heif_channel_Y);
  if (!src.y || !src.u || !src.v || cr_stride != src.c_stride || heif_image_get_bits_per_pixel(image, heif_channel_Y) != 8) {
    snprintf(info->note, sizeof info->note, "it didn't decode to 8-bit 4:2:0");
    rc = 1;
    goto done;
  }
  if (src.w != w || src.h != h) {
    snprintf(err, err_len, "HEIF decoding gave %ux%u for a %ux%u picture", src.w, src.h, w, h);
    goto done;
  }
  // How the samples are to be read. The matrix and range come from the
  // tiles' own SPS, which libheif's decoder reports (an ICC profile can't say
  // them); the primaries and transfer curve from the container's nclx when
  // it has one, else they stay unspecified and the container's ICC profile
  // says (the decoder's report of them isn't reliable: it says unspecified
  // for the camera's Display P3).
  job.vui.primaries = job.vui.transfer = 2;
  job.vui.matrix = 6;
  job.vui.full_range = 1;
  if (heif_image_get_nclx_color_profile(image, &nclx).code == heif_error_Ok && nclx) {
    job.vui.matrix = (uint8_t)nclx->matrix_coefficients;
    job.vui.full_range = nclx->full_range_flag ? 1 : 0;
    heif_nclx_color_profile_free(nclx);
    nclx = NULL;
  }
  if (heif_image_handle_get_nclx_color_profile(handle, &nclx).code == heif_error_Ok && nclx) {
    job.vui.primaries = (uint8_t)nclx->color_primaries;
    job.vui.transfer = (uint8_t)nclx->transfer_characteristics;
  }

  job.src = &src;
  job.tile_w = tile_w;
  job.tile_h = tile_h;
  job.cols = cols;
  job.count = num_tiles;
  job.rf = opt->rf;
  if (encode_tiles(&job, opt->threads, err, err_len) != 0) goto done;
  if (hevc_make_hvcc(&job.ps[0], &hvcc, &hvcc_len) != 0) {
    snprintf(err, err_len, "x265 wrote unusable parameter sets");
    goto done;
  }
  info->tiles = (int)num_tiles;

  // What stays: the picture and its tiles, its thumbnails, its Exif and XMP;
  // the gain map (and its tiles, 'tmap' item, XMP) unless --sdr.
  if (keep_image(&f, &keep, f.primary) != 0 || keep_metadata(&f, &keep, f.primary) != 0) goto oom;
  for (size_t i = 0; i < f.num_items; i++) {
    const uint32_t id = f.items[i].id;
    if (hb_has_ref(&f, id, FOURCC('t', 'h', 'm', 'b'), f.primary)) {
      if (keep_image(&f, &keep, id) != 0) goto oom;
    }
    const int tmap = f.items[i].type == FOURCC('t', 'm', 'a', 'p') &&
                     hb_has_ref(&f, id, FOURCC('d', 'i', 'm', 'g'), f.primary);
    if (tmap || is_gain_map(&f, id)) {
      info->had_gain_map = 1;
      if (opt->sdr) continue;
      if (keep_image(&f, &keep, id) != 0 || keep_metadata(&f, &keep, id) != 0) goto oom;
      if (tmap) {  // the gain map it is derived from, with its tiles
        size_t n;
        const uint32_t *in = hb_refs_from(&f, id, FOURCC('d', 'i', 'm', 'g'), &n);
        for (size_t k = 0; k < n; k++) {
          if (keep_image(&f, &keep, in[k]) != 0 || keep_metadata(&f, &keep, in[k]) != 0) goto oom;
        }
      }
      info->kept_gain_map = 1;
    }
  }

  // The new data: every tile, and the Exif when a new one is given.
  replace = (hb_replace_t *)calloc(num_tiles + 1, sizeof *replace);
  if (!replace) goto oom;
  for (size_t t = 0; t < num_tiles; t++) {
    replace[t].id = tiles[t];
    replace[t].data = job.pic[t].data;
    replace[t].len = job.pic[t].len;
  }
  size_t num_replace = num_tiles;
  if (exif) {
    for (size_t i = 0; i < f.num_items; i++) {
      const uint32_t id = f.items[i].id;
      if (f.items[i].type == FOURCC('E', 'x', 'i', 'f') && idset_has(&keep, id)) {
        exif_item = (uint8_t *)malloc(4 + exif_len);
        if (!exif_item) goto oom;
        memset(exif_item, 0, 4);  // the TIFF header follows at once
        memcpy(exif_item + 4, exif, exif_len);
        replace[num_replace].id = id;
        replace[num_replace].data = exif_item;
        replace[num_replace].len = 4 + exif_len;
        num_replace++;
        break;
      }
    }
  }
  hb_rewrite_t rw = {keep.ids, keep.n, replace, num_replace, hvcc_index, hvcc, hvcc_len};
  if (hb_rewrite(&f, &rw, out, out_len) != 0) goto oom;
  rc = 0;
  goto done;
oom:
  snprintf(err, err_len, "out of memory");
done:
  free(exif_item);
  free(replace);
  free(keep.ids);
  free(hvcc);
  free_tiles(&job);
  if (nclx) heif_nclx_color_profile_free(nclx);
  if (image) heif_image_release(image);
  heif_decoding_options_free(options);
  if (handle) heif_image_handle_release(handle);
  if (ctx) heif_context_free(ctx);
  hb_free(&f);
  return rc;
}

// ---------------------------------------------------------------------------
// A new file from pixels

#define NEW_TILE 512

static uint8_t clamp8(double v) { return v < 0 ? 0 : v > 255 ? 255 : (uint8_t)(v + 0.5); }

int heic_from_pixels(const image_t *img, const color_t *color, const uint8_t *exif, size_t exif_len,
                     const heic_opts_t *opt, uint8_t **out, size_t *out_len, heic_info_t *info, char *err,
                     size_t err_len) {
  *out = NULL;
  *out_len = 0;
  memset(info, 0, sizeof *info);
  if (!img->data || img->bytes_per_sample != 1 || !img->w || !img->h) {
    snprintf(err, err_len, "HEIC output needs 8-bit pixels");
    return -1;
  }
  const uint32_t w = img->w, h = img->h;
  info->w = w;
  info->h = h;
  // YCbCr 4:2:0, BT.601 full range (as Apple's camera files), the picture
  // padded to even sizes by its edge; chroma from the mean of each 2x2.
  const uint32_t w2 = (w + 1) & ~1u, h2 = (h + 1) & ~1u, cw = w2 / 2, ch = h2 / 2;
  uint8_t *y = (uint8_t *)malloc((size_t)w2 * h2), *u = (uint8_t *)malloc((size_t)cw * ch);
  uint8_t *v = (uint8_t *)malloc((size_t)cw * ch);
  double *cb = (double *)calloc((size_t)cw * ch, sizeof *cb), *cr = (double *)calloc((size_t)cw * ch, sizeof *cr);
  int rc = -1;
  tiles_t job;
  memset(&job, 0, sizeof job);
  uint8_t *hvcc = NULL;
  size_t hvcc_len = 0;
  if (!y || !u || !v || !cb || !cr) goto oom;
  const int ch_in = img->channels;
  for (uint32_t yy = 0; yy < h2; yy++) {
    const uint8_t *row = img->data + (size_t)(yy < h ? yy : h - 1) * img->stride;
    for (uint32_t xx = 0; xx < w2; xx++) {
      const uint8_t *px = row + (size_t)(xx < w ? xx : w - 1) * ch_in;
      const double r = px[0], g = ch_in >= 3 ? px[1] : px[0], b = ch_in >= 3 ? px[2] : px[0];
      const double luma = 0.299 * r + 0.587 * g + 0.114 * b;
      y[(size_t)yy * w2 + xx] = clamp8(luma);
      const size_t c = (size_t)(yy / 2) * cw + xx / 2;
      cb[c] += (b - luma) / 1.772 / 4;
      cr[c] += (r - luma) / 1.402 / 4;
    }
  }
  for (size_t c = 0; c < (size_t)cw * ch; c++) {
    u[c] = clamp8(cb[c] + 128);
    v[c] = clamp8(cr[c] + 128);
  }
  free(cb);
  free(cr);
  cb = cr = NULL;

  planes_t src = {y, u, v, w2, cw, w2, h2};
  // 512-pixel tiles, or one tile the size of a smaller picture (rounded up
  // to a multiple of 8, and to x265's smallest picture, 16).
  uint32_t tile_w = w2 < NEW_TILE ? (w2 + 7) & ~7u : NEW_TILE, tile_h = h2 < NEW_TILE ? (h2 + 7) & ~7u : NEW_TILE;
  if (tile_w < 16) tile_w = 16;
  if (tile_h < 16) tile_h = 16;
  job.src = &src;
  job.tile_w = tile_w;
  job.tile_h = tile_h;
  job.cols = (w2 + tile_w - 1) / tile_w;
  const uint32_t rows = (h2 + tile_h - 1) / tile_h;
  job.count = (size_t)rows * job.cols;
  job.rf = opt->rf;
  job.vui.matrix = 6;
  job.vui.full_range = 1;
  if (color->cicp_present) {
    job.vui.primaries = color->cicp[0];
    job.vui.transfer = color->cicp[1];
  } else if (color->icc.size) {
    job.vui.primaries = job.vui.transfer = 2;  // the profile says
  } else {
    job.vui.primaries = 1;  // sRGB
    job.vui.transfer = 13;
  }
  if (encode_tiles(&job, opt->threads, err, err_len) != 0) goto done;
  if (hevc_make_hvcc(&job.ps[0], &hvcc, &hvcc_len) != 0) {
    snprintf(err, err_len, "x265 wrote unusable parameter sets");
    goto done;
  }
  info->tiles = (int)job.count;
  hb_new_t n;
  memset(&n, 0, sizeof n);
  n.w = w;
  n.h = h;
  n.tile_w = tile_w;
  n.tile_h = tile_h;
  n.rows = rows;
  n.cols = job.cols;
  n.tiles = job.pic;
  n.hvcc = hvcc;
  n.hvcc_len = hvcc_len;
  n.icc = color->icc.size ? color->icc.data : NULL;
  n.icc_len = color->icc.size;
  n.nclx = job.vui;
  n.exif = exif;
  n.exif_len = exif_len;
  if (hb_write_new(&n, out, out_len) != 0) goto oom;
  rc = 0;
  goto done;
oom:
  snprintf(err, err_len, "out of memory");
done:
  free(hvcc);
  free_tiles(&job);
  free(y);
  free(u);
  free(v);
  free(cb);
  free(cr);
  return rc;
}
