// jxlbatch: converts the photos staged by the "Compress Photos" shortcut
// into JPEG XL, keeping the original EXIF/XMP metadata.
//
// For each job line "i|Name" in JOBFILE it reads jxl_in_i.orig (the original
// photo: HEIF, JPEG or PNG), writes jxl_out_i.jxl, and appends
// "jxl_out_i.jxl|i|delete|Name.jxl" to jxl_done.txt ("keep" instead of
// "delete" when the JXL lacks the original's HDR). A jxl_in_i.png converted
// by Shortcuts is used only for other formats (older versions of the shortcut).
//
// Builds with threads (JXLBATCH_THREADS, the Mac) can convert several photos
// at a time (-j), each with a share of the cores (-t); the output and
// jxl_done.txt then read as with one at a time (see parallel_batch).
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include <jxl/color_encoding.h>
#include <jxl/decode.h>
#include <jxl/encode.h>
#ifdef JXLBATCH_THREADS
#include <jxl/thread_parallel_runner.h>
#include <pthread.h>
#endif

#include "gainmap.h"
#include "meta.h"
#include "pixels.h"
#include "selftest_hdr_heic.h"
#include "selftest_heic.h"

// The build scripts set this from ../VERSION, shared with the shortcuts.
#ifndef JXLBATCH_VERSION
#define JXLBATCH_VERSION "dev"
#endif
#define DONE_FILE "jxl_done.txt"
// Created as soon as a batch starts. When a shortcut launches a-Shell, its
// WebAssembly engine may not be loaded yet and the first command fails
// without running; the shortcut then runs jxlbatch --retry, which does
// nothing when this file exists.
#define STARTED_FILE "jxl_started"

#if defined(__wasm_simd128__)
#define BUILD_KIND "WebAssembly+SIMD"
#elif defined(__wasm__)
#define BUILD_KIND "WebAssembly"
#else
#define BUILD_KIND "native"
#endif

typedef struct {
  float quality;
  int effort;
  const char *dir;
  int retry;  // --retry: skip a batch that a run already started
  int sdr;    // --sdr: HDR photos as SDR
  int mac;    // --mac: for the Mac shortcuts; no hints about the iPhone's share sheet
  int jobs;   // -j: photos converted at a time (0: from the number of cores); threads builds
  int threads;  // -t: threads per photo (0: the cores, shared by the photos); threads builds
} options_t;

#ifdef JXLBATCH_THREADS
#define THREAD_LOCAL _Thread_local
#else
#define THREAD_LOCAL  // one thread
#endif

// A growable text, where say() writes while a photo is converted at the same
// time as others (parallel_batch): each photo's lines come out as one block.
typedef struct {
  char *data;
  size_t len, cap;
} textbuf_t;

static THREAD_LOCAL textbuf_t *t_out;  // this thread's buffer; NULL: stdout
#ifdef JXLBATCH_THREADS
static THREAD_LOCAL void *t_runner;  // this thread's libjxl thread pool; NULL: one thread
#endif

static int textbuf_vprintf(textbuf_t *b, const char *fmt, va_list ap) {
  va_list copy;
  va_copy(copy, ap);
  const int n = vsnprintf(NULL, 0, fmt, copy);
  va_end(copy);
  if (n < 0) return -1;
  if (b->len + (size_t)n + 1 > b->cap) {
    size_t cap = b->cap ? b->cap : 1024;
    while (cap < b->len + (size_t)n + 1) cap *= 2;
    char *grown = (char *)realloc(b->data, cap);
    if (!grown) return -1;  // the line is lost; the photo is still converted
    b->data = grown;
    b->cap = cap;
  }
  vsnprintf(b->data + b->len, b->cap - b->len, fmt, ap);
  b->len += (size_t)n;
  return n;
}

static void say(const char *fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  if (t_out) {
    textbuf_vprintf(t_out, fmt, ap);
  } else {
    vprintf(fmt, ap);
    fflush(stdout);
  }
  va_end(ap);
}

// The output is read in a-Shell on an iPhone (about 45 columns in portrait),
// so longer messages are word-wrapped to the window width ($COLUMNS).
static size_t term_width(void) {
  const char *c = getenv("COLUMNS");
  const int w = c ? atoi(c) : 0;
  return (w >= 24 && w <= 200) ? (size_t)w - 1 : 40;
}

// Prints fmt word-wrapped, every line starting with indent.
static void say_wrap(const char *indent, const char *fmt, ...) {
  char text[1024];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(text, sizeof text, fmt, ap);
  va_end(ap);
  const size_t width = term_width(), ind = strlen(indent);
  const size_t avail = width > ind + 12 ? width - ind : 12;
  const char *p = text;
  while (*p) {
    size_t len = strcspn(p, "\n"), take = len;
    if (len > avail) {  // break at the last space that fits
      take = avail;
      while (take > 0 && p[take] != ' ') take--;
      if (take == 0) take = avail;
    }
    say("%s%.*s\n", indent, (int)take, p);
    p += take;
    while (*p == ' ') p++;
    if (*p == '\n' && take == len) p++;
  }
}

