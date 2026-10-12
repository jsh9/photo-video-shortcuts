# Tools

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. `photo-compare.html`](#1-photo-comparehtml)

______________________________________________________________________

<!--TOC-->

Small helpers that aren't part of any shortcut.

## 1. `photo-compare.html`

A viewer for comparing two photos pixel for pixel, in one file. Open it in
Safari, which decodes HEIC, AVIF and JPEG XL itself (an iPhone HEIC's tiles
assembled, with Apple's own decoder), and drop files on it or use *Add
photos…*. Nothing leaves the browser.

- Mark one file **A** and one **B**; **×** closes a file you are done with.
  Scroll or pinch to zoom around the cursor, drag to pan; both follow one view.
  Magnified pixels are drawn as squares, never smoothed, so block edges show as
  what they are.
- Modes: side by side, a wipe line to drag, flicker (space bar flips A and B in
  place, the most sensitive comparison for small differences), and an amplified
  difference, |A − B| × 8 by default (`[` and `]` change it).
- The bottom line shows the zoom, the pixel under the cursor and its color
  values in A and B.
- Keys: space flicker · 1 / 2 show A / B · s, w, d modes · f fit · 0 one image
  pixel per screen pixel · + / − zoom · arrows pan.
- `photo-compare.html?a=URL&b=URL` loads two files served next to the page (for
  scripts; a `file://` page can't fetch).

It shows the SDR picture of a gain-map HEIC and Safari's own rendering of a PQ
file. For the HDR view, use Photos.
