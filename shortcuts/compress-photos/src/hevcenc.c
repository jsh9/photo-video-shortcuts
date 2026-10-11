#include "hevcenc.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "boxes.h"

#ifdef JXLBATCH_HEIC
#include <x265.h>

int hevc_available(void) { return 1; }

const char *hevc_encoder_version(void) {
  static char version[32];
  if (!version[0]) snprintf(version, sizeof version, "x265 %s", x265_version_str);
  return version;
}

static int append(hevc_buf_t *b, const uint8_t *p, size_t n) {
  uint8_t *grown = (uint8_t *)realloc(b->data, b->len + n);
  if (!grown) return -1;
  memcpy(grown + b->len, p, n);
  b->data = grown;
  b->len += n;
  return 0;
}

// The NAL units x265 handed over, as x265 wrote them: with bAnnexB off, each
// starts with its 4-byte length.
static int append_nals(hevc_buf_t *b, const x265_nal *nal, uint32_t count) {
  for (uint32_t i = 0; i < count; i++) {
    if (append(b, nal[i].payload, nal[i].sizeBytes) != 0) return -1;
  }
  return 0;
}

int hevc_encode(const uint8_t *y, size_t y_stride, const uint8_t *u, const uint8_t *v, size_t c_stride,
                uint32_t w, uint32_t h, double rf, const hevc_vui_t *vui, int threads, hevc_buf_t *ps,
                hevc_buf_t *pic, char *err, size_t err_len) {
  memset(ps, 0, sizeof *ps);
  memset(pic, 0, sizeof *pic);
  const x265_api *api = x265_api_get(8);
  if (!api) {
    snprintf(err, err_len, "x265: no 8-bit encoder");
    return -1;
  }
  x265_param *p = api->param_alloc();
  x265_picture *in = NULL;
  x265_encoder *enc = NULL;
  int rc = -1;
  if (!p) {
    snprintf(err, err_len, "out of memory");
    return -1;
  }
  // The same as the x265 command line with --preset slow --crf RF --profile
  // mainstillpicture --frames 1 --no-info, in the order the command line
  // applies them (the profile turns header repetition on; off again below,
  // the headers go into 'hvcC').
  if (api->param_default_preset(p, "slow", NULL) != 0 || api->param_apply_profile(p, "mainstillpicture") != 0) {
    snprintf(err, err_len, "x265: cannot set up the encoder");
    goto done;
  }
  p->sourceWidth = (int)w;
  p->sourceHeight = (int)h;
  p->internalCsp = X265_CSP_I420;
  // x265 wants at least one coding tree unit (64 pixels by default): smaller
  // pictures (a small photo's tiles, a thumbnail) get smaller units.
  if (w < 64 || h < 64) p->maxCUSize = (w < 32 || h < 32) ? 16 : 32;
  p->fpsNum = 1;
  p->fpsDenom = 1;
  p->totalFrames = 1;
  p->keyframeMax = 1;
  p->bRepeatHeaders = 0;
  p->bAnnexB = 0;  // 4-byte lengths instead of start codes
  p->bEmitInfoSEI = 0;
  p->logLevel = X265_LOG_NONE;
  p->rc.rateControlMode = X265_RC_CRF;
  p->rc.rfConstant = rf;
  // No thread pool (so no wavefront, which changes the bitstream with the
  // thread count), and one frame thread: the WebAssembly build has no
  // threads, and the native builds must write the same bytes. The tiles of a
  // photo run on several threads instead (heicout.c).
  (void)threads;
  snprintf(p->numaPools, sizeof p->numaPools, "none");
  p->frameNumThreads = 1;
  p->bEnableWavefront = 0;
  if (vui) {
    p->vui.bEnableVideoSignalTypePresentFlag = 1;
    p->vui.videoFormat = 5;  // unspecified
    p->vui.bEnableVideoFullRangeFlag = vui->full_range ? 1 : 0;
    p->vui.bEnableColorDescriptionPresentFlag = 1;
    p->vui.colorPrimaries = vui->primaries;
    p->vui.transferCharacteristics = vui->transfer;
    p->vui.matrixCoeffs = vui->matrix;
  }
  enc = api->encoder_open(p);
  if (!enc) {
    snprintf(err, err_len, "x265: cannot open the encoder for %ux%u", w, h);
    goto done;
  }
  x265_nal *nal = NULL;
  uint32_t count = 0;
  if (api->encoder_headers(enc, &nal, &count) < 0 || append_nals(ps, nal, count) != 0) {
    snprintf(err, err_len, "x265: no parameter sets");
    goto done;
  }
  in = api->picture_alloc();
  if (!in) {
    snprintf(err, err_len, "out of memory");
    goto done;
  }
  api->picture_init(p, in);
  in->colorSpace = X265_CSP_I420;
  in->planes[0] = (void *)y;
  in->planes[1] = (void *)u;
  in->planes[2] = (void *)v;
  in->stride[0] = (int)y_stride;
  in->stride[1] = (int)c_stride;
  in->stride[2] = (int)c_stride;
  int r = api->encoder_encode(enc, &nal, &count, in, NULL);
  if (r < 0) {
    snprintf(err, err_len, "x265: encoding failed");
    goto done;
  }
  if (append_nals(pic, nal, count) != 0) goto oom;
  for (;;) {  // flush
    r = api->encoder_encode(enc, &nal, &count, NULL, NULL);
    if (r < 0) {
      snprintf(err, err_len, "x265: encoding failed");
      goto done;
    }
    if (append_nals(pic, nal, count) != 0) goto oom;
    if (r == 0) break;
  }
  if (!pic->len) {
    snprintf(err, err_len, "x265: no picture");
    goto done;
  }
  rc = 0;
  goto done;
oom:
  snprintf(err, err_len, "out of memory");
done:
  if (rc != 0) {
    free(ps->data);
    free(pic->data);
    memset(ps, 0, sizeof *ps);
    memset(pic, 0, sizeof *pic);
  }
  if (in) api->picture_free(in);
  if (enc) api->encoder_close(enc);
  api->param_free(p);
  return rc;
}

