#include "meta.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// stb_image's zlib decoder (compiled in pixels.c); returns a malloc'ed buffer.
char *stbi_zlib_decode_malloc_guesssize_headerflag(const char *buffer, int len,
                                                   int initial_size,
                                                   int *outlen,
                                                   int parse_header);

#define FOURCC(a, b, c, d)                                             \
  (((uint32_t)(a) << 24) | ((uint32_t)(b) << 16) | ((uint32_t)(c) << 8) | \
   (uint32_t)(d))

static uint16_t rd16be(const uint8_t *p) { return (uint16_t)((p[0] << 8) | p[1]); }
static uint32_t rd32be(const uint8_t *p) {
  return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
         ((uint32_t)p[2] << 8) | p[3];
}
static uint64_t rdNbe(const uint8_t *p, int n) {
  uint64_t v = 0;
  for (int i = 0; i < n; i++) v = (v << 8) | p[i];
  return v;
}

static int is_tiff(const uint8_t *p, size_t n) {
  if (n < 8) return 0;
  return (p[0] == 'I' && p[1] == 'I' && p[2] == 42 && p[3] == 0) ||
         (p[0] == 'M' && p[1] == 'M' && p[2] == 0 && p[3] == 42);
}

// Offset of the TIFF header in p (skipping an optional "Exif\0\0"), or -1.
static long tiff_offset(const uint8_t *p, size_t n) {
  if (n >= 6 && memcmp(p, "Exif\0\0", 6) == 0) {
    return is_tiff(p + 6, n - 6) ? 6 : -1;
  }
  return is_tiff(p, n) ? 0 : -1;
}

static int blob_set(blob_t *b, const uint8_t *p, size_t n) {
  free(b->data);
  b->data = NULL;
  b->size = 0;
  if (n == 0) return 0;
  b->data = (uint8_t *)malloc(n);
  if (!b->data) return -1;
  memcpy(b->data, p, n);
  b->size = n;
  return 0;
}

file_format_t detect_format(const uint8_t *b, size_t n) {
  if (n >= 3 && b[0] == 0xFF && b[1] == 0xD8 && b[2] == 0xFF) return FMT_JPEG;
  if (n >= 8 && memcmp(b, "\x89PNG\r\n\x1a\n", 8) == 0) return FMT_PNG;
  if (n >= 12 && memcmp(b + 4, "ftyp", 4) == 0) {
    // Any ISOBMFF file with a 'meta' box is handled by the HEIF parser; check
    // the major brand only to report a sensible format name.
    return FMT_HEIF;
  }
  return FMT_UNKNOWN;
}

const char *format_name(file_format_t f) {
  switch (f) {
    case FMT_HEIF: return "HEIF";
    case FMT_JPEG: return "JPEG";
    case FMT_PNG: return "PNG";
    default: return "unknown";
  }
}

// ---------------------------------------------------------------------------
// ISOBMFF / HEIF

typedef struct {
  const uint8_t *p;
  size_t n;
} span_t;

typedef struct {
  const uint8_t *p;
  size_t n;
  size_t pos;
} box_iter_t;

