"""
Helpers for the Compress Photos tests: test photos, running photobatch, and
reading what Apple's ImageIO, exiftool and djxl see in the results.
"""

import json
import re
import shutil
import struct
import sys
from pathlib import Path

import hdr_reference
import numpy as np
from PIL import Image, ImageDraw, ImageOps, PngImagePlugin

# SDR white in photobatch's PQ result (nits), and PQ's constants
from hdr_reference import (  # noqa: E402
    PQ_C1,
    PQ_C2,
    PQ_C3,
    PQ_M1,
    PQ_M2,
    SDR_WHITE_NITS,
)

# The helpers every shortcut's tests share, in tests/; re-exported.
_TESTS = str(Path(__file__).resolve().parents[1])
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

import shortcut_helpers  # noqa: E402
from shortcut_helpers import (  # noqa: E402, F401
    CONTROL_FLOW,
    OBJ,
    compile_swift,
    ident,
    inside_if_on,
    need,
    params,
    references,
    render,
    run,
    shell_scripts,
    walk,
)

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
    '<dc:description><rdf:Alt><rdf:li xml:lang="x-default">photobatch test'
    '</rdf:li></rdf:Alt></dc:description></rdf:Description>'
    '</rdf:RDF></x:xmpmeta>'
)


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
    draw.text(
        (width // 10, height * 3 // 4), 'photobatch F', fill=(255, 255, 0)
    )
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
    # (labeled as Apple's by make_photos), upright, turned, mirrored, square
    'heic_hdr': ('heic', ['--p3', '--hdr']),
    'heic_hdr_rot6': ('heic', ['--p3', '--orientation', '6', '--hdr']),
    'heic_hdr_rot3': ('heic', ['--p3', '--orientation', '3', '--hdr']),
    'heic_hdr_mirror2': ('heic', ['--p3', '--orientation', '2', '--hdr']),
    'heic_hdr_square_rot6': ('heic', ['--p3', '--orientation', '6', '--hdr']),
    'heic_hdr_srgb': ('heic', ['--hdr']),
}
# the scene's size for photos not made from the 640x427 one
SIZES = {'heic_hdr_square_rot6': (480, 480)}
HDR_PHOTOS = {
    name for name, (_, options) in PHOTOS.items() if '--hdr' in options
}


def make_photos(folder, make_photo):
    """Writes PHOTOS into folder; returns {name: path}."""
    folder.mkdir(parents=True, exist_ok=True)
    scene(640, 427, seed=1).save(folder / 'scene.png')
    photos = {}
    for name, (ext, options) in PHOTOS.items():
        path = folder / f'{name}.{ext}'
        source = folder / 'scene.png'
        if name in SIZES:
            source = folder / f'scene_{name}.png'
            scene(*SIZES[name], seed=1).save(source)

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
            if '--hdr' in options:
                # labeled like an iPhone's gain map, which ImageIO doesn't do
                with_apple_gain_map_label(path, path)

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
                '-XMP-dc:Description=photobatch test',
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
# Running photobatch


class Encoder:
    """photobatch as the shortcut runs it: in the folder holding the job."""

    def __init__(self, name, command):
        self.name = name
        # a list; "{dir}" is replaced by the job folder (wasm maps it in)
        self.command = [str(c) for c in command]

    def run(self, args, folder):
        cmd = [part.replace('{dir}', str(folder)) for part in self.command] + [
            str(a) for a in args
        ]
        # a batch that hangs fails its test (with its output so far) instead
        # of holding the whole run; the longest, 48 MP under wasmtime, takes
        # about a minute
        return run(cmd, cwd=folder, timeout=600)


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


# EXIF (TIFF data) written by hand, so that a test knows where every value is,
# such as an iPhone's GPS IFD whose bytes must not survive its removal.


def ascii_value(text):
    return (2, len(text.encode()) + 1, text.encode() + b'\0')


def rationals(*pairs, little_endian=False):
    order = '<' if little_endian else '>'
    return (
        5,
        len(pairs),
        b''.join(struct.pack(order + 'II', *p) for p in pairs),
    )


