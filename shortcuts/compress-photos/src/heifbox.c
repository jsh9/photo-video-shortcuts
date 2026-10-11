#include "heifbox.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define HB_MAX_ENTRIES 65536

// ---------------------------------------------------------------------------
// Reading

static int grow(void **p, size_t *cap, size_t need, size_t size) {
  if (need <= *cap) return 0;
  size_t cap2 = *cap ? *cap : 16;
  while (cap2 < need) cap2 *= 2;
  void *grown = realloc(*p, cap2 * size);
  if (!grown) return -1;
  *p = grown;
  *cap = cap2;
  return 0;
}

static int parse_iinf(hb_file_t *f, span_t box, size_t *cap) {
  if (box.n < 6) return 0;
  const int version = box.p[0];
  const size_t off = version == 0 ? 6 : 8;
  if (box.n < off) return 0;
  box_iter_t it = {box.p + off, box.n - off, 0};
  uint32_t t;
  span_t pl;
  size_t start = 0;
  while (box_next(&it, &t, &pl)) {
    const size_t end = it.pos;
    if (t == FOURCC('i', 'n', 'f', 'e') && pl.n >= 4 && pl.p[0] >= 2) {
      const int v = pl.p[0];
      const size_t idsz = v == 2 ? 2 : 4;
      if (pl.n < 4 + idsz + 2 + 4) {
        start = end;
        continue;
      }
      if (f->num_items >= HB_MAX_ENTRIES) return -1;
      if (grow((void **)&f->items, cap, f->num_items + 1, sizeof *f->items) != 0) return -1;
      hb_item_t *item = &f->items[f->num_items++];
      memset(item, 0, sizeof *item);
      item->id = idsz == 2 ? rd16be(pl.p + 4) : rd32be(pl.p + 4);
      item->flags = rd32be(pl.p) & 0xffffff;
      item->type = rd32be(pl.p + 4 + idsz + 2);
      item->infe.p = it.p + start;
      item->infe.n = end - start;
    }
    start = end;
  }
  return 0;
}

static hb_item_t *item_mut(hb_file_t *f, uint32_t id) {
  for (size_t i = 0; i < f->num_items; i++) {
    if (f->items[i].id == id) return &f->items[i];
  }
  return NULL;
}

static int parse_iloc(hb_file_t *f, span_t box, char *err, size_t err_len) {
  if (box.n < 8) return 0;
  const int version = box.p[0];
  if (version > 2) {
    snprintf(err, err_len, "unsupported HEIF ('iloc' version %d)", version);
    return -1;
  }
  f->iloc_version = version;
  const uint8_t *q = box.p + 4;
  size_t qn = box.n - 4;
  const int offset_size = q[0] >> 4, length_size = q[0] & 15;
  const int base_offset_size = q[1] >> 4;
  const int index_size = version >= 1 ? (q[1] & 15) : 0;
  q += 2;
  qn -= 2;
  uint32_t count;
  if (version < 2) {
    if (qn < 2) return 0;
    count = rd16be(q);
    q += 2;
    qn -= 2;
  } else {
    if (qn < 4) return 0;
    count = rd32be(q);
    q += 4;
    qn -= 4;
  }
  if (offset_size > 8 || length_size > 8 || base_offset_size > 8 || index_size > 8) return 0;
  const size_t idsz = version < 2 ? 2 : 4;
  size_t ext_cap = 0;
  for (uint32_t i = 0; i < count; i++) {
    if (qn < idsz) return 0;
    const uint32_t id = idsz == 2 ? rd16be(q) : rd32be(q);
    q += idsz;
    qn -= idsz;
    int method = 0;
    if (version >= 1) {
      if (qn < 2) return 0;
      method = rd16be(q) & 15;
      q += 2;
      qn -= 2;
    }
    if (qn < 2 + (size_t)base_offset_size + 2) return 0;
    const uint16_t dref = rd16be(q);
    q += 2;
    const uint64_t base = rdNbe(q, base_offset_size);
    q += base_offset_size;
    const uint16_t next = rd16be(q);
    q += 2;
    qn -= 2 + (size_t)base_offset_size + 2;
    hb_item_t *item = item_mut(f, id);
    if (item) {
      if (method > 1) {
        snprintf(err, err_len, "unsupported HEIF (item %u's data is referenced by item offset)", id);
        return -1;
      }
      if (dref != 0) {
        snprintf(err, err_len, "unsupported HEIF (item %u's data is in another file)", id);
        return -1;
      }
      item->located = 1;
      item->method = method;
      item->dref = dref;
      item->first_extent = f->num_extents;
    }
    for (uint16_t e = 0; e < next; e++) {
      const size_t need = (size_t)index_size + offset_size + length_size;
      if (qn < need) return 0;
      q += index_size;
      hb_extent_t ext;
      ext.offset = base + rdNbe(q, offset_size);
      q += offset_size;
      ext.length = rdNbe(q, length_size);
      q += length_size;
      qn -= need;
      if (item) {
        if (f->num_extents >= HB_MAX_ENTRIES) return -1;
        if (grow((void **)&f->extents, &ext_cap, f->num_extents + 1, sizeof *f->extents) != 0) return -1;
        f->extents[f->num_extents++] = ext;
      }
    }
    if (item) item->num_extents = f->num_extents - item->first_extent;
  }
  return 0;
}

