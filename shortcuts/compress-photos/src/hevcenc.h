// HEVC encoding of one picture with x265, for HEIC output (heicout.h): each
// tile of a HEIC is one intra picture. Only in builds with JXLBATCH_HEIC;
// the others report that HEIC output isn't available.
#ifndef JXLBATCH_HEVCENC_H
#define JXLBATCH_HEVCENC_H

#include <stddef.h>
#include <stdint.h>

// The video usability information written into the SPS: how a decoder
// interprets the YCbCr samples. CICP code points (ITU-T H.273); 2 =
// unspecified. Apple's camera files: 12 (Display P3), 1 (BT.709 curve),
// 6 (BT.601 matrix), full range.
typedef struct {
  uint8_t primaries, transfer, matrix;
  uint8_t full_range;
} hevc_vui_t;

// NAL units, each with a 4-byte big-endian length (as HEIF stores them).
typedef struct {
  uint8_t *data;
  size_t len;
} hevc_buf_t;

// 1 if this build can encode HEVC (x265 linked in).
int hevc_available(void);
// x265's version, e.g. "x265 4.3", or "" without it.
const char *hevc_encoder_version(void);

// Encodes one 8-bit 4:2:0 picture (w x h; u and v are (w+1)/2 x (h+1)/2) as
// a single intra picture: x265, preset slow, CRF `rf`, Main Still Picture
// profile, everything else at x265's defaults, on `threads` threads (1: on
// the calling thread; the WebAssembly build always does). `ps` gets the
// VPS, SPS and PPS and `pic` the picture's NAL units, both malloc'ed.
// Returns 0, or -1 with the reason in err.
int hevc_encode(const uint8_t *y, size_t y_stride, const uint8_t *u, const uint8_t *v, size_t c_stride,
                uint32_t w, uint32_t h, double rf, const hevc_vui_t *vui, int threads, hevc_buf_t *ps,
                hevc_buf_t *pic, char *err, size_t err_len);

// The 'hvcC' property's payload (HEVCDecoderConfigurationRecord) for
// pictures encoded with these parameter sets: its profile, tier, level and
// constraint flags from the VPS, 4-byte NAL lengths, the three parameter
// sets. malloc'ed. Returns 0, or -1 if the parameter sets are malformed or
// out of memory.
int hevc_make_hvcc(const hevc_buf_t *ps, uint8_t **out, size_t *out_len);

#endif
