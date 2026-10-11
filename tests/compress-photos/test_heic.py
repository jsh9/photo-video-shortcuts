"""
HEIC output (photobatch --heic, src/heicout.c): an iPhone-style HEIC gets its
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
    a small parser of its own, so the checks don't share code with photobatch.
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
    ph.run(
        [
            'exiftool',
            '-q',
            '-overwrite_original',
            '-XMP-dc:Description=photobatch test',
            jpg,
        ],
        check=True,
    )
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
    # the JPEG's XMP is carried, as an item of its own
    assert 'mime' in [typ for typ, _ in items(done[1][0]).values()]
    assert ph.xmp_tags(done[1][0])['Description'] == 'photobatch test'


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


def without_exif_item(path, folder):
    """
    A copy of the HEIC whose Exif item has an unknown type, so that no reader
    finds an Exif item (as in a HEIC saved by an app that removed the EXIF).
    """
    buf = bytearray(path.read_bytes())
    renamed = 0
    p = buf.find(b'infe')
    while p != -1:
        # size, 'infe', version and flags, id, protection, then the type
        if buf[p + 12 : p + 16] == b'Exif':
            buf[p + 12 : p + 16] = b'skip'
            renamed += 1

        p = buf.find(b'infe', p + 4)

    assert renamed == 1
    folder.mkdir(parents=True, exist_ok=True)
    copy = folder / path.name
    copy.write_bytes(buf)
    return copy


XMP_WITH_DATE = (
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
    b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    b'<rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/"'
    b' xmp:CreateDate="2026-10-01T12:00:00-04:00"/>'
    b'</rdf:RDF></x:xmpmeta>'
)


def with_xmp_date(path, folder):
    """
    A copy of OLDER whose XMP item describes the picture (in the fixture it is
    the gain map's) and carries a capture date, as a camera's XMP does: the
    packet is replaced by one of the same length and its 'cdsc' pointed at the
    picture, so the rest of the file is untouched.
    """
    buf = bytearray(path.read_bytes())
    ((xmp_id, (_, packet)),) = [
        (i, v) for i, v in items(path).items() if v[0] == 'mime'
    ]
    assert len(XMP_WITH_DATE) <= len(packet)
    at = buf.find(packet)
    assert at > 0 and buf.find(packet, at + 1) < 0
    buf[at : at + len(packet)] = XMP_WITH_DATE.ljust(len(packet))
    ref = b'cdsc' + xmp_id.to_bytes(2, 'big') + (1).to_bytes(2, 'big')
    at = buf.find(ref)
    assert at > 0
    buf[at + 8 : at + 10] = (1).to_bytes(2, 'big')  # the picture, item 1
    folder.mkdir(parents=True, exist_ok=True)
    copy = folder / path.name
    copy.write_bytes(buf)
    return copy


def test_date_from_photos_becomes_an_exif_item_when_the_file_has_none(
        encoder, tmp_path
):
    # An Exif item is added, describing the picture; the gain map stays.
    photo = without_exif_item(SINGLE, tmp_path / 'src')
    assert not any(typ == 'Exif' for typ, _ in items(photo).values())
    ph.stage(tmp_path, [photo])
    (tmp_path / 'jxl_dates.txt').write_text('1|2024-05-06T07:08:09-05:00')
    result = encoder.run(['--heic', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    log = ' '.join(result.stdout.split())
    assert (
        'date from Photos: 2024:05:06 07:08:09 -05:00 (the file had none)'
        in log
    )
    assert 'no metadata' not in log
    out = ph.read_done(tmp_path)[1][0]
    types = [typ for typ, _ in items(out).values()]
    assert types.count('Exif') == 1 and 'skip' not in types
    tags = ph.exif_tags(out)
    assert tags['ExifIFD:DateTimeOriginal'] == '2024:05:06 07:08:09'
    assert tags['ExifIFD:OffsetTimeOriginal'] == '-05:00'
    assert ph.iso_gain_map_headroom(out) == ph.iso_gain_map_headroom(SINGLE)


def test_date_from_photos_lands_in_the_xmp_too(encoder, tmp_path):
    # The picture's XMP capture dates get the date, as in the JPEG XL route.
    photo = with_xmp_date(OLDER, tmp_path / 'src')
    ph.stage(tmp_path, [photo])
    (tmp_path / 'jxl_dates.txt').write_text('1|2024-05-06T07:08:09-05:00')
    result = encoder.run(['--heic', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    assert 'HDR kept' in result.stdout
    out = ph.read_done(tmp_path)[1][0]
    tags = ph.exif_tags(out)
    assert tags['ExifIFD:DateTimeOriginal'] == '2024:05:06 07:08:09'
    assert ph.xmp_tags(out)['CreateDate'] == '2024:05:06 07:08:09-05:00'


def with_exif_in_idat(path, folder):
    """
    A copy of the HEIC whose Exif item's data is in 'idat' (construction method
    1, where some writers keep small items) instead of 'mdat': the 'iloc' is
    rewritten, the data appended to an 'idat' (added if there is none), and the
    'mdat' offsets moved by what 'meta' grew.
    """
    buf = path.read_bytes()

    def boxes(start, end):
        p = start
        while p + 8 <= end:
            size, typ = struct.unpack('>I4s', buf[p : p + 8])
            yield typ, p, p + size
            p += size

    (meta,) = [(a, b) for t, a, b in boxes(0, len(buf)) if t == b'meta']
    children = list(boxes(meta[0] + 12, meta[1]))  # after version and flags
    before = items(path)
    (exif_id,) = [i for i, (t, _) in before.items() if t == 'Exif']
    idat = next(((a, b) for t, a, b in children if t == b'idat'), None)
    payload = buf[idat[0] + 8 : idat[1]] if idat else b''
    # the 'iloc' entries: version 1, 4-byte offsets and lengths, no base
    # offsets or extent indices (the fixtures')
    (iloc,) = [(a, b) for t, a, b in children if t == b'iloc']
    body = buf[iloc[0] + 8 : iloc[1]]
    assert body[0] == 1 and body[4] == 0x44 and body[5] == 0
    count = struct.unpack('>H', body[6:8])[0]
    entries, q = [], 8
    for _ in range(count):
        iid, method, dref, n = struct.unpack('>HHHH', body[q : q + 8])
        q += 8
        exts = [
            struct.unpack('>II', body[q + 8 * k : q + 8 * k + 8])
            for k in range(n)
        ]
        q += 8 * n
        entries.append([iid, method, dref, exts])

    for entry in entries:
        if entry[0] == exif_id:
            entry[1] = 1
            entry[3] = [(len(payload), len(before[exif_id][1]))]

    payload += before[exif_id][1]

    def build(shift):
        out = bytearray()
        for t, a, b in children:
            if t == b'iloc':
                ent = bytearray(body[:6]) + struct.pack('>H', count)
                for iid, method, dref, exts in entries:
                    ent += struct.pack('>HHHH', iid, method, dref, len(exts))
                    for off, ln in exts:
                        moved = off + (shift if method == 0 else 0)
                        ent += struct.pack('>II', moved, ln)

                out += struct.pack('>I4s', 8 + len(ent), b'iloc') + ent
            elif t == b'idat':
                out += struct.pack('>I4s', 8 + len(payload), b'idat') + payload
            else:
                out += buf[a:b]

        if not idat:
            out += struct.pack('>I4s', 8 + len(payload), b'idat') + payload

        header = struct.pack('>I4s', 12 + len(out), b'meta')
        return header + buf[meta[0] + 8 : meta[0] + 12] + out

    shift = len(build(0)) - (meta[1] - meta[0])
    folder.mkdir(parents=True, exist_ok=True)
    copy = folder / path.name
    copy.write_bytes(buf[: meta[0]] + build(shift) + buf[meta[1] :])
    assert items(copy) == before
    return copy


def test_date_lands_in_an_exif_item_stored_in_idat(encoder, tmp_path):
    # Replaced data goes to 'mdat' wherever the old data was; the new file
    # has every item the old one had.
    photo = with_exif_in_idat(SINGLE, tmp_path / 'src')
    ph.stage(tmp_path, [photo])
    (tmp_path / 'jxl_dates.txt').write_text('1|2024-05-06T07:08:09-05:00')
    result = encoder.run(['--heic', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    out = ph.read_done(tmp_path)[1][0]
    tags = ph.exif_tags(out)
    assert tags['ExifIFD:DateTimeOriginal'] == '2024:05:06 07:08:09'
    assert tags['ExifIFD:OffsetTimeOriginal'] == '-05:00'
    assert set(items(out)) == set(items(SINGLE))
    assert ph.iso_gain_map_headroom(out) == ph.iso_gain_map_headroom(SINGLE)


def test_transparent_image_is_refused_for_heic(encoder, tmp_path):
    # No alpha image is written, so the picture would come out opaque with
    # whatever the transparent pixels hide: nothing is written and the
    # original stays. An opaque alpha channel is dropped and converts.
    scene = ph.scene(300, 200).convert('RGBA')
    opaque = tmp_path / 'opaque.png'
    scene.save(opaque, 'PNG')
    scene.putalpha(128)
    clear = tmp_path / 'clear.png'
    scene.save(clear, 'PNG')
    ph.stage(tmp_path, [opaque, clear])
    result = encoder.run(['--heic', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 1
    log = ' '.join(result.stdout.split())
    assert "a transparent image (alpha) can't be saved as HEIC" in log
    assert '1 failed; see the messages above.' in log
    assert list(ph.read_done(tmp_path)) == [1]


def unescaped(nal):
    """The NAL unit's bytes without its emulation-prevention bytes."""
    out, zeros = bytearray(), 0
    for byte in nal:
        if zeros >= 2 and byte == 3:
            zeros = 0
            continue

        out.append(byte)
        zeros = zeros + 1 if byte == 0 else 0

    return bytes(out)


