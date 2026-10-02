"""
Diagnostics for PR #5 (throwaway branch, never merged): saves the HDR test
photos, Apple's HDR renderings of them and our JXLs into diag-out/, which the
workflow commits back to this branch.
"""

import shutil

import photo_helpers as ph

NAMES = ['heic_hdr', 'heic_hdr_rot6', 'heic_hdr_srgb']


def test_save(photos, batch, helpers):
    out = ph.REPO / 'diag-out'
    out.mkdir(exist_ok=True)
    for name in NAMES:
        original, jxl, _ = batch.results[name]
        shutil.copy(original, out / f'{name}.heic')
        shutil.copy(jxl, out / f'{name}.jxl')
        ph.run([helpers['hdr_pixels'], original, out / f'{name}.apple-hdr.f32'],
               check=True)  # fmt: skip
        ph.run([helpers['hdr_pixels'], '--sdr', original,
                out / f'{name}.apple-sdr.f32'], check=True)  # fmt: skip
        info = ph.run(['heif-info', '-d', original]).stdout
        (out / f'{name}.heif-info.txt').write_text(info)
    print('DIAG saved', sorted(p.name for p in out.iterdir()))
