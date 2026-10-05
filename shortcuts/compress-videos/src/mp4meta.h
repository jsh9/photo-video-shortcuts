// Copies a video's metadata from the original into a converted MP4/MOV.
#ifndef VIDBATCH_MP4META_H
#define VIDBATCH_MP4META_H

#include <stddef.h>
#include <stdint.h>

// Copies, byte for byte, the original's movie-level `meta`/`udta` boxes
// (Apple's keys: creation date, location, make, model, software...) and its
// video track's `meta`/`udta` boxes (lens model, focal length, f-number...)
// into `converted`, replacing the converted file's own boxes at those places,
// and sets the movie and track creation/modification times from the
// original's `mvhd`. `converted` must end with its `moov` box.
// Returns the number of boxes copied, or -1 with a message in err.
int mp4meta_copy(const char *original, const char *converted, char *err, size_t err_len);

// Adds a box (for example a `meta` box) to the end of the file's `moov`, which
// must be the last box in the file. Used by the self-test. Returns 0 or -1.
int mp4meta_append(const char *path, const uint8_t *box, size_t len, char *err, size_t err_len);

#endif
