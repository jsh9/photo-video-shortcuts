"""
The Mac shortcut's conversion script (scripts/mac/*.zsh, as Run Shell Script
gets it), run for real with zsh and stand-ins for ffmpeg, ffprobe and vidmeta
that answer its questions, describe the "videos" (ffprobe's output, written by
each test) and record their arguments: the exact ffmpeg command for every
choice the lists allow (HandBrake's settings, the table below), Dolby Vision,
the frame rate's keyframe interval, the sound track, the skip rules, the checks
of the copy, the tools and their versions, the free space, the settings, the
log, the result lines, the progress window and the finish step.
test_conversion.py runs it with the real tools.
"""

import itertools
import re
import subprocess

import pytest
import video_helpers as vh

LIMITS = {'4K': 3840, '2K': 2560, '1080p': 1920, '720p': 1280}

FAKE_FFMPEG = r"""#!/bin/zsh
# Stands in for ffmpeg: answers the script's questions; a conversion records
# its arguments (calls/N.txt, one per line), prints progress, writes a file.
dir=${0:A:h}
case " $* " in
  *" -version "*)
    print -r -- "ffmpeg version ${FAKE_VERSION:-9.0.2-compress-videos-0.1.0} Copyright (c) 2000-2026 the FFmpeg developers"
    exit 0;;
  *" -encoders "*)
    print -r -- "Encoders:"
    for e in libx265 libsvtav1 libopus; do
      [[ " ${FAKE_NO_ENCODERS-} " == *" $e "* ]] || print -r -- " V....D $e             $e"
    done
    exit 0;;
  *" -decoders "*)
    print -l "Decoders:" " V..... = Video" " ------" " V....D hevc   HEVC" " V....D h264   H.264" " A....D aac    AAC" " A....D alac   ALAC"
    exit 0;;
  *" -h "*)
    [ -n "${FAKE_NO_DOVI-}" ] || print -r -- "  -dolbyvision       <boolean>    E..V....... Enable Dolby Vision RPU coding"
    exit 0;;
esac
mkdir -p "$dir/calls"
n=$(( $(ls "$dir/calls" | wc -l) + 1 ))
print -rl -- "$@" > "$dir/calls/$n.txt"
print "frame=30\nfps=30.00\nout_time_us=1000000\nspeed=1.0x\nprogress=continue"
print "frame=60\nfps=30.00\nout_time_us=2000000\nspeed=1.0x\nprogress=end"
if [ -n "${FAKE_FAIL-}" ]; then
  print -u2 "Conversion failed!"
  exit 1
fi
print -r -- "a converted video" > "${@[-1]}"
"""
FAKE_FFPROBE = r"""#!/bin/zsh
# Stands in for ffprobe: the description the test wrote (probes/NAME.txt),
# and for the check of a copy, probes/output.txt or a 10-bit HEVC video.
dir=${0:A:h}
if [[ " $* " == *" -select_streams v:0 "* ]]; then
  if [ -f "$dir/probes/output.txt" ]; then cat "$dir/probes/output.txt"
  else print "codec_name=hevc\npix_fmt=yuv420p10le\nduration=5.000000"
  fi
  exit 0
fi
probe="$dir/probes/${@[-1]:t}.txt"
[ -f "$probe" ] || exit 1
cat "$probe"
"""
FAKE_VIDMETA = r"""#!/bin/zsh
# Stands in for vidmeta.
dir=${0:A:h}
case $1 in
  --version) print -r -- "vidmeta ${FAKE_VIDMETA_VERSION:-@VERSION@}";;
  copy)
    print -r -- "copy $2 $3" >> "$dir/vidmeta.txt"
    if [ -n "${FAKE_VIDMETA_FAIL-}" ]; then
      print -u2 "vidmeta: the moov box isn't at the end of $3"
      exit 1
    fi
    print "copied 2 boxes";;
esac
"""


def probe_text(
        width=3840,
        height=2160,
        rate='30/1',
        avg=None,
        frames=150,
        duration='5.000000',
        pix='yuv420p10le',
        transfer='arib-std-b67',
        side=(),
        profile='Main 10',
        audio=(('aac', 2), ('apple_apac', 4)),
        videos=1,
):
    """
    ffprobe's compact output (-of compact=p=0) for a video, as the script asks
    it.
    """
    lines = []
    index = 0
    for _ in range(videos):
        fields = [
            f'index={index}',
            'codec_name=hevc',
            f'profile={profile}',
            'codec_type=video',
            f'width={width}',
            f'height={height}',
            f'pix_fmt={pix}',
            f'color_transfer={transfer}',
            f'r_frame_rate={rate}',
            f'avg_frame_rate={avg or rate}',
            f'nb_frames={frames}',
            f'duration={duration}',
        ] + [f'side_datum/s{k}:side_data_type={t}' for k, t in enumerate(side)]
        lines.append('|'.join(fields))
        index += 1

    for codec, channels in audio:
        lines.append(
            f'index={index}|codec_name={codec}|codec_type=audio|channels={channels}'
            f'|r_frame_rate=0/0|avg_frame_rate=0/0|nb_frames=96|duration={duration}|'
        )
        index += 1

    lines.append(f'duration={duration}')
    return '\n'.join(lines) + '\n'


