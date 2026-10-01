// HEIF/HEIC decoding through libheif (HEVC via libde265), including HDR
// photos with an ISO 21496-1 gain map (see gainmap.h).
#include <libheif/heif.h>
#include <libheif/heif_items.h>
#include <libheif/heif_properties.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gainmap.h"
#include "pixels.h"

void heif_decoder_version(char *buf, size_t len) { snprintf(buf, len, "libheif %s", heif_get_version()); }

static void release_heif_image(void *owner) { heif_image_release((struct heif_image *)owner); }

static uint32_t be16(const uint8_t *p) { return (uint32_t)p[0] << 8 | p[1]; }
static uint32_t be32(const uint8_t *p) { return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3]; }

// One box in [*p, end): its type and payload. Moves *p past it; returns 0 at
// the end or if the box is malformed.
typedef struct {
  uint32_t type;
  const uint8_t *data;
  size_t size;
} box_t;

static int next_box(const uint8_t **p, const uint8_t *end, box_t *box) {
  const size_t left = (size_t)(end - *p);
  if (left < 8) return 0;
  uint64_t size = be32(*p);
  size_t header = 8;
  box->type = be32(*p + 4);
  if (size == 1) {  // 64-bit size
    if (left < 16) return 0;
    size = (uint64_t)be32(*p + 8) << 32 | be32(*p + 12);
    header = 16;
  } else if (size == 0) {  // up to the end
    size = left;
  }
  if (size < header || size > left) return 0;
  box->data = *p + header;
  box->size = (size_t)size - header;
  *p += size;
  return 1;
}

static int find_box(const uint8_t *data, size_t size, uint32_t type, box_t *box) {
  const uint8_t *p = data;
  while (next_box(&p, data + size, box)) {
    if (box->type == type) return 1;
  }
  return 0;
}

// The ICC profile in property `index` (from 1) of 'ipco', if that is a 'colr'
// with one. Returns its size, 0 if it isn't one.
static size_t ipco_icc(const box_t *ipco, uint32_t index, const uint8_t **icc) {
  const uint8_t *p = ipco->data;
  box_t prop;
  if (index == 0) return 0;  // no property
  for (uint32_t i = 1; next_box(&p, ipco->data + ipco->size, &prop); i++) {
    if (i < index) continue;
    if (prop.type != heif_fourcc('c', 'o', 'l', 'r') || prop.size < 4) return 0;
    const uint32_t kind = be32(prop.data);
    if (kind != heif_fourcc('p', 'r', 'o', 'f') && kind != heif_fourcc('r', 'I', 'C', 'C')) return 0;
    *icc = prop.data + 4;
    return prop.size - 4;
  }
  return 0;
}

// The ICC profile of `item`, read from the file's item properties: libheif
// gives the profiles of images only, not of the 'tmap' item. Returns its size
// (0 if it has none), with *icc pointing into buf.
static size_t item_icc(const uint8_t *buf, size_t len, heif_item_id item, const uint8_t **icc) {
  box_t meta, iprp, ipco, ipma;
  if (!find_box(buf, len, heif_fourcc('m', 'e', 't', 'a'), &meta) || meta.size < 4 ||
      !find_box(meta.data + 4, meta.size - 4, heif_fourcc('i', 'p', 'r', 'p'), &iprp) ||
      !find_box(iprp.data, iprp.size, heif_fourcc('i', 'p', 'c', 'o'), &ipco)) {
    return 0;
  }
  const uint8_t *p = iprp.data;
  while (next_box(&p, iprp.data + iprp.size, &ipma)) {
    if (ipma.type != heif_fourcc('i', 'p', 'm', 'a') || ipma.size < 8) continue;
    const size_t id_size = ipma.data[0] == 0 ? 2 : 4;  // by version
    const size_t index_size = ipma.data[3] & 1 ? 2 : 1;  // by flags
    const uint8_t *q = ipma.data + 8, *end = ipma.data + ipma.size;
    for (uint32_t n = be32(ipma.data + 4); n > 0 && (size_t)(end - q) > id_size; n--) {
      const uint32_t id = id_size == 2 ? be16(q) : be32(q);
      const size_t count = q[id_size];
      q += id_size + 1;
      if ((size_t)(end - q) < count * index_size) break;
      for (size_t i = 0; id == item && i < count; i++) {
        const uint32_t index = index_size == 2 ? be16(q + 2 * i) & 0x7fff : q[i] & 0x7fu;
        const size_t size = ipco_icc(&ipco, index, icc);
        if (size) return size;
      }
      q += count * index_size;
    }
  }
  return 0;
}

