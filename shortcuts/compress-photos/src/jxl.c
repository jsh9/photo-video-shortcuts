#include "jxl.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <jxl/cms.h>
#include <jxl/decode.h>
#ifdef JXLBATCH_THREADS
#include <jxl/thread_parallel_runner.h>
#endif

#include "gainmap.h"

// A metadata box larger than this fails the photo (a decompressed "brob" box
// has no size limit of its own). A JPEG's EXIF is at most 64 KB and its
// extended XMP at most 16 MiB.
#define JXL_MAX_BOX (64u << 20)
// The largest picture decoded, in pixels: libjxl's level 5, which every
// camera and app writes, allows 2^28.
#define JXL_MAX_PIXELS (1u << 28)
// The brightness, in nits, an HDR picture is tone-mapped to for SDR (libjxl's
// Rec. 2408 tone mapping, then the sRGB curve): SDR white of the result,
// libjxl's own default for SDR. Measured on HDR copies of five iPhone photos
// against the camera's own SDR picture (2026-10-16): 3 to 29 levels of 255
// apart on average (12 in all), against 3 to 42 (17) for 203 nits and 6 to 19
// (13) for 300; no single value fits all, as Apple tone-maps the camera's
// SDR picture locally.
#define JXL_SDR_NITS 255.0f

int jxl_color_from_cicp(const uint8_t cicp[4], JxlColorEncoding *c) {
  memset(c, 0, sizeof *c);
  c->color_space = JXL_COLOR_SPACE_RGB;
  c->white_point = JXL_WHITE_POINT_D65;
  c->rendering_intent = JXL_RENDERING_INTENT_RELATIVE;
  switch (cicp[0]) {
    case 1: c->primaries = JXL_PRIMARIES_SRGB; break;
    case 9: c->primaries = JXL_PRIMARIES_2100; break;
    case 11:
      c->primaries = JXL_PRIMARIES_P3;
      c->white_point = JXL_WHITE_POINT_DCI;
      break;
    case 12: c->primaries = JXL_PRIMARIES_P3; break;
    default: return 0;
  }
  switch (cicp[1]) {
    case 1: case 6: case 14: case 15: c->transfer_function = JXL_TRANSFER_FUNCTION_709; break;
    case 8: c->transfer_function = JXL_TRANSFER_FUNCTION_LINEAR; break;
    case 13: c->transfer_function = JXL_TRANSFER_FUNCTION_SRGB; break;
    case 16: c->transfer_function = JXL_TRANSFER_FUNCTION_PQ; break;
    case 17: c->transfer_function = JXL_TRANSFER_FUNCTION_DCI; break;
    case 18: c->transfer_function = JXL_TRANSFER_FUNCTION_HLG; break;
    default: return 0;
  }
  return cicp[2] == 0;  // RGB only
}

int jxl_cicp_from_color(const JxlColorEncoding *c, uint8_t cicp[4]) {
  if (c->color_space != JXL_COLOR_SPACE_RGB) return 0;
  switch (c->primaries) {
    case JXL_PRIMARIES_SRGB: cicp[0] = 1; break;
    case JXL_PRIMARIES_2100: cicp[0] = 9; break;
    case JXL_PRIMARIES_P3: cicp[0] = c->white_point == JXL_WHITE_POINT_DCI ? 11 : 12; break;
    default: return 0;
  }
  if (c->white_point != (cicp[0] == 11 ? JXL_WHITE_POINT_DCI : JXL_WHITE_POINT_D65)) return 0;
  switch (c->transfer_function) {
    case JXL_TRANSFER_FUNCTION_709: cicp[1] = 1; break;
    case JXL_TRANSFER_FUNCTION_LINEAR: cicp[1] = 8; break;
    case JXL_TRANSFER_FUNCTION_SRGB: cicp[1] = 13; break;
    case JXL_TRANSFER_FUNCTION_PQ: cicp[1] = 16; break;
    case JXL_TRANSFER_FUNCTION_DCI: cicp[1] = 17; break;
    case JXL_TRANSFER_FUNCTION_HLG: cicp[1] = 18; break;
    default: return 0;  // a plain gamma has no code point
  }
  cicp[2] = 0;  // RGB
  cicp[3] = 1;  // full range
  return 1;
}

// ---------------------------------------------------------------------------
// Boxes

