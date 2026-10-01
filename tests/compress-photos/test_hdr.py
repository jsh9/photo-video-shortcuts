"""
HDR photos: a HEIC with an ISO 21496-1 gain map, as iPhones write since iOS 18,
becomes a JPEG XL holding the HDR rendition itself, as 16-bit PQ with SDR white
at 203 nits (Photos shows PQ as HDR but ignores JPEG XL gain maps). The result
is compared with Apple's own HDR rendering of the original. Photos without a
gain map stay SDR.
"""

import re

import numpy as np
import photo_helpers as ph
import pytest

HDR = sorted(ph.HDR_PHOTOS)
SDR = sorted(set(ph.PHOTOS) - ph.HDR_PHOTOS)


def jxlinfo(jxl):
    info = ph.run(['jxlinfo', '-v', jxl])
    ph.need(info.returncode == 0, 'jxlinfo (Homebrew jpeg-xl) is needed')
    return info.stdout


@pytest.fixture(scope='module')
def renderings(batch, apple_hdr, tmp_path_factory):
    """{name: (Apple's HDR rendering of the original, jxlbatch's result)}"""
    folder = tmp_path_factory.mktemp('hdr')
    result = {}
    for name in HDR:
        original, jxl, _ = batch.results[name]
        assert jxl is not None, f'{name} was not converted:\n{batch.output}'
        ours = ph.jxl_hdr_pixels(jxl, folder / f'{name}.ppm')
        result[name] = (apple_hdr(original), ours)

    return result


@pytest.mark.parametrize('name', HDR)
def test_test_photo_has_an_iso_gain_map(photos, name):
    assert ph.iso_gain_map_headroom(photos[name]), (
        'make_photo wrote no ISO gain map (tmap item)'
    )


@pytest.mark.parametrize('name', HDR)
def test_output_shows_headroom(batch, name):
    original, _, _ = batch.results[name]
    headroom = ph.iso_gain_map_headroom(original)
    # e.g. "HEIF 427x640, HDR 4.0×"
    assert f', HDR {headroom:.1f}×' in ph.photo_output(
        batch.output, original.stem
    )


@pytest.mark.parametrize('name', HDR)
def test_stored_as_16_bit_pq(batch, name):
    _, jxl, _ = batch.results[name]
    # jxlinfo 0.11 prints "P3 primaries, PQ transfer function", later
    # versions "Primaries: P3" and "Transfer function: PQ".
    info = jxlinfo(jxl).lower()
    primaries = 'p3' if '--p3' in ph.PHOTOS[name][1] else 'srgb'
    assert '16-bit rgb' in info
    assert (
        f'{primaries} primaries' in info or f'primaries: {primaries}' in info
    )
    assert 'pq transfer function' in info or 'transfer function: pq' in info
    assert re.search(r'intensity[_ ]target: 10000\.', info)


@pytest.mark.parametrize('name', HDR)
def test_brightness_matches_apple(renderings, name):
    apple, ours = renderings[name]
    assert ours.shape == apple.shape  # upright, like Apple's rendering
    want = ph.brightness(apple)
    assert want[-1] > 1.5, 'the test photo should be brighter than SDR'
    np.testing.assert_allclose(ph.brightness(ours), want, rtol=0.05, atol=0.01)


@pytest.mark.parametrize('name', HDR)
def test_pixels_match_apple(renderings, name):
    apple, ours = renderings[name]
    assert ours.shape == apple.shape
    assert ph.pq_psnr(apple, ours) >= ph.MIN_PQ_PSNR


@pytest.mark.parametrize('name', HDR)
def test_apple_shows_the_jxl_as_hdr(batch, renderings, apple_hdr, name):
    # What Photos shows: Apple's reading of the PQ JPEG XL, with SDR white at
    # 203 nits, looks like its HDR rendering of the original.
    _, jxl, _ = batch.results[name]
    apple, _ = renderings[name]
    shown = apple_hdr(jxl)
    assert shown.shape == apple.shape
    np.testing.assert_allclose(
        ph.brightness(shown), ph.brightness(apple), rtol=0.1, atol=0.02
    )


def test_every_build(encoder, photos, renderings, tmp_path):
    name = 'heic_hdr_rot6'
    ph.stage(tmp_path, [photos[name]])
    result = encoder.run(['jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert ', HDR ' in result.stdout
    ours = ph.jxl_hdr_pixels(tmp_path / 'jxl_out_1.jxl', tmp_path / 'hdr.ppm')
    apple, _ = renderings[name]
    assert ours.shape == apple.shape
    assert ph.pq_psnr(apple, ours) >= ph.MIN_PQ_PSNR


@pytest.mark.parametrize('name', SDR)
def test_photos_without_gain_map_stay_sdr(batch, name):
    original, jxl, _ = batch.results[name]
    assert 'HDR' not in ph.photo_output(batch.output, original.stem)
    assert 'PQ' not in jxlinfo(jxl)