static int parse_iref(hb_file_t *f, span_t box) {
  if (box.n < 4) return 0;
  const int version = box.p[0];
  f->iref_version = version;
  const size_t idsz = version == 0 ? 2 : 4;
  box_iter_t it = {box.p + 4, box.n - 4, 0};
  uint32_t t;
  span_t pl;
  size_t cap = 0;
  while (box_next(&it, &t, &pl)) {
    if (pl.n < idsz + 2) continue;
    const uint32_t from = idsz == 2 ? rd16be(pl.p) : rd32be(pl.p);
    const uint16_t cnt = rd16be(pl.p + idsz);
    if (pl.n - idsz - 2 < (size_t)cnt * idsz) continue;
    if (f->num_refs >= HB_MAX_ENTRIES) return -1;
    if (grow((void **)&f->refs, &cap, f->num_refs + 1, sizeof *f->refs) != 0) return -1;
    hb_ref_t *ref = &f->refs[f->num_refs];
    ref->type = t;
    ref->from = from;
    ref->num_to = cnt;
    ref->to = (uint32_t *)malloc((cnt ? cnt : 1) * sizeof *ref->to);
    if (!ref->to) return -1;
    for (uint16_t i = 0; i < cnt; i++) {
      ref->to[i] = idsz == 2 ? rd16be(pl.p + idsz + 2 + 2 * i) : rd32be(pl.p + idsz + 2 + 4 * i);
    }
    f->num_refs++;
  }
  return 0;
}

static int parse_iprp(hb_file_t *f, span_t box) {
  box_iter_t it = {box.p, box.n, 0};
  uint32_t t;
  span_t pl;
  size_t order_cap = 0;
  while (box_next(&it, &t, &pl)) {
    if (t == FOURCC('i', 'p', 'c', 'o')) {
      box_iter_t pit = {pl.p, pl.n, 0};
      uint32_t pt;
      span_t ppl;
      size_t cap = 0, start = 0;
      while (box_next(&pit, &pt, &ppl)) {
        if (f->num_ipco >= HB_MAX_ENTRIES) return -1;
        if (grow((void **)&f->ipco, &cap, f->num_ipco + 1, sizeof *f->ipco) != 0) return -1;
        f->ipco[f->num_ipco].p = pl.p + start;
        f->ipco[f->num_ipco].n = pit.pos - start;
        f->num_ipco++;
        start = pit.pos;
      }
    } else if (t == FOURCC('i', 'p', 'm', 'a') && pl.n >= 8) {
      f->ipma_version = pl.p[0];
      f->ipma_flags = pl.p[3];
      const size_t idsz = pl.p[0] == 0 ? 2 : 4;
      const size_t isz = pl.p[3] & 1 ? 2 : 1;
      const uint8_t *q = pl.p + 8, *end = pl.p + pl.n;
      for (uint32_t n = rd32be(pl.p + 4); n > 0 && (size_t)(end - q) > idsz; n--) {
        const uint32_t id = idsz == 2 ? rd16be(q) : rd32be(q);
        const size_t count = q[idsz];
        q += idsz + 1;
        if ((size_t)(end - q) < count * isz) break;
        hb_item_t *item = item_mut(f, id);
        if (item) {
          if (f->num_ipma >= HB_MAX_ENTRIES) return -1;
          if (grow((void **)&f->ipma_order, &order_cap, f->num_ipma + 1, sizeof *f->ipma_order) != 0) return -1;
          f->ipma_order[f->num_ipma++] = id;
          item->num_props = 0;
          for (size_t i = 0; i < count && i < HB_MAX_PROPS; i++) {
            const uint32_t v = isz == 2 ? rd16be(q + 2 * i) : q[i];
            item->props[item->num_props] = isz == 2 ? v & 0x7fff : v & 0x7f;
            item->essential[item->num_props] = isz == 2 ? (v & 0x8000) != 0 : (v & 0x80) != 0;
            item->num_props++;
          }
        }
        q += count * isz;
      }
    }
  }
  return 0;
}

static int parse_grpl(hb_file_t *f, span_t box) {
  box_iter_t it = {box.p, box.n, 0};
  uint32_t t;
  span_t pl;
  size_t cap = 0;
  while (box_next(&it, &t, &pl)) {
    if (pl.n < 12) continue;
    const uint32_t n = rd32be(pl.p + 8);
    if (pl.n - 12 < (size_t)n * 4) continue;
    if (grow((void **)&f->groups, &cap, f->num_groups + 1, sizeof *f->groups) != 0) return -1;
    hb_group_t *g = &f->groups[f->num_groups];
    g->type = t;
    g->id = rd32be(pl.p + 4);
    g->num_ids = n;
    g->ids = (uint32_t *)malloc((n ? n : 1) * sizeof *g->ids);
    if (!g->ids) return -1;
    for (uint32_t i = 0; i < n; i++) g->ids[i] = rd32be(pl.p + 12 + 4 * i);
    f->num_groups++;
  }
  return 0;
}

