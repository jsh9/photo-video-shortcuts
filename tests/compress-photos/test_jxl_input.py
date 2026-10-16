"""
JPEG XL photos as input (since 0.10.0): this tool's own copies (SDR, and HDR
with Apple's HDR profile) and cjxl's files (Brotli-compressed metadata, the
orientation in both the codestream and the EXIF, a bare codestream, a
recompressed JPEG, 16 bits, transparency, gray, an Adobe RGB profile, PQ
without a profile) convert to JPEG XL and to HEIC in every build: upright, with
their EXIF, XMP and color space, and the date and location from Photos. An HDR
one stays HDR as JPEG XL, with its peak and its profile; with --sdr (Drop HDR)
libjxl tone-maps it to SDR, and only so does it become a HEIC. A JPEG XL copy
that wouldn't be smaller than its JPEG XL original isn't written. Animated and
cut-short files fail; the rest of the batch goes on. The WebAssembly builds
decode them alike, and the Mac's within a level (libjxl's decoder computes in
floats, with fused multiply-adds on the Mac's NEON).
"""

import re
import struct
from pathlib import Path

import numpy as np
import photo_helpers as ph
import pytest
from PIL import Image

CURVE = b'hdgm' + bytes(4) + bytes(range(256))  # placeholder tag data
ADOBE_RGB = Path('/System/Library/ColorSync/Profiles/AdobeRGB1998.icc')
# name: the photo its EXIF and XMP come from (see inputs), or None
SDR = {
    'copy_sdr': 'heic_rot6',
    'cjxl_rot6': 'jpeg_rot6',
    'recompressed': 'jpeg_rot6',
    'bare': None,
    'lossless16': None,
    'alpha': 'png_alpha',
    'gray': None,
    'adobe_rgb': None,
}
# turned by the codestream's orientation, which cjxl takes from the JPEG
TURNED = {'cjxl_rot6', 'recompressed'}
HDR = ['copy_hdr', 'pq']


def write_ppm16(image, path, scale=1.0):
    """
    ``image`` as a 16-bit PPM, which cjxl reads (PIL writes 8 bits only), its
    values times ``scale``.
    """
    pixels = np.round(np.asarray(image, dtype=float) * 257 * scale)
    header = f'P6\n{image.width} {image.height}\n65535\n'.encode()
    path.write_bytes(header + pixels.astype('>u2').tobytes())