def tiff(ifd0, exif=None, gps=None, little_endian=False):
    """
    EXIF (TIFF) data, big-endian unless ``little_endian``: IFD0 with ``ifd0``'s
    entries, and an Exif and a GPS IFD with theirs if given, each {tag: (type,
    count, value)}. A value longer than 4 bytes follows its IFD. A value may
    instead be ('shares', ifd, tag, offset): the entry then points into that
    entry's value, ``offset`` bytes in (TIFF allows sharing). Written by hand,
    so that the test knows where every value is.
    """
    order = '<' if little_endian else '>'
    ifds = [('ifd0', dict(ifd0))]
    for name, tag, entries in (('exif', 0x8769, exif), ('gps', 0x8825, gps)):
        if entries is not None:
            ifds.append((name, entries))
            ifds[0][1][tag] = (4, 1, name)

    # Where each IFD and each value longer than 4 bytes goes.
    offsets, where, at = {}, {}, 8
    for name, entries in ifds:
        offsets[name] = at
        at += 2 + 12 * len(entries) + 4
        for tag in sorted(entries):
            value = entries[tag][2]
            if isinstance(value, bytes) and len(value) > 4:
                where[name, tag] = at
                at += len(value) + len(value) % 2

    header = b'II\x2a\x00' if little_endian else b'MM\x00\x2a'
    out = bytearray(header + struct.pack(order + 'I', 8))
    for name, entries in ifds:
        table, values = struct.pack(order + 'H', len(entries)), b''
        for tag in sorted(entries):
            kind, count, value = entries[tag]
            if isinstance(value, str):  # a pointer to that IFD
                value = struct.pack(order + 'I', offsets[value])

            if isinstance(value, tuple):  # ('shares', ifd, tag, offset)
                _, other, other_tag, offset = value
                table += struct.pack(
                    order + 'HHII',
                    tag,
                    kind,
                    count,
                    where[other, other_tag] + offset,
                )
            elif len(value) <= 4:
                table += struct.pack(
                    order + 'HHI', tag, kind, count
                ) + value.ljust(4, b'\0')
            else:
                table += struct.pack(
                    order + 'HHII', tag, kind, count, where[name, tag]
                )
                values += value + b'\0' * (len(value) % 2)

        out += table + struct.pack(order + 'I', 0) + values

    return bytes(out)


# An iPhone's GPS IFD (40°42'52.70" N, 73°59'53.71" W, 16.12 m, its
# direction, speed and positioning error): values whose bytes can be looked for.
OLD_GPS = {
    0x0001: ascii_value('N'),
    0x0002: rationals((40, 1), (42, 1), (5270, 100)),
    0x0003: ascii_value('W'),
    0x0004: rationals((73, 1), (59, 1), (5371, 100)),
    0x0005: (1, 1, b'\0'),
    0x0006: rationals((1612147834, 100000000)),
    0x000C: ascii_value('K'),
    0x000D: rationals((304941505, 1000000000)),
    0x0011: rationals((1979783019, 10000000)),
    0x001F: rationals((3345064213, 100000000)),
}
OLD_LAT = 40 + 42 / 60 + 52.70 / 3600
OLD_LON = -(73 + 59 / 60 + 53.71 / 3600)
OLD_BYTES = [
    struct.pack('>II', 5270, 100),
    struct.pack('>II', 5371, 100),
    struct.pack('>II', 1612147834, 100000000),
    struct.pack('>II', 1979783019, 10000000),
]
TIFF_IFD0 = {0x010F: ascii_value('TestMake')}
TIFF_EXIF = {0x9003: ascii_value('2024:05:06 07:08:09')}


def done_lines(folder):
    """jxl_done.txt's lines, split at "|"; [] if there is none."""
    done = folder / 'jxl_done.txt'
    if not done.exists():
        return []

    return [line.split('|') for line in done.read_text().split('\n')]


def read_done(folder):
    """jxl_done.txt as {index: (output file, saved name)}."""
    return {
        int(parts[1]): (folder / parts[0], parts[-1])
        for parts in done_lines(folder)
    }


def convert(encoder, folder, photos, args, dates=None, meta=None):
    """
    Converts photos (a list) the way the shortcuts do: staged (stage), with
    jxl_dates.txt from ``dates`` ({index: date}) and jxl_meta.txt from ``meta``
    (its lines) when given, by ``photobatch <args> jxl_job.txt``. Returns
    (photobatch's output, {index: output file}).
    """
    stage(folder, photos)
    if dates is not None:
        (folder / 'jxl_dates.txt').write_text(
            '\n'.join(f'{i}|{d}' for i, d in dates.items())
        )

    if meta is not None:
        (folder / 'jxl_meta.txt').write_text('\n'.join(meta))

    result = encoder.run([*args, 'jxl_job.txt'], folder)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout, {i: out for i, (out, _) in read_done(folder).items()}


