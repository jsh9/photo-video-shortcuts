"""
Helpers for the Compress Photos tests: test photos, running jxlbatch, and
reading what Apple's ImageIO, exiftool and djxl see in the results.
"""

import json
import os
import shutil
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
