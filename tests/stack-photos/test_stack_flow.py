"""
Stack Photos run end to end on a model of Shortcuts (shortcut_model.py), for
every direction, aspect ratio and fit, and from the share sheet and the picker:
the questions; the tiles (one size for a ratio, exact; as high, or as wide, as
the smallest; a crop or a pad only on two opposite sides, centered; never an
enlarged photo); the stack saved once, named after the first photo; its EXIF
date 5 seconds after the latest photo, in the device's time zone, with the
pixels untouched; videos skipped.
"""

import datetime as dt
import io
from decimal import ROUND_FLOOR, Decimal
from fractions import Fraction

import PIL.Image
import pytest
import shortcut_model as sm
import stack_helpers as sh

NEW_YORK = dt.timezone(dt.timedelta(hours=-4))
TOKYO = dt.timezone(dt.timedelta(hours=9))


def photo(name, width, height, date=None, media='Image'):
    return sm.Img(width, height, name=name, date=date, media=media)


# An iPhone photo each way, a 24 MP one, a screenshot and a square, with
# dates in two time zones (the latest is IMG_0003's, written in Tokyo).
PHOTOS = [
    photo(
        'IMG_0001',
        4032,
        3024,
        dt.datetime(2026, 5, 1, 9, 0, 0, tzinfo=NEW_YORK),
    ),
    photo(
        'IMG_0002',
        3024,
        4032,
        dt.datetime(2026, 5, 1, 9, 0, 30, tzinfo=NEW_YORK),
    ),
    photo(
        'IMG_0003',
        5712,
        4284,
        dt.datetime(2026, 5, 2, 7, 15, 59, tzinfo=TOKYO),
    ),
    photo(
        'IMG_0004',
        1179,
        2556,
        dt.datetime(2026, 4, 30, 23, 59, 59, tzinfo=dt.UTC),
    ),
    photo('IMG_0005', 2000, 2000),  # no date: not counted
]
LATEST = dt.datetime(2026, 5, 2, 7, 15, 59, tzinfo=TOKYO)


@pytest.fixture(scope='module')
def jpeg():
    """Convert Image's JPEG as ImageIO writes it (imageio.swift)."""
    return (sh.FIXTURES / 'imageio.jpg').read_bytes()


def run(actions, gen, answers, photos=PHOTOS, start='share sheet', **kw):
    shortcuts = sm.Shortcuts(
        actions,
        shortcut_input=list(photos) if start == 'share sheet' else None,
        picked=photos,
        answers=answers,
        **kw,
    )
    return shortcuts.run(), shortcuts


def exif(data):
    """DateTimeOriginal, OffsetTimeOriginal and the rest, as Pillow reads."""
    with PIL.Image.open(io.BytesIO(data)) as image:
        image.load()
        tags = image.getexif()
        sub = tags.get_ifd(0x8769)
        return {
            'DateTime': tags.get(0x0132),
            'DateTimeOriginal': sub.get(0x9003),
            'DateTimeDigitized': sub.get(0x9004),
            'OffsetTime': sub.get(0x9010),
            'OffsetTimeOriginal': sub.get(0x9011),
            'OffsetTimeDigitized': sub.get(0x9012),
            'ColorSpace': sub.get(0xA001),
            'pixels': image.tobytes(),
        }


def pixels(data):
    with PIL.Image.open(io.BytesIO(data)) as image:
        return image.tobytes()


def expected_date(date, tz):
    local = date.astimezone(tz)
    offset = local.strftime('%z')
    return local.strftime('%Y:%m:%d %H:%M:%S'), f'{offset[:3]}:{offset[3:]}'


CASES = [
    (direction, f'{a}:{b}', fit)
    for direction, ratios in (
        ('Horizontal: side by side', [(3, 4), (2, 3), (9, 16), (4, 5)]),
        ('Vertical: one above the other', [(4, 3), (3, 2), (16, 9), (5, 4)]),
    )
    for a, b in ratios
    for fit in (
        'Pad: add white borders',
        'Crop: cut the sides, keep the center',
    )
]