def kept_originals(folder):
    """
    The indexes jxl_done.txt marks "keep": photos whose original must not be
    offered for deletion (its HDR isn't in the JXL).
    """
    return {int(p[1]) for p in done_lines(folder) if p[2] == 'keep'}


# ---------------------------------------------------------------------------
# Inspecting results


def exif_tags(path):
    out = run(
        ['exiftool', '-j', '-G1', '-a', '-n', '-EXIF:all', path], check=True
    ).stdout
    tags = json.loads(out)[0]
    tags.pop('SourceFile', None)
    return tags


def gps_of(path):
    """The GPS IFD's tags (exiftool, numbers as numbers): {name: value}."""
    return {
        k.split(':')[1]: v
        for k, v in exif_tags(path).items()
        if k.startswith('GPS:')
    }


def validate(path):
    """exiftool -validate finds nothing to warn about in the file."""
    out = run(
        ['exiftool', '-validate', '-warning', '-a', '-s', '-s', '-s', path],
        check=True,
    ).stdout
    assert out.splitlines()[0] == 'OK', out


def box(path, kind):
    """A JPEG XL's box of this kind ('Exif', 'xml '), as bytes; b'' if none."""
    data = path.read_bytes()
    return next(
        (data[start:end] for k, start, end in _boxes(data) if k == kind), b''
    )


def exif_box(path):
    return box(path, 'Exif')


def xml_box(path):
    return box(path, 'xml ')


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
    """What photobatch printed for one photo, below its "[i/n] name" line."""
    match = re.search(
        r'^\[\d+/\d+\] ' + re.escape(stem) + r'\n((?:  .*\n?)*)', output, re.M
    )
    assert match, f'no output for {stem}:\n{output}'
    return match.group(1)


def unwrapped(output):
    """photobatch's output as words, since it wraps lines to the window."""
    return ' '.join(output.split())


# photobatch's note below a copy not smaller than its original, and the
# summary line of a batch with one such copy.
NOT_SMALLER = '! the copy is not smaller than the original'
NOT_SMALLER_ONE = (
    '1 copy is not smaller than its original; it was saved all the same.'
)


def not_smaller_note(bytes_in, bytes_out):
    """The note for a copy of bytes_out from an original of bytes_in."""
    diff = bytes_out - bytes_in
    assert diff >= 0
    if diff == 0:
        return f'{NOT_SMALLER}: the same size'

    if diff >= 1e6:  # as photobatch's fmt_bytes
        size = f'{diff / 1e6:.1f} MB'
    elif diff >= 1e3:
        size = f'{diff / 1e3:.0f} KB'
    else:
        size = f'{diff} B'

    return f'{NOT_SMALLER}: larger by {size}'


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


def load_generator(name='build_shortcuts'):
    """
    scripts/<name>.py (build_shortcuts or build_mac_shortcuts) as a module.
    """
    return shortcut_helpers.load_generator(TOOL / 'scripts', name)


def check_photo_dates(actions):
    """
    Checks wf.photo_date's steps in a shortcut and returns where each Format
    Date is: inside a repeat, the Repeat Item's Date Taken (Get Details of
    Images); only if Match Text finds text in it, Format Date of it as ISO 8601
    with the time, then "Repeat Index|date" appended to Dates.
    """
    by_uuid = {params(a).get('UUID'): a for a in actions}
    walked = list(walk(actions))
    match_of = {}  # Match Text UUID -> the output it reads
    for a in actions:
        if ident(a) == 'is.workflow.actions.text.match':
            (read,) = references(params(a)['text'])
            match_of[params(a)['UUID']] = read.get('OutputUUID')

    found = []
    for i, (a, depth) in enumerate(walked):
        if ident(a) != 'is.workflow.actions.format.date':
            continue

        p = params(a)
        assert p['WFDateFormatStyle'] == 'ISO 8601'
        assert p['WFISO8601IncludeTime'] is True
        assert depth == 1
        (taken,) = references(p['WFDate'])
        details = by_uuid[taken['OutputUUID']]
        assert ident(details) == 'is.workflow.actions.properties.images'
        assert params(details)['WFContentItemPropertyName'] == 'Date Taken'
        assert list(references(params(details)['WFInput'])) == [
            {'Type': 'Variable', 'VariableName': 'Repeat Item'}
        ]
        guards = [
            m for m, read in match_of.items() if read == taken['OutputUUID']
        ]
        assert len(guards) == 1
        inside = dict(
            (id(x), yes) for x, yes in inside_if_on(actions, guards[0])
        )
        assert inside[id(a)], 'formatted only when there is a date'
        line, append = actions[i + 1], actions[i + 2]
        assert (
            render(
                params(line)['WFTextActionText'],
                {'Repeat Index': '3', 'Formatted Date': 'D'},
            )
            == '3|D'
        )
        assert ident(append) == 'is.workflow.actions.appendvariable'
        assert params(append)['WFVariableName'] == 'Dates'
        found.append(i)

    return found


