"""
The stack's date as Apple's ImageIO, which Photos uses, reads it (macOS): a
JPEG written the way Combine Images and Convert Image write theirs
(imageio.swift) goes through the shortcut's base64 steps (run on
shortcut_model.py); ImageIO then reads the date and offset in DateTimeOriginal,
DateTimeDigitized and the OffsetTime tags, and the same pixels; exiftool agrees
and finds no error. ImageIO's JPEG still starts as MAIN_PATTERN expects, also
at the sizes stacks have (else the shortcut takes the fallback, which keeps
ImageIO's own EXIF segment too).
"""

import base64
import datetime as dt
import json
import shutil
import sys

import pytest
import shortcut_model as sm
import stack_helpers as sh

pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='ImageIO')


def props(imageio, path):
    result = sh.run([imageio, 'props', path])
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('size', [(64, 48), (4032, 3024), (12096, 4032)])
def test_imageio_jpeg_start(gen, imageio, tmp_path, size):
    path = tmp_path / 'stack.jpg'
    result = sh.run([imageio, 'jpeg', path, *size])
    assert result.returncode == 0, result.stderr
    start = base64.b64encode(path.read_bytes()[:30]).decode()
    assert start.startswith(gen.MAIN_PATTERN.removeprefix('^'))


@pytest.mark.parametrize(
    'tz,offset',
    [
        (dt.timezone(dt.timedelta(hours=-4)), '-04:00'),
        (dt.timezone(dt.timedelta(hours=5, minutes=30)), '+05:30'),
        (dt.UTC, '+00:00'),
    ],
)
def test_date_read_by_imageio(gen, actions, imageio, tmp_path, tz, offset):
    original = tmp_path / 'converted.jpg'
    assert sh.run([imageio, 'jpeg', original, 600, 400]).returncode == 0
    latest = dt.datetime(2026, 5, 2, 7, 15, 59, tzinfo=dt.UTC)
    photos = [
        sm.Img(
            4032, 3024, name='IMG_0001', date=latest - dt.timedelta(days=1)
        ),
        sm.Img(3024, 4032, name='IMG_0002', date=latest),
    ]
    shortcuts = sm.Shortcuts(
        actions,
        shortcut_input=photos,
        answers=sh.answers(gen, gen.HORIZONTAL, '3:4', gen.CROP),
        jpeg=original.read_bytes(),
        tz=tz,
    )
    assert shortcuts.run() == 'done'
    saved = tmp_path / shortcuts.saved[0].name
    saved.write_bytes(shortcuts.saved[0].data)

    when = (latest + dt.timedelta(seconds=5)).astimezone(tz)
    clock = when.strftime('%Y:%m:%d %H:%M:%S')
    read, before = props(imageio, saved), props(imageio, original)
    assert read['DateTimeOriginal'] == read['DateTimeDigitized'] == clock
    assert read['OffsetTimeOriginal'] == read['OffsetTimeDigitized'] == offset
    assert read['OffsetTime'] == offset
    assert read['ColorSpace'] == 1
    assert (read['width'], read['height'], read['pixels']) == (
        before['width'],
        before['height'],
        before['pixels'],
    )

    sh.need(shutil.which('exiftool'), 'exiftool (Homebrew) is needed')
    result = sh.run([
        'exiftool',
        '-j',
        '-G1',
        '-a',
        '-Error',
        '-ExifIFD:DateTimeOriginal',
        '-ExifIFD:OffsetTimeOriginal',
        '-Composite:SubSecDateTimeOriginal',
        saved,
    ])
    assert result.returncode == 0, result.stderr
    (tags,) = json.loads(result.stdout)
    assert 'ExifTool:Error' not in tags
    assert tags['ExifIFD:DateTimeOriginal'] == clock
    assert tags['ExifIFD:OffsetTimeOriginal'] == offset
    assert tags['Composite:SubSecDateTimeOriginal'] == clock + offset
