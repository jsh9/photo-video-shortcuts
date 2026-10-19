"""
JPEG XL photos as input (since 0.10.0): this tool's own copies (SDR, and HDR
with Apple's HDR profile, lossy and lossless) and cjxl's files
(Brotli-compressed metadata, the orientation in both the codestream and the
EXIF, a bare codestream, a recompressed JPEG, 10 and 16 bits, transparency,
gray, an Adobe RGB profile, PQ without a profile, PQ with a white point CICP
can't name, PQ by a profile alone, HLG, a gain map box) convert to JPEG XL and
to HEIC in every build: upright, with their EXIF, XMP and color space (10 bits
kept as JPEG XL), and the date and location from Photos. An HDR one (PQ or HLG)
stays HDR as JPEG XL, with its peak and its profile; with --sdr (Drop HDR)
libjxl tone-maps it to SDR (into Rec. 2020 primaries when CICP can't name its
own; not at all when a profile alone describes it), and only so does it become
a HEIC. A gain map ('jhgm' box) isn't used: the copy is SDR and the original is
kept. A JPEG XL copy larger than its JPEG XL original is written all the same,
with a warning. Animated and cut-short files fail, and so do metadata boxes cut
short or not decompressible (an Exif box without a TIFF header is dropped); the
rest of the batch goes on. Metadata boxes of 200 KB, raw or Brotli-compressed,
are kept byte for byte. The WebAssembly builds decode them alike, and the Mac's
within a level (libjxl's decoder computes in floats, with fused multiply-adds
on the Mac's NEON).
"""

import re
import struct
from pathlib import Path

import brotli
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
# name: its HDR encoding as cjxl and djxl name it (Display P3 PQ, or Rec. 2100
# HLG), and its primaries as jxlinfo does
HDR = {
    'copy_hdr': ('RGB_D65_DCI_Rel_PeQ', 'P3'),
    'pq': ('RGB_D65_DCI_Rel_PeQ', 'P3'),
    'hlg': ('RGB_D65_202_Rel_HLG', 'Rec.2100'),
}


def write_ppm(samples, path, maximum):
    """
    ``samples`` (rows of RGB values up to ``maximum``) as a PPM of 9 to 16
    bits, which cjxl reads (PIL writes 8 bits only) with the bit depth
    ``maximum`` gives: 1023 for 10 bits.
    """
    height, width = samples.shape[:2]
    header = f'P6\n{width} {height}\n{maximum}\n'.encode()
    path.write_bytes(header + np.asarray(samples).astype('>u2').tobytes())


def write_ppm16(image, path, scale=1.0):
    """``image`` as a 16-bit PPM, its values times ``scale``."""
    pixels = np.round(np.asarray(image, dtype=float) * 257 * scale)
    write_ppm(pixels, path, 65535)


