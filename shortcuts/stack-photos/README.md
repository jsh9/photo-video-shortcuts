# Stack Photos

**Stack Photos** puts photos side by side (horizontal) or one above the other
(vertical) and saves the result to Photos as one new photo, dated 5 seconds
after the latest of them, so it sorts right after them. Each photo can first be
fitted to one aspect ratio, with white borders or by cutting off its sides. The
originals are left as they are.

It is one shortcut for iPhone and Mac, made of Shortcuts' own actions: no
a-Shell, no Terminal. On the Mac it asks Photos for the photos you selected
with a short AppleScript, so Shortcuts must be allowed to run scripts there.

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Install (once)](#1-install-once)
- [2. Use](#2-use)
  - [2.1. The questions](#21-the-questions)
  - [2.2. What happens](#22-what-happens)
- [3. Troubleshooting](#3-troubleshooting)
- [4. Updating](#4-updating)

______________________________________________________________________

<!--TOC-->

## 1. Install (once)

1. **Add the shortcut.** From the latest
   [release](https://github.com/jsh9/photo-video-shortcuts/releases) download
   `stack-photos-shortcuts-v<version>.zip` (the same file for iPhone and Mac),
   unzip it, and open *Stack Photos* → Add Shortcut. With iCloud sync on for
   Shortcuts, it then shows up on your other devices too.
2. **Mac only: allow scripts.** Shortcuts ▸ Settings ▸ Advanced ▸ **Allow
   Running Scripts** (already on if you use Compress Photos or Compress Videos
   on the Mac). Photos' Share menu gives a shortcut no photos on the Mac, so
   the shortcut asks Photos for its selection with AppleScript.
3. **Grant permissions.** Run it once with two photos and allow it to access
   Photos when asked. On the Mac, the first time you run it from Photos, macOS
   asks whether Shortcuts may control Photos: choose Allow.

## 2. Use

- **iPhone:** in Photos, select the photos, tap Share ▸ *Stack Photos*. Or run
  it from the Shortcuts app and pick the photos in its photo picker.
- **Mac:** in Photos, select the photos, then Share ▸ *Stack Photos* (or
  right-click ▸ Share). Photos exports them as it shows them (with your edits)
  for the shortcut; there is no picker. Run from the Shortcuts app or the menu
  bar while Photos has no selection in front, it shows its photo picker. In
  Finder, select image files, right-click ▸ Quick Actions ▸ *Stack Photos*.

The photos are stacked in the order the shortcut gets them: the order you
selected them in Photos on the Mac, or picked them in the picker; from the
iPhone's share sheet, the order Photos passes them. Videos are skipped (the
notification says how many); a Live Photo is stacked as its still photo.

### 2.1. The questions

1. **Stack the photos:** *Horizontal: side by side* or *Vertical: one above the
   other*.

2. **Aspect ratio of each photo** (width:height). Horizontal stacks offer tall
   shapes, vertical stacks wide ones:

   | Horizontal | Vertical |
   | ---------- | -------- |
   | 3:4        | 4:3      |
   | 2:3        | 3:2      |
   | 9:16       | 16:9     |
   | 4:5        | 5:4      |

   or *Keep each photo as it is*.

3. **Fit each photo to** the ratio (not asked when photos keep their shape):

   - *Pad: add white borders*: the whole photo is kept, with white borders on
     two opposite sides (left and right, or top and bottom) where it is too
     narrow or too wide for the ratio.
   - *Crop: cut the sides, keep the center*: the photo is cut to the ratio
     around its center, on two opposite sides only: left and right, or top and
     bottom, never all four.

4. **Height of the photos** (horizontal) or **Width of the photos** (vertical):

   - *the smallest photo's*: no photo is enlarged (see Sizes below).
   - *type it in pixels*: you type the number, with the smallest photo's filled
     in. A larger number enlarges the photos to it; with an aspect ratio, the
     other side follows the ratio (rounded to a whole pixel).

5. **Gap between the photos**: *No gap*, or 2%, 5%, 10% or 15% of a photo's
   width (horizontal) or height (vertical); with *Keep*, of the narrowest
   (shortest) photo's. The gap is white, at least a pixel, and as high (wide)
   as the photos.

### 2.2. What happens

- **Sizes.** In a horizontal stack every photo gets the height of the smallest
  (or the height you typed), in a vertical stack its width: with the smallest,
  no photo is enlarged. With an aspect ratio, all photos come out the same
  size, at exactly that ratio: the largest whole multiple of it that no photo
  has to be enlarged for (for 3:4, 3 × 1008 by 4 × 1008 = 3024 × 4032, say; a
  photo may lose a few pixels so that the ratio is exact). With *Keep*, each
  photo keeps its own shape.
- **The new photo** is a JPEG at quality 0.9, saved to Recents and named after
  the first photo with `-stack` (`IMG_1234-stack.jpg`). The photos go through
  lossless PNG until then, so this is their only new compression.
- **Its date** is the latest date among the photos, as Photos shows it, plus 5
  seconds, in your device's time zone. (On the Mac, a date in the hour that
  repeats when daylight saving time ends is read as the first of the two.) If
  no photo has a date (an image from a file without one), it is the time you
  run the shortcut.
- **Not carried over:** location, camera, titles, captions, keywords and
  albums. HDR and wide color (Display P3) aren't kept: Shortcuts' Combine
  Images draws in 8-bit sRGB.

A notification says how many photos were stacked and the stack's size.

## 3. Troubleshooting

- **Mac: "Running scripts is not allowed"** or similar: turn on Allow Running
  Scripts (Install, step 2).

- **Mac: "ERROR: Photos could not be asked..."**: allow Shortcuts to control
  Photos in System Settings ▸ Privacy & Security ▸ Automation.

- **It stops from the share sheet with a memory error.** iOS gives shortcuts
  run from the share sheet less memory than the Shortcuts app. Run it from the
  Shortcuts app and pick the photos there, or stack fewer photos at a time.

- **"It has no date"** in the notification: the stack was saved, but its date
  couldn't be written (Shortcuts' date text wasn't the expected one), so Photos
  dates it at the time you ran the shortcut. Please report it with your
  device's language and region.

## 4. Updating

The shortcut's version is in the note at its top. When a release says Stack
Photos changed, download the new ZIP and add the shortcut again (replace the
old one when asked).
