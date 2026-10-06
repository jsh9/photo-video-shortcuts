// Grain for HDR (PQ) outputs, so that smooth gradients don't band.
//
// Apple renders a PQ JPEG XL for an SDR screen through an 8-bit PQ step,
// which gives a sky about half the levels an SDR photo has, and lossy
// encoding removes most of the fine grain that would dither those steps (see
// docs/compress-photos-banding-plan.md). So a little grain is put back into
// the pixels, in smooth areas only, before encoding: textured areas hide the
// steps anyway, and grain there would only cost bytes.
#ifndef JXLBATCH_GRAIN_H
#define JXLBATCH_GRAIN_H

#include <stdint.h>

#include "pixels.h"

typedef struct {
  // The grain's strength, as the standard deviation of what is added, in
  // percent of one 8-bit PQ step (257 of 65535), at full strength (a smooth
  // area). Two layers: `fine` is noise per pixel, which hides the steps when
  // the photo is viewed near its full size; `coarse` is noise drawn on a grid
  // 4 pixels apart and interpolated, which survives a lossy encode and a
  // viewer's downscaling (a phone's screen shows a 24 MP photo at a fifth of
  // its size) and so hides the steps there. 0 = none.
  int fine, coarse;
} grain_opts_t;

// The default amounts for a quality (more at lower qualities, which remove
// more of it).
grain_opts_t grain_auto(float quality);

// Makes `img`, an HDR image computed on request (img->render, from
// gainmap_prepare), add grain to the pixels it renders: in each 16 x 16
// cell of the photo, with a weight from 1 (the cell's SDR picture is smooth:
// neighbouring pixels differ by less than about 1 level of 255) down to 0
// (they differ by about 2.5 levels or more: texture, or grain of its own),
// feathered between cells. The same value goes to R, G and B (luma grain,
// no colour speckle), each value a hash of its position, so nothing is
// stored and the output is reproducible.
// Returns 0, 1 if `img` is not such an image (left alone; e.g. one with
// alpha, computed at once), or -1 if out of memory (left alone).
int grain_attach(image_t *img, const grain_opts_t *opts);

#endif