def ten_bit_samples(image):
    """
    ``image``'s values as 10-bit samples that use all ten bits: times 4, plus 0
    to 3 in a diagonal pattern.
    """
    pixels = np.asarray(image, dtype=np.uint16)
    rows, columns = np.indices(pixels.shape[:2])
    return pixels * 4 + ((rows + columns) % 4)[:, :, None]


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
    # and a lossless HDR copy, its samples as stored
    _, copies = ph.convert(
        wasm, folder / 'lossless', [hdr_heic], ['-q', '100']
    )
    out['lossless_hdr'] = copies[1]

    def cjxl(name, source, *args):
        out[name] = folder / f'{name}.jxl'
        ph.run(['cjxl', source, out[name], *args], check=True)

    scene = ph.scene(320, 240, seed=4)
    scene.save(folder / 'scene.png')
    write_ppm16(scene, folder / 'scene16.ppm')
    write_ppm(ten_bit_samples(scene), folder / 'scene10.ppm', 1023)
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
    cjxl('ten_bit', folder / 'scene10.ppm', '-d', '0')
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
    # the same samples as HLG (Rec. 2100 primaries), where 0.75 is reference
    # white, 203 nits on a 1000-nit display
    cjxl(
        'hlg',
        folder / 'pq.ppm',
        '-q',
        '90',
        '-x',
        'color_space=RGB_D65_202_Rel_HLG',
        '--intensity_target=1000',
    )
    cjxl('animated', folder / 'animated.png', '-q', '90')
    # PQ with a white point CICP can't name (E): HDR by libjxl's description
    cjxl(
        'pq_e',
        folder / 'pq.ppm',
        '-q',
        '90',
        '-x',
        'color_space=RGB_EER_202_Rel_PeQ',
        '--intensity_target=1000',
    )
    # PQ by a profile alone: the profile's 'cicp' tag names the curve but
    # not the primaries (code 2, unspecified); lossless keeps the profile
    unnamed = bytearray(ph.icc_tags(icc.read_bytes())['cicp'])
    unnamed[8] = 2
    scene.save(
        folder / 'pq_icc.png',
        icc_profile=ph.add_icc_tag(icc.read_bytes(), 'cicp', bytes(unnamed)),
    )
    cjxl('pq_icc', folder / 'pq_icc.png', '-d', '0')
    # an SDR copy with a gain map box ('jhgm', ISO 21496-1) after its
    # codestream, which photobatch notes but doesn't use
    out['gain_map'] = folder / 'gain_map.jxl'
    out['gain_map'].write_bytes(
        out['copy_sdr'].read_bytes()
        + struct.pack('>I', 8 + 64)
        + b'jhgm'
        + bytes(64)
    )
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
    assert 'lossless, 10-bit RGB' in info['ten_bit']
    assert 'lossless, 16-bit RGB' in info['lossless_hdr']
    assert 'ICC profile' in info['lossless_hdr']
    assert 'RGB+Alpha' in info['alpha'] or 'alpha' in info['alpha'].lower()
    assert 'Grayscale' in info['gray'] or 'gray' in info['gray'].lower()
    # cjxl describes Adobe RGB itself: custom primaries, a plain gamma
    assert 'Transfer function: gamma' in info['adobe_rgb']
    assert 'ICC profile' in info['copy_hdr']
    assert 'Transfer function: PQ' in info['pq']
    assert 'Transfer function: HLG' in info['hlg']
    assert 'Primaries: Rec.2100' in info['hlg']
    assert 'White point: E' in info['pq_e']
    assert 'Transfer function: PQ' in info['pq_e']
    assert 'ICC profile' in info['pq_icc'] and 'lossless' in info['pq_icc']
    assert inputs['gain_map'].read_bytes().endswith(b'jhgm' + bytes(64))
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


def hdr_samples(jxl, ppm, space):
    """
    A JPEG XL's samples as djxl decodes them into ``space`` (its own HDR
    encoding, PQ or HLG; asked for explicitly, as a lossy JPEG XL with an ICC
    profile otherwise decodes to linear sRGB, clipping HDR), 0 to 1.
    """
    ph.run(['djxl', jxl, ppm, f'--color_space={space}'], check=True)
    pixels, maximum = ph.read_ppm(ppm)
    return pixels / maximum


def encoded_psnr(reference, samples):
    """
    PSNR (dB) of two pictures' samples as encoded, 0 to 1: PQ or HLG codes,
    perceptually spaced either way (as pq_psnr compares linear light).
    """
    mse = float(np.mean((reference - samples) ** 2))
    return 99.0 if mse == 0 else 10 * np.log10(1 / mse)


def sdr_space(space):
    """The same primaries with the sRGB curve, as djxl names it."""
    return space[: space.rindex('_')] + '_SRG'


@pytest.mark.parametrize('name', list(HDR))
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
    space, _ = HDR[name]
    want = hdr_samples(inputs[name], tmp_path / 'want.ppm', space)
    got = hdr_samples(jxl, tmp_path / 'got.ppm', space)
    # as close as cjxl gets from the same pixels at that quality (a noisy
    # scene in PQ or HLG codes compresses worse than a photo)
    ref = tmp_path / 'ref.jxl'
    ph.run(
        [
            'cjxl',
            tmp_path / 'want.ppm',
            ref,
            '-q',
            '83',
            '-x',
            f'color_space={space}',
            f'--intensity_target={peak}',
        ],
        check=True,
    )
    floor = encoded_psnr(want, hdr_samples(ref, tmp_path / 'ref.ppm', space))
    assert encoded_psnr(want, got) > min(40, floor - 1)
    assert not ph.kept_originals(tmp_path / 'job')


def test_apple_hdr_profile_is_kept(inputs, tmp_path):
    # the copy's profile is Apple's (with its tone curve), not libjxl's
    profile = ph.jxl_profile(inputs['copy_hdr'], tmp_path)
    assert profile is not None and b'hdgm' in profile


