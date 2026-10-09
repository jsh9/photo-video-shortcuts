"""
The date the photo has in Photos (jxl_dates.txt, written by the shortcuts):
jxlbatch puts it in the JPEG XL's EXIF when the original's capture date is
another moment or missing, and otherwise leaves the EXIF as it is. For every
build (SIMD and scalar WebAssembly, native).
"""

import json
import shutil

import photo_helpers as ph
import pytest
from PIL import Image, PngImagePlugin

# The test photos' own date (make_photo.swift): 2024-05-06 07:08:09.123 +02:00
OWN = '2024:05:06 07:08:09'
# The tags a new date sets; everything else in the EXIF must stay.
DATE_TAGS = {
    'IFD0:ModifyDate',
    'ExifIFD:DateTimeOriginal',
    'ExifIFD:CreateDate',
    'ExifIFD:OffsetTime',
    'ExifIFD:OffsetTimeOriginal',
    'ExifIFD:OffsetTimeDigitized',
    'ExifIFD:SubSecTimeOriginal',
    'ExifIFD:SubSecTimeDigitized',
    'ExifIFD:ExifVersion',
}


def convert(encoder, folder, photos, dates=None):
    """
    Stages photos (a list), writes jxl_dates.txt from dates ({index: date}),
    and converts; returns (jxlbatch's output, {index: JPEG XL}).
    """
    ph.stage(folder, photos)
    if dates is not None:
        (folder / 'jxl_dates.txt').write_text(
            '\n'.join(f'{i}|{d}' for i, d in dates.items())
        )

    result = encoder.run(['-q', '60', '-e', '1', 'jxl_job.txt'], folder)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout, {
        i: jxl for i, (jxl, _) in ph.read_done(folder).items()
    }


def exif_box(path):
    """The JPEG XL's Exif box, as bytes."""
    data = path.read_bytes()
    return next(
        data[start:end]
        for kind, start, end in ph._boxes(data)
        if kind == 'Exif'
    )


def dates_of(path):
    tags = ph.exif_tags(path)
    return {k: tags[k] for k in sorted(DATE_TAGS & set(tags))}


def validate(path):
    out = ph.run(
        ['exiftool', '-validate', '-warning', '-a', '-s', '-s', '-s', path],
        check=True,
    ).stdout
    assert out.splitlines()[0] == 'OK', out


def without_date(photo, folder):
    """
    A copy of photo without the EXIF capture date (as an app may send it).
    """
    copy = folder / f'nodate_{photo.name}'
    shutil.copy(photo, copy)
    ph.run(
        [
            'exiftool',
            '-q',
            '-overwrite_original',
            '-DateTimeOriginal=',
            '-CreateDate=',
            '-ModifyDate=',
            '-OffsetTime*=',
            '-SubSecTime*=',
            copy,
        ],
        check=True,
    )
    assert 'ExifIFD:DateTimeOriginal' not in ph.exif_tags(copy)
    return copy


def assert_others_kept(original, jxl):
    before, after = ph.exif_tags(original), ph.exif_tags(jxl)
    changed = sorted(
        k
        for k in set(before) | set(after)
        if k not in ph.EXIF_ALLOWED_DIFF | DATE_TAGS
        and before.get(k) != after.get(k)
    )
    assert not changed, {k: (before.get(k), after.get(k)) for k in changed}


def test_missing_date_gets_photos_date(encoder, photos, tmp_path):
    photo = without_date(photos['heic_srgb'], tmp_path)
    out, jxl = convert(
        encoder,
        tmp_path / 'run',
        [photo],
        {1: '2026-10-08T20:32:10-04:00'},
    )
    assert dates_of(jxl[1]) == {
        'ExifIFD:DateTimeOriginal': '2026:10:08 20:32:10',
        'ExifIFD:CreateDate': '2026:10:08 20:32:10',
        'ExifIFD:OffsetTimeOriginal': '-04:00',
        'ExifIFD:OffsetTimeDigitized': '-04:00',
    }
    assert_others_kept(photo, jxl[1])
    validate(jxl[1])
    assert (
        'date from Photos: 2026:10:08 20:32:10 -04:00 (the file had none)'
        in (' '.join(ph.photo_output(out, photo.stem).split()))
    )


