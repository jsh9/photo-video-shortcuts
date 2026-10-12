// XML operations shared by JPEG metadata extraction, orientation handling and
// the metadata from Photos (dates, title, caption, keywords, location).
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

// The packet's dc:title or dc:description (`local`: "title" or
// "description"): its x-default item, else its first, references decoded,
// without surrounding whitespace; malloc'ed in *text, NULL when it has none
// or it is empty. Returns 0, or -1 if out of memory.
int xmp_dc_text(const uint8_t *xmp, size_t len, const char *local, char **text);
// The packet's dc:subject items (keywords), the empty ones left out: a
// malloc'ed array of malloc'ed strings in *items, *count of them (NULL and 0
// when it has none). Returns 0, or -1 if out of memory.
int xmp_dc_subject(const uint8_t *xmp, size_t len, char ***items, size_t *count);
// The properties xmp_set_dc replaces.
enum { XMP_DC_TITLE = 1, XMP_DC_DESCRIPTION = 2, XMP_DC_SUBJECT = 4 };
// Replaces dc:title, dc:description and dc:subject, each when its flag is in
// `which`, in the malloc-owned packet: the packet's own are removed, wherever
// they are, and the given values that aren't empty (`title`, `description`,
// the `num_subject` strings of `subject`) are added in a new rdf:Description
// at the end of rdf:RDF, as a language alternative (x-default) or a bag; every
// other byte stays. Returns the number of changes (0: none), -1 if out of
// memory, -2 if a value must be added but the packet has no rdf:RDF to add it
// to (the packet is unchanged then).
int xmp_set_dc(uint8_t **xmp, size_t *len, unsigned which, const char *title, const char *description,
               const char *const *subject, size_t num_subject);
// Removes what tells where the photo was taken from the malloc-owned packet:
// the EXIF schema's GPS properties (exif:GPSLatitude, ...) and place names
// (photoshop:City, State, Country; Iptc4xmpCore:Location, CountryCode;
// Iptc4xmpExt:LocationCreated, LocationShown). Returns the number removed, or
// -1 if out of memory (the packet is unchanged).
int xmp_remove_location(uint8_t **xmp, size_t *len);
// A new, minimal packet (an empty rdf:RDF), malloc'ed. Returns 0, or -1 if
// out of memory.
int xmp_new_packet(uint8_t **xmp, size_t *len);

#ifdef __cplusplus
}
#endif
#endif