// The box being read into `*dst`, in a buffer that grows as libjxl asks.
typedef struct {
  blob_t *dst;
  int exif;  // an Exif box: its 4-byte offset to the TIFF header is dropped
  uint8_t *data;
  size_t cap;
} box_read_t;

static int box_grow(JxlDecoder *dec, box_read_t *r) {
  const size_t used = r->data ? r->cap - JxlDecoderReleaseBoxBuffer(dec) : 0;
  const size_t cap = r->cap ? r->cap * 2 : 65536;
  if (cap > JXL_MAX_BOX) return -2;
  uint8_t *data = (uint8_t *)realloc(r->data, cap);
  if (!data) return -1;
  r->data = data;
  r->cap = cap;
  return JxlDecoderSetBoxBuffer(dec, data + used, cap - used) == JXL_DEC_SUCCESS ? 0 : -1;
}

// The box is complete: its contents become the blob.
static void box_finish(JxlDecoder *dec, box_read_t *r) {
  const size_t used = r->cap - JxlDecoderReleaseBoxBuffer(dec);
  size_t start = 0;
  if (r->exif) {
    // A TIFF header at the given offset; anything else isn't EXIF to keep.
    const uint32_t off = used >= 4 ? ((uint32_t)r->data[0] << 24 | (uint32_t)r->data[1] << 16 |
                                      (uint32_t)r->data[2] << 8 | r->data[3])
                                   : 0;
    start = used >= 4 && off <= used - 4 ? 4 + (size_t)off : used;
    if (!is_tiff(r->data + start, used - start)) start = used;
  }
  if (start < used) {
    memmove(r->data, r->data + start, used - start);
    r->dst->data = r->data;
    r->dst->size = used - start;
  } else {
    free(r->data);
  }
  memset(r, 0, sizeof *r);
}

int jxl_boxes(const uint8_t *buf, size_t len, meta_t *m, char *err, size_t err_len) {
  JxlDecoder *dec = JxlDecoderCreate(NULL);
  box_read_t r;
  memset(&r, 0, sizeof r);
  int rc = -1;
  char type[5] = "";
  if (!dec || JxlDecoderSubscribeEvents(dec, JXL_DEC_BOX) != JXL_DEC_SUCCESS ||
      JxlDecoderSetDecompressBoxes(dec, JXL_TRUE) != JXL_DEC_SUCCESS ||
      JxlDecoderSetInput(dec, buf, len) != JXL_DEC_SUCCESS) {
    snprintf(err, err_len, "out of memory");
    goto done;
  }
  // The input is closed only when libjxl has read all of it: with the input
  // closed, libjxl fails a box the file ends in as it fails a corrupt one,
  // and `ended` tells the two apart.
  int ended = 0;
  for (;;) {
    const JxlDecoderStatus st = JxlDecoderProcessInput(dec);
    if (st == JXL_DEC_NEED_MORE_INPUT && !ended) {
      ended = 1;
      JxlDecoderCloseInput(dec);
      continue;
    }
    if (st == JXL_DEC_BOX || st == JXL_DEC_SUCCESS) {
      if (r.dst) box_finish(dec, &r);
      if (st == JXL_DEC_SUCCESS) break;
      if (JxlDecoderGetBoxType(dec, type, JXL_TRUE) != JXL_DEC_SUCCESS) continue;
      if (!memcmp(type, "jhgm", 4)) m->jxl_gain_map = 1;  // a gain map (ISO 21496-1): noted, not used
      blob_t *dst = !memcmp(type, "Exif", 4) && !m->exif.size ? &m->exif
                    : !memcmp(type, "xml ", 4) && !m->xmp.size ? &m->xmp
                                                                : NULL;
      if (dst) {
        r.dst = dst;
        r.exif = dst == &m->exif;
        if (box_grow(dec, &r) != 0) {
          snprintf(err, err_len, "out of memory");
          goto done;
        }
      }
    } else if (st == JXL_DEC_BOX_NEED_MORE_OUTPUT) {
      const int g = box_grow(dec, &r);
      if (g != 0) {
        if (g == -2) {
          snprintf(err, err_len, "metadata box %.4s over 64 MiB", type);
        } else {
          snprintf(err, err_len, "out of memory");
        }
        goto done;
      }
    } else if (r.dst) {
      // within a metadata box: it can't be kept
      snprintf(err, err_len, ended ? "metadata box %.4s cut short" : "unreadable metadata box %.4s", type);
      goto done;
    } else {
      // elsewhere (a codestream box cut short, say): the picture's
      // decoding says what is wrong
      break;
    }
  }
  rc = 0;

done:
  free(r.data);
  if (dec) JxlDecoderDestroy(dec);
  return rc;
}

