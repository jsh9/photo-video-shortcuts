"""
Every EXIF orientation (1-8) becomes upright pixels, and the orientation tags
are reset to match, so no viewer rotates a photo twice. Lossless (-q 100), so
the result is compared exactly with Pillow's ImageOps.exif_transpose().
"""

import numpy as np
import photo_helpers as ph
import pytest

ORIENTATIONS = range(1, 9)


@pytest.fixture(scope='module')
def oriented(encoder, tmp_path_factory, need_tools):
    """{orientation: (jxl, upright reference)}, converted by each build."""
    folder = tmp_path_factory.mktemp(f'orientation-{encoder.name}')
    sources, references = [], {}
    for o in ORIENTATIONS:
        path, references[o] = ph.orientation_source(o, folder)
        sources.append(path)

    ph.stage(folder, sources)  # job index == orientation
    result = encoder.run(['-q', '100', 'jxl_job.txt'], folder)
    assert result.returncode == 0, result.stdout
    done = ph.read_done(folder)
    return {o: (done[o][0], references[o]) for o in ORIENTATIONS}


@pytest.mark.parametrize('orientation', ORIENTATIONS)
def test_pixels_upright(oriented, orientation, tmp_path):
    jxl, want = oriented[orientation]
    got = ph.decode_jxl(jxl, tmp_path / 'got.png').convert('RGB')
    assert got.size == want.size
    assert np.array_equal(np.asarray(got), np.asarray(want))


@pytest.mark.parametrize('orientation', ORIENTATIONS)
def test_orientation_tags_reset(oriented, orientation):
    jxl, want = oriented[orientation]
    out = ph.run(
        [
            'exiftool',
            '-n',
            '-s3',
            '-f',
            '-EXIF:Orientation',
            '-ExifIFD:ExifImageWidth',
            '-ExifIFD:ExifImageHeight',
            '-XMP-tiff:Orientation',
            jxl,
        ],
        check=True,
    ).stdout.split('\n')[:4]
    assert out == ['1', str(want.size[0]), str(want.size[1]), '1']