@pytest.mark.parametrize('direction,ratio,fit', CASES)
def test_ratio_tiles(gen, actions, jpeg, direction, ratio, fit):
    result, s = run(actions, gen, [direction, ratio, fit], jpeg=jpeg)
    assert result == 'done'
    a, b = (int(n) for n in ratio.split(':'))
    crop = fit == gen.CROP
    # The largest whole K such that no photo is enlarged: a photo w × h holds
    # min(w/a, h/b) units cropped and max(w/a, h/b) padded.
    k = min(
        (min if crop else max)(Fraction(p.width, a), Fraction(p.height, b))
        for p in PHOTOS
    )
    k = int(k)
    tile = (k * a, k * b)

    ((mode, tiles),) = s.combined
    assert mode == (
        'Horizontally' if direction == gen.HORIZONTAL else 'Vertically'
    )
    assert [t.name for t in tiles] == [p.name for p in PHOTOS]  # in order
    assert all((t.width, t.height) == tile for t in tiles)
    assert all(t.kind == 'png' for t in tiles)  # lossless until the JPEG

    photos = [r for r in s.resized if r[0].name != 'canvas']
    assert len(photos) == len(PHOTOS)
    for (image, width, height), original in zip(photos, PHOTOS):
        assert image.kind == 'png'  # converted first, then resized
        assert width <= original.width and height <= original.height

    if crop:
        assert not s.overlaid
        for image, x, y, width, height in s.cropped:
            assert (width, height) == tile
            # only two opposite sides, the middle kept
            assert (x, y) == (
                (image.width - width) // 2,
                (image.height - height) // 2,
            )
            assert x == 0 or y == 0
    else:
        assert not s.cropped
        canvas = [r for r in s.resized if r[0].name == 'canvas']
        assert [(w, h) for _, w, h in canvas] == [tile]  # made once
        for base, image, x, y in s.overlaid:
            assert (base.width, base.height) == tile
            assert (x, y) == (
                (tile[0] - image.width) // 2,
                (tile[1] - image.height) // 2,
            )
            assert x == 0 or y == 0


@pytest.mark.parametrize(
    'direction', ['Horizontal: side by side', 'Vertical: one above the other']
)
def test_kept_shapes(gen, actions, jpeg, direction):
    result, s = run(actions, gen, [direction, gen.KEEP], jpeg=jpeg)
    assert result == 'done'
    assert not s.cropped and not s.overlaid
    ((mode, tiles),) = s.combined
    if direction == gen.HORIZONTAL:
        height = min(p.height for p in PHOTOS)
        expected = [
            (
                int(
                    (Decimal(p.width) * height / p.height).quantize(
                        1, 'ROUND_HALF_UP'
                    )
                ),
                height,
            )
            for p in PHOTOS
        ]
    else:
        width = min(p.width for p in PHOTOS)
        expected = [
            (
                width,
                int(
                    (Decimal(p.height) * width / p.width).quantize(
                        1, 'ROUND_HALF_UP'
                    )
                ),
            )
            for p in PHOTOS
        ]

    assert [(t.width, t.height) for t in tiles] == expected


def test_questions(gen, actions, jpeg):
    _, s = run(actions, gen, [gen.HORIZONTAL, '3:4', gen.PAD], jpeg=jpeg)
    assert s.menus == [
        ('Stack the photos', [gen.HORIZONTAL, gen.VERTICAL]),
        (
            'Aspect ratio of each photo',
            ['3:4', '2:3', '9:16', '4:5', gen.KEEP],
        ),
        ('Fit each photo to 3:4', [gen.PAD, gen.CROP]),
    ]
    _, s = run(actions, gen, [gen.VERTICAL, gen.KEEP], jpeg=jpeg)
    assert s.menus == [
        ('Stack the photos', [gen.HORIZONTAL, gen.VERTICAL]),
        (
            'Aspect ratio of each photo',
            ['4:3', '3:2', '16:9', '5:4', gen.KEEP],
        ),
    ]  # nothing to fit


@pytest.mark.parametrize('start', ['share sheet', 'Shortcuts app'])
@pytest.mark.parametrize(
    'tz', [NEW_YORK, TOKYO, dt.UTC], ids=['-04', '+09', 'utc']
)
def test_saved_with_the_date(gen, actions, jpeg, start, tz):
    result, s = run(
        actions,
        gen,
        [gen.VERTICAL, '4:3', gen.CROP],
        start=start,
        jpeg=jpeg,
        tz=tz,
    )
    assert result == 'done'
    (saved,) = s.saved
    assert isinstance(saved, sm.File)
    assert saved.name == 'IMG_0001-stack.jpg'
    tags = exif(saved.data)
    when, offset = expected_date(LATEST + dt.timedelta(seconds=5), tz)
    for key in ('DateTime', 'DateTimeOriginal', 'DateTimeDigitized'):
        assert tags[key] == when

    for key in ('OffsetTime', 'OffsetTimeOriginal', 'OffsetTimeDigitized'):
        assert tags[key] == offset

    assert tags['ColorSpace'] == 1
    assert tags['pixels'] == pixels(jpeg)
    (note,) = s.notifications
    assert note.startswith(
        f'Saved a stack of {len(PHOTOS)} photo(s) to Photos, '
    )
    assert 'no date' not in note and 'Skipped' not in note


def test_imageio_segment_renamed(gen, actions, jpeg):
    # ImageIO's own EXIF segment becomes APP15: one EXIF segment in the file.
    _, s = run(actions, gen, [gen.HORIZONTAL, gen.KEEP], jpeg=jpeg)
    data = s.saved[0].data
    markers = []
    i = 2
    while data[i + 1] != 0xDA:
        markers.append(data[i + 1])
        i += 2 + int.from_bytes(data[i + 2 : i + 4], 'big')

    assert markers[:3] == [0xE0, 0xE1, 0xEF]
    assert markers.count(0xE1) == 1
    assert data[2:20] == jpeg[2:20]  # JFIF kept