def check_photo_locations(actions):
    """
    Checks wf.photo_location's steps in a shortcut and returns where each
    photo's Location is read: inside a repeat, the Repeat Item's Location (Get
    Details of Images); if it has a value, its Latitude and Longitude (Get
    Details of Locations) in "Repeat Index|gps|lat,lon", appended to Meta;
    otherwise, only for a library photo (Is Favorite, through Match Text),
    "Repeat Index|gps|".
    """
    walked = list(walk(actions))
    found = []
    for i, (a, depth) in enumerate(walked):
        p = params(a)
        if not (
            ident(a) == 'is.workflow.actions.properties.images'
            and p['WFContentItemPropertyName'] == 'Location'
        ):
            continue

        assert depth == 1
        assert list(references(p['WFInput'])) == [
            {'Type': 'Variable', 'VariableName': 'Repeat Item'}
        ]
        inside = dict(
            (id(x), yes) for x, yes in inside_if_on(actions, p['UUID'])
        )
        details = {
            params(x)['WFContentItemPropertyName']: x
            for x in actions
            if ident(x) == 'is.workflow.actions.properties.locations'
            and [r.get('OutputUUID') for r in references(params(x)['WFInput'])]
            == [p['UUID']]
        }
        assert set(details) == {'Latitude', 'Longitude'}
        assert all(inside[id(x)] for x in details.values())
        lines = [
            (j, x)
            for j, x in enumerate(actions)
            if ident(x) == 'is.workflow.actions.gettext'
            and '|gps|' in repr(params(x)['WFTextActionText'])
        ]
        rendered = {
            render(
                params(x)['WFTextActionText'],
                {'Repeat Index': '3', 'Latitude': 'LAT', 'Longitude': 'LON'},
            ): j
            for j, x in lines
        }
        assert set(rendered) == {'3|gps|LAT,LON', '3|gps|'}
        for line, j in rendered.items():
            append = actions[j + 1]
            assert ident(append) == 'is.workflow.actions.appendvariable'
            assert params(append)['WFVariableName'] == 'Meta'
            # the coordinates when there is a location, else the empty line
            assert inside[id(actions[j])] == (line != '3|gps|')

        favorite = [
            x
            for x in actions[i:]
            if ident(x) == 'is.workflow.actions.properties.images'
            and params(x)['WFContentItemPropertyName'] == 'Is Favorite'
        ][0]
        guard = next(
            params(x)['UUID']
            for x in actions
            if ident(x) == 'is.workflow.actions.text.match'
            and [r.get('OutputUUID') for r in references(params(x)['text'])]
            == [params(favorite)['UUID']]
        )
        empty = actions[rendered['3|gps|']]
        assert dict((id(x), yes) for x, yes in inside_if_on(actions, guard))[
            id(empty)
        ]
        found.append(i)

    return found


def ashell_commands(actions, values):
    """The command text of each a-Shell Execute Command action."""
    return [
        render(params(a)['command'], values)
        for a in actions
        if ident(a).endswith('.ExecuteCommandIntent')
    ]


# ---------------------------------------------------------------------------
# HDR

# PSNR of HDR images compared as PQ signals (dB): quality 83 gives about 40
# against the exact result; a misaligned gain map gives about 28, the SDR
# photo about 30.
MIN_PQ_PSNR = 35.0


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