// 1 if an ICC profile has Apple's HDR tone-mapping curve, its 'hdgm' tag.
static int has_tone_curve(const uint8_t *icc, size_t size) {
  if (size < 132) return 0;
  const uint32_t n = be32(icc + 128);
  if (n > (size - 132) / 12) return 0;
  for (uint32_t i = 0; i < n; i++) {
    if (be32(icc + 132 + 12 * i) == heif_fourcc('h', 'd', 'g', 'm')) return 1;
  }
  return 0;
}

// Copies Apple's profile for the HDR rendition into color->hdr_icc, if the
// photo has one: Display P3 with PQ, plus the curve Apple derived from the
// gain map, which it tone-maps the HDR with on screens that can't show all of
// it. ISO 21496-1 puts it on the 'tmap' item; it is looked for on the gain map
// too, which carries it in a JPEG.
static void keep_hdr_profile(const uint8_t *buf, size_t len, heif_item_id tmap, heif_item_id gain_map,
                             color_t *color) {
  const heif_item_id items[] = {tmap, gain_map};
  for (int i = 0; i < 2; i++) {
    const uint8_t *icc = NULL;
    const size_t size = item_icc(buf, len, items[i], &icc);
    if (!size || !has_tone_curve(icc, size)) continue;
    color->hdr_icc.data = (uint8_t *)malloc(size);
    if (!color->hdr_icc.data) return;  // not needed for the pixels
    memcpy(color->hdr_icc.data, icc, size);
    color->hdr_icc.size = size;
    return;
  }
}

// Finds the 'tmap' item derived from `primary` and its gain map. libheif
// doesn't read 'tmap' items itself. Returns 1 if found, 0 if there is none,
// -1 if its metadata can't be used (reason in note).
static int find_gain_map(struct heif_context *ctx, heif_item_id primary, heif_item_id *tmap_id,
                         heif_item_id *gain_map, gainmap_meta_t *meta, char *note, size_t note_len) {
  const int n = heif_context_get_number_of_items(ctx);
  heif_item_id *ids = n > 0 ? (heif_item_id *)malloc((size_t)n * sizeof *ids) : NULL;
  if (!ids) return 0;
  const int count = heif_context_get_list_of_item_IDs(ctx, ids, n);
  heif_item_id tmap = 0;
  for (int i = 0; i < count && !tmap; i++) {
    if (heif_item_get_item_type(ctx, ids[i]) != heif_fourcc('t', 'm', 'a', 'p')) continue;
    for (int r = 0; !tmap; r++) {
      uint32_t type = 0;
      heif_item_id *to = NULL;
      // Its inputs: the SDR image, then the gain map.
      const size_t k = heif_context_get_item_references(ctx, ids[i], r, &type, &to);
      if (k == 2 && type == heif_fourcc('d', 'i', 'm', 'g') && to[0] == primary) {
        tmap = ids[i];
        *gain_map = to[1];
      }
      heif_release_item_references(ctx, &to);
      if (k == 0) break;
    }
  }
  free(ids);
  if (!tmap) return 0;
  *tmap_id = tmap;
  uint8_t *data = NULL;
  size_t size = 0;
  int rc = -1;
  if (heif_item_get_item_data(ctx, tmap, NULL, &data, &size).code != heif_error_Ok) {
    snprintf(note, note_len, "unreadable gain map metadata");
  } else if (gainmap_parse(data, size, meta, note, note_len) == 0) {
    rc = 1;
  }
  heif_release_item_data(ctx, &data);
  return rc;
}