DOVI = 'DOVI configuration record'


class Fake:
    """The stand-in tools in <root>/bin, and what they recorded."""

    def __init__(self, root):
        self.bin = root / 'bin'
        (self.bin / 'probes').mkdir(parents=True)
        for name, text in (
            ('ffmpeg', FAKE_FFMPEG),
            ('ffprobe', FAKE_FFPROBE),
            ('vidmeta', FAKE_VIDMETA.replace('@VERSION@', vh.VERSION)),
        ):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)

    @property
    def tools(self):
        return {n: self.bin / n for n in ('ffmpeg', 'ffprobe', 'vidmeta')}

    def describe(self, name, **probe):
        (self.bin / 'probes' / f'{name}.txt').write_text(probe_text(**probe))

    def output(self, codec='hevc', pix='yuv420p10le', duration='5.000000'):
        (self.bin / 'probes' / 'output.txt').write_text(
            f'codec_name={codec}\npix_fmt={pix}\nduration={duration}\n'
        )

    def calls(self):
        folder = self.bin / 'calls'
        if not folder.exists():
            return []

        return [
            (folder / f'{n}.txt').read_text().splitlines()
            for n in range(1, len(list(folder.iterdir())) + 1)
        ]

    @property
    def vidmeta(self):
        path = self.bin / 'vidmeta.txt'
        return path.read_text().splitlines() if path.exists() else []


@pytest.fixture
def fake(tmp_path):
    return Fake(tmp_path)


@pytest.fixture
def mac(tmp_path, actions, fake):
    return vh.Mac(tmp_path, actions, fake.tools)


def video(mac, fake, name, **probe):
    """
    A video Photos exported (a stand-in file, and what ffprobe says of it).
    """
    path = mac.work / 'in' / name
    path.write_bytes(b'v' * 1000)
    fake.describe(name, **probe)
    return path


def expected(
        mac,
        fake,
        name,
        n,
        codec,
        preset,
        tune,
        rf,
        size,
        kbps,
        *,
        audio='0:1',
        ac2=False,
        keyint=30,
        vbv=None,
        dovi=False,
):
    """
    The ffmpeg command HandBrake's settings make (docs/compress-videos-mac-
    design.md, 4.2), after ``nice -n 10 ffmpeg``.
    """
    limit = LIMITS[size]
    cmd = [
        '-hide_banner',
        '-nostdin',
        '-v',
        'warning',
        '-nostats',
        '-progress',
        'pipe:1',
        '-y',
        '-noautorotate',
        '-i',
        str(mac.work / 'in' / name),
        '-map',
        '0:v:0',
    ]
    if audio:
        cmd += ['-map', audio]

    cmd += [
        '-map_metadata',
        '-1',
        '-fps_mode',
        'passthrough',
        '-vf',
        f"scale=w='min(iw,{limit})':h='min(ih,{limit})':force_original_aspect_ratio=decrease:force_divisible_by=2",
    ]
    if codec == 'h265':
        cmd += ['-c:v', 'libx265', '-preset', preset, '-crf', str(rf)]
        if tune == 'grain':
            cmd += ['-tune', 'grain']

        params = f'keyint={10 * keyint}:min-keyint={keyint}'
        if vbv:
            params += f':vbv-bufsize={vbv}:vbv-maxrate={vbv}'

        cmd += ['-profile:v', 'main10', '-pix_fmt', 'yuv420p10le']
        cmd += ['-x265-params', params]
        if dovi:
            cmd += ['-dolbyvision', '1', '-strict', 'unofficial']

        cmd += ['-tag:v', 'hvc1']
    else:
        cmd += [
            '-c:v',
            'libsvtav1',
            '-preset',
            preset,
            '-crf',
            str(rf),
            '-pix_fmt',
            'yuv420p10le',
            '-svtav1-params',
            'tune=0:enable-variance-boost=1:film-grain=8',
        ]
        if dovi:
            cmd += ['-dolbyvision', '1', '-strict', 'unofficial']

    if audio:
        cmd += ['-c:a', 'libopus', '-b:a', f'{kbps}k']
        if ac2:
            cmd += ['-ac', '2']
    else:
        cmd += ['-an']

    return cmd + [str(mac.work / f'vid_out_{n}.mp4')]


def choices():
    """
    Every preset x tune x size of each codec, with the RF and audio lists'
    values in turn, so that every value of every list is used.
    """
    vf = vh.load_generator('vf')
    rfs = itertools.cycle(vf.RF_VALUES)
    kbps = itertools.cycle(k for k, _ in vf.AUDIO_KBPS)
    out = []
    for codec in ('h265', 'av1'):
        tunes = [v for _, v in vf.TUNES] if codec == 'h265' else ['']
        for preset, _ in vf.PRESETS[codec]:
            for tune in tunes:
                for size, _ in vf.SIZES:
                    out.append((
                        codec,
                        preset,
                        tune,
                        next(rfs),
                        size,
                        next(kbps),
                    ))

    return out