@pytest.fixture(scope='module')
def inputs(wasm, photos, batch, tmp_path_factory):
    """The JPEG XL test inputs: {name: path} (see the module's docstring)."""
    folder = tmp_path_factory.mktemp('jxl-inputs')
    out = {}

    # This tool's copies, by the build that ships to the iPhone: a turned
    # Display P3 photo, and an HDR one with Apple's HDR profile (shaped like
    # iOS 26's), as an iPhone's.
    _, pq_jxl, _ = batch.results['heic_hdr']
    icc = folder / 'p3pq.icc'
    ph.run(
        [
            'djxl',
            pq_jxl,
            folder / 'profile.ppm',
            '--color_space=RGB_D65_DCI_Rel_PeQ',
            f'--icc_out={icc}',
        ],
        check=True,
    )
    hdr_heic = folder / 'hdr.heic'
    profile = ph.apple_shaped_hdr_profile(icc.read_bytes(), CURVE)
    ph.with_item_profile(photos['heic_hdr'], 'tmap', profile, hdr_heic)
    _, copies = ph.convert(
        wasm, folder / 'copies', [photos['heic_rot6'], hdr_heic], ['-q', '93']
    )
    out['copy_sdr'], out['copy_hdr'] = copies[1], copies[2]

    def cjxl(name, source, *args):
        out[name] = folder / f'{name}.jxl'
        ph.run(['cjxl', source, out[name], *args], check=True)

    scene = ph.scene(320, 240, seed=4)
    scene.save(folder / 'scene.png')
    write_ppm16(scene, folder / 'scene16.ppm')
    # as PQ: at most 0.75, 983 nits, under its intensity target (1000)
    write_ppm16(scene, folder / 'pq.ppm', scale=0.75)
    scene.convert('L').save(folder / 'gray.png')
    scene.save(folder / 'adobe.png', icc_profile=ADOBE_RGB.read_bytes())
    scene.save(
        folder / 'animated.png',
        save_all=True,
        append_images=[scene.rotate(180)],
        duration=100,
    )
    # the JPEG's orientation goes into the codestream and stays in the EXIF
    cjxl('cjxl_rot6', photos['jpeg_rot6'], '--lossless_jpeg=0', '-q', '90')
    cjxl('recompressed', photos['jpeg_rot6'])  # lossless, with jbrd and brob
    cjxl('bare', folder / 'scene.png', '-q', '90', '--container=0')
    cjxl('lossless16', folder / 'scene16.ppm', '-d', '0')
    cjxl('alpha', photos['png_alpha'], '-q', '90')
    cjxl('gray', folder / 'gray.png', '-q', '90')
    cjxl('adobe_rgb', folder / 'adobe.png', '-q', '90')
    cjxl(
        'pq',
        folder / 'pq.ppm',
        '-q',
        '90',
        '-x',
        'color_space=RGB_D65_DCI_Rel_PeQ',
        '--intensity_target=1000',
    )
    cjxl('animated', folder / 'animated.png', '-q', '90')
    data = out['cjxl_rot6'].read_bytes()
    out['truncated'] = folder / 'truncated.jxl'
    out['truncated'].write_bytes(data[: len(data) * 2 // 3])
    return out


def jxl_info(path):
    return ph.run(['jxlinfo', '-v', path], check=True).stdout


def decoded(path, out_png):
    """djxl's decode, 8 bits, upright, in the file's own color space."""
    ph.run(['djxl', path, out_png, '--bits_per_sample=8'], check=True)
    return Image.open(out_png)


def test_inputs_are_what_they_say(inputs):
    info = {name: jxl_info(path) for name, path in inputs.items()}
    assert '90 degrees clockwise' in info['cjxl_rot6']
    assert 'Brotli-compressed Exif' in info['cjxl_rot6']
    assert 'Brotli-compressed xml' in info['recompressed']
    assert 'JPEG bitstream reconstruction data' in info['recompressed']
    assert inputs['bare'].read_bytes()[:2] == b'\xff\x0a'
    assert 'Uncompressed Exif' in info['copy_sdr']
    assert '16-bit RGB' in info['lossless16']
    assert 'RGB+Alpha' in info['alpha'] or 'alpha' in info['alpha'].lower()
    assert 'Grayscale' in info['gray'] or 'gray' in info['gray'].lower()
    # cjxl describes Adobe RGB itself: custom primaries, a plain gamma
    assert 'Transfer function: gamma' in info['adobe_rgb']
    assert 'ICC profile' in info['copy_hdr']
    assert 'Transfer function: PQ' in info['pq']
    assert 'Have animation: 1' in info['animated']


@pytest.mark.parametrize('name', sorted(SDR))
def test_converts_to_jpeg_xl(encoder, inputs, photos, name, tmp_path):
    output, results = ph.convert(
        encoder, tmp_path / 'job', [inputs[name]], ['-q', '75']
    )
    jxl = results[1]
    assert f'JPEG XL {decoded(inputs[name], tmp_path / "a.png").width}' in (
        ph.photo_output(output, inputs[name].stem)
    )
    want = decoded(inputs[name], tmp_path / 'want.png')
    got = decoded(jxl, tmp_path / 'got.png')
    assert got.size == want.size
    if name in TURNED:
        assert got.size == (427, 640)  # upright: 640x427 stored, turned once

    assert ph.psnr(want, got) > ph.MIN_PSNR
    assert want.mode == got.mode  # gray stays gray, alpha stays
    assert 'Orientation: 1' in jxl_info(jxl) or 'Orientation' not in (
        jxl_info(jxl)
    )
    source = SDR[name]
    if source:
        # the EXIF of the photo it came from, the orientation and size
        # excepted (upright now)
        theirs = ph.exif_tags(photos[source])
        ours = ph.exif_tags(jxl)
        assert ours.get('IFD0:Orientation', 1) == 1
        for key in set(theirs) | set(ours):
            if key not in ph.EXIF_ALLOWED_DIFF:
                assert ours.get(key) == theirs.get(key), key

    if name == 'recompressed':  # its XMP was in a brob box
        xmp = ph.xmp_tags(jxl)
        assert xmp['Description'] == 'photobatch test'
        assert xmp['Orientation'] == 1

    assert not ph.kept_originals(tmp_path / 'job')


def color_lines(path):
    """jxlinfo's description of a JPEG XL's color space."""
    keys = ('Color space', 'White point', 'Primaries', 'Red', 'Green', 'Blue')
    keys += ('Transfer function',)
    return [
        line
        for line in jxl_info(path).splitlines()
        if line.strip().startswith(keys)
    ]


def test_color_space_without_code_points_is_kept(encoder, inputs, tmp_path):
    # Adobe RGB: other primaries and a plain gamma, which CICP can't say,
    # go into the copy as the profile libjxl makes of them, which libjxl
    # stores as the same description
    _, results = ph.convert(
        encoder, tmp_path / 'job', [inputs['adobe_rgb']], ['-q', '75']
    )
    want, got = color_lines(inputs['adobe_rgb']), color_lines(results[1])
    assert any('gamma' in line for line in want)
    # the same words, and numbers within the profile's rounding
    number = r'-?\d+(?:\.\d+)?'
    assert [re.sub(number, '#', line) for line in got] == [
        re.sub(number, '#', line) for line in want
    ]
    assert [float(v) for v in re.findall(number, ' '.join(got))] == (
        pytest.approx(
            [float(v) for v in re.findall(number, ' '.join(want))], abs=1e-4
        )
    )


@pytest.mark.parametrize(
    'name', ['copy_sdr', 'cjxl_rot6', 'gray', 'adobe_rgb', 'lossless16']
)
def test_converts_to_heic(encoder, inputs, name, tmp_path):
    output, results = ph.convert(
        encoder, tmp_path / 'job', [inputs[name]], ['--heic']
    )
    heic = results[1]
    assert heic.suffix == '.heic'
    assert 'SDR HEIC' in ph.photo_output(output, inputs[name].stem)
    want = decoded(inputs[name], tmp_path / 'want.png')
    got = ph.apple_render(heic, tmp_path / 'got.png')
    assert got.size == want.size
    # x265 at RF 26 on a noisy scene: a few levels off, no color shift
    a = np.asarray(want.convert('RGB'), dtype=float)
    b = np.asarray(got.convert('RGB'), dtype=float)
    assert np.abs(a - b).mean() < 6
    assert np.abs(a.mean(axis=(0, 1)) - b.mean(axis=(0, 1))).max() < 2
    if SDR[name]:
        assert ph.exif_tags(heic).get('IFD0:Orientation', 1) == 1


def test_transparent_jpeg_xl_is_not_written_as_heic(encoder, inputs, tmp_path):
    ph.stage(tmp_path, [inputs['alpha']])
    result = encoder.run(['--heic', 'jxl_job.txt'], tmp_path)
    assert "transparent image (alpha) can't be saved as HEIC" in ' '.join(
        result.stdout.split()
    )
    assert not (tmp_path / 'jxl_done.txt').exists()


@pytest.mark.parametrize('name', HDR)
def test_hdr_stays_hdr(encoder, inputs, name, tmp_path):
    output, results = ph.convert(
        encoder, tmp_path / 'job', [inputs[name]], ['-q', '83']
    )
    jxl = results[1]
    peak = ph.jxl_intensity_target(inputs[name])
    assert ph.jxl_intensity_target(jxl) == pytest.approx(peak, abs=0.5)
    assert f'HDR {peak / 203:.1f}' in ph.photo_output(
        output, inputs[name].stem
    )
    assert ph.jxl_profile(jxl, tmp_path) == ph.jxl_profile(
        inputs[name], tmp_path
    )
    want = ph.jxl_hdr_pixels(inputs[name], tmp_path / 'want.ppm')
    got = ph.jxl_hdr_pixels(jxl, tmp_path / 'got.ppm')
    # as close as cjxl gets from the same pixels at that quality (a noisy
    # scene in PQ codes compresses worse than a photo)
    ref = tmp_path / 'ref.jxl'
    ph.run(
        [
            'cjxl',
            tmp_path / 'want.ppm',
            ref,
            '-q',
            '83',
            '-x',
            'color_space=RGB_D65_DCI_Rel_PeQ',
            f'--intensity_target={peak}',
        ],
        check=True,
    )
    floor = ph.pq_psnr(want, ph.jxl_hdr_pixels(ref, tmp_path / 'ref.ppm'))
    assert ph.pq_psnr(want, got) > min(40, floor - 1)
    assert not ph.kept_originals(tmp_path / 'job')


def test_apple_hdr_profile_is_kept(inputs, tmp_path):
    # the copy's profile is Apple's (with its tone curve), not libjxl's
    profile = ph.jxl_profile(inputs['copy_hdr'], tmp_path)
    assert profile is not None and b'hdgm' in profile


@pytest.mark.parametrize('name', HDR)
def test_drop_hdr_tone_maps_to_sdr(encoder, inputs, name, tmp_path):
    output, results = ph.convert(
        encoder, tmp_path / 'job', [inputs[name]], ['-q', '83', '--sdr']
    )
    info = jxl_info(results[1])
    assert 'lossy, 8-bit RGB' in info
    assert 'Transfer function: sRGB' in info
    assert 'Primaries: P3' in info
    assert 'HDR tone-mapped to SDR' in ' '.join(
        ph.photo_output(output, inputs[name].stem).split()
    )
    assert ph.kept_originals(tmp_path / 'job') == {1}
    # lit like an SDR picture, not like PQ read as sRGB (much darker)
    mean = np.asarray(decoded(results[1], tmp_path / 'sdr.png')).mean()
    assert 60 < mean < 200


@pytest.mark.parametrize('name', HDR)
def test_hdr_becomes_heic_only_with_drop_hdr(encoder, inputs, name, tmp_path):
    ph.stage(tmp_path / 'keep', [inputs[name]])
    result = encoder.run(['--heic', 'jxl_job.txt'], tmp_path / 'keep')
    text = ' '.join(result.stdout.split())
    assert "FAILED: an HDR JPEG XL can't keep its HDR as HEIC" in text
    assert 'convert it on the Mac with Drop HDR' in text  # the iPhone's
    assert not (tmp_path / 'keep' / 'jxl_done.txt').exists()

    ph.stage(tmp_path / 'mac', [inputs[name]])
    result = encoder.run(['--heic', '--mac', 'jxl_job.txt'], tmp_path / 'mac')
    assert 'choose Drop HDR for an SDR HEIC, or JPEG XL' in ' '.join(
        result.stdout.split()
    )

    output, results = ph.convert(
        encoder, tmp_path / 'drop', [inputs[name]], ['--heic', '--sdr']
    )
    assert results[1].suffix == '.heic'
    assert ph.kept_originals(tmp_path / 'drop') == {1}
    assert ph.apple_render(results[1], tmp_path / 'got.png').size == (
        decoded(inputs[name], tmp_path / 'want.png').size
    )


def test_copy_not_smaller_is_not_written(encoder, inputs, tmp_path):
    # Lossless, a lossy JPEG XL only grows: left alone, not a failure. The
    # JPEG converted alongside is written.
    ph.stage(tmp_path, [inputs['copy_sdr'], ph.HERE / 'fixtures/hdr/o1.heic'])
    result = encoder.run(['-q', '100', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    text = ' '.join(result.stdout.split())
    assert '! not converted: the copy' in text
    assert 'would not be smaller than the original' in text
    assert '1 JPEG XL photo not converted: its copy would not be smaller.' in (
        text
    )
    assert 'failed' not in text
    assert list(ph.read_done(tmp_path)) == [2]
    assert not (tmp_path / 'jxl_out_1.jxl').exists()


def test_animated_and_cut_short_fail(encoder, inputs, tmp_path):
    ph.stage(
        tmp_path, [inputs['animated'], inputs['truncated'], inputs['bare']]
    )
    result = encoder.run(['-q', '83', 'jxl_job.txt'], tmp_path)
    text = ' '.join(result.stdout.split())
    assert "FAILED: an animated JPEG XL isn't a still photo" in text
    assert 'FAILED: the JPEG XL file is cut short' in text
    assert '2 failed' in text
    assert list(ph.read_done(tmp_path)) == [3]


def test_dates_and_location_from_photos(encoder, inputs, tmp_path):
    _, results = ph.convert(
        encoder,
        tmp_path,
        [inputs['cjxl_rot6']],
        ['-q', '75'],
        dates={1: '2024-01-01T17:00:00-05:00'},
        meta=['1|gps|40.758441666667,-73.829766666667'],
    )
    tags = ph.exif_tags(results[1])
    assert tags['ExifIFD:DateTimeOriginal'] == '2024:01:01 17:00:00'
    gps = ph.gps_of(results[1])
    assert gps['GPSLatitude'] == pytest.approx(40.758441666667, abs=1e-5)
    assert gps['GPSLongitude'] == pytest.approx(73.829766666667, abs=1e-5)
    assert (gps['GPSLatitudeRef'], gps['GPSLongitudeRef']) == ('N', 'W')


def padded(path, folder):
    """
    ``path`` with an unknown 8 MB box after its codestream, which libjxl skips:
    a lossless copy is then smaller than the input, so it is written, and its
    pixels are the decoder's, exactly.
    """
    out = folder / path.name
    pad = 8_000_000
    out.write_bytes(
        path.read_bytes() + struct.pack('>I', 8 + pad) + b'pad ' + bytes(pad)
    )
    return out


def djxl_pixels(jxl, ppm):
    """The samples of a lossless JPEG XL, as djxl decodes them."""
    ph.run(['djxl', jxl, ppm], check=True)
    return ph.read_ppm(ppm)[0].astype(int)


def test_builds_decode_alike(wasm, macos, inputs, tmp_path):
    """
    The WebAssembly builds (SIMD and scalar, the iPhone's) decode a JPEG XL to
    the same pixels; the Mac's build within one level of 255 of them (16 of
    65535 for HDR, a sixteenth of an 8-bit level), so the copies of a JPEG XL
    differ a little between the Mac and the iPhone, unlike other photos'
    (test_mac_script.py).
    """
    path = ph.TOOL / 'dist' / 'photobatch-scalar.wasm'
    ph.need(path.exists(), f'{path} is missing; run scripts/build-wasm.sh')
    scalar = ph.Encoder('wasm-scalar', [*wasm.command[:-1], path])
    names = ['copy_sdr', 'copy_hdr', 'cjxl_rot6', 'recompressed']
    sources = tmp_path / 'padded'
    sources.mkdir()
    staged = [padded(inputs[n], sources) for n in names]
    pixels = {}
    for label, encoder, args in (
        ('wasm', wasm, []),
        ('wasm-scalar', scalar, []),
        ('macos', macos, []),
        ('macos-sdr', macos, ['--sdr']),
        ('wasm-sdr', wasm, ['--sdr']),
    ):
        _, results = ph.convert(
            encoder, tmp_path / label, staged, ['-q', '100', *args]
        )
        assert len(results) == len(names), label
        pixels[label] = [
            djxl_pixels(jxl, tmp_path / f'{label}{i}.ppm')
            for i, jxl in sorted(results.items())
        ]

    for a, b in zip(pixels['wasm'], pixels['wasm-scalar']):
        assert np.array_equal(a, b)

    for mac_label, wasm_label in (
        ('macos', 'wasm'),
        ('macos-sdr', 'wasm-sdr'),
    ):
        for name, a, b in zip(names, pixels[mac_label], pixels[wasm_label]):
            # measured: 1 of 255 in about 0.02% of an 8-bit picture's
            # samples, 6 of 65535 in 2% of an HDR (16-bit) one's
            tolerance = 16 if a.max() > 255 else 1
            assert np.abs(a - b).max() <= tolerance, (mac_label, name)