static double now_seconds(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static void fmt_bytes(char *buf, size_t n, double bytes) {
  if (bytes >= 1e6) {
    snprintf(buf, n, "%.1f MB", bytes / 1e6);
  } else if (bytes >= 1e3) {
    snprintf(buf, n, "%.0f KB", bytes / 1e3);
  } else {
    snprintf(buf, n, "%.0f B", bytes);
  }
}

static char *path_join(const char *dir, const char *name) {
  if (!dir || !*dir || name[0] == '/') return strdup(name);
  size_t dl = strlen(dir), nl = strlen(name);
  char *p = (char *)malloc(dl + nl + 2);
  if (!p) return NULL;
  memcpy(p, dir, dl);
  size_t pos = dl;
  if (dl && dir[dl - 1] != '/') p[pos++] = '/';
  memcpy(p + pos, name, nl + 1);
  return p;
}

// a-Shell's WebAssembly runtime passes every read and write to the app, and a
// call that takes longer than 0.5 s silently returns no data. Writes are sent
// as comma-separated decimal bytes. So files are read and written in small
// pieces, and sizes are checked so a short transfer is an error, not a
// silently truncated photo.
#define READ_CHUNK (256 * 1024)
#define WRITE_CHUNK (64 * 1024)

static int read_file(const char *path, uint8_t **out, size_t *out_len) {
  int fd = open(path, O_RDONLY);
  if (fd < 0) return -1;
  struct stat st;
  const long long expected = fstat(fd, &st) == 0 ? (long long)st.st_size : -1;
  size_t cap = expected > 0 ? (size_t)expected + READ_CHUNK : (size_t)4 << 20, len = 0;
  uint8_t *buf = (uint8_t *)malloc(cap);
  int err = buf ? 0 : ENOMEM;
  while (!err) {
    if (cap - len < READ_CHUNK) {
      uint8_t *grown = (uint8_t *)realloc(buf, cap * 2);
      if (!grown) {
        err = ENOMEM;
        break;
      }
      buf = grown;
      cap *= 2;
    }
    ssize_t got = read(fd, buf + len, READ_CHUNK);
    if (got < 0) {
      if (errno != EINTR) err = errno;
      continue;
    }
    if (got == 0) break;
    len += (size_t)got;
  }
  close(fd);
  if (!err && expected > 0 && (long long)len != expected) err = EIO;  // short read
  if (err) {
    free(buf);
    errno = err;
    return -1;
  }
  *out = buf;
  *out_len = len;
  return 0;
}

static int write_file(const char *path, const uint8_t *data, size_t len) {
  int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
  if (fd < 0) return -1;
  size_t off = 0;
  int err = 0, stalls = 0;
  while (off < len && !err) {
    size_t n = len - off < WRITE_CHUNK ? len - off : WRITE_CHUNK;
    ssize_t put = write(fd, data + off, n);
    if (put < 0) {
      if (errno != EINTR) err = errno;
    } else if (put == 0) {
      if (++stalls > 20) err = EIO;
    } else {
      off += (size_t)put;
    }
  }
  if (close(fd) != 0 && !err) err = errno;
  struct stat st;
  if (!err && stat(path, &st) == 0 && (size_t)st.st_size != len) err = EIO;  // short write
  if (err) {
    errno = err;
    return -1;
  }
  return 0;
}

// ---------------------------------------------------------------------------
// Encoding

typedef struct {
  const color_t *color;  // NULL means sRGB
  const uint8_t *exif;   // raw TIFF (without the 4-byte box offset)
  size_t exif_len;
  const uint8_t *xmp;
  size_t xmp_len;
  double intensity_target;  // HDR (PQ): the brightest pixels, in nits; 0 = PQ's peak
} encode_meta_t;

static const char *jxl_error_name(JxlEncoderError e) {
  switch (e) {
    case JXL_ENC_ERR_OK: return "ok";
    case JXL_ENC_ERR_GENERIC: return "generic error";
    case JXL_ENC_ERR_OOM: return "out of memory";
    case JXL_ENC_ERR_JBRD: return "JPEG reconstruction data error";
    case JXL_ENC_ERR_BAD_INPUT: return "bad input";
    case JXL_ENC_ERR_NOT_SUPPORTED: return "not supported";
    case JXL_ENC_ERR_API_USAGE: return "API usage error";
    default: return "unknown error";
  }
}

static int color_from_cicp(const uint8_t cicp[4], JxlColorEncoding *c) {
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

// Chunked input: libjxl reads the pixels in place, a region at a time,
// instead of first copying the whole image (matters for 48 MP photos). An
// HDR image is computed a region at a time, as libjxl asks for it.
typedef struct {
  const image_t *img;
  JxlPixelFormat format;
} chunk_source_t;

static void chunk_color_format(void *opaque, JxlPixelFormat *format) {
  *format = ((const chunk_source_t *)opaque)->format;
}

static const void *chunk_color_data(void *opaque, size_t xpos, size_t ypos, size_t xsize, size_t ysize,
                                    size_t *row_offset) {
  const image_t *img = ((const chunk_source_t *)opaque)->img;
  if (img->render) {
    const size_t row = xsize * pixel_size(img);
    uint8_t *buf = (uint8_t *)malloc(row * ysize);
    if (buf && img->render(img->owner, (uint32_t)xpos, (uint32_t)ypos, (uint32_t)xsize, (uint32_t)ysize, buf,
                           row) != 0) {
      free(buf);
      buf = NULL;
    }
    *row_offset = row;
    return buf;  // NULL makes libjxl fail the photo
  }
  *row_offset = img->stride;
  return img->data + ypos * img->stride + xpos * pixel_size(img);
}

static void chunk_extra_format(void *opaque, size_t index, JxlPixelFormat *format) {
  (void)opaque;
  (void)index;
  (void)format;
}

static const void *chunk_extra_data(void *opaque, size_t index, size_t xpos, size_t ypos, size_t xsize,
                                    size_t ysize, size_t *row_offset) {
  (void)opaque;
  (void)index;
  (void)xpos;
  (void)ypos;
  (void)xsize;
  (void)ysize;
  *row_offset = 0;
  return NULL;  // only used for images with alpha, which take the other path
}

static void chunk_release(void *opaque, const void *buf) {
  if (((const chunk_source_t *)opaque)->img->render) free((void *)buf);
}

// Output written as libjxl encodes. With it, libjxl reads the input a region
// at a time; with JxlEncoderProcessOutput, it copies the whole image first.
// A growable buffer that libjxl can seek in (to fill in sizes).
typedef struct {
  uint8_t *data;
  size_t size, cap, pos;
} out_buffer_t;

static void *out_get_buffer(void *opaque, size_t *size) {
  out_buffer_t *o = (out_buffer_t *)opaque;
  const size_t want = *size ? *size : (size_t)1 << 16;
  if (want > SIZE_MAX - o->pos) return *size = 0, NULL;
  if (o->pos + want > o->cap) {
    size_t cap = o->cap ? o->cap : (size_t)1 << 20;
    while (cap < o->pos + want) cap *= 2;
    uint8_t *grown = (uint8_t *)realloc(o->data, cap);
    if (!grown) return *size = 0, NULL;  // libjxl then fails
    o->data = grown;
    o->cap = cap;
  }
  *size = want;
  return o->data + o->pos;
}

static void out_release_buffer(void *opaque, size_t written) {
  out_buffer_t *o = (out_buffer_t *)opaque;
  o->pos += written;
  if (o->pos > o->size) o->size = o->pos;
}

static void out_seek(void *opaque, uint64_t position) { ((out_buffer_t *)opaque)->pos = (size_t)position; }

static void out_set_finalized_position(void *opaque, uint64_t position) {
  (void)opaque;
  (void)position;
}

enum { ENC_OK = 0, ENC_FAIL = -1, ENC_BAD_ICC = -2 };

// Encodes img; the caller frees it afterwards.
static int encode_attempt(image_t *img, const encode_meta_t *em, const options_t *opt, int use_icc, uint8_t **out,
                          size_t *out_len, char *err, size_t err_len) {
  int rc = ENC_FAIL;
  uint8_t *exif_box = NULL, *buf = NULL;
  out_buffer_t output = {NULL, 0, 0, 0};
  JxlEncoder *enc = JxlEncoderCreate(NULL);
  if (!enc) {
    snprintf(err, err_len, "out of memory creating the encoder");
    return ENC_FAIL;
  }
#ifdef JXLBATCH_THREADS
  if (t_runner) JxlEncoderSetParallelRunner(enc, JxlThreadParallelRunner, t_runner);
#endif
  const int lossless = opt->quality >= 100.0f;
  const int gray = img->channels <= 2;
  const int alpha = img->channels == 2 || img->channels == 4;
  const uint32_t container_bits = (uint32_t)img->bytes_per_sample * 8;
  const uint32_t bits = (uint32_t)img->bits;  // e.g. 10 for 10-bit HEIF in 16-bit samples
  const color_t *color = em->color;
  // HDR photos are PQ (see hdr.h), coded by CICP, or by Apple's profile for
  // them (which describes the same color space).
  const int pq = color && !(use_icc && color->icc.size) && color->cicp_present && color->cicp[1] == 16;
  const int hdr_icc = pq && use_icc && color->hdr_icc.size;

#define FAIL(...)                              \
  do {                                         \
    snprintf(err, err_len, __VA_ARGS__);       \
    goto done;                                 \
  } while (0)

  if (JxlEncoderUseContainer(enc, JXL_TRUE) != JXL_ENC_SUCCESS ||
      JxlEncoderUseBoxes(enc) != JXL_ENC_SUCCESS) {
    FAIL("cannot enable the JPEG XL container");
  }
  if (!alpha) {
    const struct JxlEncoderOutputProcessor processor = {&output, out_get_buffer, out_release_buffer, out_seek,
                                                       out_set_finalized_position};
    if (JxlEncoderSetOutputProcessor(enc, processor) != JXL_ENC_SUCCESS) FAIL("cannot set the output");
  }

  JxlBasicInfo info;
  JxlEncoderInitBasicInfo(&info);
  info.xsize = img->w;
  info.ysize = img->h;
  info.bits_per_sample = bits;
  info.exponent_bits_per_sample = 0;
  info.num_color_channels = gray ? 1 : 3;
  info.num_extra_channels = alpha ? 1 : 0;
  info.alpha_bits = alpha ? bits : 0;
  info.alpha_exponent_bits = 0;
  // In lossy files, libjxl replaces a profile it can describe itself (as it
  // can Apple's HDR profile) by that description, which would drop Apple's
  // tone-mapping curve. It keeps the profile if the image is lossless when the
  // profile is set, so it is set that way first. (This relies on libjxl's
  // JxlEncoderSetICCProfile deciding then, in DecideIfWantICC, as libjxl
  // 0.11.2 and 0.12.0 do; test_hdr_profile.py checks it.)
  info.uses_original_profile = lossless || hdr_icc ? JXL_TRUE : JXL_FALSE;
  info.orientation = JXL_ORIENT_IDENTITY;  // pixels are already upright
  // How bright an HDR photo gets, in nits: at most PQ's peak, 10,000 nits
  // (its brighter values are clipped there, and libjxl rejects targets above
  // 65,504). Left at 0 otherwise: libjxl then uses the default for the color
  // it ends up storing (10,000 nits for PQ, 255 for SDR).
  if (pq && em->intensity_target > 0) info.intensity_target = (float)fmin(em->intensity_target, 10000);
  if (JxlEncoderSetBasicInfo(enc, &info) != JXL_ENC_SUCCESS) {
    FAIL("rejected image header (%s)", jxl_error_name(JxlEncoderGetError(enc)));
  }

  int color_set = 0;
  if (hdr_icc) {
    if (JxlEncoderSetICCProfile(enc, color->hdr_icc.data, color->hdr_icc.size) != JXL_ENC_SUCCESS) {
      rc = ENC_BAD_ICC;
      FAIL("ICC profile rejected");
    }
    info.uses_original_profile = lossless ? JXL_TRUE : JXL_FALSE;
    if (JxlEncoderSetBasicInfo(enc, &info) != JXL_ENC_SUCCESS) {
      rc = ENC_BAD_ICC;  // tried again without the profile
      FAIL("rejected image header (%s)", jxl_error_name(JxlEncoderGetError(enc)));
    }
    color_set = 1;
  }
  if (!color_set && use_icc && color && color->icc.size) {
    if (JxlEncoderSetICCProfile(enc, color->icc.data, color->icc.size) != JXL_ENC_SUCCESS) {
      rc = ENC_BAD_ICC;
      FAIL("ICC profile rejected");
    }
    color_set = 1;
  }
  if (!color_set && color && color->cicp_present && !gray) {
    JxlColorEncoding ce;
    if (color_from_cicp(color->cicp, &ce) && JxlEncoderSetColorEncoding(enc, &ce) == JXL_ENC_SUCCESS) {
      color_set = 1;
    }
  }
  if (!color_set) {
    JxlColorEncoding ce;
    JxlColorEncodingSetToSRGB(&ce, gray ? JXL_TRUE : JXL_FALSE);
    if (JxlEncoderSetColorEncoding(enc, &ce) != JXL_ENC_SUCCESS) FAIL("cannot set sRGB");
  }

  // Metadata boxes: uncompressed, so Apple's ImageIO (and exiftool) can read them.
  if (em->exif_len) {
    exif_box = (uint8_t *)malloc(em->exif_len + 4);
    if (!exif_box) FAIL("out of memory");
    memset(exif_box, 0, 4);  // TIFF header offset: header follows immediately
    memcpy(exif_box + 4, em->exif, em->exif_len);
    if (JxlEncoderAddBox(enc, "Exif", exif_box, em->exif_len + 4, JXL_FALSE) != JXL_ENC_SUCCESS) {
      FAIL("cannot add the Exif box");
    }
  }
  if (em->xmp_len && JxlEncoderAddBox(enc, "xml ", em->xmp, em->xmp_len, JXL_FALSE) != JXL_ENC_SUCCESS) {
    FAIL("cannot add the XMP box");
  }
  JxlEncoderCloseBoxes(enc);

  JxlEncoderFrameSettings *fs = JxlEncoderFrameSettingsCreate(enc, NULL);
  if (!fs) FAIL("out of memory");
  if (JxlEncoderFrameSettingsSetOption(fs, JXL_ENC_FRAME_SETTING_EFFORT, opt->effort) != JXL_ENC_SUCCESS) {
    FAIL("invalid effort %d", opt->effort);
  }
  if (lossless) {
    if (JxlEncoderSetFrameLossless(fs, JXL_TRUE) != JXL_ENC_SUCCESS) FAIL("cannot enable lossless");
  } else if (JxlEncoderSetFrameDistance(fs, JxlEncoderDistanceFromQuality(opt->quality)) != JXL_ENC_SUCCESS) {
    FAIL("invalid quality %g", opt->quality);
  }
  // Always encode large images in streaming mode (2048 x 2048 sections). By
  // default libjxl does that at effort 7 only below distance 3, i.e. above
  // quality ~70; at lower qualities it holds the whole image, which takes
  // about 2.7 GB for a 24 MP photo and gets a-Shell's engine killed by iOS.
  if (JxlEncoderFrameSettingsSetOption(fs, JXL_ENC_FRAME_SETTING_BUFFERING, 2) != JXL_ENC_SUCCESS) {
    FAIL("cannot enable streaming");
  }

  if (bits < container_bits) {
    // Samples are e.g. 0..1023 in 16-bit containers: scale by the declared depth.
    const JxlBitDepth depth = {JXL_BIT_DEPTH_FROM_CODESTREAM, 0, 0};
    if (JxlEncoderSetFrameBitDepth(fs, &depth) != JXL_ENC_SUCCESS) FAIL("cannot set %u-bit input", bits);
  }

  JxlPixelFormat pf = {(uint32_t)img->channels, container_bits == 16 ? JXL_TYPE_UINT16 : JXL_TYPE_UINT8,
                       JXL_NATIVE_ENDIAN, 0};
  if (alpha) {
    // Chunked input wants alpha separate from color; this rare case uses a packed copy.
    if (image_make_packed(img) != 0) FAIL("out of memory");
    if (JxlEncoderAddImageFrame(fs, &pf, img->data, img->stride * img->h) != JXL_ENC_SUCCESS) {
      FAIL("encoder rejected the image (%s)", jxl_error_name(JxlEncoderGetError(enc)));
    }
    JxlEncoderCloseInput(enc);
  } else {
    chunk_source_t source = {img, pf};
    const struct JxlChunkedFrameInputSource input = {&source,           chunk_color_format, chunk_color_data,
                                              chunk_extra_format, chunk_extra_data,  chunk_release};
    // As the last frame, this also closes the input; the output processor
    // gets the whole file.
    if (JxlEncoderAddChunkedFrame(fs, JXL_TRUE, input) != JXL_ENC_SUCCESS ||
        JxlEncoderFlushInput(enc) != JXL_ENC_SUCCESS) {
      FAIL("encoding failed (%s)", jxl_error_name(JxlEncoderGetError(enc)));
    }
    *out = output.data;
    *out_len = output.size;
    output.data = NULL;
    rc = ENC_OK;
    goto done;
  }

  size_t cap = 1 << 20;
  buf = (uint8_t *)malloc(cap);
  if (!buf) FAIL("out of memory");
  uint8_t *next = buf;
  size_t avail = cap;
  JxlEncoderStatus st;
  while ((st = JxlEncoderProcessOutput(enc, &next, &avail)) == JXL_ENC_NEED_MORE_OUTPUT) {
    size_t used = (size_t)(next - buf);
    uint8_t *grown = (uint8_t *)realloc(buf, cap * 2);
    if (!grown) FAIL("out of memory");
    buf = grown;
    cap *= 2;
    next = buf + used;
    avail = cap - used;
  }
  if (st != JXL_ENC_SUCCESS) FAIL("encoding failed (%s)", jxl_error_name(JxlEncoderGetError(enc)));
  *out = buf;
  *out_len = (size_t)(next - buf);
  buf = NULL;
  rc = ENC_OK;
#undef FAIL
done:
  free(buf);
  free(output.data);
  free(exif_box);
  JxlEncoderDestroy(enc);
  return rc;
}

static int encode_jxl(image_t *img, const encode_meta_t *em, const options_t *opt, uint8_t **out,
                      size_t *out_len, char *err, size_t err_len) {
  int rc = encode_attempt(img, em, opt, 1, out, out_len, err, err_len);
  if (rc == ENC_BAD_ICC) {
    // An HDR photo's only profile is Apple's HDR one; without it, the PQ
    // pixels are still labeled by CICP.
    const int hdr = em->color && em->color->hdr_icc.size && !em->color->icc.size;
    say_wrap("  ", hdr ? "! Apple's HDR color profile rejected by libjxl; saved without it"
                       : "! color profile rejected by libjxl; saved as sRGB");
    rc = encode_attempt(img, em, opt, 0, out, out_len, err, err_len);
  }
  return rc == ENC_OK ? 0 : -1;
}

// ---------------------------------------------------------------------------
// Jobs

typedef struct {
  unsigned index;
  char name[256];
} job_t;

static void clean_name(char *name, unsigned index) {
  static const char *kExts[] = {"heic", "heif", "hif", "jpg", "jpeg", "png", "dng", "tif",
                                "tiff", "gif", "webp", "avif", "bmp", "jxl"};
  for (char *p = name; *p; p++) {
    if (*p == '/' || *p == '\\' || *p == '|' || *p == ':' || (unsigned char)*p < 0x20) *p = '_';
  }
  char *dot = strrchr(name, '.');
  if (dot) {
    for (size_t i = 0; i < sizeof kExts / sizeof kExts[0]; i++) {
      if (strcasecmp(dot + 1, kExts[i]) == 0) {
        *dot = 0;
        break;
      }
    }
  }
  size_t len = strlen(name);
  while (len && (name[len - 1] == ' ' || name[len - 1] == '.')) name[--len] = 0;
  if (!len) snprintf(name, 256, "photo_%u", index);
}

static int parse_jobs(const uint8_t *data, size_t len, job_t **jobs_out, size_t *count_out) {
  size_t cap = 16, count = 0;
  job_t *jobs = (job_t *)malloc(cap * sizeof *jobs);
  if (!jobs) return -1;
  size_t pos = 0;
  if (len >= 3 && memcmp(data, "\xEF\xBB\xBF", 3) == 0) pos = 3;  // UTF-8 BOM
  while (pos < len) {
    size_t end = pos;
    while (end < len && data[end] != '\n') end++;
    size_t a = pos, b = end;
    pos = end + 1;
    while (a < b && (data[a] == ' ' || data[a] == '\t' || data[a] == '\r')) a++;
    while (b > a && (data[b - 1] == ' ' || data[b - 1] == '\t' || data[b - 1] == '\r')) b--;
    if (a == b || data[a] == '#') continue;
    if (data[a] < '0' || data[a] > '9') continue;
    unsigned idx = 0;
    while (a < b && data[a] >= '0' && data[a] <= '9' && idx < 100000000u) idx = idx * 10 + (data[a++] - '0');
    job_t job;
    job.index = idx;
    job.name[0] = 0;
    if (a < b && data[a] == '|') {
      a++;
      while (a < b && data[a] == ' ') a++;
      size_t n = b - a;
      if (n >= sizeof job.name) n = sizeof job.name - 1;
      memcpy(job.name, data + a, n);
      job.name[n] = 0;
    }
    clean_name(job.name, idx);
    if (count == cap) {
      job_t *grown = (job_t *)realloc(jobs, cap * 2 * sizeof *jobs);
      if (!grown) {
        free(jobs);
        return -1;
      }
      jobs = grown;
      cap *= 2;
    }
    jobs[count++] = job;
  }
  *jobs_out = jobs;
  *count_out = count;
  return 0;
}

typedef struct {
  size_t done;
  size_t apple_jpegs;  // originals that Photos sent as JPEG (see run_batch)
  size_t kept;         // originals marked "keep": their HDR isn't in the JXL
  size_t not_iphone;   // HDR photos saved as SDR, gain map not labeled as Apple's
  double bytes_in, bytes_out;
  FILE *done_file;
} batch_t;

// What a converted photo adds to the batch (commit_outcome). Kept apart from
// the conversion so that photos converted at the same time join the batch one
// at a time, in job order.
typedef struct {
  char name_out[64];
  int keep;  // the original had HDR that the JXL lacks: not to be deleted
  int apple_jpeg, not_iphone;
  double bytes_in, bytes_out;
} outcome_t;

// Converts one photo: jxl_in_N.orig to jxl_out_N.jxl, printing its lines.
// Returns 1 and fills `res` when the file was written.
static int process_job(const char *dir, const job_t *job, size_t pos, size_t total,
                       const options_t *opt, outcome_t *res) {
  char name_orig[64], name_png[64], name_out[64];
  snprintf(name_orig, sizeof name_orig, "jxl_in_%u.orig", job->index);
  snprintf(name_png, sizeof name_png, "jxl_in_%u.png", job->index);
  snprintf(name_out, sizeof name_out, "jxl_out_%u.jxl", job->index);
  char *p_orig = path_join(dir, name_orig), *p_png = path_join(dir, name_png);
  char *p_out = path_join(dir, name_out);
  uint8_t *orig = NULL, *png = NULL, *jxl = NULL, *exif = NULL, *xmp = NULL;
  size_t orig_len = 0, png_len = 0, jxl_len = 0, exif_len = 0, xmp_len = 0;
  meta_t mo, mp;
  memset(&mo, 0, sizeof mo);
  memset(&mp, 0, sizeof mp);
  image_t img;
  memset(&img, 0, sizeof img);
  color_t color;
  memset(&color, 0, sizeof color);
  hdr_info_t hdr;
  memset(&hdr, 0, sizeof hdr);
  char err[256] = "";
  int ok = 0;
  const double t0 = now_seconds();

  say("\n[%zu/%zu] %s\n", pos, total, job->name);
  if (!p_orig || !p_png || !p_out) {
    snprintf(err, sizeof err, "out of memory");
    goto done;
  }
  // The original photo provides both pixels and metadata. A PNG converted by
  // Shortcuts (jxl_in_N.png, from older versions of the shortcut) is only
  // used for formats jxlbatch can't decode, such as DNG.
  const int have_orig = read_file(p_orig, &orig, &orig_len) == 0;
  const file_format_t orig_format = have_orig ? detect_format(orig, orig_len) : FMT_UNKNOWN;
  const int decode_orig = orig_format == FMT_HEIF || orig_format == FMT_JPEG || orig_format == FMT_PNG;
  if (!decode_orig && read_file(p_png, &png, &png_len) != 0) {
    if (!have_orig) {
      snprintf(err, sizeof err, "cannot read %s (%s)", name_orig, strerror(errno));
    } else {
      snprintf(err, sizeof err, "unsupported format: only HEIF, JPEG and PNG photos can be converted");
    }
    goto done;
  }
  if ((have_orig && meta_extract(orig, orig_len, &mo, err, sizeof err) != 0) || (png && meta_extract(png, png_len, &mp, err, sizeof err) != 0)) {
    goto done;
  }
  const double orig_size = (double)(have_orig ? orig_len : png_len);
  // With the share sheet's default "Send As: Automatic", Photos converts HEIF
  // to JPEG; count those to remind the user at the end.
  char make[32] = "";
  if (mo.exif.size) exif_string(mo.exif.data, mo.exif.size, 0x010F, make, sizeof make);
  const int apple_jpeg = orig_format == FMT_JPEG && strcmp(make, "Apple") == 0;

  // Metadata to embed: the original's when it has any, else the PNG's.
  const int from_orig = mo.exif.size || mo.xmp.size;
  const blob_t *src_exif = from_orig ? &mo.exif : &mp.exif;
  const blob_t *src_xmp = from_orig ? &mo.xmp : &mp.xmp;
  const int orig_orient = src_exif->size ? exif_orientation(src_exif->data, src_exif->size) : 0;
  uint32_t orig_w = 0, orig_h = 0;
  const int have_dims = src_exif->size && exif_pixel_dims(src_exif->data, src_exif->size, &orig_w, &orig_h);

  // Decode. HEIF comes out upright, and HDR if it has a gain map; JPEG and
  // PNG pixels are as stored, with their orientation in EXIF (or XMP).
  int orient = 1;
  int transposed = 0;  // the stored pixels are turned by a quarter turn
  const file_format_t pixel_format = decode_orig ? orig_format : FMT_PNG;
  if (orig_format == FMT_HEIF) {
    if (heif_decode(orig, orig_len, opt->sdr, &img, &color, &hdr, &transposed, err, sizeof err) != 0) goto done;
    if (hdr.note[0]) say_wrap("  ", "! HDR gain map not used (%s); saved as SDR", hdr.note);
    if (hdr.warning[0]) say_wrap("  ", "! %s", hdr.warning);
  } else {
    // HDR JPEGs (as Photos sends HDR photos with "Send As: Automatic"): the
    // gain map isn't converted.
    if (orig_format == FMT_JPEG && jpeg_has_gain_map(orig, orig_len)) {
      hdr.has_gain_map = 1;
      if (!opt->sdr) {
        say_wrap("  ", opt->mac ? "! HDR not kept (JPEG with a gain map)"
                                : "! HDR not kept (JPEG with a gain map; send as Current to keep it)");
      }
    }
    const meta_t *pm = decode_orig ? &mo : &mp;
    if (stb_decode(decode_orig ? orig : png, decode_orig ? orig_len : png_len, &img, err, sizeof err) != 0) {
      goto done;
    }
    orient = pm->exif.size ? exif_orientation(pm->exif.data, pm->exif.size) : 0;
    if (!orient && pm->xmp.size) orient = xmp_orientation(pm->xmp.data, pm->xmp.size);
    if (!orient) orient = 1;
    transposed = orient >= 5;
    if (pm->icc.size) {
      color.icc.data = (uint8_t *)malloc(pm->icc.size);
      if (!color.icc.data) {
        snprintf(err, sizeof err, "out of memory");
        goto done;
      }
      memcpy(color.icc.data, pm->icc.data, pm->icc.size);
      color.icc.size = pm->icc.size;
    }
    color.cicp_present = pm->png_cicp_present;
    memcpy(color.cicp, pm->png_cicp, sizeof color.cicp);
  }
  free(orig);  // decoded, and the metadata was copied
  orig = NULL;
  free(png);
  png = NULL;
  image_drop_opaque_alpha(&img);
  if (image_orient(&img, orient) != 0) {
    snprintf(err, sizeof err, "out of memory rotating the image");
    goto done;
  }

  // Cross-check against the original's own orientation (warning only), if
  // its EXIF size is the size as stored (the EXIF describes the stored
  // pixels): an edited photo's EXIF keeps the size of the photo before the
  // edit (Photos does so), which can be the result's size transposed.
  const uint32_t stored_w = transposed ? img.h : img.w, stored_h = transposed ? img.w : img.h;
  if (have_dims && orig_orient && orig_w != orig_h && img.w != img.h && orig_w == stored_w && orig_h == stored_h) {
    const int want_portrait = (orig_orient >= 5) ? (orig_w > orig_h) : (orig_h > orig_w);
    const int is_portrait = img.h > img.w;
    if (want_portrait != is_portrait) {
      say_wrap("  ", "! orientation check: the original (%ux%u, orientation %d) should be %s, but the result is %ux%u",
               orig_w, orig_h, orig_orient, want_portrait ? "portrait" : "landscape", img.w, img.h);
    }
  }

  // Private copies of the metadata, patched to match the upright pixels.
  if (src_exif->size) {
    exif = (uint8_t *)malloc(src_exif->size);
    if (!exif) {
      snprintf(err, sizeof err, "out of memory");
      goto done;
    }
    memcpy(exif, src_exif->data, src_exif->size);
    exif_len = src_exif->size;
    exif_patch(exif, exif_len, img.w, img.h);
  }
  if (src_xmp->size) {
    xmp = (uint8_t *)malloc(src_xmp->size);
    if (!xmp) {
      snprintf(err, sizeof err, "out of memory");
      goto done;
    }
    memcpy(xmp, src_xmp->data, src_xmp->size);
    xmp_len = src_xmp->size;
    if (xmp_reset_orientation(&xmp, &xmp_len) < 0) {
      snprintf(err, sizeof err, "out of memory");
      goto done;
    }
  }

  encode_meta_t em = {&color, exif, exif_len, xmp, xmp_len, hdr.peak * GAINMAP_SDR_WHITE_NITS};
  if (encode_jxl(&img, &em, opt, &jxl, &jxl_len, err, sizeof err) != 0) goto done;
  if (write_file(p_out, jxl, jxl_len) != 0) {
    snprintf(err, sizeof err, "cannot write %s (%s)", name_out, strerror(errno));
    goto done;
  }
  // The original is kept (not offered for deletion) when it had HDR that
  // the JXL lacks, except a gain map not labeled as Apple's: the owner's
  // choice.
  snprintf(res->name_out, sizeof res->name_out, "%s", name_out);
  res->keep = hdr.has_gain_map && !(hdr.headroom > 0) && !hdr.not_iphone;
  res->apple_jpeg = apple_jpeg;
  res->not_iphone = hdr.not_iphone;
  res->bytes_in = orig_size;
  res->bytes_out = (double)jxl_len;
  ok = 1;

  {
    // e.g. "HEIF 3024x4032, HDR 3.5×" and "2.4 MB -> 1.2 MB (50%), 4.1 s"
    char in_s[32], out_s[32], depth[32] = "";
    fmt_bytes(in_s, sizeof in_s, orig_size);
    fmt_bytes(out_s, sizeof out_s, (double)jxl_len);
    if (hdr.headroom > 0) {
      snprintf(depth, sizeof depth, ", HDR %.1f\u00d7", hdr.headroom);
    } else if (img.bits > 8) {
      snprintf(depth, sizeof depth, ", 10-bit");
    }
    say_wrap("  ", "%s %ux%u%s%s%s", format_name(orig_format == FMT_UNKNOWN ? pixel_format : orig_format), img.w,
             img.h, depth, img.channels == 2 || img.channels == 4 ? ", alpha" : "",
             exif_len || xmp_len ? "" : ", no metadata");
    say_wrap("  ", "%s -> %s (%.0f%%), %.1f s", in_s, out_s, orig_size > 0 ? 100.0 * jxl_len / orig_size : 0.0,
             now_seconds() - t0);
  }

done:
  if (!ok) say_wrap("  ", "FAILED: %s", err);
  image_free(&img);
  color_free(&color);
  meta_free(&mo);
  meta_free(&mp);
  free(orig);
  free(png);
  free(jxl);
  free(exif);
  free(xmp);
  free(p_orig);
  free(p_png);
  free(p_out);
  return ok;
}

// Adds a converted photo to the batch: its line in jxl_done.txt and the
// counts. "file|index|delete or keep|name": the shortcut saves `file` as
// `name`, and after saving may delete the photo at position `index` of the
// ones it staged, unless marked "keep". (Older shortcuts read only the first
// and last fields.) No trailing newline: Shortcuts' Split Text would yield an
// empty item. Returns 0 when the line can't be written: the photo then counts
// as failed (its file stays, unused).
static int commit_outcome(batch_t *batch, const char *dir, const job_t *job, const outcome_t *res) {
  if (!batch->done_file) {
    char *p_done = path_join(dir, DONE_FILE);
    batch->done_file = p_done ? fopen(p_done, "w") : NULL;
    free(p_done);
    if (!batch->done_file) {
      say_wrap("  ", "FAILED: cannot write %s (%s)", DONE_FILE, strerror(errno));
      return 0;
    }
  }
  fprintf(batch->done_file, "%s%s|%u|%s|%s.jxl", batch->done ? "\n" : "", res->name_out, job->index,
          res->keep ? "keep" : "delete", job->name);
  fflush(batch->done_file);
  batch->done++;
  batch->kept += res->keep;
  batch->apple_jpegs += res->apple_jpeg;
  batch->not_iphone += res->not_iphone;
  batch->bytes_in += res->bytes_in;
  batch->bytes_out += res->bytes_out;
  return 1;
}

// One photo after the other, on this thread.
static void serial_batch(const char *dir, const job_t *jobs, size_t count, const options_t *opt,
                         batch_t *batch) {
  for (size_t i = 0; i < count; i++) {
    outcome_t res;
    if (process_job(dir, &jobs[i], i + 1, count, opt, &res)) commit_outcome(batch, dir, &jobs[i], &res);
  }
}

#ifdef JXLBATCH_THREADS
// Parallel conversion (-j): `workers` threads each take the next photo, with
// a libjxl thread pool of their own (a pool serves one encoder at a time) and
// say() writing to the photo's buffer. Finished photos join the batch in job
// order, each printed as one block, so the output and jxl_done.txt read as
// with one photo at a time; a photo's lines appear once the photos before it
// are done.

static int cpu_count(void) {
  const size_t n = JxlThreadParallelRunnerDefaultNumWorkerThreads();
  return n >= 1 && n <= 1024 ? (int)n : 1;
}

static void *runner_create(int threads) {
  return threads > 1 ? JxlThreadParallelRunnerCreate(NULL, (size_t)threads) : NULL;
}

// -j 0: how many photos to convert at a time. One photo keeps about half of
// the cores busy on average (decoding, the gain map and the metadata run on
// one thread, only libjxl's encoder on all of them), so a few at a time fill
// the rest: one per 5 cores, at most 3 (beyond that the cores are shared
// again and the memory adds up: each photo holds its decoded pixels, up to
// about 1 GB for a 48 MP HDR photo), and one per 4 GB of memory.
static int auto_workers(size_t count) {
  int n = (cpu_count() + 2) / 5;  // 8 cores: 2; 14: 3
  const long pages = sysconf(_SC_PHYS_PAGES), page = sysconf(_SC_PAGESIZE);
  if (pages > 0 && page > 0) {
    const double gb = (double)pages * (double)page / (1024.0 * 1024 * 1024);
    if (n > (int)(gb / 4)) n = (int)(gb / 4);
  }
  if (n > 3) n = 3;
  if (n < 1) n = 1;
  if (count && (size_t)n > count) n = (int)count;
  return n;
}

// How many photos to convert at a time and with how many threads each, from
// -j and -t: by default one at a time with all the cores (as the builds
// without threads do, one thread).
static void plan_threads(const options_t *opt, size_t count, int *workers, int *threads) {
  *workers = opt->jobs > 0 ? opt->jobs : auto_workers(count);
  if (count && (size_t)*workers > count) *workers = (int)count;
  if (*workers < 1) *workers = 1;
  *threads = opt->threads > 0 ? opt->threads : (cpu_count() + *workers - 1) / *workers;
}

typedef struct {
  textbuf_t out;  // the photo's lines
  outcome_t res;
  int ok, finished;
} slot_t;

typedef struct {
  const char *dir;
  const options_t *opt;
  const job_t *jobs;
  size_t count;
  batch_t *batch;
  int threads;       // per worker
  size_t next;       // the next photo to take
  size_t committed;  // photos 0..committed-1 have joined the batch
  slot_t *slots;     // one per photo
  pthread_mutex_t lock;
} pool_t;

static void *pool_worker(void *arg) {
  pool_t *pool = (pool_t *)arg;
  t_runner = runner_create(pool->threads);
  for (;;) {
    pthread_mutex_lock(&pool->lock);
    const size_t i = pool->next < pool->count ? pool->next++ : pool->count;
    pthread_mutex_unlock(&pool->lock);
    if (i >= pool->count) break;
    slot_t *s = &pool->slots[i];
    t_out = &s->out;
    s->ok = process_job(pool->dir, &pool->jobs[i], i + 1, pool->count, pool->opt, &s->res);
    t_out = NULL;
    pthread_mutex_lock(&pool->lock);
    s->finished = 1;
    while (pool->committed < pool->count && pool->slots[pool->committed].finished) {
      slot_t *done = &pool->slots[pool->committed];
      if (done->out.data) fwrite(done->out.data, 1, done->out.len, stdout);
      fflush(stdout);
      free(done->out.data);
      done->out.data = NULL;
      if (done->ok) commit_outcome(pool->batch, pool->dir, &pool->jobs[pool->committed], &done->res);
      pool->committed++;
    }
    pthread_mutex_unlock(&pool->lock);
  }
  if (t_runner) JxlThreadParallelRunnerDestroy(t_runner);
  t_runner = NULL;
  return NULL;
}

// Returns -1 (nothing converted) only when out of memory.
static int parallel_batch(const char *dir, const job_t *jobs, size_t count, const options_t *opt,
                          batch_t *batch, int workers, int threads) {
  pool_t pool = {dir, opt, jobs, count, batch, threads, 0, 0, NULL, PTHREAD_MUTEX_INITIALIZER};
  pool.slots = (slot_t *)calloc(count ? count : 1, sizeof *pool.slots);
  pthread_t *tids = (pthread_t *)calloc((size_t)workers, sizeof *tids);
  if (!pool.slots || !tids) {
    free(pool.slots);
    free(tids);
    return -1;
  }
  int started = 0;
  while (started < workers && pthread_create(&tids[started], NULL, pool_worker, &pool) == 0) started++;
  if (!started) pool_worker(&pool);  // no threads to be had: this thread does the work
  for (int w = 0; w < started; w++) pthread_join(tids[w], NULL);
  free(tids);
  free(pool.slots);
  return 0;
}
#endif

// Finds the folder holding `job`: -C, the current folder, $PWD, $SHORTCUTS.
// In a-Shell, relative paths are the reliable choice: its WASI layer opens
// them from the shell's current folder (which a-Shell sets to the Shortcuts
// folder before running a shortcut's commands), while absolute paths outside
// the current folder lose their leading "/" and fail.
// Says where the job was looked for, so a failure in a-Shell shows why.
static void say_not_found(const options_t *opt, const char *job) {
  const char *pwd = getenv("PWD"), *shortcuts = getenv("SHORTCUTS");
  say("ERROR: cannot find %s\nLooked in:\n", job);
  if (opt->dir) say("  -C (%s)\n", opt->dir);
  say("  the current folder\n");
  say("  $PWD (%s)\n", pwd && *pwd ? pwd : "not set");
  say("  $SHORTCUTS (%s)\n", shortcuts && *shortcuts ? shortcuts : "not set");
}

// 1 if a JPEG XL file stores ICC profile `icc` (not libjxl's own
// description of the color).
static int jxl_has_profile(const uint8_t *jxl, size_t len, const blob_t *icc) {
  JxlDecoder *dec = JxlDecoderCreate(NULL);
  int found = 0;
  if (dec && JxlDecoderSubscribeEvents(dec, JXL_DEC_COLOR_ENCODING) == JXL_DEC_SUCCESS &&
      JxlDecoderSetInput(dec, jxl, len) == JXL_DEC_SUCCESS) {
    JxlDecoderCloseInput(dec);
    JxlDecoderStatus st;
    while ((st = JxlDecoderProcessInput(dec)) != JXL_DEC_COLOR_ENCODING && st != JXL_DEC_ERROR &&
           st != JXL_DEC_SUCCESS && st != JXL_DEC_NEED_MORE_INPUT) {
    }
    JxlColorEncoding ce;
    size_t size = 0;
    uint8_t *got = NULL;
    // A stored profile has no description as a color encoding.
    if (st == JXL_DEC_COLOR_ENCODING &&
        JxlDecoderGetColorAsEncodedProfile(dec, JXL_COLOR_PROFILE_TARGET_ORIGINAL, &ce) != JXL_DEC_SUCCESS &&
        JxlDecoderGetICCProfileSize(dec, JXL_COLOR_PROFILE_TARGET_ORIGINAL, &size) == JXL_DEC_SUCCESS &&
        size == icc->size && (got = (uint8_t *)malloc(size)) != NULL &&
        JxlDecoderGetColorAsICCProfile(dec, JXL_COLOR_PROFILE_TARGET_ORIGINAL, got, size) == JXL_DEC_SUCCESS) {
      found = memcmp(got, icc->data, size) == 0;
    }
    free(got);
  }
  if (dec) JxlDecoderDestroy(dec);
  return found;
}

static int file_exists(const char *dir, const char *name) {
  char *path = path_join(dir, name);
  FILE *f = path ? fopen(path, "rb") : NULL;
  free(path);
  if (f) fclose(f);
  return f != NULL;
}

static char *find_dir(const options_t *opt, const char *job) {
  const char *candidates[] = {opt->dir, ".", getenv("PWD"), getenv("SHORTCUTS")};
  for (size_t i = 0; i < sizeof candidates / sizeof candidates[0]; i++) {
    const char *c = candidates[i];
    if (!c || !*c) continue;
    char *path = path_join(strcmp(c, ".") == 0 ? NULL : c, job);
    if (!path) return NULL;
    FILE *f = fopen(path, "rb");
    free(path);
    if (f) {
      fclose(f);
      return strdup(c);
    }
  }
  return NULL;
}

// Full version details, for --version and --selftest.
static void print_header(const options_t *opt) {
  uint32_t v = JxlEncoderVersion();
  char heif[64];
  heif_decoder_version(heif, sizeof heif);
  say_wrap("", "jxlbatch %s (libjxl %u.%u.%u, %s, %s)", JXLBATCH_VERSION, v / 1000000, (v / 1000) % 1000, v % 1000,
           heif, BUILD_KIND);
  if (opt->quality >= 100.0f) {
    say_wrap("", "quality 100 (lossless), effort %d", opt->effort);
  } else {
    say_wrap("", "quality %g (distance %.2f), effort %d", opt->quality, JxlEncoderDistanceFromQuality(opt->quality),
             opt->effort);
  }
}

static int run_batch(const options_t *opt, const char *job_arg) {
  char *dir = NULL;
  const char *job = job_arg;
  const char *slash = strrchr(job_arg, '/');
  if (slash) {
    dir = strndup(job_arg, (size_t)(slash - job_arg) + (slash == job_arg ? 1 : 0));
    job = slash + 1;
  } else {
    dir = find_dir(opt, job_arg);
  }
  if (!dir) {
    say_not_found(opt, job_arg);
    return 1;
  }
  const char *dir_for_files = strcmp(dir, ".") == 0 ? NULL : dir;
  if (opt->retry && file_exists(dir_for_files, STARTED_FILE)) {
    free(dir);
    return 0;
  }
  char *job_path = path_join(dir_for_files, job);
  uint8_t *data = NULL;
  size_t len = 0;
  job_t *jobs = NULL;
  size_t count = 0;
  if (!job_path || read_file(job_path, &data, &len) != 0) {
    say_wrap("", "ERROR: cannot read %s (%s)", job_path ? job_path : job, strerror(errno));
    return 1;
  }
  if (parse_jobs(data, len, &jobs, &count) != 0) {
    say("ERROR: out of memory\n");
    return 1;
  }
  free(data);
  char *started = path_join(dir_for_files, STARTED_FILE);
  if (started) write_file(started, (const uint8_t *)"", 0);
  free(started);
  // How the cores are used, when it isn't one photo at a time on all of them.
  char how[64] = "";
#ifdef JXLBATCH_THREADS
  int workers = 1, threads = 1;
  plan_threads(opt, count, &workers, &threads);
  if (workers > 1) {
    snprintf(how, sizeof how, ", %d at a time (%d thread%s each)", workers, threads, threads == 1 ? "" : "s");
  } else if (threads == 1) {
    snprintf(how, sizeof how, ", 1 thread");
  }
#endif
  if (opt->quality >= 100.0f) {
    say_wrap("", "jxlbatch: %zu photo%s, lossless, effort %d%s", count, count == 1 ? "" : "s", opt->effort, how);
  } else {
    say_wrap("", "jxlbatch: %zu photo%s, quality %g, effort %d%s", count, count == 1 ? "" : "s", opt->quality,
             opt->effort, how);
  }

  batch_t batch;
  memset(&batch, 0, sizeof batch);
  const double t0 = now_seconds();
#ifdef JXLBATCH_THREADS
  if (workers == 1 || parallel_batch(dir_for_files, jobs, count, opt, &batch, workers, threads) != 0) {
    t_runner = runner_create(threads);
    serial_batch(dir_for_files, jobs, count, opt, &batch);
    if (t_runner) JxlThreadParallelRunnerDestroy(t_runner);
    t_runner = NULL;
  }
#else
  serial_batch(dir_for_files, jobs, count, opt, &batch);
#endif
  if (batch.done_file) fclose(batch.done_file);

  char in_s[32], out_s[32];
  fmt_bytes(in_s, sizeof in_s, batch.bytes_in);
  fmt_bytes(out_s, sizeof out_s, batch.bytes_out);
  say("\n");
  say_wrap("", "Done: %zu of %zu converted in %.0f s", batch.done, count, now_seconds() - t0);
  if (batch.done) {
    say_wrap("", "%s -> %s (%.0f%%)", in_s, out_s, batch.bytes_in > 0 ? 100.0 * batch.bytes_out / batch.bytes_in : 0.0);
  }
  if (batch.done < count) {
    say_wrap("", "%zu failed; see the messages above.", count - batch.done);
  }
  if (batch.kept) {
    const int one = batch.kept == 1;
    say_wrap("", "%zu original%s kept: %s HDR isn't in the JXL.", batch.kept, one ? "" : "s", one ? "its" : "their");
  }
  if (batch.not_iphone) {
    const int one = batch.not_iphone == 1;
    say_wrap("", "%zu HDR photo%s saved as SDR (not an iPhone camera photo); %s offered for deletion.",
             batch.not_iphone, one ? "" : "s", one ? "its original is" : "their originals are");
  }
  // On the Mac the shortcuts hand over the library's files as they are, so a
  // JPEG is the original; the hint is about the iPhone's share sheet.
  if (batch.apple_jpegs && !opt->mac) {
    const int one = batch.apple_jpegs == 1;
    say("\n");
    say_wrap("", "Note: Photos sent %s iPhone photo%s as JPEG, so the sizes compare against %s, not the "
             "original HEIF. To send originals, run the shortcut from the Shortcuts app and pick the photos "
             "there, or set Options > Send As > Current in the share sheet.",
             one ? "this" : "these", one ? "" : "s", one ? "that JPEG" : "those JPEGs");
  }
  free(jobs);
  free(job_path);
  free(dir);
  return batch.done > 0 ? 0 : 1;
}

// ---------------------------------------------------------------------------
// Self-test (run once in a-Shell after installing)

static void selftest_io(const char *label, const char *dir) {
  if (!dir || !*dir) {
    say("  %-12s (not set)\n", label);
    return;
  }
  char *path = path_join(strcmp(dir, ".") == 0 ? NULL : dir, "jxlbatch_selftest.tmp");
  const char *msg = "ok";
  FILE *f = path ? fopen(path, "wb") : NULL;
  if (!f) {
    msg = "cannot create a file";
  } else {
    fputs("jxlbatch", f);
    fclose(f);
    uint8_t *back = NULL;
    size_t n = 0;
    if (read_file(path, &back, &n) != 0 || n != 8 || memcmp(back, "jxlbatch", 8) != 0) {
      msg = "wrote a file but could not read it back";
    } else if (remove(path) != 0) {
      msg = "read/write ok, delete failed";
    }
    free(back);
  }
  say("  %-12s %s: %s%s%s\n", label, dir, msg, strcmp(msg, "ok") ? " - " : "", strcmp(msg, "ok") ? strerror(errno) : "");
  free(path);
}

// Writes and reads back a photo-sized file, the way a batch does.
static int selftest_large_io(const char *dir) {
  const size_t n = 8 << 20;
  char *path = path_join(strcmp(dir, ".") == 0 ? NULL : dir, "jxlbatch_selftest.big");
  uint8_t *data = (uint8_t *)malloc(n), *back = NULL;
  size_t back_len = 0;
  if (!path || !data) {
    say("\nERROR: out of memory\n");
    return -1;
  }
  uint32_t seed = 42;
  for (size_t i = 0; i < n; i++) {
    seed = seed * 1664525u + 1013904223u;
    data[i] = (uint8_t)(seed >> 24);
  }
  say("\nLarge file (8 MB) in the current folder:\n");
  double t0 = now_seconds();
  int rc = write_file(path, data, n);
  const double t_write = now_seconds() - t0;
  if (rc != 0) {
    say("  write FAILED: %s\n", strerror(errno));
  } else {
    t0 = now_seconds();
    rc = read_file(path, &back, &back_len);
    const double t_read = now_seconds() - t0;
    if (rc != 0) {
      say("  read FAILED: %s\n", strerror(errno));
    } else if (back_len != n || memcmp(back, data, n) != 0) {
      say("  FAILED: read back %zu bytes that differ from what was written\n", back_len);
      rc = -1;
    } else {
      say("  ok: write %.1f s, read %.1f s\n", t_write, t_read);
    }
  }
  remove(path);
  free(back);
  free(data);
  free(path);
  return rc;
}

// Decodes the embedded 96x64 HEIC and checks its four colored quadrants.
static int selftest_heif(void) {
  image_t img;
  color_t color;
  hdr_info_t hdr;
  char err[256] = "";
  say("\nHEIF decoding:\n");
  if (heif_decode(kSelftestHeic, sizeof kSelftestHeic, 0, &img, &color, &hdr, NULL, err, sizeof err) != 0) {
    say("  FAILED: %s\n", err);
    return -1;
  }
  static const uint8_t want[4][3] = {{220, 30, 30}, {30, 200, 30}, {30, 30, 220}, {240, 240, 240}};
  static const uint32_t at[4][2] = {{24, 16}, {72, 16}, {24, 48}, {72, 48}};
  int bad = img.w != 96 || img.h != 64 || img.bytes_per_sample != 1;
  for (int q = 0; q < 4 && !bad; q++) {
    const uint8_t *px = img.data + at[q][1] * img.stride + at[q][0] * pixel_size(&img);
    for (int c = 0; c < 3; c++) bad |= abs((int)px[c] - (int)want[q][c]) > 24;
  }
  if (bad) {
    say("  FAILED: decoded %ux%u image does not match the test pattern\n", img.w, img.h);
  } else {
    say("  ok\n");
  }
  image_free(&img);
  color_free(&color);
  return bad ? -1 : 0;
}

// Decodes the embedded HDR HEIC (with a gain map and Apple's HDR profile) and
// checks its HDR pixels, then that the profile is kept in a JPEG XL.
static int selftest_hdr(const options_t *opt) {
  image_t img;
  color_t color;
  hdr_info_t hdr;
  char err[256] = "";
  say("\nHDR decoding:\n");
  if (heif_decode(kSelftestHdrHeic, sizeof kSelftestHdrHeic, 0, &img, &color, &hdr, NULL, err, sizeof err) != 0) {
    say("  FAILED: %s\n", err);
    return -1;
  }
  int bad = 0;
  if (hdr.note[0] || fabs(hdr.headroom - kSelftestHdrHeadroom) > 0.01 || img.w != 64 || img.h != 48) {
    say_wrap("  ", "FAILED: not decoded as HDR (%ux%u, headroom %.3f; %s)", img.w, img.h, hdr.headroom,
             hdr.note[0] ? hdr.note : "no note");
    bad = 1;
  }
  for (size_t i = 0; !bad && i < sizeof kSelftestHdrPixels / sizeof kSelftestHdrPixels[0]; i++) {
    const unsigned *want = kSelftestHdrPixels[i];
    uint16_t px[4];
    if (img.render(img.owner, want[0], want[1], 1, 1, (uint8_t *)px, sizeof px) != 0) {
      say("  FAILED: out of memory\n");
      bad = 1;
      break;
    }
    for (int c = 0; c < 3; c++) {
      if (abs((int)px[c] - (int)want[2 + c]) > 2) {
        say_wrap("  ", "FAILED: HDR pixel (%u, %u) is %u/%u/%u, expected %u/%u/%u", want[0], want[1], px[0], px[1],
                 px[2], want[2], want[3], want[4]);
        bad = 1;
        break;
      }
    }
  }
  if (!bad) say_wrap("  ", "ok: HDR %.1f\u00d7, %u nits peak", hdr.headroom, (unsigned)(hdr.peak * GAINMAP_SDR_WHITE_NITS + 0.5));
  if (!bad && color.hdr_icc.size != kSelftestHdrProfileSize) {
    say("  FAILED: Apple's HDR profile not found\n");
    bad = 1;
  }
  if (!bad) {
    encode_meta_t em = {&color, NULL, 0, NULL, 0, hdr.peak * GAINMAP_SDR_WHITE_NITS};
    uint8_t *out = NULL;
    size_t out_len = 0;
    if (encode_jxl(&img, &em, opt, &out, &out_len, err, sizeof err) != 0) {
      say("  FAILED: %s\n", err);
      bad = 1;
    } else if (!jxl_has_profile(out, out_len, &color.hdr_icc)) {
      // libjxl stored its own description of the color instead
      say("  FAILED: Apple's HDR profile not kept in the JPEG XL\n");
      bad = 1;
    } else {
      say("  ok: Apple's HDR profile kept\n");
    }
    free(out);
  }
  image_free(&img);
  color_free(&color);
  return bad ? -1 : 0;
}

static int selftest(const options_t *opt) {
  print_header(opt);
  say("\nEnvironment:\n  PWD=%s\n  SHORTCUTS=%s\n  HOME=%s\n", getenv("PWD") ? getenv("PWD") : "(unset)",
      getenv("SHORTCUTS") ? getenv("SHORTCUTS") : "(unset)", getenv("HOME") ? getenv("HOME") : "(unset)");
  say("\nFile access:\n");
  if (opt->dir) selftest_io("-C", opt->dir);
  selftest_io("relative", ".");
  selftest_io("$PWD", getenv("PWD"));
  selftest_io("$SHORTCUTS", getenv("SHORTCUTS"));
  if (selftest_large_io(opt->dir ? opt->dir : ".") != 0) return 1;
  if (selftest_heif() != 0) return 1;
  if (selftest_hdr(opt) != 0) return 1;

  // Synthetic 12 MP photo-like image: smooth gradients plus sensor-like noise.
  const uint32_t w = 4032, h = 3024;
  image_t img;
  memset(&img, 0, sizeof img);
  img.w = w;
  img.h = h;
  img.channels = 3;
  img.bytes_per_sample = 1;
  img.bits = 8;
  img.stride = (size_t)w * 3;
  img.data = (uint8_t *)malloc(img.stride * h);
  if (!img.data) {
    say("\nERROR: cannot allocate a 12 MP test image\n");
    return 1;
  }
  uint32_t seed = 12345;
  for (uint32_t y = 0; y < h; y++) {
    for (uint32_t x = 0; x < w; x++) {
      seed = seed * 1664525u + 1013904223u;
      int noise = (int)((seed >> 24) & 15) - 8;
      uint8_t *p = img.data + ((size_t)y * w + x) * 3;
      int r = (int)(x * 255 / w) + noise, g = (int)(y * 255 / h) + noise, b = 128 + ((int)(x / 64 + y / 64) % 2) * 60 + noise;
      p[0] = (uint8_t)(r < 0 ? 0 : r > 255 ? 255 : r);
      p[1] = (uint8_t)(g < 0 ? 0 : g > 255 ? 255 : g);
      p[2] = (uint8_t)(b < 0 ? 0 : b > 255 ? 255 : b);
    }
  }
  say("\nEncoding a synthetic 12 MP image at quality %g, effort %d...\n", opt->quality, opt->effort);
  encode_meta_t em;
  memset(&em, 0, sizeof em);
  uint8_t *out = NULL;
  size_t out_len = 0;
  char err[256] = "";
  const double t0 = now_seconds();
  if (encode_jxl(&img, &em, opt, &out, &out_len, err, sizeof err) != 0) {
    say("  FAILED: %s\n", err);
    image_free(&img);
    return 1;
  }
  const double secs = now_seconds() - t0;
  char out_s[32];
  fmt_bytes(out_s, sizeof out_s, (double)out_len);
  say("  ok: %s in %.1f s (%.2f MP/s)\n", out_s, secs, (w * (double)h / 1e6) / secs);
  free(out);
  image_free(&img);
  say("\nSelf-test passed.\n");
  return 0;
}

// Grows the heap in 64 MB steps to find how much memory the runtime allows.
static int memtest(void) {
  enum { kStep = 64 << 20, kMax = 24 };
  void *blocks[kMax];
  int n = 0;
  say("Allocating memory in 64 MB steps (up to 1.5 GB)...\n");
  for (; n < kMax; n++) {
    blocks[n] = malloc(kStep);
    if (!blocks[n]) break;
    memset(blocks[n], 1, kStep);
    say("  %d MB\n", (n + 1) * 64);
  }
  say("Reached %d MB.\n", n * 64);
  for (int i = 0; i < n; i++) free(blocks[i]);
  return 0;
}

static void usage(void) {
  say("usage: jxlbatch [--retry] [--sdr] [--mac] [-q QUALITY] [-e EFFORT] [-j PHOTOS] [-t THREADS] [-C DIR] JOBFILE\n"
      "       jxlbatch --selftest [-q QUALITY] [-e EFFORT] [-t THREADS] [-C DIR]\n"
      "       jxlbatch --memtest | --version\n\n"
      "  -q  JPEG XL quality, 1-100 (default 83; 100 = lossless)\n"
      "  -e  encoder effort, 1-10 (default 7; lower is faster)\n"
      "  -j  photos converted at a time, 0-64 (default 1; 0: from the number of cores)\n"
      "  -t  threads per photo, 0-64 (default 0: the cores, shared by the photos)\n"
#ifndef JXLBATCH_THREADS
      "      (this build has no threads: -j and -t change nothing)\n"
#endif
      "  -C  folder holding JOBFILE and the jxl_in_* files\n"
      "  --retry  do nothing if a run already started this batch\n"
      "  --sdr    save HDR photos as SDR (their originals are marked to keep)\n"
      "  --mac    for the Mac shortcuts: no hints about the iPhone's share sheet\n");
}

int main(int argc, char **argv) {
  options_t opt = {83.0f, 7, NULL, 0, 0, 0, 1, 0};
  const char *job = NULL;
  int mode = 0;  // 0 = batch, 1 = selftest, 2 = memtest
  for (int i = 1; i < argc; i++) {
    const char *a = argv[i];
    if ((!strcmp(a, "-q") || !strcmp(a, "-e") || !strcmp(a, "-C") || !strcmp(a, "-j") || !strcmp(a, "-t")) &&
        i + 1 < argc) {
      const char *v = argv[++i];
      char *end = NULL;
      if (a[1] == 'q') {
        char num[32];
        snprintf(num, sizeof num, "%s", v);
        char *comma = strchr(num, ',');  // Shortcuts may format "83,5" in some locales
        if (comma) *comma = '.';
        v = num;
        opt.quality = strtof(v, &end);
        if (end == v || *end || opt.quality <= 0 || opt.quality > 100) {
          say("ERROR: quality must be between 1 and 100 (got \"%s\")\n", v);
          return 2;
        }
      } else if (a[1] == 'e') {
        long e = strtol(v, &end, 10);
        if (end == v || *end || e < 1 || e > 10) {
          say("ERROR: effort must be between 1 and 10 (got \"%s\")\n", v);
          return 2;
        }
        opt.effort = (int)e;
      } else if (a[1] == 'j' || a[1] == 't') {
        long n = strtol(v, &end, 10);
        if (end == v || *end || n < 0 || n > 64) {
          say("ERROR: %s must be between 0 and 64 (got \"%s\")\n", a, v);
          return 2;
        }
        if (a[1] == 'j') {
          opt.jobs = (int)n;
        } else {
          opt.threads = (int)n;
        }
      } else {
        opt.dir = v;
      }
    } else if (!strcmp(a, "--retry")) {
      opt.retry = 1;
    } else if (!strcmp(a, "--sdr")) {
      opt.sdr = 1;
    } else if (!strcmp(a, "--mac")) {
      opt.mac = 1;
    } else if (!strcmp(a, "--selftest")) {
      mode = 1;
    } else if (!strcmp(a, "--memtest")) {
      mode = 2;
    } else if (!strcmp(a, "--version")) {
      print_header(&opt);
      return 0;
    } else if (!strcmp(a, "-h") || !strcmp(a, "--help")) {
      usage();
      return 0;
    } else if (a[0] != '-' && !job) {
      job = a;
    } else {
      usage();
      return 2;
    }
  }
  int rc;
  if (mode == 1) {
#ifdef JXLBATCH_THREADS
    t_runner = runner_create(opt.threads > 0 ? opt.threads : cpu_count());  // a batch plans its own
#endif
    rc = selftest(&opt);
  } else if (mode == 2) {
    rc = memtest();
  } else if (!job) {
    usage();
    rc = 2;
  } else {
    rc = run_batch(&opt, job);
  }
#ifdef JXLBATCH_THREADS
  if (t_runner) JxlThreadParallelRunnerDestroy(t_runner);
#endif
  return rc;
}
