"""
HEIC output (jxlbatch --heic, src/heicout.c): an iPhone-style HEIC gets its
HEVC tiles re-encoded inside its own container, with the gain map, thumbnail
and metadata byte for byte; other photos are written anew as SDR HEIC. For
every build (SIMD and scalar WebAssembly, native, macOS).
"""

import struct

import photo_helpers as ph
import pytest
from PIL import Image

FIXTURES = ph.HERE / 'fixtures'
HDR = FIXTURES / 'hdr'
GRID = HDR / 'grid_o6.heic'  # a 2x2 grid of tiles, turned by its 'irot'
SINGLE = HDR / 'o1.heic'  # one 'hvc1' item with an ISO gain map
OLDER = HDR / 'apple_older.heic'  # Apple's older gain map (auxiliary image)
SDR_HEIC = FIXTURES / 'heif' / 'rotate_then_crop.heic'


def items(path):
    """
    A HEIF's items as {id: (type, data)} (the data from 'mdat' or 'idat'), with
    a small parser of its own, so the checks don't share code with jxlbatch.
    """
    buf = path.read_bytes()

    def boxes(start, end):
        p = start
        while p + 8 <= end:
            size, typ = struct.unpack('>I4s', buf[p : p + 8])
            hdr = 8
            if size == 1:
                size = struct.unpack('>Q', buf[p + 8 : p + 16])[0]
                hdr = 16
            elif size == 0:
                size = end - p

            yield typ, p + hdr, p + size
            p += size

    meta = next((a, b) for t, a, b in boxes(0, len(buf)) if t == b'meta')
    types, locs, idat = {}, {}, None
    for typ, a, b in boxes(meta[0] + 4, meta[1]):
        body = buf[a:b]
        if typ == b'iinf':
            v = body[0]
            off = 6 if v == 0 else 8
            for t2, a2, b2 in boxes(a + off, b):
                e = buf[a2:b2]
                idsz = 2 if e[0] == 2 else 4
                iid = int.from_bytes(e[4 : 4 + idsz], 'big')
                types[iid] = e[4 + idsz + 2 : 4 + idsz + 6].decode('latin1')
        elif typ == b'idat':
            idat = (a, b)
        elif typ == b'iloc':
            v = body[0]
            osz, lsz = body[4] >> 4, body[4] & 15
            bsz = body[5] >> 4
            isz = body[5] & 15 if v else 0
            q = 6
            if v < 2:
                n = struct.unpack('>H', body[q : q + 2])[0]
                q += 2
            else:
                n = struct.unpack('>I', body[q : q + 4])[0]
                q += 4

            for _ in range(n):
                idsz = 2 if v < 2 else 4
                iid = int.from_bytes(body[q : q + idsz], 'big')
                q += idsz
                cm = 0
                if v:
                    cm = struct.unpack('>H', body[q : q + 2])[0] & 15
                    q += 2

                q += 2  # data reference
                base = int.from_bytes(body[q : q + bsz], 'big')
                q += bsz
                ec = struct.unpack('>H', body[q : q + 2])[0]
                q += 2
                exts = []
                for _ in range(ec):
                    q += isz
                    o = int.from_bytes(body[q : q + osz], 'big')
                    q += osz
                    ln = int.from_bytes(body[q : q + lsz], 'big')
                    q += lsz
                    exts.append((base + o, ln))

                locs[iid] = (cm, exts)

    out = {}
    for iid, typ in types.items():
        cm, exts = locs.get(iid, (0, []))
        src = buf if cm == 0 else buf[idat[0] : idat[1]]
        out[iid] = (typ, b''.join(src[o : o + ln] for o, ln in exts))

    return out


def convert(encoder, folder, photo, *args):
    ph.stage(folder, [photo])
    result = encoder.run(['--heic', *args, 'jxl_job.txt'], folder)
    assert result.returncode == 0, result.stdout + result.stderr
    out, name = ph.read_done(folder)[1]
    return out, name, result.stdout