def iso_gain_map(path):
    """
    A HEIF's ISO 21496-1 gain map metadata, from its 'tmap' item (see
    hdr_reference.parse_tmap); None if it has none.
    """
    data = Path(path).read_bytes()
    try:
        _, _, children = _meta(data)
    except AssertionError:
        return None

    tmap, _ = _gain_map_items(data, children)
    return (
        None
        if tmap is None
        else hdr_reference.parse_tmap(_item_data(data, children, tmap))
    )


def iso_gain_map_headroom(path):
    """
    The HDR headroom (peak brightness / SDR white) of a HEIF's ISO 21496-1 gain
    map; None if it has none.
    """
    meta = iso_gain_map(path)
    return meta and meta['headroom']


def apple_older_gain_map_headroom(path):
    """
    The headroom of Apple's older gain map (photos taken before iOS 18: no
    'tmap', the headroom in maker notes 33 and 48); None if it has none.
    """
    if iso_gain_map(path):
        return None

    info = json.loads(
        run([
            'exiftool', '-j', '-n', '-AuxiliaryImageType', '-HDRHeadroom',
            '-HDRGain', path,
        ]).stdout or '[{}]'
    )[0]  # fmt: skip
    if 'hdrgainmap' not in str(info.get('AuxiliaryImageType', '')):
        return None

    if 'HDRHeadroom' not in info or 'HDRGain' not in info:
        return None

    return hdr_reference.apple_headroom(info['HDRHeadroom'], info['HDRGain'])


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
    photobatch's HDR result, decoded by djxl: linear Display P3 (as
    apple_hdr_pixels), 1.0 = SDR white.
    """
    # Asked for Display P3 PQ explicitly: a lossy JPEG XL with an ICC profile
    # (Apple's HDR profile) otherwise decodes to linear sRGB, clipping HDR.
    run(['djxl', jxl, ppm, '--color_space=RGB_D65_DCI_Rel_PeQ'], check=True)
    pixels, maximum = read_ppm(ppm)
    return pq_to_linear(pixels / maximum) * 10000 / SDR_WHITE_NITS


def jxl_intensity_target(jxl):
    """
    A JPEG XL's intensity target (its peak brightness, in nits), or None if
    jxlinfo shows none: the default for SDR, 255 nits.
    """
    info = run(['jxlinfo', '-v', jxl])
    need(info.returncode == 0, 'jxlinfo (Homebrew jpeg-xl) is needed')
    match = re.search(r'intensity[_ ]target: ([\d.]+)', info.stdout, re.I)
    return float(match.group(1)) if match else None


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

    start, end = boxes.get('iref', (0, 0))
    id_size = 2 if end and data[start] == 0 else 4
    for kind, s, _ in _boxes(data, start + 4, end) if end else ():
        if kind == 'dimg' and _uint(data, s, id_size) == tmap:
            first = s + id_size + 2  # after the count: the photo, the gain map
            return tmap, _uint(data, first + id_size, id_size)

    return None, None


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
    return _with_icc_tags(icc, {**icc_tags(icc), signature: data})


def _identity_curves(count):
    """``count`` identity 'curv' curves (no entries), as in 'mAB ' tags."""
    return (b'curv' + bytes(8)) * count


# an 'mAB '/'mBA ' matrix: 3x3, then the offsets (s15Fixed16)
_IDENTITY_MATRIX = struct.pack(
    '>12i', *(65536 if i in (0, 4, 8) else 0 for i in range(12))
)


def _identity_clut(precision):
    """A 2x2x2 identity CLUT, 3 channels, ``precision`` bytes per value."""
    top = (1 << (8 * precision)) - 1
    # the first input channel varies slowest
    values = [top * (i >> (2 - c) & 1) for i in range(8) for c in range(3)]
    data = struct.pack(f'>{len(values)}{"BH"[precision - 1]}', *values)
    header = bytes([2, 2, 2] + [0] * 13 + [precision, 0, 0, 0])
    return header + data + bytes(-len(data) % 4)


def _lut_tag(kind, elements):
    """
    An 'mAB ' or 'mBA ' tag with 3 inputs and 3 outputs: ``elements`` ({'A',
    'CLUT', 'M', 'matrix' or 'B': data}) in the order given, the others absent.
    """
    body, offsets = b'', {}
    for name, data in elements.items():
        offsets[name] = 32 + len(body)
        body += data

    names = ('B', 'matrix', 'M', 'CLUT', 'A')
    header = kind.encode('latin-1') + bytes(4) + bytes([3, 3, 0, 0])
    return (
        header + struct.pack('>5I', *(offsets.get(n, 0) for n in names)) + body
    )


def apple_shaped_hdr_profile(icc, curve):
    """
    A copy of PQ profile ``icc`` (with a 'cicp' tag) shaped like Apple's HDR
    profile in iPhone photos (iOS 26): an XYZ connection space, no TRC or
    colorant tags, an 'mAB ' A2B0 without B curves (A curves, a CLUT and a
    matrix without M curves, which skcms, libjxl's color engine in WebAssembly,
    rejects), a full 'mBA ' B2A0, and tone curve ``curve`` in an 'hdgm' tag.
    The transforms are identities: libjxl takes a PQ profile's color from its
    'cicp' tag (Apple's own profile can't be committed).
    """
    tags = icc_tags(icc)
    assert tags['cicp'][8:10] == bytes([12, 16]), 'not a Display P3 PQ profile'
    for signature in ('rTRC', 'gTRC', 'bTRC', 'rXYZ', 'gXYZ', 'bXYZ'):
        tags.pop(signature, None)

    tags['A2B0'] = _lut_tag(
        'mAB ',
        {
            'A': _identity_curves(3),
            'CLUT': _identity_clut(2),
            'matrix': _IDENTITY_MATRIX,
        },
    )
    tags['B2A0'] = _lut_tag(
        'mBA ',
        {
            'B': _identity_curves(3),
            'matrix': _IDENTITY_MATRIX,
            'M': _identity_curves(3),
            'CLUT': _identity_clut(1),
            'A': _identity_curves(3),
        },
    )
    tags['hdgm'] = curve
    out = bytearray(_with_icc_tags(icc, tags))
    out[20:24] = b'XYZ '  # the profile connection space
    return bytes(out)


def _with_icc_tags(icc, tags):
    """A copy of an ICC profile's header with ``tags`` ({signature: data})."""
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
    'tmap' item or gain map item (as photobatch looks for it), or None.
    """
    data = Path(heic).read_bytes()
    _, _, children = _meta(data)
    for item in _gain_map_items(data, children):
        icc = _item_profile(data, children, item)
        if icc and 'hdgm' in icc_tags(icc):
            return icc

    return None


def item_profile(heic, item):
    """The ICC profile of a HEIC's 'tmap' item or 'gain map', or None."""
    data = Path(heic).read_bytes()
    _, _, children = _meta(data)
    tmap, gain_map = _gain_map_items(data, children)
    return _item_profile(data, children, tmap if item == 'tmap' else gain_map)