// 1 if `item` is rotated or mirrored ('irot' other than 0, or 'imir').
static int is_turned(struct heif_context *ctx, heif_item_id item) {
  heif_property_id props[16];
  const int n = heif_item_get_transformation_properties(ctx, item, props, 16);
  for (int i = 0; i < n; i++) {
    const uint32_t type = (uint32_t)heif_item_get_property_type(ctx, item, props[i]);
    if (type == heif_fourcc('i', 'm', 'i', 'r')) return 1;
    if (type == heif_fourcc('i', 'r', 'o', 't') &&
        heif_item_get_property_transform_rotation_ccw(ctx, item, props[i]) != 0) {
      return 1;
    }
  }
  return 0;
}

// Applies `item`'s rotation and mirroring (not its crop) to `img`, as
// libheif applies them to that item's own pixels. Returns -1 if out of memory.
static int apply_rotation(struct heif_context *ctx, heif_item_id item, image_t *img) {
  heif_property_id props[16];
  const int n = heif_item_get_transformation_properties(ctx, item, props, 16);
  for (int i = 0; i < n; i++) {
    int orientation;  // the EXIF orientation that does the same
    const uint32_t type = (uint32_t)heif_item_get_property_type(ctx, item, props[i]);
    if (type == heif_fourcc('i', 'r', 'o', 't')) {
      const int ccw = heif_item_get_property_transform_rotation_ccw(ctx, item, props[i]);
      orientation = ccw == 90 ? 8 : ccw == 180 ? 3 : ccw == 270 ? 6 : 1;
    } else if (type == heif_fourcc('i', 'm', 'i', 'r')) {
      const enum heif_transform_mirror_direction d = heif_item_get_property_transform_mirror(ctx, item, props[i]);
      if (d == heif_transform_mirror_direction_invalid) continue;
      orientation = d == heif_transform_mirror_direction_horizontal ? 2 : 4;
    } else {
      continue;  // a crop ('clap'): the gain map is scaled to the photo anyway
    }
    if (image_orient(img, orientation) != 0) return -1;
  }
  return 0;
}

// Decodes the gain map, aligned with the upright primary image.
static int decode_gain_map(struct heif_context *ctx, struct heif_image_handle *primary, heif_item_id id,
                           image_t *gm, int *full_range, char *note, size_t note_len) {
  struct heif_image_handle *handle = NULL;
  struct heif_image *image = NULL;
  struct heif_decoding_options *options = NULL;
  int rc = -1;
  memset(gm, 0, sizeof *gm);
  if (heif_context_get_image_handle(ctx, id, &handle).code != heif_error_Ok) {
    snprintf(note, note_len, "unreadable gain map");
    return -1;
  }
  enum heif_colorspace space = heif_colorspace_undefined;
  enum heif_chroma chroma = heif_chroma_undefined;
  heif_image_handle_get_preferred_decoding_colorspace(handle, &space, &chroma);
  const int mono = space == heif_colorspace_monochrome;
  const int wide = heif_image_handle_get_luma_bits_per_pixel(handle) > 8;
  options = heif_decoding_options_alloc();
  struct heif_error e =
      mono ? heif_decode_image(handle, &image, heif_colorspace_monochrome, heif_chroma_monochrome, options)
           : heif_decode_image(handle, &image, heif_colorspace_RGB,
                               wide ? heif_chroma_interleaved_RRGGBB_LE : heif_chroma_interleaved_RGB, options);
  if (e.code != heif_error_Ok) {
    snprintf(note, note_len, "gain map decoding failed (%s)", e.message);
    goto done;
  }
  const enum heif_channel channel = mono ? heif_channel_Y : heif_channel_interleaved;
  size_t stride = 0;
  const uint8_t *plane = heif_image_get_plane_readonly2(image, channel, &stride);
  if (!plane) {
    snprintf(note, note_len, "gain map decoding returned no pixels");
    goto done;
  }
  gm->data = (uint8_t *)plane;
  gm->w = (uint32_t)heif_image_get_width(image, channel);
  gm->h = (uint32_t)heif_image_get_height(image, channel);
  gm->stride = stride;
  gm->channels = mono ? 1 : 3;
  gm->bits = heif_image_get_bits_per_pixel_range(image, channel);
  gm->bytes_per_sample = gm->bits > 8 ? 2 : 1;
  gm->owner = image;
  gm->owner_free = release_heif_image;
  // Monochrome values are as coded: full or limited range, as signaled by
  // the colr box or else the HEVC stream. RGB comes out full range.
  *full_range = 1;
  struct heif_color_profile_nclx *nclx = NULL;
  if (mono && heif_image_get_nclx_color_profile(image, &nclx).code == heif_error_Ok && nclx) {
    *full_range = nclx->full_range_flag != 0;
  }
  heif_nclx_color_profile_free(nclx);
  image = NULL;
  // Apple stores the gain map like the primary image, without turning it
  // (ImageIO writes 'irot' 0): the primary's rotation and mirroring apply.
  if (!is_turned(ctx, id) && apply_rotation(ctx, heif_image_handle_get_item_id(primary), gm) != 0) {
    snprintf(note, note_len, "not enough memory");
    goto done;
  }
  rc = 0;

done:
  if (rc != 0) image_free(gm);
  if (image) heif_image_release(image);
  heif_decoding_options_free(options);
  heif_image_handle_release(handle);
  return rc;
}