@pytest.mark.parametrize('fixture', [SINGLE, GRID])
def test_transcode_keeps_everything_but_the_picture(
        encoder, tmp_path, fixture
):
    # The output has the same items as the original but Apple's extras (none
    # here): the tiles' data differs, everything else is byte for byte.
    out, name, log = convert(encoder, tmp_path, fixture, '--rf', '26')
    assert name == fixture.stem + '.heic'
    assert 'HDR kept' in log
    before, after = items(fixture), items(out)
    assert set(after) == set(before)
    tiles = 0
    for iid, (typ, data) in before.items():
        if (
            after[iid][0] == 'hvc1'
            and 'tile' in log
            and iid in primary_tiles(fixture)
        ):
            assert after[iid][1] != data, iid
            tiles += 1
        else:
            assert after[iid] == (typ, data), iid

    assert f'{tiles} tile' in log
    assert ph.iso_gain_map_headroom(out) == ph.iso_gain_map_headroom(fixture)


def primary_tiles(path):
    """The ids of the primary picture's HEVC items: itself, or its tiles."""
    found = items(path)
    hvc1 = [iid for iid, (typ, _) in found.items() if typ == 'hvc1']
    grids = [iid for iid, (typ, _) in found.items() if typ == 'grid']
    if not grids:
        return {min(hvc1)}  # the primary is the first picture (fixtures)

    buf = path.read_bytes()
    # the grid's 'dimg' references
    i = buf.find(b'dimg')
    assert i > 0
    from_id = struct.unpack('>H', buf[i + 4 : i + 6])[0]
    count = struct.unpack('>H', buf[i + 6 : i + 8])[0]
    ids = struct.unpack(f'>{count}H', buf[i + 8 : i + 8 + 2 * count])
    assert from_id in grids
    return set(ids)


def test_hdr_rendering_matches_the_original(encoder, tmp_path, apple_hdr):
    # Apple's own HDR rendering (Core Image, as Photos shows it) of the copy
    # is the original's, but for the lossy base picture.
    out, _, _ = convert(encoder, tmp_path, SINGLE, '--rf', '22')
    a, b = apple_hdr(SINGLE), apple_hdr(out)
    assert a.shape == b.shape
    assert abs(float(a.max()) - float(b.max())) < 0.15
    assert abs(a - b).mean() < 0.02


def test_sdr_option_drops_the_gain_map(encoder, tmp_path, apple_hdr):
    out, name, log = convert(encoder, tmp_path, SINGLE, '--sdr')
    assert 'HDR dropped' in log
    assert ph.iso_gain_map_headroom(out) is None
    assert not any(typ == 'tmap' for typ, _ in items(out).values())
    rendered = apple_hdr(out)
    luminance = (
        0.2627 * rendered[..., 0]
        + 0.678 * rendered[..., 1]
        + 0.0593 * rendered[..., 2]
    )
    assert float(luminance.max()) <= 1.05  # nothing above SDR white
    # the original is marked to keep: its HDR isn't in the copy
    assert 1 in ph.kept_originals(tmp_path)
    assert "1 original kept: its HDR isn't in the HEIC" in ' '.join(
        log.split()
    )


def test_older_apple_gain_map_is_kept_too(encoder, tmp_path):
    out, _, log = convert(encoder, tmp_path, OLDER)
    assert 'HDR kept' in log
    assert ph.apple_older_gain_map_headroom(out) == pytest.approx(
        ph.apple_older_gain_map_headroom(OLDER)
    )


def test_bigger_rf_gives_a_smaller_file(encoder, tmp_path):
    sizes = []
    for rf in ('22', '30', '40'):
        out, _, log = convert(encoder, tmp_path / rf, GRID, '--rf', rf)
        assert f'HEIC, RF {rf}' in log
        sizes.append(out.stat().st_size)

    assert sizes == sorted(sizes, reverse=True)