@pytest.mark.parametrize('name', list(HDR))
def test_drop_hdr_tone_maps_to_sdr(encoder, inputs, name, tmp_path):
    output, results = ph.convert(
        encoder, tmp_path / 'job', [inputs[name]], ['-q', '83', '--sdr']
    )
    space, primaries = HDR[name]
    info = jxl_info(results[1])
    assert 'lossy, 8-bit RGB' in info
    assert 'Transfer function: sRGB' in info
    assert f'Primaries: {primaries}' in info
    assert 'HDR tone-mapped to SDR' in ' '.join(
        ph.photo_output(output, inputs[name].stem).split()
    )
    assert ph.kept_originals(tmp_path / 'job') == {1}
    # libjxl's rendering of the picture for an SDR display (255 nits, as
    # jxl_decode asks: Rec. 2408 for PQ, the HLG OOTF for HLG), which djxl
    # makes with --display_nits: lit like an SDR picture (means of 161, 119
    # and 65 of 255 for copy_hdr, pq and hlg), not like the HDR codes read as
    # sRGB (much darker; nor like the un-tone-mapped rendering, whose white
    # is the file's peak: 117, 62 and 45). Compared on a lossless copy: the
    # lossy one's own loss on the noisy synthetic scenes (about 26 dB at
    # quality 83) would hide a wrong tone mapping; the lossless copy is that
    # rendering within a level (the builds' decoders differ by that much).
    ref = tmp_path / 'ref.png'
    ph.run(
        [
            'djxl',
            inputs[name],
            ref,
            '--bits_per_sample=8',
            '--display_nits=255',
            f'--color_space={sdr_space(space)}',
        ],
        check=True,
    )
    assert (
        60 < np.asarray(decoded(results[1], tmp_path / 'sdr.png')).mean() < 200
    )
    _, lossless = ph.convert(
        encoder, tmp_path / 'lossless', [inputs[name]], ['-q', '100', '--sdr']
    )
    got = decoded(lossless[1], tmp_path / 'lossless.png')
    assert ph.psnr(Image.open(ref), got) > 40


@pytest.mark.parametrize('name', list(HDR))
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


def test_larger_copy_is_written(encoder, inputs, tmp_path):
    # Lossless, a lossy JPEG XL only grows; its copy is written and collected
    # like any other, with a warning (0.10.0 left such a JPEG XL alone;
    # test_encoder_cli.py has the other formats). A batch of such copies alone
    # exits with 0 and leaves a jxl_done.txt for the shortcuts.
    copy = inputs['copy_sdr']
    output, results = ph.convert(encoder, tmp_path, [copy], ['-q', '100'])
    assert results[1].stat().st_size > copy.stat().st_size
    assert '! the copy is larger than the original' in ph.photo_output(
        output, copy.stem
    )
    text = ' '.join(output.split())
    assert 'Done: 1 of 1 converted' in text
    summary = '1 copy is larger than its original; it was saved all the same.'
    assert summary in text
    assert ph.kept_originals(tmp_path) == set()


def test_gain_map_box_is_noted_and_original_kept(encoder, inputs, tmp_path):
    # A JPEG XL with a gain map ('jhgm' box) is converted as its SDR base,
    # like a JPEG with a gain map: the log says so (not with --sdr, which
    # asks for SDR) and the original is kept, on both routes.
    runs = (
        ('jxl', ['-q', '75'], '.jxl'),
        ('sdr', ['-q', '75', '--sdr'], '.jxl'),
        ('heic', ['--heic'], '.heic'),
    )
    for label, args, suffix in runs:
        output, results = ph.convert(
            encoder, tmp_path / label, [inputs['gain_map']], args
        )
        text = ' '.join(ph.photo_output(output, 'gain_map').split())
        noted = '! HDR not kept (JPEG XL with a gain map)' in text
        assert noted == (label != 'sdr'), label
        assert results[1].suffix == suffix, label
        assert ph.kept_originals(tmp_path / label) == {1}, label


