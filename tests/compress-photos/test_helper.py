"""
Compress Photos Helper (src/photoedits, scripts/build-helper.sh), the app the
Mac selection route starts to save an edited photo's copy with its edit. Its
rules that need no photo library: the version line the shortcut checks, what an
edit record allows, and the geometry check. The library parts (check, create)
run only against Photos; test_mac_script.py stands in for them.
"""

import json
import plistlib
import shutil
import zlib

import photo_helpers as ph
import pytest
from PIL import Image

FIXTURES = ph.HERE / 'fixtures'
VERSION = (ph.TOOL / 'VERSION').read_text().strip()


@pytest.fixture(scope='session')
def helper(tmp_path_factory):
    """The helper's executable, built from source into a folder of its own."""
    ph.need(shutil.which('swiftc'), 'swiftc is needed (Xcode)')
    out = tmp_path_factory.mktemp('helper')
    built = ph.run([ph.TOOL / 'scripts' / 'build-helper.sh', out])
    assert built.returncode == 0, built.stderr
    assert (out / 'compress-photos-helper-macos.zip').is_file()
    return (
        out
        / 'Compress Photos Helper.app'
        / 'Contents'
        / 'MacOS'
        / 'photoedits'
    )


def test_version_line_is_what_the_shortcut_checks(helper):
    # selection.zsh reads "photoedits <version> protocol 2" as the answers'
    # first line (1 was the prototype's); the version is Compress Photos'.
    result = ph.run([helper, '--version'])
    assert result.stdout == f'photoedits {VERSION} protocol 2\n'


def record(
        tmp_path, parts=('Crop',), fmt='com.apple.photo', base=0, data=None
):
    """An edit record as Photos keeps it (Adjustments.plist)."""
    if data is None:
        edit = json.dumps({'adjustments': [{'identifier': p} for p in parts]})
        deflate = zlib.compressobj(wbits=-15)  # raw DEFLATE, Apple's "zlib"
        data = deflate.compress(edit.encode()) + deflate.flush()

    path = tmp_path / 'Adjustments.plist'
    path.write_bytes(
        plistlib.dumps({
            'adjustmentFormatIdentifier': fmt,
            'adjustmentFormatVersion': '1.5',
            'adjustmentBaseVersion': base,
            'adjustmentData': data,
        })
    )
    return path


@pytest.mark.parametrize(
    ('kwargs', 'answer'),
    [
        ({}, 'ok|'),
        # Portrait and Photographic Styles: a HEIC copy has their data
        (
            {'parts': ('Crop', 'DepthEffect', 'SemanticStyle', 'SmartTone')},
            'ok|',
        ),
        ({'parts': ('Inpaint', 'InpaintMasks')}, 'ok|Clean Up, not tested'),
        ({'parts': ('Mystery',)}, 'ok|a part not tested (Mystery)'),
        (
            {'data': b'not deflate'},
            "ok|its edit is in a form this version doesn't read",
        ),
        # what can't be copied: the shortcut burns the edit in
        (
            {'fmt': 'com.example.editor'},
            'no|edited by another app (com.example.editor)',
        ),
        ({'base': 1}, 'no|its edit is not based on the original photo'),
        ({'data': b''}, 'no|Photos keeps its edit outside its edit record'),
    ],
)
def test_edit_record_rules(helper, tmp_path, kwargs, answer):
    result = ph.run([helper, 'plist', record(tmp_path, **kwargs)])
    assert result.stdout == answer + '\n'


def test_unreadable_edit_record_is_refused(helper, tmp_path):
    path = tmp_path / 'Adjustments.plist'
    path.write_text('not a plist')
    result = ph.run([helper, 'plist', path])
    assert result.stdout == 'no|its edit could not be read\n'


def jpeg(path, size, orientation):
    image = Image.new('RGB', size, (90, 120, 150))
    exif = image.getexif()
    exif[0x0112] = orientation
    image.save(path, exif=exif)
    return path


@pytest.mark.parametrize(
    ('copy', 'original', 'answer'),
    [
        # photobatch turns the pixels upright: an orientation alone is no
        # difference (a photo stored upside down, orientation 3)
        (((64, 48), 1), ((64, 48), 3), 'ok'),
        (((48, 64), 1), ((64, 48), 6), 'ok'),
        (
            ((64, 48), 1),
            ((64, 48), 6),
            'no|the copy is 64x48, the original 48x64',
        ),
        (
            ((60, 48), 1),
            ((64, 48), 1),
            'no|the copy is 60x48, the original 64x48',
        ),
    ],
)
def test_geometry_compares_the_shown_sizes(
        helper, tmp_path, copy, original, answer
):
    a = jpeg(tmp_path / 'copy.jpg', *copy)
    b = jpeg(tmp_path / 'original.jpg', *original)
    assert ph.run([helper, 'geometry', a, b]).stdout == answer + '\n'
