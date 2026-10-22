#!/usr/bin/env python3
"""
Generates the shortcut "Stack Photos" as a signed .shortcut file.

One shortcut for iPhone and Mac, made of Shortcuts' own actions only: no
a-Shell, no scripts. It puts photos side by side (Horizontal) or one above the
other (Vertical). Each photo is first fitted to one aspect ratio (padded with
white, or cropped around its center), or kept as it is; then all are resized to
the height (Horizontal) or the width (Vertical) of the smallest, and combined.
The stack is saved to Photos as a JPEG dated 5 seconds after the latest photo.
No action sets a date, so the shortcut writes it into the JPEG's EXIF itself,
as base64 text (exif_segment, prefix_pieces; see ../DEVELOPING.md).

The generic builder (text and variable encoding, built-in actions, writing and
signing the file) is lib/wfkit.py, shared with the other shortcuts.

Usage::

    build_shortcuts.py[--no - sign]
"""

import argparse
import base64
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
sys.path.insert(0, str(HERE.parents[2] / 'lib'))

import wfkit  # noqa: E402
from wfkit import (  # noqa: E402
    REPEAT_ITEM,
    SHORTCUT_INPUT,
    Sample,
    output_of,
    text,
    variable,
    workflow,
)

NAME = 'Stack Photos'
VERSION = (TOOL / 'VERSION').read_text(encoding='utf-8').strip()
HELP_URL = 'https://github.com/jsh9/photo-video-shortcuts/blob/main/shortcuts/stack-photos/README.md'
DIST = TOOL / 'dist'
OUT = TOOL / 'build' / 'shortcuts'

# The questions. Each direction offers aspect ratios (width:height) whose
# photos make a stack of that direction: tall ones side by side, wide ones
# one above the other. KEEP leaves each photo's own shape.
DIRECTION_PROMPT = 'Stack the photos'
HORIZONTAL = 'Horizontal: side by side'
VERTICAL = 'Vertical: one above the other'
RATIO_PROMPT = 'Aspect ratio of each photo'
RATIOS = {
    HORIZONTAL: [(3, 4), (2, 3), (9, 16), (4, 5)],
    VERTICAL: [(4, 3), (3, 2), (16, 9), (5, 4)],
}
KEEP = 'Keep each photo as it is'
FIT_PROMPT = 'Fit each photo to '  # + the ratio
PAD = 'Pad: add white borders'
CROP = 'Crop: cut the sides, keep the center'

# The stack's file: one JPEG encode at the end (the photos go through PNG
# until then), at ImageIO's quality 0.9 (its default, 0.75, made a 24 MP
# photo's file about a quarter smaller: 3.9 MB against 5.3 MB). ImageIO
# writes JPEG for Convert Image on both iPhone and Mac.
QUALITY = 0.9
SUFFIX = '-stack'  # the stack's name: the first photo's, with this
DELAY = 5  # seconds after the latest photo's date

# A 1x1 white PNG (RGB, no alpha), stretched to the tile's size as the pad
# canvas: Core Graphics keeps a stretched pixel's color to the edges, white
# everywhere (checked at every interpolation quality).
WHITE_PNG = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR42mP4//8/AAX+'
    'Av4zEpUUAAAAAElFTkSuQmCC'
)

# ---------------------------------------------------------------------------
# The date, written into the JPEG as base64 text
#
# Save to Photo Album creates the asset from the file alone
# (PHAssetCreationRequest creationRequestForAssetFromImageAtFileURL, no
# creationDate), so Photos dates the stack from its EXIF. No action writes
# EXIF, but Base64 Encode, Replace Text and Base64 Decode can: the JPEG's
# base64 text gets a new start. Base64 turns each 3 bytes into 4 characters,
# so a piece of text replaces whole bytes only at multiples of 3 bytes; the
# segment below is laid out so that every place a date or an offset goes
# starts at such a multiple (prefix_pieces).
#
# Convert Image's JPEG (ImageIO; seen on macOS 27, and iOS shares ImageIO)
# starts with SOI, a JFIF APP0 segment (72 dpi) and ImageIO's own small Exif
# APP1 segment (ColorSpace, PixelX/YDimension). The shortcut keeps SOI and
# APP0, puts its
# EXIF segment after them, and renames ImageIO's APP1 to APP15, which no
# reader takes for EXIF: a JPEG has one EXIF segment. That is one Replace
# Text of MAIN_PATTERN (the first 21 bytes and the next marker's E1). A JPEG
# that starts otherwise gets the segment right after SOI (FALLBACK_PATTERN,
# the first 3 bytes), its own segments kept.