int hb_parse(const uint8_t *buf, size_t len, hb_file_t *f, char *err, size_t err_len) {
  memset(f, 0, sizeof *f);
  f->file = buf;
  f->file_len = len;
  box_iter_t top = {buf, len, 0};
  uint32_t t;
  span_t pl, meta = {NULL, 0};
  size_t start = 0;
  while (box_next(&top, &t, &pl)) {
    if (t == FOURCC('f', 't', 'y', 'p') && !f->ftyp.p) {
      f->ftyp.p = buf + start;
      f->ftyp.n = top.pos - start;
    } else if (t == FOURCC('m', 'e', 't', 'a') && !meta.p && pl.n >= 4) {
      meta = pl;
    }
    start = top.pos;
  }
  if (!f->ftyp.p || !meta.p) {
    snprintf(err, err_len, "not a HEIF file");
    return -1;
  }
  memcpy(f->meta_vf, meta.p, 4);
  box_iter_t it = {meta.p + 4, meta.n - 4, 0};
  size_t items_cap = 0, child_cap = 0, types_cap = 0;
  start = 0;
  int rc = 0;
  while (rc == 0 && box_next(&it, &t, &pl)) {
    if (grow((void **)&f->children, &child_cap, f->num_children + 1, sizeof *f->children) != 0 ||
        grow((void **)&f->child_types, &types_cap, f->num_children + 1, sizeof *f->child_types) != 0) {
      rc = -1;
      break;
    }
    f->children[f->num_children].p = it.p + start;
    f->children[f->num_children].n = it.pos - start;
    f->child_types[f->num_children] = t;
    f->num_children++;
    start = it.pos;
    if (t == FOURCC('p', 'i', 't', 'm') && pl.n >= 6) {
      f->primary = pl.p[0] == 0 ? rd16be(pl.p + 4) : (pl.n >= 8 ? rd32be(pl.p + 4) : 0);
    } else if (t == FOURCC('i', 'i', 'n', 'f')) {
      rc = parse_iinf(f, pl, &items_cap);
    } else if (t == FOURCC('i', 'd', 'a', 't')) {
      f->idat = pl;
    }
  }
  // the tables that refer to items, once the items are known
  for (size_t i = 0; rc == 0 && i < f->num_children; i++) {
    const uint32_t ct = f->child_types[i];
    span_t c = f->children[i];
    const size_t hdr = c.n >= 8 && rd32be(c.p) == 1 ? 16 : 8;
    span_t cpl = {c.p + hdr, c.n - hdr};
    if (ct == FOURCC('i', 'l', 'o', 'c')) {
      rc = parse_iloc(f, cpl, err, err_len);
    } else if (ct == FOURCC('i', 'r', 'e', 'f')) {
      rc = parse_iref(f, cpl);
    } else if (ct == FOURCC('i', 'p', 'r', 'p')) {
      rc = parse_iprp(f, cpl);
    } else if (ct == FOURCC('g', 'r', 'p', 'l')) {
      rc = parse_grpl(f, cpl);
    }
  }
  if (rc != 0) {
    if (!err[0]) snprintf(err, err_len, "out of memory");
    hb_free(f);
    return -1;
  }
  if (!f->num_items || !hb_item(f, f->primary)) {
    snprintf(err, err_len, "no primary image in HEIF");
    hb_free(f);
    return -1;
  }
  return 0;
}

void hb_free(hb_file_t *f) {
  for (size_t i = 0; i < f->num_refs; i++) free(f->refs[i].to);
  for (size_t i = 0; i < f->num_groups; i++) free(f->groups[i].ids);
  free(f->children);
  free(f->child_types);
  free(f->items);
  free(f->extents);
  free(f->refs);
  free(f->ipco);
  free(f->groups);
  free(f->ipma_order);
  memset(f, 0, sizeof *f);
}

const hb_item_t *hb_item(const hb_file_t *f, uint32_t id) { return item_mut((hb_file_t *)f, id); }

const uint32_t *hb_refs_from(const hb_file_t *f, uint32_t from, uint32_t type, size_t *n) {
  for (size_t i = 0; i < f->num_refs; i++) {
    if (f->refs[i].from == from && f->refs[i].type == type) {
      *n = f->refs[i].num_to;
      return f->refs[i].to;
    }
  }
  *n = 0;
  return NULL;
}

int hb_has_ref(const hb_file_t *f, uint32_t from, uint32_t type, uint32_t to) {
  for (size_t i = 0; i < f->num_refs; i++) {
    const hb_ref_t *r = &f->refs[i];
    if (r->from != from || r->type != type) continue;
    for (size_t j = 0; j < r->num_to; j++) {
      if (r->to[j] == to) return 1;
    }
  }
  return 0;
}

int hb_property(const hb_file_t *f, uint32_t index, uint32_t *type, span_t *payload) {
  if (index < 1 || index > f->num_ipco) return 0;
  const span_t box = f->ipco[index - 1];
  if (box.n < 8) return 0;
  const size_t hdr = rd32be(box.p) == 1 ? 16 : 8;
  if (box.n < hdr) return 0;
  *type = rd32be(box.p + 4);
  payload->p = box.p + hdr;
  payload->n = box.n - hdr;
  return 1;
}

