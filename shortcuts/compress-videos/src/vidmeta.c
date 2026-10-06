// vidmeta: the metadata helper of Compress Videos (macOS).
//
// After ffmpeg has converted a video, `vidmeta copy` copies the original's
// Apple metadata into the copy, byte for byte (mp4meta.c), so every value
// keeps its type: the movie's keys (capture date with its time zone, location,
// make, model, software...), the video track's keys (lens model, focal length,
// f-number, Apple's maker notes) and the creation and modification times.
// ffmpeg can't do this itself: it writes the movie's keys back as unnamed text
// entries, and drops the video track's. `vidmeta key` prints one of the
// movie's keys, which ffprobe can misread (it reads an iPhone's 8-byte
// integers as 0).
//
// Usage: vidmeta copy ORIGINAL CONVERTED   (CONVERTED must end with its moov)
//        vidmeta key FILE KEY              (exit status 1: no such key)
//        vidmeta --version
//        vidmeta --selftest
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "mp4meta.h"

#ifndef VIDMETA_VERSION
#define VIDMETA_VERSION "dev"
#endif

static int usage(void) {
  fprintf(stderr,
          "usage: vidmeta copy ORIGINAL CONVERTED\n"
          "       vidmeta key FILE KEY\n"
          "       vidmeta --version\n"
          "       vidmeta --selftest\n");
  return 2;
}

static int copy(const char *original, const char *converted) {
  char err[512] = "";
  const int copied = mp4meta_copy(original, converted, err, sizeof err);
  if (copied < 0) {
    fprintf(stderr, "vidmeta: %s\n", err);
    return 1;
  }
  printf("copied %d boxes\n", copied);
  return 0;
}

// Prints the value of one of the movie's keys; nothing, and exit status 1,
// when the file doesn't have it.
static int key(const char *path, const char *name) {
  static char value[65536];
  char err[512] = "";
  const int found = mp4meta_key(path, name, value, sizeof value, err, sizeof err);
  if (found < 0) fprintf(stderr, "vidmeta: %s\n", err);
  if (found <= 0) return 1;
  printf("%s\n", value);
  return 0;
}

// ---------------------------------------------------------------------------
// The self-test: two minimal MP4 files written here, the "original" with
// Apple keys on the movie and on its video track, and a "converted" one with
// ffmpeg's own boxes and other times; vidmeta copies the first's metadata
// onto the second, which is then read back, and its date key read by name.

typedef struct {
  uint8_t *data;
  size_t size, cap;
  int failed;
} out_t;

static void put(out_t *o, const void *data, size_t len) {
  if (o->size + len > o->cap) {
    size_t cap = o->cap ? o->cap * 2 : 1024;
    while (cap < o->size + len) cap *= 2;
    uint8_t *p = realloc(o->data, cap);
    if (!p) {
      o->failed = 1;
      return;
    }
    o->data = p;
    o->cap = cap;
  }
  memcpy(o->data + o->size, data, len);
  o->size += len;
}

static void put32(out_t *o, uint32_t v) {
  const uint8_t b[4] = {(uint8_t)(v >> 24), (uint8_t)(v >> 16), (uint8_t)(v >> 8), (uint8_t)v};
  put(o, b, 4);
}

static void put64(out_t *o, uint64_t v) {
  put32(o, (uint32_t)(v >> 32));
  put32(o, (uint32_t)v);
}

static void zeros(out_t *o, size_t len) {
  static const uint8_t z[64];
  while (len) {
    const size_t n = len < sizeof z ? len : sizeof z;
    put(o, z, n);
    len -= n;
  }
}

// begin_box returns where the box starts; end_box writes its size there.
static size_t begin_box(out_t *o, const char *type) {
  const size_t start = o->size;
  put32(o, 0);
  put(o, type, 4);
  return start;
}

static void end_box(out_t *o, size_t start) {
  if (o->failed) return;
  const uint32_t size = (uint32_t)(o->size - start);
  o->data[start] = (uint8_t)(size >> 24);
  o->data[start + 1] = (uint8_t)(size >> 16);
  o->data[start + 2] = (uint8_t)(size >> 8);
  o->data[start + 3] = (uint8_t)size;
}

// An mvhd, tkhd or mdhd box: version 0 (32-bit times) or 1 (64-bit), the
// creation and modification times, then `rest` zero bytes (version 0's sizes:
// mvhd 88, tkhd 72, mdhd 12; version 1 adds 4 for the longer duration).
static void timed_box(out_t *o, const char *type, int version, uint64_t created, uint64_t modified,
                      size_t rest) {
  const size_t b = begin_box(o, type);
  put32(o, (uint32_t)version << 24);
  if (version == 1) {
    put64(o, created);
    put64(o, modified);
  } else {
    put32(o, (uint32_t)created);
    put32(o, (uint32_t)modified);
  }
  zeros(o, rest + (version == 1 ? 4 : 0));
  end_box(o, b);
}

