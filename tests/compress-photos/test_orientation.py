"""
Every EXIF orientation (1-8) becomes upright pixels, and the orientation tags
are reset to match, so no viewer rotates a photo twice. Lossless (-q 100), so
the result is compared exactly with Pillow's ImageOps.exif_transpose().

jxlbatch also warns when the result's shape contradicts the original's EXIF
orientation and size; but not for a photo edited in Photos, whose EXIF keeps
the size of the photo before the edit.
"""

import shutil

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


# EXIF pixel sizes for a HEIC that is upright portrait (427x640) once its HEIF
# transforms are applied, with EXIF orientation 1: (size, warned)
EXIF_SIZES = {
    # as Photos saves a cropped photo: the size before the edit
    'edited': ((5712, 4284), False),
    # its own size, but landscape: the orientation contradicts the result
    'contradicting': ((640, 427), True),
}


def test_orientation_check(encoder, photos, tmp_path):
    sources = []
    for name, ((width, height), _) in EXIF_SIZES.items():
        path = tmp_path / f'{name}.heic'
        shutil.copy(photos['heic_rot6'], path)
        ph.run(
            [
                'exiftool',
                '-q',
                '-overwrite_original',
                '-n',
                '-EXIF:Orientation=1',
                f'-ExifIFD:ExifImageWidth={width}',
                f'-ExifIFD:ExifImageHeight={height}',
                path,
            ],
            check=True,
        )
        sources.append(path)

    ph.stage(tmp_path / 'job', sources)
    result = encoder.run(['jxl_job.txt'], tmp_path / 'job')
    assert result.returncode == 0, result.stdout + result.stderr
    for name, (_, warned) in EXIF_SIZES.items():
        output = ph.photo_output(result.stdout, name)
        assert 'HEIF 427x640' in output
        assert ('orientation check' in output) == warned, output