def test_changed_date_replaces_the_files(encoder, photos, tmp_path):
    photo = photos['heic_srgb']
    out, jxl = convert(
        encoder, tmp_path, [photo], {1: '2024-01-01T17:00:00-05:00'}
    )
    assert dates_of(jxl[1]) == {
        'ExifIFD:DateTimeOriginal': '2024:01:01 17:00:00',
        'ExifIFD:CreateDate': '2024:01:01 17:00:00',
        'ExifIFD:OffsetTimeOriginal': '-05:00',
        'ExifIFD:OffsetTimeDigitized': '-05:00',
    }  # the original's SubSecTimeOriginal (123) is gone with its date
    assert_others_kept(photo, jxl[1])
    validate(jxl[1])
    said = ' '.join(ph.photo_output(out, photo.stem).split())
    assert (
        'date from Photos: 2024:01:01 17:00:00 -05:00 '
        f'(the file had {OWN} +02:00)'
    ) in said


def test_milliseconds_and_other_date_forms(encoder, photos, tmp_path):
    photo = photos['heic_srgb']
    _, jxl = convert(
        encoder,
        tmp_path,
        [photo, photo, photo],
        {
            1: '2024-01-01T17:00:00.25-0500',
            2: '2024-01-01 17:00:00Z',
            3: '2024:01:01 17:00:00.123456+05',
        },
    )
    assert dates_of(jxl[1])['ExifIFD:SubSecTimeOriginal'] == 250
    assert dates_of(jxl[1])['ExifIFD:OffsetTimeOriginal'] == '-05:00'
    assert dates_of(jxl[2])['ExifIFD:OffsetTimeOriginal'] == '+00:00'
    assert dates_of(jxl[3])['ExifIFD:SubSecTimeOriginal'] == 123
    assert dates_of(jxl[3])['ExifIFD:OffsetTimeOriginal'] == '+05:00'


@pytest.mark.parametrize(
    'date',
    [
        # the same moment, in Photos' zone: 07:08:09 +02:00 is 05:08:09 UTC
        '2024-05-06T01:08:09.123-04:00',
        '2024-05-06T07:08:09+02:00',
        # a second apart (rounding), still the same
        '2024-05-06T07:08:10+02:00',
    ],
)
def test_same_moment_leaves_the_exif_as_it_is(encoder, photos, tmp_path, date):
    photo = photos['heic_srgb']
    out, dated = convert(encoder, tmp_path / 'dated', [photo], {1: date})
    _, plain = convert(encoder, tmp_path / 'plain', [photo])
    assert exif_box(dated[1]) == exif_box(plain[1])
    assert 'date from Photos' not in out


def test_wall_time_compared_when_the_file_has_no_offset(
        encoder, photos, tmp_path
):
    # png_alpha's EXIF: DateTimeOriginal 2024:05:06 07:08:09, no offset
    photo = photos['png_alpha']
    _, jxl = convert(
        encoder,
        tmp_path / 'dated',
        [photo, photo],
        {1: '2024-05-06T07:08:09-07:00', 2: '2024-05-06T08:08:09-07:00'},
    )
    _, plain = convert(encoder, tmp_path / 'plain', [photo])
    assert exif_box(jxl[1]) == exif_box(plain[1])
    assert 'ExifIFD:OffsetTimeOriginal' not in ph.exif_tags(jxl[1])
    assert (
        dates_of(jxl[2])['ExifIFD:DateTimeOriginal'] == '2024:05:06 08:08:09'
    )
    assert dates_of(jxl[2])['ExifIFD:OffsetTimeOriginal'] == '-07:00'


def test_no_exif_at_all(encoder, imageio, tmp_path):
    # A screenshot-like PNG: no EXIF, no XMP.
    photo = tmp_path / 'IMG_0001.PNG'
    ph.scene(64, 48).save(photo)
    out, jxl = convert(
        encoder,
        tmp_path / 'run',
        [photo],
        {1: '2025-03-12T19:00:00.500-04:00'},
    )
    tags = ph.exif_tags(jxl[1])
    assert tags['ExifIFD:DateTimeOriginal'] == '2025:03:12 19:00:00'
    assert tags['ExifIFD:OffsetTimeOriginal'] == '-04:00'
    assert tags['ExifIFD:SubSecTimeOriginal'] == 500
    assert tags['ExifIFD:ExifVersion'] == '0232'
    validate(jxl[1])
    assert 'no metadata' not in ph.photo_output(out, 'IMG_0001')
    props = imageio(jxl[1])[str(jxl[1])]
    assert props['taken'] == '2025:03:12 19:00:00'
    assert props['offset'] == '-04:00'


def test_ifd0_without_an_exif_ifd(encoder, tmp_path):
    # Only IFD0 (Make), little-endian as Pillow writes it.
    photo = tmp_path / 'made.png'
    exif = Image.Exif()
    exif[0x010F] = 'TestMake'
    ph.scene(64, 48).save(photo, exif=exif.tobytes())
    _, jxl = convert(
        encoder, tmp_path / 'run', [photo], {1: '2025-03-12T19:00:00-04:00'}
    )
    tags = ph.exif_tags(jxl[1])
    assert tags['IFD0:Make'] == 'TestMake'
    assert tags['ExifIFD:DateTimeOriginal'] == '2025:03:12 19:00:00'
    validate(jxl[1])