// A QuickTime metadata box with one UTF-8 key, as iPhones write them.
static void meta_box(out_t *o, const char *key, const char *value) {
  const size_t meta = begin_box(o, "meta");
  const size_t hdlr = begin_box(o, "hdlr");
  zeros(o, 8);
  put(o, "mdta", 4);
  zeros(o, 13);
  end_box(o, hdlr);
  const size_t keys = begin_box(o, "keys");
  put32(o, 0);
  put32(o, 1);
  put32(o, 8 + (uint32_t)strlen(key));
  put(o, "mdta", 4);
  put(o, key, strlen(key));
  end_box(o, keys);
  const size_t ilst = begin_box(o, "ilst");
  const size_t item = begin_box(o, "\0\0\0\1");
  const size_t data = begin_box(o, "data");
  put32(o, 1);  // UTF-8
  put32(o, 0);  // locale
  put(o, value, strlen(value));
  end_box(o, data);
  end_box(o, item);
  end_box(o, ilst);
  end_box(o, meta);
}

static void video_trak(out_t *o, int version, uint64_t created, uint64_t modified,
                       void (*extra)(out_t *)) {
  const size_t trak = begin_box(o, "trak");
  timed_box(o, "tkhd", version, created, modified, 72);
  const size_t mdia = begin_box(o, "mdia");
  timed_box(o, "mdhd", version, created, modified, 12);
  const size_t hdlr = begin_box(o, "hdlr");
  zeros(o, 8);
  put(o, "vide", 4);
  zeros(o, 13);
  end_box(o, hdlr);
  end_box(o, mdia);
  extra(o);
  end_box(o, trak);
}

static const char kDateKey[] = "com.apple.quicktime.creationdate";
static const char kDate[] = "2025-06-01T12:34:56+0200";
static const char kLensKey[] = "com.apple.quicktime.camera.lens_model";
static const char kLens[] = "iPhone 17 Pro back camera 6.86mm f/1.78";
static const char kEncoder[] = "Lavf-selftest";
static const char kFrames[] = "frames the copy must keep";
static const uint64_t kOriginalTimes[2] = {3833000000u, 3833000001u};  // 2025, in 1904 seconds
static const uint64_t kConvertedTimes[2] = {5000000000u, 5000000001u};

static void lens_meta(out_t *o) { meta_box(o, kLensKey, kLens); }

static void encoder_udta(out_t *o) {
  const size_t udta = begin_box(o, "udta");
  const size_t too = begin_box(o, "\251too");
  put(o, kEncoder, strlen(kEncoder));
  end_box(o, too);
  end_box(o, udta);
}

static int write_file(const char *path, const out_t *o) {
  FILE *f = fopen(path, "wb");
  if (!f) return -1;
  const int ok = !o->failed && fwrite(o->data, 1, o->size, f) == o->size;
  return fclose(f) == 0 && ok ? 0 : -1;
}

static uint8_t *read_file(const char *path, size_t *len) {
  FILE *f = fopen(path, "rb");
  if (!f) return NULL;
  uint8_t *data = NULL;
  size_t size = 0;
  uint8_t chunk[4096];
  size_t n;
  while ((n = fread(chunk, 1, sizeof chunk, f)) > 0) {
    uint8_t *p = realloc(data, size + n);
    if (!p) {
      free(data);
      fclose(f);
      return NULL;
    }
    data = p;
    memcpy(data + size, chunk, n);
    size += n;
  }
  fclose(f);
  *len = size;
  return data;
}

static const uint8_t *find(const uint8_t *data, size_t len, const void *needle, size_t n) {
  for (size_t i = 0; i + n <= len; i++)
    if (memcmp(data + i, needle, n) == 0) return data + i;
  return NULL;
}

static uint64_t rd(const uint8_t *p, int bytes) {
  uint64_t v = 0;
  for (int i = 0; i < bytes; i++) v = v << 8 | p[i];
  return v;
}

// Whether the box named `type` (found by name: each occurs once here) has the
// original's times.
static int has_original_times(const uint8_t *data, size_t len, const char *type) {
  const uint8_t *b = find(data, len, type, 4);
  if (!b || b + 4 + 20 > data + len) return 0;
  const int width = b[4] == 1 ? 8 : 4;
  return rd(b + 8, width) == kOriginalTimes[0] && rd(b + 8 + width, width) == kOriginalTimes[1];
}

