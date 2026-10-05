"""
vidmeta, the metadata helper (src/vidmeta.c, src/mp4meta.c), on MP4 files
written here box by box: what it copies from the original into the converted
file, the times it sets, what it leaves alone, and the files it refuses.

The tests run the build with the sanitizers (build/vidmeta), so a memory error
in the box parsing fails them; the released build is checked for its version
and self-test.
"""

import struct
import subprocess

import pytest

ORIGINAL_TIMES = (3_833_000_000, 3_833_000_001)  # seconds since 1904 (2025)
CONVERTED_TIMES = (5_000_000_000, 5_000_000_001)  # needs version 1 boxes
CONVERTED_TIMES_32 = (4_100_000_000, 4_100_000_001)  # for version 0


# ---------------------------------------------------------------------------
# Writing boxes


def box(kind, *children, large=False):
    body = b''.join(children)
    if large:  # a 64-bit size, as for a large mdat
        return struct.pack('>I4sQ', 1, kind, 16 + len(body)) + body

    return struct.pack('>I4s', 8 + len(body), kind) + body


def timed(kind, version, times):
    """mvhd, tkhd or mdhd with these creation and modification times."""
    rest = {b'mvhd': 88, b'tkhd': 72, b'mdhd': 12}[kind]
    if version == 1:
        return box(kind, struct.pack('>I2Q', 1 << 24, *times), bytes(rest + 4))

    return box(kind, struct.pack('>I2I', 0, *times), bytes(rest))


def hdlr(handler):
    return box(b'hdlr', bytes(8), handler, bytes(13))


def keys_meta(**keys):
    """A QuickTime metadata box (hdlr mdta, keys, ilst), UTF-8 values."""
    names = [k.replace('_', '.') for k in keys]
    keys_box = box(
        b'keys',
        struct.pack('>II', 0, len(names)),
        *(box(b'mdta', n.encode()) for n in names),
    )
    items = box(
        b'ilst',
        *(
            box(
                struct.pack('>I', i),
                box(b'data', struct.pack('>II', 1, 0), v.encode()),
            )
            for i, v in enumerate(keys.values(), 1)
        ),
    )
    return box(b'meta', hdlr(b'mdta'), keys_box, items)


def udta(tag, text):
    return box(b'udta', box(tag, text.encode()))


def trak(handler, version, times, *extra):
    return box(
        b'trak',
        timed(b'tkhd', version, times),
        box(b'mdia', timed(b'mdhd', version, times), hdlr(handler)),
        *extra,
    )


DATE = keys_meta(
    com_apple_quicktime_creationdate='2025-06-01T12:34:56+0200',
    com_apple_quicktime_location_ISO6709='+48.8584+002.2945+035.000/',
)
CAMERA = udta(b'\xa9mak', 'Apple')
LENS = keys_meta(
    com_apple_quicktime_camera_lens_model='iPhone 17 Pro back camera'
)
FFMPEG_TAG = udta(b'\xa9too', 'Lavf62.3.100')
AUDIO_TAG = udta(b'name', 'Stereo')
FRAMES = box(b'mdat', b'frames that must not change' * 10)
FTYP = box(b'ftyp', b'isom', bytes(4))


def original(version=0, moov_first=False):
    """An iPhone-like original: movie keys and udta, the video track's keys."""
    moov = box(
        b'moov',
        timed(b'mvhd', version, ORIGINAL_TIMES),
        trak(b'vide', version, ORIGINAL_TIMES, LENS),
        trak(b'soun', version, ORIGINAL_TIMES),
        DATE,
        CAMERA,
    )
    return FTYP + (moov + FRAMES if moov_first else FRAMES + moov)


def converted(version=1, frames=FRAMES, tracks=None):
    """As ffmpeg writes it: frames first, then a moov with its own tags."""
    own = CONVERTED_TIMES if version == 1 else CONVERTED_TIMES_32
    tracks = tracks or [
        trak(b'vide', version, own, FFMPEG_TAG),
        trak(b'soun', version, own, AUDIO_TAG),
    ]
    moov = box(b'moov', timed(b'mvhd', version, own), *tracks, FFMPEG_TAG)
    return FTYP + frames + moov


# ---------------------------------------------------------------------------
# Reading boxes


