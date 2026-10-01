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

// Finds the 'tmap' item derived from `primary` and its gain map. libheif
// doesn't read 'tmap' items itself. Returns 1 if found, 0 if there is none,
// -1 if its metadata can't be used (reason in note).
static int find_gain_map(struct heif_context *ctx, heif_item_id primary, heif_item_id *gain_map,
                         gainmap_meta_t *meta, char *note, size_t note_len) {
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

// Applies `item`'s rotation and mirroring to `img`, as libheif applies them
// to that item's own pixels. Returns -1 if it has other transformations.
static int apply_transformations(struct heif_context *ctx, heif_item_id item, image_t *img) {
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
      if (d == heif_transform_mirror_direction_invalid) return -1;
      orientation = d == heif_transform_mirror_direction_horizontal ? 2 : 4;
    } else {
      return -1;  // a crop ('clap')
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
  // The gain map is stored like the primary image (its own rotation, if any,
  // isn't the photo's), so it is decoded as stored and turned with the
  // primary's rotation and mirroring below.
  options = heif_decoding_options_alloc();
  options->ignore_transformations = 1;
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
  if (apply_transformations(ctx, heif_image_handle_get_item_id(primary), gm) != 0) {
    snprintf(note, note_len, "the photo is cropped");
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
static void apply_gain_map(struct heif_context *ctx, struct heif_image_handle *primary, image_t *img,
                           color_t *color, hdr_info_t *hdr) {
  gainmap_meta_t meta;
  heif_item_id gain_map_id = 0;
  char *note = hdr->note;
  const size_t note_len = sizeof hdr->note;
  const int found = find_gain_map(ctx, heif_image_handle_get_item_id(primary), &gain_map_id, &meta, note,
                                  note_len);
  if (found <= 0) return;
  const int primaries = gainmap_srgb_primaries(color);
  if (!primaries) {
    snprintf(note, note_len, "unsupported color profile");
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
  if (hdr) apply_gain_map(ctx, handle, img, color, hdr);
  rc = 0;

done:
  if (rc != 0) color_free(color);
  heif_decoding_options_free(options);
  if (image) heif_image_release(image);
  if (handle) heif_image_handle_release(handle);
  heif_context_free(ctx);
  return rc;
}