def test_hdr_cicp_cannot_name_stays_hdr_and_tone_maps(
        encoder, inputs, tmp_path
):
    # PQ with a white point CICP can't name (E): HDR all the same, kept with
    # libjxl's description and its brightness; refused as HEIC; with --sdr
    # tone-mapped into Rec. 2020 primaries (D65), which CICP names, on both
    # routes.
    output, results = ph.convert(
        encoder, tmp_path / 'hdr', [inputs['pq_e']], ['-q', '83']
    )
    assert 'HDR 4.9' in ph.photo_output(output, 'pq_e')  # 1000 nits
    info = jxl_info(results[1])
    assert 'lossy, 16-bit RGB' in info
    assert 'White point: E' in info and 'Transfer function: PQ' in info
    assert ph.jxl_intensity_target(results[1]) == pytest.approx(1000, abs=0.5)
    assert not ph.kept_originals(tmp_path / 'hdr')

    ph.stage(tmp_path / 'keep', [inputs['pq_e']])
    result = encoder.run(['--heic', 'jxl_job.txt'], tmp_path / 'keep')
    assert "an HDR JPEG XL can't keep its HDR as HEIC" in ' '.join(
        result.stdout.split()
    )
    assert not (tmp_path / 'keep' / 'jxl_done.txt').exists()

    output, results = ph.convert(
        encoder, tmp_path / 'sdr', [inputs['pq_e']], ['-q', '83', '--sdr']
    )
    info = jxl_info(results[1])
    assert 'lossy, 8-bit RGB' in info
    assert 'White point: D65' in info and 'Primaries: Rec.2100' in info
    assert 'Transfer function: sRGB' in info
    assert 'HDR tone-mapped to SDR' in ' '.join(
        ph.photo_output(output, 'pq_e').split()
    )
    assert ph.kept_originals(tmp_path / 'sdr') == {1}
    mean = np.asarray(decoded(results[1], tmp_path / 'sdr.png')).mean()
    assert 60 < mean < 200

    output, results = ph.convert(
        encoder, tmp_path / 'heic', [inputs['pq_e']], ['--heic', '--sdr']
    )
    assert results[1].suffix == '.heic'
    assert 'SDR HEIC' in ph.photo_output(output, 'pq_e')
    assert ph.kept_originals(tmp_path / 'heic') == {1}


def is_pq(jxl, folder):
    """
    The JPEG XL is PQ: by libjxl's description, or by its profile's 'cicp' tag
    (the static builds keep such a profile, Homebrew's libjxl describes it).
    """
    profile = ph.jxl_profile(jxl, folder)
    if profile is None:
        return 'Transfer function: PQ' in jxl_info(jxl)

    return ph.icc_tags(profile).get('cicp', b'')[9:10] == b'\x10'


def test_hdr_by_profile_alone_cannot_be_tone_mapped(encoder, inputs, tmp_path):
    # PQ by an ICC profile whose 'cicp' tag doesn't name the primaries: HDR
    # (kept by the profile, or libjxl's description of it); with --sdr it
    # stays HDR and the log says why; as HEIC it is refused either way.
    output, results = ph.convert(
        encoder, tmp_path / 'hdr', [inputs['pq_icc']], ['-q', '83']
    )
    text = ' '.join(ph.photo_output(output, 'pq_icc').split())
    assert 'HDR 49.3' in text  # PQ's peak, 10,000 nits, as cjxl wrote
    assert 'HDR kept' not in text
    assert is_pq(results[1], tmp_path / 'hdr')
    assert not ph.kept_originals(tmp_path / 'hdr')

    output, results = ph.convert(
        encoder, tmp_path / 'sdr', [inputs['pq_icc']], ['-q', '83', '--sdr']
    )
    text = ' '.join(ph.photo_output(output, 'pq_icc').split())
    assert (
        '! HDR kept: a PQ picture described by its ICC profile alone '
        "can't be tone-mapped to SDR"
    ) in text
    assert 'HDR 49.3' in text
    assert is_pq(results[1], tmp_path / 'sdr')
    assert not ph.kept_originals(tmp_path / 'sdr')

    refusals = (
        ('keep', ['--heic'], "can't keep its HDR as HEIC"),
        (
            'drop',
            ['--heic', '--sdr'],
            "can't be tone-mapped to SDR, so it can't be saved as HEIC",
        ),
    )
    for label, args, message in refusals:
        ph.stage(tmp_path / label, [inputs['pq_icc']])
        result = encoder.run([*args, 'jxl_job.txt'], tmp_path / label)
        assert message in ' '.join(result.stdout.split()), label
        assert not (tmp_path / label / 'jxl_done.txt').exists(), label


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


def jxl_box(kind, payload):
    return struct.pack('>I', 8 + len(payload)) + kind.encode() + payload


def container(codestream, before=b'', after=b''):
    """
    A JPEG XL container made by hand: the signature and ftyp boxes, then the
    boxes ``before``, the codestream (a jxlc box) and the boxes ``after``.
    """
    return (
        jxl_box('JXL ', b'\r\n\x87\n')
        + jxl_box('ftyp', b'jxl \0\0\0\0jxl ')
        + before
        + jxl_box('jxlc', codestream)
        + after
    )


