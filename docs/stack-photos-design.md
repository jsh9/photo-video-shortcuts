# Stack Photos: design

The decisions behind Stack Photos 0.1.0 (October 2026) and the evidence for
each: how the shortcut works is in
[its developer notes](../shortcuts/stack-photos/DEVELOPING.md).

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. The request](#1-the-request)
- [2. Decisions](#2-decisions)
- [3. Writing the date](#3-writing-the-date)
- [4. Checking without a device](#4-checking-without-a-device)
- [5. To check on a device](#5-to-check-on-a-device)

______________________________________________________________________

<!--TOC-->

## 1. The request

Stack the selected photos horizontally or vertically; optionally fit each to
one aspect ratio (horizontal: 3:4, 2:3, 9:16, 4:5; vertical: 4:3, 3:2, 16:9,
5:4) by padding or by a centered crop of two opposite sides only; resize so
that all have the smallest height (horizontal) or width (vertical); save to
Photos dated 5 seconds after the latest photo. Without a-Shell or Terminal, and
on iPhone and Mac alike: if either was impossible, stop and say so. Neither
was, but the Mac needed scripts for one thing (2, the Mac route).

## 2. Decisions

- **Shortcuts' own actions**, one shortcut for both platforms: Get Details of
  Images, Convert, Resize, Crop, Overlay and Combine Images, Calculate,
  Calculate Statistics, Round Number, the date actions, Base64 Encode, Replace
  Text, Save to Photo Album.
- **The Mac route (decided with the user, 2026-10-22).** The first version,
  script-free, showed the picker when run from Photos' Share menu on the Mac,
  and the user rejected that: no picker. Photos' Share menu hands a shortcut
  nothing it can read on the Mac (Compress Photos' spike S5, and the unified
  log of the user's run on macOS 27: input passed, Shortcut Input empty), so
  the only way to Photos' selection is AppleScript. Offered one shortcut with a
  Mac-only branch, a separate Mac shortcut, or no scripts (no Share menu on the
  Mac), the user chose one shortcut. The branch (Run AppleScript and Run Shell
  Script) runs only when Get Device Details says "Mac"; it needs Allow Running
  Scripts on the Mac. With no selection in Photos (run from the Shortcuts app),
  the Mac still shows the picker.
- **A fourth ratio choice, *Keep each photo as it is*,** stacks the photos with
  their own shapes, resized only.
- **Pad color: white**, the usual border for stacked photos. A 1x1 white PNG,
  stretched.
- **Exact ratios.** Every tile is K·A × K·B with K whole, the largest that
  enlarges no photo; with one size for all, equal heights and equal widths are
  the same. A photo may lose up to A−1 or B−1 pixels to that.
- **Lossless until the end.** Resize, Crop and Overlay re-encode in the input's
  type (HEIC, at ImageIO's default quality), and Combine writes JPEG at 0.75
  unless most inputs are PNG. So each photo becomes a PNG first and the stack
  is encoded once, as JPEG at 0.9.
- **JPEG, not HEIC**, because the date is written into the file's bytes (3),
  which is simple in a JPEG. Compress Photos can turn the stack into HEIC or
  JPEG XL afterwards, with its date.
- **The date in the device's time zone**, as Format Date gives it, with its
  offset in the OffsetTime tags: the same moment as the latest photo plus 5 s.
- **Order**: the order the shortcut receives the photos; no sorting.
- **Name**: the first photo's, with `-stack`.
- **Videos are skipped**; a Live Photo is an image to Shortcuts and is stacked
  as its still.

## 3. Writing the date

Save to Photo Album (`WFSaveToCameraRollAction`) calls
`creationRequestForAssetFromImageAtFileURL` and sets no `creationDate`, so
Photos takes the date from the file. Photos' App Intents
(`PhotosUICore.framework/.../extract.actionsdata`, macOS 27) offer no date
either: Update Asset sets a name, favorite and hidden only. And no built-in
action writes metadata (the action identifiers in the Mac's frameworks have
none). So the shortcut writes the EXIF itself: Base64 Encode of the JPEG,
Replace Text of its start with a prefix built from constant base64 pieces and
the date's and offset's own base64, Base64 Decode. The layout that makes this
work is in the developer notes (1.2).

Checked on the Mac:

- ImageIO's JPEG from Combine and Convert Image (as their decompiled code calls
  it) starts `/9j/4AAQSkZJRgABAQAASABIAAD/4QBM`: SOI, JFIF at 72 dpi, and a
  76-byte Exif segment (ColorSpace, PixelX/YDimension).
- After the splice, ImageIO reads DateTimeOriginal, DateTimeDigitized and
  OffsetTimeOriginal, the decoded pixels are identical, and exiftool reads
  every tag with no error. Its `-validate` warns of tags missing that ImageIO's
  own JPEG lacks too (ComponentsConfiguration, YCbCrPositioning), of
  ExifImageWidth and ExifImageHeight (ImageIO's segment had them; they are the
  stack's size, numbers the shortcut can't write as text), and of the unknown
  APP15 segment.
- Base64 Decode's file is typed from its bytes (`public.jpeg`, `public.png`)
  before Set Name, and the renamed file is an image
  (`WFContentItem itemWithFile:`).
- Format Date's ISO 8601 is en_US_POSIX `yyyy-MM-dd'T'HH:mm:ssZZZZZ` (Compress
  Photos 0.7.0's reading of ContentKit), so the date text is ASCII in every
  region.

## 4. Checking without a device

ActionKit, which holds the actions, won't load outside Apple's own processes
(`WFActionKitStaticInitializer` asserts a platform binary), and importing a
shortcut on the Mac takes a click. So:

- The decompiled actions (iOS 18.2: ActionKit, ContentKit, WorkflowKit;
  [EthanArbuckle/iPhone17-1_18.2_22C152_Restore](https://github.com/EthanArbuckle/iPhone17-1_18.2_22C152_Restore))
  gave each action's parameters and behavior.
- On the Mac, ContentKit and WorkflowKit load in a test program: their
  functions `WFImageSizeFromMetadata`, `WFImageSizeFromFile`,
  `WFAsyncTransformedImageFromImage` (Resize's drawing),
  `generateImageFileForType:` (Convert Image) ran on real files, and every
  parameter of the generated shortcut parsed with WorkflowKit's parameter
  states (`WFNumberSubstitutableState`, `WFVariableStringParameterState`,
  `WFQuantityParameterState`, `WFVariableParameterState`,
  `WFVariableConditionalSubjectState`) with each variable resolved. That caught
  Adjust Date's duration: its magnitude is the variable's bare dictionary; a
  wrapped one reads as "Unknown Variable".
- Shortcuts built on devices (public shortcut files) showed how number fields
  store variables and constants, and Combine Images' current mode names.
- `tests/stack-photos/` runs the whole shortcut on a model of these actions.

The first run on the Mac (2026-10-22, traced in the unified log: each action's
"finished with output of N items") found what none of this could: Calculate
Statistics' input is stored as `Input` (as Count's), not `WFInput`. Shortcuts
ignores a key it doesn't know, so the action got nothing, every size after it
was empty, Combine Images gave nothing, and nothing was saved, with no error.
WorkflowKit's parameter states parse values, not key names. So
`test_shortcuts.py` now checks each action's input key and form against
shortcuts built on a device (Get Time Between Dates' input is a text field
there too), and the shortcut stops with a message when Combine Images gives
nothing rather than report a stack.

## 5. To check on a device

- The Mac route from Photos' Share menu: no picker; Photos' export of each
  selected item (the AppleScript compiles against Photos' dictionary, but
  Photos couldn't be scripted from the session, error -1743), the order, and
  the date Photos shows for the stack.

- A stack from the iPhone's share sheet and from the picker, on the iPhone and
  the Mac: the questions, the sizes, the white borders and the crops, and the
  date and time Photos shows for the stack (5 s after the latest photo).

- How large a stack the share sheet can make before iOS's memory limit.

- That Convert Image's JPEG starts as on the Mac (else the fallback writes the
  date after SOI, which works too, with ImageIO's segment kept).

- The order in which Photos' share sheet passes the selected photos.
