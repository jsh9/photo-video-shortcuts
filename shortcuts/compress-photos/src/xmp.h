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
// XML) and resolve namespaces, so text that merely looks like a property is
// ignored; an undeclared conventional prefix ("tiff:", "xmpNote:") still counts.
int xmp_orientation(const uint8_t *xmp, size_t len);  // 1..8, 0 if absent
// 1 if the packet has an xmpNote:HasExtendedXMP reference, else 0.
int xmp_has_extended_reference(const uint8_t *xmp, size_t len);
// Replaces each TIFF orientation value other than 1 (e.g. "6" or "&#54;") with
// "1" in the malloc-owned packet; every other byte stays the same. Returns the
// number of values changed, or -1 if out of memory (the packet is unchanged).
int xmp_reset_orientation(uint8_t **xmp, size_t *len);

#ifdef __cplusplus
}
#endif
#endif