@pytest.mark.parametrize(
    'choice', choices(), ids=lambda c: '-'.join(map(str, c))
)
def test_command_for_every_choice(mac, fake, choice):
    codec, preset, tune, rf, size, kbps = choice
    video(mac, fake, 'IMG_0001.MOV')
    if codec == 'av1':
        fake.output(codec='av1', pix='unknown')

    lines = mac.convert(
        'A1|IMG_0001.MOV',
        Codec=codec,
        Preset=preset,
        Tune=tune,
        RF=str(rf),
        Size=size,
        Audio=str(kbps),
    )
    assert fake.calls() == [
        expected(
            mac, fake, 'IMG_0001.MOV', 1, codec, preset, tune, rf, size, kbps
        )
    ]
    assert lines == [f'{mac.work}/out/IMG_0001.mp4|A1|delete|IMG_0001.mp4']


@pytest.mark.parametrize(
    ('size', 'width', 'height', 'rate', 'vbv'),
    [
        # HandBrake's hb_dovi_levels, high tier: the first level the copy's
        # width and pixels per second fit
        ('4K', 3840, 2160, '30/1', 130000),  # level 7
        ('4K', 3840, 2160, '60/1', 130000),  # level 9
        ('2K', 3840, 2160, '30/1', 70000),  # 2560x1440: level 5
        ('1080p', 3840, 2160, '30/1', 70000),  # 1920x1080: level 4
        ('720p', 3840, 2160, '30/1', 50000),  # 1280x720: level 2
        ('4K', 1920, 1080, '30000/1001', 70000),  # never enlarged: level 4
    ],
)
def test_dolby_vision_with_hand_brakes_vbv(
        mac, fake, size, width, height, rate, vbv
):
    video(
        mac,
        fake,
        'IMG_0001.MOV',
        width=width,
        height=height,
        rate=rate,
        side=[DOVI],
    )
    mac.convert('A1|IMG_0001.MOV', Size=size)
    keyint = round(eval(rate))
    assert fake.calls() == [
        expected(
            mac,
            fake,
            'IMG_0001.MOV',
            1,
            'h265',
            'medium',
            'none',
            24,
            size,
            160,
            keyint=keyint,
            vbv=vbv,
            dovi=True,
        )
    ]
    assert 'Dolby Vision kept' in mac.log


def test_dolby_vision_with_av1_and_switched_off(mac, fake):
    video(mac, fake, 'IMG_0001.MOV', side=[DOVI])
    fake.output(codec='av1', pix='unknown')
    mac.convert('A1|IMG_0001.MOV', Codec='av1', Preset='5', Tune='', RF='30')
    assert fake.calls()[0] == expected(
        mac, fake, 'IMG_0001.MOV', 1, 'av1', '5', '', 30, '2K', 160, dovi=True
    )
    # DOLBY=0: converted as plain HDR, without the options
    mac2 = vh.Mac(mac.root / 'second', mac.actions, fake.tools)
    (fake.bin / 'calls').rename(fake.bin / 'calls-av1')
    (fake.bin / 'probes' / 'output.txt').unlink()
    video(mac2, fake, 'IMG_0001.MOV', side=[DOVI])
    mac2.convert('A1|IMG_0001.MOV', env={'DOLBY': '0'})
    assert fake.calls()[0] == expected(
        mac2, fake, 'IMG_0001.MOV', 1, 'h265', 'medium', 'none', 24, '2K', 160
    )
    assert 'Dolby Vision kept' not in mac2.log


@pytest.mark.parametrize(
    ('rate', 'avg', 'keyint'),
    [
        ('30/1', None, 30),
        ('30000/1001', None, 30),
        ('60/1', None, 60),
        ('24/1', None, 24),
        ('25/1', None, 25),
        ('150/1', '2760/97', 28),  # variable rate: the average counts
    ],
)
def test_keyframe_interval_from_the_frame_rate(mac, fake, rate, avg, keyint):
    # HandBrake: keyint = 10 x the rounded frame rate, min-keyint = the rate.
    video(mac, fake, 'IMG_0001.MOV', rate=rate, avg=avg)
    mac.convert('A1|IMG_0001.MOV')
    params = fake.calls()[0][fake.calls()[0].index('-x265-params') + 1]
    assert params == f'keyint={10 * keyint}:min-keyint={keyint}'


