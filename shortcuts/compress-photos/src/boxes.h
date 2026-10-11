// ISOBMFF box reading, shared by the metadata parser (meta.c) and the HEIC
// writer (heifbox.c): big-endian integers, a byte span and a box iterator.
#ifndef JXLBATCH_BOXES_H
#define JXLBATCH_BOXES_H

#include <stddef.h>
#include <stdint.h>

#define FOURCC(a, b, c, d) \
  (((uint32_t)(a) << 24) | ((uint32_t)(b) << 16) | ((uint32_t)(c) << 8) | (uint32_t)(d))

static inline uint16_t rd16be(const uint8_t *p) { return (uint16_t)((p[0] << 8) | p[1]); }
static inline uint32_t rd32be(const uint8_t *p) {
  return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}
static inline uint64_t rdNbe(const uint8_t *p, int n) {
  uint64_t v = 0;
  for (int i = 0; i < n; i++) v = (v << 8) | p[i];
  return v;
}

typedef struct {
  const uint8_t *p;
  size_t n;
} span_t;

typedef struct {
  const uint8_t *p;
  size_t n;
  size_t pos;
} box_iter_t;

// The next box in the span: its type and payload (after the header). Returns
// 0 at the end, or at a box that doesn't fit.
static inline int box_next(box_iter_t *it, uint32_t *type, span_t *payload) {
  if (it->pos > it->n || it->n - it->pos < 8) return 0;
  const uint8_t *b = it->p + it->pos;
  uint64_t size = rd32be(b);
  uint32_t t = rd32be(b + 4);
  size_t hdr = 8;
  if (size == 1) {
    if (it->n - it->pos < 16) return 0;
    size = rdNbe(b + 8, 8);
    hdr = 16;
  } else if (size == 0) {
    size = it->n - it->pos;
  }
  if (size < hdr || size > it->n - it->pos) return 0;
  *type = t;
  payload->p = b + hdr;
  payload->n = (size_t)(size - hdr);
  it->pos += (size_t)size;
  return 1;
}

#endif
