"""
The whole conversion with the real tools (ours, or the ffmpeg the FFMPEG
variable names): test videos written by AVFoundation as an iPhone writes them,
"exported" into the shortcut's work folder, through its script with each codec,
then what Apple's AVFoundation (the framework Photos uses) and ffprobe read in
the copies: the codec in 10 bits, the size limit, the rotation, HDR and Dolby
Vision, the sound, every Apple key with its value and type, and the picture
(PSNR against the original).
"""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import video_helpers as vh

# test video -> the name Photos exports it under
NAMES = {
    'sdr': 'IMG_0001.MOV',
    'hlg': 'IMG_0002.MOV',
    'two': 'IMG_0003.MOV',
    'silent': 'IMG_0004.MOV',
    'slomo': 'IMG_0005.MOV',
    'big': 'IMG_0006.MOV',
    'four_three': 'IMG_0007.MOV',
    'ntsc': 'IMG_0008.MOV',
    'bare': 'IMG_0009.MOV',
    'fast': 'IMG_0010.MOV',
    'prores': 'IMG_0012.MOV',
    'applelog': 'IMG_0013.MOV',
}
SKIPPED = ('slomo', 'applelog')
# Quick settings: the copies are checked, not the encoders' quality.
SETTINGS = {
    'h265': {'Codec': 'h265', 'Preset': 'fast', 'Tune': 'none', 'RF': '28'},
    'av1': {'Codec': 'av1', 'Preset': '5', 'Tune': '', 'RF': '40'},
}
MIN_PSNR = 30.0  # dB, of the luma; a wrong size or rotation gives about 10


@pytest.fixture(scope='module', params=['h265', 'av1'])
def run(request, tmp_path_factory, actions, tools, videos):
    """Every test video through the script with one codec."""
    codec = request.param
    mac = vh.Mac(
        tmp_path_factory.mktemp(f'conversion-{codec}'), actions, tools
    )
    for key, name in NAMES.items():
        mac.export(videos[key], name)

    ids = '\n'.join(f'ID-{key}|{name}' for key, name in NAMES.items())
    lines = mac.convert(ids, Size='720p', Audio='96', **SETTINGS[codec])
    copies = {}
    for line in lines:
        path, ident, flag, _ = line.split('|')
        assert flag == 'delete'
        copies[ident.removeprefix('ID-')] = Path(path)

    return SimpleNamespace(codec=codec, mac=mac, copies=copies, videos=videos)


def probe(tools, path):
    """ffprobe's streams: (video, [audio...])."""
    data = vh.ffprobe_streams(tools['ffprobe'], path)
    streams = data['streams']
    video = [s for s in streams if s['codec_type'] == 'video']
    audio = [s for s in streams if s['codec_type'] == 'audio']
    assert len(video) == 1
    return video[0], audio


def test_everything_but_the_slo_mo_and_apple_log_converted(run):
    # The slo-mo is skipped as its file marks it; the 120 fps video that is
    # marked to play at its full rate is converted; ProRes is converted, but
    # not in Apple Log (the log curve AVFoundation wrote, as the Camera does).
    assert sorted(run.copies) == sorted(k for k in NAMES if k not in SKIPPED)
    log = run.mac.log
    assert 'Skipped IMG_0005.MOV: slo-mo (120 fps on average)' in log
    assert (
        'Skipped IMG_0013.MOV: Apple Log, which needs a LUT; a copy would look '
        'flat'
    ) in log
    assert 'Done: 10 of 10 converted in' in log
    assert '!' not in log
    assert run.mac.skipped == (
        'Skipped 1 slo-mo video(s), 1 Apple Log video(s).'
    )


def test_codec_container_and_sound(run, tools):
    for key, path in run.copies.items():
        assert path.suffix == '.mp4'
        video, audio = probe(tools, path)
        if run.codec == 'h265':
            assert (video['codec_name'], video['codec_tag_string']) == (
                'hevc',
                'hvc1',
            )
            assert video['profile'] == 'Main 10'
        else:
            assert (video['codec_name'], video['codec_tag_string']) == (
                'av1',
                'av01',
            )

        # 10 bits, as our ffprobe reads AV1 too (FFmpeg's AV1 decoder)
        assert video['pix_fmt'] == 'yuv420p10le'

        if key == 'silent':
            assert audio == []
        else:
            assert len(audio) == 1, key
            assert (
                audio[0]['codec_name'],
                audio[0]['sample_rate'],
                audio[0]['channels'],
            ) == ('opus', '48000', 2)


def rotation(stream):
    for side in stream.get('side_data_list', []):
        if 'rotation' in side:
            return side['rotation']

    return 0