@pytest.mark.parametrize(
    ('audio', 'mapped', 'ac2'),
    [
        ((('aac', 2), ('apple_apac', 4)), '0:1', False),  # an iPhone's
        ((('aac', 6), ('aac', 2)), '0:2', False),  # stereo first
        ((('aac', 6),), '0:1', True),  # mixed down to stereo
        ((('apple_apac', 4), ('alac', 1)), '0:2', False),  # a readable one
        ((), None, False),  # no sound: none in the copy
    ],
)
def test_sound_track_choice(mac, fake, audio, mapped, ac2):
    video(mac, fake, 'IMG_0001.MOV', audio=audio)
    mac.convert('A1|IMG_0001.MOV')
    assert fake.calls() == [
        expected(
            mac,
            fake,
            'IMG_0001.MOV',
            1,
            'h265',
            'medium',
            'none',
            24,
            '2K',
            160,
            audio=mapped,
            ac2=ac2,
        )
    ]


def test_skip_rules(mac, fake):
    # Exported files: a Live Photo (a photo, and a .mov that isn't an item of
    # its own), a photo, a video whose name stem a photo item shares, another
    # file; probed videos: slo-mo (by its capture rate or its average), spatial,
    # sound ffmpeg can't read, Dolby Vision this ffmpeg can't carry.
    ids = '\n'.join(
        f'{i}|{n}'
        for i, n in enumerate([
            'IMG_0001.HEIC',
            'IMG_0002.JPG',
            'IMG_0003.MOV',
            'IMG_0003.HEIC',
            'IMG_0004.MOV',
            'IMG_0005.MOV',
            'IMG_0006.MOV',
            'IMG_0007.MOV',
            'IMG_0008.MOV',
            'notes.txt',
        ])
    )
    (mac.work / 'in' / 'IMG_0001.HEIC').write_bytes(b'photo')
    (mac.work / 'in' / 'IMG_0001.mov').write_bytes(b'live')
    (mac.work / 'in' / 'IMG_0002.JPG').write_bytes(b'photo')
    (mac.work / 'in' / 'IMG_0003.HEIC').write_bytes(b'photo')
    video(mac, fake, 'IMG_0003.MOV')
    video(mac, fake, 'IMG_0004.MOV', rate='240/1', avg='291200/1649')
    video(mac, fake, 'IMG_0005.MOV', rate='120/1', avg='120/1')
    video(mac, fake, 'IMG_0006.MOV', side=['Stereo 3D'])
    video(mac, fake, 'IMG_0007.MOV', audio=(('apple_apac', 4),))
    video(mac, fake, 'IMG_0008.MOV', side=[DOVI])
    (mac.work / 'in' / 'notes.txt').write_text('x')
    lines = mac.convert(ids, env={'FAKE_NO_DOVI': '1'})
    assert [c[c.index('-i') + 1] for c in fake.calls()] == [
        str(mac.work / 'in' / 'IMG_0003.MOV')
    ]
    assert lines == [f'{mac.work}/out/IMG_0003.mp4|2|delete|IMG_0003.mp4']
    assert mac.skipped == (
        'Skipped 2 photo(s), 1 Live Photo(s), 2 slo-mo video(s), 1 spatial video(s), '
        "1 video(s) whose sound can't be read, 1 Dolby Vision video(s), 1 other file(s)."
    )
    log = mac.log
    for line in (
        'Skipped IMG_0001.HEIC: a Live Photo',
        'Skipped IMG_0002.JPG: a photo',
        'Skipped IMG_0003.HEIC: a photo',
        'Skipped IMG_0004.MOV: slo-mo (177 fps on average); a copy would play at normal speed',
        'Skipped IMG_0005.MOV: slo-mo (120 fps on average)',
        'Skipped IMG_0006.MOV: spatial video; a copy would keep one view only',
        "Skipped IMG_0007.MOV: this ffmpeg can't read its sound; a copy would be silent",
        "Skipped IMG_0008.MOV: Dolby Vision, which this ffmpeg can't carry",
        'Skipped notes.txt: not a video',
        '! /',  # the note that this ffmpeg can't carry Dolby Vision
    ):
        assert line in log, line

    assert mac.skipped in log


def test_without_ids_a_photo_and_its_mov_are_a_live_photo(mac, fake):
    # When Photos' export failed to list the items, a .mov next to a photo of
    # the same name is taken for a Live Photo's.
    (mac.work / 'in' / 'IMG_0001.HEIC').write_bytes(b'photo')
    video(mac, fake, 'IMG_0001.MOV')
    video(mac, fake, 'IMG_0002.MOV')
    lines = mac.convert('ERROR: Photos could not export the selected photos')
    assert lines == [f'{mac.work}/out/IMG_0002.mp4||delete|IMG_0002.mp4']
    assert mac.log.startswith('Settings: ')
    assert 'ERROR: Photos could not export' in mac.log
    assert mac.skipped == 'Skipped 1 Live Photo(s).'


