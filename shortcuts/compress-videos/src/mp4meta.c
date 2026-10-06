// Metadata copying between QuickTime/MP4 files (see mp4meta.h).
//
// Works on the box tree directly, so every value keeps its original data
// type, which FFmpeg's metadata API would turn into text. Only the `moov` box
// is read: the original's is usually well under 1 MB even for long videos.
#include "mp4meta.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

typedef struct {
  uint8_t *data;
  size_t size, cap;
} buf_t;

typedef struct {
  uint32_t type;
  size_t pos, header, size;  // offset and sizes within the parent buffer
} box_t;

#define FOURCC(a, b, c, d) \
  (((uint32_t)(a) << 24) | ((uint32_t)(b) << 16) | ((uint32_t)(c) << 8) | (uint32_t)(d))

static void set_err(char *err, size_t len, const char *fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(err, len, fmt, ap);
  va_end(ap);
}

static uint32_t rd32(const uint8_t *p) {
  return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

static uint64_t rd64(const uint8_t *p) { return ((uint64_t)rd32(p) << 32) | rd32(p + 4); }

static void wr32(uint8_t *p, uint32_t v) {
  p[0] = (uint8_t)(v >> 24);
  p[1] = (uint8_t)(v >> 16);
  p[2] = (uint8_t)(v >> 8);
  p[3] = (uint8_t)v;
}

static void wr64(uint8_t *p, uint64_t v) {
  wr32(p, (uint32_t)(v >> 32));
  wr32(p + 4, (uint32_t)v);
}

static int buf_add(buf_t *b, const void *data, size_t len) {
  if (b->size + len > b->cap) {
    size_t cap = b->cap ? b->cap * 2 : 4096;
    while (cap < b->size + len) cap *= 2;
    uint8_t *p = realloc(b->data, cap);
    if (!p) return -1;
    b->data = p;
    b->cap = cap;
  }
  memcpy(b->data + b->size, data, len);
  b->size += len;
  return 0;
}

// Appends a box header for a body of `body_len` bytes; returns 0 or -1.
static int buf_add_header(buf_t *b, uint32_t type, uint64_t body_len) {
  uint8_t h[16];
  if (body_len + 8 <= 0xFFFFFFFFu) {
    wr32(h, (uint32_t)(body_len + 8));
    wr32(h + 4, type);
    return buf_add(b, h, 8);
  }
  wr32(h, 1);
  wr32(h + 4, type);
  wr64(h + 8, body_len + 16);
  return buf_add(b, h, 16);
}

// Iterates the boxes in data[start, end): returns 1 and fills *box while
// there is a next one at *pos, 0 at the end, -1 if malformed.
static int next_box(const uint8_t *data, size_t *pos, size_t end, box_t *box) {
  if (*pos + 8 > end) return 0;
  uint64_t size = rd32(data + *pos);
  size_t header = 8;
  if (size == 1) {
    if (*pos + 16 > end) return -1;
    size = rd64(data + *pos + 8);
    header = 16;
  } else if (size == 0) {
    size = end - *pos;
  }
  if (size < header || size > end - *pos) return -1;
  box->type = rd32(data + *pos + 4);
  box->pos = *pos;
  box->header = header;
  box->size = (size_t)size;
  *pos += (size_t)size;
  return 1;
}

static int find_child(const uint8_t *data, size_t start, size_t end, uint32_t type, box_t *out) {
  size_t pos = start;
  box_t b;
  int r;
  while ((r = next_box(data, &pos, end, &b)) == 1)
    if (b.type == type) {
      *out = b;
      return 1;
    }
  return r;
}

// Reads the top-level moov box of an open file into *moov; *offset is where
// it starts and *at_end whether it's the file's last box.
static int read_moov(FILE *f, uint8_t **moov, size_t *moov_len, long long *offset, int *at_end,
                     char *err, size_t err_len) {
  struct stat st;
  if (fstat(fileno(f), &st) != 0) {
    set_err(err, err_len, "can't read the file size");
    return -1;
  }
  long long file_size = (long long)st.st_size, pos = 0;
  while (pos + 8 <= file_size) {
    uint8_t h[16];
    if (fseeko(f, pos, SEEK_SET) != 0 || fread(h, 1, 16, f) < 8) break;
    uint64_t size = rd32(h);
    uint32_t type = rd32(h + 4);
    if (size == 1)
      size = rd64(h + 8);
    else if (size == 0)
      size = (uint64_t)(file_size - pos);
    if (size < 8 || (long long)size > file_size - pos) {
      set_err(err, err_len, "damaged file (box at %lld)", pos);
      return -1;
    }
    if (type == FOURCC('m', 'o', 'o', 'v')) {
      if (size > (64u << 20)) {
        set_err(err, err_len, "moov box too large");
        return -1;
      }
      *moov = malloc((size_t)size);
      if (!*moov || fseeko(f, pos, SEEK_SET) != 0 || fread(*moov, 1, (size_t)size, f) != size) {
        free(*moov);
        *moov = NULL;
        set_err(err, err_len, "can't read the moov box");
        return -1;
      }
      *moov_len = (size_t)size;
      *offset = pos;
      *at_end = pos + (long long)size == file_size;
      return 0;
    }
    pos += (long long)size;
  }
  set_err(err, err_len, "no moov box");
  return -1;
}

static int is_carried(uint32_t type) {
  return type == FOURCC('m', 'e', 't', 'a') || type == FOURCC('u', 'd', 't', 'a');
}

// The handler type ('vide', 'soun', ...) of the trak box b in data.
static uint32_t handler_type(const uint8_t *data, const box_t *trak) {
  box_t mdia, hdlr;
  if (find_child(data, trak->pos + trak->header, trak->pos + trak->size, FOURCC('m', 'd', 'i', 'a'),
                 &mdia) != 1)
    return 0;
  if (find_child(data, mdia.pos + mdia.header, mdia.pos + mdia.size, FOURCC('h', 'd', 'l', 'r'),
                 &hdlr) != 1 ||
      hdlr.size < hdlr.header + 12)
    return 0;
  return rd32(data + hdlr.pos + hdlr.header + 8);
}

// Creation and modification times of an mvhd/tkhd/mdhd box: version 0 has
// 32-bit fields, version 1 64-bit ones.
static void get_times(const uint8_t *data, const box_t *b, uint64_t t[2]) {
  const uint8_t *p = data + b->pos + b->header;
  if (p[0] == 1) {
    t[0] = rd64(p + 4);
    t[1] = rd64(p + 12);
  } else {
    t[0] = rd32(p + 4);
    t[1] = rd32(p + 8);
  }
}

static void set_times(uint8_t *data, const box_t *b, const uint64_t t[2]) {
  uint8_t *p = data + b->pos + b->header;
  if (b->size < b->header + 20) return;
  if (p[0] == 1) {
    wr64(p + 4, t[0]);
    wr64(p + 12, t[1]);
  } else {
    wr32(p + 4, t[0] > 0xFFFFFFFFu ? 0xFFFFFFFFu : (uint32_t)t[0]);
    wr32(p + 8, t[1] > 0xFFFFFFFFu ? 0xFFFFFFFFu : (uint32_t)t[1]);
  }
}

// Appends the carried (meta/udta) children of data[start, end) to out.
static int collect_carried(const uint8_t *data, size_t start, size_t end, buf_t *out, int *count) {
  size_t pos = start;
  box_t b;
  int r;
  while ((r = next_box(data, &pos, end, &b)) == 1)
    if (is_carried(b.type)) {
      if (buf_add(out, data + b.pos, b.size) != 0) return -1;
      (*count)++;
    }
  return r;
}

// Rewrites the file's moov (its last box) as: its children (with times set
// and carried boxes replaced when given) + movie_extra. video_extra replaces
// the first video track's meta/udta boxes. times may be NULL.
static int rewrite_moov(const char *path, const buf_t *movie_extra, const buf_t *video_extra,
                        const uint64_t *times, char *err, size_t err_len) {
  FILE *f = fopen(path, "r+b");
  if (!f) {
    set_err(err, err_len, "can't open %s", path);
    return -1;
  }
  uint8_t *moov = NULL;
  size_t moov_len = 0;
  long long offset = 0;
  int at_end = 0, ret = -1;
  buf_t body = {0}, out = {0}, trak = {0};
  if (read_moov(f, &moov, &moov_len, &offset, &at_end, err, err_len) != 0) goto done;
  if (!at_end) {
    set_err(err, err_len, "the moov box isn't at the end of %s", path);
    goto done;
  }
  box_t top;
  size_t tpos = 0;
  if (next_box(moov, &tpos, moov_len, &top) != 1) {
    set_err(err, err_len, "damaged moov box");
    goto done;
  }
  size_t pos = top.header;
  box_t b;
  int r, video_done = 0;
  while ((r = next_box(moov, &pos, moov_len, &b)) == 1) {
    if (movie_extra && is_carried(b.type)) continue;
    if (b.type == FOURCC('m', 'v', 'h', 'd') && times) set_times(moov, &b, times);
    if (b.type != FOURCC('t', 'r', 'a', 'k')) {
      if (buf_add(&body, moov + b.pos, b.size) != 0) goto oom;
      continue;
    }
    int is_video = !video_done && handler_type(moov, &b) == FOURCC('v', 'i', 'd', 'e');
    video_done |= is_video;
    const buf_t *extra = is_video ? video_extra : NULL;
    trak.size = 0;
    size_t cpos = b.pos + b.header;
    box_t c;
    int cr;
    while ((cr = next_box(moov, &cpos, b.pos + b.size, &c)) == 1) {
      if (times && c.type == FOURCC('t', 'k', 'h', 'd')) set_times(moov, &c, times);
      if (times && c.type == FOURCC('m', 'd', 'i', 'a')) {
        box_t mdhd;
        if (find_child(moov, c.pos + c.header, c.pos + c.size, FOURCC('m', 'd', 'h', 'd'), &mdhd) == 1)
          set_times(moov, &mdhd, times);
      }
      if (extra && is_carried(c.type)) continue;
      if (buf_add(&trak, moov + c.pos, c.size) != 0) goto oom;
    }
    if (cr < 0) {
      set_err(err, err_len, "damaged trak box");
      goto done;
    }
    if (extra && buf_add(&trak, extra->data, extra->size) != 0) goto oom;
    if (buf_add_header(&body, FOURCC('t', 'r', 'a', 'k'), trak.size) != 0 ||
        buf_add(&body, trak.data, trak.size) != 0)
      goto oom;
  }
  if (r < 0) {
    set_err(err, err_len, "damaged moov box");
    goto done;
  }
  if (movie_extra && buf_add(&body, movie_extra->data, movie_extra->size) != 0) goto oom;
  if (buf_add_header(&out, FOURCC('m', 'o', 'o', 'v'), body.size) != 0 ||
      buf_add(&out, body.data, body.size) != 0)
    goto oom;
  if (fseeko(f, offset, SEEK_SET) != 0 || fwrite(out.data, 1, out.size, f) != out.size ||
      fflush(f) != 0 || ftruncate(fileno(f), offset + (long long)out.size) != 0) {
    set_err(err, err_len, "can't write %s", path);
    goto done;
  }
  ret = 0;
  goto done;
oom:
  set_err(err, err_len, "out of memory");
done:
  if (fclose(f) != 0 && ret == 0) {
    set_err(err, err_len, "can't write %s", path);
    ret = -1;
  }
  free(moov);
  free(body.data);
  free(out.data);
  free(trak.data);
  return ret;
}

int mp4meta_copy(const char *original, const char *converted, char *err, size_t err_len) {
  FILE *f = fopen(original, "rb");
  if (!f) {
    set_err(err, err_len, "can't open %s", original);
    return -1;
  }
  uint8_t *moov = NULL;
  size_t moov_len = 0;
  long long offset;
  int at_end, count = 0, ret = -1, have_times = 0;
  uint64_t times[2] = {0, 0};
  buf_t movie = {0}, video = {0};
  int r = read_moov(f, &moov, &moov_len, &offset, &at_end, err, err_len);
  fclose(f);
  if (r != 0) return -1;

  box_t top, b;
  size_t pos = 0;
  if (next_box(moov, &pos, moov_len, &top) != 1) {
    set_err(err, err_len, "damaged moov box in %s", original);
    goto done;
  }
  if (collect_carried(moov, top.header, moov_len, &movie, &count) < 0) goto bad;
  pos = top.header;
  int video_found = 0;
  while ((r = next_box(moov, &pos, moov_len, &b)) == 1) {
    if (b.type == FOURCC('m', 'v', 'h', 'd')) {
      get_times(moov, &b, times);
      have_times = 1;
    } else if (b.type == FOURCC('t', 'r', 'a', 'k') && !video_found &&
               handler_type(moov, &b) == FOURCC('v', 'i', 'd', 'e')) {
      video_found = 1;
      if (collect_carried(moov, b.pos + b.header, b.pos + b.size, &video, &count) < 0) goto bad;
    }
  }
  if (r < 0) goto bad;
  if (rewrite_moov(converted, &movie, &video, have_times ? times : NULL, err, err_len) != 0) goto done;
  ret = count;
  goto done;
bad:
  set_err(err, err_len, "damaged moov box in %s", original);
done:
  free(moov);
  free(movie.data);
  free(video.data);
  return ret;
}

// The text of a data box's value: UTF-8 as it is; a big-endian integer
// (QuickTime's well-known types 21 and 65-67, 74: signed; 22 and 75-78:
// unsigned) of 1 to 8 bytes in decimal. Returns 1, or -1 for another type.
static int value_text(uint32_t type, const uint8_t *p, size_t len, char *out, size_t out_len,
                      char *err, size_t err_len) {
  const int is_signed = type == 21 || (type >= 65 && type <= 67) || type == 74;
  const int is_unsigned = type == 22 || (type >= 75 && type <= 78);
  if (type == 1) {
    if (len >= out_len) {
      set_err(err, err_len, "the value is too long");
      return -1;
    }
    memcpy(out, p, len);
    out[len] = '\0';
    return 1;
  }
  if ((is_signed || is_unsigned) && len >= 1 && len <= 8) {
    uint64_t v = 0;
    for (size_t i = 0; i < len; i++) v = v << 8 | p[i];
    if (is_signed) {
      if (len < 8 && (p[0] & 0x80)) v |= ~(uint64_t)0 << (8 * len);  // sign extension
      snprintf(out, out_len, "%lld", (long long)(int64_t)v);
    } else {
      snprintf(out, out_len, "%llu", (unsigned long long)v);
    }
    return 1;
  }
  set_err(err, err_len, "the value has data type %u, which isn't shown", (unsigned)type);
  return -1;
}

// Looks for `key` in a QuickTime metadata box (hdlr mdta, keys, ilst): 1 and
// its value in out, 0 if it isn't there, -1 if the box is damaged or the value
// can't be shown.
static int meta_key(const uint8_t *data, const box_t *meta, const char *key, char *out,
                    size_t out_len, char *err, size_t err_len) {
  const size_t end = meta->pos + meta->size;
  size_t start = meta->pos + meta->header;
  box_t hdlr, keys, ilst, item, value;
  // QuickTime's meta box has no version and flags; ISO's has them.
  if (find_child(data, start, end, FOURCC('h', 'd', 'l', 'r'), &hdlr) != 1) {
    start += 4;
    if (start > end || find_child(data, start, end, FOURCC('h', 'd', 'l', 'r'), &hdlr) != 1)
      return 0;
  }
  if (hdlr.size < hdlr.header + 12 ||
      rd32(data + hdlr.pos + hdlr.header + 8) != FOURCC('m', 'd', 't', 'a') ||
      find_child(data, start, end, FOURCC('k', 'e', 'y', 's'), &keys) != 1 ||
      find_child(data, start, end, FOURCC('i', 'l', 's', 't'), &ilst) != 1)
    return 0;
  // keys: version and flags, the count, then (size, namespace, name) per key;
  // the first key is number 1.
  const size_t key_len = strlen(key), keys_end = keys.pos + keys.size;
  size_t p = keys.pos + keys.header + 8;
  uint32_t index = 0;
  for (uint32_t n = 1; p + 8 <= keys_end; n++) {
    const uint32_t size = rd32(data + p);
    if (size < 8 || size > keys_end - p) goto bad;
    if (size - 8 == key_len && memcmp(data + p + 8, key, key_len) == 0) {
      index = n;
      break;
    }
    p += size;
  }
  if (!index) return 0;
  // ilst: a box per value, its type the key's number, holding a data box:
  // the value's type, its locale, then the value.
  size_t pos = ilst.pos + ilst.header;
  int r;
  while ((r = next_box(data, &pos, ilst.pos + ilst.size, &item)) == 1) {
    if (item.type != index) continue;
    if (find_child(data, item.pos + item.header, item.pos + item.size, FOURCC('d', 'a', 't', 'a'),
                   &value) != 1 ||
        value.size < value.header + 8)
      goto bad;
    const uint8_t *v = data + value.pos + value.header;
    return value_text(rd32(v) & 0xFFFFFF, v + 8, value.size - value.header - 8, out, out_len, err,
                      err_len);
  }
  if (r == 0) return 0;
bad:
  set_err(err, err_len, "damaged meta box");
  return -1;
}

int mp4meta_key(const char *path, const char *key, char *out, size_t out_len, char *err,
                size_t err_len) {
  FILE *f = fopen(path, "rb");
  if (!f) {
    set_err(err, err_len, "can't open %s", path);
    return -1;
  }
  uint8_t *moov = NULL;
  size_t moov_len = 0;
  long long offset;
  int at_end, found = 0;
  int r = read_moov(f, &moov, &moov_len, &offset, &at_end, err, err_len);
  fclose(f);
  if (r != 0) return -1;
  box_t top, b;
  size_t pos = 0;
  if (next_box(moov, &pos, moov_len, &top) != 1) {
    r = -1;
  } else {
    pos = top.header;
    while (!found && (r = next_box(moov, &pos, moov_len, &b)) == 1)
      if (b.type == FOURCC('m', 'e', 't', 'a'))
        found = meta_key(moov, &b, key, out, out_len, err, err_len);
  }
  free(moov);
  if (found < 0) return -1;
  if (found == 0 && r < 0) {
    set_err(err, err_len, "damaged moov box in %s", path);
    return -1;
  }
  return found;
}

// The first sample description of the first video track in a moov: 1 and
// *entry, 0 if there is none, -1 if a box on the way is damaged.
static int video_sample_entry(const uint8_t *data, size_t len, box_t *entry) {
  box_t top, b, mdia, minf, stbl, stsd;
  size_t pos = 0;
  int r;
  if (next_box(data, &pos, len, &top) != 1) return -1;
  pos = top.header;
  while ((r = next_box(data, &pos, len, &b)) == 1) {
    if (b.type != FOURCC('t', 'r', 'a', 'k') ||
        handler_type(data, &b) != FOURCC('v', 'i', 'd', 'e'))
      continue;
    if (find_child(data, b.pos + b.header, b.pos + b.size, FOURCC('m', 'd', 'i', 'a'), &mdia) !=
            1 ||
        find_child(data, mdia.pos + mdia.header, mdia.pos + mdia.size, FOURCC('m', 'i', 'n', 'f'),
                   &minf) != 1 ||
        find_child(data, minf.pos + minf.header, minf.pos + minf.size, FOURCC('s', 't', 'b', 'l'),
                   &stbl) != 1 ||
        find_child(data, stbl.pos + stbl.header, stbl.pos + stbl.size, FOURCC('s', 't', 's', 'd'),
                   &stsd) != 1)
      return 0;
    // stsd: version and flags, the number of entries, then the entries.
    size_t epos = stsd.pos + stsd.header + 8;
    if (epos > stsd.pos + stsd.size) return -1;
    return next_box(data, &epos, stsd.pos + stsd.size, entry);
  }
  return r;
}

int mp4meta_log(const char *path, char *out, size_t out_len, char *err, size_t err_len) {
  FILE *f = fopen(path, "rb");
  if (!f) {
    set_err(err, err_len, "can't open %s", path);
    return -1;
  }
  uint8_t *moov = NULL;
  size_t moov_len = 0;
  long long offset;
  int at_end;
  int r = read_moov(f, &moov, &moov_len, &offset, &at_end, err, err_len);
  fclose(f);
  if (r != 0) return -1;
  box_t entry, logs;
  r = video_sample_entry(moov, moov_len, &entry);
  // A visual sample entry: its header, 78 bytes of fields (size, depth,
  // compressor...), then its boxes: colr, fiel, logs...
  const size_t start = entry.pos + entry.header + 78, end = entry.pos + entry.size;
  if (r == 1)
    r = start <= end ? find_child(moov, start, end, FOURCC('l', 'o', 'g', 's'), &logs) : -1;
  if (r == 1) {
    size_t len = logs.size - logs.header;
    const char *name = (const char *)moov + logs.pos + logs.header;
    while (len > 0 && name[len - 1] == '\0') len--;  // a terminating NUL, if any
    if (len >= out_len) {
      set_err(err, err_len, "the log transfer function's name is too long");
      r = -1;
    } else {
      memcpy(out, name, len);
      out[len] = '\0';
    }
  } else if (r < 0) {
    set_err(err, err_len, "damaged moov box in %s", path);
  }
  free(moov);
  return r;
}

int mp4meta_append(const char *path, const uint8_t *box, size_t len, char *err, size_t err_len) {
  // Keep the file's own meta/udta boxes: pass them along with the new box.
  FILE *f = fopen(path, "rb");
  if (!f) {
    set_err(err, err_len, "can't open %s", path);
    return -1;
  }
  uint8_t *moov = NULL;
  size_t moov_len = 0;
  long long offset;
  int at_end, count = 0;
  int r = read_moov(f, &moov, &moov_len, &offset, &at_end, err, err_len);
  fclose(f);
  if (r != 0) return -1;
  buf_t movie = {0};
  box_t top;
  size_t pos = 0;
  if (next_box(moov, &pos, moov_len, &top) != 1 ||
      collect_carried(moov, top.header, moov_len, &movie, &count) < 0 ||
      buf_add(&movie, box, len) != 0) {
    free(moov);
    free(movie.data);
    set_err(err, err_len, "damaged moov box");
    return -1;
  }
  free(moov);
  r = rewrite_moov(path, &movie, NULL, NULL, err, err_len);
  free(movie.data);
  return r;
}