def test_size_limit_and_rotation(run, tools):
    # The long edge at most 1280 (720p), whatever the orientation; never
    # enlarged; the rotation flag as it was (the frame as stored).
    sizes = {}
    for key, path in run.copies.items():
        video, _ = probe(tools, path)
        sizes[key] = (video['width'], video['height'], rotation(video))

    assert sizes['big'] == (1280, 720, -90)  # shown 720x1280
    assert sizes['four_three'] == (1280, 960, 0)
    assert sizes['sdr'] == (320, 180, -90)
    for key in ('hlg', 'two', 'silent', 'ntsc', 'bare', 'fast', 'prores'):
        assert sizes[key] == (320, 180, 0), key


def test_color_tags(run, tools):
    # HLG, from HEVC and from ProRes (4:2:2, made 4:2:0 by -pix_fmt)
    for key in ('hlg', 'prores'):
        hlg, _ = probe(tools, run.copies[key])
        assert (
            hlg['color_primaries'],
            hlg['color_transfer'],
            hlg['color_space'],
            hlg['color_range'],
        ) == (
            'bt2020',
            'arib-std-b67',
            'bt2020nc',
            'tv',
        ), key

    sdr, _ = probe(tools, run.copies['sdr'])
    assert (
        sdr['color_primaries'],
        sdr['color_transfer'],
        sdr['color_space'],
    ) == ('bt709', 'bt709', 'bt709')


def test_frame_rate_and_duration(run, tools):
    for key, path in run.copies.items():
        video, _ = probe(tools, path)
        original, _ = probe(tools, run.videos[key])
        assert (
            abs(float(video['duration']) - float(original['duration'])) < 0.05
        ), key
        num, den = map(int, video['avg_frame_rate'].split('/'))
        if key == 'ntsc':
            assert abs(num / den - 29.95) < 0.1
        elif key == 'fast':
            assert abs(num / den - 120) < 0.5


def test_the_copys_size_in_the_log(run):
    # ffprobe's size of the copy, not a prediction
    line = next(
        l
        for l in run.mac.log.splitlines()
        if l.startswith('  ') and ' → ' in l
    )
    assert ', 320×180, ' in line


def test_the_stereo_track_is_chosen(run):
    # 'two' has a 5.1 track, then a stereo one: the stereo one is converted.
    log = run.mac.log
    line = next(l for l in log.splitlines() if ' -i in/IMG_0003.MOV ' in l)
    assert ' -map 0:2 ' in line and ' -ac 2' not in line


def test_apple_keys_as_avfoundation_reads_them(run, helpers):
    # Every key of the original, on the movie and on the video track, with
    # its value and its data type; nothing else (ffmpeg's own tags and unnamed
    # itsk/ entries are gone); playable; the same rotation and creation date.
    for key, path in run.copies.items():
        original = vh.avmeta(helpers['avmeta'], run.videos[key])
        copy = vh.avmeta(helpers['avmeta'], path)
        assert copy['playable'] is True, key
        assert copy['metadata'] == original['metadata'], key
        assert copy.get('creationDate') == original.get('creationDate'), key
        assert 'itsk' not in repr(copy), key
        o_video = next(
            t for t in original['tracks'] if t['mediaType'] == 'vide'
        )
        c_video = next(t for t in copy['tracks'] if t['mediaType'] == 'vide')
        assert c_video.get('metadata', {}) == o_video.get('metadata', {}), key
        assert c_video['rotation'] == o_video['rotation'], key
        assert c_video['BitsPerComponent'] == 10, key
        if key != 'bare':
            assert set(copy['metadata']) == set(vh.MOVIE_KEYS)
            assert set(c_video['metadata']) == set(vh.TRACK_KEYS)


def test_hdr_and_dolby_vision(run, helpers, tools):
    original = vh.avmeta(helpers['avmeta'], run.videos['hlg'])
    copy = vh.avmeta(helpers['avmeta'], run.copies['hlg'])
    o_video = next(t for t in original['tracks'] if t['mediaType'] == 'vide')
    c_video = next(t for t in copy['tracks'] if t['mediaType'] == 'vide')
    assert c_video['hdr'] is True
    assert c_video['CVImageBufferTransferFunction'] == 'ITU_R_2100_HLG'
    if 'dvvC' not in o_video.get('atoms', []):
        pytest.skip("this Mac's AVFoundation writes HLG without Dolby Vision")

    # Dolby Vision kept, as Apple's players see it (the dvvC box) and as
    # ffprobe reads it (profile 8 for H.265, 10 for AV1).
    assert 'dvvC' in c_video['atoms']
    video, _ = probe(tools, run.copies['hlg'])
    record = next(
        s
        for s in video['side_data_list']
        if s['side_data_type'] == 'DOVI configuration record'
    )
    assert record['dv_profile'] == (8 if run.codec == 'h265' else 10)
    assert record['rpu_present_flag'] == 1
    assert 'Dolby Vision kept' in run.mac.log


