"""
Writes the HDR test photos in fixtures/hdr/ and their expected results.

The photos are tiny HEICs laid out like an iPhone's (primary image, gain map,
ISO 21496-1 'tmap' item or Apple's older gain map, Exif), in the layouts
jxlbatch has to handle: every orientation, crops, grids, 10-bit, RGB and
multichannel gain maps, limited range, other color spaces, and photos whose
gain map can't be used. HEVC is lossless, so decoding gives exactly the values
written here (up to the YCbCr round trip, which the expected results take from
libheif's own decoding).

- fixtures/hdr/<name>.heic: the photos.
- fixtures/hdr/expected.npz: for each HDR photo, the expected 16-bit PQ
  pixels (upright), from hdr_reference.py.
- fixtures/hdr/cases.json: what each photo should give (HDR or a note, the
  headroom, the peak brightness, the color primaries).
- shortcuts/compress-photos/src/selftest_hdr_heic.h: the HDR photo for
  ``jxlbatch --selftest``.
- fixtures/heif/<name>.heic and expected.npz: SDR photos in HEIF layouts
  beyond an iPhone's (transforms in an unusual order, crops reaching past the
  photo, derived 'iden' images of a turned source, transparency with transforms
  of its own), with their expected 8-bit RGB(A) pixels (upright).
  crop_outside_the_photo.heic has none: its crop leaves nothing.

Needs ffmpeg with libx265, and libheif's heif-dec, djxl and cjxl (Homebrew:
ffmpeg, libheif, jpeg-xl). Run from anywhere: python3 make_hdr_fixtures.py The
tests only read the files it writes.
"""

import json
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hdr_reference as ref  # noqa: E402
import photo_helpers as ph  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / 'fixtures' / 'hdr'
LAYOUTS_OUT = HERE / 'fixtures' / 'heif'
SELFTEST_H = (
    HERE.parents[1]
    / 'shortcuts'
    / 'compress-photos'
    / 'src'
    / 'selftest_hdr_heic.h'
)
APPLE_GAIN_MAP = 'urn:com:apple:photo:2020:aux:hdrgainmap'


def run(cmd, **kw):
    return subprocess.run(
        [str(c) for c in cmd], check=True, capture_output=True, **kw
    )


# ---------------------------------------------------------------------------
# Test images


