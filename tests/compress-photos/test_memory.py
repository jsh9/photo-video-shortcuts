"""
Memory: iOS stops a-Shell's WebAssembly engine if it uses too much. libjxl's
default turns its low-memory streaming mode off at effort 7 below quality ~70,
which took about 2.7 GB for a 24 MP photo; photobatch keeps streaming on. HDR
photos are computed a region at a time as the encoder reads them, so they take
about as much memory as SDR ones, rather than an extra 16-bit image (0.3 GB at
48 MP). A JPEG XL original is decoded whole, and its decoder freed before the
encoder starts.
"""

import re

import photo_helpers as ph
import pytest
from PIL import Image

LIMIT = 1.5e9  # bytes; streaming needs about 0.5-0.8 GB for 24 MP


def big_heic(folder, make_photo, width, height, options=()):
    tile = ph.scene(1428, 1071, seed=3)
    big = Image.new('RGB', (width, height))
    for x in range(0, width, 1428):
        for y in range(0, height, 1071):
            big.paste(tile, (x, y))

    big.save(folder / 'big.png')
    heic = folder / 'big.heic'
    ph.run([make_photo, folder / 'big.png', heic, *options], check=True)
    if '--hdr' in options:
        ph.with_apple_gain_map_label(heic, heic)  # like an iPhone's

    return heic


def convert(wasm, heic, folder, quality, options=()):
    """photobatch's output and peak memory (bytes) converting heic."""
    ph.stage(folder, [heic])
    command = [p.replace('{dir}', str(folder)) for p in wasm.command]
    result = ph.run(
        [
            '/usr/bin/time',
            '-l',
            *command,
            *options,
            '-q',
            quality,
            'jxl_job.txt',
        ],
        cwd=folder,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    peak = int(
        re.search(r'(\d+)\s+maximum resident set size', result.stderr).group(1)
    )
    return result.stdout, peak


def test_24_mp_photo_at_low_quality(wasm, helpers, tmp_path, need_tools):
    heic = big_heic(tmp_path, helpers['make_photo'], 5712, 4284)
    _, peak = convert(wasm, heic, tmp_path / 'job', '30')
    assert peak < LIMIT, f'peak memory {peak / 1e9:.2f} GB'


@pytest.mark.parametrize(
    'size', [(5712, 4284), (8064, 6048)], ids=['24-mp', '48-mp']
)
def test_hdr_photo(wasm, helpers, tmp_path, need_tools, size):
    heic = big_heic(tmp_path, helpers['make_photo'], *size, ['--p3', '--hdr'])
    output, peak = convert(wasm, heic, tmp_path / 'job', '83')
    assert ', HDR ' in output, output
    assert peak < LIMIT, f'peak memory {peak / 1e9:.2f} GB'
    # about as much as the same photo converted as SDR
    _, sdr_peak = convert(wasm, heic, tmp_path / 'sdr', '83', ['--sdr'])
    assert peak < 1.15 * sdr_peak, (
        f'HDR {peak / 1e9:.2f} GB, SDR {sdr_peak / 1e9:.2f} GB'
    )


@pytest.mark.parametrize(
    'progressive', [False, True], ids=['single-pass', 'progressive']
)
@pytest.mark.parametrize('route', ['jxl', 'heic'])
def test_48_mp_jpeg_xl(wasm, tmp_path, need_tools, progressive, route):
    # JPEG XL input (0.10.0): libjxl's decoder is gone before the encoder
    # starts, so the two don't add up (measured: about 0.55 GB single pass,
    # 0.65 GB progressive)
    tile = ph.scene(1428, 1071, seed=3)
    big = Image.new('RGB', (8064, 6048))
    for x in range(0, 8064, 1428):
        for y in range(0, 6048, 1071):
            big.paste(tile, (x, y))

    big.save(tmp_path / 'big.png')
    jxl = tmp_path / 'big.jxl'
    ph.run(
        ['cjxl', tmp_path / 'big.png', jxl, '-q', '90']
        + (['-p'] if progressive else []),
        check=True,
    )
    options = ['--heic'] if route == 'heic' else []
    output, peak = convert(wasm, jxl, tmp_path / 'job', '70', options)
    assert 'JPEG XL 8064x6048' in output, output
    assert peak < LIMIT, f'peak memory {peak / 1e9:.2f} GB'
