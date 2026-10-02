// Image decoding (HEIF via libheif; JPEG and PNG via stb_image) and pixel
// transforms (alpha removal, EXIF orientation).
#ifndef JXLBATCH_PIXELS_H
#define JXLBATCH_PIXELS_H

#include <stddef.h>
#include <stdint.h>

#include "meta.h"

typedef struct {
  uint8_t *data;  // interleaved samples, native-endian for 16-bit
  uint32_t w, h;
  size_t stride;         // bytes per row
  int channels;          // 1 = gray, 2 = gray+alpha, 3 = RGB, 4 = RGBA
  int bytes_per_sample;  // 1 or 2
  int bits;              // significant bits per sample: 8, 10, 12 or 16
  void *owner;           // decoder object owning `data`, or NULL if malloc'ed
  void (*owner_free)(void *owner);
  // Pixels computed on request instead of stored (`data` is NULL): writes
  // the w x h region at (x, y) to `out`, rows `stride` bytes apart. `owner`
  // is its state. Returns 0, or -1 if out of memory.
  int (*render)(void *owner, uint32_t x, uint32_t y, uint32_t w, uint32_t h, uint8_t *out, size_t stride);
} image_t;

// Color of the decoded pixels: an ICC profile, else CICP code points, else sRGB.
typedef struct {
  blob_t icc;
  int cicp_present;
  uint8_t cicp[4];  // primaries, transfer, matrix (0 = RGB), full-range flag
  // HDR photos (PQ, by CICP): Apple's profile for the same color space, if the
  // photo has one, with the curve Apple tone-maps the HDR with on dimmer screens.
  blob_t hdr_icc;
} color_t;

// What heif_decode did with an HDR gain map.
typedef struct {
  double headroom;  // > 0: the image is HDR, peaking at this many times SDR white
  char note[128];  // why the photo's gain map wasn't used, if it wasn't
} hdr_info_t;

// JPEG or PNG. Pixels are as stored (EXIF orientation not applied).
int stb_decode(const uint8_t *buf, size_t len, image_t *img, char *err, size_t err_len);
// HEIF/HEIC primary image, upright (irot/imir applied), with its color. A
// photo with an ISO 21496-1 gain map becomes HDR: 16-bit PQ with SDR white
// at 203 nits, computed on request (see hdr.h); `hdr` says so, or why not.
int heif_decode(const uint8_t *buf, size_t len, image_t *img, color_t *color, hdr_info_t *hdr, char *err,
                size_t err_len);
void heif_decoder_version(char *buf, size_t len);

void image_free(image_t *img);
void color_free(color_t *color);
size_t pixel_size(const image_t *img);  // bytes per pixel

// Turns a decoder-owned, padded or rendered image into a packed, malloc'ed
// one. Returns 0, or -1 if out of memory.
int image_make_packed(image_t *img);
// Removes the alpha channel when every pixel is fully opaque. Returns 1 if removed.
int image_drop_opaque_alpha(image_t *img);
// Applies EXIF orientation `o` (2..8) so the pixels become upright.
// Returns 0 on success (or when o is 1/unknown), -1 on allocation failure.
int image_orient(image_t *img, int o);

#endif