def hvcc_records(path):
    """Every 'hvcC' property's payload in the file's 'meta' box."""
    buf = path.read_bytes()
    p, meta = 0, None
    while p + 8 <= len(buf) and meta is None:
        size, typ = struct.unpack('>I4s', buf[p : p + 8])
        if typ == b'meta':
            meta = (p, p + size)

        p += size

    found, p = [], buf.find(b'hvcC', meta[0], meta[1])
    while p > 0:
        size = int.from_bytes(buf[p - 4 : p], 'big')
        found.append(buf[p + 4 : p - 4 + size])
        p = buf.find(b'hvcC', p + 4, meta[1])

    return found


def check_hvcc(rec):
    """The record's profile, tier, flags and level are its VPS's."""
    assert rec[0] == 1
    p, vps = 23, None
    for _ in range(rec[22]):
        typ, count = rec[p] & 63, int.from_bytes(rec[p + 1 : p + 3], 'big')
        p += 3
        for _ in range(count):
            n = int.from_bytes(rec[p : p + 2], 'big')
            if typ == 32:
                vps = unescaped(rec[p + 2 : p + 2 + n])

            p += 2 + n

    assert vps[6:18] == rec[1:13]
    assert rec[12] != 0  # general_level_idc


def test_hvcc_profile_tier_level_is_the_parameter_sets(encoder, tmp_path):
    # Read from the VPS without its emulation-prevention bytes, which its
    # mostly-zero profile_tier_level has (copied raw, they shifted the level
    # to 0). Both writers: the rewritten container and a new file.
    out, _, _ = convert(encoder, tmp_path / 'grid', GRID, '--rf', '26')
    before = hvcc_records(GRID)
    new = [rec for rec in hvcc_records(out) if rec not in before]
    assert len(new) == 1  # the tiles'; the gain map's is the original's
    check_hvcc(new[0])
    png = tmp_path / 'photo.png'
    ph.scene(300, 200).save(png, 'PNG')
    out, _, _ = convert(encoder, tmp_path / 'png', png)
    (rec,) = hvcc_records(out)
    check_hvcc(rec)


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
