// HEIC output: a photo re-encoded with x265 (hevcenc.h), either by replacing
// the HEVC tiles of its own file (heic_transcode: the gain map, thumbnail
// and metadata stay as they are) or written from its pixels as an SDR HEIC
// (heic_from_pixels).
#ifndef JXLBATCH_HEICOUT_H
#define JXLBATCH_HEICOUT_H

#include <stddef.h>
#include <stdint.h>

#include "pixels.h"

typedef struct {
  double rf;    // x265 CRF
  int sdr;      // drop the gain map (heic_transcode)
  int threads;  // tiles encoded at a time (1: on the calling thread)
} heic_opts_t;

typedef struct {
  uint32_t w, h;      // the picture as stored
  int tiles;          // pictures encoded
  int had_gain_map;   // the file had one (heic_transcode)
  int kept_gain_map;  // and the output has it
  char note[160];     // heic_transcode's reason for 1: why this file can't be transcoded
} heic_info_t;

// Re-encodes the base picture of a HEIF whose primary image is an HEVC
// picture or a grid of them, 8-bit 4:2:0, into the file's own container:
// every tile decoded as stored and encoded again at `rf`; the gain map
// (ISO 21496-1 'tmap' or Apple's older auxiliary image) with its tiles,
// the thumbnail, the Exif and XMP items stay byte for byte unless `sdr`
// drops the gain map; other auxiliary images (Apple's Photographic Styles
// data, mattes) are dropped. `exif`, if given, replaces the Exif item (TIFF
// data). Returns 0 with the malloc'ed file, 1 if this file can't be
// transcoded (info->note says why; heic_from_pixels can still convert it),
// or -1 with the reason in err.
int heic_transcode(const uint8_t *buf, size_t len, const heic_opts_t *opt, const uint8_t *exif, size_t exif_len,
                   uint8_t **out, size_t *out_len, heic_info_t *info, char *err, size_t err_len);

// Writes a new SDR HEIC from `img` (8-bit, 3 channels, stored pixels; an
// alpha channel is dropped, gray expanded) with its color (an ICC profile,
// else CICP, else sRGB) and the Exif (TIFF data, or NULL), as a grid of
// 512-pixel HEVC tiles. Returns 0, or -1 with the reason in err.
int heic_from_pixels(const image_t *img, const color_t *color, const uint8_t *exif, size_t exif_len,
                     const heic_opts_t *opt, uint8_t **out, size_t *out_len, heic_info_t *info, char *err,
                     size_t err_len);

#endif