def children(data, start=0, end=None):
    """
    (kind, offset, header size, total size) of each box in data[start:end].
    """
    end = len(data) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack_from('>I4s', data, pos)
        header = 8
        if size == 1:
            (size,) = struct.unpack_from('>Q', data, pos + 8)
            header = 16
        elif size == 0:
            size = end - pos

        assert size >= header and pos + size <= end, f'bad box at {pos}'
        yield kind, pos, header, size
        pos += size

    assert pos == end, f'trailing bytes at {pos}'


def child_boxes(data, start=0, end=None):
    """The children of data[start:end] as (kind, bytes)."""
    return [
        (kind, data[pos : pos + size])
        for kind, pos, _, size in children(data, start, end)
    ]


def inside(b):
    """The children of one box (given as its bytes)."""
    header = 16 if struct.unpack_from('>I', b)[0] == 1 else 8
    return child_boxes(b, header)


def moov(data):
    top = child_boxes(data)
    assert top[-1][0] == b'moov', 'moov is not the last box'
    return inside(top[-1][1])


def times(timed_box):
    version = timed_box[8]
    fmt = '>2Q' if version == 1 else '>2I'
    return struct.unpack_from(fmt, timed_box, 12)


def tracks(moov_children):
    return [b for kind, b in moov_children if kind == b'trak']


def track_parts(trak_box):
    parts = inside(trak_box)
    mdia = next(b for kind, b in parts if kind == b'mdia')
    return parts, inside(mdia)


# ---------------------------------------------------------------------------
# The tests


def run(vidmeta, *args):
    return subprocess.run(
        [str(vidmeta), *map(str, args)], capture_output=True, text=True
    )


def copy(vidmeta, tmp_path, original_bytes, converted_bytes):
    orig, conv = tmp_path / 'IMG_0001.MOV', tmp_path / 'IMG_0001.mp4'
    orig.write_bytes(original_bytes)
    conv.write_bytes(converted_bytes)
    result = run(vidmeta, 'copy', orig, conv)
    return result, conv.read_bytes()


def test_version(vidmeta, vidmeta_release, version):
    for binary in (vidmeta, vidmeta_release):
        result = run(binary, '--version')
        assert result.returncode == 0
        assert result.stdout == f'vidmeta {version}\n'


def test_selftest(vidmeta, vidmeta_release):
    for binary in (vidmeta, vidmeta_release):
        result = run(binary, '--selftest')
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.endswith('Self-test passed.\n')


@pytest.mark.parametrize('args', [[], ['copy'], ['copy', 'a'], ['--help']])
def test_usage(vidmeta, args):
    result = run(vidmeta, *args)
    assert result.returncode == 2
    assert result.stderr.startswith('usage: vidmeta copy ORIGINAL CONVERTED')


@pytest.mark.parametrize(
    'orig_version, conv_version', [(0, 1), (1, 0), (0, 0), (1, 1)]
)
def test_copies_the_apple_metadata(
        vidmeta, tmp_path, orig_version, conv_version
):
    before = converted(conv_version)
    result, after = copy(vidmeta, tmp_path, original(orig_version), before)
    assert result.returncode == 0, result.stderr
    # The movie's meta and udta, and the video track's meta.
    assert result.stdout == 'copied 3 boxes\n'
    out = moov(after)
    # The movie: the original's keys and udta, byte for byte, in place of
    # ffmpeg's udta (its encoder tag goes with it).
    assert [b for kind, b in out if kind in (b'meta', b'udta')] == [
        DATE,
        CAMERA,
    ]
    video, audio = tracks(out)
    video_parts, _ = track_parts(video)
    audio_parts, _ = track_parts(audio)
    # The video track: the original's lens key instead of ffmpeg's tag.
    assert [b for kind, b in video_parts if kind in (b'meta', b'udta')] == [
        LENS
    ]
    # Other tracks keep their own boxes.
    assert AUDIO_TAG in [b for _, b in audio_parts]
    assert FFMPEG_TAG not in after
    # Nothing before the moov moved.
    prefix = len(FTYP) + len(FRAMES)
    assert after[:prefix] == before[:prefix]


@pytest.mark.parametrize('orig_version', [0, 1])
@pytest.mark.parametrize('conv_version', [0, 1])
def test_sets_the_times_from_the_original(
        vidmeta, tmp_path, orig_version, conv_version
):
    result, after = copy(
        vidmeta, tmp_path, original(orig_version), converted(conv_version)
    )
    assert result.returncode == 0, result.stderr
    out = moov(after)
    mvhd = next(b for kind, b in out if kind == b'mvhd')
    # A version 0 box can't hold times past 2040; the original's fit.
    assert times(mvhd) == ORIGINAL_TIMES
    for t in tracks(out):
        parts, mdia = track_parts(t)
        assert times(dict(parts)[b'tkhd']) == ORIGINAL_TIMES
        assert times(dict(mdia)[b'mdhd']) == ORIGINAL_TIMES