uint32_t hb_item_property(const hb_file_t *f, uint32_t id, uint32_t type) {
  const hb_item_t *item = hb_item(f, id);
  if (!item) return 0;
  for (size_t i = 0; i < item->num_props; i++) {
    uint32_t t;
    span_t pl;
    if (hb_property(f, item->props[i], &t, &pl) && t == type) return item->props[i];
  }
  return 0;
}

// The item's extents, each as a span into the file (or 'idat'); returns the
// total length, or (size_t)-1 if one lies outside.
static size_t item_extents(const hb_file_t *f, const hb_item_t *item, span_t *spans, size_t max_spans) {
  const uint8_t *src = item->method == 1 ? f->idat.p : f->file;
  const size_t src_len = item->method == 1 ? f->idat.n : f->file_len;
  if (!item->located || !src) return (size_t)-1;
  size_t total = 0;
  for (size_t e = 0; e < item->num_extents; e++) {
    const hb_extent_t *ext = &f->extents[item->first_extent + e];
    uint64_t len = ext->length;
    if (ext->offset > src_len) return (size_t)-1;
    if (len == 0) len = src_len - ext->offset;  // to the end
    if (len > src_len - ext->offset) return (size_t)-1;
    if (e < max_spans) {
      spans[e].p = src + ext->offset;
      spans[e].n = (size_t)len;
    }
    total += (size_t)len;
  }
  return total;
}

uint8_t *hb_item_data(const hb_file_t *f, uint32_t id, size_t *len) {
  const hb_item_t *item = hb_item(f, id);
  *len = 0;
  if (!item || item->num_extents == 0 || item->num_extents > 1024) return NULL;
  span_t spans[1024];
  const size_t total = item_extents(f, item, spans, 1024);
  if (total == (size_t)-1) return NULL;
  uint8_t *d = (uint8_t *)malloc(total ? total : 1);
  if (!d) return NULL;
  size_t pos = 0;
  for (size_t e = 0; e < item->num_extents; e++) {
    memcpy(d + pos, spans[e].p, spans[e].n);
    pos += spans[e].n;
  }
  *len = total;
  return d;
}

// ---------------------------------------------------------------------------
// Writing

typedef struct {
  uint8_t *data;
  size_t len, cap;
  int oom;
} bb_t;

static void bb_put(bb_t *b, const void *p, size_t n) {
  if (b->oom) return;
  if (b->len + n > b->cap) {
    size_t cap = b->cap ? b->cap : 4096;
    while (cap < b->len + n) cap *= 2;
    uint8_t *grown = (uint8_t *)realloc(b->data, cap);
    if (!grown) {
      b->oom = 1;
      return;
    }
    b->data = grown;
    b->cap = cap;
  }
  if (n) memcpy(b->data + b->len, p, n);
  b->len += n;
}
static void bb_u8(bb_t *b, unsigned v) {
  const uint8_t x = (uint8_t)v;
  bb_put(b, &x, 1);
}
static void bb_u16(bb_t *b, unsigned v) {
  const uint8_t x[2] = {(uint8_t)(v >> 8), (uint8_t)v};
  bb_put(b, x, 2);
}
static void bb_u32(bb_t *b, uint32_t v) {
  const uint8_t x[4] = {(uint8_t)(v >> 24), (uint8_t)(v >> 16), (uint8_t)(v >> 8), (uint8_t)v};
  bb_put(b, x, 4);
}
static void bb_u64(bb_t *b, uint64_t v) {
  bb_u32(b, (uint32_t)(v >> 32));
  bb_u32(b, (uint32_t)v);
}
// A box header; returns where it starts, for bb_end.
static size_t bb_begin(bb_t *b, uint32_t type) {
  const size_t start = b->len;
  bb_u32(b, 0);
  bb_u32(b, type);
  return start;
}
static void bb_end(bb_t *b, size_t start) {
  if (b->oom) return;
  const uint32_t size = (uint32_t)(b->len - start);
  b->data[start] = (uint8_t)(size >> 24);
  b->data[start + 1] = (uint8_t)(size >> 16);
  b->data[start + 2] = (uint8_t)(size >> 8);
  b->data[start + 3] = (uint8_t)size;
}
static void bb_u8_at(bb_t *b, size_t at, unsigned v) {
  if (!b->oom && at < b->len) b->data[at] = (uint8_t)v;
}

typedef struct {
  const hb_file_t *f;
  const hb_rewrite_t *rw;
  uint8_t *kept;      // per item (f->items order)
  uint64_t *offsets;  // per item: where its data goes in the output (method 0)
  size_t *lengths;
} rewrite_t;

static int is_kept(const rewrite_t *r, uint32_t id) {
  for (size_t i = 0; i < r->f->num_items; i++) {
    if (r->f->items[i].id == id) return r->kept[i];
  }
  return 0;
}

static const hb_replace_t *replacement(const rewrite_t *r, uint32_t id) {
  for (size_t i = 0; i < r->rw->num_replace; i++) {
    if (r->rw->replace[i].id == id) return &r->rw->replace[i];
  }
  return NULL;
}

