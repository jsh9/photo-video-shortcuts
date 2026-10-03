"""
HEIF layouts beyond an iPhone's (fixtures/heif/, written by
make_hdr_fixtures.py): transforms in an unusual order (a rotation or mirror
listed before the crop), a crop reaching past the photo's edges (cut to the
photo, as libheif does), derived 'iden' photos whose source is turned itself,
and transparency (alpha) images with transforms of their own. Converted
losslessly in every build, each must come out exactly as expected, upright, and
its original may be offered for deletion. A crop that leaves nothing fails the
photo, as in libheif (and jxlbatch 0.1.1).
"""

import numpy as np
import photo_helpers as ph
import pytest
from PIL import Image

FIXTURES = ph.HERE / 'fixtures' / 'heif'
EXPECTED = np.load(FIXTURES / 'expected.npz')


@pytest.mark.parametrize('name', sorted(EXPECTED.files))
def test_layout(encoder, name, tmp_path):
    ph.stage(tmp_path, [FIXTURES / f'{name}.heic'])
    result = encoder.run(['-q', '100', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    jxl, _ = ph.read_done(tmp_path)[1]
    assert not ph.kept_originals(tmp_path), result.stdout
    ph.run(['djxl', jxl, tmp_path / 'out.png'], check=True)
    ours = np.asarray(Image.open(tmp_path / 'out.png'))  # RGB or RGBA
    want = EXPECTED[name]
    assert ours.shape == want.shape, result.stdout
    assert np.abs(ours.astype(int) - want.astype(int)).max() <= 1


def test_crop_outside_the_photo_fails(encoder, tmp_path):
    ph.stage(tmp_path, [FIXTURES / 'crop_outside_the_photo.heic'])
    result = encoder.run(['-q', '100', 'jxl_job.txt'], tmp_path)
    output = ' '.join(result.stdout.split())  # unwrapped
    assert 'FAILED: HEIF decoding failed (invalid crop)' in output
    # not converted, so its original is not offered for deletion
    assert not (tmp_path / 'jxl_done.txt').exists(), result.stdout
