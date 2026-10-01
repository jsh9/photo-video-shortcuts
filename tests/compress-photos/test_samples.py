"""
Optional: your own photos in tests/samples/compress-photos/ (not committed;
real iPhone photos have things test photos can't, such as HEIC tiles, Apple
maker notes and HDR gain maps). Skipped when there are none.
"""

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
def test_sample(sample_batch, imageio, sample, tmp_path):
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

    props = imageio(sample, jxl)
    a, b = props[str(sample)], props[str(jxl)]
    differ = [f for f in ph.IMAGEIO_FIELDS if a.get(f) != b.get(f)]
    assert not differ, {f: (a.get(f), b.get(f)) for f in differ}
    assert b['orientation'] == 1
    assert b['upright'] == a['upright']

    reference = ph.apple_render(sample, tmp_path / 'apple.png')
    decoded = ph.decode_jxl(jxl, tmp_path / 'jxl.png')
    assert decoded.size == reference.size
    assert ph.psnr(reference, decoded) >= ph.MIN_PSNR