static void write_meta(bb_t *b, const rewrite_t *r, uint64_t mdat_start) {
  const hb_file_t *f = r->f;
  const size_t meta = bb_begin(b, FOURCC('m', 'e', 't', 'a'));
  bb_put(b, f->meta_vf, 4);
  for (size_t c = 0; c < f->num_children; c++) {
    const uint32_t ct = f->child_types[c];
    const span_t box = f->children[c];
    const size_t hdr = box.n >= 8 && rd32be(box.p) == 1 ? 16 : 8;
    const span_t pl = {box.p + hdr, box.n - hdr};
    if (ct == FOURCC('i', 'i', 'n', 'f') && pl.n >= 4) {
      const size_t start = bb_begin(b, ct);
      bb_put(b, pl.p, 4);
      size_t count = 0;
      for (size_t i = 0; i < f->num_items; i++) count += r->kept[i];
      if (pl.p[0] == 0) {
        bb_u16(b, (unsigned)count);
      } else {
        bb_u32(b, (uint32_t)count);
      }
      for (size_t i = 0; i < f->num_items; i++) {
        if (r->kept[i]) bb_put(b, f->items[i].infe.p, f->items[i].infe.n);
      }
      bb_end(b, start);
    } else if (ct == FOURCC('i', 'r', 'e', 'f') && pl.n >= 4) {
      const size_t start = bb_begin(b, ct);
      bb_put(b, pl.p, 4);
      for (size_t i = 0; i < f->num_refs; i++) {
        const hb_ref_t *ref = &f->refs[i];
        if (!is_kept(r, ref->from)) continue;
        size_t n = 0;
        for (size_t j = 0; j < ref->num_to; j++) n += is_kept(r, ref->to[j]);
        if (!n) continue;
        const size_t rs = bb_begin(b, ref->type);
        if (f->iref_version == 0) {
          bb_u16(b, ref->from);
        } else {
          bb_u32(b, ref->from);
        }
        bb_u16(b, (unsigned)n);
        for (size_t j = 0; j < ref->num_to; j++) {
          if (!is_kept(r, ref->to[j])) continue;
          if (f->iref_version == 0) {
            bb_u16(b, ref->to[j]);
          } else {
            bb_u32(b, ref->to[j]);
          }
        }
        bb_end(b, rs);
      }
      bb_end(b, start);
    } else if (ct == FOURCC('i', 'p', 'r', 'p')) {
      const size_t start = bb_begin(b, ct);
      const size_t ipco = bb_begin(b, FOURCC('i', 'p', 'c', 'o'));
      for (size_t i = 0; i < f->num_ipco; i++) {
        if (r->rw->hvcc_index == i + 1) {
          const size_t ps = bb_begin(b, FOURCC('h', 'v', 'c', 'C'));
          bb_put(b, r->rw->hvcc, r->rw->hvcc_len);
          bb_end(b, ps);
        } else {
          bb_put(b, f->ipco[i].p, f->ipco[i].n);
        }
      }
      bb_end(b, ipco);
      const size_t ipma = bb_begin(b, FOURCC('i', 'p', 'm', 'a'));
      bb_u8(b, (unsigned)f->ipma_version);
      bb_u16(b, 0);
      bb_u8(b, (unsigned)f->ipma_flags);
      size_t count = 0;
      for (size_t i = 0; i < f->num_ipma; i++) count += is_kept(r, f->ipma_order[i]);
      bb_u32(b, (uint32_t)count);
      for (size_t i = 0; i < f->num_ipma; i++) {
        const hb_item_t *item = hb_item(f, f->ipma_order[i]);
        if (!item || !is_kept(r, item->id)) continue;
        if (f->ipma_version == 0) {
          bb_u16(b, item->id);
        } else {
          bb_u32(b, item->id);
        }
        bb_u8(b, (unsigned)item->num_props);
        for (size_t p = 0; p < item->num_props; p++) {
          if (f->ipma_flags & 1) {
            bb_u16(b, (item->essential[p] ? 0x8000u : 0) | item->props[p]);
          } else {
            bb_u8(b, (item->essential[p] ? 0x80u : 0) | item->props[p]);
          }
        }
      }
      bb_end(b, ipma);
      bb_end(b, start);
    } else if (ct == FOURCC('i', 'l', 'o', 'c')) {
      const size_t start = bb_begin(b, ct);
      const int v = f->iloc_version;
      bb_u8(b, (unsigned)v);
      bb_u16(b, 0);
      bb_u8(b, 0);
      bb_u8(b, 0x44);  // offset_size 4, length_size 4
      bb_u8(b, 0x00);  // base_offset_size 0, index_size 0
      size_t count = 0;
      for (size_t i = 0; i < f->num_items; i++) count += r->kept[i] && f->items[i].located;
      if (v < 2) {
        bb_u16(b, (unsigned)count);
      } else {
        bb_u32(b, (uint32_t)count);
      }
      for (size_t i = 0; i < f->num_items; i++) {
        const hb_item_t *item = &f->items[i];
        if (!r->kept[i] || !item->located) continue;
        if (v < 2) {
          bb_u16(b, item->id);
        } else {
          bb_u32(b, item->id);
        }
        if (v >= 1) bb_u16(b, (unsigned)item->method);
        bb_u16(b, 0);  // data_reference_index
        if (item->method == 0) {
          bb_u16(b, 1);
          bb_u32(b, (uint32_t)(mdat_start + r->offsets[i]));
          bb_u32(b, (uint32_t)r->lengths[i]);
        } else {
          bb_u16(b, (unsigned)item->num_extents);
          for (size_t e = 0; e < item->num_extents; e++) {
            const hb_extent_t *ext = &f->extents[item->first_extent + e];
            bb_u32(b, (uint32_t)ext->offset);
            bb_u32(b, (uint32_t)ext->length);
          }
        }
      }
      bb_end(b, start);
    } else if (ct == FOURCC('g', 'r', 'p', 'l')) {
      bb_t groups = {NULL, 0, 0, 0};
      for (size_t g = 0; g < f->num_groups; g++) {
        const hb_group_t *grp = &f->groups[g];
        size_t n = 0;
        for (size_t j = 0; j < grp->num_ids; j++) n += is_kept(r, grp->ids[j]);
        if (n < 2) continue;
        const size_t gs = bb_begin(&groups, grp->type);
        bb_u32(&groups, 0);  // version and flags
        bb_u32(&groups, grp->id);
        bb_u32(&groups, (uint32_t)n);
        for (size_t j = 0; j < grp->num_ids; j++) {
          if (is_kept(r, grp->ids[j])) bb_u32(&groups, grp->ids[j]);
        }
        bb_end(&groups, gs);
      }
      if (groups.oom) b->oom = 1;
      if (groups.len) {
        const size_t start = bb_begin(b, ct);
        bb_put(b, groups.data, groups.len);
        bb_end(b, start);
      }
      free(groups.data);
    } else {
      bb_put(b, box.p, box.n);  // hdlr, pitm, idat, dinf, ...
    }
  }
  bb_end(b, meta);
}