static int selftest(void) {
  const char *tmp = getenv("TMPDIR");
  char dir[1024];
  snprintf(dir, sizeof dir, "%s/vidmeta-selftest.XXXXXX", tmp && *tmp ? tmp : "/tmp");
  if (!mkdtemp(dir)) {
    printf("Self-test FAILED: can't create a folder in %s\n", tmp && *tmp ? tmp : "/tmp");
    return 1;
  }
  char original[1100], converted[1100], err[512] = "", value[64] = "";
  snprintf(original, sizeof original, "%s/original.mov", dir);
  snprintf(converted, sizeof converted, "%s/converted.mp4", dir);
  const char *failure = NULL;

  // The original: moov with a version 0 mvhd and a video track with the lens
  // key; the movie's date key is appended by mp4meta_append, as the tests do.
  out_t a = {0};
  size_t b = begin_box(&a, "ftyp");
  put(&a, "qt  ", 4);
  zeros(&a, 4);
  end_box(&a, b);
  b = begin_box(&a, "moov");
  timed_box(&a, "mvhd", 0, kOriginalTimes[0], kOriginalTimes[1], 88);
  video_trak(&a, 0, kOriginalTimes[0], kOriginalTimes[1], lens_meta);
  end_box(&a, b);

  // The converted copy, as ffmpeg writes it: its frames, then a moov with
  // version 1 (64-bit) times and its own encoder tag, on the movie and on the
  // video track.
  out_t c = {0};
  b = begin_box(&c, "ftyp");
  put(&c, "isom", 4);
  zeros(&c, 4);
  end_box(&c, b);
  b = begin_box(&c, "mdat");
  put(&c, kFrames, strlen(kFrames));
  end_box(&c, b);
  b = begin_box(&c, "moov");
  timed_box(&c, "mvhd", 1, kConvertedTimes[0], kConvertedTimes[1], 88);
  video_trak(&c, 1, kConvertedTimes[0], kConvertedTimes[1], encoder_udta);
  encoder_udta(&c);
  end_box(&c, b);

  out_t date = {0}, lens = {0};
  meta_box(&date, kDateKey, kDate);
  meta_box(&lens, kLensKey, kLens);
  size_t len = 0;
  uint8_t *result = NULL;
  int copied = -1;
  if (a.failed || c.failed || date.failed || lens.failed) {
    failure = "out of memory";
  } else if (write_file(original, &a) != 0 || write_file(converted, &c) != 0) {
    failure = "can't write the test files";
  } else if (mp4meta_append(original, date.data, date.size, err, sizeof err) != 0 ||
             (copied = mp4meta_copy(original, converted, err, sizeof err)) < 0) {
    failure = err;
  } else if (!(result = read_file(converted, &len))) {
    failure = "can't read the copy back";
  } else if (copied != 2) {
    failure = "not 2 boxes copied";
  } else if (!find(result, len, date.data, date.size)) {
    failure = "the movie's date key is missing";
  } else if (!find(result, len, lens.data, lens.size)) {
    failure = "the video track's lens key is missing";
  } else if (find(result, len, kEncoder, strlen(kEncoder))) {
    failure = "ffmpeg's own tags are still there";
  } else if (!has_original_times(result, len, "mvhd") || !has_original_times(result, len, "tkhd") ||
             !has_original_times(result, len, "mdhd")) {
    failure = "the times were not set";
  } else if (len < 24 + strlen(kFrames) || memcmp(result, c.data, 24 + strlen(kFrames)) != 0) {
    failure = "the frames were changed";
  } else if (mp4meta_key(converted, kDateKey, value, sizeof value, err, sizeof err) != 1 ||
             strcmp(value, kDate) != 0) {
    failure = "the date key can't be read back";
  }
  free(a.data);
  free(c.data);
  free(date.data);
  free(lens.data);
  free(result);
  unlink(original);
  unlink(converted);
  rmdir(dir);
  if (failure) {
    printf("Self-test FAILED: %s\n", failure);
    return 1;
  }
  printf("vidmeta %s\nSelf-test passed.\n", VIDMETA_VERSION);
  return 0;
}

int main(int argc, char **argv) {
  if (argc == 2 && strcmp(argv[1], "--version") == 0) {
    printf("vidmeta %s\n", VIDMETA_VERSION);
    return 0;
  }
  if (argc == 2 && strcmp(argv[1], "--selftest") == 0) return selftest();
  if (argc == 4 && strcmp(argv[1], "copy") == 0) return copy(argv[2], argv[3]);
  if (argc == 4 && strcmp(argv[1], "key") == 0) return key(argv[2], argv[3]);
  return usage();
}