def test_result_lines_ids_and_names(mac, fake):
    # Two items with one name: neither gets an id (no albums, not collected);
    # names that become the same copy name get "2".
    video(mac, fake, 'IMG_0001.MOV')
    video(mac, fake, 'IMG_0001.mp4')
    video(mac, fake, 'IMG_0002 (1).MOV')
    video(mac, fake, 'IMG_0003.MOV')
    lines = mac.convert(
        'A|IMG_0001.MOV\nB|IMG_0001.MOV\nC|IMG_0002 (1).MOV\nD|IMG_0003.MOV\n'
    )
    out = mac.work / 'out'
    assert lines == [
        f'{out}/IMG_0001.mp4||delete|IMG_0001.mp4',
        f'{out}/IMG_0001 2.mp4||delete|IMG_0001 2.mp4',
        f'{out}/IMG_0002 (1).mp4|C|delete|IMG_0002 (1).mp4',
        f'{out}/IMG_0003.mp4|D|delete|IMG_0003.mp4',
    ]
    assert (
        mac.log.count('! two or more selected items are named IMG_0001.MOV')
        == 1
    )
    # vidmeta copied each original's metadata onto its copy
    assert fake.vidmeta == [
        f'copy {mac.work}/in/{name} {mac.work}/vid_out_{n}.mp4'
        for n, name in enumerate(
            [
                'IMG_0001.MOV',
                'IMG_0001.mp4',
                'IMG_0002 (1).MOV',
                'IMG_0003.MOV',
            ],
            1,
        )
    ]
    assert (mac.work / 'vid_done.txt').read_text() == (
        'vid_out_1.mp4|1|delete|IMG_0001.mp4\n'
        'vid_out_2.mp4|2|delete|IMG_0001.mp4\n'
        'vid_out_3.mp4|3|delete|IMG_0002 (1).mp4\n'
        'vid_out_4.mp4|4|delete|IMG_0003.mp4\n'
    )


def test_nothing_to_convert(mac, fake, gen):
    (mac.work / 'in' / 'IMG_0001.HEIC').write_bytes(b'photo')
    assert mac.convert('A|IMG_0001.HEIC') == []
    assert 'Nothing to convert: no videos among the selected items.' in mac.log
    assert not re.search(gen.WARNINGS, mac.log)
    assert fake.calls() == []


@pytest.mark.parametrize(
    ('output', 'message'),
    [
        ({'duration': '1.000000'}, '! only 20% of the video was written'),
        ({'pix': 'yuv420p'}, '! the copy is not 10-bit (yuv420p)'),
        ({'codec': 'h264'}, '! the copy has no hevc video'),
    ],
)
def test_a_copy_that_fails_the_check(mac, fake, gen, output, message):
    video(mac, fake, 'IMG_0001.MOV')
    video(mac, fake, 'IMG_0002.MOV')
    fake.output(**output)
    assert mac.convert('A|IMG_0001.MOV\nB|IMG_0002.MOV') == []
    log = mac.log
    assert log.count(message) == 2
    assert 'Done: 0 of 2 converted' in log
    assert '2 failed; see the messages above.' in log
    assert re.search(gen.WARNINGS, log)
    assert not list(mac.work.glob('vid_out_*'))
    assert fake.vidmeta == []


def test_ffmpeg_and_vidmeta_failures(mac, fake):
    video(mac, fake, 'IMG_0001.MOV')
    assert mac.convert('A|IMG_0001.MOV', env={'FAKE_FAIL': '1'}) == []
    assert '  ! ffmpeg could not convert it (exit status 1)' in mac.log
    assert '  Conversion failed!' in mac.log  # ffmpeg's own message
    assert not (mac.work / 'vid_out_1.mp4').exists()
    assert mac.convert('A|IMG_0001.MOV', env={'FAKE_VIDMETA_FAIL': '1'}) == []
    assert (
        "  ! the metadata could not be copied: vidmeta: the moov box isn't at the end of"
        in mac.log
    )
    assert not (mac.work / 'vid_out_2.mp4').exists()


def test_av1_copy_without_a_pixel_format(mac, fake):
    # Our ffprobe has no AV1 decoder and can't tell AV1's pixel format.
    video(mac, fake, 'IMG_0001.MOV')
    fake.output(codec='av1', pix='unknown')
    assert (
        len(
            mac.convert(
                'A|IMG_0001.MOV', Codec='av1', Preset='5', Tune='', RF='30'
            )
        )
        == 1
    )
    fake.output(codec='av1', pix='yuv420p')
    assert (
        mac.convert(
            'A|IMG_0001.MOV', Codec='av1', Preset='5', Tune='', RF='30'
        )
        == []
    )
    assert '! the copy is not 10-bit (yuv420p)' in mac.log


def without_homebrew(script):
    """The script with only the pretend home's tool folders."""
    for tool in ('ffmpeg', 'vidmeta'):
        script = script.replace(
            f'"/opt/homebrew/bin/{tool}" "/usr/local/bin/{tool}"', ''
        )

    return script


