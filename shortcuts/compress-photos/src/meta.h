// Metadata extraction (EXIF, XMP, ICC) from HEIF, JPEG and PNG files, plus
// in-place helpers for the EXIF/XMP orientation and pixel-dimension tags, and
// setting the EXIF capture date, GPS position and caption.
#ifndef JXLBATCH_META_H
#define JXLBATCH_META_H

#include <stddef.h>
#include <stdint.h>
#include "xmp.h"

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
// metadata; returns -1 with a descriptive error if it cannot be preserved.
int meta_extract(const uint8_t *buf, size_t len, meta_t *m, char *err, size_t err_len);
void meta_free(meta_t *m);

// The ICC profile of HEIF item `id` (its 'colr' property of type 'prof' or
// 'rICC'), pointing into buf; returns its size, 0 if it has none. libheif
// gives the profiles of images only, not of other items such as 'tmap'.
size_t heif_item_profile(const uint8_t *buf, size_t len, uint32_t id, const uint8_t **icc);
// 1 if HEIF item `id` is an auxiliary image of type `aux_type` (its 'auxC').
int heif_item_has_aux_type(const uint8_t *buf, size_t len, uint32_t id, const char *aux_type);
// The CICP color primaries in HEIF item `id`'s 'colr' property of type
// 'nclx'; 0 if it has none.
int heif_item_nclx_primaries(const uint8_t *buf, size_t len, uint32_t id);
// 1 if a JPEG holds a gain map (an HDR photo): a second image (MPF) with
// gain map metadata.
int jpeg_has_gain_map(const uint8_t *buf, size_t len);

// EXIF helpers; `tiff` points at the TIFF header.
int exif_orientation(const uint8_t *tiff, size_t len);  // 1..8, 0 if absent
int exif_pixel_dims(const uint8_t *tiff, size_t len, uint32_t *w, uint32_t *h);
// Copies an IFD0 text tag (e.g. 0x010F Make) into buf. Returns 1 if found.
// Apple's maker note tags 33 and 48 (Apple calls them HDRHeadroom and
// HDRGain): the headroom of Apple's older gain maps. Returns 1 if both found.
int exif_apple_hdr(const uint8_t *tiff, size_t len, double *headroom, double *gain);
int exif_string(const uint8_t *tiff, size_t len, uint16_t tag, char *buf, size_t buf_len);
// Sets Orientation to 1 and PixelXDimension/PixelYDimension to w/h, for the
// tags that exist. Returns the number of tags changed.
int exif_patch(uint8_t *tiff, size_t len, uint32_t w, uint32_t h);

// A photo's date as the shortcut gives it (Photos' date): the wall time where
// the photo is shown, and that place's offset from UTC on that date.
typedef struct {
  int year, month, day, hour, minute, second;
  int millis;  // 0-999, or -1 when not given
  int offset;  // minutes east of UTC (-05:00 is -300)
} photo_date_t;

// Parses "2024-01-01T17:00:00-05:00": a space may replace the T, the date's
// parts may be separated by ":" as in EXIF, fractions of a second may follow
// the seconds (".123"), and the offset may be "-0500", "-05" or "Z". Returns
// 1 if valid.
int photo_date_parse(const char *s, photo_date_t *d);
// Writes the date as EXIF does, "2024:01:01 17:00:00 -05:00", or for XMP,
// "2024-01-01T17:00:00.123-05:00" (with the fraction when it has one).
void photo_date_exif_text(const photo_date_t *d, char *buf, size_t buf_len);
void photo_date_iso_text(const photo_date_t *d, char *buf, size_t buf_len);

