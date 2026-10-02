"""
Diagnostics for PR #5 (throwaway branch, never merged): prints numbers, every
test passes; read the output (-s).

Why is the rotated HDR test photo (heic_hdr_rot6) 6% brighter than Apple's
rendering at its brightest 0.1% of pixels, while the unrotated one matches?
"""

import numpy as np
import photo_helpers as ph

NAMES = ['heic_hdr', 'heic_hdr_rot6']


def say(*parts):
    print('DIAG', *parts, flush=True)


def lum(pixels):
    return pixels.max(axis=2)


def where(label, img, pct=99.9):
    """Rows and columns of the brightest (pct) pixels."""
    v = lum(img)
    ys, xs = np.nonzero(v >= np.percentile(v, pct))
    say(label, f'top {100 - pct:.1f}%: {len(ys)} px, rows {ys.min()}-{ys.max()} '
        f'(median {int(np.median(ys))}), cols {xs.min()}-{xs.max()} '
        f'(median {int(np.median(xs))}), max {v.max():.3f} at '
        f'{np.unravel_index(v.argmax(), v.shape)}')  # fmt: skip


def compare(label, a, b):
    """b relative to a: brightness ratio across the image and at the edges."""
    if a.shape != b.shape:
        say(label, 'shapes differ', a.shape, b.shape)
        return

    la, lb = lum(a), lum(b)
    ratio = (lb + 1e-3) / (la + 1e-3)
    diff = lb - la
    yx = np.unravel_index(np.abs(diff).argmax(), diff.shape)
    say(label, f'ratio median {np.median(ratio):.4f}, p1 {np.percentile(ratio, 1):.4f}, '
        f'p99 {np.percentile(ratio, 99):.4f}, max |diff| {np.abs(diff).max():.3f} '
        f'at {yx} (a {la[yx]:.3f}, b {lb[yx]:.3f})')  # fmt: skip
    h, w = la.shape
    for name, sl in [('top 3 rows', np.s_[:3, :]), ('bottom 3 rows', np.s_[h - 3 :, :]),
                     ('left 3 cols', np.s_[:, :3]), ('right 3 cols', np.s_[:, w - 3 :]),
                     ('interior', np.s_[8 : h - 8, 8 : w - 8])]:  # fmt: skip
        say(label, f'  {name}: mean ratio {ratio[sl].mean():.4f}, '
            f'mean diff {diff[sl].mean():+.4f}')  # fmt: skip

    say(label, 'percentiles a', np.round(ph.brightness(a), 3).tolist(),
        'b', np.round(ph.brightness(b), 3).tolist())  # fmt: skip


def test_rotation(photos, batch, apple_hdr, tmp_path):
    apple, ours = {}, {}
    for name in NAMES:
        original, jxl, _ = batch.results[name]
        say(name, 'heif-info:', ' | '.join(
            line.strip() for line in ph.run(['heif-info', original]).stdout.splitlines()
            if any(k in line for k in ('image', 'Image', 'aux', 'size', 'x'))
        )[:900])  # fmt: skip
        say(name, 'tmap:', ph.iso_gain_map(original))
        say(name, 'exiftool:', ' | '.join(ph.run(['exiftool', '-a', '-G4', '-s',
            '-ImageWidth', '-ImageHeight', '-Orientation', '-Rotation', original]
        ).stdout.split('\n'))[:600])  # fmt: skip
        apple[name] = apple_hdr(original)
        ours[name] = ph.jxl_hdr_pixels(jxl, tmp_path / f'{name}.ppm')
        say(name, 'shapes: apple', apple[name].shape, 'ours', ours[name].shape)
        where(f'{name} apple', apple[name])
        where(f'{name} ours ', ours[name])
        compare(f'{name} ours vs apple', apple[name], ours[name])

    # the rotated photo, turned back to the unrotated one's orientation
    for k in (1, 3):
        a = np.rot90(apple['heic_hdr_rot6'], k)
        o = np.rot90(ours['heic_hdr_rot6'], k)
        compare(f'rot90 k={k}: apple rot6 vs apple plain', apple['heic_hdr'], a)
        compare(f'rot90 k={k}: ours rot6 vs ours plain', ours['heic_hdr'], o)