def test_dolby_vision_rpu_in_every_frame(run, tools, videos):
    if run.codec != 'h265':
        pytest.skip("RPUs are counted in HEVC's NAL units")

    ffmpeg = vh.homebrew('ffmpeg')
    vh.need(ffmpeg, "Homebrew's ffmpeg (trace_headers) is needed")

    def rpus(path):
        result = vh.run([
            ffmpeg,
            '-v',
            'trace',
            '-i',
            path,
            '-map',
            '0:v:0',
            '-c:v',
            'copy',
            '-bsf:v',
            'trace_headers',
            '-f',
            'null',
            '-',
        ])
        return result.stderr.count('nal_unit_type: 62(UNSPEC62)')

    original = rpus(videos['hlg'])
    if original == 0:
        pytest.skip("this Mac's AVFoundation writes HLG without Dolby Vision")

    assert rpus(run.copies['hlg']) == original == 60


def luma(ffmpeg, path, size, frames=10):
    """The first frames' luma, scaled to ``size`` (the frames as stored)."""
    width, height = size
    result = subprocess.run(
        [
            str(ffmpeg),
            '-v',
            'error',
            '-noautorotate',
            '-i',
            str(path),
            '-frames:v',
            str(frames),
            '-vf',
            f'scale={width}:{height}',
            '-f',
            'rawvideo',
            '-pix_fmt',
            'gray',
            '-',
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    return (
        np
        .frombuffer(result.stdout, np.uint8)
        .reshape(-1, height, width)
        .astype(float)
    )


@pytest.mark.parametrize('key', ['sdr', 'big', 'hlg', 'prores'])
def test_the_picture(run, tools, key):
    # PSNR of the luma against the original scaled to the copy's size.
    ffmpeg = vh.homebrew('ffmpeg')
    vh.need(ffmpeg, "Homebrew's ffmpeg (every decoder) is needed")
    video, _ = probe(tools, run.copies[key])
    size = (video['width'], video['height'])
    a = luma(ffmpeg, run.videos[key], size)
    b = luma(ffmpeg, run.copies[key], size)
    assert a.shape == b.shape
    mse = np.mean((a - b) ** 2)
    psnr = 99.0 if mse == 0 else 10 * np.log10(255.0**2 / mse)
    assert psnr >= MIN_PSNR, psnr


@pytest.mark.parametrize('codec', ['h265', 'av1'])
def test_an_av1_video_converts_again(tmp_path, actions, tools, videos, codec):
    # An AV1 video (a copy this shortcut made, say) is decoded in software,
    # with dav1d (FFmpeg's own AV1 decoder works only with a hardware
    # accelerator), and converted again.
    source = tmp_path / 'av1.mp4'
    result = vh.run([
        tools['ffmpeg'],
        '-v',
        'error',
        '-i',
        videos['sdr'],
        '-map',
        '0:v:0',
        '-map',
        '0:a:0',
        '-c:v',
        'libsvtav1',
        '-preset',
        '10',
        '-crf',
        '40',
        '-pix_fmt',
        'yuv420p10le',
        '-c:a',
        'libopus',
        source,
    ])
    assert result.returncode == 0, result.stderr
    mac = vh.Mac(tmp_path / 'mac', actions, tools)
    mac.export(source, 'IMG_0011.mp4')
    lines = mac.convert(
        'ID|IMG_0011.mp4', Size='720p', Audio='96', **SETTINGS[codec]
    )
    assert len(lines) == 1, mac.log
    assert '!' not in mac.log, mac.log
    video, audio = probe(tools, Path(lines[0].split('|')[0]))
    assert video['codec_name'] == ('hevc' if codec == 'h265' else 'av1')
    assert video['pix_fmt'] == 'yuv420p10le'
    assert [a['codec_name'] for a in audio] == ['opus']


def test_fixtures_have_an_iphones_keys(videos, helpers):
    # The test videos carry the keys and types an iPhone 17 Pro writes
    # (docs/compress-videos-mac-design.md, 4.5).
    meta = vh.avmeta(helpers['avmeta'], videos['sdr'])
    assert {k: v['type'] for k, v in meta['metadata'].items()} == vh.MOVIE_KEYS
    track = next(t for t in meta['tracks'] if t['mediaType'] == 'vide')
    assert {
        k: v['type'] for k, v in track['metadata'].items()
    } == vh.TRACK_KEYS
    bare = vh.avmeta(helpers['avmeta'], videos['bare'])
    assert bare['metadata'] == {}
