#include "hdr.h"

#include <jxl/cms.h>
#include <jxl/color_encoding.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int hdr_check(const color_t *color, const gainmap_meta_t *meta, hdr_info_t *hdr) {
  const int primaries = gainmap_srgb_primaries(color);
  if (!primaries) {
    char name[64];
    gainmap_color_name(color, name, sizeof name);
    snprintf(hdr->note, sizeof hdr->note, "unsupported color profile: %s", name);
    return 0;
  }
  if (!meta->use_base_color_space) {
    snprintf(hdr->note, sizeof hdr->note, "gain map in another color space");
    return 0;
  }
  if (!(meta->alternate_headroom > meta->base_headroom)) {
    snprintf(hdr->note, sizeof hdr->note, "the gain map doesn't make the photo brighter");
    return 0;
  }
  return primaries;
}

// 1 if libjxl reads ICC profile `icc` as PQ with D65 white and CICP
// `primaries` (1 or 12): the color of the HDR pixels.
static int profile_is_pq(const uint8_t *icc, size_t size, int primaries) {
  JxlColorEncoding got;
  JXL_BOOL cmyk = JXL_FALSE;
  const JxlCmsInterface *cms = JxlGetDefaultCms();
  if (!cms || !cms->set_fields_from_icc(cms->set_fields_data, icc, size, &got, &cmyk) || cmyk) return 0;
  return got.color_space == JXL_COLOR_SPACE_RGB && got.white_point == JXL_WHITE_POINT_D65 &&
         got.primaries == (primaries == 12 ? JXL_PRIMARIES_P3 : JXL_PRIMARIES_SRGB) &&
         got.transfer_function == JXL_TRANSFER_FUNCTION_PQ;
}

// Apple's HDR profile: the first candidate with Apple's tone curve ('hdgm'
// tag), if libjxl reads it as the HDR pixels' color. Copied into `out`;
// otherwise says why not in `warning`. Without the curve, Apple dims the
// HDR on dimmer screens its standard way, a little darker than the original.
static void keep_hdr_profile(const hdr_parts_t *parts, int primaries, blob_t *out, char *warning, size_t len) {
  for (int i = 0; i < 2; i++) {
    const blob_t icc = {(uint8_t *)parts->profiles[i], parts->profile_sizes[i]};
    if (!icc.size || !gainmap_icc_has_tag(&icc, "hdgm")) continue;
    if (!profile_is_pq(icc.data, icc.size, primaries)) {
      snprintf(warning, len, "Apple's HDR profile not used (unrecognized format); may look slightly darker");
      return;
    }
    out->data = (uint8_t *)malloc(icc.size);
    if (!out->data) return;  // not needed for the pixels
    memcpy(out->data, icc.data, icc.size);
    out->size = icc.size;
    return;
  }
  snprintf(warning, len, "Apple's HDR profile not found; this JXL may look slightly darker");
}

void hdr_apply(image_t *img, color_t *color, int primaries, hdr_parts_t *parts, hdr_info_t *hdr) {
  image_t *gm = &parts->gain_map;
  const double *win = parts->window;
  // The gain map must have the photo's shape (a mismatch would apply the gain
  // to the wrong places).
  if (!gainmap_same_shape(win[2] - win[0], win[3] - win[1], img->w, img->h)) {
    snprintf(hdr->note, sizeof hdr->note, "the gain map doesn't match the photo (%.0fx%.0f, photo %ux%u)",
             win[2] - win[0], win[3] - win[1], img->w, img->h);
    image_free(gm);
    return;
  }
  image_t out;
  if (gainmap_prepare(img, gm, win, parts->gain_map_full_range, &parts->meta, &out) != 0) {
    image_free(gm);
    snprintf(hdr->note, sizeof hdr->note, "not enough memory");
    return;
  }
  *img = out;
  color_free(color);
  color->cicp_present = 1;
  color->cicp[0] = (uint8_t)primaries;
  color->cicp[1] = 16;  // PQ
  color->cicp[2] = 0;
  color->cicp[3] = 1;
  if (parts->meta.apple_headroom <= 0) {
    keep_hdr_profile(parts, primaries, &color->hdr_icc, hdr->warning, sizeof hdr->warning);
  }
  hdr->headroom = exp2(parts->meta.alternate_headroom);
  hdr->peak = gainmap_peak(&parts->meta);
}
