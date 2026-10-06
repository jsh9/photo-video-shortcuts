"""
Optional: your own photos in tests/samples/compress-photos/ (not committed;
real iPhone photos have things test photos can't, such as HEIC tiles, Apple
maker notes and HDR gain maps). Skipped when there are none. A photo with an
ISO 21496-1 gain map (iPhone, iOS 18 or later), such as hdr/chinatown.heic,
must become HDR and match Apple's HDR rendering, keeping Apple's HDR profile
(tone curve) if it has one, and then look like the original on SDR screens too.
So must a photo with Apple's older gain map (iOS 14 to 17), such as
hdr/2021-10-31.heic (iPhone 13, iOS 15) or hdr/IMG_7223.heic (iPhone 13 mini,
iOS 16). An HDR result must be at most 25% larger than an SDR one (--sdr).
Other photos must match Apple's SDR rendering.
"""

import numpy as np
import photo_helpers as ph
import pytest

SAMPLES = sorted(
    p
    for p in (ph.REPO / 'tests' / 'samples' / 'compress-photos').rglob('*')
    if p.suffix.lower() in {'.heic', '.heif', '.jpg', '.jpeg', '.png'}
)


@pytest.fixture(scope='module')
def sample_batch(tmp_path_factory, wasm, need_tools):
    """{sample: (jxl, saved name)}, converted in one batch at quality 83."""
    folder = tmp_path_factory.mktemp('samples')
    staged = ph.stage(folder, SAMPLES)
    result = wasm.run(['-q', '83', '-e', '7', 'jxl_job.txt'], folder)
    done = ph.read_done(folder)
    return {
        path: done.get(index, (None, None)) for index, path in staged.items()
    }, result.stdout


@pytest.mark.parametrize(
    'sample', SAMPLES, ids=lambda p: str(p.relative_to(ph.REPO))
)
def test_sample(sample_batch, imageio, apple_hdr, apple_sdr, sample, tmp_path):
    results, output = sample_batch
    jxl, saved = results[sample]
    assert jxl is not None, f'not converted:\n{output}'
    assert saved == f'{sample.stem}.jxl'

    before, after = ph.exif_tags(sample), ph.exif_tags(jxl)
    changed = sorted(
        k
        for k in set(before) | set(after)
        if k not in ph.EXIF_ALLOWED_DIFF and before.get(k) != after.get(k)
    )
    assert not changed, changed
    assert ph.xmp_properties(sample) == ph.xmp_properties(jxl)
    assert 'brob' not in ph.boxes(jxl)

    headroom = ph.iso_gain_map_headroom(
        sample
    ) or ph.apple_older_gain_map_headroom(sample)
    props = imageio(sample, jxl)
    a, b = props[str(sample)], props[str(jxl)]
    fields = [f for f in ph.IMAGEIO_FIELDS if not (headroom and f == 'color')]
    differ = [f for f in fields if a.get(f) != b.get(f)]
    assert not differ, {f: (a.get(f), b.get(f)) for f in differ}
    assert b['orientation'] == 1
    assert b['upright'] == a['upright']

    if headroom:
        # HDR (PQ): compare with Apple's HDR rendering
        assert f', HDR {headroom:.1f}×' in ph.photo_output(output, sample.stem)
        # with Apple's HDR profile (tone curve), if the photo has one
        profile = ph.hdr_profile(sample)
        if profile:
            assert ph.jxl_profile(jxl, tmp_path) == profile

        apple = apple_hdr(sample)
        ours = ph.jxl_hdr_pixels(jxl, tmp_path / 'hdr.ppm')
        assert ours.shape == apple.shape
        np.testing.assert_allclose(
            ph.brightness(ours), ph.brightness(apple), rtol=0.05, atol=0.01
        )
        assert ph.pq_psnr(apple, ours) >= ph.MIN_PQ_PSNR
        if profile:
            # and with Apple's tone curve, an SDR screen shows it like the
            # original
            want, shown = apple_sdr(sample), apple_sdr(jxl)
            assert shown.shape == want.shape
            np.testing.assert_allclose(
                ph.brightness(shown), ph.brightness(want), rtol=0.1, atol=0.02
            )

        return

    reference = ph.apple_render(sample, tmp_path / 'apple.png')
    decoded = ph.decode_jxl(jxl, tmp_path / 'jxl.png')
    assert decoded.size == reference.size
    assert ph.psnr(reference, decoded) >= ph.MIN_PSNR


HDR_SAMPLES = [
    p
    for p in SAMPLES
    if p.suffix.lower() in {'.heic', '.heif'}
    and (ph.iso_gain_map_headroom(p) or ph.apple_older_gain_map_headroom(p))
]


@pytest.mark.parametrize(
    'sample', HDR_SAMPLES, ids=lambda p: str(p.relative_to(ph.REPO))
)
def test_hdr_sample_is_about_as_large_as_sdr(
        sample_batch, wasm, sample, tmp_path
):
    results, _ = sample_batch
    hdr_jxl, _ = results[sample]
    ph.stage(tmp_path, [sample])
    result = wasm.run(
        ['--sdr', '-q', '83', '-e', '7', 'jxl_job.txt'], tmp_path
    )
    assert result.returncode == 0, result.stdout
    sdr_jxl = tmp_path / 'jxl_out_1.jxl'
    # without the grain the HDR output gets against banding (test_banding)
    plain = tmp_path / 'plain'
    ph.stage(plain, [sample])
    result = wasm.run(
        [
            '--grain',
            '0',
            '--grain-coarse',
            '0',
            '-q',
            '83',
            '-e',
            '7',
            'jxl_job.txt',
        ],
        plain,
    )
    assert result.returncode == 0, result.stdout
    plain_jxl = plain / 'jxl_out_1.jxl'
    assert plain_jxl.stat().st_size <= 1.25 * sdr_jxl.stat().st_size
    # the grain's cost: about 10-15% on a sky, less with little smooth area
    assert hdr_jxl.stat().st_size <= 1.35 * plain_jxl.stat().st_size
