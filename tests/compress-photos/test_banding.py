"""
The grain jxlbatch adds to HDR outputs against banding (src/grain.c), checked
with the simulation of Apple's SDR rendering in banding.py on the sky fixture
(fixtures/hdr/sky.heic: a smooth gradient with faint grain, 1024 x 768).
"""

import re

import banding
import make_hdr_fixtures as mk
import numpy as np
import photo_helpers as ph
import pytest

FIXTURES = ph.HERE / 'fixtures'
SKY = FIXTURES / 'hdr' / 'sky.heic'
SDR_PHOTO = FIXTURES / 'heif' / 'rotate_then_crop.heic'
NO_GRAIN = ['--grain', '0', '--grain-coarse', '0']


def convert(encoder, folder, *args):
    """(the JPEG XL, what jxlbatch printed) for one photo."""
    ph.stage(folder, [args[-1]])
    result = encoder.run([*args[:-1], 'jxl_job.txt'], folder)
    assert result.returncode == 0, result.stdout + result.stderr
    return ph.read_done(folder)[1][0], result.stdout


def pq_green(jxl, ppm):
    """The green channel of a JPEG XL's 16-bit PQ pixels, in 8-bit-PQ units."""
    ph.run(
        [
            'djxl',
            jxl,
            ppm,
            '--color_space=RGB_D65_DCI_Rel_PeQ',
            '--bits_per_sample=16',
        ],
        check=True,
    )
    pixels, maximum = ph.read_ppm(ppm)
    return pixels[..., 1].astype(np.float32) * (255.0 / maximum)


@pytest.fixture(scope='module')
def references(wasm, tmp_path_factory):
    """The sky's lossless HDR picture (PQ) and its SDR picture (green)."""
    folder = tmp_path_factory.mktemp('sky-reference')
    jxl, _ = convert(wasm, folder, '-q', '100', SKY)
    sdr = mk.sky_scene(1024, 768)[..., 1].astype(np.float32)
    return pq_green(jxl, folder / 'reference.ppm'), sdr


def test_sky_bands_without_grain(wasm, references, tmp_path):
    # The problem the grain solves: through Apple's 8-bit PQ step, the sky
    # shows wide steps that its SDR picture doesn't, at both viewing scales.
    jxl, output = convert(wasm, tmp_path, '-q', '83', *NO_GRAIN, SKY)
    assert 'grain' not in output
    ok, scores = banding.passes(
        pq_green(jxl, tmp_path / 'out.ppm'), *references
    )
    assert not ok, scores
    for ours, theirs in scores.values():
        assert ours > theirs + 0.2, scores


def test_sky_does_not_band_with_the_default_grain(wasm, references, tmp_path):
    jxl, output = convert(wasm, tmp_path, '-q', '83', SKY)
    assert re.search(r'HDR \d+\.\d×, grain \d+\+\d+', output), output
    ok, scores = banding.passes(
        pq_green(jxl, tmp_path / 'out.ppm'), *references
    )
    assert ok, scores


@pytest.mark.parametrize('quality', ['88', '83', '72'])
def test_grain_grows_as_quality_drops(wasm, tmp_path, quality):
    # Lower qualities remove more of the grain, so they get more (grain_auto).
    _, output = convert(wasm, tmp_path, '-q', quality, SKY)
    fine, coarse = map(int, re.search(r'grain (\d+)\+(\d+)', output).groups())
    expected = {'88': (67, 41), '83': (80, 50), '72': (110, 68)}[quality]
    assert (fine, coarse) == expected


def test_sdr_photo_unchanged_by_the_grain_options(wasm, tmp_path):
    # Grain is for HDR (PQ) outputs only: an SDR photo's bytes don't change.
    a, output = convert(wasm, tmp_path / 'a', '-q', '83', SDR_PHOTO)
    b, _ = convert(wasm, tmp_path / 'b', '-q', '83', *NO_GRAIN, SDR_PHOTO)
    assert 'grain' not in output
    assert a.read_bytes() == b.read_bytes()


def test_lossless_hdr_output_gets_no_grain(wasm, tmp_path):
    a, output = convert(wasm, tmp_path / 'a', '-q', '100', SKY)
    b, _ = convert(wasm, tmp_path / 'b', '-q', '100', *NO_GRAIN, SKY)
    assert 'grain' not in output
    assert a.read_bytes() == b.read_bytes()


def test_sdr_option_gets_no_grain(wasm, tmp_path):
    _, output = convert(wasm, tmp_path, '--sdr', '-q', '83', SKY)
    assert 'grain' not in output


def test_grain_is_reproducible(wasm, tmp_path):
    a, _ = convert(wasm, tmp_path / 'a', '-q', '83', SKY)
    b, _ = convert(wasm, tmp_path / 'b', '-q', '83', SKY)
    assert a.read_bytes() == b.read_bytes()


@pytest.mark.parametrize(
    'args', [['--grain', '-1'], ['--grain'], ['--grain-coarse', '500']]
)
def test_bad_grain_options(wasm, tmp_path, args):
    ph.stage(tmp_path, [SKY])
    result = wasm.run([*args, 'jxl_job.txt'], tmp_path)
    assert result.returncode == 2
    assert 'usage' in result.stdout