def test_metadata_boxes(encoder, inputs, tmp_path):
    """
    Metadata boxes made by hand around the 'bare' input's codestream: one cut
    short at the end of the file, or a Brotli-compressed one that can't be
    decompressed or whose stream doesn't end where the box does, fails its
    photo (its metadata can't be kept) and the rest of the batch goes on; an
    Exif box whose TIFF header is further in (its offset skips the 6 bytes a
    JPEG's EXIF starts with) is read; one without a TIFF header is dropped, and
    its photo converts without it.
    """
    tiff = ph.tiff({0x010F: ph.ascii_value('photobatch')}, exif=ph.TIFF_EXIF)
    xmp = ph.XMP.format(o=1).encode()
    brotli_exif = brotli.compress(bytes(4) + tiff)
    code = inputs['bare'].read_bytes()
    files = {
        'exif_cut': container(
            code, after=jxl_box('Exif', bytes(4) + tiff)[:-8]
        ),
        'xml_cut': container(code, after=jxl_box('xml ', xmp)[:-8]),
        # a Brotli stream whose first meta-block sets the reserved bit; at the
        # end of the file too, it isn't taken for a box cut short
        'brob_corrupt': container(
            code, after=jxl_box('brob', b'Exif' + b'\x1c' + bytes(15))
        ),
        # a Brotli stream that the box cuts short, at the end of the file or
        # before the codestream, or one with other bytes after it in its box:
        # libjxl 0.11.2 without patch_deps.py --brob took what it had
        # decompressed for the whole box, read on into the next box, and
        # ignored the bytes
        'brob_cut': container(
            code, after=jxl_box('brob', b'Exif' + brotli_exif[:-3])
        ),
        'brob_cut_first': container(
            code, before=jxl_box('brob', b'Exif' + brotli_exif[:-3])
        ),
        'brob_extra': container(
            code, after=jxl_box('brob', b'Exif' + brotli_exif + bytes(3))
        ),
        'exif_offset': container(
            code,
            before=jxl_box('Exif', struct.pack('>I', 6) + b'Exif\0\0' + tiff),
        ),
        'exif_not_tiff': container(
            code, before=jxl_box('Exif', bytes(4) + b'not a TIFF header')
        ),
    }
    sources = tmp_path / 'sources'
    sources.mkdir()
    for name, data in files.items():
        (sources / f'{name}.jxl').write_bytes(data)

    ph.stage(tmp_path / 'job', [sources / f'{name}.jxl' for name in files])
    result = encoder.run(['-q', '75', 'jxl_job.txt'], tmp_path / 'job')
    assert result.returncode == 0, result.stdout + result.stderr

    def said(name):
        return ' '.join(ph.photo_output(result.stdout, name).split())

    assert said('exif_cut') == 'FAILED: metadata box Exif cut short'
    assert said('xml_cut') == 'FAILED: metadata box xml cut short'
    assert said('brob_corrupt') == 'FAILED: unreadable metadata box Exif'
    for name in ('brob_cut', 'brob_cut_first', 'brob_extra'):
        assert said(name) == 'FAILED: unreadable metadata box Exif', name

    assert '6 failed' in ' '.join(result.stdout.split())
    done = {i: out for i, (out, _) in ph.read_done(tmp_path / 'job').items()}
    assert sorted(done) == [7, 8]

    tags = ph.exif_tags(done[7])
    assert tags['IFD0:Make'] == 'photobatch'
    assert tags['ExifIFD:DateTimeOriginal'] == '2024:05:06 07:08:09'
    assert 'no metadata' in said('exif_not_tiff')
    assert ph.exif_box(done[8]) == b''
    assert (
        ph.psnr(
            decoded(inputs['bare'], tmp_path / 'want.png'),
            decoded(done[8], tmp_path / 'got.png'),
        )
        > ph.MIN_PSNR
    )


