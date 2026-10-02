// HEIF/HEIC decoding through libheif (HEVC via libde265), including the parts
// of an HDR photo with a gain map (see hdr.h): ISO 21496-1, or Apple's older
// format.
#include <libheif/heif.h>
#include <libheif/heif_items.h>
#include <libheif/heif_properties.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gainmap.h"
#include "hdr.h"
#include "meta.h"
#include "pixels.h"

void heif_decoder_version(char *buf, size_t len) { snprintf(buf, len, "libheif %s", heif_get_version()); }

static void release_heif_image(void *owner) { heif_image_release((struct heif_image *)owner); }

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

// Apple's older gain map (photos taken before iOS 18): an auxiliary image of
// `primary` of this type. ISO 21496-1 gain maps in Apple's photos have it too.
#define APPLE_GAIN_MAP "urn:com:apple:photo:2020:aux:hdrgainmap"

// 1 if `from` has a reference of `type` to `to` (alone).
static int refers_to(struct heif_context *ctx, heif_item_id from, uint32_t type, heif_item_id to) {
  int found = 0;
  for (int r = 0; !found; r++) {
    uint32_t t = 0;
    heif_item_id *ids = NULL;
    const size_t k = heif_context_get_item_references(ctx, from, r, &t, &ids);
    found = k == 1 && t == type && ids[0] == to;
    heif_release_item_references(ctx, &ids);
    if (k == 0) break;
  }
  return found;
}

// Finds Apple's older gain map of `primary`. Returns its ID, 0 if none.
static heif_item_id find_older_gain_map(struct heif_context *ctx, const uint8_t *buf, size_t len,
                                        heif_item_id primary) {
  const int n = heif_context_get_number_of_items(ctx);
  heif_item_id *ids = n > 0 ? (heif_item_id *)malloc((size_t)n * sizeof *ids) : NULL;
  if (!ids) return 0;
  const int count = heif_context_get_list_of_item_IDs(ctx, ids, n);
  heif_item_id found = 0;
  for (int i = 0; i < count && !found; i++) {
    if (ids[i] != primary && heif_item_has_aux_type(buf, len, ids[i], APPLE_GAIN_MAP) &&
        refers_to(ctx, ids[i], heif_fourcc('a', 'u', 'x', 'l'), primary)) {
      found = ids[i];
    }
  }
  free(ids);
  return found;
}

