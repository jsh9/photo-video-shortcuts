"""
Helpers for the Compress Photos tests: test photos, running jxlbatch, and
reading what Apple's ImageIO, exiftool and djxl see in the results.
"""

import json
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageOps, PngImagePlugin

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TOOL = REPO / 'shortcuts' / 'compress-photos'

# EXIF tags expected to change: orientation and pixel size follow the upright
# pixels; exiftool reports the thumbnail's file offset, which moves.
EXIF_ALLOWED_DIFF = {
    'IFD0:Orientation',
    'ExifIFD:ExifImageWidth',
    'ExifIFD:ExifImageHeight',
    'IFD1:ThumbnailOffset',
}
# What Photos reads through ImageIO (see imageio_props.swift).
IMAGEIO_FIELDS = [
    'color',
    'taken',
    'offset',
    'subsec',
    'make',
    'model',
    'lens',
    'fnumber',
    'exposure',
    'iso',
    'focal35',
    'lat',
    'lon',
    'alt',
]
MIN_PSNR = 30.0  # dB; quality 83 gives ~40, a wrong rotation or color ~10-20
XMP = (
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/"'
    ' xmlns:tiff="http://ns.adobe.com/tiff/1.0/" tiff:Orientation="{o}">'
    '<dc:description><rdf:Alt><rdf:li xml:lang="x-default">jxlbatch test'
    '</rdf:li></rdf:Alt></dc:description></rdf:Description>'
    '</rdf:RDF></x:xmpmeta>'
)


def need(condition, reason):
    """Skips a test locally when a tool or build is missing; fails in CI."""
    if not condition:
        if os.environ.get('CI'):
            pytest.fail(reason)

        pytest.skip(reason)


def run(cmd, **kw):
    return subprocess.run(
        [str(c) for c in cmd], capture_output=True, text=True, **kw
    )


def compile_swift(source, out):
    need(shutil.which('swiftc'), 'swiftc (Xcode) is needed')
    result = run(['swiftc', '-O', source, '-o', out])
    assert result.returncode == 0, result.stderr
    return out


# ---------------------------------------------------------------------------
# Test photos


