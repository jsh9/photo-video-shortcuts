// HDR photos: what to do with a gain map a decoder found, whatever the file
// format. The decoder finds and decodes the parts (gainmap.h has the math);
// these functions decide whether they can be used, say why not in
// hdr_info_t's note, and turn the SDR photo into its HDR rendition.
#ifndef JXLBATCH_HDR_H
#define JXLBATCH_HDR_H

#include <stddef.h>
#include <stdint.h>

#include "gainmap.h"
#include "pixels.h"

// A gain map photo's parts, as the decoder found them.
typedef struct {
  gainmap_meta_t meta;
  image_t gain_map;  // aligned with the upright photo
  int gain_map_full_range;
  // Candidates for the HDR rendition's ICC profile, in order of preference
  // (e.g. on the 'tmap' item, then on the gain map), pointing into the file.
  const uint8_t *profiles[2];
  size_t profile_sizes[2];
} hdr_parts_t;

// Checks the photo's color and the gain map's metadata, before the gain map
// is decoded. Returns the CICP primaries of the HDR result (1 or 12), or 0
// with the reason in hdr->note.
int hdr_check(const color_t *color, const gainmap_meta_t *meta, hdr_info_t *hdr);

// Replaces `img`, the upright SDR photo, with its HDR rendition (16-bit PQ,
// computed on request; see gainmap_prepare) and `color` with its color:
// PQ in `primaries` by CICP, and Apple's HDR profile when the photo has one
// that describes those pixels (with the tone curve Apple uses on screens
// that can't show all of the HDR). Takes over parts->gain_map. If the gain
// map can't be used, leaves both, with the reason in hdr->note.
void hdr_apply(image_t *img, color_t *color, int primaries, hdr_parts_t *parts, hdr_info_t *hdr);

#endif