def with_item_profile(heic, item, icc, out):
    """
    Writes a copy of a HEIC with ICC profile ``icc`` added to its 'tmap' item
    (item='tmap') or its gain map (item='gain map'), as a 'colr' property.
    """
    data = Path(heic).read_bytes()
    tmap, gain_map = _gain_map_items(data, _meta(data)[2])
    target = tmap if item == 'tmap' else gain_map
    _with_property(data, target, _box('colr', b'prof' + icc), out)


APPLE_GAIN_MAP = 'urn:com:apple:photo:2020:aux:hdrgainmap'


def with_apple_gain_map_label(heic, out):
    """
    Writes a copy of a HEIC whose gain map is labeled as Apple's, as in iPhone
    photos: an auxiliary image of the photo ('auxl' reference) of Apple's type
    ('auxC' property). ImageIO doesn't label the gain maps it writes, and
    photobatch uses only labeled ones.
    """
    data = Path(heic).read_bytes()
    _, _, children = _meta(data)
    _, gain_map = _gain_map_items(data, children)
    start, end = next((s, e) for k, s, e in children if k == 'pitm')
    photo = _uint(data, start + 4, 2 if data[start] == 0 else 4)
    auxc = _box('auxC', bytes(4) + APPLE_GAIN_MAP.encode() + b'\0')
    _with_property(data, gain_map, auxc, out, ('auxl', gain_map, photo))


