"""
HEIF layouts beyond an iPhone's (fixtures/heif/, written by
make_hdr_fixtures.py): transforms in an unusual order (a rotation or mirror
listed before the crop), derived 'iden' photos whose source is turned itself,
and transparency (alpha) images with transforms of their own. Converted
losslessly in every build, each must come out exactly as expected, upright, and
its original may be offered for deletion.
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
