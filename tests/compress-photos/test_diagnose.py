"""
Diagnostics for PR #5 (throwaway branch, never merged): prints numbers for
two failing tests. Every test passes; read the output (-s).

1. Size: HDR vs --sdr JXL sizes, and the gain map's noise.
2. SDR look: how Apple shows each version of an HDR photo on an SDR screen.
"""

import glob
import traceback

import numpy as np
import photo_helpers as ph
import pytest
from PIL import Image
from test_memory import big_heic

HDR = ['heic_hdr', 'heic_hdr_rot6', 'heic_hdr_srgb']
QUALITIES = ['50', '70', '83', '95']


def say(*parts):
    print('DIAG', *parts, flush=True)


def jxl_size(wasm, heic, folder, quality, options=()):
    ph.stage(folder, [heic])
    result = wasm.run([*options, '-q', quality, 'jxl_job.txt'], folder)
    assert result.returncode == 0, result.stdout
    return (folder / 'jxl_out_1.jxl').stat().st_size, result.stdout


def gain_map_noise(heic, folder):
    """The gain map's size and high-pass standard deviation (0..255)."""
    folder.mkdir(parents=True, exist_ok=True)
    result = ph.run(['heif-dec', '--with-aux', heic, folder / 'base.png'])
    found = sorted(glob.glob(str(folder / '*aux*'))) or sorted(
        glob.glob(str(folder / '*.png'))
    )
    out = []
    for path in found:
        img = np.asarray(Image.open(path).convert('L'), dtype=np.float64)
        blur = (
            img[:-2, :-2] + img[:-2, 1:-1] + img[:-2, 2:]
            + img[1:-1, :-2] + img[1:-1, 1:-1] + img[1:-1, 2:]
            + img[2:, :-2] + img[2:, 1:-1] + img[2:, 2:]
        ) / 9  # fmt: skip
        noise = (img[1:-1, 1:-1] - blur).std()
        out.append(
            f'{path.split("/")[-1]} {img.shape[1]}x{img.shape[0]} '
            f'mean {img.mean():.1f} high-pass std {noise:.2f}'
        )

    return out or [f'no images: {result.stdout} {result.stderr}']


@pytest.mark.parametrize('name', HDR)
def test_size(photos, wasm, name, tmp_path):
    heic = photos[name]
    for line in gain_map_noise(heic, tmp_path / 'aux'):
        say(name, 'image:', line)

    for q in QUALITIES:
        hdr, _ = jxl_size(wasm, heic, tmp_path / f'hdr{q}', q)
        sdr, _ = jxl_size(wasm, heic, tmp_path / f'sdr{q}', q, ['--sdr'])
        say(name, f'q{q}', f'HDR {hdr} SDR {sdr} ratio {hdr / sdr:.3f}')


def test_size_24_mp(helpers, wasm, tmp_path):
    heic = big_heic(
        tmp_path, helpers['make_photo'], 5712, 4284, ['--p3', '--hdr']
    )
    for line in gain_map_noise(heic, tmp_path / 'aux'):
        say('24mp', 'image:', line)

    hdr, _ = jxl_size(wasm, heic, tmp_path / 'hdr', '83')
    sdr, _ = jxl_size(wasm, heic, tmp_path / 'sdr', '83', ['--sdr'])
    say('24mp', 'q83', f'HDR {hdr} SDR {sdr} ratio {hdr / sdr:.3f}')


def percentiles(label, pixels):
    say('SDR look', label, np.round(ph.brightness(pixels), 3).tolist())


@pytest.mark.parametrize('name', HDR)
def test_sdr_look(photos, batch, helpers, wasm, apple_sdr, apple_hdr, name,
                  tmp_path):  # fmt: skip
    helper = helpers['hdr_pixels']
    original = photos[name]
    say('SDR look', '----', name)
    try:
        percentiles('A original HEIC (SDR decoding)', apple_sdr(original))
        percentiles('original HEIC, Apple HDR (Core Image)', apple_hdr(original))
    except Exception:
        say('SDR look', 'A failed', traceback.format_exc())

    derived = ph.apple_hdr_profile(helper, original, tmp_path / 'hdr.icc')
    if derived:
        tags = ph.icc_tags(derived)
        desc = tags.get('desc', b'')[:120]
        say('SDR look', 'derived profile', len(derived), 'bytes; tags',
            sorted(tags), '; hdgm', len(tags.get('hdgm', b'')), 'bytes;',
            'desc', desc)  # fmt: skip
    else:
        say('SDR look', 'no derived profile')

    for ext in ('png', 'heic'):
        out = tmp_path / f'apple_hdr.{ext}'
        result = ph.run([helper, '--hdr-file', original, out])
        say('SDR look', f'B file ({ext}):', result.stdout.strip(),
            result.stderr.strip())  # fmt: skip
        if result.returncode == 0 and out.exists():
            try:
                percentiles(f'B Apple HDR decoding as {ext}', apple_sdr(out))
                percentiles(f'B {ext}, Apple HDR (Core Image)', apple_hdr(out))
            except Exception:
                say('SDR look', f'B {ext} failed', traceback.format_exc())

    _, plain, _ = batch.results[name]
    try:
        percentiles('D our JXL without curve', apple_sdr(plain))
        percentiles('our JXL, Apple HDR (Core Image)', apple_hdr(plain))
    except Exception:
        say('SDR look', 'D failed', traceback.format_exc())

    if not derived or 'hdgm' not in ph.icc_tags(derived):
        return

    ph.run(['djxl', plain, tmp_path / 'p.ppm', '--color_space=RGB_D65_DCI_Rel_PeQ',
            f'--icc_out={tmp_path / "p3_pq.icc"}'], check=True)  # fmt: skip
    icc = ph.add_icc_tag(
        (tmp_path / 'p3_pq.icc').read_bytes(), 'hdgm', ph.icc_tags(derived)['hdgm']
    )
    heic = tmp_path / 'with_curve.heic'
    ph.with_item_profile(original, 'tmap', icc, heic)
    ph.stage(tmp_path / 'job', [heic])
    result = wasm.run(['jxl_job.txt'], tmp_path / 'job')
    jxl = tmp_path / 'job' / 'jxl_out_1.jxl'
    say('SDR look', 'C output', ' '.join(result.stdout.split())[-160:])
    try:
        percentiles('C our JXL with the curve', apple_sdr(jxl))
    except Exception:
        say('SDR look', 'C failed', traceback.format_exc())

    # the curve on Apple's own HDR pixels, in a lossless PQ JXL: isolates
    # the curve from jxlbatch's pixels
    hdr_png = tmp_path / 'apple_hdr.png'
    if hdr_png.exists():
        say('SDR look', 'B png stored as', ph.run(['exiftool', '-s',
            '-ProfileDescription', '-BitDepth', hdr_png]).stdout.strip())  # fmt: skip
