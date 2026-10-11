// HEIF containers for HEIC output (heicout.h): reading a file's items,
// properties, references and locations; writing it back with some items
// dropped and the base picture's tiles replaced (hb_rewrite); and writing a
// new file around freshly encoded tiles (hb_write_new).
#ifndef JXLBATCH_HEIFBOX_H
#define JXLBATCH_HEIFBOX_H

#include <stddef.h>
#include <stdint.h>

#include "boxes.h"
#include "hevcenc.h"

#define HB_MAX_PROPS 32

typedef struct {
  uint32_t id;
  uint32_t type;   // 'hvc1', 'grid', 'tmap', 'Exif', 'mime', 'uri ', ...
  uint32_t flags;  // infe flags: 1 = hidden
  span_t infe;     // the whole 'infe' box, in the file
  uint32_t props[HB_MAX_PROPS];  // property indices (from 1), from 'ipma'
  uint8_t essential[HB_MAX_PROPS];
  size_t num_props;
  int located;  // has an 'iloc' entry
  int method;   // 0: file offsets, 1: offsets into 'idat'
  uint16_t dref;
  size_t first_extent, num_extents;  // into hb_file_t.extents
} hb_item_t;

typedef struct {
  uint64_t offset, length;
} hb_extent_t;

typedef struct {
  uint32_t type;  // 'dimg', 'thmb', 'auxl', 'cdsc', ...
  uint32_t from;
  uint32_t *to;
  size_t num_to;
} hb_ref_t;

typedef struct {
  uint32_t type;  // 'altr', ...
  uint32_t id;
  uint32_t *ids;
  size_t num_ids;
} hb_group_t;

typedef struct {
  const uint8_t *file;
  size_t file_len;
  span_t ftyp;      // the whole box
  uint8_t meta_vf[4];  // the 'meta' box's version and flags
  span_t *children;    // the 'meta' box's children, whole boxes, in order
  uint32_t *child_types;
  size_t num_children;
  uint32_t primary;
  hb_item_t *items;  // in 'iinf' order
  size_t num_items;
  hb_extent_t *extents;
  size_t num_extents;
  hb_ref_t *refs;
  size_t num_refs;
  span_t *ipco;  // the properties, whole boxes, from 1 (ipco[0] is property 1)
  size_t num_ipco;
  hb_group_t *groups;
  size_t num_groups;
  span_t idat;  // its payload
  int iloc_version, iref_version, ipma_version, ipma_flags;
  uint32_t *ipma_order;  // item ids in 'ipma' order
  size_t num_ipma;
} hb_file_t;

// Reads the file's structure (nothing is copied but the tables). Returns 0,
// or -1 with the reason in err (not a HEIF, or a feature this writer doesn't
// handle, such as data referenced by item offset).
int hb_parse(const uint8_t *buf, size_t len, hb_file_t *f, char *err, size_t err_len);
void hb_free(hb_file_t *f);

const hb_item_t *hb_item(const hb_file_t *f, uint32_t id);
// The ids item `from` references with `type`, or NULL; *n gets how many.
const uint32_t *hb_refs_from(const hb_file_t *f, uint32_t from, uint32_t type, size_t *n);
// 1 if item `from` references `to` with `type`.
int hb_has_ref(const hb_file_t *f, uint32_t from, uint32_t type, uint32_t to);
// Property `index` (from 1): its type and payload. Returns 0 if there is none.
int hb_property(const hb_file_t *f, uint32_t index, uint32_t *type, span_t *payload);
// The index of the item's first property of `type`, 0 if none.
uint32_t hb_item_property(const hb_file_t *f, uint32_t id, uint32_t type);
// A copy of the item's data (its extents concatenated), or NULL.
uint8_t *hb_item_data(const hb_file_t *f, uint32_t id, size_t *len);

// New data for an item that is kept.
typedef struct {
  uint32_t id;
  const uint8_t *data;
  size_t len;
} hb_replace_t;

typedef struct {
  const uint32_t *keep;  // the items to keep; every other item goes
  size_t num_keep;
  const hb_replace_t *replace;
  size_t num_replace;
  uint32_t hvcc_index;  // property to replace with `hvcc` (0: none)
  const uint8_t *hvcc;  // the new 'hvcC' payload
  size_t hvcc_len;
} hb_rewrite_t;

// Writes the file again: 'ftyp' as it was; 'meta' with the kept items only
// ('iinf', 'iref', 'ipma', 'grpl' filtered, 'iloc' regenerated, the property
// replaced, everything else byte for byte); 'mdat' with the kept items' data
// in the original order, replaced data where given. malloc'ed. Returns 0, or
// -1 if out of memory.
int hb_rewrite(const hb_file_t *f, const hb_rewrite_t *rw, uint8_t **out, size_t *out_len);

// A new HEIC: one picture as a grid of HEVC tiles (a single 'hvc1' item when
// the one tile is the picture), with an ICC profile or an nclx color, and
// an Exif item when given.
typedef struct {
  uint32_t w, h;
  uint32_t tile_w, tile_h, rows, cols;
  const hevc_buf_t *tiles;  // rows x cols pictures, row by row
  const uint8_t *hvcc;      // the 'hvcC' payload they share
  size_t hvcc_len;
  const uint8_t *icc;  // NULL: `nclx` is written instead
  size_t icc_len;
  hevc_vui_t nclx;
  const uint8_t *exif;  // TIFF data, or NULL
  size_t exif_len;
} hb_new_t;

int hb_write_new(const hb_new_t *n, uint8_t **out, size_t *out_len);

#endif
