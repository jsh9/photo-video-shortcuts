// JPEG XL input, with libjxl's decoder: the metadata boxes (EXIF, XMP) and
// the pixels, upright, in the file's own color space. Also the conversions
// between libjxl's color encodings and CICP code points, which the encoder
// (photobatch.c) shares.
#ifndef JXLBATCH_JXL_H
#define JXLBATCH_JXL_H

#include <stddef.h>
#include <stdint.h>

#include <jxl/color_encoding.h>

#include "meta.h"
#include "pixels.h"

// The first Exif box (as raw TIFF, without the box's 4-byte offset) and the
// first "xml " box of a JPEG XL file into `m`, Brotli-compressed ("brob")
// ones too. Returns 0 (also for a bare codestream, which has no boxes), or
// -1 with a message when a metadata box can't be read: cut short, not
// decompressible, or over 64 MiB.
int jxl_boxes(const uint8_t *buf, size_t len, meta_t *m, char *err, size_t err_len);

// The picture of a JPEG XL file, upright (the codestream's orientation
// applied; the EXIF's doesn't count in a JPEG XL), 8-bit, or 16-bit when the
// file has more than 8 bits or is HDR. `color` gets the CICP code points of
// the file's color space when it has some, else its ICC profile; an HDR
// (PQ) picture described by an ICC profile with a 'cicp' tag, as this tool's
// HDR copies are (Apple's HDR profile), gets the code points and the profile
// as `color->hdr_icc`. An HDR picture (PQ or HLG) stays HDR, with `hdr`'s
// headroom and peak from the file's intensity target, unless `sdr`: then
// libjxl tone-maps it to SDR, 8-bit with the sRGB curve in the same
// primaries, and `hdr->tone_mapped` says so. `runner`, if not NULL, is a
// libjxl thread pool (JxlThreadParallelRunner). `transposed`, if given, is
// set to 1 when the codestream's orientation turned the picture by a quarter
// turn. Animated and floating-point files are refused.
int jxl_decode(const uint8_t *buf, size_t len, int sdr, void *runner, image_t *img, color_t *color,
               hdr_info_t *hdr, int *transposed, char *err, size_t err_len);

// CICP code points (primaries, transfer, matrix 0, full range) to libjxl's
// color encoding, and back. Both return 1, or 0 when one can't express the
// other (other primaries, white points or curves, a matrix, gray).
int jxl_color_from_cicp(const uint8_t cicp[4], JxlColorEncoding *c);
int jxl_cicp_from_color(const JxlColorEncoding *c, uint8_t cicp[4]);

#endif
