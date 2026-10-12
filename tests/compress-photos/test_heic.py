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


def test_photos_metadata_adds_an_exif_and_an_xmp_item(
        encoder, tmp_path, imageio
):
    # A file with neither gets both, each describing the picture (jxl_meta.txt:
    # the location into the Exif item, the title into the XMP item); the gain
    # map stays.
    photo = without_exif_item(SINGLE, tmp_path / 'src')
    assert not any(typ in {'Exif', 'mime'} for typ, _ in items(photo).values())
    ph.stage(tmp_path, [photo])
    (tmp_path / 'jxl_meta.txt').write_text(
        '1|gps|48.8584,2.2945\n1|title|Tour'
    )
    result = encoder.run(['--heic', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    assert 'HDR kept' in result.stdout
    out = ph.read_done(tmp_path)[1][0]
    types = [typ for typ, _ in items(out).values()]
    assert types.count('Exif') == 1 and types.count('mime') == 1
    assert ph.xmp_properties(out)['XMP-dc:Title'] == 'Tour'
    props = imageio(out)[str(out)]
    assert props['lat'].endswith('N') and props['title'] == 'Tour'
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


def boxes(buf, start, end):
    """
    The boxes in buf[start:end], as (type, start, end). A size of 1 means a
    64-bit size follows, 0 that the box runs to ``end``; anything else below 8
    is damage, where the walk stops.
    """
    p = start
    while p + 8 <= end:
        size, typ = struct.unpack('>I4s', buf[p : p + 8])
        if size == 1:
            size = struct.unpack('>Q', buf[p + 8 : p + 16])[0]
        elif size == 0:
            size = end - p

        if size < 8:
            return

        yield typ, p, p + size
        p += size


def payload(buf, start):
    """
    Where the box at ``start`` has its payload: after an 8- or 16-byte header.
    """
    return start + (
        16 if struct.unpack('>I', buf[start : start + 4])[0] == 1 else 8
    )


class Meta:
    """
    A HEIC's 'meta' box taken apart for editing: its child boxes' payloads in
    order (bytearrays), the 'iloc' entries ([id, construction method, data
    reference, [(offset, length)]], offsets absolute in the file, or into
    'idat') and the 'idat' payload. 'iloc' versions 0 and 1 are read (any
    offset, length and base offset sizes); it is written as version 1 with
    4-byte offsets and lengths and no base offsets. write() puts the file
    together again, with the 'mdat' offsets moved by what 'meta' grew.
    """

    def __init__(self, path):
        self.buf = buf = path.read_bytes()
        (self.meta,) = [
            (a, b) for t, a, b in boxes(buf, 0, len(buf)) if t == b'meta'
        ]
        # after the box's version and flags
        self.children = [
            (t, bytearray(buf[payload(buf, a) : b]))
            for t, a, b in boxes(buf, self.meta[0] + 12, self.meta[1])
        ]
        iloc = self.child(b'iloc')
        version = iloc[0]
        assert version in (0, 1), version
        osz, lsz = iloc[4] >> 4, iloc[4] & 15
        bsz, isz = iloc[5] >> 4, iloc[5] & 15 if version else 0
        count = struct.unpack('>H', iloc[6:8])[0]
        self.entries, q = [], 8
        for _ in range(count):
            iid = struct.unpack('>H', iloc[q : q + 2])[0]
            q += 2
            method = 0
            if version:
                method = struct.unpack('>H', iloc[q : q + 2])[0] & 15
                q += 2

            dref = struct.unpack('>H', iloc[q : q + 2])[0]
            q += 2
            base = int.from_bytes(iloc[q : q + bsz], 'big')
            q += bsz
            n = struct.unpack('>H', iloc[q : q + 2])[0]
            q += 2
            exts = []
            for _ in range(n):
                q += isz
                off = int.from_bytes(iloc[q : q + osz], 'big')
                q += osz
                length = int.from_bytes(iloc[q : q + lsz], 'big')
                q += lsz
                exts.append((base + off, length))

            self.entries.append([iid, method, dref, exts])

        idat = self.child(b'idat')
        self.had_idat = idat is not None
        self.idat = bytearray(idat) if idat is not None else bytearray()

    def child(self, typ):
        return next((p for t, p in self.children if t == typ), None)

    def build(self, shift):
        out = bytearray()
        for t, payload in self.children:
            if t == b'iloc':
                # version 1, no flags; 4-byte offsets and lengths, no base
                # offsets or extent indices
                ent = bytearray(b'\x01\x00\x00\x00\x44\x00')
                ent += struct.pack('>H', len(self.entries))
                for iid, method, dref, exts in self.entries:
                    ent += struct.pack('>HHHH', iid, method, dref, len(exts))
                    for off, ln in exts:
                        moved = off + (shift if method == 0 else 0)
                        ent += struct.pack('>II', moved, ln)

                payload = ent
            elif t == b'idat':
                payload = self.idat

            out += struct.pack('>I4s', 8 + len(payload), t) + payload

        if not self.had_idat:
            out += struct.pack('>I4s', 8 + len(self.idat), b'idat') + self.idat

        header = struct.pack('>I4s', 12 + len(out), b'meta')
        return header + self.buf[self.meta[0] + 8 : self.meta[0] + 12] + out

    def write(self, copy):
        shift = len(self.build(0)) - (self.meta[1] - self.meta[0])
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(
            self.buf[: self.meta[0]]
            + self.build(shift)
            + self.buf[self.meta[1] :]
        )
        return copy


def with_exif_in_idat(path, folder):
    """
    A copy of the HEIC whose Exif item's data is in 'idat' (construction method
    1, where some writers keep small items) instead of 'mdat'.
    """
    before = items(path)
    (exif_id,) = [i for i, (t, _) in before.items() if t == 'Exif']
    m = Meta(path)
    for entry in m.entries:
        if entry[0] == exif_id:
            entry[1] = 1
            entry[3] = [(len(m.idat), len(before[exif_id][1]))]

    m.idat += before[exif_id][1]
    copy = m.write(folder / path.name)
    assert items(copy) == before
    return copy


def with_mime_item(path, folder, content_type, data, before_id):
    """
    A copy of the HEIC with another 'mime' item describing the picture (item
    1): hidden, of ``content_type``, with ``data`` in 'idat', listed in 'iinf'
    before the item ``before_id``.
    """
    m = Meta(path)
    new_id = max(items(path)) + 1
    infe = b'\x02\x00\x00\x01' + struct.pack('>HH', new_id, 0)  # hidden
    infe += b'mime\x00' + content_type.encode() + b'\x00'
    infe = struct.pack('>I4s', 8 + len(infe), b'infe') + infe
    iinf = m.child(b'iinf')
    assert iinf[0] == 0  # a 16-bit count
    count = struct.unpack('>H', iinf[4:6])[0]
    at, q = len(iinf), 6
    for _ in range(count):
        size = struct.unpack('>I', iinf[q : q + 4])[0]
        if struct.unpack('>H', iinf[q + 12 : q + 14])[0] == before_id:
            at = q
            break

        q += size

    iinf[at:at] = infe
    iinf[4:6] = struct.pack('>H', count + 1)
    m.child(b'iref').extend(
        struct.pack('>I4s', 14, b'cdsc') + struct.pack('>HHH', new_id, 1, 1)
    )
    m.entries.append([new_id, 1, 0, [(len(m.idat), len(data))]])
    m.idat += data
    copy = m.write(folder / path.name)
    assert items(copy)[new_id] == ('mime', data)
    return copy


def with_icc_profile(path, folder, icc):
    """
    A copy of the HEIC whose 'colr' properties are each replaced by one
    carrying the ICC profile ``icc`` (every other property, and so each one's
    index in 'ipma', stays).
    """
    m = Meta(path)
    iprp = m.child(b'iprp')
    (ipco,) = [(a, b) for t, a, b in boxes(iprp, 0, len(iprp)) if t == b'ipco']
    box = struct.pack('>I4s4s', 12 + len(icc), b'colr', b'prof') + icc
    inner, replaced = bytearray(), 0
    for t, a, b in boxes(iprp, payload(iprp, ipco[0]), ipco[1]):
        inner += box if t == b'colr' else iprp[a:b]
        replaced += t == b'colr'

    assert replaced
    iprp[ipco[0] : ipco[1]] = (
        struct.pack('>I4s', 8 + len(inner), b'ipco') + inner
    )
    return m.write(folder / path.name)


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
    assert result.returncode == 0, result.stdout  # one of the two converted
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
    (meta,) = [(a, b) for t, a, b in boxes(buf, 0, len(buf)) if t == b'meta']
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


def test_xmp_is_told_from_other_mime_items(encoder, tmp_path):
    # The XMP is the 'mime' item of type application/rdf+xml. Another 'mime'
    # item describing the picture, listed before it, stays as it is.
    photo = with_xmp_date(OLDER, tmp_path / 'a')
    (xmp_id,) = [i for i, (t, _) in items(photo).items() if t == 'mime']
    photo = with_mime_item(
        photo, tmp_path / 'b', 'text/plain', b'a note', xmp_id
    )
    note_id = max(items(photo))
    ph.stage(tmp_path, [photo])
    (tmp_path / 'jxl_dates.txt').write_text('1|2024-05-06T07:08:09-05:00')
    result = encoder.run(['--heic', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    out = ph.read_done(tmp_path)[1][0]
    assert items(out)[note_id] == ('mime', b'a note')
    assert ph.xmp_tags(out)['CreateDate'] == '2024:05:06 07:08:09-05:00'


def gray_icc(gamma):
    """
    A minimal grayscale ICC profile (version 2) whose tone curve is the plain
    gamma ``gamma`` (1: linear light).
    """

    def s15(v):
        return struct.pack('>i', round(v * 65536))

    d50 = s15(0.9642) + s15(1.0) + s15(0.8249)
    tags = {
        b'wtpt': b'XYZ \x00\x00\x00\x00' + d50,
        b'kTRC': b'curv\x00\x00\x00\x00'
        + struct.pack('>IH', 1, round(gamma * 256)),
        b'cprt': b'text\x00\x00\x00\x00none\x00',
    }
    table, body = struct.pack('>I', len(tags)), b''
    first = 128 + 4 + 12 * len(tags)
    for sig, data in tags.items():
        table += sig + struct.pack('>II', first + len(body), len(data))
        body += data + b'\x00' * (-len(data) % 4)

    header = struct.pack('>I', 128 + len(table) + len(body))
    header += (
        b'\x00' * 4 + b'\x02\x10\x00\x00' + b'mntrGRAYXYZ ' + b'\x00' * 12
    )
    header += b'acsp' + b'\x00' * 28 + d50 + b'\x00' * 48
    assert len(header) == 128
    return header + table + body


def assert_half_white_srgb(out, apple_sdr):
    """
    The HEIC is sRGB by an nclx, with no profile, and shows as half of white:
    what a mid gray with a linear-light profile is.
    """
    buf = out.read_bytes()
    (meta,) = [(a, b) for t, a, b in boxes(buf, 0, len(buf)) if t == b'meta']
    colr = buf.find(b'colr', meta[0], meta[1])
    assert buf[colr + 4 : colr + 8] == b'nclx'
    assert b'prof' not in buf[meta[0] : meta[1]]
    rendered = apple_sdr(out)
    assert abs(float(rendered.mean()) - 128 / 255) < 0.02


def test_gray_profile_is_applied_and_the_picture_written_as_srgb(
        encoder, tmp_path, apple_sdr
):
    # A gray PNG with a linear-light profile: its mid gray is half of white,
    # which the HEIC (sRGB, no profile: one for gray can't describe the RGB
    # written) shows as such.
    png = tmp_path / 'gray.png'
    Image.new('L', (300, 200), 128).save(png, 'PNG', icc_profile=gray_icc(1))
    out, _, log = convert(encoder, tmp_path, png)
    assert 'PNG 300x200, SDR HEIC' in log
    assert_half_white_srgb(out, apple_sdr)


def test_gray_profile_on_a_heif_written_anew(
        encoder, tmp_path, helpers, apple_sdr
):
    # The decoder gives a HEIF's pixels as RGB whatever the file holds, so the
    # profile, not the channel count, decides. ImageIO writes no monochrome
    # HEVC, so: a mid-gray 10-bit HEIC (not transcodable: written anew) whose
    # color property is swapped for a linear-light gray profile.
    png = tmp_path / 'gray.png'
    Image.new('RGB', (300, 200), (128, 128, 128)).save(png, 'PNG')
    heic = tmp_path / 'gray.heic'
    ph.run([helpers['make_photo'], png, heic, '--depth16'], check=True)
    photo = with_icc_profile(heic, tmp_path / 'src', gray_icc(1))
    out, _, log = convert(encoder, tmp_path / 'job', photo)
    assert 'written anew, as SDR' in ' '.join(log.split())  # wrapped lines
    assert_half_white_srgb(out, apple_sdr)


def test_ten_bit_pixels_are_written_as_an_eight_bit_sdr_heic(
        encoder, tmp_path, imageio
):
    # A HEIF whose tiles are 10-bit can't be transcoded: decoded, rounded to 8
    # bits and written anew (its HDR not kept, so the original is kept). A
    # 16-bit PNG likewise.
    ten = HDR / 'ten_bit.heic'
    png = tmp_path / 'deep.png'
    Image.new('I;16', (300, 200), 40000).save(png, 'PNG')
    ph.stage(tmp_path, [ten, png])
    result = encoder.run(['--heic', 'jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout
    log = ' '.join(result.stdout.split())
    assert 'written anew, as SDR' in log
    assert 'HDR not kept; saved as SDR' in log
    assert 'PNG 300x200, SDR HEIC' in log
    done = ph.read_done(tmp_path)
    assert set(done) == {1, 2}
    assert 1 in ph.kept_originals(tmp_path)
    for index in done:
        assert str(done[index][0]) in imageio(done[index][0])


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
