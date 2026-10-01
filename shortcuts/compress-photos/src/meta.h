// Metadata extraction (EXIF, XMP, ICC) from HEIF, JPEG and PNG files, plus
// in-place helpers for the EXIF/XMP orientation and pixel-dimension tags.
#ifndef JXLBATCH_META_H
#define JXLBATCH_META_H

#include <stddef.h>
#include <stdint.h>

typedef struct {
  uint8_t *data;
  size_t size;
} blob_t;

typedef enum { FMT_UNKNOWN = 0, FMT_HEIF, FMT_JPEG, FMT_PNG } file_format_t;

typedef struct {
  file_format_t format;
  blob_t exif;           // raw TIFF structure, starts with "II*\0" or "MM\0*"
  blob_t xmp;            // XMP packet
  blob_t icc;            // ICC profile (PNG iCCP chunk or JPEG APP2 segments)
  int png_srgb;          // PNG has an sRGB chunk
  int png_cicp_present;  // PNG has a cICP chunk
  uint8_t png_cicp[4];   // primaries, transfer, matrix, full-range flag
} meta_t;

file_format_t detect_format(const uint8_t *buf, size_t len);
const char *format_name(file_format_t format);

// Fills `m` with whatever metadata the file contains. Never fails on missing
// metadata; returns -1 only on allocation failure.
int meta_extract(const uint8_t *buf, size_t len, meta_t *m);
void meta_free(meta_t *m);

// EXIF helpers; `tiff` points at the TIFF header.
int exif_orientation(const uint8_t *tiff, size_t len);  // 1..8, 0 if absent
int exif_pixel_dims(const uint8_t *tiff, size_t len, uint32_t *w, uint32_t *h);
// Copies an IFD0 text tag (e.g. 0x010F Make) into buf. Returns 1 if found.
int exif_string(const uint8_t *tiff, size_t len, uint16_t tag, char *buf, size_t buf_len);
// Sets Orientation to 1 and PixelXDimension/PixelYDimension to w/h, for the
// tags that exist. Returns the number of tags changed.
int exif_patch(uint8_t *tiff, size_t len, uint32_t w, uint32_t h);

int xmp_orientation(const uint8_t *xmp, size_t len);  // 1..8, 0 if absent
int xmp_reset_orientation(uint8_t *xmp, size_t len);  // 1 if changed

#endif