int hb_rewrite(const hb_file_t *f, const hb_rewrite_t *rw, uint8_t **out, size_t *out_len) {
  *out = NULL;
  *out_len = 0;
  rewrite_t r;
  r.f = f;
  r.rw = rw;
  r.kept = (uint8_t *)calloc(f->num_items ? f->num_items : 1, 1);
  r.offsets = (uint64_t *)calloc(f->num_items ? f->num_items : 1, sizeof *r.offsets);
  r.lengths = (size_t *)calloc(f->num_items ? f->num_items : 1, sizeof *r.lengths);
  size_t *order = (size_t *)calloc(f->num_items ? f->num_items : 1, sizeof *order);
  int rc = -1;
  bb_t b = {NULL, 0, 0, 0};
  if (!r.kept || !r.offsets || !r.lengths || !order) goto done;
  for (size_t i = 0; i < f->num_items; i++) {
    for (size_t k = 0; k < rw->num_keep; k++) {
      if (rw->keep[k] == f->items[i].id) r.kept[i] = 1;
    }
  }
  // The data's order in the new 'mdat': the kept items with file data, by
  // where their data was (replaced data in the place of the old).
  size_t n_order = 0;
  for (size_t i = 0; i < f->num_items; i++) {
    if (r.kept[i] && f->items[i].located && f->items[i].method == 0) order[n_order++] = i;
  }
  for (size_t a = 1; a < n_order; a++) {  // insertion sort by first extent offset
    const size_t x = order[a];
    const uint64_t key = f->items[x].num_extents ? f->extents[f->items[x].first_extent].offset : 0;
    size_t j = a;
    while (j > 0) {
      const size_t y = order[j - 1];
      const uint64_t ky = f->items[y].num_extents ? f->extents[f->items[y].first_extent].offset : 0;
      if (ky <= key) break;
      order[j] = y;
      j--;
    }
    order[j] = x;
  }
  uint64_t pos = 0;
  for (size_t k = 0; k < n_order; k++) {
    const size_t i = order[k];
    const hb_replace_t *rep = replacement(&r, f->items[i].id);
    size_t len;
    if (rep) {
      len = rep->len;
    } else {
      len = item_extents(f, &f->items[i], NULL, 0);
      if (len == (size_t)-1) goto done;
    }
    r.offsets[i] = pos;
    r.lengths[i] = len;
    pos += len;
  }
  // 'meta' once to measure it (its size doesn't depend on the offsets), then
  // for real with the offsets into 'mdat'.
  write_meta(&b, &r, 0);
  if (b.oom) goto done;
  const uint64_t mdat_start = f->ftyp.n + b.len + 8;
  b.len = 0;
  bb_put(&b, f->ftyp.p, f->ftyp.n);
  write_meta(&b, &r, mdat_start);
  const size_t mdat = bb_begin(&b, FOURCC('m', 'd', 'a', 't'));
  for (size_t k = 0; k < n_order; k++) {
    const size_t i = order[k];
    const hb_replace_t *rep = replacement(&r, f->items[i].id);
    if (rep) {
      bb_put(&b, rep->data, rep->len);
    } else {
      span_t spans[1024];
      if (f->items[i].num_extents > 1024) goto done;
      item_extents(f, &f->items[i], spans, 1024);
      for (size_t e = 0; e < f->items[i].num_extents; e++) bb_put(&b, spans[e].p, spans[e].n);
    }
  }
  bb_end(&b, mdat);
  if (b.oom) goto done;
  *out = b.data;
  *out_len = b.len;
  b.data = NULL;
  rc = 0;
done:
  free(b.data);
  free(r.kept);
  free(r.offsets);
  free(r.lengths);
  free(order);
  return rc;
}