def test_other_jpeg_start_still_dated(gen, actions):
    # A JPEG that doesn't start as ImageIO's does gets the segment after SOI.
    buffer = io.BytesIO()
    PIL.Image.new('RGB', (40, 30), (10, 200, 30)).save(
        buffer, 'JPEG', quality=90
    )
    other = buffer.getvalue()
    assert not other.startswith(
        bytes.fromhex('ffd8ffe000104a46494600010100004800480000')
    )
    _, s = run(actions, gen, [gen.HORIZONTAL, '2:3', gen.PAD], jpeg=other)
    data = s.saved[0].data
    assert data[2:4] == b'\xff\xe1'
    when, offset = expected_date(LATEST + dt.timedelta(seconds=5), NEW_YORK)
    tags = exif(data)
    assert (tags['DateTimeOriginal'], tags['OffsetTimeOriginal']) == (
        when,
        offset,
    )
    assert tags['pixels'] == pixels(other)


def test_no_dates_uses_now(gen, actions, jpeg):
    undated = [photo('A', 3000, 2000), photo('B', 2000, 3000)]
    now = dt.datetime(2026, 10, 22, 16, 4, 5, tzinfo=dt.UTC)
    _, s = run(
        actions,
        gen,
        [gen.HORIZONTAL, '4:5', gen.CROP],
        photos=undated,
        jpeg=jpeg,
        now=now,
    )
    when, offset = expected_date(now, NEW_YORK)
    tags = exif(s.saved[0].data)
    assert (tags['DateTimeOriginal'], tags['OffsetTimeOriginal']) == (
        when,
        offset,
    )


def test_one_photo(gen, actions, jpeg):
    # Nothing to stack it with: fitted to the ratio all the same.
    (single,) = PHOTOS[:1]
    result, s = run(
        actions,
        gen,
        [gen.HORIZONTAL, '4:5', gen.PAD],
        photos=[single],
        jpeg=jpeg,
    )
    assert result == 'done'
    ((_, tiles),) = s.combined
    assert [(t.width, t.height) for t in tiles] == [(4032, 5040)]  # K = 1008


def test_videos_skipped(gen, actions, jpeg):
    video = photo('IMG_0009', 1920, 1080, media='Video')
    result, s = run(
        actions,
        gen,
        [gen.HORIZONTAL, gen.KEEP],
        photos=[*PHOTOS[:2], video],
        jpeg=jpeg,
    )
    assert result == 'done'
    ((_, tiles),) = s.combined
    assert [t.name for t in tiles] == ['IMG_0001', 'IMG_0002']
    assert s.notifications[0].endswith(' Skipped 1 video(s).')


def test_nothing_to_stack(gen, actions):
    video = photo('IMG_0009', 1920, 1080, media='Video')
    result, s = run(actions, gen, [], photos=[video])
    assert result == 'stopped'
    assert s.notifications == ['Nothing to stack: no photos were given.']
    assert not s.saved and not s.menus


def test_odd_date_text_saves_undated(gen, actions, jpeg, monkeypatch):
    # Should Format Date ever give another text, the JPEG is saved as it is.
    monkeypatch.setattr(
        sm.Shortcuts, 'iso', lambda self, date: '2026-05-02T07:16:04.250+09:00'
    )
    _, s = run(actions, gen, [gen.HORIZONTAL, gen.KEEP], jpeg=jpeg)
    assert s.saved[0].data == jpeg
    assert 'It has no date' in s.notifications[0]


def test_rounding_never_enlarges(gen, actions, jpeg):
    # Sizes whose ratios don't divide evenly.
    odd = [
        photo('A', 4031, 3023),
        photo('B', 3001, 4003),
        photo('C', 997, 1301),
    ]
    for answers in (
        [gen.HORIZONTAL, '9:16', gen.PAD],
        [gen.HORIZONTAL, '9:16', gen.CROP],
        [gen.VERTICAL, '16:9', gen.PAD],
        [gen.VERTICAL, '16:9', gen.CROP],
        [gen.HORIZONTAL, gen.KEEP],
        [gen.VERTICAL, gen.KEEP],
    ):
        result, s = run(actions, gen, answers, photos=odd, jpeg=jpeg)
        assert result == 'done'
        for image, width, height in s.resized:
            if image.name != 'canvas':
                original = next(p for p in odd if p.name == image.name)
                assert width <= original.width and height <= original.height


def test_no_stack_says_so(gen, actions, jpeg, monkeypatch):
    # Should Combine Images give nothing, nothing is reported as saved.
    monkeypatch.setattr(
        sm.Shortcuts, 'do_image_combine', lambda self, p, r: None
    )
    result, s = run(actions, gen, [gen.HORIZONTAL, gen.KEEP], jpeg=jpeg)
    assert result == 'stopped'
    assert s.notifications == [gen.NO_STACK]
    assert not s.saved