#else

int hevc_available(void) { return 0; }
const char *hevc_encoder_version(void) { return ""; }

int hevc_encode(const uint8_t *y, size_t y_stride, const uint8_t *u, const uint8_t *v, size_t c_stride,
                uint32_t w, uint32_t h, double rf, const hevc_vui_t *vui, int threads, hevc_buf_t *ps,
                hevc_buf_t *pic, char *err, size_t err_len) {
  (void)y, (void)y_stride, (void)u, (void)v, (void)c_stride, (void)w, (void)h, (void)rf, (void)vui, (void)threads;
  memset(ps, 0, sizeof *ps);
  memset(pic, 0, sizeof *pic);
  snprintf(err, err_len, "HEIC output is not in this build");
  return -1;
}

#endif

// Walks the length-prefixed NAL units in buf.
static int next_nal(const hevc_buf_t *b, size_t *pos, const uint8_t **nal, size_t *len) {
  if (*pos + 4 > b->len) return 0;
  const uint32_t n = rd32be(b->data + *pos);
  if (n < 2 || n > b->len - *pos - 4) return 0;
  *nal = b->data + *pos + 4;
  *len = n;
  *pos += 4 + n;
  return 1;
}

int hevc_make_hvcc(const hevc_buf_t *ps, uint8_t **out, size_t *out_len) {
  *out = NULL;
  *out_len = 0;
  const uint8_t *sets[3] = {NULL, NULL, NULL};  // VPS, SPS, PPS
  size_t set_len[3] = {0, 0, 0};
  size_t pos = 0;
  const uint8_t *nal;
  size_t len;
  while (next_nal(ps, &pos, &nal, &len)) {
    const int type = (nal[0] >> 1) & 63;
    if (type >= 32 && type <= 34 && !sets[type - 32]) {
      sets[type - 32] = nal;
      set_len[type - 32] = len;
    }
  }
  if (!sets[0] || !sets[1] || !sets[2] || set_len[0] < 18) return -1;
  const uint8_t *vps = sets[0];
  const size_t total = 23 + 3 * 5 + set_len[0] + set_len[1] + set_len[2];
  uint8_t *rec = (uint8_t *)malloc(total);
  if (!rec) return -1;
  uint8_t *q = rec;
  *q++ = 1;                 // configurationVersion
  memcpy(q, vps + 6, 12);   // general profile space, tier, idc; compatibility and constraint flags; level
  q += 12;
  *q++ = 0xf0;              // min_spatial_segmentation_idc = 0 (reserved bits set)
  *q++ = 0x00;
  *q++ = 0xfc;              // parallelismType = 0
  *q++ = 0xfd;              // chromaFormat = 1 (4:2:0)
  *q++ = 0xf8;              // bitDepthLumaMinus8 = 0
  *q++ = 0xf8;              // bitDepthChromaMinus8 = 0
  *q++ = 0;                 // avgFrameRate = 0
  *q++ = 0;
  // constantFrameRate = 0, numTemporalLayers and temporalIdNested from the
  // VPS (vps_max_sub_layers_minus1, vps_temporal_id_nesting_flag), 4-byte
  // NAL lengths (lengthSizeMinusOne = 3).
  *q++ = (uint8_t)(((((vps[3] >> 1) & 7) + 1) << 3) | ((vps[3] & 1) << 2) | 3);
  *q++ = 3;  // numOfArrays
  for (int i = 0; i < 3; i++) {
    *q++ = (uint8_t)(0x80 | (32 + i));  // array_completeness, NAL unit type
    *q++ = 0;                           // numNalus = 1
    *q++ = 1;
    *q++ = (uint8_t)(set_len[i] >> 8);
    *q++ = (uint8_t)set_len[i];
    memcpy(q, sets[i], set_len[i]);
    q += set_len[i];
  }
  *out = rec;
  *out_len = total;
  return 0;
}
