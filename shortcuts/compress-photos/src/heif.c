// HEIF/HEIC decoding through libheif (HEVC via libde265).
#include <libheif/heif.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "pixels.h"

void heif_decoder_version(char *buf, size_t len) { snprintf(buf, len, "libheif %s", heif_get_version()); }

static void release_heif_image(void *owner) { heif_image_release((struct heif_image *)owner); }

int heif_decode(const uint8_t *buf, size_t len, image_t *img, color_t *color, char *err, size_t err_len) {
  memset(img, 0, sizeof *img);
  memset(color, 0, sizeof *color);
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
  rc = 0;

done:
  if (rc != 0) color_free(color);
  heif_decoding_options_free(options);
  if (image) heif_image_release(image);
  if (handle) heif_image_handle_release(handle);
  heif_context_free(ctx);
  return rc;
}