def test_tools_found_in_the_users_folders(mac, fake):
    # ~/.local/bin first; ffprobe next to ffmpeg.
    local = mac.home / '.local' / 'bin'
    local.mkdir(parents=True)
    for name, installed in (
        ('ffmpeg', 'compress-videos-ffmpeg'),
        ('ffprobe', 'compress-videos-ffprobe'),
        ('vidmeta', 'vidmeta'),
    ):
        (local / installed).symlink_to(fake.bin / name)

    video(mac, fake, 'IMG_0001.MOV')
    env = mac.env()
    for name in ('FFMPEG', 'FFPROBE', 'VIDMETA'):
        del env[name]

    result = subprocess.run(
        [
            'zsh',
            '-c',
            without_homebrew(mac.conversion('A|IMG_0001.MOV')),
            'zsh',
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith('|A|delete|IMG_0001.mp4\n')
    assert (
        f'ffmpeg: {local}/compress-videos-ffmpeg (9.0.2-compress-videos-{vh.VERSION}'
        in mac.log
    )


@pytest.mark.parametrize(
    ('missing', 'message'),
    [
        (
            'ffmpeg',
            'ERROR: ffmpeg is not installed (looked in ~/.local/bin/compress-videos-ffmpeg, ~/bin/compress-videos-ffmpeg, /opt/homebrew/bin/ffmpeg, /usr/local/bin/ffmpeg).',
        ),
        (
            'ffprobe',
            '/ffprobe is missing: it must be next to ',
        ),
        (
            'vidmeta',
            'ERROR: vidmeta is not installed (looked in ~/.local/bin/vidmeta',
        ),
    ],
)
def test_missing_tools(mac, fake, missing, message):
    video(mac, fake, 'IMG_0001.MOV')
    env = mac.env()
    env[missing.upper()] = '/nonexistent'
    if missing == 'ffprobe':
        del env['FFPROBE']  # then the one next to ffmpeg: there is none

        (fake.bin / 'ffprobe').rename(fake.bin / 'ffprobe-elsewhere')

    result = subprocess.run(
        [
            'zsh',
            '-c',
            without_homebrew(mac.conversion('A|IMG_0001.MOV')),
            'zsh',
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, '', '')
    assert message in mac.log
    assert 'compress-videos/README.md' in mac.log
    assert fake.calls() == []


@pytest.mark.parametrize(
    ('version', 'note'),
    [
        ('6.1.1', 'ERROR: '),  # too old: no -dolbyvision, older wrappers
        ('7.0', 'ERROR: '),
        ('7.1', None),
        ('8.0.1', None),
        ('N-118000-g1234abcd', '! could not read the version of'),
    ],
)
def test_ffmpeg_version(mac, fake, version, note):
    video(mac, fake, 'IMG_0001.MOV')
    lines = mac.convert('A|IMG_0001.MOV', env={'FAKE_VERSION': version})
    if note == 'ERROR: ':
        assert lines == []
        assert 'ERROR: ' in mac.log and '7.1 or later is needed' in mac.log
    else:
        assert len(lines) == 1
        assert (note in mac.log) if note else ('!' not in mac.log)


def test_encoders_and_dolby_vision_support(mac, fake):
    video(mac, fake, 'IMG_0001.MOV')
    assert (
        mac.convert(
            'A|IMG_0001.MOV',
            Codec='av1',
            Preset='5',
            Tune='',
            RF='30',
            env={'FAKE_NO_ENCODERS': 'libsvtav1'},
        )
        == []
    )
    assert 'has no libsvtav1 encoder' in mac.log
    assert (
        len(
            mac.convert(
                'A|IMG_0001.MOV', env={'FAKE_NO_ENCODERS': 'libsvtav1'}
            )
        )
        == 1
    )
    assert (
        mac.convert(
            'A|IMG_0001.MOV', env={'FAKE_NO_ENCODERS': 'libx265 libopus'}
        )
        == []
    )
    assert 'has no libx265 and libopus encoder' in mac.log
    mac.convert('A|IMG_0001.MOV', env={'FAKE_NO_DOVI': '1'})
    assert "can't carry Dolby Vision: videos with it are skipped" in mac.log
    mac.convert('A|IMG_0001.MOV', env={'FAKE_NO_DOVI': '1', 'DOLBY': '0'})
    assert "can't carry Dolby Vision" not in mac.log


def test_vidmeta_of_another_version_is_noted(mac, fake):
    video(mac, fake, 'IMG_0001.MOV')
    assert (
        len(
            mac.convert(
                'A|IMG_0001.MOV', env={'FAKE_VIDMETA_VERSION': '0.0.1'}
            )
        )
        == 1
    )
    assert (
        f'is not vidmeta {vh.VERSION}, the version this shortcut was made for'
        in mac.log
    )


def test_free_space(mac, fake, gen):
    # df says 1 KB is free: nothing is converted, and the log says why.
    video(mac, fake, 'IMG_0001.MOV')
    df = fake.bin / 'fakepath' / 'df'
    df.parent.mkdir()
    df.write_text(
        '#!/bin/sh\necho "Filesystem 1024-blocks Used Available Capacity Mounted on"\n'
        'echo "/dev/disk3s5 100 99 1 99% /"\n'
    )
    df.chmod(0o755)
    assert mac.convert('A|IMG_0001.MOV', path=df.parent) == []
    assert 'ERROR: not enough free space to convert 1 KB of videos' in mac.log
    assert 'Nothing to convert' not in mac.log
    assert fake.calls() == []
    assert re.search(gen.WARNINGS, mac.log)


def test_settings_saved_and_reused(mac, fake, vf):
    video(mac, fake, 'IMG_0001.MOV')
    mac.convert(
        'A|IMG_0001.MOV',
        Codec='h265',
        Preset='slow',
        Tune='grain',
        RF='20',
        Size='1080p',
        Audio='192',
    )
    settings = mac.logdir / 'last-settings.txt'
    assert settings.read_text() == (
        'CODEC=h265\nPRESET=slow\nTUNE=grain\nRF=20\nSIZE=1080p\nAUDIO=192\n'
        'SUMMARY=H.265 · preset slow · tune grain · RF 20 · 1080p · Opus 192 kbps\n'
    )
    # "Same as last time": the shortcut sets Reuse, and nothing else.
    first = fake.calls()[0]
    (fake.bin / 'calls').rename(fake.bin / 'calls-first')
    mac.convert(
        'A|IMG_0001.MOV',
        Codec='',
        Preset='',
        Tune='',
        RF='',
        Size='',
        Audio='',
        Reuse='1',
    )
    assert fake.calls()[0] == first
    assert mac.log.startswith(
        'Settings: H.265 · preset slow · tune grain · RF 20 · 1080p · Opus 192 kbps\n'
    )
    # AV1's summary has no tune
    mac.convert(
        'A|IMG_0001.MOV',
        Codec='av1',
        Preset='3',
        Tune='',
        RF='34',
        Size='720p',
        Audio='64',
    )
    assert (
        'SUMMARY=AV1 · preset 3 · RF 34 · 720p · Opus 64 kbps\n'
        in settings.read_text()
    )


@pytest.mark.parametrize(
    'settings',
    [
        {'Codec': 'h264'},
        {'Preset': 'veryslow'},
        {'Codec': 'av1', 'Preset': '8', 'Tune': ''},
        {'Tune': 'film'},
        {'RF': '99'},
        {'RF': 'x'},
        {'Size': '8K'},
        {'Audio': '1000'},
        {'Codec': '', 'Reuse': '1'},  # nothing to reuse yet
    ],
)
def test_unexpected_settings(mac, fake, settings):
    video(mac, fake, 'IMG_0001.MOV')
    assert mac.convert('A|IMG_0001.MOV', **settings) == []
    assert 'ERROR: unexpected ' in mac.log
    assert fake.calls() == []
    assert not (mac.logdir / 'last-settings.txt').exists()


def test_log_lines(mac, fake):
    video(
        mac,
        fake,
        'IMG_0001.MOV',
        side=[DOVI],
        rate='30000/1001',
        frames=300,
        videos=2,
    )
    video(
        mac,
        fake,
        'IMG_0002.MOV',
        width=1920,
        height=1080,
        pix='yuv420p',
        transfer='bt709',
        audio=(('aac', 6),),
    )
    mac.convert(
        'A|IMG_0001.MOV\nB|IMG_0002.MOV',
        env={'PROGRESS_EVERY': '0'},
        Size='1080p',
        Audio='128',
    )
    log = mac.log.splitlines()
    assert (
        log[0]
        == 'Settings: H.265 · preset medium · tune none · RF 24 · 1080p · Opus 128 kbps'
    )
    assert log[1].startswith('ffmpeg: ')
    first = log.index(
        '[1/2] IMG_0001.MOV  3840×2160 29.97 fps HLG 10-bit Dolby Vision, 1 KB → '
        '1920×1080 H.265 medium tune none RF 24, Opus 128 kbps, Dolby Vision kept'
    )
    assert (
        log[first + 1] == '  (it has 2 video tracks; the first is converted)'
    )
    assert log[first + 2].startswith(
        '  nice -n 10 ffmpeg -hide_banner -nostdin '
    )
    assert ' -i in/IMG_0001.MOV ' in log[first + 2]
    assert log[first + 2].endswith(' vid_out_1.mp4')
    assert (
        '''-vf "scale=w='min(iw,1920)':h='min(ih,1920)':force_original_aspect_ratio=decrease:force_divisible_by=2"'''
        in log[first + 2]
    )
    assert re.fullmatch(r'   10%  frame 30/300  30 fps.*', log[first + 3])
    assert re.fullmatch(
        r'  1 KB → 0 KB \(\d+%\), 0:0\d at [\d.]+× real time', log[first + 4]
    )
    assert (
        '[2/2] IMG_0002.MOV  1920×1080 30 fps, 1 KB → 1920×1080 H.265 medium tune none RF 24, '
        'Opus 128 kbps (stereo)'
    ) in log
    assert re.search(
        r'^Done: 2 of 2 converted in 0:0\d\.$', mac.log, re.MULTILINE
    )
    assert (
        log[-1]
        == 'Now Photos imports the videos, adds them to their albums and collects the originals...'
    )


def test_nice(mac, fake):
    video(mac, fake, 'IMG_0001.MOV')
    mac.convert('A|IMG_0001.MOV', env={'NICE': '0'})
    assert '  nice -n 0 ffmpeg ' in mac.log


def test_warnings_pattern(gen):
    pattern = re.compile(gen.WARNINGS)
    for text in (
        '  ! only 97% of the video was written',
        'ERROR: ffmpeg is not installed',
        'Done: 4 of 5 converted in 12:30.\n1 failed; see the messages above.',
        "x\n! /x/ffmpeg can't carry Dolby Vision",
    ):
        assert pattern.search(text), text

    for text in (
        'Done: 2 of 2 converted in 0:12.',
        'Skipped 1 photo(s), 1 slo-mo video(s).',
        'Skipped IMG_0004.MOV: slo-mo (177 fps on average); a copy would play at normal speed',
        '   34%  frame 2345/6900  28 fps  0.9×  ETA 2:40',
    ):
        assert not pattern.search(text), text


def test_follow_up_scripts(mac, fake):
    (mac.work / 'in' / 'IMG_0001.HEIC').write_bytes(b'photo')
    video(mac, fake, 'IMG_0002.MOV')
    mac.convert('A|IMG_0001.HEIC\nB|IMG_0002.MOV')
    show_log, skipped, finish = mac.follow_ups()
    assert mac.run(show_log).stdout == mac.log
    assert mac.run(skipped).stdout.strip() == 'Skipped 1 photo(s).'
    assert mac.run(finish, stdin='imported=1\ncollected=1').returncode == 0
    # in/ and the work files go; out/ stays (Photos may reference its files)
    assert not (mac.work / 'in').exists()
    assert not list(mac.work.glob('vid_*'))
    assert (mac.work / 'out' / 'IMG_0002.mp4').exists()
    assert mac.log.rstrip().endswith('imported=1\ncollected=1')
    # without a skipped list, the skipped script prints nothing
    assert mac.run(skipped).stdout == ''


def test_progress_window(mac, fake):
    # With WATCH=1, a Terminal window follows the log (a tail -f, its pid
    # recorded); the finish script appends the outcome and "Done" and ends it.
    video(mac, fake, 'IMG_0001.MOV')
    opener = fake.bin / 'fakeopen'
    opener.mkdir()
    (opener / 'open').write_text(
        f'#!/bin/sh\nprintf \'%s\\n\' "$@" >> "{mac.root}/opened.txt"\n'
    )
    (opener / 'open').chmod(0o755)
    mac.convert('A|IMG_0001.MOV', watch=True, path=opener)
    command = (mac.logdir / 'videos.command').read_text()
    assert command.startswith('#!/bin/zsh\necho $$ > ')
    assert '\nexec tail -n +1 -f ' in command
    assert (mac.root / 'opened.txt').read_text().splitlines() == [
        '-a',
        'Terminal',
        str(mac.logdir / 'videos.command'),
    ]
    tail = subprocess.Popen(
        ['tail', '-n', '+1', '-f', str(mac.logdir / 'videos.log')],
        stdout=subprocess.PIPE,
        text=True,
    )
    (mac.logdir / 'videos.pid').write_text(f'{tail.pid}\n')
    try:
        finish = mac.follow_ups()[2]
        assert (
            mac.run(finish, stdin='Saved 1 video(s) to Photos.').returncode
            == 0
        )
        shown, _ = tail.communicate(timeout=10)
    finally:
        tail.kill()

    assert shown.rstrip().endswith(
        'Saved 1 video(s) to Photos.\nDone. You can close this window.'
    )
    assert not (mac.logdir / 'videos.command').exists()


def test_no_progress_window_without_videos(mac, fake):
    (mac.work / 'in' / 'IMG_0001.HEIC').write_bytes(b'photo')
    opener = fake.bin / 'fakeopen'
    opener.mkdir()
    (opener / 'open').write_text(f'#!/bin/sh\ntouch "{mac.root}/opened.txt"\n')
    (opener / 'open').chmod(0o755)
    mac.convert('A|IMG_0001.HEIC', watch=True, path=opener)
    assert not (mac.root / 'opened.txt').exists()


def test_ffprobe_named_like_ffmpeg(mac, fake):
    # The release files, ffmpeg-macos and ffprobe-macos, work as they are.
    folder = fake.bin / 'release'
    folder.mkdir()
    (folder / 'ffmpeg-macos').symlink_to(fake.bin / 'ffmpeg')
    (folder / 'ffprobe-macos').symlink_to(fake.bin / 'ffprobe')
    video(mac, fake, 'IMG_0001.MOV')
    env = mac.env()
    env['FFMPEG'] = str(folder / 'ffmpeg-macos')
    del env['FFPROBE']
    result = subprocess.run(
        ['zsh', '-c', mac.conversion('A|IMG_0001.MOV'), 'zsh'],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith('|A|delete|IMG_0001.mp4\n')
