"""
Banding in Apple's SDR rendering of an HDR (PQ) JPEG XL, simulated.

Apple renders a PQ JPEG XL for an SDR screen by shrinking it to the viewing
size and rounding the PQ values to 8 bits (measured on macOS 26: the SDR output
is a function of the 8-bit PQ value, about 2 SDR steps per PQ step). A smooth
gradient, a sky, then shows steps unless grain dithers them, and a lossy encode
removes most of the photo's own grain. See
docs/compress-photos-banding-plan.md.

The score is the share of pixels, in smooth blocks of the picture, whose right
and lower neighbours have the same value: lower is better. The reference is the
original's SDR picture, which Apple shows as it is.
"""

import numpy as np
from PIL import Image

BLOCK = 32
# A block is smooth (textureless) when the high-pass std of the unquantized
# reference is below this, in 8-bit-PQ levels.
SMOOTH_HF = 0.5
# Viewing scales, as fractions of the photo's width: a 4K display showing a
# 24 MP photo fit to the window, and an iPhone's screen (1206 of 5712 px).
MAC_FIT = 3808 / 5712
PHONE_FIT = 1206 / 5712
# Pass: the mean plateau of the smooth blocks within this of the reference's,
# per viewing scale. The Mac margin is what the default grain achieves on a
# sunset sky the user judged acceptable (0.43 against 0.30; see the plan,
# package C); the phone margin is tighter because the coarse grain layer is
# cheap there.
MARGINS = {'mac': 0.20, 'phone': 0.15}


def shrink(a, width):
    """A float32 2-D array shrunk to ``width`` columns (box filter)."""
    a = np.asarray(a, dtype=np.float32)
    if width >= a.shape[1]:
        return a

    height = max(1, round(a.shape[0] * width / a.shape[1]))
    return np.asarray(
        Image.fromarray(a, 'F').resize((width, height), Image.BOX)
    )


def _box(a, r):
    k = np.ones(2 * r + 1) / (2 * r + 1)
    a = np.apply_along_axis(lambda v: np.convolve(v, k, 'same'), 0, a)
    return np.apply_along_axis(lambda v: np.convolve(v, k, 'same'), 1, a)


def _blocks(a):
    h, w = a.shape[0] // BLOCK * BLOCK, a.shape[1] // BLOCK * BLOCK
    return (
        a[:h, :w].reshape(h // BLOCK, BLOCK, w // BLOCK, BLOCK).swapaxes(1, 2)
    )


def smooth_mask(reference):
    """Per block, whether the (unquantized) reference is textureless."""
    hf = reference - _box(reference, 2)
    return _blocks(hf).std(axis=(2, 3)) < SMOOTH_HF


def plateau(quantized):
    """
    Per block, the share of pixels equal to their right and lower neighbours.
    """
    q = np.asarray(quantized)
    flat = (q[:-1, :-1] == q[:-1, 1:]) & (q[:-1, :-1] == q[1:, :-1])
    return _blocks(flat.astype(np.float32)).mean(axis=(2, 3))


def _common(*arrays):
    h = min(a.shape[0] for a in arrays)
    w = min(a.shape[1] for a in arrays)
    return [a[:h, :w] for a in arrays]


def score(pq_output, pq_reference, sdr_reference, scale):
    """
    At a viewing ``scale`` (a fraction of the width): the mean plateau of the
    output through Apple's 8-bit PQ step and the reference's, over the smooth
    blocks.

    ``pq_output`` and ``pq_reference``: one channel (green) of the 16-bit PQ
    output and of the lossless HDR picture, in 8-bit-PQ units (0..255, float).
    ``sdr_reference``: the same channel of the original's SDR picture, 0..255.
    """
    width = max(BLOCK * 2, round(pq_output.shape[1] * scale))
    mask = smooth_mask(shrink(pq_reference, width))
    ours = plateau(np.round(shrink(pq_output, width)))
    theirs = plateau(np.round(shrink(sdr_reference, width)))
    mask, ours, theirs = _common(mask, ours, theirs)
    if not mask.any():
        raise ValueError('no smooth block in the reference')

    return float(ours[mask].mean()), float(theirs[mask].mean())


def passes(pq_output, pq_reference, sdr_reference):
    """Whether the output passes at both viewing scales; with the scores."""
    scales = {'mac': MAC_FIT, 'phone': PHONE_FIT}
    results = {
        name: score(pq_output, pq_reference, sdr_reference, scale)
        for name, scale in scales.items()
    }
    ok = all(
        ours <= theirs + MARGINS[name]
        for name, (ours, theirs) in results.items()
    )
    return ok, results
