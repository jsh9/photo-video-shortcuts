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
int xmp_orientation(const uint8_t *xmp, size_t len);  // 1..8, 0 if absent
// Replaces the malloc-owned packet only when orientation changes. Returns -1
// on invalid XML/allocation failure; leaves the original buffer intact then.
int xmp_reset_orientation(uint8_t **xmp, size_t *len, char *err, size_t err_len);

#ifdef __cplusplus
}
#endif
#endif
