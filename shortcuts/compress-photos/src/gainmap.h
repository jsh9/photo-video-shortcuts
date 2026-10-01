// HDR photos with an ISO 21496-1 gain map (iPhones since iOS 18): the SDR
// image plus the gain map make one HDR image, stored as PQ.
#ifndef JXLBATCH_GAINMAP_H
#define JXLBATCH_GAINMAP_H

#include <stddef.h>
#include <stdint.h>

#include "pixels.h"

// SDR white in the PQ result, in nits (ITU-R BT.2408's reference white).
#define GAINMAP_SDR_WHITE_NITS 203.0

// ISO 21496-1 metadata, as stored in a HEIF 'tmap' item.
typedef struct {
  int channels;              // 1, or 3 for one gain per color channel
  int use_base_color_space;  // the gain applies in the SDR image's color space
  double base_headroom, alternate_headroom;  // log2 of the peak, relative to SDR white
  // Per channel: gains (log2) at gain map values 0 and 1, the gain map's
  // gamma, and offsets added before and removed after applying the gain.
  double min[3], max[3], gamma[3], base_offset[3], alternate_offset[3];
} gainmap_meta_t;

// Parses a 'tmap' item's data. Returns 0, or -1 with the reason in err.
int gainmap_parse(const uint8_t *data, size_t len, gainmap_meta_t *meta, char *err, size_t err_len);

// The CICP primaries of an image with the sRGB transfer curve, from its ICC
// profile or CICP code points: 1 (sRGB) or 12 (Display P3); 0 for any other
// color space.
int gainmap_srgb_primaries(const color_t *color);
// A short name for the color, for messages: the ICC profile's description,
// or the CICP code points.
void gainmap_color_name(const color_t *color, char *buf, size_t len);

// Applies the gain map at full strength, giving the HDR (alternate) image.
// `base`: upright RGB or RGBA, 8 to 16 bits, sRGB transfer curve.
// `gain_map`: 1 or 3 channels, 8 to 16 bits, aligned with `base`; it is
// enlarged to the base's size (bilinear). Limited-range values (16-235 for
// 8 bits) are expanded unless `gain_map_full_range`.
// `out` gets a 16-bit PQ image in the base's primaries, with SDR white at
// GAINMAP_SDR_WHITE_NITS, computed row by row. Returns 0, or -1 if out of
// memory.
int gainmap_apply(const image_t *base, const image_t *gain_map, int gain_map_full_range,
                  const gainmap_meta_t *meta, image_t *out);

#endif