// Replaces the decoded SDR image with its HDR rendition when the file has an
// ISO 21496-1 gain map. Otherwise leaves it, with a note if the gain map
// can't be used.
static void apply_gain_map(struct heif_context *ctx, const uint8_t *buf, size_t len,
                           struct heif_image_handle *primary, image_t *img, color_t *color, hdr_info_t *hdr) {
  gainmap_meta_t meta;
  heif_item_id tmap_id = 0, gain_map_id = 0;
  char *note = hdr->note;
  const size_t note_len = sizeof hdr->note;
  const int found = find_gain_map(ctx, heif_image_handle_get_item_id(primary), &tmap_id, &gain_map_id, &meta,
                                  note, note_len);
  if (found <= 0) return;
  const int primaries = gainmap_srgb_primaries(color);
  if (!primaries) {
    char name[64];
    gainmap_color_name(color, name, sizeof name);
    snprintf(note, note_len, "unsupported color profile: %s", name);
    return;
  }
  if (!meta.use_base_color_space) {
    snprintf(note, note_len, "gain map in another color space");
    return;
  }
  if (!(meta.alternate_headroom > meta.base_headroom)) {
    snprintf(note, note_len, "the gain map doesn't make the photo brighter");
    return;
  }
  image_t gm;
  int full_range = 1;
  if (decode_gain_map(ctx, primary, gain_map_id, &gm, &full_range, note, note_len) != 0) return;
  // After rotation, the gain map must have the photo's shape (a mismatch
  // would apply the gain to the wrong places).
  const double aspect = (double)img->w / img->h, gm_aspect = (double)gm.w / gm.h;
  if (fabs(gm_aspect / aspect - 1) > 0.05) {
    snprintf(note, note_len, "the gain map doesn't match the photo (%ux%u, photo %ux%u)", gm.w, gm.h, img->w,
             img->h);
    image_free(&gm);
    return;
  }
  image_t out;
  const int rc = gainmap_apply(img, &gm, full_range, &meta, &out);
  image_free(&gm);
  if (rc != 0) {
    snprintf(note, note_len, "not enough memory");
    return;
  }
  image_free(img);
  *img = out;
  color_free(color);
  color->cicp_present = 1;
  color->cicp[0] = (uint8_t)primaries;
  color->cicp[1] = 16;  // PQ
  color->cicp[2] = 0;
  color->cicp[3] = 1;
  keep_hdr_profile(buf, len, tmap_id, gain_map_id, color);
  hdr->headroom = exp2(meta.alternate_headroom);
}