// The headroom of Apple's older gain map, from the photo's maker notes (tags
// 33 and 48). Returns 1 if found.
static int older_gain_map_meta(struct heif_image_handle *primary, gainmap_meta_t *meta) {
  heif_item_id ids[4];
  const int n = heif_image_handle_get_list_of_metadata_block_IDs(primary, "Exif", ids, 4);
  int found = 0;
  for (int i = 0; i < n && !found; i++) {
    const size_t size = heif_image_handle_get_metadata_size(primary, ids[i]);
    uint8_t *data = size > 4 ? (uint8_t *)malloc(size) : NULL;
    if (data && heif_image_handle_get_metadata(primary, ids[i], data).code == heif_error_Ok) {
      // a 4-byte offset to the TIFF header, counted from byte 4
      const uint32_t offset = (uint32_t)data[0] << 24 | (uint32_t)data[1] << 16 | (uint32_t)data[2] << 8 | data[3];
      double headroom = 0, gain = 0;
      if (offset < size - 4 && exif_apple_hdr(data + 4 + offset, size - 4 - offset, &headroom, &gain)) {
        gainmap_apple_meta(headroom, gain, meta);
        found = 1;
      }
    }
    free(data);
  }
  return found;
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

// The EXIF orientation that rotates or mirrors like property `prop` ('irot'
// or 'imir'); 0 for other properties.
static int transform_orientation(struct heif_context *ctx, heif_item_id item, heif_property_id prop) {
  const uint32_t type = (uint32_t)heif_item_get_property_type(ctx, item, prop);
  if (type == heif_fourcc('i', 'r', 'o', 't')) {
    const int ccw = heif_item_get_property_transform_rotation_ccw(ctx, item, prop);
    return ccw == 90 ? 8 : ccw == 180 ? 3 : ccw == 270 ? 6 : 0;
  }
  if (type == heif_fourcc('i', 'm', 'i', 'r')) {
    const enum heif_transform_mirror_direction d = heif_item_get_property_transform_mirror(ctx, item, prop);
    return d == heif_transform_mirror_direction_horizontal ? 2 : d == heif_transform_mirror_direction_vertical ? 4 : 0;
  }
  return 0;
}

// Turns `win` (x0, y0, x1, y1, in the pixels of a w x h image) the way EXIF
// orientation `o` (2, 3, 4, 6 or 8) turns the image (see image_orient).
static void orient_window(double *win, double w, double h, int o) {
  const double x0 = win[0], y0 = win[1], x1 = win[2], y1 = win[3];
  double out[4] = {x0, y0, x1, y1};
  if (o == 2 || o == 3) out[0] = w - x1, out[2] = w - x0;
  if (o == 3 || o == 4) out[1] = h - y1, out[3] = h - y0;
  if (o == 6) out[0] = h - y1, out[1] = x0, out[2] = h - y0, out[3] = x1;
  if (o == 8) out[0] = y0, out[1] = w - x1, out[2] = y1, out[3] = w - x0;
  memcpy(win, out, sizeof out);
}

// Applies the transforms of image item `item` (w x h pixels as stored), in
// the file's order: crops ('clap', cut to the image as libheif does),
// rotations and mirrors. They apply to `img` if given, and to `gm` if given:
// a gain map stored like the item, whose part covering it, `win`, a crop
// narrows. Returns 0; -1 if out of memory; -2 if a crop leaves nothing
// (libheif then refuses to decode the image).
static int apply_transforms(struct heif_context *ctx, heif_item_id item, int w, int h, image_t *img, image_t *gm,
                            double *win) {
  heif_property_id props[16];
  const int n = heif_item_get_transformation_properties(ctx, item, props, 16);
  for (int i = 0; i < n; i++) {
    if ((uint32_t)heif_item_get_property_type(ctx, item, props[i]) == heif_fourcc('c', 'l', 'a', 'p')) {
      int left = 0, top = 0, right = 0, bottom = 0;
      heif_item_get_property_transform_crop_borders(ctx, item, props[i], w, h, &left, &top, &right, &bottom);
      // negative: the crop reaches past that edge
      left = left > 0 ? left : 0;
      top = top > 0 ? top : 0;
      right = right > 0 ? right : 0;
      bottom = bottom > 0 ? bottom : 0;
      if (left + right >= w || top + bottom >= h) return -2;
      if (img) {
        image_crop(img, (uint32_t)left, (uint32_t)top, (uint32_t)(w - left - right), (uint32_t)(h - top - bottom));
      }
      if (gm) {
        const double sx = (win[2] - win[0]) / w, sy = (win[3] - win[1]) / h;
        win[0] += left * sx;
        win[2] -= right * sx;
        win[1] += top * sy;
        win[3] -= bottom * sy;
      }
      w -= left + right;
      h -= top + bottom;
      continue;
    }
    const int o = transform_orientation(ctx, item, props[i]);
    if (!o) continue;
    if (img && image_orient(img, o) != 0) return -1;
    if (gm) {
      orient_window(win, gm->w, gm->h, o);
      if (image_orient(gm, o) != 0) return -1;
    }
    if (o == 6 || o == 8) {
      const int t = w;
      w = h;
      h = t;
    }
  }
  return 0;
}

// 1 if no image that `item` is derived from (at any depth) has transforms of
// its own, so that `item`'s are the only ones. Then it can be decoded as
// stored and its transforms applied by jxlbatch: libheif's
// ignore_transformations also skips those of the images it is derived from.
static int only_own_transforms(struct heif_context *ctx, heif_item_id item, int depth) {
  if (depth > 8) return 0;
  int ok = 1;
  for (int r = 0; ok; r++) {
    uint32_t type = 0;
    heif_item_id *to = NULL;
    const size_t k = heif_context_get_item_references(ctx, item, r, &type, &to);
    for (size_t i = 0; i < k && ok && type == heif_fourcc('d', 'i', 'm', 'g'); i++) {
      heif_property_id props[1];
      ok = heif_item_get_transformation_properties(ctx, to[i], props, 1) == 0 &&
           only_own_transforms(ctx, to[i], depth + 1);
    }
    heif_release_item_references(ctx, &to);
    if (k == 0) break;
  }
  return ok;
}

// 1 if the photo's transparency (alpha) images, if any, have no transforms of
// their own (nor the images they are derived from). libheif turns an alpha
// image by its own transforms, which ignore_transformations skips too.
static int alpha_is_plain(struct heif_context *ctx, const uint8_t *buf, size_t len, heif_item_id photo) {
  // the alpha types libheif recognizes
  static const char *kAlpha[] = {"urn:mpeg:mpegB:cicp:systems:auxiliary:alpha", "urn:mpeg:hevc:2015:auxid:1",
                                 "urn:mpeg:avc:2015:auxid:1"};
  const int n = heif_context_get_number_of_items(ctx);
  heif_item_id *ids = n > 0 ? (heif_item_id *)malloc((size_t)n * sizeof *ids) : NULL;
  if (!ids) return 0;  // libheif applies all transforms
  const int count = heif_context_get_list_of_item_IDs(ctx, ids, n);
  int plain = 1;
  for (int i = 0; i < count && plain; i++) {
    if (ids[i] == photo || !refers_to(ctx, ids[i], heif_fourcc('a', 'u', 'x', 'l'), photo)) continue;
    int alpha = 0;
    for (size_t k = 0; k < sizeof kAlpha / sizeof kAlpha[0]; k++) {
      alpha |= heif_item_has_aux_type(buf, len, ids[i], kAlpha[k]);
    }
    heif_property_id props[1];
    plain = !alpha || (heif_item_get_transformation_properties(ctx, ids[i], props, 1) == 0 &&
                       only_own_transforms(ctx, ids[i], 0));
  }
  free(ids);
  return plain;
}

// Decodes the gain map, upright, and the part of it that covers the upright
// photo.
static int decode_gain_map(struct heif_context *ctx, struct heif_image_handle *primary, heif_item_id id,
                           hdr_parts_t *parts, char *note, size_t note_len) {
  image_t *gm = &parts->gain_map;
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
  // As stored: either its own transforms or the primary's are applied below.
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
  parts->gain_map_full_range = 1;
  struct heif_color_profile_nclx *nclx = NULL;
  if (mono && heif_image_get_nclx_color_profile(image, &nclx).code == heif_error_Ok && nclx) {
    parts->gain_map_full_range = nclx->full_range_flag != 0;
  }
  heif_nclx_color_profile_free(nclx);
  image = NULL;
  // Apple stores its gain maps like the primary image, without its
  // transforms ('irot' 0, and a full-size gain map gets the primary's crop
  // but not its rotation): the primary's transforms, crop included, apply.
  // A gain map turned itself has its own. Either way, one set applies.
  struct heif_image_handle *owner = is_turned(ctx, id) ? handle : primary;
  parts->window[0] = parts->window[1] = 0;
  parts->window[2] = gm->w;
  parts->window[3] = gm->h;
  const int t = apply_transforms(ctx, heif_image_handle_get_item_id(owner), heif_image_handle_get_ispe_width(owner),
                                 heif_image_handle_get_ispe_height(owner), NULL, gm, parts->window);
  if (t != 0) {
    snprintf(note, note_len, t == -2 ? "unsupported image layout" : "not enough memory");
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

// Replaces the decoded SDR image with its HDR rendition when the file has a
// gain map (see hdr.h): an ISO 21496-1 one, or else Apple's older one.
// Otherwise leaves it, with a note if the gain map can't be used.
static void apply_gain_map(struct heif_context *ctx, const uint8_t *buf, size_t len, int sdr, int own_transforms,
                           struct heif_image_handle *primary, image_t *img, color_t *color, hdr_info_t *hdr) {
  hdr_parts_t parts;
  memset(&parts, 0, sizeof parts);
  const heif_item_id primary_id = heif_image_handle_get_item_id(primary);
  heif_item_id tmap_id = 0, gain_map_id = 0;
  const int iso = find_gain_map(ctx, primary_id, &tmap_id, &gain_map_id, &parts.meta, hdr->note, sizeof hdr->note);
  if (iso == 0) gain_map_id = find_older_gain_map(ctx, buf, len, primary_id);
  if (iso == 0 && !gain_map_id) return;
  hdr->has_gain_map = 1;
  // Only Apple's gain maps, as iPhones label them (their auxiliary image
  // type), are known to line up with the photo as below. Others aren't
  // guessed at: the photo stays SDR, and its original may still be deleted
  // (the owner's choice), whatever else is wrong with it.
  if (!heif_item_has_aux_type(buf, len, gain_map_id, APPLE_GAIN_MAP)) {
    snprintf(hdr->note, sizeof hdr->note, "not an iPhone camera photo");
    hdr->not_iphone = 1;
  }
  if (sdr) {  // asked for SDR: nothing to say
    hdr->note[0] = 0;
    return;
  }
  if (iso < 0 || hdr->not_iphone) return;
  // Lining the gain map up with the photo needs the transforms of both, so
  // each must have only its own (e.g. not be derived from a turned image).
  if (!own_transforms || !only_own_transforms(ctx, gain_map_id, 0)) {
    snprintf(hdr->note, sizeof hdr->note, "unsupported image layout");
    return;
  }
  if (iso == 0 && !older_gain_map_meta(primary, &parts.meta)) {
    snprintf(hdr->note, sizeof hdr->note, "Apple's older gain map without its headroom");
    return;
  }
  const int primaries = hdr_check(color, &parts.meta, hdr);
  if (!primaries || decode_gain_map(ctx, primary, gain_map_id, &parts, hdr->note, sizeof hdr->note) != 0) {
    return;
  }
  // Apple's HDR profile: ISO 21496-1 puts it on the 'tmap' item; it is looked
  // for on the gain map too, which carries it in a JPEG.
  if (tmap_id) {
    parts.profile_sizes[0] = heif_item_profile(buf, len, tmap_id, &parts.profiles[0]);
    parts.profile_sizes[1] = heif_item_profile(buf, len, gain_map_id, &parts.profiles[1]);
  }
  hdr_apply(img, color, primaries, &parts, hdr);
}

int heif_decode(const uint8_t *buf, size_t len, int sdr, image_t *img, color_t *color, hdr_info_t *hdr, char *err,
                size_t err_len) {
  memset(img, 0, sizeof *img);
  memset(color, 0, sizeof *color);
  memset(hdr, 0, sizeof *hdr);
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

  // As stored, and apply_transforms turns it upright; unless an image it is
  // derived from, or its transparency image, has transforms too, which
  // libheif then applies (all of them).
  const heif_item_id photo = heif_image_handle_get_item_id(handle);
  const int own_transforms = only_own_transforms(ctx, photo, 0) && alpha_is_plain(ctx, buf, len, photo);
  options = heif_decoding_options_alloc();
  options->ignore_transformations = own_transforms;
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
  const int t = own_transforms ? apply_transforms(ctx, photo, (int)img->w, (int)img->h, img, NULL, NULL) : 0;
  if (t != 0) {
    snprintf(err, err_len, t == -2 ? "HEIF decoding failed (invalid crop)" : "out of memory");
    goto done;
  }
  apply_gain_map(ctx, buf, len, sdr, own_transforms, handle, img, color, hdr);
  rc = 0;

done:
  if (rc != 0) {
    image_free(img);
    color_free(color);
  }
  heif_decoding_options_free(options);
  if (image) heif_image_release(image);
  if (handle) heif_image_handle_release(handle);
  heif_context_free(ctx);
  return rc;
}
