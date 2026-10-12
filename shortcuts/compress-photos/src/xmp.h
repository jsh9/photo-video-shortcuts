// XML operations shared by JPEG metadata extraction and orientation handling.
#ifndef JXLBATCH_XMP_H
#define JXLBATCH_XMP_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Returns 1 for a reference, 0 when absent, -1 for invalid XML/reference.
int xmp_extended_guid(const uint8_t *xmp, size_t len, char guid[33], char *err, size_t err_len);
int xmp_merge_extended(const uint8_t *base, size_t base_len, const uint8_t *extended,
                       size_t extended_len, uint8_t **out, size_t *out_len,
                       char *err, size_t err_len);
// The functions below scan the packet's bytes tolerantly (it need not be strict
// XML) for top-level properties and resolve namespaces, so text that merely
// looks like a property, or a field of a structure, is ignored; an undeclared
// conventional prefix ("tiff:", "xmpNote:") still counts.
int xmp_orientation(const uint8_t *xmp, size_t len);  // 1..8, 0 if absent
// 1 if the packet has an xmpNote:HasExtendedXMP reference, else 0.
int xmp_has_extended_reference(const uint8_t *xmp, size_t len);
// Replaces the digit of each TIFF orientation other than 1 (e.g. "6", "&#54;",
// or the 6 in "<![CDATA[6]]>") with "1" in the malloc-owned packet; every other
// byte stays the same. Returns the number of values changed, or -1 if out of
// memory (the packet is unchanged).
int xmp_reset_orientation(uint8_t **xmp, size_t *len);
// Replaces the value of each capture date the packet has (xmp:CreateDate,
// photoshop:DateCreated, exif:DateTimeOriginal, exif:DateTimeDigitized) with
// `date` (ISO 8601) in the malloc-owned packet; none is added, and a value
// written in pieces (split by a comment or CDATA) stays. Returns the number
// of values replaced, or -1 if out of memory (the packet is unchanged).
int xmp_set_dates(uint8_t **xmp, size_t *len, const char *date);

#ifdef __cplusplus
}
#endif
#endif
