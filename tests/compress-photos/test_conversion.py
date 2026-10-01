"""
End to end: photos written the way an iPhone or camera writes them (Apple's
ImageIO), converted in one batch as the shortcut runs jxlbatch, then checked
with exiftool, djxl and Apple's ImageIO (what Photos uses).
"""

import numpy as np
import photo_helpers as ph
import pytest
from PIL import Image

NAMES = list(ph.PHOTOS)


@pytest.mark.parametrize('name', NAMES)
def test_converted_under_original_name(batch, name):
    original, jxl, saved = batch.results[name]
    assert jxl is not None, f'{name} was not converted:\n{batch.output}'
    assert jxl.exists()
    assert saved == f'{original.stem}.jxl'


@pytest.mark.parametrize('name', NAMES)
def test_exif_kept(batch, name):
    original, jxl, _ = batch.results[name]
    before, after = ph.exif_tags(original), ph.exif_tags(jxl)
    assert before, 'the test photo should have EXIF'
    changed = sorted(
        k
        for k in set(before) | set(after)
        if k not in ph.EXIF_ALLOWED_DIFF and before.get(k) != after.get(k)
    )
    assert not changed, {k: (before.get(k), after.get(k)) for k in changed}
    assert after.get('IFD0:Orientation', 1) == 1


@pytest.mark.parametrize('name', NAMES)
def test_xmp_kept_with_orientation_reset(batch, name):
    _, jxl, _ = batch.results[name]
    xmp = ph.xmp_tags(jxl)
    assert xmp.get('Description') == 'jxlbatch test'
    assert xmp.get('Orientation', 1) == 1


@pytest.mark.parametrize('name', NAMES)
def test_metadata_boxes_uncompressed(batch, name):
    # Apple's ImageIO can't read Brotli-compressed ("brob") boxes.
    _, jxl, _ = batch.results[name]
    dump = ph.boxes(jxl)
    assert 'brob' not in dump
    assert "Tag 'Exif'" in dump
    assert "Tag 'xml '" in dump


@pytest.mark.parametrize('name', NAMES)
def test_photos_reads_same_metadata(batch, imageio, name):
    original, jxl, _ = batch.results[name]
    props = imageio(original, jxl)
    before, after = props[str(original)], props[str(jxl)]
    assert 'error' not in after, 'ImageIO cannot read the JXL'
    differ = {
        f: (before.get(f), after.get(f))
        for f in ph.IMAGEIO_FIELDS
        if before.get(f) != after.get(f)
    }
    # A photo without a color profile is stored as sRGB, its usual meaning.
    if differ.get('color') == (None, 'sRGB IEC61966-2.1'):
        del differ['color']

    assert not differ
    assert after['orientation'] == 1
    assert after['upright'] == before['upright']


@pytest.mark.parametrize('name', NAMES)
def test_pixels_match_apple_render(batch, name, tmp_path):
    original, jxl, _ = batch.results[name]
    reference = ph.apple_render(original, tmp_path / 'apple.png')
    decoded = ph.decode_jxl(jxl, tmp_path / 'jxl.png')
    assert decoded.size == reference.size
    assert ph.psnr(reference, decoded) >= ph.MIN_PSNR


def test_10_bit_heif_stays_10_bit(batch):
    original, jxl, _ = batch.results['heic_10bit']
    depth = ph.run(['exiftool', '-s3', '-ImagePixelDepth', original]).stdout
    assert depth.split() == ['10', '10', '10'], 'test photo should be 10-bit'
    info = ph.run(['jxlinfo', jxl])
    ph.need(info.returncode == 0, 'jxlinfo (Homebrew jpeg-xl) is needed')
    assert '10-bit' in info.stdout


def test_transparency_kept(batch, tmp_path):
    original, jxl, _ = batch.results['png_alpha']
    decoded = ph.decode_jxl(jxl, tmp_path / 'jxl.png')
    assert decoded.mode == 'RGBA'
    before = np.asarray(Image.open(original).getchannel('A'), dtype=int)
    after = np.asarray(decoded.getchannel('A'), dtype=int)
    assert np.abs(before - after).max() <= 2


def test_reminds_about_iphone_jpegs(batch):
    # An iPhone photo arriving as JPEG means the share sheet's "Send As" was
    # Automatic; jxlbatch suggests sending originals instead.
    assert batch.output.count('Note: Photos sent') == 1
