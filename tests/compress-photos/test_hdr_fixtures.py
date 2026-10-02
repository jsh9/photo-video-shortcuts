"""
The committed HDR test photos (fixtures/hdr/, written by make_hdr_fixtures.py):
the layouts the Core Image test photos can't cover. Every orientation, with and
without the gain map's own transforms; crops (also past the photo's edges);
grids; 10-bit photos; RGB, multichannel, limited-range, full- and quarter-size
gain maps; sRGB and unspecified color; a gain map brighter than PQ can store;
Apple's older gain maps (before iOS 18); and gain maps that can't be used.

Converted losslessly (-q 100), an HDR photo must match the reference math
(hdr_reference.py) to 1/65535. (Apple can't decode the synthetic photos with
its older gain maps, so Apple's rendering of those is compared only with your
own photos, in test_samples.py.) A photo whose gain map can't be used must say
why, stay SDR, and be marked so that its original is kept; except a photo whose
gain map isn't labeled as Apple's (not taken by an iPhone camera), whose
original may be deleted.
"""

import json

import numpy as np
import photo_helpers as ph
import pytest

FIXTURES = ph.HERE / 'fixtures' / 'hdr'
CASES = json.loads((FIXTURES / 'cases.json').read_text())
HDR = sorted(n for n, c in CASES.items() if 'note' not in c)
NOT_USED = sorted(n for n, c in CASES.items() if 'note' in c)
# a sample for each build: rotation, crop, older gain map, 10-bit, channels
EVERY_BUILD = ['o5', 'crop_o6', 'apple_older_o6', 'ten_bit', 'multichannel']


def convert(encoder, names, folder):
    """{name: (jxl or None, what jxlbatch printed for it, original kept)}"""
    staged = ph.stage(folder, [FIXTURES / f'{n}.heic' for n in names])
    result = encoder.run(['-q', '100', 'jxl_job.txt'], folder)
    assert result.returncode == 0, result.stdout + result.stderr
    done, kept = ph.read_done(folder), ph.kept_originals(folder)
    return {
        heic.stem: (
            done.get(index, (None, None))[0],
            ' '.join(ph.photo_output(result.stdout, heic.stem).split()),
            index in kept,
        )
        for index, heic in staged.items()
    }


@pytest.fixture(scope='module')
def converted(wasm, tmp_path_factory):
    return convert(wasm, sorted(CASES), tmp_path_factory.mktemp('fixtures'))


@pytest.fixture(scope='module')
def expected():
    return np.load(FIXTURES / 'expected.npz')


def decoded(jxl, ppm):
    """The 16-bit PQ pixels of a lossless JPEG XL."""
    ph.run(['djxl', jxl, ppm], check=True)
    return ph.read_ppm(ppm)[0].astype(np.int64)


@pytest.mark.parametrize('name', HDR)
def test_matches_reference(converted, expected, name, tmp_path):
    jxl, output, _ = converted[name]
    assert jxl is not None, output
    ours = decoded(jxl, tmp_path / 'ours.ppm')
    want = expected[name].astype(np.int64)
    assert ours.shape == want.shape, output
    assert np.abs(ours - want).max() <= 1, output


@pytest.mark.parametrize('name', HDR)
def test_shows_headroom(converted, name):
    _, output, _ = converted[name]
    assert f', HDR {CASES[name]["headroom"]:.1f}×' in output


@pytest.mark.parametrize('name', HDR)
def test_stores_peak_brightness(converted, name):
    # intensity_target: the brightest the photo gets, in nits
    jxl, _, _ = converted[name]
    # at most PQ's 10,000 nits (libjxl rejects much more)
    peak = min(ph.SDR_WHITE_NITS * CASES[name]['peak'], 10000)
    assert ph.jxl_intensity_target(jxl) == pytest.approx(peak, rel=1e-3)


@pytest.mark.parametrize('name', HDR)
def test_hdr_original_may_be_deleted(converted, name):
    _, output, kept = converted[name]
    assert not kept, output


@pytest.mark.parametrize('name', NOT_USED)
def test_gain_map_not_used(converted, name):
    jxl, output, kept = converted[name]
    assert CASES[name]['note'] in output
    assert 'saved as SDR' in output
    assert 'PQ' not in ph.run(['jxlinfo', jxl], check=True).stdout
    # its HDR isn't in the JXL, so the shortcut mustn't offer to delete it;
    # except for a photo not taken by an iPhone, whose gain map jxlbatch
    # doesn't use (the owner's choice)
    assert kept == (not CASES[name].get('delete')), output


@pytest.mark.parametrize('name', EVERY_BUILD)
def test_every_build(encoder, expected, name, tmp_path):
    jxl, output, _ = convert(encoder, [name], tmp_path)[name]
    ours = decoded(jxl, tmp_path / 'ours.ppm')
    assert np.abs(ours - expected[name].astype(np.int64)).max() <= 1, output