def test_original_with_its_moov_first(vidmeta, tmp_path):
    result, after = copy(
        vidmeta, tmp_path, original(moov_first=True), converted()
    )
    assert result.returncode == 0, result.stderr
    assert DATE in after and LENS in after


def test_only_the_first_video_track(vidmeta, tmp_path):
    second = trak(b'vide', 1, CONVERTED_TIMES, FFMPEG_TAG)
    first = trak(b'vide', 1, CONVERTED_TIMES, FFMPEG_TAG)
    result, after = copy(
        vidmeta, tmp_path, original(), converted(tracks=[first, second])
    )
    assert result.returncode == 0, result.stderr
    one, two = tracks(moov(after))
    assert LENS in one and FFMPEG_TAG not in one
    assert FFMPEG_TAG in two and LENS not in two


def test_original_without_metadata(vidmeta, tmp_path):
    bare = (
        FTYP
        + FRAMES
        + box(
            b'moov',
            timed(b'mvhd', 0, ORIGINAL_TIMES),
            trak(b'vide', 0, ORIGINAL_TIMES),
        )
    )
    result, after = copy(vidmeta, tmp_path, bare, converted())
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'copied 0 boxes\n'
    # ffmpeg's tags are dropped all the same, and the times set.
    assert FFMPEG_TAG not in after
    out = moov(after)
    assert times(next(b for kind, b in out if kind == b'mvhd')) == (
        ORIGINAL_TIMES
    )


def test_large_frames_box(vidmeta, tmp_path):
    # A 64-bit size, as ffmpeg writes for an mdat over 4 GB.
    frames = box(b'mdat', b'x' * 100, large=True)
    before = converted(frames=frames)
    result, after = copy(vidmeta, tmp_path, original(), before)
    assert result.returncode == 0, result.stderr
    assert (
        after[: len(FTYP) + len(frames)] == before[: len(FTYP) + len(frames)]
    )
    assert DATE in after


def refused(vidmeta, tmp_path, original_bytes, converted_bytes, message):
    result, after = copy(vidmeta, tmp_path, original_bytes, converted_bytes)
    assert result.returncode == 1
    assert result.stdout == ''
    assert message in result.stderr
    assert after == converted_bytes  # left as it was


def test_refuses_a_copy_with_its_moov_first(vidmeta, tmp_path):
    moov_first = FTYP + converted()[len(FTYP) + len(FRAMES) :] + FRAMES
    refused(
        vidmeta,
        tmp_path,
        original(),
        moov_first,
        "the moov box isn't at the end",
    )


def test_refuses_a_copy_without_moov(vidmeta, tmp_path):
    refused(vidmeta, tmp_path, original(), FTYP + FRAMES, 'no moov box')


@pytest.mark.parametrize('which', ['original', 'converted'])
def test_refuses_damaged_files(vidmeta, tmp_path, which):
    good_orig, good_conv = original(), converted()
    # The frames box claims more bytes than the file has.
    damaged = bytearray(good_orig if which == 'original' else good_conv)
    struct.pack_into('>I', damaged, len(FTYP), len(damaged) * 2)
    orig = bytes(damaged) if which == 'original' else good_orig
    conv = bytes(damaged) if which == 'converted' else good_conv
    refused(vidmeta, tmp_path, orig, conv, 'damaged file')


def test_refuses_a_damaged_moov(vidmeta, tmp_path):
    good = converted()
    damaged = bytearray(good)
    # The first box inside the moov (mvhd) claims to run past the moov.
    mvhd_at = len(FTYP) + len(FRAMES) + 8
    struct.pack_into('>I', damaged, mvhd_at, 10_000)
    refused(vidmeta, tmp_path, original(), bytes(damaged), 'damaged moov')


def test_missing_original(vidmeta, tmp_path):
    conv = tmp_path / 'IMG_0001.mp4'
    conv.write_bytes(converted())
    result = run(vidmeta, 'copy', tmp_path / 'nothing.MOV', conv)
    assert result.returncode == 1
    assert "can't open" in result.stderr
    assert conv.read_bytes() == converted()