def test_apple_maker_note_kept(encoder, tmp_path):
    # An iPhone 13 mini photo's EXIF: no date, an Apple maker note (HDR
    # headroom), which a moved Exif IFD must not break.
    photo = ph.HERE / 'fixtures' / 'hdr' / 'apple_older.heic'

    def apple(path):
        out = ph.run(
            ['exiftool', '-j', '-G1', '-n', '-MakerNotes:all', path],
            check=True,
        ).stdout
        tags = json.loads(out)[0]
        tags.pop('SourceFile')
        return tags

    _, jxl = convert(
        encoder, tmp_path, [photo], {1: '2022-02-02T10:00:00-08:00'}
    )
    assert apple(jxl[1]) == apple(photo)
    assert apple(photo)['Apple:HDRHeadroom'] == 0.8
    assert (
        dates_of(jxl[1])['ExifIFD:DateTimeOriginal'] == '2022:02:02 10:00:00'
    )
    validate(jxl[1])


def test_xmp_dates_follow(encoder, tmp_path):
    photo = tmp_path / 'edited.png'
    exif = Image.Exif()
    exif[0x8769] = {0x9003: OWN}
    info = PngImagePlugin.PngInfo()
    info.add_itxt(
        'XML:com.adobe.xmp',
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/"'
        ' xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmp:CreateDate="2024-05-06T07:08:09">'
        '<photoshop:DateCreated> 2024-05-06T07:08:09 </photoshop:DateCreated>'
        '<xmp:ModifyDate>2024-05-07T00:00:00</xmp:ModifyDate>'
        '<dc:description><rdf:Alt><rdf:li xml:lang="x-default">'
        '2024-05-06T07:08:09</rdf:li></rdf:Alt></dc:description>'
        '</rdf:Description></rdf:RDF></x:xmpmeta>',
    )
    ph.scene(64, 48).save(photo, exif=exif.tobytes(), pnginfo=info)
    _, jxl = convert(
        encoder,
        tmp_path / 'run',
        [photo, photo],
        {1: '2024-01-01T17:00:00.250-05:00', 2: '2024-05-06T07:08:09-07:00'},
    )
    xmp = ph.xmp_properties(jxl[1])
    assert xmp['XMP-xmp:CreateDate'] == '2024:01:01 17:00:00.250-05:00'
    # only the value is replaced; the spaces around it stay
    assert (
        xmp['XMP-photoshop:DateCreated'] == ' 2024-01-01T17:00:00.250-05:00 '
    )
    # not a capture date, and text that only looks like one: kept
    assert xmp['XMP-xmp:ModifyDate'] == '2024:05:07 00:00:00'
    assert xmp['XMP-dc:Description'] == '2024-05-06T07:08:09'
    # the same moment: the XMP as it was
    assert ph.xmp_properties(jxl[2]) == ph.xmp_properties(photo)


def test_unreadable_date_keeps_the_files(encoder, photos, tmp_path):
    photo = photos['heic_srgb']
    out, jxl = convert(encoder, tmp_path / 'bad', [photo], {1: 'yesterday'})
    _, plain = convert(encoder, tmp_path / 'plain', [photo])
    assert exif_box(jxl[1]) == exif_box(plain[1])
    assert '! date not understood (yesterday)' in out


def test_dates_go_by_index(encoder, photos, tmp_path):
    a, b = photos['heic_srgb'], photos['jpeg']
    _, jxl = convert(
        encoder,
        tmp_path / 'dated',
        [a, b],
        {2: '2024-01-01T17:00:00-05:00', 7: '2020-01-01T00:00:00Z'},
    )
    _, plain = convert(encoder, tmp_path / 'plain', [a, b])
    assert exif_box(jxl[1]) == exif_box(plain[1])
    assert (
        dates_of(jxl[2])['ExifIFD:DateTimeOriginal'] == '2024:01:01 17:00:00'
    )


def test_photos_reads_the_new_date(wasm, imageio, photos, tmp_path):
    photo = photos['heic_p3']
    _, jxl = convert(
        wasm, tmp_path, [photo], {1: '2024-01-01T17:00:00.250-05:00'}
    )
    before, after = imageio(photo, jxl[1]).values()
    assert after['taken'] == '2024:01:01 17:00:00'
    assert after['offset'] == '-05:00'
    assert after['subsec'] == '250'
    for field in ph.IMAGEIO_FIELDS:
        if field not in {'taken', 'offset', 'subsec', 'color'}:
            assert after[field] == before[field], field