static int box_next(box_iter_t *it, uint32_t *type, span_t *payload) {
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

typedef struct {
  uint32_t id;
  uint32_t type;
  char content_type[64];
} heif_item_t;

typedef struct {
  uint32_t id;
  int method;  // 0 = file offset, 1 = idat offset
  uint64_t base;
  size_t first_extent;
  size_t num_extents;
} heif_loc_t;

typedef struct {
  uint64_t offset;
  uint64_t length;
} heif_extent_t;

typedef struct {
  heif_item_t *items;
  size_t num_items;
  heif_loc_t *locs;
  size_t num_locs;
  heif_extent_t *extents;
  size_t num_extents;
  uint32_t *cdsc;  // pairs: from (metadata item), to (image item)
  size_t num_cdsc;
  uint32_t primary;
  int has_primary;
  span_t idat;
} heif_t;

static void heif_free(heif_t *h) {
  free(h->items);
  free(h->locs);
  free(h->extents);
  free(h->cdsc);
}

#define HEIF_MAX_ENTRIES 65536

static void heif_parse_iinf(heif_t *h, span_t box) {
  if (box.n < 6) return;
  int version = box.p[0];
  size_t off = version == 0 ? 6 : 8;
  if (box.n < off) return;
  box_iter_t it = {box.p + off, box.n - off, 0};
  uint32_t t;
  span_t pl;
  size_t cap = 0;
  while (box_next(&it, &t, &pl)) {
    if (t != FOURCC('i', 'n', 'f', 'e') || pl.n < 4) continue;
    int v = pl.p[0];
    if (v < 2) continue;  // HEIF requires infe version >= 2
    const uint8_t *q = pl.p + 4;
    size_t qn = pl.n - 4;
    size_t idsz = v == 2 ? 2 : 4;
    if (qn < idsz + 2 + 4) continue;
    heif_item_t item;
    memset(&item, 0, sizeof item);
    item.id = v == 2 ? rd16be(q) : rd32be(q);
    q += idsz + 2;  // item_ID, item_protection_index
    qn -= idsz + 2;
    item.type = rd32be(q);
    q += 4;
    qn -= 4;
    const uint8_t *z = (const uint8_t *)memchr(q, 0, qn);  // item_name
    if (z && item.type == FOURCC('m', 'i', 'm', 'e')) {
      qn -= (size_t)(z - q) + 1;
      q = z + 1;
      const uint8_t *z2 = (const uint8_t *)memchr(q, 0, qn);
      size_t len = z2 ? (size_t)(z2 - q) : qn;
      if (len >= sizeof item.content_type) len = sizeof item.content_type - 1;
      memcpy(item.content_type, q, len);
    }
    if (h->num_items == cap) {
      if (cap >= HEIF_MAX_ENTRIES) break;
      cap = cap ? cap * 2 : 16;
      heif_item_t *grown = (heif_item_t *)realloc(h->items, cap * sizeof *grown);
      if (!grown) break;
      h->items = grown;
    }
    h->items[h->num_items++] = item;
  }
}

static void heif_parse_iloc(heif_t *h, span_t box) {
  if (box.n < 8) return;
  int version = box.p[0];
  if (version > 2) return;
  const uint8_t *q = box.p + 4;
  size_t qn = box.n - 4;
  int offset_size = q[0] >> 4, length_size = q[0] & 15;
  int base_offset_size = q[1] >> 4;
  int index_size = (version == 1 || version == 2) ? (q[1] & 15) : 0;
  q += 2;
  qn -= 2;
  uint32_t count;
  if (version < 2) {
    if (qn < 2) return;
    count = rd16be(q);
    q += 2;
    qn -= 2;
  } else {
    if (qn < 4) return;
    count = rd32be(q);
    q += 4;
    qn -= 4;
  }
  if (offset_size > 8 || length_size > 8 || base_offset_size > 8 || index_size > 8) return;
  if (count > HEIF_MAX_ENTRIES) return;
  h->locs = (heif_loc_t *)calloc(count ? count : 1, sizeof *h->locs);
  if (!h->locs) return;
  size_t ext_cap = 0;
  size_t idsz = version < 2 ? 2 : 4;
  for (uint32_t i = 0; i < count; i++) {
    heif_loc_t loc;
    memset(&loc, 0, sizeof loc);
    if (qn < idsz) return;
    loc.id = version < 2 ? rd16be(q) : rd32be(q);
    q += idsz;
    qn -= idsz;
    if (version == 1 || version == 2) {
      if (qn < 2) return;
      loc.method = rd16be(q) & 15;
      q += 2;
      qn -= 2;
    }
    if (qn < 2 + (size_t)base_offset_size + 2) return;
    q += 2;  // data_reference_index
    qn -= 2;
    loc.base = rdNbe(q, base_offset_size);
    q += base_offset_size;
    qn -= base_offset_size;
    uint16_t next = rd16be(q);
    q += 2;
    qn -= 2;
    loc.first_extent = h->num_extents;
    for (uint16_t e = 0; e < next; e++) {
      size_t need = (size_t)index_size + offset_size + length_size;
      if (qn < need) return;
      q += index_size;
      heif_extent_t ext;
      ext.offset = rdNbe(q, offset_size);
      q += offset_size;
      ext.length = rdNbe(q, length_size);
      q += length_size;
      qn -= need;
      if (h->num_extents == ext_cap) {
        if (ext_cap >= HEIF_MAX_ENTRIES) return;
        ext_cap = ext_cap ? ext_cap * 2 : 16;
        heif_extent_t *grown =
            (heif_extent_t *)realloc(h->extents, ext_cap * sizeof *grown);
        if (!grown) return;
        h->extents = grown;
      }
      h->extents[h->num_extents++] = ext;
    }
    loc.num_extents = h->num_extents - loc.first_extent;
    h->locs[h->num_locs++] = loc;
  }
}

static void heif_parse_iref(heif_t *h, span_t box) {
  if (box.n < 4) return;
  int version = box.p[0];
  size_t idsz = version == 0 ? 2 : 4;
  box_iter_t it = {box.p + 4, box.n - 4, 0};
  uint32_t t;
  span_t pl;
  size_t cap = 0;
  while (box_next(&it, &t, &pl)) {
    if (t != FOURCC('c', 'd', 's', 'c')) continue;
    if (pl.n < idsz + 2) continue;
    uint32_t from = idsz == 2 ? rd16be(pl.p) : rd32be(pl.p);
    uint16_t cnt = rd16be(pl.p + idsz);
    const uint8_t *q = pl.p + idsz + 2;
    size_t qn = pl.n - idsz - 2;
    for (uint16_t i = 0; i < cnt && qn >= idsz; i++) {
      uint32_t to = idsz == 2 ? rd16be(q) : rd32be(q);
      q += idsz;
      qn -= idsz;
      if (h->num_cdsc == cap) {
        if (cap >= HEIF_MAX_ENTRIES) return;
        cap = cap ? cap * 2 : 8;
        uint32_t *grown = (uint32_t *)realloc(h->cdsc, cap * 2 * sizeof *grown);
        if (!grown) return;
        h->cdsc = grown;
      }
      h->cdsc[2 * h->num_cdsc] = from;
      h->cdsc[2 * h->num_cdsc + 1] = to;
      h->num_cdsc++;
    }
  }
}

// Copies the item's bytes (all extents concatenated) into a new buffer.
static uint8_t *heif_item_data(const heif_t *h, const uint8_t *file, size_t file_len,
                               uint32_t id, size_t *out_len) {
  const heif_loc_t *loc = NULL;
  for (size_t i = 0; i < h->num_locs; i++) {
    if (h->locs[i].id == id) {
      loc = &h->locs[i];
      break;
    }
  }
  if (!loc || loc->num_extents == 0) return NULL;
  const uint8_t *src;
  size_t src_len;
  if (loc->method == 0) {
    src = file;
    src_len = file_len;
  } else if (loc->method == 1 && h->idat.p) {
    src = h->idat.p;
    src_len = h->idat.n;
  } else {
    return NULL;
  }
  uint64_t total = 0;
  for (size_t e = 0; e < loc->num_extents; e++) {
    const heif_extent_t *ext = &h->extents[loc->first_extent + e];
    uint64_t start = loc->base + ext->offset;
    uint64_t len = ext->length;
    if (start > src_len) return NULL;
    if (len == 0) len = src_len - start;  // "to the end" (single extent)
    if (len > src_len - start) return NULL;
    total += len;
  }
  if (total == 0 || total > (uint64_t)1 << 30) return NULL;
  uint8_t *out = (uint8_t *)malloc((size_t)total);
  if (!out) return NULL;
  size_t pos = 0;
  for (size_t e = 0; e < loc->num_extents; e++) {
    const heif_extent_t *ext = &h->extents[loc->first_extent + e];
    uint64_t start = loc->base + ext->offset;
    uint64_t len = ext->length ? ext->length : src_len - start;
    memcpy(out + pos, src + start, (size_t)len);
    pos += (size_t)len;
  }
  *out_len = pos;
  return out;
}

static int heif_describes_primary(const heif_t *h, uint32_t item_id) {
  if (!h->has_primary) return 0;
  for (size_t i = 0; i < h->num_cdsc; i++) {
    if (h->cdsc[2 * i] == item_id && h->cdsc[2 * i + 1] == h->primary) return 1;
  }
  return 0;
}

// Picks the best item of the given type (preferring one linked to the
// primary image) and returns its id, or 0.
static uint32_t heif_pick_item(const heif_t *h, uint32_t type, const char *content_type) {
  uint32_t best = 0;
  int best_score = -1;
  for (size_t i = 0; i < h->num_items; i++) {
    const heif_item_t *it = &h->items[i];
    if (it->type != type) continue;
    if (content_type && strcmp(it->content_type, content_type) != 0) continue;
    int score = heif_describes_primary(h, it->id) ? 1 : 0;
    if (score > best_score) {
      best = it->id;
      best_score = score;
    }
  }
  return best;
}

// The 'meta' box of a HEIF file (a FullBox: payload after its 4 bytes of
// version and flags), or an empty span.
static span_t heif_meta(const uint8_t *buf, size_t len) {
  box_iter_t top = {buf, len, 0};
  uint32_t t;
  span_t pl, none = {NULL, 0};
  while (box_next(&top, &t, &pl)) {
    if (t == FOURCC('m', 'e', 't', 'a')) {
      if (pl.n < 4) return none;
      pl.p += 4;
      pl.n -= 4;
      return pl;
    }
  }
  return none;
}

static span_t child_box(span_t parent, uint32_t type) {
  box_iter_t it = {parent.p, parent.n, 0};
  uint32_t t;
  span_t pl, none = {NULL, 0};
  while (box_next(&it, &t, &pl)) {
    if (t == type) return pl;
  }
  return none;
}

// Property `index` (from 1) of 'ipco': its type and payload. Returns 0 if
// there is none.
static int ipco_property(span_t ipco, uint32_t index, uint32_t *type, span_t *prop) {
  box_iter_t it = {ipco.p, ipco.n, 0};
  for (uint32_t i = 1; index > 0 && box_next(&it, type, prop); i++) {
    if (i == index) return 1;
  }
  return 0;
}

// Calls `fn` on each property of HEIF item `id`, in order, until it returns
// nonzero; returns that value (0 if none did).
static size_t each_item_property(const uint8_t *buf, size_t len, uint32_t id,
                                 size_t (*fn)(uint32_t type, span_t prop, void *arg), void *arg) {
  const span_t iprp = child_box(heif_meta(buf, len), FOURCC('i', 'p', 'r', 'p'));
  const span_t ipco = child_box(iprp, FOURCC('i', 'p', 'c', 'o'));
  if (!ipco.p) return 0;
  box_iter_t it = {iprp.p, iprp.n, 0};
  uint32_t t;
  span_t ipma;
  while (box_next(&it, &t, &ipma)) {  // every 'ipma'
    if (t != FOURCC('i', 'p', 'm', 'a') || ipma.n < 8) continue;
    const size_t id_size = ipma.p[0] == 0 ? 2 : 4;      // by version
    const size_t index_size = ipma.p[3] & 1 ? 2 : 1;  // by flags
    const uint8_t *q = ipma.p + 8, *end = ipma.p + ipma.n;
    for (uint32_t n = rd32be(ipma.p + 4); n > 0 && (size_t)(end - q) > id_size; n--) {
      const uint32_t item = id_size == 2 ? rd16be(q) : rd32be(q);
      const size_t count = q[id_size];
      q += id_size + 1;
      if ((size_t)(end - q) < count * index_size) break;
      for (size_t i = 0; item == id && i < count; i++) {
        const uint32_t index = index_size == 2 ? rd16be(q + 2 * i) & 0x7fffu : q[i] & 0x7fu;
        uint32_t type;
        span_t prop;
        if (!ipco_property(ipco, index, &type, &prop)) continue;
        const size_t result = fn(type, prop, arg);
        if (result) return result;
      }
      q += count * index_size;
    }
  }
  return 0;
}

// A 'colr' property with an ICC profile: its size, with `arg` set to it.
static size_t profile_of(uint32_t type, span_t prop, void *arg) {
  if (type != FOURCC('c', 'o', 'l', 'r') || prop.n < 4) return 0;
  const uint32_t kind = rd32be(prop.p);
  if (kind != FOURCC('p', 'r', 'o', 'f') && kind != FOURCC('r', 'I', 'C', 'C')) return 0;
  *(const uint8_t **)arg = prop.p + 4;
  return prop.n - 4;
}

size_t heif_item_profile(const uint8_t *buf, size_t len, uint32_t id, const uint8_t **icc) {
  return each_item_property(buf, len, id, profile_of, (void *)icc);
}

// 1 if the property is an 'auxC' with the type in `arg`.
static size_t is_aux_type(uint32_t type, span_t prop, void *arg) {
  const char *want = (const char *)arg;
  const size_t n = strlen(want);
  // version and flags, then the type, NUL-terminated
  return type == FOURCC('a', 'u', 'x', 'C') && prop.n > 4 + n && memcmp(prop.p + 4, want, n) == 0 &&
         prop.p[4 + n] == 0;
}

int heif_item_has_aux_type(const uint8_t *buf, size_t len, uint32_t id, const char *aux_type) {
  return each_item_property(buf, len, id, is_aux_type, (void *)aux_type) != 0;
}

static int parse_heif(const uint8_t *buf, size_t len, meta_t *m) {
  const span_t meta = heif_meta(buf, len);
  if (!meta.p) return 0;

  heif_t h;
  memset(&h, 0, sizeof h);
  uint32_t t;
  span_t pl, iinf = {NULL, 0}, iloc = {NULL, 0}, iref = {NULL, 0};
  box_iter_t mi = {meta.p, meta.n, 0};
  while (box_next(&mi, &t, &pl)) {
    if (t == FOURCC('p', 'i', 't', 'm') && pl.n >= 6) {
      h.primary = pl.p[0] == 0 ? rd16be(pl.p + 4) : (pl.n >= 8 ? rd32be(pl.p + 4) : 0);
      h.has_primary = 1;
    } else if (t == FOURCC('i', 'i', 'n', 'f')) {
      iinf = pl;
    } else if (t == FOURCC('i', 'l', 'o', 'c')) {
      iloc = pl;
    } else if (t == FOURCC('i', 'r', 'e', 'f')) {
      iref = pl;
    } else if (t == FOURCC('i', 'd', 'a', 't')) {
      h.idat = pl;
    }
  }
  if (iinf.p) heif_parse_iinf(&h, iinf);
  if (iloc.p) heif_parse_iloc(&h, iloc);
  if (iref.p) heif_parse_iref(&h, iref);

  int rc = 0;
  uint32_t exif_id = heif_pick_item(&h, FOURCC('E', 'x', 'i', 'f'), NULL);
  if (exif_id) {
    size_t n = 0;
    uint8_t *d = heif_item_data(&h, buf, len, exif_id, &n);
    if (d && n > 4) {
      // Payload: 4-byte offset to the TIFF header, counted from byte 4.
      uint32_t off = rd32be(d);
      long tiff = -1;
      if ((uint64_t)off + 4 < n && is_tiff(d + 4 + off, n - 4 - off)) {
        tiff = 4 + (long)off;
      } else {
        long rel = tiff_offset(d + 4, n - 4);
        if (rel >= 0) tiff = 4 + rel;
      }
      if (tiff >= 0 && blob_set(&m->exif, d + tiff, n - (size_t)tiff) != 0) rc = -1;
    }
    free(d);
  }
  uint32_t xmp_id = heif_pick_item(&h, FOURCC('m', 'i', 'm', 'e'), "application/rdf+xml");
  if (xmp_id) {
    size_t n = 0;
    uint8_t *d = heif_item_data(&h, buf, len, xmp_id, &n);
    if (d && n > 0) {
      free(m->xmp.data);
      m->xmp.data = d;
      m->xmp.size = n;
      d = NULL;
    }
    free(d);
  }
  heif_free(&h);
  return rc;
}

// ---------------------------------------------------------------------------
// JPEG

// Joins the ICC profile from its APP2 "ICC_PROFILE" segments (numbered 1..count).
static int join_jpeg_icc(const uint8_t *const *parts, const size_t *lens, int count, meta_t *m) {
  size_t total = 0;
  for (int i = 1; i <= count; i++) {
    if (!parts[i]) return 0;  // incomplete profile: ignore it
    total += lens[i];
  }
  if (total == 0) return 0;
  m->icc.data = (uint8_t *)malloc(total);
  if (!m->icc.data) return -1;
  for (int i = 1; i <= count; i++) {
    memcpy(m->icc.data + m->icc.size, parts[i], lens[i]);
    m->icc.size += lens[i];
  }
  return 0;
}

#define MAX_EXTENDED_XMP (16u * 1024u * 1024u)

typedef struct {
  char guid[33];
  uint32_t total, offset;
  const uint8_t *data;
  size_t size;
} xmp_fragment_t;

static int metadata_error(char *err, size_t n, const char *message) {
  if (n) snprintf(err, n, "%s", message);
  return -1;
}

static int fragment_order(const void *a, const void *b) {
  const uint32_t x = ((const xmp_fragment_t *)a)->offset;
  const uint32_t y = ((const xmp_fragment_t *)b)->offset;
  return x < y ? -1 : x > y;
}

static int assemble_xmp(meta_t *m, xmp_fragment_t *parts, size_t count,
                        char *err, size_t err_len) {
  // Without extended fragments there is nothing to merge: the standard packet
  // is kept byte for byte, even if it isn't strict XML. But if it refers to
  // extended XMP, the fragments may have been missed, and converting would
  // lose them (and the original may then be deleted), so the photo fails.
  if (!count) {
    if (m->xmp.size && xmp_has_extended_reference(m->xmp.data, m->xmp.size))
      return metadata_error(err, err_len, "extended XMP fragments are missing");
    return 0;
  }
  char guid[33];
  const int reference = xmp_extended_guid(m->xmp.data, m->xmp.size, guid, err, err_len);
  if (reference < 0) return -1;
  if (!reference) return metadata_error(err, err_len, "extended XMP has no HasExtendedXMP reference");
  const uint32_t total = parts[0].total;
  if (!total || total > MAX_EXTENDED_XMP)
    return metadata_error(err, err_len, "extended XMP exceeds the 16 MiB limit or has zero length");
  qsort(parts, count, sizeof *parts, fragment_order);
  size_t covered = 0;
  for (size_t i = 0; i < count; ++i) {
    const xmp_fragment_t *p = &parts[i];
    if (strcmp(p->guid, guid))
      return metadata_error(err, err_len, "extended XMP GUID does not match HasExtendedXMP");
    if (p->total != total)
      return metadata_error(err, err_len, "extended XMP fragments disagree on total length");
    if (!p->size || p->offset > total || p->size > total - p->offset)
      return metadata_error(err, err_len, "extended XMP fragment is truncated or outside its declared length");
    if (p->offset < covered)
      return metadata_error(err, err_len, "extended XMP fragments overlap");
    if (p->offset > covered)
      return metadata_error(err, err_len, "extended XMP fragments are missing");
    covered += p->size;
  }
  if (covered != total)
    return metadata_error(err, err_len, "extended XMP fragments are missing or truncated");
  uint8_t *extended = (uint8_t *)malloc(total);
  if (!extended) return -1;
  for (size_t i = 0; i < count; ++i)
    memcpy(extended + parts[i].offset, parts[i].data, parts[i].size);
  uint8_t *merged = NULL;
  size_t merged_len = 0;
  const int rc = xmp_merge_extended(m->xmp.data, m->xmp.size, extended, total,
                                    &merged, &merged_len, err, err_len);
  free(extended);
  if (rc) return rc;
  free(m->xmp.data);
  m->xmp.data = merged;
  m->xmp.size = merged_len;
  return 0;
}

static int parse_jpeg(const uint8_t *b, size_t n, meta_t *m, char *err, size_t err_len) {
  static const char kXmpSig[] = "http://ns.adobe.com/xap/1.0/";  // + NUL
  static const char kExtSig[] = "http://ns.adobe.com/xmp/extension/";
  static const char kIccSig[] = "ICC_PROFILE";
  const uint8_t *icc_parts[256] = {0};
  size_t icc_lens[256] = {0};
  int icc_count = 0, rc = -1;
  xmp_fragment_t *parts = NULL;
  size_t count = 0, capacity = 0, pos = 2;
  while (pos + 2 <= n) {
    if (b[pos] != 0xFF || b[pos + 1] == 0xFF) { pos++; continue; }
    const uint8_t marker = b[pos + 1];
    pos += 2;
    if (marker == 0xD8 || marker == 0x01 || (marker >= 0xD0 && marker <= 0xD7)) continue;
    if (marker == 0xD9 || marker == 0xDA) break;
    // A damaged segment could hide metadata after it; fail rather than lose it.
    if (pos + 2 > n || rd16be(b + pos) < 2 || rd16be(b + pos) > n - pos) {
      metadata_error(err, err_len, "truncated JPEG metadata segment");
      goto done;
    }
    const size_t seg_len = rd16be(b + pos), dn = seg_len - 2;
    const uint8_t *d = b + pos + 2;
    if (marker == 0xE1) {
      if (!m->exif.size && dn > 6 && !memcmp(d, "Exif\0\0", 6) && is_tiff(d + 6, dn - 6)) {
        if (blob_set(&m->exif, d + 6, dn - 6)) goto done;
      } else if (dn >= sizeof kXmpSig && !memcmp(d, kXmpSig, sizeof kXmpSig)) {
        // The first nonempty packet is the photo's XMP; empty or repeated
        // packets are ignored, as other readers do.
        if (!m->xmp.size && dn > sizeof kXmpSig &&
            blob_set(&m->xmp, d + sizeof kXmpSig, dn - sizeof kXmpSig))
          goto done;
      } else if (dn >= sizeof kExtSig && !memcmp(d, kExtSig, sizeof kExtSig)) {
        if (dn < sizeof kExtSig + 40) {
          metadata_error(err, err_len, "truncated extended XMP fragment header");
          goto done;
        }
        if (count == capacity) {
          size_t next = capacity ? capacity * 2 : 8;
          xmp_fragment_t *grown = (xmp_fragment_t *)realloc(parts, next * sizeof *parts);
          if (!grown) goto done;
          parts = grown;
          capacity = next;
        }
        xmp_fragment_t *p = &parts[count++];
        const uint8_t *header = d + sizeof kExtSig;
        for (size_t i = 0; i < 32; ++i) {
          char c = header[i];
          p->guid[i] = c >= 'a' && c <= 'f' ? c - 'a' + 'A' : c;
        }
        p->guid[32] = 0;
        p->total = rd32be(header + 32);
        p->offset = rd32be(header + 36);
        p->data = header + 40;
        p->size = dn - sizeof kExtSig - 40;
      }
    } else if (marker == 0xE2 && dn > sizeof kIccSig + 2 && !memcmp(d, kIccSig, sizeof kIccSig)) {
      const int seq = d[sizeof kIccSig], number = d[sizeof kIccSig + 1];
      if (seq >= 1 && seq <= number && (icc_count == 0 || icc_count == number)) {
        icc_count = number;
        icc_parts[seq] = d + sizeof kIccSig + 2;
        icc_lens[seq] = dn - sizeof kIccSig - 2;
      }
    }
    pos += seg_len;
  }
  if (assemble_xmp(m, parts, count, err, err_len)) goto done;
  rc = icc_count ? join_jpeg_icc(icc_parts, icc_lens, icc_count, m) : 0;
done:
  free(parts);
  return rc;
}

// ---------------------------------------------------------------------------
// PNG

static uint8_t *inflate_zlib(const uint8_t *p, size_t n, size_t *out_len) {
  if (n == 0 || n > 0x7fffffff) return NULL;
  int out = 0;
  int guess = n < (1 << 18) ? (int)(n * 4 + 1024) : (1 << 20);
  char *d = stbi_zlib_decode_malloc_guesssize_headerflag((const char *)p, (int)n, guess,
                                                         &out, 1);
  if (!d || out <= 0) {
    free(d);
    return NULL;
  }
  *out_len = (size_t)out;
  return (uint8_t *)d;
}

static int parse_png(const uint8_t *b, size_t n, meta_t *m) {
  size_t pos = 8;
  while (pos < n && n - pos >= 12) {
    uint32_t len = rd32be(b + pos);
    uint32_t type = rd32be(b + pos + 4);
    if (len > n - pos - 12) break;
    const uint8_t *d = b + pos + 8;
    if (type == FOURCC('e', 'X', 'I', 'f')) {
      long off = tiff_offset(d, len);
      if (off >= 0 && !m->exif.size) {
        if (blob_set(&m->exif, d + off, len - (size_t)off) != 0) return -1;
      }
    } else if (type == FOURCC('i', 'T', 'X', 't') && !m->xmp.size) {
      static const char kKey[] = "XML:com.adobe.xmp";
      if (len > sizeof kKey + 2 && memcmp(d, kKey, sizeof kKey) == 0) {  // key + NUL
        const uint8_t *q = d + sizeof kKey;
        size_t qn = len - sizeof kKey;
        int compressed = q[0];
        q += 2;  // compression flag, compression method
        qn -= 2;
        for (int skip = 0; skip < 2; skip++) {  // language tag, translated keyword
          const uint8_t *z = (const uint8_t *)memchr(q, 0, qn);
          if (!z) {
            qn = 0;
            break;
          }
          qn -= (size_t)(z - q) + 1;
          q = z + 1;
        }
        if (qn > 0) {
          if (compressed) {
            size_t out_len = 0;
            uint8_t *x = inflate_zlib(q, qn, &out_len);
            if (x) {
              m->xmp.data = x;
              m->xmp.size = out_len;
            }
          } else if (blob_set(&m->xmp, q, qn) != 0) {
            return -1;
          }
        }
      }
    } else if (type == FOURCC('i', 'C', 'C', 'P') && !m->icc.size) {
      const uint8_t *z = (const uint8_t *)memchr(d, 0, len);
      if (z && (size_t)(z - d) + 2 < len) {
        const uint8_t *q = z + 2;  // skip NUL and compression method
        size_t out_len = 0;
        uint8_t *icc = inflate_zlib(q, len - (size_t)(q - d), &out_len);
        if (icc) {
          m->icc.data = icc;
          m->icc.size = out_len;
        }
      }
    } else if (type == FOURCC('s', 'R', 'G', 'B')) {
      m->png_srgb = 1;
    } else if (type == FOURCC('c', 'I', 'C', 'P') && len == 4) {
      m->png_cicp_present = 1;
      memcpy(m->png_cicp, d, 4);
    } else if (type == FOURCC('I', 'E', 'N', 'D')) {
      break;
    }
    pos += 12 + (size_t)len;
  }
  return 0;
}

int meta_extract(const uint8_t *buf, size_t len, meta_t *m, char *err, size_t err_len) {
  memset(m, 0, sizeof *m);
  if (err_len) err[0] = 0;
  m->format = detect_format(buf, len);
  int rc = 0;
  switch (m->format) {
    case FMT_HEIF: rc = parse_heif(buf, len, m); break;
    case FMT_JPEG: rc = parse_jpeg(buf, len, m, err, err_len); break;
    case FMT_PNG: rc = parse_png(buf, len, m); break;
    default: break;
  }
  if (rc && err_len && !err[0]) metadata_error(err, err_len, "out of memory reading metadata");
  return rc;
}

void meta_free(meta_t *m) {
  free(m->exif.data);
  free(m->xmp.data);
  free(m->icc.data);
  memset(m, 0, sizeof *m);
}

// ---------------------------------------------------------------------------
// EXIF (TIFF) tag access

typedef struct {
  uint8_t *p;
  size_t n;
  int le;
} tiff_t;

static uint16_t t16(const tiff_t *t, size_t o) {
  return t->le ? (uint16_t)(t->p[o] | (t->p[o + 1] << 8))
               : (uint16_t)((t->p[o] << 8) | t->p[o + 1]);
}
static uint32_t t32(const tiff_t *t, size_t o) {
  return t->le ? ((uint32_t)t->p[o] | ((uint32_t)t->p[o + 1] << 8) |
                  ((uint32_t)t->p[o + 2] << 16) | ((uint32_t)t->p[o + 3] << 24))
               : rd32be(t->p + o);
}
static void w16(const tiff_t *t, size_t o, uint16_t v) {
  if (t->le) {
    t->p[o] = (uint8_t)v;
    t->p[o + 1] = (uint8_t)(v >> 8);
  } else {
    t->p[o] = (uint8_t)(v >> 8);
    t->p[o + 1] = (uint8_t)v;
  }
}
static void w32(const tiff_t *t, size_t o, uint32_t v) {
  for (int i = 0; i < 4; i++) {
    t->p[o + (t->le ? i : 3 - i)] = (uint8_t)(v >> (8 * i));
  }
}

enum { TIFF_SHORT = 3, TIFF_LONG = 4 };

// Offset of the 12-byte entry for `tag` in the IFD at `ifd`, or 0.
static size_t ifd_find(const tiff_t *t, uint32_t ifd, uint16_t tag) {
  if (ifd < 8 || (size_t)ifd + 2 > t->n) return 0;
  uint16_t count = t16(t, ifd);
  if ((size_t)ifd + 2 + (size_t)count * 12 > t->n) return 0;
  for (uint16_t i = 0; i < count; i++) {
    size_t e = (size_t)ifd + 2 + (size_t)i * 12;
    if (t16(t, e) == tag) return e;
  }
  return 0;
}

static int entry_uint(const tiff_t *t, size_t e, uint32_t *v) {
  if (!e || t32(t, e + 4) != 1) return 0;
  uint16_t type = t16(t, e + 2);
  if (type == TIFF_SHORT) {
    *v = t16(t, e + 8);
    return 1;
  }
  if (type == TIFF_LONG) {
    *v = t32(t, e + 8);
    return 1;
  }
  return 0;
}

static int tiff_open(tiff_t *t, const uint8_t *p, size_t n) {
  if (!is_tiff(p, n)) return 0;
  t->p = (uint8_t *)p;
  t->n = n;
  t->le = p[0] == 'I';
  return 1;
}

static uint32_t exif_ifd_offset(const tiff_t *t) {
  uint32_t off = 0;
  if (!entry_uint(t, ifd_find(t, t32(t, 4), 0x8769), &off)) return 0;
  return off;
}

int exif_orientation(const uint8_t *p, size_t n) {
  tiff_t t;
  uint32_t v = 0;
  if (!tiff_open(&t, p, n)) return 0;
  if (!entry_uint(&t, ifd_find(&t, t32(&t, 4), 0x0112), &v)) return 0;
  return (v >= 1 && v <= 8) ? (int)v : 0;
}

int exif_string(const uint8_t *p, size_t n, uint16_t tag, char *buf, size_t buf_len) {
  tiff_t t;
  if (buf_len == 0) return 0;
  buf[0] = 0;
  if (!tiff_open(&t, p, n)) return 0;
  const size_t e = ifd_find(&t, t32(&t, 4), tag);
  if (!e || t16(&t, e + 2) != 2) return 0;  // ASCII
  const uint32_t count = t32(&t, e + 4);
  const size_t src = count <= 4 ? e + 8 : t32(&t, e + 8);
  if (count == 0 || src > n || count > n - src) return 0;
  const size_t len = count < buf_len ? count : buf_len - 1;
  memcpy(buf, p + src, len);
  buf[len] = 0;
  size_t k = strlen(buf);
  while (k && buf[k - 1] == ' ') buf[--k] = 0;
  return k > 0;
}

int exif_pixel_dims(const uint8_t *p, size_t n, uint32_t *w, uint32_t *h) {
  tiff_t t;
  if (!tiff_open(&t, p, n)) return 0;
  uint32_t exif = exif_ifd_offset(&t);
  if (!exif) return 0;
  return entry_uint(&t, ifd_find(&t, exif, 0xA002), w) &&
         entry_uint(&t, ifd_find(&t, exif, 0xA003), h);
}

// A number in TIFF entry `e`: rational, signed rational, float or double,
// with offsets counted from `base` in the TIFF data. Returns 1 if read.
static int entry_number(const tiff_t *t, size_t e, size_t base, double *v) {
  if (!e || t32(t, e + 4) != 1) return 0;
  const uint16_t type = t16(t, e + 2);
  if (type == 11) {  // float, stored in the entry
    const uint32_t bits = t32(t, e + 8);
    float f;
    memcpy(&f, &bits, sizeof f);
    *v = f;
    return 1;
  }
  const size_t at = base + t32(t, e + 8);
  if (at < base || at > t->n || t->n - at < 8) return 0;
  if (type == 12) {  // double
    const uint64_t bits = t->le ? ((uint64_t)t32(t, at + 4) << 32 | t32(t, at)) : ((uint64_t)t32(t, at) << 32 | t32(t, at + 4));
    memcpy(v, &bits, sizeof *v);
    return 1;
  }
  const uint32_t n = t32(t, at), d = t32(t, at + 4);
  if ((type != 5 && type != 10) || d == 0) return 0;
  *v = (type == 10 ? (double)(int32_t)n : (double)n) / (type == 10 ? (double)(int32_t)d : (double)d);
  return 1;
}

int exif_apple_hdr(const uint8_t *p, size_t n, double *headroom, double *gain) {
  tiff_t t;
  if (!tiff_open(&t, p, n)) return 0;
  const size_t e = ifd_find(&t, exif_ifd_offset(&t), 0x927C);  // MakerNote
  if (!e || t16(&t, e + 2) != 7) return 0;
  const uint32_t size = t32(&t, e + 4), at = t32(&t, e + 8);
  if (size <= 4 || at > n || size > n - at) return 0;
  // "Apple iOS\0", version, byte order, then an IFD; offsets count from the
  // start of the maker note.
  const uint8_t *note = p + at;
  if (size < 16 || memcmp(note, "Apple iOS", 10) != 0 || (memcmp(note + 12, "MM", 2) != 0 && memcmp(note + 12, "II", 2) != 0)) {
    return 0;
  }
  tiff_t m = {(uint8_t *)note, size, note[12] == 'I'};
  const uint16_t count = t16(&m, 14);
  if (16 + (size_t)count * 12 > size) return 0;
  int found = 0;
  for (uint16_t i = 0; i < count; i++) {
    const size_t entry = 16 + (size_t)i * 12;
    const uint16_t tag = t16(&m, entry);
    if (tag == 33) found |= entry_number(&m, entry, 0, headroom);
    if (tag == 48) found |= entry_number(&m, entry, 0, gain) << 1;
  }
  return found == 3;
}

static int contains(const uint8_t *p, size_t n, const char *text) {
  const size_t k = strlen(text);
  for (size_t i = 0; n >= k && i <= n - k; i++) {
    if (p[i] == (uint8_t)text[0] && memcmp(p + i, text, k) == 0) return 1;
  }
  return 0;
}

int jpeg_has_gain_map(const uint8_t *p, size_t n) {
  // A second image (MPF) with gain map metadata: ISO 21496-1, Adobe's
  // (hdrgm) or Apple's
  int mpf = 0;  // an APP2 segment "MPF\0"
  for (size_t i = 0; !mpf && n >= 8 && i <= n - 8; i++) {
    mpf = p[i] == 0xFF && p[i + 1] == 0xE2 && memcmp(p + i + 4, "MPF", 4) == 0;
  }
  return mpf && (contains(p, n, "urn:iso:std:iso:ts:21496:-1") ||
                                    contains(p, n, "http://ns.adobe.com/hdr-gain-map/") ||
                                    contains(p, n, "HDRGainMapVersion"));
}

static int patch_uint(const tiff_t *t, size_t e, uint32_t v) {
  if (!e || t32(t, e + 4) != 1) return 0;
  uint16_t type = t16(t, e + 2);
  if (type == TIFF_SHORT && v <= 0xFFFF) {
    if (t16(t, e + 8) == v) return 0;
    w16(t, e + 8, (uint16_t)v);
    return 1;
  }
  if (type == TIFF_LONG) {
    if (t32(t, e + 8) == v) return 0;
    w32(t, e + 8, v);
    return 1;
  }
  return 0;
}

int exif_patch(uint8_t *p, size_t n, uint32_t w, uint32_t h) {
  tiff_t t;
  if (!tiff_open(&t, p, n)) return 0;
  int changed = patch_uint(&t, ifd_find(&t, t32(&t, 4), 0x0112), 1);
  uint32_t exif = exif_ifd_offset(&t);
  if (exif) {
    changed += patch_uint(&t, ifd_find(&t, exif, 0xA002), w);
    changed += patch_uint(&t, ifd_find(&t, exif, 0xA003), h);
  }
  return changed;
}