def scene(width, height, seed=0):
    """A photo-like, asymmetric test image: gradients, shapes, noise, text."""
    x = np.linspace(0, 1, width)[None, :, None]
    y = np.linspace(0, 1, height)[:, None, None]
    base = np.concatenate(
        [
            0.2 + 0.6 * x + 0 * y,
            0.3 + 0.5 * y + 0 * x,
            0.8 - 0.5 * x * y,
        ],
        axis=2,
    )
    rng = np.random.default_rng(seed)
    pixels = np.clip(base + rng.normal(0, 0.03, base.shape), 0, 1)
    img = Image.fromarray((pixels * 255).astype(np.uint8), 'RGB')
    draw = ImageDraw.Draw(img)
    draw.rectangle(
        [width // 10, height // 8, width // 3, height // 2], fill=(200, 40, 30)
    )
    draw.ellipse(
        [width // 2, height // 3, width * 9 // 10, height * 9 // 10],
        fill=(30, 60, 190),
    )
    draw.text((width // 10, height * 3 // 4), 'jxlbatch F', fill=(255, 255, 0))
    return img


# name: (file type, make_photo options); see make_photos()
PHOTOS = {
    'heic_p3': ('heic', ['--p3']),
    'heic_srgb': ('heic', []),
    'heic_rot6': ('heic', ['--p3', '--orientation', '6']),
    'heic_10bit': ('heic', ['--p3', '--depth16']),
    'jpeg': ('jpg', []),
    'jpeg_rot6': ('jpg', ['--orientation', '6']),
    'jpeg_apple': ('jpg', ['--make', 'Apple', '--model', 'iPhone 17 Pro']),
    'png_alpha': ('png', []),
    # HDR, with an ISO 21496-1 gain map as iPhones write since iOS 18
    'heic_hdr': ('heic', ['--p3', '--hdr']),
    'heic_hdr_rot6': ('heic', ['--p3', '--orientation', '6', '--hdr']),
    'heic_hdr_srgb': ('heic', ['--hdr']),
}
HDR_PHOTOS = {
    name for name, (_, options) in PHOTOS.items() if '--hdr' in options
}


def make_photos(folder, make_photo):
    """Writes PHOTOS into folder; returns {name: path}."""
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / 'scene.png'
    scene(640, 427, seed=1).save(source)
    photos = {}
    for name, (ext, options) in PHOTOS.items():
        path = folder / f'{name}.{ext}'
        if ext == 'png':
            rgba = scene(320, 240, seed=2).convert('RGBA')
            rgba.putalpha(Image.linear_gradient('L').resize(rgba.size))
            exif = Image.Exif()
            exif[0x010F] = 'TestMake'  # Make
            exif[0x8769] = {0x9003: '2024:05:06 07:08:09'}  # DateTimeOriginal
            info = PngImagePlugin.PngInfo()
            info.add_itxt('XML:com.adobe.xmp', XMP.format(o=1))
            rgba.save(path, exif=exif.tobytes(), pnginfo=info)
        else:
            result = run([make_photo, source, path, *options])
            assert result.returncode == 0, result.stderr
            # XMP, as a phone adds it (description and orientation).
            orientation = (
                options[options.index('--orientation') + 1]
                if ('--orientation' in options)
                else '1'
            )
            result = run([
                'exiftool',
                '-q',
                '-overwrite_original',
                '-XMP-dc:Description=jxlbatch test',
                f'-XMP-tiff:Orientation={orientation}',
                '-n',
                path,
            ])
            assert result.returncode == 0, result.stderr

        photos[name] = path

    return photos


def orientation_source(orientation, folder):
    """
    A PNG whose pixels are stored unrotated, with the orientation in EXIF
    (eXIf) and XMP, plus the upright reference image Pillow derives from it.
    """
    width, height = 97, 61  # odd, non-square: every orientation differs
    rng = np.random.default_rng(orientation)
    img = Image.fromarray(
        rng.integers(0, 256, (height, width, 3), dtype=np.uint8), 'RGB'
    )
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif[0x010F] = 'TestMake'
    exif[0x8769] = {
        0xA002: width,  # PixelXDimension
        0xA003: height,  # PixelYDimension
        0x9003: '2024:05:06 07:08:09',  # DateTimeOriginal
    }
    info = PngImagePlugin.PngInfo()
    info.add_itxt('XML:com.adobe.xmp', XMP.format(o=orientation))
    path = folder / f'orientation_{orientation}.png'
    img.save(path, exif=exif.tobytes(), pnginfo=info)
    reference = img.copy()
    reference.info['exif'] = exif.tobytes()
    reference.getexif()[0x0112] = orientation
    return path, ImageOps.exif_transpose(reference)


# ---------------------------------------------------------------------------
# Running jxlbatch


class Encoder:
    """jxlbatch as the shortcut runs it: in the folder holding the job."""

    def __init__(self, name, command):
        self.name = name
        # a list; "{dir}" is replaced by the job folder (wasm maps it in)
        self.command = [str(c) for c in command]

    def run(self, args, folder):
        cmd = [part.replace('{dir}', str(folder)) for part in self.command] + [
            str(a) for a in args
        ]
        return run(cmd, cwd=folder)


def stage(folder, photos):
    """
    Copies photos into folder the way the shortcut does (jxl_in_<i>.orig plus
    an "<i>|<name>" line in jxl_job.txt); returns {index: original}.
    """
    folder.mkdir(parents=True, exist_ok=True)
    staged, lines = {}, []
    for i, photo in enumerate(photos, 1):
        shutil.copy(photo, folder / f'jxl_in_{i}.orig')
        lines.append(f'{i}|{photo.name}')
        staged[i] = photo

    (folder / 'jxl_job.txt').write_text('\n'.join(lines))
    return staged


def read_done(folder):
    """jxl_done.txt as {index: (output file, saved name)}."""
    done = folder / 'jxl_done.txt'
    if not done.exists():
        return {}

    result = {}
    for line in done.read_text().split('\n'):
        file_name, index, name = line.split('|')
        result[int(index)] = (folder / file_name, name)

    return result


# ---------------------------------------------------------------------------
# Inspecting results


def exif_tags(path):
    out = run(
        ['exiftool', '-j', '-G1', '-a', '-n', '-EXIF:all', path], check=True
    ).stdout
    tags = json.loads(out)[0]
    tags.pop('SourceFile', None)
    return tags


def xmp_tags(path):
    out = run(['exiftool', '-j', '-n', '-XMP:all', path], check=True).stdout
    tags = json.loads(out)[0]
    tags.pop('SourceFile', None)
    return tags


def xmp_properties(path):
    """Primary-photo XMP, namespace-qualified with structured values."""
    args = ['exiftool', '-j', '-G1', '-struct', '-n', '-XMP:all']
    if path.suffix.lower() in {'.heic', '.heif'}:
        # HEIF can contain distinct XMP packets for depth/segmentation/gain-map
        # images. Compare the primary photo's packet, including its toolkit
        # attribute, without combining metadata from those auxiliary images.
        packet = run(['exiftool', '-b', '-Main:XMP', path], check=True).stdout
        if not packet:
            return {}

        out = run([*args, '-'], input=packet, check=True).stdout
    else:
        out = run([*args, path], check=True).stdout

    tags = json.loads(out)[0]
    tags.pop('SourceFile', None)
    tags.pop('XMP-xmpNote:HasExtendedXMP', None)
    if 'XMP-tiff:Orientation' in tags:
        tags['XMP-tiff:Orientation'] = 1

    return tags


def photo_output(output, stem):
    """What jxlbatch printed for one photo, below its "[i/n] name" line."""
    match = re.search(
        r'^\[\d+/\d+\] ' + re.escape(stem) + r'\n((?:  .*\n?)*)', output, re.M
    )
    assert match, f'no output for {stem}:\n{output}'
    return match.group(1)


def boxes(path):
    """exiftool's dump of the JPEG XL container boxes."""
    return run(['exiftool', '-v2', path]).stdout


def decode_jxl(path, out_png):
    run(['djxl', path, out_png], check=True)
    return Image.open(out_png)


def apple_render(photo, out_png):
    """Apple's decode of the original (sips), turned upright."""
    run(['sips', '-s', 'format', 'png', photo, '--out', out_png], check=True)
    return ImageOps.exif_transpose(Image.open(out_png))


def psnr(reference, image):
    a = np.asarray(reference.convert('RGB'), dtype=np.float64)
    b = np.asarray(image.convert('RGB'), dtype=np.float64)
    mse = float(np.mean((a - b) ** 2))
    return 99.0 if mse == 0 else 10 * np.log10(255.0**2 / mse)


# ---------------------------------------------------------------------------
# The shortcuts, as scripts/build_shortcuts.py generates them

CONTROL_FLOW = {
    'is.workflow.actions.conditional',
    'is.workflow.actions.repeat.each',
    'is.workflow.actions.repeat.count',
    'is.workflow.actions.choosefrommenu',
}
OBJ = '￼'  # where a variable sits inside a Shortcuts text field


def load_generator():
    """scripts/build_shortcuts.py as a module."""
    import importlib.util

    path = TOOL / 'scripts' / 'build_shortcuts.py'
    spec = importlib.util.spec_from_file_location('build_shortcuts', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ident(action):
    return action['WFWorkflowActionIdentifier']


def params(action):
    return action['WFWorkflowActionParameters']


def references(value):
    """Every variable or action output referenced inside a parameter."""
    if isinstance(value, dict):
        if value.get('Type') in ('ActionOutput', 'Variable'):
            yield value

        for v in value.values():
            yield from references(v)
    elif isinstance(value, list):
        for v in value:
            yield from references(v)


def render(field, values):
    """
    A text parameter as a string: each variable is replaced by
    values[OutputName or VariableName].
    """
    if isinstance(field, str):
        return field

    value = field['Value']
    text = value['string']
    attachments = sorted(
        value.get('attachmentsByRange', {}).items(),
        key=lambda kv: int(kv[0].strip('{}').split(',')[0]),
    )
    for _, ref in attachments:
        key = ref.get('OutputName') or ref.get('VariableName')
        text = text.replace(OBJ, str(values[key]), 1)

    return text


def ashell_commands(actions, values):
    """The command text of each a-Shell Execute Command action."""
    return [
        render(params(a)['command'], values)
        for a in actions
        if ident(a).endswith('.ExecuteCommandIntent')
    ]


# ---------------------------------------------------------------------------
# HDR

SDR_WHITE_NITS = 203  # SDR white in jxlbatch's PQ result
# PSNR of HDR images compared as PQ signals (dB): quality 83 gives about 40
# against the exact result; a misaligned gain map gives about 28, the SDR
# photo about 30.
MIN_PQ_PSNR = 35.0
PQ_M1, PQ_M2 = 2610 / 16384, 2523 / 4096 * 128
PQ_C1, PQ_C2, PQ_C3 = 3424 / 4096, 2413 / 4096 * 32, 2392 / 4096 * 32


def _boxes(data, start=0, end=None):
    """ISOBMFF boxes in data[start:end]: (type, payload start, end)."""
    end = len(data) if end is None else end
    while start + 8 <= end:
        size, kind = struct.unpack('>I4s', data[start : start + 8])
        header = 8
        if size == 1:
            size = struct.unpack('>Q', data[start + 8 : start + 16])[0]
            header = 16
        elif size == 0:
            size = end - start

        if size < header or start + size > end:
            return

        yield kind.decode('latin-1'), start + header, start + size
        start += size


def _uint(data, pos, size):
    return int.from_bytes(data[pos : pos + size], 'big')


def iso_gain_map_headroom(path):
    """
    The HDR headroom (peak brightness / SDR white) of a HEIF's ISO 21496-1 gain
    map, from its 'tmap' item; None if it has none.
    """
    data = Path(path).read_bytes()
    meta = next((b for b in _boxes(data) if b[0] == 'meta'), None)
    if not meta:
        return None

    children = {k: (s, e) for k, s, e in _boxes(data, meta[1] + 4, meta[2])}
    if 'iinf' not in children or 'iloc' not in children:
        return None

    start, end = children['iinf']
    start += 4 + (2 if data[start] == 0 else 4)
    tmap = None
    for kind, s, _ in _boxes(data, start, end):
        if kind == 'infe' and data[s] >= 2:
            id_size = 2 if data[s] == 2 else 4
            item_type = data[s + 4 + id_size + 2 : s + 4 + id_size + 6]
            if item_type == b'tmap':
                tmap = _uint(data, s + 4, id_size)

    if tmap is None:
        return None

    # iloc: where the item's data is (in the file or in 'idat')
    pos, _ = children['iloc']
    version = data[pos]
    offset_size, length_size = data[pos + 4] >> 4, data[pos + 4] & 15
    base_size = data[pos + 5] >> 4
    index_size = data[pos + 5] & 15 if version else 0
    id_size = 4 if version == 2 else 2
    pos += 6
    count = _uint(data, pos, id_size)
    pos += id_size
    for _ in range(count):
        item = _uint(data, pos, id_size)
        pos += id_size
        method = 0
        if version:
            method = _uint(data, pos, 2) & 15
            pos += 2

        pos += 2  # data_reference_index
        base = _uint(data, pos, base_size)
        pos += base_size
        extents = _uint(data, pos, 2)
        pos += 2
        chunks = []
        for _ in range(extents):
            pos += index_size
            offset = _uint(data, pos, offset_size)
            length = _uint(data, pos + offset_size, length_size)
            pos += offset_size + length_size
            chunks.append((base + offset, length))

        if item == tmap:
            origin = children['idat'][0] if method == 1 else 0
            payload = b''.join(
                data[origin + o : origin + o + n] for o, n in chunks
            )
            # version, minimum and writer versions, flags, base headroom,
            # then the alternate headroom (log2) as a fraction
            numerator, denominator = struct.unpack('>II', payload[14:22])
            return 2 ** (numerator / denominator)

    return None


def pq_to_linear(signal):
    """PQ signal (0..1) to luminance, in units of 10,000 nits."""
    p = np.power(np.clip(signal, 0, 1), 1 / PQ_M2)
    return np.power(np.maximum(p - PQ_C1, 0) / (PQ_C2 - PQ_C3 * p), 1 / PQ_M1)


def linear_to_pq(luminance):
    """Luminance, in units of 10,000 nits, to a PQ signal (0..1)."""
    p = np.power(np.clip(luminance, 0, 1), PQ_M1)
    return np.power((PQ_C1 + PQ_C2 * p) / (1 + PQ_C3 * p), PQ_M2)


def read_ppm(path):
    """A binary PPM (8 or 16 bits) as an array of integers."""
    data = Path(path).read_bytes()
    fields = re.match(rb'P6\s+(\d+)\s+(\d+)\s+(\d+)\s', data)
    width, height, maximum = (int(v) for v in fields.groups())
    pixels = np.frombuffer(
        data,
        dtype='>u2' if maximum > 255 else 'u1',
        count=width * height * 3,
        offset=fields.end(),
    )
    return pixels.reshape(height, width, 3), maximum


def jxl_hdr_pixels(jxl, ppm):
    """
    jxlbatch's HDR result, decoded by djxl: linear Display P3 (as
    apple_hdr_pixels), 1.0 = SDR white.
    """
    # Asked for Display P3 PQ explicitly: a lossy JPEG XL with an ICC profile
    # (Apple's HDR profile) otherwise decodes to linear sRGB, clipping HDR.
    run(['djxl', jxl, ppm, '--color_space=RGB_D65_DCI_Rel_PeQ'], check=True)
    pixels, maximum = read_ppm(ppm)
    return pq_to_linear(pixels / maximum) * 10000 / SDR_WHITE_NITS


def jxl_profile(jxl, folder):
    """The ICC profile stored in a JPEG XL (None if it has a color label)."""
    icc = Path(folder) / 'stored.icc'
    icc.unlink(missing_ok=True)
    run(['djxl', jxl, Path(folder) / 'stored.ppm', f'--orig_icc_out={icc}'])
    info = run(['jxlinfo', jxl], check=True).stdout
    return icc.read_bytes() if 'ICC profile' in info else None


# ---------------------------------------------------------------------------
# Apple's HDR color profile in a HEIC: Display P3 + PQ, with the tone curve
# Apple derived from the gain map ('hdgm' tag), on the 'tmap' item or the
# gain map item.


def _box(kind, payload):
    return (
        struct.pack('>I4s', 8 + len(payload), kind.encode('latin-1')) + payload
    )


def _meta(data):
    """The top-level 'meta' box: (box start, end, [(type, start, end)])."""
    start = 0
    for kind, payload, end in _boxes(data):
        if kind == 'meta':
            return start, end, list(_boxes(data, payload + 4, end))

        start = end

    raise AssertionError('no meta box')


def _gain_map_items(data, children):
    """(tmap item ID, gain map item ID) of a HEIF: the tmap's 'dimg' inputs."""
    boxes = {k: (s, e) for k, s, e in children}
    start, end = boxes['iinf']
    start += 4 + (2 if data[start] == 0 else 4)
    tmap = None
    for kind, s, _ in _boxes(data, start, end):
        if kind == 'infe' and data[s] >= 2:
            id_size = 2 if data[s] == 2 else 4
            if data[s + 4 + id_size + 2 : s + 4 + id_size + 6] == b'tmap':
                tmap = _uint(data, s + 4, id_size)

    start, end = boxes['iref']
    id_size = 2 if data[start] == 0 else 4
    for kind, s, _ in _boxes(data, start + 4, end):
        if kind == 'dimg' and _uint(data, s, id_size) == tmap:
            first = s + id_size + 2  # after the count: the photo, the gain map
            return tmap, _uint(data, first + id_size, id_size)

    raise AssertionError('no tmap item with a gain map')


def _ipma_entries(payload):
    """'ipma' payload: (version, flags, [[item, [(essential, index)]]])."""
    version, flags = payload[0], _uint(payload, 1, 3)
    id_size, index_size = (2 if version == 0 else 4), (2 if flags & 1 else 1)
    flag = 0x8000 if flags & 1 else 0x80
    entries, pos = [], 8
    for _ in range(_uint(payload, 4, 4)):
        item, count = _uint(payload, pos, id_size), payload[pos + id_size]
        pos += id_size + 1
        values = [
            _uint(payload, pos + i * index_size, index_size)
            for i in range(count)
        ]
        entries.append([
            item,
            [(bool(v & flag), v & (flag - 1)) for v in values],
        ])
        pos += count * index_size

    return version, flags, entries


def _item_profile(data, children, item):
    """The ICC profile in ``item``'s 'colr' property, or None."""
    boxes = {k: (s, e) for k, s, e in children}
    props, indices = [], []
    for kind, s, e in _boxes(data, *boxes['iprp']):
        if kind == 'ipco':
            props = list(_boxes(data, s, e))
        elif kind == 'ipma':
            for entry, pairs in _ipma_entries(data[s:e])[2]:
                if entry == item:
                    indices += [index for _, index in pairs]

    for index in indices:
        kind, s, e = props[index - 1] if index else ('', 0, 0)
        if kind == 'colr' and data[s : s + 4] in (b'prof', b'rICC'):
            return data[s + 4 : e]

    return None


def icc_tags(icc):
    """An ICC profile's tags: {signature: data}."""
    count = _uint(icc, 128, 4)
    tags = {}
    for i in range(count):
        signature, offset, size = struct.unpack(
            '>4sII', icc[132 + 12 * i : 144 + 12 * i]
        )
        tags[signature.decode('latin-1')] = icc[offset : offset + size]

    return tags


def add_icc_tag(icc, signature, data):
    """A copy of an ICC profile with one more tag."""
    tags = {**icc_tags(icc), signature: data}
    table_end = 132 + 12 * len(tags)
    table, body = struct.pack('>I', len(tags)), b''
    for name, value in tags.items():
        body += b'\0' * (-(table_end + len(body)) % 4)
        table += struct.pack(
            '>4sII', name.encode('latin-1'), table_end + len(body), len(value)
        )
        body += value

    out = bytearray(icc[:128] + table + body)
    out[0:4] = struct.pack('>I', len(out))
    out[84:100] = bytes(16)  # profile ID: none
    return bytes(out)


def hdr_profile(heic):
    """
    Apple's HDR profile in a HEIC: the ICC profile with an 'hdgm' tag on its
    'tmap' item or gain map item (as jxlbatch looks for it), or None.
    """
    data = Path(heic).read_bytes()
    _, _, children = _meta(data)
    for item in _gain_map_items(data, children):
        icc = _item_profile(data, children, item)
        if icc and 'hdgm' in icc_tags(icc):
            return icc

    return None


def with_item_profile(heic, item, icc, out):
    """
    Writes a copy of a HEIC with ICC profile ``icc`` added to its 'tmap' item
    (item='tmap') or its gain map (item='gain map'), as a 'colr' property.
    """
    data = Path(heic).read_bytes()
    meta_start, meta_end, children = _meta(data)
    tmap, gain_map = _gain_map_items(data, children)
    target = tmap if item == 'tmap' else gain_map
    boxes = {k: (s, e) for k, s, e in children}
    count = sum(
        len(list(_boxes(data, s, e)))
        for k, s, e in _boxes(data, *boxes['iprp'])
        if k == 'ipco'
    )
    iprp = b''
    for kind, s, e in _boxes(data, *boxes['iprp']):
        payload = data[s:e]
        if kind == 'ipco':
            payload += _box('colr', b'prof' + icc)
        elif kind == 'ipma':
            payload = _ipma_with(payload, target, count + 1)
            target = None  # added once

        iprp += _box(kind, payload)

    iprp = _box('iprp', iprp)
    old_iprp = next(e - s for k, s, e in children if k == 'iprp')
    delta = len(iprp) - 8 - old_iprp
    meta = data[meta_start + 8 : meta_start + 12]  # 'meta' version and flags
    for kind, s, e in children:
        if kind == 'iprp':
            meta += iprp
        elif kind == 'iloc':
            meta += _box(kind, _iloc_moved(data[s:e], meta_end, delta))
        else:
            meta += _box(kind, data[s:e])

    meta = _box('meta', meta)
    assert len(meta) - (meta_end - meta_start) == delta, 'unexpected box sizes'
    Path(out).write_bytes(data[:meta_start] + meta + data[meta_end:])


def _ipma_with(payload, item, index):
    """'ipma' payload with property ``index`` associated to ``item``."""
    version, flags, entries = _ipma_entries(payload)
    if item is not None:
        entry = next((e for e in entries if e[0] == item), None)
        if entry is None:
            entry = [item, []]
            entries = sorted(entries + [entry])

        entry[1].append((False, index))

    if index > 0x7F:
        flags |= 1  # 16-bit indices

    id_size, wide = (2 if version == 0 else 4), flags & 1
    out = (
        bytes([version])
        + flags.to_bytes(3, 'big')
        + len(entries).to_bytes(4, 'big')
    )
    for entry_item, pairs in entries:
        out += entry_item.to_bytes(id_size, 'big') + bytes([len(pairs)])
        for essential, i in pairs:
            value = (
                (0x8000 if essential else 0) | i
                if wide
                else (0x80 if essential else 0) | i
            )
            out += value.to_bytes(2 if wide else 1, 'big')

    return out


def _iloc_moved(payload, after, delta):
    """
    'iloc' payload with file offsets at or after ``after`` moved by delta.
    """
    out = bytearray(payload)
    version = payload[0]
    offset_size, length_size = payload[4] >> 4, payload[4] & 15
    base_size = payload[5] >> 4
    index_size = payload[5] & 15 if version else 0
    id_size = 4 if version == 2 else 2
    pos = 6
    count = _uint(payload, pos, id_size)
    pos += id_size
    for _ in range(count):
        pos += id_size
        method = 0
        if version:
            method = _uint(payload, pos, 2) & 15
            pos += 2

        pos += 2  # data_reference_index
        base_pos, base = pos, _uint(payload, pos, base_size)
        pos += base_size
        extents = _uint(payload, pos, 2)
        pos += 2
        for k in range(extents):
            pos += index_size
            offset = _uint(payload, pos, offset_size)
            if method == 0 and base + offset >= after:
                if base_size and k == 0:
                    base += delta
                    out[base_pos : base_pos + base_size] = base.to_bytes(
                        base_size, 'big'
                    )
                elif not base_size:
                    out[pos : pos + offset_size] = (offset + delta).to_bytes(
                        offset_size, 'big'
                    )

            pos += offset_size + length_size

    return bytes(out)


def apple_hdr_pixels(helper, path, out):
    """
    Apple's HDR rendering (Core Image, gain map and orientation applied):
    linear Display P3, 1.0 = SDR white.
    """
    run([helper, path, out], check=True)
    width, height = np.fromfile(out, dtype='<i4', count=2)
    pixels = np.fromfile(out, dtype='<f4', offset=8)
    return pixels.reshape(height, width, 4)[..., :3].astype(np.float64)


def brightness(linear, percentiles=(50, 90, 99, 99.9)):
    """Percentiles of each pixel's brightest channel (1.0 = SDR white)."""
    return np.percentile(linear.max(axis=2), percentiles)


def pq_psnr(reference, image):
    """PSNR (dB) of two HDR images (1.0 = SDR white), compared as PQ."""
    scale = SDR_WHITE_NITS / 10000
    a = linear_to_pq(np.maximum(reference, 0) * scale)
    b = linear_to_pq(np.maximum(image, 0) * scale)
    mse = float(np.mean((a - b) ** 2))
    return 99.0 if mse == 0 else 10 * np.log10(1 / mse)