SOI = b'\xff\xd8'
JFIF = bytes.fromhex('ffe000104a46494600010100004800480000')  # APP0, 72 dpi
# Where the values go in the TIFF data (offsets from its "MM"), each at a
# multiple of 3 bytes in both prefixes (the TIFF starts 30 bytes in after
# SOI, APP0 and the APP1 header; 12 bytes in without APP0) and at an even
# offset, as TIFF wants. Each tag has a copy of its own.
DATE_AT = (132, 156, 180)  # DateTime, DateTimeOriginal, DateTimeDigitized
OFFSET_AT = (204, 216, 228)  # OffsetTime, OffsetTimeOriginal, ...Digitized
TIFF_LENGTH = 236
DATE_LENGTH = 19  # "2026:10:22 10:15:05"
OFFSET_LENGTH = 6  # "-04:00"


def exif_segment(date=b'2000:01:01 00:00:00', offset=b'+00:00'):
    """
    The APP1 segment with the date and its UTC offset: IFD0's DateTime and the
    Exif IFD's DateTimeOriginal and DateTimeDigitized, their OffsetTime tags,
    ExifVersion 0232 (offsets are EXIF 2.31) and ColorSpace sRGB, which
    ImageIO's segment had (Combine Images draws in device RGB, which ImageIO
    writes with no ICC profile).
    """
    assert len(date) == DATE_LENGTH and len(offset) == OFFSET_LENGTH

    def entry(tag, kind, count, value):
        return struct.pack('>HHI', tag, kind, count) + value

    def at(offset_):
        return struct.pack('>I', offset_)

    ifd0 = (
        struct.pack('>H', 2)
        + entry(0x0132, 2, 20, at(DATE_AT[0]))
        + entry(0x8769, 4, 1, at(38))  # the Exif IFD, right after IFD0
        + at(0)
    )
    exif = (
        struct.pack('>H', 7)
        + entry(0x9000, 7, 4, b'0232')
        + entry(0x9003, 2, 20, at(DATE_AT[1]))
        + entry(0x9004, 2, 20, at(DATE_AT[2]))
        + entry(0x9010, 2, 7, at(OFFSET_AT[0]))
        + entry(0x9011, 2, 7, at(OFFSET_AT[1]))
        + entry(0x9012, 2, 7, at(OFFSET_AT[2]))
        + entry(0xA001, 3, 1, struct.pack('>HH', 1, 0))
        + at(0)
    )
    tiff = bytearray(TIFF_LENGTH)
    head = b'MM\x00\x2a' + at(8) + ifd0 + exif
    tiff[: len(head)] = head
    for where in DATE_AT:
        tiff[where : where + DATE_LENGTH] = date

    for where in OFFSET_AT:
        tiff[where : where + OFFSET_LENGTH] = offset

    body = b'Exif\x00\x00' + bytes(tiff)
    return b'\xff\xe1' + struct.pack('>H', len(body) + 2) + body


def prefix_bytes(with_jfif):
    """
    The bytes that replace the JPEG's first 21 (with_jfif) or 3: SOI, the JFIF
    segment if kept, the EXIF segment and the next marker's FF.
    """
    return SOI + (JFIF if with_jfif else b'') + exif_segment() + b'\xff'