def scene(width, height):
    """An asymmetric test photo without noise (compresses well)."""
    x = np.linspace(0, 1, width)[None, :, None]
    y = np.linspace(0, 1, height)[:, None, None]
    rgb = np.concatenate(
        [0.2 + 0.6 * x + 0 * y, 0.3 + 0.5 * y + 0 * x, 0.8 - 0.5 * x * y],
        axis=2,
    )
    img = Image.fromarray(np.round(rgb * 255).astype(np.uint8), 'RGB')
    draw = ImageDraw.Draw(img)
    draw.rectangle(
        [width // 10, height // 8, width // 3, height // 2], fill=(200, 40, 30)
    )
    draw.ellipse(
        [width // 2, height // 3, width * 9 // 10, height * 9 // 10],
        fill=(30, 60, 190),
    )
    draw.rectangle(
        [width * 3 // 4, 0, width - 1, height // 6], fill=(250, 250, 240)
    )
    return np.asarray(img)


def gain_pattern(width, height):
    """A smooth, asymmetric gain map (0..255): a bright blob, a ramp."""
    x = np.linspace(0, 1, width)[None, :]
    y = np.linspace(0, 1, height)[:, None]
    blob = np.exp(-(((x - 0.25) / 0.2) ** 2 + ((y - 0.3) / 0.25) ** 2))
    g = np.clip(blob + 0.6 * x * (1 - y), 0, 1)
    img = Image.fromarray(np.round(g * 255).astype(np.uint8), 'L')
    return np.asarray(img.filter(ImageFilter.GaussianBlur(1)))


# EXIF orientation: the PIL transpose that turns the upright image into the
# stored one, and libheif's 'irot'/'imir' properties that turn it back.
STORE = {
    2: Image.FLIP_LEFT_RIGHT,
    3: Image.ROTATE_180,
    4: Image.FLIP_TOP_BOTTOM,
    5: Image.TRANSPOSE,
    6: Image.ROTATE_90,
    7: Image.TRANSVERSE,
    8: Image.ROTATE_270,
}
UPRIGHT = {  # stored -> upright, as numpy operations
    1: lambda a: a,
    2: lambda a: a[:, ::-1],
    3: lambda a: a[::-1, ::-1],
    4: lambda a: a[::-1],
    5: lambda a: np.swapaxes(a, 0, 1),
    6: lambda a: np.rot90(a, -1),
    7: lambda a: np.swapaxes(a[::-1, ::-1], 0, 1),
    8: lambda a: np.rot90(a, 1),
}


def stored(array, orientation):
    if orientation == 1:
        return array

    return np.asarray(Image.fromarray(array).transpose(STORE[orientation]))


# ---------------------------------------------------------------------------
# HEVC (lossless x265 through ffmpeg)


def rgb_to_ycbcr(rgb, bits=8, full=True):
    """BT.601 YCbCr planes (4:4:4) for integer RGB of ``bits`` bits."""
    kr, kb = 0.299, 0.114
    m = (1 << bits) - 1
    v = rgb.astype(np.float64) / m
    y = kr * v[..., 0] + (1 - kr - kb) * v[..., 1] + kb * v[..., 2]
    cb = (v[..., 2] - y) / (2 * (1 - kb))
    cr = (v[..., 0] - y) / (2 * (1 - kr))
    if full:
        planes = (
            y * m,
            cb * m + (1 << (bits - 1)),
            cr * m + (1 << (bits - 1)),
        )
    else:
        s = 1 << (bits - 8)
        planes = (
            (16 + 219 * y) * s,
            (128 + 224 * cb) * s,
            (128 + 224 * cr) * s,
        )

    dtype = np.uint16 if bits > 8 else np.uint8
    return [np.clip(np.round(p), 0, m).astype(dtype) for p in planes]


def subsample(plane):
    """4:2:0 chroma by averaging 2x2 blocks (edges repeated)."""
    p = plane.astype(np.float64)
    h, w = (p.shape[0] + 1) // 2 * 2, (p.shape[1] + 1) // 2 * 2
    p = np.pad(p, ((0, h - p.shape[0]), (0, w - p.shape[1])), mode='edge')
    out = (p[0::2, 0::2] + p[1::2, 0::2] + p[0::2, 1::2] + p[1::2, 1::2]) / 4
    return np.round(out).astype(plane.dtype)


def x265(planes, width, height, pix_fmt, full):
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / 'in.yuv', Path(d) / 'out.hevc'
        src.write_bytes(
            b''.join(np.ascontiguousarray(p).tobytes() for p in planes)
        )
        params = [
            'range=' + ('full' if full else 'limited'),
            'colormatrix=smpte170m',
            'info=0',
            'log-level=error',
            'keyint=1',
            'repeat-headers=0',
            'lossless=1',
        ]
        run([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-f', 'rawvideo', '-pix_fmt', pix_fmt, '-s', f'{width}x{height}',
            '-i', src, '-frames:v', '1', '-c:v', 'libx265',
            '-x265-params', ':'.join(params), '-f', 'hevc', out,
        ])  # fmt: skip
        return out.read_bytes()


def nal_units(annexb):
    starts, i = [], 0
    while i < len(annexb) - 3:
        if annexb[i : i + 3] == b'\0\0\1':
            starts.append(i + 3)
            i += 3
        else:
            i += 1

    nals = []
    for k, s in enumerate(starts):
        e = starts[k + 1] - 3 if k + 1 < len(starts) else len(annexb)
        nals.append(annexb[s:e].rstrip(b'\0'))

    return nals


def unescape(nal):
    out, zeros = bytearray(), 0
    for b in nal:
        if zeros >= 2 and b == 3:
            zeros = 0
            continue

        out.append(b)
        zeros = zeros + 1 if b == 0 else 0

    return bytes(out)


class Bits:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def u(self, n):
        v = 0
        for _ in range(n):
            bit = (self.data[self.pos >> 3] >> (7 - (self.pos & 7))) & 1
            v, self.pos = (v << 1) | bit, self.pos + 1

        return v

    def ue(self):
        zeros = 0
        while self.u(1) == 0:
            zeros += 1

        return (1 << zeros) - 1 + self.u(zeros)


def hvcc(nals):
    """The 'hvcC' configuration box payload for an HEVC stream."""
    kinds = {
        k: [n for n in nals if (n[0] >> 1) & 63 == k] for k in (32, 33, 34)
    }
    sps = unescape(kinds[33][0])
    bits = Bits(sps[2:])
    bits.u(4)
    assert bits.u(3) == 0  # one sub-layer
    bits.u(1)
    ptl = sps[3:15]  # general profile_tier_level
    bits.pos += 96
    bits.ue()
    chroma = bits.ue()
    if chroma == 3:
        bits.u(1)

    bits.ue(), bits.ue()
    if bits.u(1):
        for _ in range(4):
            bits.ue()

    luma, chroma_depth = bits.ue(), bits.ue()
    out = bytearray([1]) + ptl[0:12]
    out += struct.pack('>HBBBBHB', 0xF000, 0xFC, 0xFC | chroma, 0xF8 | luma,
                       0xF8 | chroma_depth, 0, 0x0F)  # fmt: skip
    out.append(3)
    for kind in (32, 33, 34):
        out += struct.pack('>BH', 0x80 | kind, len(kinds[kind]))
        for n in kinds[kind]:
            out += struct.pack('>H', len(n)) + n

    return bytes(out)


def hevc_item(planes, width, height, pix_fmt, full):
    nals = nal_units(x265(planes, width, height, pix_fmt, full))
    data = b''.join(
        struct.pack('>I', len(n)) + n for n in nals if (n[0] >> 1) & 63 < 32
    )
    return hvcc(nals), data


# ---------------------------------------------------------------------------
# HEIF boxes


def box(kind, payload):
    return (
        struct.pack('>I4s', 8 + len(payload), kind.encode('latin-1')) + payload
    )


def fullbox(kind, version, flags, payload):
    return box(kind, struct.pack('>I', version << 24 | flags) + payload)


def nclx(primaries, transfer, matrix, full):
    payload = struct.pack(
        '>HHHB', primaries, transfer, matrix, 0x80 if full else 0
    )
    return box('colr', b'nclx' + payload)


def prof(icc):
    return box('colr', b'prof' + icc)


def ispe(w, h):
    return fullbox('ispe', 0, 0, struct.pack('>II', w, h))


def pixi(bits, channels):
    return fullbox('pixi', 0, 0, bytes([channels] + [bits] * channels))


def irot(quarter_turns_ccw):
    return box('irot', bytes([quarter_turns_ccw & 3]))


def imir(axis):
    return box('imir', bytes([axis & 1]))


def clap(width, height, left, top, crop_width, crop_height):
    """A crop to crop_width x crop_height at (left, top), in whole pixels."""
    # offsets of the crop's center from the image's center, in half pixels
    dx = 2 * left + crop_width - width
    dy = 2 * top + crop_height - height
    return box(
        'clap', struct.pack('>8i', crop_width, 1, crop_height, 1, dx, 2, dy, 2)
    )


def auxc(urn):
    return fullbox('auxC', 0, 0, urn.encode() + b'\0')


# EXIF orientation -> libheif transform properties (stored -> upright)
TRANSFORMS = {
    1: [],
    2: [imir(1)],
    3: [irot(2)],
    4: [imir(0)],
    5: [irot(3), imir(1)],
    6: [irot(3)],
    7: [irot(1), imir(1)],
    8: [irot(1)],
}


def tmap_payload(meta, use_base=True, version=0, min_version=0,
                 writer_version=0, den=1 << 20):  # fmt: skip
    flags = (0x80 if len(meta['channels']) == 3 else 0) | (
        0x40 if use_base else 0
    )
    out = struct.pack('>BHHB', version, min_version, writer_version, flags)

    def u(v):
        return struct.pack('>II', round(v * den), den)

    def s(v):
        return struct.pack('>iI', round(v * den), den)

    out += u(meta['base_headroom']) + u(meta['alt_headroom'])
    for c in meta['channels']:
        out += s(c['min']) + s(c['max']) + u(c['gamma'])
        out += s(c['base_offset']) + s(c['alt_offset'])

    return out


def tiff(orientation, maker=None):
    """
    Exif as a big-endian TIFF: Make, Model, Orientation, and Apple's maker
    notes with tags 33 and 48 (signed rationals) when ``maker`` is given.
    """
    make, model = b'Apple\0', b'iPhone 13 mini\0\0'  # even lengths
    count = 4 if maker else 3
    ifd0 = 8
    data = ifd0 + 2 + 12 * count + 4
    entries = [
        struct.pack('>HHII', 0x010F, 2, len(make), data),
        struct.pack('>HHII', 0x0110, 2, len(model), data + len(make)),
        struct.pack('>HHIHH', 0x0112, 3, 1, orientation, 0),
    ]
    tail = make + model
    if maker:
        exif_ifd = data + len(tail)
        entries.append(struct.pack('>HHII', 0x8769, 4, 1, exif_ifd))
        note = b'Apple iOS\0' + b'\0\1' + b'MM'
        values = 14 + 2 + 2 * 12 + 4
        note += struct.pack('>H', 2)
        note += struct.pack('>HHII', 0x0021, 10, 1, values)
        note += struct.pack('>HHII', 0x0030, 10, 1, values + 8)
        note += struct.pack('>I', 0)
        for value in maker:
            note += struct.pack('>ii', round(value * 1_000_000), 1_000_000)

        ifd = struct.pack('>H', 1)
        ifd += struct.pack(
            '>HHII', 0x927C, 7, len(note), exif_ifd + 2 + 12 + 4
        )
        ifd += struct.pack('>I', 0)
        tail += ifd + note

    return (
        b'MM\0*'
        + struct.pack('>IH', ifd0, count)
        + b''.join(entries)
        + b'\0' * 4
        + tail
    )


XMP_GAIN_MAP = (
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF'
    ' xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description rdf:about=""'
    ' xmlns:HDRGainMap="http://ns.apple.com/HDRGainMap/1.0/"'
    ' HDRGainMap:HDRGainMapVersion="65536"/>'
    '</rdf:RDF></x:xmpmeta>'
).encode()


class Heif:
    """A HEIF file: items with properties, references, data in mdat/idat."""

    def __init__(self):
        self.items, self.refs, self.props = [], [], []
        self.primary = None

    def add(
            self, kind, data, props=(), hidden=False, in_idat=False, mime=None
    ):
        ids = []
        for prop, essential in props:
            if prop not in self.props:
                self.props.append(prop)

            ids.append((self.props.index(prop) + 1, essential))

        self.items.append({
            'id': len(self.items) + 1,
            'type': kind,
            'data': data,
            'hidden': hidden,
            'idat': in_idat,
            'mime': mime,
            'props': ids,
        })
        return len(self.items)

    def add_prop(self, prop):
        """A property's index (from 1), adding it if new."""
        if prop not in self.props:
            self.props.append(prop)

        return self.props.index(prop) + 1

    def image(self, planes, width, height, pix_fmt, full, color, extra=(),
              hidden=False, bits=8, tile=None):  # fmt: skip
        """An hvc1 image, or a grid of hvc1 tiles (``tile`` = (w, h))."""
        channels = len(planes)
        if tile is None:
            config, data = hevc_item(planes, width, height, pix_fmt, full)
            props = [(box('hvcC', config), True), (ispe(width, height), False)]
            props += color + [(pixi(bits, channels), False)] + list(extra)
            return self.add('hvc1', data, props, hidden)

        tw, th = tile
        sub = 1 if pix_fmt.startswith('gray') else 2
        tiles = []
        for y in range(0, height, th):
            for x in range(0, width, tw):
                parts = []
                for k, p in enumerate(planes):
                    s = 1 if k == 0 else sub
                    block = p[y // s : (y + th) // s, x // s : (x + tw) // s]
                    pad = (
                        (0, th // s - block.shape[0]),
                        (0, tw // s - block.shape[1]),
                    )
                    parts.append(np.pad(block, pad, mode='edge'))

                config, data = hevc_item(parts, tw, th, pix_fmt, full)
                props = [(box('hvcC', config), True), (ispe(tw, th), False)]
                tiles.append(
                    self.add('hvc1', data, props + color, hidden=True)
                )

        rows, cols = -(-height // th), -(-width // tw)
        grid = struct.pack('>BBBBII', 0, 1, rows - 1, cols - 1, width, height)
        props = color + [
            (ispe(width, height), False),
            (pixi(bits, channels), False),
        ]
        grid_id = self.add(
            'grid', grid, props + list(extra), hidden, in_idat=True
        )
        self.refs.append(('dimg', grid_id, tiles))
        return grid_id

    def write(self, path):
        hdlr = fullbox(
            'hdlr', 0, 0, struct.pack('>I4s', 0, b'pict') + b'\0' * 13
        )
        pitm = fullbox('pitm', 0, 0, struct.pack('>H', self.primary))
        infe = b''
        for it in self.items:
            payload = (
                struct.pack('>HH4s', it['id'], 0, it['type'].encode()) + b'\0'
            )
            if it['mime']:
                payload += it['mime'].encode() + b'\0'

            infe += fullbox('infe', 2, 1 if it['hidden'] else 0, payload)

        iinf = fullbox('iinf', 0, 0, struct.pack('>H', len(self.items)) + infe)
        iref = fullbox('iref', 0, 0, b''.join(
            box(kind, struct.pack('>HH', src, len(dst)) + b''.join(struct.pack('>H', d) for d in dst))
            for kind, src, dst in self.refs
        ))  # fmt: skip
        assoc = b''
        listed = [it for it in self.items if it['props']]
        for it in listed:
            assoc += struct.pack('>HB', it['id'], len(it['props']))
            assoc += bytes((0x80 if e else 0) | i for i, e in it['props'])

        ipma = fullbox('ipma', 0, 0, struct.pack('>I', len(listed)) + assoc)
        iprp = box('iprp', box('ipco', b''.join(self.props)) + ipma)
        idat = box(
            'idat', b''.join(it['data'] for it in self.items if it['idat'])
        )
        ftyp = box('ftyp', b'heic' + b'\0' * 4 + b'mif1heicmiafMiHBtmap')

        def meta(mdat_start):
            entries, in_file, in_idat = b'', mdat_start + 8, 0
            for it in self.items:
                n = len(it['data'])
                if not n:  # no data (e.g. 'iden'): no extent
                    entries += struct.pack('>HHHH', it['id'], 0, 0, 0)
                elif it['idat']:
                    entries += struct.pack(
                        '>HHHHII', it['id'], 1, 0, 1, in_idat, n
                    )
                    in_idat += n
                else:
                    entries += struct.pack(
                        '>HHHHII', it['id'], 0, 0, 1, in_file, n
                    )
                    in_file += n

            iloc = fullbox(
                'iloc',
                1,
                0,
                b'\x44\x00' + struct.pack('>H', len(self.items)) + entries,
            )
            return fullbox(
                'meta', 0, 0, hdlr + pitm + iinf + iref + iprp + idat + iloc
            )

        size = len(meta(0))
        mdat = box(
            'mdat', b''.join(it['data'] for it in self.items if not it['idat'])
        )
        Path(path).write_bytes(ftyp + meta(len(ftyp) + size) + mdat)


# ---------------------------------------------------------------------------
# Profiles (from libjxl, so no third-party profile is committed)


def libjxl_profile(space):
    """
    The ICC profile libjxl writes for a color space, e.g. RGB_D65_DCI_Rel_SRG.
    """
    with tempfile.TemporaryDirectory() as d:
        ppm, jxl, icc = Path(d) / 'a.ppm', Path(d) / 'a.jxl', Path(d) / 'a.icc'
        ppm.write_bytes(b'P6\n2 2\n255\n' + bytes(12))
        run(['cjxl', ppm, jxl, '-d', '0', '-x', f'color_space={space}'])
        run(['djxl', jxl, Path(d) / 'b.ppm', f'--icc_out={icc}'])
        return icc.read_bytes()


# ---------------------------------------------------------------------------
# Test photos

ISO_META = {
    'base_headroom': 0.0,
    'alt_headroom': 1.8037,
    'channels': [{'min': -0.000866, 'max': 1.803711, 'gamma': 0.737793,
                  'base_offset': 1e-5, 'alt_offset': 1e-5}],
}  # fmt: skip
MULTI_META = {
    'base_headroom': 0.0,
    'alt_headroom': 2.0,
    'channels': [
        {'min': 0, 'max': 2, 'gamma': 1, 'base_offset': 1 / 64, 'alt_offset': 1 / 64},
        {'min': 0, 'max': 1, 'gamma': 0.5, 'base_offset': 1 / 64, 'alt_offset': 1 / 64},
        {'min': -0.5, 'max': 1.5, 'gamma': 2, 'base_offset': 0, 'alt_offset': 0},
    ],
}  # fmt: skip
APPLE_MAKER = (0.8, 0.02)  # tags 33 and 48: 1.599 stops, headroom 3.03
W, H = 64, 48  # the upright photo


class Case:
    """
    One test photo. ``o``: EXIF orientation (stored as libheif transforms on
    the primary). ``gain_map_turned``: the gain map carries the same transforms
    (else it is stored like the primary, without them, as Apple does).
    ``crop``: (left, top, width, height) of a 'clap' crop of the stored
    primary, applied before its rotation. ``gain_map_cropped``: the gain map
    carries that crop too (but not the rotation), as ImageIO writes a full-size
    gain map. ``iden_source_turns``: the primary is a derived 'iden' image of
    the coded photo, which is turned by that many quarter turns itself.
    ``apple``: the gain map is labeled as Apple's (an auxiliary image of type
    APPLE_GAIN_MAP), as in iPhone photos; jxlbatch uses only those. ``delete``:
    a gain map that isn't used, but the original may still be deleted.
    """

    def __init__(self, name, o=1, gain_map_turned=False, crop=None, size=(W, H),
                 gain_size=None, color='p3', bits=8, tile=None, full_range=True,
                 rgb_gain_map=False, meta=ISO_META, tmap=True, apple=True,
                 maker=None, xmp=False, note=None, tmap_kw=None,
                 tmap_data=None, gain_map_cropped=False, iden_source_turns=0,
                 delete=False):  # fmt: skip
        self.__dict__.update(locals())
        del self.__dict__['self']


CASES = [Case(f'o{o}', o=o) for o in range(1, 9)]
CASES += [Case(f'o{o}_turned', o=o, gain_map_turned=True) for o in (2, 5, 6)]
CASES += [
    Case('grid_o6', o=6, tile=(32, 32)),
    Case('odd_size_o6', o=6, size=(66, 50), crop=(0, 0, 49, 65), tile=(32, 32)),
    Case('crop', size=(64, 48), crop=(4, 3, 56, 42)),
    Case('crop_square', size=(64, 48), crop=(8, 0, 48, 48)),
    Case('crop_o6', o=6, size=(64, 48), crop=(3, 4, 42, 56)),
    # a full-size gain map with the photo's crop but not its rotation, as
    # ImageIO writes (an odd height stored one row taller)
    Case('cropped_gain_map', crop=(0, 0, 64, 47), gain_size=(64, 48),
         gain_map_cropped=True),
    Case('cropped_gain_map_o6', o=6, size=(48, 64), crop=(0, 0, 64, 47),
         gain_size=(48, 64), gain_map_cropped=True),
    # a crop reaching past the photo's edges: cut to the photo, as libheif does
    Case('crop_past_the_edge', size=(64, 48), crop=(10, 10, 60, 44)),
    Case('full_size_gain_map', gain_size=(64, 48)),
    Case('quarter_gain_map', size=(128, 96), gain_size=(32, 24)),
    Case('limited_range_gain_map', full_range=False),
    Case('rgb_gain_map', rgb_gain_map=True),
    Case('multichannel', meta=MULTI_META, rgb_gain_map=True),
    Case('srgb', color='srgb'),
    Case('unspecified_color', color='unspecified'),
    Case('ten_bit', bits=10),
    # a gain map 9 stops brighter: above PQ's 10,000 nits
    Case('high_headroom', meta={
        **ISO_META, 'alt_headroom': 9.0,
        'channels': [{**ISO_META['channels'][0], 'max': 9.0}]}),
    # the most jxlbatch accepts: 16 stops
    Case('headroom_16_stops', meta={
        **ISO_META, 'alt_headroom': 16.0,
        'channels': [{**ISO_META['channels'][0], 'max': 16.0}]}),
    # Apple's older gain map (before iOS 18): maker notes, no 'tmap'
    Case('apple_older', tmap=False, maker=APPLE_MAKER, xmp=True),
    Case('apple_older_o6', o=6, tmap=False, maker=APPLE_MAKER, xmp=True),
    Case('apple_older_no_maker_notes', tmap=False, xmp=True,
         note="Apple's older gain map without its headroom"),
    # gain maps that can't be used (the photo stays SDR, with a note)
    Case('not_used_color', color='rec2020', note='unsupported color profile'),
    Case('not_used_other_color_space', tmap_kw={'use_base': False},
         note='gain map in another color space'),
    Case('not_used_version', tmap_kw={'version': 1},
         note='unsupported tone map version'),
    Case('not_used_min_version', tmap_kw={'min_version': 1, 'writer_version': 1},
         note='unsupported gain map version'),
    Case('not_used_darker', meta={**ISO_META, 'alt_headroom': 0.0},
         note="the gain map doesn't make the photo brighter"),
    Case('not_used_shape', gain_size=(32, 32),
         note="the gain map doesn't match the photo"),
    Case('not_used_malformed', tmap_data=b'\0\0\0\0\0',
         note='malformed gain map metadata'),
    # more than 16 stops brighter: not a real photo's
    Case('not_used_absurd_headroom', meta={
        **ISO_META, 'alt_headroom': 130.0,
        'channels': [{**ISO_META['channels'][0], 'max': 130.0}]},
         note='malformed gain map metadata'),
    # the photo as a derived image of a turned source: its gain map's
    # alignment isn't defined
    Case('not_used_derived_photo', iden_source_turns=2,
         note='unsupported image layout'),
    # not labeled as Apple's, e.g. written by ImageIO in an app: how it lines
    # up with a turned photo isn't certain, so it isn't used, but the original
    # may be deleted
    Case('not_iphone_o3', o=3, apple=False,
         note='not an iPhone camera photo', delete=True),
    Case('not_iphone_o6', o=6, apple=False,
         note='not an iPhone camera photo', delete=True),
    # whatever else is wrong with it
    Case('not_iphone_malformed', apple=False, tmap_data=b'\0\0\0\0\0',
         note='not an iPhone camera photo', delete=True),
]  # fmt: skip

COLOR = {
    # (nclx primaries, transfer), libjxl color space of the profile (or none)
    'p3': ((12, 13), 'RGB_D65_DCI_Rel_SRG'),
    'srgb': ((1, 13), None),
    'unspecified': ((2, 2), None),
    'rec2020': ((9, 13), None),
}


def crop_box(case):
    """
    The crop (left, top, width, height) of the stored photo, cut to the photo
    as libheif does: the whole photo if there is none.
    """
    sw, sh = case.size if case.o in (1, 2, 3, 4) else case.size[::-1]
    left, top, cw, ch = case.crop or (0, 0, sw, sh)
    return left, top, min(cw, sw - left), min(ch, sh - top)


def upright_size(case):
    """The photo's upright size, after its crop."""
    cw, ch = crop_box(case)[2:]
    return (cw, ch) if case.o in (1, 2, 3, 4) else (ch, cw)


def write_photo(case, path, profiles, transforms=True):
    """Writes the HEIC; returns (stored gain map, stored-to-upright fn)."""
    sw, sh = case.size if case.o in (1, 2, 3, 4) else case.size[::-1]
    # the upright photo, uncropped, then stored
    upright = scene(*case.size)
    base = stored(upright, case.o)
    gw, gh = case.gain_size or (case.size[0] // 2, case.size[1] // 2)
    gain_upright = gain_pattern(gw, gh)
    if case.rgb_gain_map:
        g = gain_upright.astype(np.float64)
        gain_upright = np.stack([g, 255 - g, g * 0.5], axis=2).astype(np.uint8)

    gain = stored(gain_upright, case.o)
    h = Heif()
    full = True
    (primaries, transfer), space = COLOR[case.color]
    color = [(nclx(primaries, transfer, 6, full), True)]
    if space:
        color = [(prof(profiles[space]), True)] + color

    if case.bits == 10:
        planes = rgb_to_ycbcr(base.astype(np.uint16) * 4 + 1, 10, full)
        pix_fmt = 'yuv420p10le'
    else:
        planes = rgb_to_ycbcr(base, 8, full)
        pix_fmt = 'yuv420p'

    planes = [planes[0], subsample(planes[1]), subsample(planes[2])]
    write_transforms = transforms
    transforms = TRANSFORMS[case.o]
    if case.crop:
        left, top, cw, ch = case.crop
        transforms = [clap(sw, sh, left, top, cw, ch)] + transforms

    # without them: the same coded photo, as stored (for expected())
    tf = [(t, True) for t in transforms] if write_transforms else []
    primary = h.image(planes, sw, sh, pix_fmt, full, color, tf, bits=case.bits,
                      tile=case.tile, hidden=bool(case.iden_source_turns))  # fmt: skip
    if case.iden_source_turns:
        # the photo as a derived image of a turned source
        turns = case.iden_source_turns
        h.items[primary - 1]['props'].append((h.add_prop(irot(turns)), True))
        iw, ih = (sw, sh) if turns % 2 == 0 else (sh, sw)
        source, primary = primary, h.add('iden', b'', [(ispe(iw, ih), False)])
        h.refs.append(('dimg', primary, [source]))

    h.primary = primary
    # the gain map
    gh_s, gw_s = gain.shape[:2]
    if gain.ndim == 2:
        values = (
            gain
            if case.full_range
            else np.round(16 + gain * 219 / 255).astype(np.uint8)
        )
        gplanes, gfmt = [values], 'gray'
        gcolor = [(nclx(2, 2, 2, case.full_range), True)]
    else:
        y, cb, cr = rgb_to_ycbcr(gain, 8, True)
        gplanes, gfmt = [y, subsample(cb), subsample(cr)], 'yuv420p'
        gcolor = [(nclx(2, 2, 6, True), True)]

    extra = [(auxc(APPLE_GAIN_MAP), True)] if case.apple else []
    if case.gain_map_turned:
        extra += tf[len(transforms) - len(TRANSFORMS[case.o]) :]

    if case.gain_map_cropped:  # the crop only (full-size gain maps)
        assert (gw_s, gh_s) == (sw, sh), 'a cropped gain map must be full size'
        extra += [(clap(sw, sh, *case.crop), True)]

    gain_id = h.image(gplanes, gw_s, gh_s, gfmt, case.full_range or gain.ndim == 3,
                      gcolor, extra, hidden=True)  # fmt: skip
    if case.apple:
        h.refs.append(('auxl', gain_id, [primary]))

    if case.tmap:
        payload = case.tmap_data or tmap_payload(
            case.meta, **(case.tmap_kw or {})
        )
        tmap = h.add(
            'tmap', payload, [(ispe(*upright_size(case)), False)], in_idat=True
        )
        h.refs.append(('dimg', tmap, [primary, gain_id]))

    if case.xmp:
        xmp = h.add(
            'mime', XMP_GAIN_MAP, hidden=True, mime='application/rdf+xml'
        )
        h.refs.append(('cdsc', xmp, [gain_id]))

    exif = h.add('Exif', b'\0\0\0\0' + tiff(case.o, case.maker), hidden=True)
    h.refs.append(('cdsc', exif, [primary]))
    h.write(path)
    return gain, gplanes


def decoded_gain_map(case, gain, gplanes):
    """The gain map's values as jxlbatch decodes them: 0..1, stored layout."""
    if gain.ndim == 2:
        g = gplanes[0].astype(np.float64)
        return g / 255 if case.full_range else np.clip((g - 16) / 219, 0, 1)

    # RGB: through libheif, as jxlbatch decodes it
    with tempfile.TemporaryDirectory() as d:
        h = Heif()
        h.primary = h.image(gplanes, gain.shape[1], gain.shape[0], 'yuv420p', True,
                            [(nclx(2, 2, 6, True), True)])  # fmt: skip
        h.write(Path(d) / 'g.heic')
        run(['heif-dec', Path(d) / 'g.heic', Path(d) / 'g.png'])
        return np.asarray(Image.open(Path(d) / 'g.png').convert('RGB')) / 255


def decoded_base(heic):
    """The upright SDR photo as libheif decodes it: 0..1."""
    with tempfile.TemporaryDirectory() as d:
        png = Path(d) / 'base.png'
        run(['heif-dec', heic, png])
        return np.asarray(Image.open(png).convert('RGB')) / 255


def decoded_base_16(heic):
    """A 10-bit photo as libheif decodes it: 0..1 (heif-dec's 16-bit PNG)."""
    with tempfile.TemporaryDirectory() as d:
        png = Path(d) / 'base.png'
        run(['heif-dec', heic, png])
        data = png.read_bytes()
        pos, idat, header = 8, b'', None
        while pos < len(data):
            n, kind = struct.unpack('>I4s', data[pos : pos + 8])
            body = data[pos + 8 : pos + 8 + n]
            if kind == b'IHDR':
                header = struct.unpack('>IIBBBBB', body)
            elif kind == b'IDAT':
                idat += body

            pos += 12 + n

        width, height, depth, ctype = header[:4]
        assert depth == 16 and ctype == 2, header
        raw = zlib.decompress(idat)
        stride = width * 6
        rows, prev = [], bytearray(stride)
        for y in range(height):
            f = raw[y * (stride + 1)]
            line = bytearray(
                raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)]
            )
            for i in range(stride):
                a = line[i - 6] if i >= 6 else 0
                b, c = prev[i], prev[i - 6] if i >= 6 else 0
                if f == 1:
                    line[i] = (line[i] + a) & 255
                elif f == 2:
                    line[i] = (line[i] + b) & 255
                elif f == 3:
                    line[i] = (line[i] + (a + b) // 2) & 255
                elif f == 4:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pred = a if pa <= pb and pa <= pc else b if pb <= pc else c
                    line[i] = (line[i] + pred) & 255

            rows.append(bytes(line))
            prev = line

        values = np.frombuffer(b''.join(rows), '>u2').reshape(height, width, 3)
        # heif-dec shifts the 10-bit values left by 6
        assert not (values % 64).any()
        return (values >> 6).astype(np.float64) / 1023


def upright_base(case, profiles):
    """
    The upright SDR photo, 0..1: decoded as stored (libheif, from a copy
    without the crop and rotation), then cropped and turned in RGB, as jxlbatch
    does. (libheif crops and turns before converting to RGB, which shifts the
    colors when a 4:2:0 photo is cropped at an odd offset.)
    """
    with tempfile.TemporaryDirectory() as d:
        stored = Path(d) / 'stored.heic'
        write_photo(case, stored, profiles, transforms=False)
        base = (
            decoded_base_16(stored)
            if case.bits == 10
            else decoded_base(stored)
        )

    left, top, cw, ch = crop_box(case)
    return UPRIGHT[case.o](base[top : top + ch, left : left + cw])


def expected(case, heic, gain, gplanes, profiles):
    """(expected 16-bit PQ pixels, headroom, peak) for an HDR test photo."""
    base = upright_base(case, profiles)
    g = decoded_gain_map(case, gain, gplanes)
    gh, gw = g.shape[:2]
    sw, sh = case.size if case.o in (1, 2, 3, 4) else case.size[::-1]
    left, top, cw, ch = crop_box(case)
    window = (
        left * gw / sw,
        top * gh / sh,
        (left + cw) * gw / sw,
        (top + ch) * gh / sh,
    )
    enlarged = UPRIGHT[case.o](ref.enlarge(g, cw, ch, window))

    if case.tmap:
        meta = ref.parse_tmap(tmap_payload(case.meta))
        linear = ref.apply_iso(base, enlarged, meta)
        return ref.pq_codes(linear), meta['headroom'], ref.iso_peak(meta)

    headroom = ref.apple_headroom(*case.maker)
    return (
        ref.pq_codes(ref.apply_apple(base, enlarged, headroom)),
        headroom,
        headroom,
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    profiles = {
        space: libjxl_profile(space) for _, space in COLOR.values() if space
    }
    arrays, cases = {}, {}
    for case in CASES:
        heic = OUT / f'{case.name}.heic'
        gain, gplanes = write_photo(case, heic, profiles)
        primaries = 'srgb' if case.color in ('srgb', 'unspecified') else 'p3'
        info = {'primaries': primaries}
        if case.note:
            info['note'] = case.note
            if case.delete:
                info['delete'] = True
        else:
            pixels, headroom, peak = expected(
                case, heic, gain, gplanes, profiles
            )
            arrays[case.name] = pixels
            info.update(headroom=headroom, peak=peak)

        cases[case.name] = info
        print(f'{case.name:32s} {heic.stat().st_size:6d} bytes')

    np.savez_compressed(OUT / 'expected.npz', **arrays)
    (OUT / 'cases.json').write_text(
        json.dumps(cases, indent=2, sort_keys=True) + '\n'
    )
    write_selftest(profiles)
    write_layouts()


# ---------------------------------------------------------------------------
# SDR photos in unusual HEIF layouts (fixtures/heif/)


def coded(h, rgb, extra=(), hidden=False):
    """A lossless sRGB hvc1 image of ``rgb`` (stored), with ``extra`` props."""
    planes = rgb_to_ycbcr(rgb, 8, True)
    planes = [planes[0], subsample(planes[1]), subsample(planes[2])]
    color = [(nclx(1, 13, 6, True), True)]
    return h.image(planes, rgb.shape[1], rgb.shape[0], 'yuv420p', True, color,
                   [(p, True) for p in extra], hidden=hidden)  # fmt: skip


def libheif_rgb(heic):
    """
    A photo as libheif decodes it, transforms applied: 8-bit RGB, or RGBA with
    transparency.
    """
    with tempfile.TemporaryDirectory() as d:
        png = Path(d) / 'out.png'
        run(['heif-dec', heic, png])
        img = Image.open(png)
        return np.asarray(img.convert('RGBA' if 'A' in img.mode else 'RGB'))


ALPHA = 'urn:mpeg:mpegB:cicp:systems:auxiliary:alpha'


def alpha_image(h, photo, extra=()):
    """A transparency (alpha) image for ``photo``, with ``extra`` props."""
    x = np.linspace(0, 1, 64)[None, :]
    y = np.linspace(0, 1, 48)[:, None]
    alpha = np.round(255 * (0.25 + 0.5 * x * (1 - 0.5 * y))).astype(np.uint8)
    alpha[4:20, 6:30] = 255  # asymmetric: shows a turn
    item = h.image([alpha], 64, 48, 'gray', True, [(nclx(2, 2, 2, True), True)],
                   [(auxc(ALPHA), True)] + [(p, True) for p in extra],
                   hidden=True)  # fmt: skip
    h.refs.append(('auxl', item, [photo]))


def stored_rgb(rgb):
    """``rgb`` as libheif decodes it from a plain coded image: 8-bit RGB."""
    with tempfile.TemporaryDirectory() as d:
        h = Heif()
        h.primary = coded(h, rgb)
        h.write(Path(d) / 'stored.heic')
        return libheif_rgb(Path(d) / 'stored.heic')


def write_layouts():
    """
    The photos in fixtures/heif/ and their expected pixels: for a coded photo,
    decoded as stored, then turned and cropped in RGB in property order (as
    Apple shows it); for a derived photo, libheif's own decoding (jxlbatch
    leaves those transforms to libheif, as before 0.2.0).
    """
    LAYOUTS_OUT.mkdir(parents=True, exist_ok=True)
    rgb = scene(64, 48)
    raw = stored_rgb(rgb)
    arrays = {}

    def save(name, h, want=None):
        path = LAYOUTS_OUT / f'{name}.heic'
        h.write(path)
        arrays[name] = libheif_rgb(path) if want is None else want
        print(f'{name:32s} {path.stat().st_size:6d} bytes')
        return arrays[name]

    # a crop reaching past the photo's edges: cut to the photo, as libheif does
    h = Heif()
    h.primary = coded(h, rgb, [clap(64, 48, 10, 10, 60, 44)])
    save('crop_past_the_edge', h, raw[10:48, 10:64])

    # a crop that leaves nothing (no expected pixels: libheif refuses it)
    h = Heif()
    h.primary = coded(h, rgb, [clap(64, 48, 70, 0, 10, 10)])
    h.write(LAYOUTS_OUT / 'crop_outside_the_photo.heic')

    # turned, then cropped at an odd offset (crop listed after the rotation)
    h = Heif()
    h.primary = coded(h, rgb, [irot(1), clap(48, 64, 3, 5, 40, 52)])
    save('rotate_then_crop', h, np.rot90(raw, 1)[5:57, 3:43])

    # mirrored, then cropped
    h = Heif()
    h.primary = coded(h, rgb, [imir(1), clap(64, 48, 5, 3, 52, 40)])
    save('mirror_then_crop', h, raw[:, ::-1][3:43, 5:57])

    # a derived 'iden' image of a source turned 180 degrees
    h = Heif()
    source = coded(h, rgb, [irot(2)], hidden=True)
    h.primary = h.add('iden', b'', [(ispe(64, 48), False)])
    h.refs.append(('dimg', h.primary, [source]))
    want = save('iden_rotated_source', h)
    assert np.array_equal(want, np.rot90(raw, 2)), 'libheif should turn it'

    # an 'iden' with its own crop, of a source turned 90 degrees
    h = Heif()
    source = coded(h, rgb, [irot(1)], hidden=True)
    h.primary = h.add('iden', b'', [(ispe(48, 64), False),
                                    (clap(48, 64, 3, 5, 40, 52), True)])  # fmt: skip
    h.refs.append(('dimg', h.primary, [source]))
    save('iden_cropped_rotated_source', h)

    # transparency turned 180 degrees, the photo not
    h = Heif()
    h.primary = coded(h, rgb)
    alpha_image(h, h.primary, [irot(2)])
    save('alpha_rotated_independently', h)

    # photo and transparency both turned 180 degrees, as writers do
    h = Heif()
    h.primary = coded(h, rgb, [irot(2)])
    alpha_image(h, h.primary, [irot(2)])
    want = save('alpha_rotated_with_photo', h)
    assert want.shape == (48, 64, 4), want.shape

    np.savez_compressed(LAYOUTS_OUT / 'expected.npz', **arrays)


def write_selftest(profiles):
    """The --selftest HDR photo, with Apple-like HDR profile, as a C array."""
    case = Case('selftest', size=(64, 48))
    with tempfile.TemporaryDirectory() as d:
        heic = Path(d) / 'selftest.heic'
        gain, gplanes = write_photo(case, heic, profiles)
        pixels, headroom, _ = expected(case, heic, gain, gplanes, profiles)
        # Apple's HDR profile: Display P3 with PQ, plus a placeholder curve
        hdr = ph.add_icc_tag(libjxl_profile('RGB_D65_DCI_Rel_PeQ'), 'hdgm',
                             b'hdgm' + bytes(4) + bytes(range(32)))  # fmt: skip
        data = with_tmap_profile(heic, hdr, Path(d) / 'with_profile.heic')

    points = [(8, 8), (16, 14), (40, 24), (56, 40)]
    lines = [
        '// Generated by tests/compress-photos/make_hdr_fixtures.py: a 64x48 HDR',
        '// HEIC with an ISO 21496-1 gain map and an HDR profile (Display P3 + PQ',
        "// with a placeholder 'hdgm' tone curve) on its tmap item, for",
        '// jxlbatch --selftest. Do not edit.',
        '#ifndef JXLBATCH_SELFTEST_HDR_HEIC_H',
        '#define JXLBATCH_SELFTEST_HDR_HEIC_H',
        '',
        f'static const double kSelftestHdrHeadroom = {headroom:.6f};',
        f'static const unsigned kSelftestHdrProfileSize = {len(hdr)};',
        '// expected PQ code values {x, y, r, g, b}',
        'static const unsigned kSelftestHdrPixels[][5] = {',
    ]
    for x, y in points:
        r, g, b = (int(v) for v in pixels[y, x])
        lines.append(f'    {{{x}, {y}, {r}, {g}, {b}}},')

    lines += ['};', 'static const unsigned char kSelftestHdrHeic[] = {']
    for i in range(0, len(data), 16):
        lines.append(
            '    ' + ', '.join(f'0x{b:02x}' for b in data[i : i + 16]) + ','
        )

    lines += ['};', '', '#endif', '']
    SELFTEST_H.write_text('\n'.join(lines))
    print(f'{SELFTEST_H.name}: {len(data)} bytes')


def with_tmap_profile(heic, icc, out):
    """The test photo's bytes, with ICC profile ``icc`` on its tmap item."""
    ph.with_item_profile(heic, 'tmap', icc, out)
    return out.read_bytes()


if __name__ == '__main__':
    os.chdir(HERE)
    main()