def test_metadata_boxes_over_64_kb(encoder, inputs, tmp_path):
    """
    EXIF and XMP of 200 KB each (a long ImageDescription, a long
    dc:description), raw or Brotli-compressed, around the 'bare' input's
    codestream: jxl_boxes reads them into a 64 KB buffer that libjxl asks to
    grow, twice for each, and the copy gets them byte for byte. (An unknown 1
    MB box pads each input, as padded() does, so that the copy, which stores
    the boxes raw, is smaller than the original and is written.)
    """
    text = ' '.join(f'{i:06d}' for i in range(30_000))  # 209,999 bytes
    tiff = ph.tiff(
        {0x010F: ph.ascii_value('photobatch'), 0x010E: ph.ascii_value(text)},
        exif=ph.TIFF_EXIF,
    )
    exif = bytes(4) + tiff  # the TIFF header at offset 0
    xmp = ph.XMP.format(o=1).replace('photobatch test', text).encode()
    assert min(len(exif), len(xmp)) > 2 * 65536
    code = inputs['bare'].read_bytes()
    pad = jxl_box('pad ', bytes(1 << 20))
    files = {
        'raw': container(
            code,
            before=jxl_box('Exif', exif),
            after=jxl_box('xml ', xmp) + pad,
        ),
        'brob': container(
            code,
            before=jxl_box('brob', b'Exif' + brotli.compress(exif)),
            after=jxl_box('brob', b'xml ' + brotli.compress(xmp)) + pad,
        ),
    }
    sources = tmp_path / 'sources'
    sources.mkdir()
    for name, data in files.items():
        (sources / f'{name}.jxl').write_bytes(data)

    _, results = ph.convert(
        encoder,
        tmp_path / 'job',
        [sources / f'{name}.jxl' for name in files],
        ['-q', '75'],
    )
    assert sorted(results) == [1, 2]
    for i, name in enumerate(files, 1):
        assert ph.exif_box(results[i]) == exif, name
        assert ph.xml_box(results[i]) == xmp, name

    tags = ph.exif_tags(results[1])
    assert tags['IFD0:Make'] == 'photobatch'
    assert tags['IFD0:ImageDescription'] == text
    assert ph.xmp_tags(results[2])['Description'] == text


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


def test_ten_bits_are_kept(encoder, inputs, tmp_path):
    """
    A 10-bit JPEG XL comes out of libjxl as 0 to 1023, its own depth, as a
    10-bit HEIF's does: the JPEG XL copy is 10-bit, and lossless here, so its
    samples are the input's exactly. The HEIC gets the 8-bit rendering of them.
    """
    source = padded(inputs['ten_bit'], tmp_path)
    output, results = ph.convert(
        encoder, tmp_path / 'jxl', [source], ['-q', '100']
    )
    assert '10-bit' in ph.photo_output(output, 'ten_bit')
    assert 'lossless, 10-bit RGB' in jxl_info(results[1])
    want = djxl_pixels(inputs['ten_bit'], tmp_path / 'want.ppm')
    assert want.max() > 255 and (want % 4).any()  # all ten bits used
    assert np.array_equal(djxl_pixels(results[1], tmp_path / 'got.ppm'), want)

    output, results = ph.convert(
        encoder, tmp_path / 'heic', [inputs['ten_bit']], ['--heic']
    )
    assert 'SDR HEIC' in ph.photo_output(output, 'ten_bit')
    rendering = np.round(want * 255 / 1023)
    got = ph.apple_render(results[1], tmp_path / 'heic.png').convert('RGB')
    got = np.asarray(got, dtype=float)
    # x265 at RF 26 on a noisy scene: a few levels off, no color shift
    assert np.abs(rendering - got).mean() < 6
    assert (
        np.abs(rendering.mean(axis=(0, 1)) - got.mean(axis=(0, 1))).max() < 2
    )


def test_lossless_hdr_copy_is_decoded_as_stored(encoder, inputs, tmp_path):
    """
    A lossless HDR copy (16-bit PQ, Apple's HDR profile) converted losslessly
    again: the same samples and the same profile, byte for byte, on every
    build. jxl_decode asks for the code points the profile's 'cicp' tag names
    (Display P3 PQ), which libjxl takes for the profile's own color space (it
    reads the tag too, the static builds through patch_deps.py's skcms patch),
    so no color transform changes the samples.
    """
    source = padded(inputs['lossless_hdr'], tmp_path)
    output, results = ph.convert(
        encoder, tmp_path / 'job', [source], ['-q', '100']
    )
    jxl = results[1]
    peak = ph.jxl_intensity_target(source)
    assert f'HDR {peak / 203:.1f}' in ph.photo_output(output, source.stem)
    assert ph.jxl_intensity_target(jxl) == pytest.approx(peak, abs=0.5)
    profile = ph.jxl_profile(source, tmp_path)
    assert profile is not None and b'hdgm' in profile
    assert ph.jxl_profile(jxl, tmp_path) == profile
    want = djxl_pixels(source, tmp_path / 'want.ppm')
    assert want.max() > 255
    assert np.array_equal(djxl_pixels(jxl, tmp_path / 'got.ppm'), want)
