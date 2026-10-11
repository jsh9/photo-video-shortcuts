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
    """
    The sky's lossless HDR picture (PQ), its SDR picture (green), and its q83
    output without grain.
    """
    folder = tmp_path_factory.mktemp('sky-reference')
    jxl, _ = convert(wasm, folder, '-q', '100', SKY)
    pq = pq_green(jxl, folder / 'reference.ppm')
    sdr = mk.sky_scene(1024, 768)[..., 1].astype(np.float32)
    plain_folder = tmp_path_factory.mktemp('sky-plain')
    jxl, output = convert(wasm, plain_folder, '-q', '83', *NO_GRAIN, SKY)
    assert 'grain' not in output
    return pq_green(jxl, plain_folder / 'plain.ppm'), pq, sdr


def test_sky_bands_without_grain(references):
    # The problem the grain solves: through Apple's 8-bit PQ step, the sky
    # shows wide steps that its SDR picture doesn't, at both viewing scales.
    plain, pq, sdr = references
    for scale, gap in ((banding.MAC_FIT, 0.4), (banding.PHONE_FIT, 0.1)):
        ours, theirs = banding.score(plain, pq, sdr, scale)
        assert ours > theirs + gap, (scale, ours, theirs)


@pytest.mark.parametrize(
    ('quality', 'grain'),
    [('93', (60, 40)), ('88', (60, 40)), ('83', (60, 40)), ('72', (82, 54))],
)
def test_sky_does_not_band_with_the_tuned_grain(
        wasm, references, tmp_path, quality, grain
):
    # The amounts that were tuned for each quality (docs/compress-photos-
    # banding-plan.md), asked for with --grain, close the gap: checked by
    # their outcome, not only their numbers.
    fine, coarse = grain
    jxl, output = convert(
        wasm,
        tmp_path,
        '-q',
        quality,
        '--grain',
        str(fine),
        '--grain-coarse',
        str(coarse),
        SKY,
    )
    assert re.search(rf'HDR \d+\.\d×, grain {fine}\+{coarse}', output), output
    ok, scores = banding.passes(
        pq_green(jxl, tmp_path / 'out.ppm'), *references
    )
    assert ok, (quality, scores)


@pytest.mark.parametrize('quality', ['93', '83', '72'])
def test_no_grain_by_default(wasm, tmp_path, quality):
    # Since 0.7.0 no grain is added unless asked for: the output is the
    # photo as it is (the same bytes as with the grain turned off).
    a, output = convert(wasm, tmp_path / 'a', '-q', quality, SKY)
    assert 'grain' not in output
    b, _ = convert(wasm, tmp_path / 'b', '-q', quality, *NO_GRAIN, SKY)
    assert a.read_bytes() == b.read_bytes()


def test_grain_options_override_the_curve(wasm, tmp_path):
    a, output = convert(
        wasm,
        tmp_path / 'a',
        '-q',
        '83',
        '--grain',
        '30',
        '--grain-coarse',
        '0',
        SKY,
    )
    assert 'grain 30+0' in output, output
    b, _ = convert(wasm, tmp_path / 'b', '-q', '83', SKY)
    c, _ = convert(wasm, tmp_path / 'c', '-q', '83', *NO_GRAIN, SKY)
    assert a.read_bytes() != b.read_bytes()
    assert a.read_bytes() != c.read_bytes()


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


def test_bright_sky_warning(wasm, tmp_path):
    # An HDR photo with much bright sky (smooth, colored, above SDR white) gets
    # a warning: Photos' rendering of an HDR JPEG XL shows faint pink patches
    # there (README, "pink patches"). The sky fixture's bright part is about
    # 1% of it (the gain map's blob), below the default of 5%.
    _, output = convert(wasm, tmp_path / 'default', '-q', '83', SKY)
    assert 'bright sky' not in output
    _, output = convert(
        wasm, tmp_path / 'low', '-q', '83', '--sky-warn', '0.5', SKY
    )
    said = ' '.join(output.split())
    assert re.search(
        r'! bright sky \(\d+% of the photo\): in Photos, the HDR copy may show faint pink patches there; the HEIC route avoids them \(see README\)',
        said,
    ), said
    assert (
        '1 HDR photo with a bright sky: in Photos, its copy may show faint pink patches there (an Apple issue; see README). The HEIC route avoids them.'
        in said
    )
    _, output = convert(
        wasm, tmp_path / 'mac', '--mac', '-q', '83', '--sky-warn', '0.5', SKY
    )
    assert 'The HEIC route avoids them' in ' '.join(output.split())
    # The HEIC route itself never warns: Photos shows a HEIC with its gain
    # map as it shows the original.
    _, output = convert(
        wasm, tmp_path / 'heic', '--heic', '--sky-warn', '0.5', SKY
    )
    assert 'bright sky' not in output
    _, output = convert(
        wasm, tmp_path / 'off', '-q', '83', '--sky-warn', '0', SKY
    )
    assert 'bright sky' not in output
    _, output = convert(
        wasm, tmp_path / 'sdr', '--sdr', '-q', '83', '--sky-warn', '0.5', SKY
    )
    assert 'bright sky' not in output  # an SDR copy has no patches
    _, output = convert(
        wasm, tmp_path / 'plain', '-q', '83', '--sky-warn', '0.5', SDR_PHOTO
    )
    assert 'bright sky' not in output  # not HDR


@pytest.mark.parametrize(
    'args',
    [
        ['--grain', '-1'],
        ['--grain'],
        ['--grain-coarse', '500'],
        ['--sky-warn', '101'],
        ['--sky-warn', 'abc'],
    ],
)
def test_bad_grain_options(wasm, tmp_path, args):
    ph.stage(tmp_path, [SKY])
    result = wasm.run([*args, 'jxl_job.txt'], tmp_path)
    assert result.returncode == 2
    assert 'usage' in result.stdout