def prefix_pieces(with_jfif):
    """
    prefix_bytes' base64 text, split around the values: the constant texts
    between them, and for each value 'date' or 'offset', in order. A date is 19
    bytes from a multiple of 3: its base64 without "==" is 26 characters, and
    the text goes on with the last group's other two, which depend only on the
    NUL after the date and the byte after that. An offset is 6 bytes: 8
    characters exactly.
    """
    data = prefix_bytes(with_jfif)
    start = len(data) - 1 - TIFF_LENGTH  # where the TIFF begins
    encoded = base64.b64encode(data).decode()
    slots = sorted(
        [(start + w, 'date', 26) for w in DATE_AT]
        + [(start + w, 'offset', 8) for w in OFFSET_AT]
    )
    pieces, pos = [], 0
    for where, kind, length in slots:
        assert where % 3 == 0
        pieces += [encoded[pos : where // 3 * 4], kind]
        pos = where // 3 * 4 + length

    assert len(data) % 3 == 0
    return [*pieces, encoded[pos:]]


# The JPEG's start as Convert Image writes it (SOI, JFIF, FF), and "4Q": the
# E1 of ImageIO's APP1 with the 0 above its length. "7w" makes that E1 an EF
# (APP15) and keeps the length.
MAIN_PATTERN = '^' + base64.b64encode(SOI + JFIF + b'\xff').decode() + '4Q'
MAIN_RENAME = '7w'
FALLBACK_PATTERN = '^' + base64.b64encode(SOI + b'\xff').decode()
# Format Date's ISO 8601 with the time: en_US_POSIX, the device's time zone
# ("Z" when its offset is 0; ContentKit's NSDate(WFFormatting)). Anything
# else leaves the JPEG without a date rather than with broken bytes.
ISO_PATTERN = r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d([+-]\d\d:\d\d|Z)$'
ISO_TO_EXIF = (r'^(\d{4})-(\d\d)-(\d\d)T(\d\d:\d\d:\d\d).*$', '$1:$2:$3 $4')
ISO_TO_OFFSET = (r'^.{19}', '')
UTC = ('Z', '+00:00')

# ---------------------------------------------------------------------------
# The shortcut


class Builder(wfkit.Builder):
    def set_number(self, name, value):
        """Number (a constant) into the variable ``name``."""
        a = self.add(
            'is.workflow.actions.number', {'WFNumberActionNumber': str(value)}
        )
        self.set_variable(name, output_of(a, 'Number'))

    def set_text(self, name, value):
        self.set_variable(name, self.text(value))


def choose_shape(b):
    """
    The three questions. They set Horizontal (only for a horizontal stack),
    Ratio, A and B (width:height, only for a ratio), Keep (only when each photo
    keeps its shape), and Crop (only for crop). Shortcuts can't preselect a
    choice, so the order is the suggestion.
    """

    def ratios(direction):
        def ratio(a, r):
            b.set_number('A', a)
            b.set_number('B', r)
            b.set_text('Ratio', f'{a}:{r}')

        cases = {
            f'{a}:{r}': lambda a=a, r=r: ratio(a, r)
            for a, r in RATIOS[direction]
        }
        cases[KEEP] = lambda: b.set_text('Keep', 'keep')
        b.choose_from_menu(RATIO_PROMPT, cases)

    def horizontal():
        b.set_text('Horizontal', 'Horizontally')
        ratios(HORIZONTAL)

    b.choose_from_menu(
        DIRECTION_PROMPT,
        {HORIZONTAL: horizontal, VERTICAL: lambda: ratios(VERTICAL)},
    )
    b.if_has_value(
        variable('Keep'),
        lambda: None,
        lambda: b.choose_from_menu(
            text(FIT_PROMPT, variable('Ratio')),
            {PAD: lambda: None, CROP: lambda: b.set_text('Crop', 'crop')},
        ),
    )


def keep_images(b, photos):
    """
    The images among ``photos`` into Stills, in order: a video (its Media Type,
    read in memory, as Compress Photos does) is counted in Skipped. A Live
    Photo is an image: its still photo is stacked.
    """

    def per_item():
        media = b.photo_details(REPEAT_ITEM, 'Media Type')
        b.if_has_value(
            b.match_text(media, '^(Video|Audio)$'),
            lambda: b.append_variable('Skipped', REPEAT_ITEM),
            lambda: b.append_variable('Stills', REPEAT_ITEM),
        )

    b.repeat_each(photos, per_item)


def pair(b, first, second, operation):
    """Calculate Statistics ``operation`` (Minimum, Maximum) of two numbers."""
    b.set_variable('Pair', first)
    b.append_variable('Pair', second)
    return b.statistics(variable('Pair'), operation)


def tile_size(b, stills):
    """
    TW and TH, every tile's size, but for kept shapes only TH (horizontal) or
    TW (vertical), the smallest photo's: the stack never enlarges a photo.

    For a ratio A:B every tile is K·A × K·B, with K a whole number, so the
    ratio is exact: the largest K that no photo has to be enlarged for. A photo
    w × h cropped to A:B fits min(w/A, h/B) units, padded max(w/A, h/B); K is
    the smallest of those, rounded down. With all tiles one size, equal heights
    (horizontal) and equal widths (vertical) are the same thing.
    """

    def per_photo():
        w = b.photo_details(REPEAT_ITEM, 'Width')
        h = b.photo_details(REPEAT_ITEM, 'Height')
        b.append_variable('Widths', w)
        b.append_variable('Heights', h)
        b.if_has_value(
            variable('Keep'),
            lambda: None,
            lambda: units(w, h),
        )

    def units(w, h):
        across = b.calculate(w, '÷', variable('A'))
        down = b.calculate(h, '÷', variable('B'))
        b.if_has_value(
            variable('Crop'),
            lambda: b.append_variable(
                'Units', pair(b, across, down, 'Minimum')
            ),
            lambda: b.append_variable(
                'Units', pair(b, across, down, 'Maximum')
            ),
        )

    b.repeat_each(stills, per_photo)

    def keep():
        b.set_variable('TH', b.statistics(variable('Heights'), 'Minimum'))
        b.set_variable('TW', b.statistics(variable('Widths'), 'Minimum'))

    def ratio():
        k = b.round_number(
            b.statistics(variable('Units'), 'Minimum'), 'Always Round Down'
        )
        b.set_variable('TW', b.calculate(k, '×', variable('A')))
        b.set_variable('TH', b.calculate(k, '×', variable('B')))

    b.if_has_value(variable('Keep'), keep, ratio)


def make_tiles(b, stills):
    """
    Each photo as a tile, into Tiles: converted to PNG first (lossless, its
    orientation kept for Resize Image, which draws it upright), so that no step
    re-encodes it lossily and Combine Images, given PNGs only, writes a PNG
    too.

    Kept shapes: resized to TH high (horizontal) or TW wide. Crop: resized to
    cover TW × TH, the larger of the two scales, then the middle cut out. Pad:
    resized to fit inside, the smaller scale, and laid on the white canvas.
    Offsets are whole pixels (rounded down: a pixel nearer the top left when
    the margin is odd), so nothing is drawn between pixels.
    """
    b.if_has_value(
        variable('Keep'),
        lambda: None,
        lambda: b.if_has_value(
            variable('Crop'),
            lambda: None,
            lambda: b.set_variable(
                'Canvas',
                b.resize_image(
                    b.base64(b.text(WHITE_PNG), 'Decode'),
                    variable('TW'),
                    variable('TH'),
                ),
            ),
        ),
    )

    def per_photo():
        w = b.photo_details(REPEAT_ITEM, 'Width')
        h = b.photo_details(REPEAT_ITEM, 'Height')
        png = b.convert_image(REPEAT_ITEM, 'PNG')
        b.if_has_value(
            variable('Keep'),
            lambda: keep(png, w, h),
            lambda: fit(png, w, h),
        )

    def keep(png, w, h):
        def horizontal():
            width = b.round_number(
                b.calculate(b.calculate(w, '×', variable('TH')), '÷', h)
            )
            b.append_variable(
                'Tiles', b.resize_image(png, width, variable('TH'))
            )

        def vertical():
            height = b.round_number(
                b.calculate(b.calculate(h, '×', variable('TW')), '÷', w)
            )
            b.append_variable(
                'Tiles', b.resize_image(png, variable('TW'), height)
            )

        b.if_has_value(variable('Horizontal'), horizontal, vertical)

    def fit(png, w, h):
        across = b.calculate(variable('TW'), '÷', w)
        down = b.calculate(variable('TH'), '÷', h)

        def scaled(operation):
            scale = pair(b, across, down, operation)
            width = b.round_number(b.calculate(w, '×', scale))
            height = b.round_number(b.calculate(h, '×', scale))
            return width, height, b.resize_image(png, width, height)

        def margin(big, small):
            return b.round_number(
                b.calculate(b.calculate(big, '-', small), '÷', 2),
                'Always Round Down',
            )

        def crop():
            width, height, resized = scaled('Maximum')
            b.append_variable(
                'Tiles',
                b.crop_image(
                    resized,
                    margin(width, variable('TW')),
                    margin(height, variable('TH')),
                    variable('TW'),
                    variable('TH'),
                ),
            )

        def pad():
            width, height, resized = scaled('Minimum')
            b.append_variable(
                'Tiles',
                b.overlay_image(
                    variable('Canvas'),
                    resized,
                    margin(variable('TW'), width),
                    margin(variable('TH'), height),
                    width,
                    height,
                ),
            )

        b.if_has_value(variable('Crop'), crop, pad)

    b.repeat_each(stills, per_photo)


def stack_date(b, stills):
    """
    The variable When: DELAY seconds after the latest Date Taken among the
    photos (Photos' date for a library photo, else the EXIF date), or now if
    none has one. Each date's seconds from the first are compared, so the first
    date's own precision doesn't matter.
    """

    def per_photo():
        date = b.photo_details(REPEAT_ITEM, 'Date Taken')
        b.if_has_value(
            date, lambda: b.append_variable('Dates', date), lambda: None
        )

    b.repeat_each(stills, per_photo)

    def latest():
        first = b.item_from_list(variable('Dates'), 'First Item')
        b.repeat_each(
            variable('Dates'),
            lambda: b.append_variable(
                'Seconds', b.time_between(first, REPEAT_ITEM)
            ),
        )
        later = b.calculate(
            b.statistics(variable('Seconds'), 'Maximum'), '+', DELAY
        )
        b.set_variable('When', b.add_seconds(first, later))

    b.if_has_value(
        variable('Dates'),
        latest,
        lambda: b.set_variable('When', b.current_date()),
    )


def dated_jpeg(b, jpeg):
    """
    The variable Dated: ``jpeg`` with the EXIF segment carrying When (see
    exif_segment), or ``jpeg`` itself, and the variable Undated set, if When's
    text isn't the expected ISO 8601.
    """
    iso = b.format_date(variable('When'))

    def write():
        date = b.replace_text(iso, *ISO_TO_EXIF)
        offset = b.replace_text(b.replace_text(iso, *ISO_TO_OFFSET), *UTC)
        values = {
            # without the padding: the bytes after the date follow
            'date': b.replace_text(b.base64(date, 'Encode'), '=', ''),
            'offset': b.base64(offset, 'Encode'),
        }

        def spliced(pattern, with_jfif, *after):
            parts = [values.get(p, p) for p in prefix_pieces(with_jfif)]
            return b.replace_text(data, pattern, *parts, *after)

        data = b.base64(jpeg, 'Encode')
        b.if_has_value(
            b.match_text(data, MAIN_PATTERN),
            lambda: b.set_variable(
                'Spliced', spliced(MAIN_PATTERN, True, MAIN_RENAME)
            ),
            lambda: b.set_variable(
                'Spliced', spliced(FALLBACK_PATTERN, False)
            ),
        )
        b.set_variable('Dated', b.base64(variable('Spliced'), 'Decode'))

    def undated():
        b.set_variable('Dated', jpeg)
        b.set_text('Undated', ' It has no date: Format Date gave an odd text.')

    b.if_has_value(b.match_text(iso, ISO_PATTERN), write, undated)


def build(sample):
    b = Builder(sample)
    b.comment(
        f'{NAME} {VERSION}. '
        'Puts photos side by side or one above the other, each fitted to one '
        'aspect ratio (white borders or a centered crop) or kept as it is, '
        'all as high (or as wide) as the smallest, and saves the stack to '
        'Photos as a JPEG dated 5 seconds after the latest photo. Only '
        "Shortcuts' own actions: it runs on iPhone and Mac. From the share "
        'sheet (iPhone) or Finder (Mac) it stacks the shared photos; started '
        'any other way it shows a photo picker. Help: '
        f'{HELP_URL}'
    )
    b.if_has_value(
        SHORTCUT_INPUT,
        lambda: b.set_variable('Photos', SHORTCUT_INPUT),
        lambda: b.set_variable('Photos', b.select_photos()),
    )
    keep_images(b, variable('Photos'))
    stills = variable('Stills')

    def nothing_to_stack():
        b.notification(NAME, 'Nothing to stack: no photos were given.')
        b.stop()

    b.if_has_value(stills, lambda: None, nothing_to_stack)
    choose_shape(b)
    tile_size(b, stills)
    make_tiles(b, stills)
    b.if_has_value(
        variable('Horizontal'),
        lambda: b.set_variable(
            'Stack', b.combine_images(variable('Tiles'), 'Horizontally')
        ),
        lambda: b.set_variable(
            'Stack', b.combine_images(variable('Tiles'), 'Vertically')
        ),
    )
    stack = variable('Stack')
    jpeg = b.convert_image(stack, 'JPEG', QUALITY)
    stack_date(b, stills)
    dated_jpeg(b, jpeg)
    first = b.get_name(b.item_from_list(stills, 'First Item'))
    b.save_to_photos(b.set_name(variable('Dated'), first, SUFFIX, '.jpg'))
    b.if_has_value(
        variable('Skipped'),
        lambda: b.set_variable(
            'Skipped Note',
            b.text(' Skipped ', b.count(variable('Skipped')), ' video(s).'),
        ),
        lambda: None,
    )
    b.notification(
        NAME,
        'Saved a stack of ',
        b.count(stills),
        ' photo(s) to Photos, ',
        b.photo_details(stack, 'Width'),
        ' × ',
        b.photo_details(stack, 'Height'),
        '.',
        variable('Undated'),
        variable('Skipped Note'),
    )
    return b.actions


def stack_workflow(sample, actions):
    """
    The share sheet (iPhone; the Mac's Share menu, which gives no photos from
    Photos: the picker then), and on the Mac Finder's Quick Actions and the
    Services menu, with image files.
    """
    return workflow(
        sample,
        NAME,
        actions,
        share_sheet=True,
        types=['ActionExtension', 'QuickActions'],
        input_classes=['WFImageContentItem'],
        quick_action_surfaces=['Finder', 'Services'],
    )


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        '--no-sign', action='store_true', help='write unsigned plists only'
    )
    # scripts/release.py passes --guess to every tool's build_shortcuts.py;
    # this shortcut copies no action from a sample, so there is nothing to
    # guess.
    ap.add_argument('--guess', action='store_true', help=argparse.SUPPRESS)
    args = ap.parse_args()
    sample = Sample(wfkit.guessed_workflow())
    wfkit.write(
        NAME,
        stack_workflow(sample, build(sample)),
        not args.no_sign,
        OUT,
        DIST,
    )


if __name__ == '__main__':
    main()
