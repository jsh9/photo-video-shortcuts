"""
Reference HDR math in NumPy (float64), independent of jxlbatch's C code: the
expected results for the test photos in fixtures/hdr/ (see
make_hdr_fixtures.py).

- ISO 21496-1 gain maps, applied at full strength (the alternate rendition).
- Apple's older gain maps (before iOS 18), as Apple documents them in
  "Applying Apple HDR effect to your photos".

Both give linear light with SDR white at 1.0, stored as 16-bit PQ with SDR
white at 203 nits.
"""

import struct

import numpy as np

SDR_WHITE_NITS = 203.0
PQ_M1, PQ_M2 = 2610 / 16384, 2523 / 4096 * 128
PQ_C1, PQ_C2, PQ_C3 = 3424 / 4096, 2413 / 4096 * 32, 2392 / 4096 * 32


def pq_codes(linear):
    """Linear light (1.0 = SDR white) to 16-bit PQ code values."""
    y = np.clip(np.maximum(linear, 0) * SDR_WHITE_NITS / 10000, 0, 1)
    p = np.power(y, PQ_M1)
    signal = np.power((PQ_C1 + PQ_C2 * p) / (1 + PQ_C3 * p), PQ_M2)
    return np.round(signal * 65535).astype(np.uint16)


def srgb_to_linear(v):
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def rec709_to_linear(v):
    """Inverse of the Rec.709 transfer function (Apple's older gain maps)."""
    return np.where(v < 0.081, v / 4.5, ((v + 0.099) / 1.099) ** (1 / 0.45))


def parse_tmap(data):
    """ISO 21496-1 metadata (version 0): {headroom, channels: [3 dicts]}."""
    flags = data[5]
    pos = 6

    def fraction(signed):
        nonlocal pos
        n, d = struct.unpack('>iI' if signed else '>II', data[pos : pos + 8])
        pos += 8
        return n / d

    base, alternate = fraction(False), fraction(False)
    channels = []
    for _ in range(3 if flags & 0x80 else 1):
        channels.append({
            'min': fraction(True),
            'max': fraction(True),
            'gamma': fraction(False),
            'base_offset': fraction(True),
            'alt_offset': fraction(True),
        })

    channels += [channels[0]] * (3 - len(channels))
    return {
        'base_headroom': base,
        'headroom': 2**alternate,
        'channels': channels,
    }


def enlarge(gain_map, width, height, window=None):
    """
    Center-aligned bilinear enlargement of a gain map (h x w or h x w x c,
    float) to width x height, from ``window`` (x0, y0, x1, y1) in gain map
    pixels: the whole gain map by default.
    """
    h, w = gain_map.shape[:2]
    x0, y0, x1, y1 = window or (0, 0, w, h)

    def positions(n_out, start, end, n_in):
        s = start + (np.arange(n_out) + 0.5) * (end - start) / n_out - 0.5
        s = np.clip(s, 0, n_in - 1)
        i0 = np.floor(s).astype(int)
        return i0, np.minimum(i0 + 1, n_in - 1), s - i0

    ya, yb, fy = positions(height, y0, y1, h)
    xa, xb, fx = positions(width, x0, x1, w)
    g = gain_map if gain_map.ndim == 3 else gain_map[..., None]
    fx, fy = fx[None, :, None], fy[:, None, None]
    top = g[ya][:, xa] * (1 - fx) + g[ya][:, xb] * fx
    bottom = g[yb][:, xa] * (1 - fx) + g[yb][:, xb] * fx
    return top * (1 - fy) + bottom * fy


def apply_iso(base, gain_map, meta):
    """
    base: upright SDR photo, sRGB curve, values 0..1 (H x W x 3). gain_map:
    already enlarged to H x W (x 1 or 3), values 0..1.
    """
    linear = srgb_to_linear(base)
    out = np.empty_like(linear)
    for c in range(3):
        m = meta['channels'][c]
        g = gain_map[..., c if gain_map.shape[2] == 3 else 0]
        log2 = m['min'] + (m['max'] - m['min']) * np.power(g, 1 / m['gamma'])
        out[..., c] = (linear[..., c] + m['base_offset']) * np.exp2(log2)
        out[..., c] -= m['alt_offset']

    return out


def iso_peak(meta):
    """The brightest value an ISO gain map can produce (1.0 = SDR white)."""
    return max(
        (1 + m['base_offset']) * 2 ** m['max'] - m['alt_offset']
        for m in meta['channels']
    )


def apple_headroom(maker33, maker48):
    """Apple's older gain maps: headroom from maker note tags 33 and 48."""
    if maker33 < 1.0:
        stops = (
            -20.0 * maker48 + 1.8
            if maker48 <= 0.01
            else -0.101 * maker48 + 1.601
        )
    else:
        stops = (
            -70.0 * maker48 + 3.0
            if maker48 <= 0.01
            else -0.303 * maker48 + 2.303
        )

    return 2 ** max(stops, 0.0)


def apply_apple(base, gain_map, headroom):
    """
    Apple's older gain map: base as in apply_iso; gain_map enlarged, values
    0..1 as stored (Rec.709 curve).
    """
    g = rec709_to_linear(gain_map[..., :1])
    return srgb_to_linear(base) * (1 + (headroom - 1) * g)