def _with_property(data, target, prop, out, ref=None):
    """
    Writes a copy of a HEIF (``data``) with property box ``prop`` added to item
    ``target``, and item reference ``ref`` ((type, from, to)) if given.
    """
    meta_start, meta_end, children = _meta(data)
    boxes = {k: (s, e) for k, s, e in children}
    assert 'iref' in boxes or not ref, 'no iref box to add to'
    count = sum(
        len(list(_boxes(data, s, e)))
        for k, s, e in _boxes(data, *boxes['iprp'])
        if k == 'ipco'
    )
    iprp = b''
    for kind, s, e in _boxes(data, *boxes['iprp']):
        payload = data[s:e]
        if kind == 'ipco':
            payload += prop
        elif kind == 'ipma':
            payload = _ipma_with(payload, target, count + 1)
            target = None  # added once

        iprp += _box(kind, payload)

    new = {'iprp': iprp}
    if ref:
        start, end = boxes['iref']
        size = 2 if data[start] == 0 else 4  # item IDs, by version
        kind, source, to = ref
        new['iref'] = data[start:end] + _box(
            kind,
            source.to_bytes(size, 'big')
            + (1).to_bytes(2, 'big')
            + to.to_bytes(size, 'big'),
        )

    delta = sum(len(v) - (boxes[k][1] - boxes[k][0]) for k, v in new.items())
    meta = data[meta_start + 8 : meta_start + 12]  # 'meta' version and flags
    for kind, s, e in children:
        if kind in new:
            meta += _box(kind, new[kind])
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


def _iloc_entries(payload):
    """
    'iloc' payload: for each item, {item, method, base (position, size, value),
    extents [(offset position, offset, length)]}.
    """
    version = payload[0]
    offset_size, length_size = payload[4] >> 4, payload[4] & 15
    base_size = payload[5] >> 4
    index_size = payload[5] & 15 if version else 0
    id_size = 4 if version == 2 else 2
    pos = 6 + id_size
    entries = []
    for _ in range(_uint(payload, 6, id_size)):
        item = _uint(payload, pos, id_size)
        pos += id_size
        method = 0
        if version:
            method = _uint(payload, pos, 2) & 15
            pos += 2

        pos += 2  # data_reference_index
        base = (pos, base_size, _uint(payload, pos, base_size))
        pos += base_size
        count = _uint(payload, pos, 2)
        pos += 2
        extents = []
        for _ in range(count):
            pos += index_size
            extents.append((
                pos,
                offset_size,
                _uint(payload, pos, offset_size),
                _uint(payload, pos + offset_size, length_size),
            ))
            pos += offset_size + length_size

        entries.append({
            'item': item,
            'method': method,
            'base': base,
            'extents': extents,
        })

    return entries


def _item_data(data, children, item):
    """An item's data, from the file or from 'idat'."""
    boxes = {k: (s, e) for k, s, e in children}
    start, end = boxes['iloc']
    for entry in _iloc_entries(data[start:end]):
        if entry['item'] == item:
            origin = boxes['idat'][0] if entry['method'] == 1 else 0
            base = entry['base'][2]
            return b''.join(
                data[origin + base + o : origin + base + o + n]
                for _, _, o, n in entry['extents']
            )

    raise AssertionError(f'item {item} has no data')


def _iloc_moved(payload, after, delta):
    """
    'iloc' payload with file offsets at or after ``after`` moved by delta.
    """
    out = bytearray(payload)
    for entry in _iloc_entries(payload):
        if entry['method'] != 0:
            continue

        base_pos, base_size, base = entry['base']
        if base_size and base >= after:
            # the base offset puts every extent after `after`
            out[base_pos : base_pos + base_size] = (base + delta).to_bytes(
                base_size, 'big'
            )
            continue

        for pos, size, offset, _ in entry['extents']:
            if base + offset >= after:
                out[pos : pos + size] = (offset + delta).to_bytes(size, 'big')

    return bytes(out)


def apple_hdr_pixels(helper, path, out):
    """
    Apple's HDR rendering (Core Image, gain map and orientation applied):
    linear Display P3, 1.0 = SDR white.
    """
    return _rendered(helper, [path, out], out)


def apple_sdr_pixels(helper, path, out):
    """
    How an SDR screen shows an image (ImageIO's SDR decoding, orientation
    applied): linear Display P3, 1.0 = SDR white.
    """
    return _rendered(helper, ['--sdr', path, out], out)


def _rendered(helper, args, out):
    run([helper, *args], check=True)
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