int heif_decode(const uint8_t *buf, size_t len, image_t *img, color_t *color, hdr_info_t *hdr, char *err,
                size_t err_len) {
  memset(img, 0, sizeof *img);
  memset(color, 0, sizeof *color);
  if (hdr) memset(hdr, 0, sizeof *hdr);
  struct heif_context *ctx = heif_context_alloc();
  struct heif_image_handle *handle = NULL;
  struct heif_image *image = NULL;
  struct heif_decoding_options *options = NULL;
  int rc = -1;
  if (!ctx) {
    snprintf(err, err_len, "out of memory");
    return -1;
  }
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

  const int alpha = heif_image_handle_has_alpha_channel(handle);
  int bits = heif_image_handle_get_luma_bits_per_pixel(handle);
  if (bits < 8) bits = 8;
  const int wide = bits > 8;  // 10- or 12-bit HEIF: keep the precision
  const enum heif_chroma chroma =
      wide ? (alpha ? heif_chroma_interleaved_RRGGBBAA_LE : heif_chroma_interleaved_RRGGBB_LE)
           : (alpha ? heif_chroma_interleaved_RGBA : heif_chroma_interleaved_RGB);

  // Color of the decoded RGB: the ICC profile if the file has one, else nclx.
  const size_t icc_size = heif_image_handle_get_raw_color_profile_size(handle);
  if (icc_size > 0) {
    color->icc.data = (uint8_t *)malloc(icc_size);
    if (color->icc.data && heif_image_handle_get_raw_color_profile(handle, color->icc.data).code == heif_error_Ok) {
      color->icc.size = icc_size;
    } else {
      free(color->icc.data);
      color->icc.data = NULL;
    }
  }
  if (!color->icc.size) {
    struct heif_color_profile_nclx *nclx = NULL;
    if (heif_image_handle_get_nclx_color_profile(handle, &nclx).code == heif_error_Ok && nclx) {
      color->cicp_present = 1;
      color->cicp[0] = (uint8_t)nclx->color_primaries;
      color->cicp[1] = (uint8_t)nclx->transfer_characteristics;
      color->cicp[2] = 0;  // decoded to RGB
      color->cicp[3] = 1;
      heif_nclx_color_profile_free(nclx);
    }
  }

  // Default options apply the HEIF rotation/mirroring, so pixels come out upright.
  options = heif_decoding_options_alloc();
  e = heif_decode_image(handle, &image, heif_colorspace_RGB, chroma, options);
  if (e.code != heif_error_Ok) {
    snprintf(err, err_len, "HEIF decoding failed (%s)", e.message);
    goto done;
  }
  size_t stride = 0;
  const uint8_t *plane = heif_image_get_plane_readonly2(image, heif_channel_interleaved, &stride);
  if (!plane) {
    snprintf(err, err_len, "HEIF decoding returned no pixels");
    goto done;
  }
  img->data = (uint8_t *)plane;
  img->w = (uint32_t)heif_image_get_width(image, heif_channel_interleaved);
  img->h = (uint32_t)heif_image_get_height(image, heif_channel_interleaved);
  img->stride = stride;
  img->channels = alpha ? 4 : 3;
  img->bytes_per_sample = wide ? 2 : 1;
  img->bits = wide ? bits : 8;
  img->owner = image;  // the decoded image outlives the context
  img->owner_free = release_heif_image;
  image = NULL;
  if (hdr) apply_gain_map(ctx, buf, len, handle, img, color, hdr);
  rc = 0;

done:
  if (rc != 0) color_free(color);
  heif_decoding_options_free(options);
  if (image) heif_image_release(image);
  if (handle) heif_image_handle_release(handle);
  heif_context_free(ctx);
  return rc;
}