def test_jpeg_and_png_become_sdr_heic(encoder, tmp_path, imageio):
    # Written anew from the pixels: the same picture, upright, with its date.
    scene = ph.scene(300, 200)
    jpg = tmp_path / 'photo.jpg'
    scene.save(jpg, 'JPEG', quality=92)
    png = tmp_path / 'photo.png'
    scene.save(png, 'PNG')
    ph.stage(tmp_path, [jpg, png])
    (tmp_path / 'jxl_dates.txt').write_text('2|2024-05-06T07:08:09-05:00')
    result = encoder.run(['--heic', '--rf', '22', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    done = ph.read_done(tmp_path)
    assert {name for _, name in done.values()} == {'photo.heic'}
    assert 'JPEG 300x200, SDR HEIC' in result.stdout
    assert 'PNG 300x200, SDR HEIC' in result.stdout
    for index, (out, _) in done.items():
        size = ph.run(
            ['sips', '-g', 'pixelWidth', '-g', 'pixelHeight', out], check=True
        ).stdout
        assert 'pixelWidth: 300' in size and 'pixelHeight: 200' in size
        assert str(out) in imageio(out)  # ImageIO reads it

    tags = ph.exif_tags(done[2][0])
    assert tags.get('ExifIFD:DateTimeOriginal') == '2024:05:06 07:08:09'
    assert tags.get('ExifIFD:OffsetTimeOriginal') == '-05:00'


def test_sdr_heic_is_transcoded_without_a_gain_map(encoder, tmp_path):
    out, name, log = convert(encoder, tmp_path, SDR_HEIC)
    assert name == 'rotate_then_crop.heic'
    assert 'HDR' not in log
    assert 'tile' in log
    assert 1 not in ph.kept_originals(tmp_path)


def test_date_from_photos_lands_in_the_exif(encoder, tmp_path):
    ph.stage(tmp_path, [SINGLE])
    (tmp_path / 'jxl_dates.txt').write_text('1|2024-05-06T07:08:09-05:00')
    result = encoder.run(['--heic', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    assert 'date from Photos: 2024:05:06 07:08:09 -05:00' in ' '.join(
        result.stdout.split()
    )
    out = ph.read_done(tmp_path)[1][0]
    tags = ph.exif_tags(out)
    assert tags['ExifIFD:DateTimeOriginal'] == '2024:05:06 07:08:09'
    assert tags['ExifIFD:OffsetTimeOriginal'] == '-05:00'
    # the gain map is still the original's
    assert ph.iso_gain_map_headroom(out) == ph.iso_gain_map_headroom(SINGLE)


def test_rf_needs_heic(encoder, tmp_path):
    result = encoder.run(['--rf', '26', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 2
    assert '--rf is for --heic' in result.stdout


@pytest.mark.parametrize('rf', ['0', '52', 'x'])
def test_rejects_bad_rf(encoder, tmp_path, rf):
    result = encoder.run(['--heic', '--rf', rf, 'jxl_job.txt'], tmp_path)
    assert result.returncode == 2
    assert 'RF must be between 1 and 51' in result.stdout


def test_decimal_comma_rf(encoder, tmp_path):
    out, _, log = convert(encoder, tmp_path, GRID, '--rf', '26,5')
    assert 'RF 26.5' in log


def test_done_lines_name_heic_copies(encoder, tmp_path):
    ph.stage(tmp_path, [GRID, SINGLE])
    result = encoder.run(['--heic', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    assert (tmp_path / 'jxl_done.txt').read_text() == (
        'jxl_out_1.heic|1|delete|grid_o6.heic\njxl_out_2.heic|2|delete|o1.heic'
    )


def test_macos_build_matches_wasm(wasm, macos, tmp_path):
    # The Mac shortcuts' encoder writes the bytes the iPhone's does.
    a, _, _ = convert(wasm, tmp_path / 'wasm', GRID, '--rf', '26')
    b, _, _ = convert(macos, tmp_path / 'macos', GRID, '--rf', '26')
    assert a.read_bytes() == b.read_bytes()
