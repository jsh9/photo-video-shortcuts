// HDR photos with a gain map: the SDR image plus the gain map make one HDR
// image, stored as PQ. ISO 21496-1 gain maps (iPhones since iOS 18), and
// Apple's older gain maps (iPhones on iOS 14 to 17), as Apple documents them
// in "Applying Apple HDR effect to your photos" (but with the curve Apple
// renders them with).
#ifndef JXLBATCH_GAINMAP_H
#define JXLBATCH_GAINMAP_H

#include <stddef.h>
#include <stdint.h>

#include "pixels.h"

// SDR white in the PQ result, in nits (ITU-R BT.2408's reference white).
#define GAINMAP_SDR_WHITE_NITS 203.0
// The most a gain map may claim to brighten a photo, in stops (65,536x):
// more is treated as malformed metadata. Real photos are far below (iPhones
// reach about 3 stops; PQ itself ends about 5.6 stops above SDR white).
#define GAINMAP_MAX_STOPS 16.0

// ISO 21496-1 metadata, as stored in a HEIF 'tmap' item.
typedef struct {
  int channels;              // 1, or 3 for one gain per color channel
  int use_base_color_space;  // the gain applies in the SDR image's color space, else in the HDR image's
  // The CICP primaries of the HDR (alternate) image's color space, from the
  // 'tmap' item's color, not its data (set by the decoder); 0 if unknown.
  int alternate_primaries;
  double base_headroom, alternate_headroom;  // log2 of the peak, relative to SDR white
  // Per channel: gains (log2) at gain map values 0 and 1, the gain map's
  // gamma, and offsets added before and removed after applying the gain.
  double min[3], max[3], gamma[3], base_offset[3], alternate_offset[3];
  // > 0: Apple's older gain map, with this headroom (the gain is 1 +
  // (headroom - 1) * value, the value linearized with a gamma of 2.2);
  // the fields above are then unused, except the two headrooms.
  double apple_headroom;
} gainmap_meta_t;

// Parses a 'tmap' item's data. Returns 0, or -1 with the reason in err.
int gainmap_parse(const uint8_t *data, size_t len, gainmap_meta_t *meta, char *err, size_t err_len);
// The metadata of Apple's older gain map, from the photo's maker note tags
// 33 and 48 (exiftool calls them HDRHeadroom and HDRGain).
void gainmap_apple_meta(double maker33, double maker48, gainmap_meta_t *meta);
// The brightest the HDR image can get, relative to SDR white.
double gainmap_peak(const gainmap_meta_t *meta);
// 1 if two sizes have the same aspect ratio, within 5%.
int gainmap_same_shape(double w1, double h1, double w2, double h2);

// The CICP primaries of an image with the sRGB transfer curve, from its ICC
// profile or CICP code points: 1 (sRGB) or 12 (Display P3); 0 for any other
// color space. No color information, or unspecified code points, mean sRGB.
int gainmap_srgb_primaries(const color_t *color);
// A short name for the color, for messages: the ICC profile's description,
// or the CICP code points.
void gainmap_color_name(const color_t *color, char *buf, size_t len);

// Gives the HDR (alternate) image: the gain map applied at full strength.
// `base`: upright RGB or RGBA, 8 to 16 bits, sRGB transfer curve.
// `gain_map`: 1 or 3 channels, 8 to 16 bits, upright; its part `window`
// (x0, y0, x1, y1, in gain map pixels) covers the base and is enlarged to
// the base's size (bilinear). Limited-range values (16-235 for 8 bits) are
// expanded unless `gain_map_full_range`.
// `out` becomes a 16-bit PQ image in the base's primaries, with SDR white at
// GAINMAP_SDR_WHITE_NITS. Its pixels are computed on request (out->render),
// a region at a time, so no 16-bit copy of the whole photo is held; with
// alpha, they are computed at once. `out` takes over `base` and `gain_map`
// (both are emptied). Returns 0, or -1 if out of memory (both left as they
// were).
int gainmap_prepare(image_t *base, image_t *gain_map, const double window[4], int gain_map_full_range,
                    const gainmap_meta_t *meta, image_t *out);

// 1 if an ICC profile has the tag `sig`.
int gainmap_icc_has_tag(const blob_t *icc, const char sig[4]);
// The CICP color primaries in an ICC profile's 'cicp' tag; 0 if it has none.
int gainmap_icc_cicp_primaries(const blob_t *icc);

#endif