// Makes `date` the EXIF's capture date. When DateTimeOriginal already is that
// moment (to the second, by its OffsetTimeOriginal, OffsetTimeDigitized or
// OffsetTime if it has one, else by the clock time), nothing changes and 0 is
// returned. Otherwise *out gets a new, malloc'ed TIFF structure (from `tiff`,
// or from scratch when len is 0) with DateTimeOriginal and CreateDate set to
// the date, OffsetTimeOriginal and OffsetTimeDigitized to its offset, and
// SubSecTimeOriginal and SubSecTimeDigitized to its milliseconds (removed
// when it has none); the modification time (DateTime, OffsetTime, SubSecTime)
// stays. The Exif IFD is rewritten at the end of the data, so no other value
// moves (maker notes keep their offsets). Returns 1 then.
// A file without a time zone whose clock time is `date`'s moment in some zone
// (whole quarter hours, up to 14 h from UTC) keeps that clock time and gets
// that zone: *date becomes what was written, and 2 is returned.
// `was` gets the file's own date for a log ("" if none).
// Returns -1 if out of memory, -2 if the EXIF can't be read (or its Exif IFD
// can't be followed from IFD0; the EXIF is then kept as it is).
int exif_set_capture_date(const uint8_t *tiff, size_t len, photo_date_t *date, uint8_t **out, size_t *out_len,
                          char *was, size_t was_len);

// A photo's location as the shortcut gives it (Photos' location): degrees,
// north and east positive, and the altitude in meters when has_alt.
typedef struct {
  double lat, lon, alt;
  int has_alt;
} photo_location_t;

// Parses "lat,lon" or "lat,lon,alt": decimal numbers with "." as the decimal
// point, an exponent allowed ("5e-05", as Shortcuts writes small values).
// An altitude of exactly 0 is none: Photos gives 0 for a place typed in its
// Info window, and a measured altitude is never exactly 0. Returns 1 if valid
// (latitude within ±90, longitude within ±180).
int photo_location_parse(const char *s, photo_location_t *loc);
// The EXIF's GPS position (GPSLatitude and GPSLongitude with their refs) in
// *loc; its altitude isn't read (has_alt is 0), as photo_location_same
// doesn't compare it. Returns 1 if it has one.
int exif_gps(const uint8_t *tiff, size_t len, photo_location_t *loc);
// 1 if two positions are the same place: within 0.00001° (about 1 m) in both
// coordinates. Photos gives reals, EXIF stores rationals (an iPhone writes
// seconds to 0.01", about 0.3 m).
int photo_location_same(const photo_location_t *a, const photo_location_t *b);
// Makes `loc` the EXIF's GPS position, or removes the position (loc NULL).
// *out gets a new, malloc'ed TIFF structure (from `tiff`, or from scratch when
// len is 0) whose GPS IFD has only GPSVersionID, the latitude and longitude
// with their refs, and the altitude when loc has one: the file's direction,
// speed, positioning error and fix time belong to its old position. The GPS
// IFD is written at the end of the data and IFD0's pointer moved to it (IFD0
// is rewritten when it has no pointer, or without it for a removal), so no
// other value moves. The old GPS IFD and the values it points to are zeroed,
// and so is IFD0's old table when IFD0 is rewritten, so the old position
// isn't left in the data (but the bytes another IFD's entry still refers to,
// in a file that shares values, or parts of them, or points IFDs into one
// another). Returns 1, or 0 when removing from an EXIF without a position; -1
// if out of memory, -2 if the EXIF can't be read (it is then kept as it is).
int exif_set_gps(const uint8_t *tiff, size_t len, const photo_location_t *loc, uint8_t **out, size_t *out_len);
// IFD0's ImageDescription (the caption EXIF readers show; ASCII, or BYTE or
// UNDEFINED as some writers store UTF-8), without trailing spaces and NULs,
// malloc'ed in *text: "" when it is blank (ImageIO still takes it over the
// XMP's caption). Returns 1 when the EXIF has one, 0 when not (*text NULL),
// -1 if out of memory.
int exif_description(const uint8_t *tiff, size_t len, char **text);
// Sets IFD0's ImageDescription to `text` (UTF-8), or removes it when `text`
// is NULL or empty; only an EXIF that has one is changed (0 is returned
// otherwise). The new value is written at the end of the data, the old one
// zeroed (but the bytes another entry shares); a removal rewrites IFD0 at
// the end and zeroes the old entry's value and the old table, a short value
// held in it included. Returns 1 when *out got a new, malloc'ed TIFF
// structure, -1 if out of memory, -2 if the EXIF can't be read.
int exif_set_description(const uint8_t *tiff, size_t len, const char *text, uint8_t **out, size_t *out_len);

#endif