// ---------------------------------------------------------------------------
// Pixels

int jxl_decode(const uint8_t *buf, size_t len, int sdr, void *runner, image_t *img, color_t *color,
               hdr_info_t *hdr, int *transposed, char *err, size_t err_len) {
  memset(img, 0, sizeof *img);
  memset(color, 0, sizeof *color);
  memset(hdr, 0, sizeof *hdr);
  if (transposed) *transposed = 0;
  uint8_t *pixels = NULL;
  int rc = -1;
  JxlBasicInfo info;
  JxlPixelFormat format = {3, JXL_TYPE_UINT8, JXL_NATIVE_ENDIAN, 0};
  int have_info = 0, have_pixels = 0;
  // The brightness an HDR picture is tone-mapped to, once its color encoding
  // has shown that it is wanted (below). libjxl takes the setting while it
  // reads the headers, before the color-encoding event, so a call made there
  // has no effect: the decoding then starts over with it set (the headers
  // are a few hundred bytes).
  float target = 0;
  JxlDecoder *dec;
start:
  memset(&info, 0, sizeof info);
  dec = JxlDecoderCreate(NULL);
  if (!dec || JxlDecoderSubscribeEvents(dec, JXL_DEC_BASIC_INFO | JXL_DEC_COLOR_ENCODING | JXL_DEC_FULL_IMAGE) !=
                  JXL_DEC_SUCCESS ||
      JxlDecoderSetCms(dec, *JxlGetDefaultCms()) != JXL_DEC_SUCCESS ||
      JxlDecoderSetUnpremultiplyAlpha(dec, JXL_TRUE) != JXL_DEC_SUCCESS ||
      JxlDecoderSetInput(dec, buf, len) != JXL_DEC_SUCCESS ||
      (target > 0 && JxlDecoderSetDesiredIntensityTarget(dec, target) != JXL_DEC_SUCCESS)) {
    snprintf(err, err_len, "out of memory");
    goto done;
  }
#ifdef JXLBATCH_THREADS
  if (runner && JxlDecoderSetParallelRunner(dec, JxlThreadParallelRunner, runner) != JXL_DEC_SUCCESS) {
    snprintf(err, err_len, "cannot set up the decoder's threads");
    goto done;
  }
#else
  (void)runner;
#endif
  // The input isn't closed: a file that ends too soon then asks for more
  // input (it is cut short) instead of failing.

  for (;;) {
    const JxlDecoderStatus st = JxlDecoderProcessInput(dec);
    if (st == JXL_DEC_BASIC_INFO) {
      if (JxlDecoderGetBasicInfo(dec, &info) != JXL_DEC_SUCCESS) {
        snprintf(err, err_len, "unreadable JPEG XL header");
        goto done;
      }
      have_info = 1;
      if (info.have_animation) {
        snprintf(err, err_len, "an animated JPEG XL isn't a still photo");
        goto done;
      }
      if (info.exponent_bits_per_sample > 0) {
        snprintf(err, err_len, "a JPEG XL with floating-point samples can't be converted");
        goto done;
      }
      if (!info.xsize || !info.ysize || (uint64_t)info.xsize * info.ysize > JXL_MAX_PIXELS) {
        snprintf(err, err_len, "a JPEG XL of %ux%u pixels is too large", info.xsize, info.ysize);
        goto done;
      }
    } else if (st == JXL_DEC_COLOR_ENCODING) {
      // The file's color space: an encoding libjxl describes (CICP for us),
      // or an ICC profile. A lossy (XYB) file comes out in linear sRGB unless
      // asked for its own color space, so it is always asked for.
      JxlColorEncoding enc;
      int have_enc = JxlDecoderGetColorAsEncodedProfile(dec, JXL_COLOR_PROFILE_TARGET_ORIGINAL, &enc) ==
                     JXL_DEC_SUCCESS;
      size_t icc_size = 0;
      if (!have_enc || !jxl_cicp_from_color(&enc, color->cicp)) {
        if (JxlDecoderGetICCProfileSize(dec, JXL_COLOR_PROFILE_TARGET_ORIGINAL, &icc_size) != JXL_DEC_SUCCESS ||
            !icc_size || !(color->icc.data = (uint8_t *)malloc(icc_size)) ||
            JxlDecoderGetColorAsICCProfile(dec, JXL_COLOR_PROFILE_TARGET_ORIGINAL, color->icc.data, icc_size) !=
                JXL_DEC_SUCCESS) {
          snprintf(err, err_len, "the JPEG XL's color profile can't be read");
          goto done;
        }
        color->icc.size = icc_size;
      } else {
        color->cicp_present = 1;
      }
      // An HDR profile with a 'cicp' tag (Apple's, as this tool's HDR copies
      // have it): its code points, and the profile kept as Apple's HDR one.
      if (!color->cicp_present && color->icc.size) {
        const uint8_t tagged[4] = {(uint8_t)gainmap_icc_cicp_primaries(&color->icc),
                                   (uint8_t)gainmap_icc_cicp_transfer(&color->icc), 0, 1};
        if ((tagged[1] == 16 || tagged[1] == 18) && jxl_color_from_cicp(tagged, &enc)) {
          memcpy(color->cicp, tagged, 4);
          color->cicp_present = 1;
          if (tagged[1] == 16) {
            color->hdr_icc = color->icc;
          } else {
            free(color->icc.data);
          }
          memset(&color->icc, 0, sizeof color->icc);
          have_enc = 1;
        }
      }
      // The transfer curve, as a CICP code: from the code points; else from
      // libjxl's description, which CICP may not name in full (another white
      // point, custom primaries); else from the profile's 'cicp' tag, whose
      // primaries CICP couldn't name. (A PQ curve in a profile without the
      // tag isn't recognized.)
      const int transfer = color->cicp_present ? color->cicp[1]
                           : have_enc          ? (enc.transfer_function == JXL_TRANSFER_FUNCTION_PQ    ? 16
                                                  : enc.transfer_function == JXL_TRANSFER_FUNCTION_HLG ? 18
                                                                                                       : 0)
                                               : gainmap_icc_cicp_transfer(&color->icc);
      const int hdr_curve = transfer == 16 || transfer == 18;
      JxlDecoderStatus set;
      if (hdr_curve && sdr && (color->cicp_present || have_enc)) {
        // Tone-mapped by libjxl (Rec. 2408 for PQ, the HLG OOTF for HLG) to
        // the same primaries with the sRGB curve; when CICP can't name the
        // picture's primaries or white point, to Rec. 2020 primaries (D65),
        // which it names and which hold any picture's colors.
        if (target == 0) {
          // libjxl needs the brightness before the headers (see `target`):
          // once more from the start, with it set. Not for a picture HDR by a
          // profile alone (below), which stays HDR: libjxl would tone-map
          // it all the same, within PQ, were the brightness set.
          target = JXL_SDR_NITS;
          JxlDecoderDestroy(dec);
          color_free(color);
          have_info = 0;
          goto start;
        }
        if (!color->cicp_present) {
          const uint8_t rec2020[4] = {9, 13, 0, 1};
          memcpy(color->cicp, rec2020, 4);
          color->cicp_present = 1;
          free(color->icc.data);
          memset(&color->icc, 0, sizeof color->icc);
        }
        color->cicp[1] = 13;
        free(color->hdr_icc.data);
        memset(&color->hdr_icc, 0, sizeof color->hdr_icc);
        jxl_color_from_cicp(color->cicp, &enc);
        set = JxlDecoderSetOutputColorProfile(dec, &enc, NULL, 0);
        hdr->tone_mapped = 1;
      } else if (color->cicp_present) {
        jxl_color_from_cicp(color->cicp, &enc);
        set = JxlDecoderSetOutputColorProfile(dec, &enc, NULL, 0);
      } else if (have_enc) {
        // described by libjxl, but not by CICP (gray, a plain gamma): its
        // profile goes into the copy
        set = JxlDecoderSetOutputColorProfile(dec, &enc, NULL, 0);
      } else if (info.uses_original_profile) {
        // The pixels are stored in the profile's own space (not XYB): they
        // come out as they are, with no conversion asked for, which libjxl's
        // CMS can't always do into a profile it reads (a PQ profile's curves
        // are skipped; see patch_deps.py).
        set = JXL_DEC_SUCCESS;
      } else {
        // Lossy (XYB): converted into the profile by libjxl's CMS.
        set = JxlDecoderSetOutputColorProfile(dec, NULL, color->icc.data, color->icc.size);
      }
      if (set != JXL_DEC_SUCCESS) {
        snprintf(err, err_len, "the JPEG XL can't be decoded in its own color space");
        goto done;
      }
      if (hdr_curve && sdr && !hdr->tone_mapped) {
        // HDR by a profile alone (its 'cicp' tag names the curve, not the
        // primaries): libjxl can't be asked for an SDR version of it.
        snprintf(hdr->warning, sizeof hdr->warning,
                 "HDR kept: a %s picture described by its ICC profile alone can't be tone-mapped to SDR",
                 transfer == 16 ? "PQ" : "HLG");
      }
      if (hdr_curve && !hdr->tone_mapped) {
        // How bright it gets: its intensity target, relative to SDR white.
        // Every file has one (libjxl refuses a header without; its encoder
        // writes 10,000 nits for PQ and 1,000 for HLG when given none).
        hdr->headroom = hdr->peak = info.intensity_target / GAINMAP_SDR_WHITE_NITS;
      }
      // 8 bits for SDR pictures of 8 bits or fewer, else 16 (with the file's
      // own bit depth up to 16, so the copy keeps it).
      const int alpha = info.alpha_bits > 0;
      const int wide = !hdr->tone_mapped && (info.bits_per_sample > 8 || hdr_curve);
      format.num_channels = info.num_color_channels + (alpha ? 1 : 0);
      format.data_type = wide ? JXL_TYPE_UINT16 : JXL_TYPE_UINT8;
      img->channels = (int)format.num_channels;
      img->bytes_per_sample = wide ? 2 : 1;
      img->bits = wide ? (info.bits_per_sample < 16 && info.bits_per_sample > 8 ? (int)info.bits_per_sample : 16) : 8;
    } else if (st == JXL_DEC_NEED_IMAGE_OUT_BUFFER) {
      size_t size = 0;
      if (JxlDecoderImageOutBufferSize(dec, &format, &size) != JXL_DEC_SUCCESS) {
        snprintf(err, err_len, "JPEG XL decoding failed");
        goto done;
      }
      free(pixels);
      pixels = (uint8_t *)malloc(size ? size : 1);
      if (!pixels) {
        snprintf(err, err_len, "out of memory");
        goto done;
      }
      if (JxlDecoderSetImageOutBuffer(dec, &format, pixels, size) != JXL_DEC_SUCCESS) {
        snprintf(err, err_len, "JPEG XL decoding failed");
        goto done;
      }
      // 10- or 12-bit samples as they are (0 to 1023 or 4095), as libheif
      // gives a 10-bit HEIF's, rather than stretched to 16 bits.
      const JxlBitDepth depth = {JXL_BIT_DEPTH_FROM_CODESTREAM, 0, 0};
      if (img->bytes_per_sample == 2 && img->bits < 16 && JxlDecoderSetImageOutBitDepth(dec, &depth) != JXL_DEC_SUCCESS) {
        snprintf(err, err_len, "cannot decode %d-bit samples", img->bits);
        goto done;
      }
    } else if (st == JXL_DEC_FULL_IMAGE) {
      have_pixels = 1;  // a still picture: the first full image is all of it
      break;
    } else if (st == JXL_DEC_SUCCESS) {
      break;
    } else if (st == JXL_DEC_NEED_MORE_INPUT) {
      snprintf(err, err_len, have_info ? "the JPEG XL file is cut short" : "unreadable JPEG XL file");
      goto done;
    } else {
      snprintf(err, err_len, have_info ? "JPEG XL decoding failed" : "unreadable JPEG XL file");
      goto done;
    }
  }
  if (!have_pixels) {
    snprintf(err, err_len, "the JPEG XL has no picture");
    goto done;
  }
  // The codestream's orientation is applied: orientations 5 to 8 swap the
  // stored width and height.
  const int turned = info.orientation >= JXL_ORIENT_TRANSPOSE;
  if (transposed) *transposed = turned;
  img->data = pixels;
  pixels = NULL;
  img->w = turned ? info.ysize : info.xsize;
  img->h = turned ? info.xsize : info.ysize;
  img->stride = (size_t)img->w * pixel_size(img);
  rc = 0;

done:
  free(pixels);
  if (dec) JxlDecoderDestroy(dec);  // before encoding: its memory and the encoder's don't add up
  if (rc != 0) {
    image_free(img);
    color_free(color);
  }
  return rc;
}
