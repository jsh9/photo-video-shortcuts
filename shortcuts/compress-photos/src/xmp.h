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

// What the packet has for Photos' title, caption and keywords, read in one
// pass: dc:title and dc:description (each its x-default item, else its first;
// a qualified item's rdf:value), and dc:subject's items (keywords; the empty
// ones left out). Each field's state: 0 the packet doesn't have the property,
// 1 it has one (its text in title or description, NULL when empty; the
// keywords in subject, num_subject of them), 2 it has one whose value isn't
// readable as text (an array item holding elements but no rdf:value, a
// structure of fields: never Photos' value), or more than one that don't
// agree (a title or caption repeated with the same text counts as one; a
// repeated dc:subject never does). References are decoded, surrounding
// whitespace left out. Returns 0, or -1 if out of memory (nothing is held
// then); xmp_dc_free frees what it holds.
typedef struct {
  int title_state, description_state, subject_state;
  char *title, *description;
  char **subject;
  size_t num_subject;
} xmp_dc_t;
int xmp_dc_read(const uint8_t *xmp, size_t len, xmp_dc_t *dc);
void xmp_dc_free(xmp_dc_t *dc);
// The properties xmp_set_dc replaces.
enum { XMP_DC_TITLE = 1, XMP_DC_DESCRIPTION = 2, XMP_DC_SUBJECT = 4 };
// Replaces dc:title, dc:description and dc:subject, each when its flag is in
// `which`, in the malloc-owned packet: the packet's own are removed, wherever
// they are and however written (qualifiers too), and the given values that
// aren't empty (`title`, `description`, the `num_subject` strings of
// `subject`) are added in a new rdf:Description at the end of rdf:RDF (an
// empty rdf:RDF written as one tag gets an end tag), as a language
// alternative (x-default) or a bag; every other byte stays. Returns the number
// of changes (0: none), -1 if out of memory, -2 if a value must be added but
// the packet has no rdf:RDF to add it to (the packet is unchanged then).
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