// ---------------------------------------------------------------------------
// A new file

static void put_fullbox(bb_t *b, uint32_t v, uint32_t flags) { bb_u32(b, (v << 24) | (flags & 0xffffff)); }

static void put_infe(bb_t *b, uint32_t id, uint32_t flags, uint32_t type) {
  const size_t s = bb_begin(b, FOURCC('i', 'n', 'f', 'e'));
  put_fullbox(b, 2, flags);
  bb_u16(b, id);
  bb_u16(b, 0);  // protection
  bb_u32(b, type);
  bb_u8(b, 0);  // name
  bb_end(b, s);
}

static void put_ispe(bb_t *b, uint32_t w, uint32_t h) {
  const size_t s = bb_begin(b, FOURCC('i', 's', 'p', 'e'));
  put_fullbox(b, 0, 0);
  bb_u32(b, w);
  bb_u32(b, h);
  bb_end(b, s);
}

int hb_write_new(const hb_new_t *n, uint8_t **out, size_t *out_len) {
  *out = NULL;
  *out_len = 0;
  const size_t num_tiles = (size_t)n->rows * n->cols;
  const int single = num_tiles == 1 && n->tile_w == n->w && n->tile_h == n->h;
  // items: tiles 1..T, then the grid (unless single), then Exif
  const uint32_t grid_id = single ? 1 : (uint32_t)num_tiles + 1;
  const uint32_t primary = grid_id;
  const uint32_t exif_id = primary + 1;
  // properties: 1 ispe (tile), 2 hvcC, 3 colr, 4 pixi, 5 ispe (picture)
  const uint32_t P_ISPE_TILE = 1, P_HVCC = 2, P_COLR = 3, P_PIXI = 4, P_ISPE = 5;
  bb_t b = {NULL, 0, 0, 0};

  // ftyp
  size_t s = bb_begin(&b, FOURCC('f', 't', 'y', 'p'));
  bb_u32(&b, FOURCC('h', 'e', 'i', 'c'));
  bb_u32(&b, 0);
  bb_u32(&b, FOURCC('m', 'i', 'f', '1'));
  bb_u32(&b, FOURCC('h', 'e', 'i', 'c'));
  bb_end(&b, s);

  // meta, written twice: the second time with the offsets into mdat
  const size_t meta_at = b.len;
  uint64_t mdat_start = 0;
  for (int pass = 0; pass < 2; pass++) {
    b.len = meta_at;
    const size_t meta = bb_begin(&b, FOURCC('m', 'e', 't', 'a'));
    put_fullbox(&b, 0, 0);
    s = bb_begin(&b, FOURCC('h', 'd', 'l', 'r'));
    put_fullbox(&b, 0, 0);
    bb_u32(&b, 0);
    bb_u32(&b, FOURCC('p', 'i', 'c', 't'));
    bb_u32(&b, 0);
    bb_u32(&b, 0);
    bb_u32(&b, 0);
    bb_u8(&b, 0);
    bb_end(&b, s);
    s = bb_begin(&b, FOURCC('p', 'i', 't', 'm'));
    put_fullbox(&b, 0, 0);
    bb_u16(&b, primary);
    bb_end(&b, s);
    // iinf
    s = bb_begin(&b, FOURCC('i', 'i', 'n', 'f'));
    put_fullbox(&b, 0, 0);
    bb_u16(&b, (unsigned)(single ? 1 : num_tiles + 1) + (n->exif ? 1 : 0));
    if (single) {
      put_infe(&b, 1, 0, FOURCC('h', 'v', 'c', '1'));
    } else {
      for (size_t t = 0; t < num_tiles; t++) put_infe(&b, (uint32_t)t + 1, 1, FOURCC('h', 'v', 'c', '1'));
      put_infe(&b, grid_id, 0, FOURCC('g', 'r', 'i', 'd'));
    }
    if (n->exif) put_infe(&b, exif_id, 1, FOURCC('E', 'x', 'i', 'f'));
    bb_end(&b, s);
    // iref
    if (!single || n->exif) {
      s = bb_begin(&b, FOURCC('i', 'r', 'e', 'f'));
      put_fullbox(&b, 0, 0);
      if (!single) {
        const size_t rs = bb_begin(&b, FOURCC('d', 'i', 'm', 'g'));
        bb_u16(&b, grid_id);
        bb_u16(&b, (unsigned)num_tiles);
        for (size_t t = 0; t < num_tiles; t++) bb_u16(&b, (unsigned)t + 1);
        bb_end(&b, rs);
      }
      if (n->exif) {
        const size_t rs = bb_begin(&b, FOURCC('c', 'd', 's', 'c'));
        bb_u16(&b, exif_id);
        bb_u16(&b, 1);
        bb_u16(&b, primary);
        bb_end(&b, rs);
      }
      bb_end(&b, s);
    }
    // iprp
    s = bb_begin(&b, FOURCC('i', 'p', 'r', 'p'));
    const size_t ipco = bb_begin(&b, FOURCC('i', 'p', 'c', 'o'));
    put_ispe(&b, n->tile_w, n->tile_h);
    size_t p = bb_begin(&b, FOURCC('h', 'v', 'c', 'C'));
    bb_put(&b, n->hvcc, n->hvcc_len);
    bb_end(&b, p);
    p = bb_begin(&b, FOURCC('c', 'o', 'l', 'r'));
    if (n->icc) {
      bb_u32(&b, FOURCC('p', 'r', 'o', 'f'));
      bb_put(&b, n->icc, n->icc_len);
    } else {
      bb_u32(&b, FOURCC('n', 'c', 'l', 'x'));
      bb_u16(&b, n->nclx.primaries);
      bb_u16(&b, n->nclx.transfer);
      bb_u16(&b, n->nclx.matrix);
      bb_u8(&b, n->nclx.full_range ? 0x80 : 0);
    }
    bb_end(&b, p);
    p = bb_begin(&b, FOURCC('p', 'i', 'x', 'i'));
    put_fullbox(&b, 0, 0);
    bb_u8(&b, 3);
    bb_u8(&b, 8);
    bb_u8(&b, 8);
    bb_u8(&b, 8);
    bb_end(&b, p);
    put_ispe(&b, n->w, n->h);
    bb_end(&b, ipco);
    const size_t ipma = bb_begin(&b, FOURCC('i', 'p', 'm', 'a'));
    put_fullbox(&b, 0, 0);
    bb_u32(&b, (uint32_t)(single ? 1 : num_tiles + 1));
    if (single) {
      bb_u16(&b, 1);
      bb_u8(&b, 4);
      bb_u8(&b, 0x80 | P_ISPE);
      bb_u8(&b, 0x80 | P_COLR);
      bb_u8(&b, 0x80 | P_HVCC);
      bb_u8(&b, P_PIXI);
    } else {
      for (size_t t = 0; t < num_tiles; t++) {
        bb_u16(&b, (unsigned)t + 1);
        bb_u8(&b, 3);
        bb_u8(&b, 0x80 | P_ISPE_TILE);
        bb_u8(&b, 0x80 | P_COLR);
        bb_u8(&b, 0x80 | P_HVCC);
      }
      bb_u16(&b, grid_id);
      bb_u8(&b, 3);
      bb_u8(&b, 0x80 | P_COLR);
      bb_u8(&b, P_ISPE);
      bb_u8(&b, P_PIXI);
    }
    bb_end(&b, ipma);
    bb_end(&b, s);
    // idat: the grid's payload
    if (!single) {
      s = bb_begin(&b, FOURCC('i', 'd', 'a', 't'));
      const int wide = n->w > 0xffff || n->h > 0xffff;
      bb_u8(&b, 0);  // version
      bb_u8(&b, wide ? 1 : 0);
      bb_u8(&b, n->rows - 1);
      bb_u8(&b, n->cols - 1);
      if (wide) {
        bb_u32(&b, n->w);
        bb_u32(&b, n->h);
      } else {
        bb_u16(&b, n->w);
        bb_u16(&b, n->h);
      }
      bb_end(&b, s);
    }
    // iloc
    s = bb_begin(&b, FOURCC('i', 'l', 'o', 'c'));
    put_fullbox(&b, 1, 0);
    bb_u8(&b, 0x44);
    bb_u8(&b, 0x00);
    bb_u16(&b, (unsigned)(single ? 1 : num_tiles + 1) + (n->exif ? 1 : 0));
    uint64_t pos = mdat_start;
    for (size_t t = 0; t < num_tiles; t++) {
      bb_u16(&b, (unsigned)t + 1);
      bb_u16(&b, 0);  // construction method 0
      bb_u16(&b, 0);  // data reference
      bb_u16(&b, 1);
      bb_u32(&b, (uint32_t)pos);
      bb_u32(&b, (uint32_t)n->tiles[t].len);
      pos += n->tiles[t].len;
    }
    if (!single) {
      bb_u16(&b, grid_id);
      bb_u16(&b, 1);  // in idat
      bb_u16(&b, 0);
      bb_u16(&b, 1);
      bb_u32(&b, 0);
      bb_u32(&b, n->w > 0xffff || n->h > 0xffff ? 12 : 8);
    }
    if (n->exif) {
      bb_u16(&b, exif_id);
      bb_u16(&b, 0);
      bb_u16(&b, 0);
      bb_u16(&b, 1);
      bb_u32(&b, (uint32_t)pos);
      bb_u32(&b, (uint32_t)(4 + n->exif_len));
    }
    bb_end(&b, s);
    bb_end(&b, meta);
    mdat_start = b.len + 8;
  }
  // mdat
  s = bb_begin(&b, FOURCC('m', 'd', 'a', 't'));
  for (size_t t = 0; t < num_tiles; t++) bb_put(&b, n->tiles[t].data, n->tiles[t].len);
  if (n->exif) {
    bb_u32(&b, 0);  // offset of the TIFF header
    bb_put(&b, n->exif, n->exif_len);
  }
  bb_end(&b, s);
  if (b.oom) {
    free(b.data);
    return -1;
  }
  *out = b.data;
  *out_len = b.len;
  return 0;
}
