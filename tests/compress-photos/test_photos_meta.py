"""
What a photo has in Photos besides its date (jxl_meta.txt, written by the
shortcuts): photobatch writes its location into the EXIF's GPS IFD and its
title, caption and keywords into the XMP (dc:title, dc:description, dc:subject;
the caption into an EXIF ImageDescription the file has too), removes what
Photos doesn't have, and leaves a file that already agrees as it is. For every
build (SIMD and scalar WebAssembly, native, macOS), JPEG XL and HEIC.
"""

import struct

import photo_helpers as ph
import pytest
from photo_helpers import (
    OLD_BYTES,
    OLD_GPS,
    OLD_LAT,
    OLD_LON,
    ascii_value,
    tiff,
)
from PIL import PngImagePlugin

IFD0, EXIF = ph.TIFF_IFD0, ph.TIFF_EXIF

ROUTES = {'jxl': ['-q', '60', '-e', '1'], 'heic': ['--heic', '--rf', '40']}

DC = 'xmlns:dc="http://purl.org/dc/elements/1.1/"'


def convert(encoder, folder, photos, meta=None, args=ROUTES['jxl']):
    """
    Converts photos (a list) with jxl_meta.txt from meta (its lines); returns
    (photobatch's output, {index: output file}).
    """
    return ph.convert(encoder, folder, photos, args, meta=meta)


def said(out, stem):
    """What photobatch printed for one photo, its wrapped lines joined."""
    return ' '.join(ph.photo_output(out, stem).split())


# ---------------------------------------------------------------------------
# Test photos with metadata the test knows byte for byte (photo_helpers.tiff)


def xmp_packet(*properties, attributes=''):
    """An XMP packet with one rdf:Description holding ``properties``."""
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" ' + DC + ' '
        'xmlns:exif="http://ns.adobe.com/exif/1.0/" '
        'xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/" '
        'xmlns:tiff="http://ns.adobe.com/tiff/1.0/"'
        + attributes
        + '>'
        + ''.join(properties)
        + '</rdf:Description></rdf:RDF></x:xmpmeta>'
        '<?xpacket end="w"?>'
    )


def alt(name, text):
    return (
        f'<dc:{name}><rdf:Alt><rdf:li xml:lang="x-default">{text}</rdf:li>'
        f'</rdf:Alt></dc:{name}>'
    )


def bag(*texts):
    items = ''.join(f'<rdf:li>{t}</rdf:li>' for t in texts)
    return f'<dc:subject><rdf:Bag>{items}</rdf:Bag></dc:subject>'


def photo(folder, name, exif=None, xmp=None):
    """A small PNG with this EXIF (TIFF data) and XMP packet, if given."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    info = PngImagePlugin.PngInfo()
    if xmp is not None:
        info.add_itxt('XML:com.adobe.xmp', xmp)

    extra = {'exif': exif} if exif is not None else {}
    ph.scene(64, 48).save(path, pnginfo=info, **extra)
    return path


def with_gps(folder, xmp=None):
    return photo(folder, 'IMG_0001.PNG', tiff(IFD0, EXIF, OLD_GPS), xmp)


# ---------------------------------------------------------------------------
# Location


@pytest.mark.parametrize('route', ROUTES)
def test_location_added_to_a_photo_without_one(
        encoder, imageio, tmp_path, route
):
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', tiff(IFD0, EXIF))
    out, done = convert(
        encoder,
        tmp_path / 'run',
        [original],
        ['1|gps|25.7708431,-80.1976364,2.5'],
        ROUTES[route],
    )
    gps = ph.gps_of(done[1])
    assert gps == {
        'GPSVersionID': '2 2 0 0',
        'GPSLatitudeRef': 'N',
        'GPSLatitude': pytest.approx(25.7708431, abs=1e-7),
        'GPSLongitudeRef': 'W',
        'GPSLongitude': pytest.approx(80.1976364, abs=1e-7),
        'GPSAltitudeRef': 0,
        'GPSAltitude': 2.5,
    }
    tags = ph.exif_tags(done[1])
    assert tags['IFD0:Make'] == 'TestMake'
    assert tags['ExifIFD:DateTimeOriginal'] == '2024:05:06 07:08:09'
    ph.validate(done[1])
    props = imageio(done[1])[str(done[1])]
    assert props['lat'].endswith('N') and props['lon'].endswith('W')
    assert float(props['alt']) == 2.5
    assert (
        'location from Photos: 25.770843, -80.197636 (the file had none)'
        in said(out, 'IMG_0001')
    )


def test_location_added_to_a_photo_without_exif(encoder, imageio, tmp_path):
    original = photo(tmp_path / 'src', 'IMG_0002.PNG')
    _, done = convert(
        encoder, tmp_path / 'run', [original], ['1|gps|-33.8568,151.2153']
    )
    gps = ph.gps_of(done[1])
    assert gps['GPSLatitudeRef'] == 'S' and gps['GPSLongitudeRef'] == 'E'
    assert gps['GPSLatitude'] == pytest.approx(33.8568, abs=1e-7)
    ph.validate(done[1])
    props = imageio(done[1])[str(done[1])]
    assert props['lat'].endswith('S') and props['lon'].endswith('E')


@pytest.mark.parametrize('route', ROUTES)
def test_location_changed_in_photos_replaces_the_files(
        encoder, imageio, tmp_path, route
):
    # The old fix's altitude, direction, speed and error go with it, and its
    # bytes leave the file; the XMP's location goes, its other properties stay.
    xmp = xmp_packet(
        '<exif:GPSLatitude>40,42.878333N</exif:GPSLatitude>',
        '<photoshop:City>New York</photoshop:City>',
        alt('description', 'photobatch test'),
    )
    out, done = convert(
        encoder,
        tmp_path / 'run',
        [with_gps(tmp_path / 'src', xmp)],
        ['1|gps|40.758441666667,-73.829766666667'],
        ROUTES[route],
    )
    assert ph.gps_of(done[1]) == {
        'GPSVersionID': '2 2 0 0',
        'GPSLatitudeRef': 'N',
        'GPSLatitude': pytest.approx(40.758441666667, abs=1e-7),
        'GPSLongitudeRef': 'W',
        'GPSLongitude': pytest.approx(73.829766666667, abs=1e-7),
    }
    data = done[1].read_bytes()
    assert not [b for b in OLD_BYTES if b in data]
    properties = ph.xmp_properties(done[1])
    assert 'XMP-exif:GPSLatitude' not in properties
    assert 'XMP-photoshop:City' not in properties
    assert properties['XMP-dc:Description'] == 'photobatch test'
    assert ph.exif_tags(done[1])['IFD0:Make'] == 'TestMake'
    ph.validate(done[1])
    assert 'alt' not in imageio(done[1])[str(done[1])]
    assert (
        'location from Photos: 40.758442, -73.829767 (the file had another)'
        in said(out, 'IMG_0001')
    )


@pytest.mark.parametrize('route', ROUTES)
def test_location_hidden_in_photos_leaves_none(
        encoder, imageio, tmp_path, route
):
    # Hide Location: Photos gives none, so the copy has none, in the EXIF
    # (pointer and bytes) and in the XMP.
    xmp = xmp_packet('<photoshop:City>New York</photoshop:City>')
    out, done = convert(
        encoder,
        tmp_path / 'run',
        [with_gps(tmp_path / 'src', xmp)],
        ['1|gps|'],
        ROUTES[route],
    )
    assert ph.gps_of(done[1]) == {}
    data = done[1].read_bytes()
    assert not [b for b in OLD_BYTES if b in data]
    assert 'XMP-photoshop:City' not in ph.xmp_properties(done[1])
    tags = ph.exif_tags(done[1])
    assert tags['IFD0:Make'] == 'TestMake'
    assert tags['ExifIFD:DateTimeOriginal'] == '2024:05:06 07:08:09'
    ph.validate(done[1])
    assert 'lat' not in imageio(done[1])[str(done[1])]
    assert 'location removed: Photos has none' in said(out, 'IMG_0001')


@pytest.mark.parametrize(
    'partial',
    [
        # longitude and altitude, no latitude
        {k: v for k, v in OLD_GPS.items() if k not in (0x0001, 0x0002)},
        # an altitude alone
        {k: v for k, v in OLD_GPS.items() if k in (0x0005, 0x0006)},
    ],
)
def test_location_hidden_in_photos_removes_a_partial_gps(
        encoder, tmp_path, partial
):
    # Photos has none: the GPS IFD goes even when it holds no readable
    # position, and the rest of the EXIF stays.
    original = photo(
        tmp_path / 'src', 'IMG_0001.PNG', tiff(IFD0, EXIF, partial)
    )
    out, done = convert(encoder, tmp_path / 'run', [original], ['1|gps|'])
    assert ph.gps_of(done[1]) == {}
    data = done[1].read_bytes()
    assert not [b for b in OLD_BYTES if b in data]
    tags = ph.exif_tags(done[1])
    assert tags['IFD0:Make'] == 'TestMake'
    assert tags['ExifIFD:DateTimeOriginal'] == '2024:05:06 07:08:09'
    ph.validate(done[1])
    assert 'location removed: Photos has none' in said(out, 'IMG_0001')


@pytest.mark.parametrize('location', ['48.8584,2.2945', ''])
def test_an_unreadable_exif_keeps_the_xmp_location_unless_removed(
        encoder, tmp_path, location
):
    # EXIF whose IFD0 lies outside it: no location can be written there. A
    # new one from Photos then changes nothing, the XMP's location included;
    # Photos having none still removes the XMP's.
    exif = b'MM\x00\x2a' + struct.pack('>I', 0x7FFF) + b'\0' * 8
    xmp = xmp_packet(
        '<exif:GPSLatitude>40,42.878333N</exif:GPSLatitude>',
        '<photoshop:City>New York</photoshop:City>',
    )
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', exif, xmp)
    out, done = convert(
        encoder, tmp_path / 'run', [original], [f'1|gps|{location}']
    )
    properties = ph.xmp_properties(done[1])
    log = said(out, 'IMG_0001')
    if location:
        assert b'<exif:GPSLatitude>40,42.878333N<' in ph.xml_box(done[1])
        assert properties['XMP-photoshop:City'] == 'New York'
        assert (
            "! location not written: the EXIF can't be read; the file's is kept"
            in log
        )
    else:
        assert 'XMP-exif:GPSLatitude' not in properties
        assert 'XMP-photoshop:City' not in properties
        assert (
            "! location not removed from the EXIF: it can't be read "
            '(removed from the XMP)'
        ) in log
        assert 'location removed' not in log


def test_the_same_location_leaves_the_exif_as_it_is(encoder, tmp_path):
    # Photos' reals for the file's rationals, rounded as the Mac's route
    # rounds them (6 decimals); an altitude Photos gives differently doesn't
    # count. Photos having none for a file without one changes nothing either.
    original = with_gps(tmp_path / 'src')
    plain_photo = photo(tmp_path / 'src', 'IMG_0002.PNG', tiff(IFD0, EXIF))
    meta = [f'1|gps|{OLD_LAT:.6f},{OLD_LON:.6f},99', '2|gps|']
    out, done = convert(
        encoder, tmp_path / 'dated', [original, plain_photo], meta
    )
    _, plain = convert(encoder, tmp_path / 'plain', [original, plain_photo])
    assert ph.exif_box(done[1]) == ph.exif_box(plain[1])
    assert ph.exif_box(done[2]) == ph.exif_box(plain[2])
    assert 'location' not in out


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        # a place typed in Photos' Info window: altitude 0.0, no altitude
        ('25.7708431,-80.1976364,0', {'GPSLatitudeRef': 'N'}),
        # below sea level, southern and eastern
        (
            '-31.5,35.5,-430.5',
            {
                'GPSLatitudeRef': 'S',
                'GPSLongitudeRef': 'E',
                'GPSAltitudeRef': 1,
                'GPSAltitude': 430.5,
            },
        ),
        # Shortcuts' %0.16g of small numbers, and spaces
        (
            '5e-05, -0.0001',
            {
                'GPSLatitude': pytest.approx(0.00005, abs=1e-7),
                'GPSLongitude': pytest.approx(0.0001, abs=1e-7),
                'GPSLongitudeRef': 'W',
            },
        ),
    ],
)
def test_location_forms(encoder, tmp_path, value, expected):
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', tiff(IFD0, EXIF))
    _, done = convert(
        encoder, tmp_path / 'run', [original], [f'1|gps|{value}']
    )
    gps = ph.gps_of(done[1])
    assert {k: gps.get(k) for k in expected} == expected
    if value.endswith(',0'):
        assert 'GPSAltitude' not in gps


@pytest.mark.parametrize(
    'value', ['north', '91,0', '1,2,3,4', 'nan,1', '0x1,2']
)
def test_location_not_understood_keeps_the_files(encoder, tmp_path, value):
    original = with_gps(tmp_path / 'src')
    out, done = convert(
        encoder, tmp_path / 'bad', [original], [f'1|gps|{value}']
    )
    _, plain = convert(encoder, tmp_path / 'plain', [original])
    assert ph.exif_box(done[1]) == ph.exif_box(plain[1])
    assert f'! location not understood ({value})' in said(out, 'IMG_0001')


# ---------------------------------------------------------------------------
# Title, caption and keywords


@pytest.mark.parametrize('route', ROUTES)
def test_title_caption_and_keywords_from_photos(
        encoder, imageio, photos, tmp_path, route
):
    # The test photo's XMP has a caption (dc:description) of its own and an
    # orientation; the caption is replaced, the rest stays. The values are
    # escaped as the shortcuts write them (%, |, line breaks, commas).
    original = photos['heic_srgb']
    meta = [
        '1|title|Le café | 100%25',
        '1|caption|Line 1%0ALine 2 <&>%0D',
        '1|keywords|b%2Cc,a, a ',
    ]
    out, done = convert(encoder, tmp_path, [original], meta, ROUTES[route])
    properties = ph.xmp_properties(done[1])
    assert properties['XMP-dc:Title'] == 'Le café | 100%'
    assert properties['XMP-dc:Description'] == 'Line 1\nLine 2 <&>\r'
    assert properties['XMP-dc:Subject'] == ['b,c', 'a', 'a']
    before = ph.xmp_properties(original)
    for key in before.keys() - {'XMP-dc:Description', 'XMP-x:XMPToolkit'}:
        assert properties[key] == before[key], key

    props = imageio(done[1])[str(done[1])]
    assert props['title'] == 'Le café | 100%'
    assert props['caption'].startswith('Line 1\nLine 2 <&>')
    assert set(props['keywords'].split('|')) == {'b,c', 'a'}
    log = said(out, original.stem)
    assert 'title from Photos (the file had none)' in log
    assert 'caption from Photos (the file had another)' in log
    assert 'keywords from Photos (the file had none)' in log


@pytest.mark.parametrize('route', ROUTES)
def test_what_photos_doesnt_have_is_removed(encoder, imageio, tmp_path, route):
    xmp = xmp_packet(
        alt('title', 'Old title'),
        alt('description', 'Old caption'),
        bag('old', 'keywords'),
        '<tiff:Make>TestMake</tiff:Make>',
    )
    exif = tiff({**IFD0, 0x010E: ascii_value('Old caption')}, EXIF)
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', exif, xmp)
    out, done = convert(
        encoder,
        tmp_path / 'run',
        [original],
        ['1|title|', '1|caption|', '1|keywords|'],
        ROUTES[route],
    )
    properties = ph.xmp_properties(done[1])
    assert not {
        'XMP-dc:Title',
        'XMP-dc:Description',
        'XMP-dc:Subject',
    } & set(properties)
    assert properties['XMP-tiff:Make'] == 'TestMake'
    tags = ph.exif_tags(done[1])
    assert 'IFD0:ImageDescription' not in tags
    assert tags['IFD0:Make'] == 'TestMake'
    assert b'Old caption' not in done[1].read_bytes()
    ph.validate(done[1])
    props = imageio(done[1])[str(done[1])]
    assert not {'title', 'caption', 'keywords'} & set(props)
    log = said(out, 'IMG_0001')
    for field in ('title', 'caption', 'keywords'):
        assert f'{field} removed: Photos has none' in log


def test_a_file_that_agrees_stays_as_it_is(encoder, tmp_path):
    # The same title (written with a reference), caption (in the EXIF and the
    # XMP) and keywords (in another order): nothing is written. Photos having
    # none for a file without any changes nothing either.
    xmp = xmp_packet(
        alt('title', 'Caf&#xE9;'),
        alt('description', ' Caption '),
        bag('b', 'a'),
    )
    exif = tiff({**IFD0, 0x010E: ascii_value('Caption')}, EXIF)
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', exif, xmp)
    bare = photo(tmp_path / 'src', 'IMG_0002.PNG', tiff(IFD0, EXIF))
    meta = [
        '1|title|Café',
        '1|caption|Caption',
        '1|keywords|a,b',
        '2|title|',
        '2|caption|',
        '2|keywords|',
    ]
    out, done = convert(encoder, tmp_path / 'meta', [original, bare], meta)
    _, plain = convert(encoder, tmp_path / 'plain', [original, bare])
    for i in (1, 2):
        assert ph.exif_box(done[i]) == ph.exif_box(plain[i])
        assert ph.xml_box(done[i]) == ph.xml_box(plain[i])

    assert 'from Photos' not in out and 'removed' not in out


@pytest.mark.parametrize('kind', [1, 7])  # BYTE, UNDEFINED
@pytest.mark.parametrize('caption', ['', 'New caption'])
def test_a_description_stored_in_bytes_counts(
        encoder, tmp_path, kind, caption
):
    # Some writers store a UTF-8 ImageDescription as BYTE or UNDEFINED rather
    # than ASCII; ImageIO reads it all the same, so it is the file's caption:
    # removed when Photos has none, replaced when Photos has another.
    exif = tiff({**IFD0, 0x010E: (kind, 8, b'Holiday\0')}, EXIF)
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', exif)
    assert 'IFD0:ImageDescription' in ph.exif_tags(original)  # BYTE: numbers
    out, done = convert(
        encoder, tmp_path / 'run', [original], [f'1|caption|{caption}']
    )
    tags = ph.exif_tags(done[1])
    assert tags.get('IFD0:ImageDescription') == (caption or None)
    assert b'Holiday' not in ph.exif_box(done[1])
    ph.validate(done[1])
    log = said(out, 'IMG_0001')
    if caption:
        assert 'caption from Photos (the file had another)' in log
    else:
        assert 'caption removed: Photos has none' in log


def test_a_short_caption_leaves_no_bytes_either(encoder, tmp_path):
    # A caption of up to three characters lives in the entry itself; removing
    # it rewrites IFD0, and the old entry's bytes must go too.
    exif = tiff({**IFD0, 0x010E: ascii_value('NYC')}, EXIF)
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', exif)
    _, done = convert(encoder, tmp_path / 'run', [original], ['1|caption|'])
    assert 'IFD0:ImageDescription' not in ph.exif_tags(done[1])
    assert b'NYC\0' not in ph.exif_box(done[1])
    ph.validate(done[1])


def shared_value_tiff(suffix=False):
    """
    Big-endian EXIF whose ImageDescription and Artist point to one string (TIFF
    allows sharing a value), or, with ``suffix``, the Artist to its last word
    only: removing or replacing the caption must not zero what the Artist still
    refers to.
    """
    text, make = b'Shared: text\0', b'TestMake\0'
    skip = len(b'Shared: ') if suffix else 0  # even: values at even offsets
    entries = [
        (0x010E, len(text), 0),
        (0x010F, len(make), 0),
        (0x013B, len(text) - skip, skip),
    ]
    values_at = 8 + 2 + 12 * len(entries) + 4
    make_at, text_at = values_at, values_at + len(make) + len(make) % 2
    out = b'MM\x00\x2a' + struct.pack('>IH', 8, len(entries))
    for tag, count, offset in entries:
        at = make_at if tag == 0x010F else text_at + offset
        out += struct.pack('>HHII', tag, 2, count, at)

    return out + struct.pack('>I', 0) + make + b'\0' * (len(make) % 2) + text


@pytest.mark.parametrize('caption', ['', 'New caption'])
def test_a_value_shared_with_another_tag_is_kept(encoder, tmp_path, caption):
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', shared_value_tiff())
    assert ph.exif_tags(original)['IFD0:Artist'] == 'Shared: text'
    _, done = convert(
        encoder, tmp_path / 'run', [original], [f'1|caption|{caption}']
    )
    tags = ph.exif_tags(done[1])
    assert tags['IFD0:Artist'] == 'Shared: text'
    assert tags.get('IFD0:ImageDescription') == (caption or None)
    ph.validate(done[1])


@pytest.mark.parametrize('location', ['', '48.8584,2.2945'])
def test_a_gps_pointer_into_the_exif_ifd_zeroes_nothing(
        encoder, tmp_path, location
):
    # A malformed file whose GPS pointer is the Exif IFD's offset: nothing of
    # the Exif IFD (its table or its values) may be zeroed as the "old
    # position"; the new position is written, or the pointer removed.
    exif = tiff({**IFD0, 0x8825: (4, 1, 'exif')}, EXIF)
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', exif)
    _, done = convert(
        encoder, tmp_path / 'run', [original], [f'1|gps|{location}']
    )
    tags = ph.exif_tags(done[1])
    assert tags['IFD0:Make'] == 'TestMake'
    assert tags['ExifIFD:DateTimeOriginal'] == '2024:05:06 07:08:09'
    if location:
        assert tags['GPS:GPSLatitude'] == pytest.approx(48.8584, abs=1e-7)
    else:
        assert not [k for k in tags if k.startswith('GPS:')]


def test_caption_follows_into_an_image_description(encoder, imageio, tmp_path):
    # ImageIO (and so Photos) takes the EXIF's ImageDescription over the
    # XMP's caption: one the file has gets Photos' caption too, even when only
    # the XMP's disagrees. A file without one doesn't get one; nor XMP when it
    # has nothing to hold.
    exif_only = tiff({**IFD0, 0x010E: ascii_value('Old')}, EXIF)
    both = tiff({**IFD0, 0x010E: ascii_value('New caption')}, EXIF)
    photos = [
        photo(tmp_path / 'src', 'a.png', exif_only),
        photo(
            tmp_path / 'src',
            'b.png',
            both,
            xmp_packet(alt('description', 'Old')),
        ),
        photo(tmp_path / 'src', 'c.png', tiff(IFD0, EXIF)),
        photo(tmp_path / 'src', 'd.png', exif_only),
    ]
    meta = [
        '1|caption|New caption',
        '2|caption|New caption',
        '3|caption|New caption',
        '4|caption|',
    ]
    _, done = convert(encoder, tmp_path / 'run', photos, meta)
    for i in (1, 2):
        assert ph.exif_tags(done[i])['IFD0:ImageDescription'] == 'New caption'
        assert (
            ph.xmp_properties(done[i])['XMP-dc:Description'] == 'New caption'
        )
        ph.validate(done[i])

    assert 'IFD0:ImageDescription' not in ph.exif_tags(done[3])
    assert ph.xmp_properties(done[3])['XMP-dc:Description'] == 'New caption'
    assert 'IFD0:ImageDescription' not in ph.exif_tags(done[4])
    assert ph.xml_box(done[4]) == b''
    props = imageio(*done.values())
    assert [props[str(done[i])].get('caption') for i in (1, 2, 3, 4)] == [
        'New caption',
        'New caption',
        'New caption',
        None,
    ]


@pytest.mark.parametrize('blank', ['', '   '])
@pytest.mark.parametrize('xmp_caption', [None, 'Old', 'New caption'])
def test_a_blank_image_description_gets_the_caption(
        encoder, imageio, tmp_path, blank, xmp_caption
):
    # An empty or spaces-only ImageDescription is still the file's caption
    # for ImageIO: it gets Photos', also when the XMP's already is Photos'.
    exif = tiff({**IFD0, 0x010E: ascii_value(blank)}, EXIF)
    xmp = (
        None
        if xmp_caption is None
        else xmp_packet(alt('description', xmp_caption))
    )
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', exif, xmp)
    _, done = convert(
        encoder, tmp_path / 'run', [original], ['1|caption|New caption']
    )
    assert ph.exif_tags(done[1])['IFD0:ImageDescription'] == 'New caption'
    assert ph.xmp_properties(done[1])['XMP-dc:Description'] == 'New caption'
    assert imageio(done[1])[str(done[1])]['caption'] == 'New caption'
    ph.validate(done[1])


def test_other_ways_to_write_the_properties(encoder, tmp_path):
    # A caption as an attribute, a title as a simple element, keywords as a
    # sequence, each in a description of its own: removed or replaced
    # wherever they are, the rest of the packet byte for byte.
    xmp = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" ' + DC + ' dc:description="Attribute"'
        ' xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:Rating="3"/>'
        '<rdf:Description rdf:about="" ' + DC + '>'
        '<dc:title>Simple</dc:title>'
        '<dc:subject><rdf:Seq><rdf:li>x</rdf:li></rdf:Seq></dc:subject>'
        '</rdf:Description></rdf:RDF></x:xmpmeta>'
    )
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', xmp=xmp)
    meta = ['1|title|New', '1|caption|', '1|keywords|y']
    _, done = convert(encoder, tmp_path / 'run', [original], meta)
    properties = ph.xmp_properties(done[1])
    assert properties['XMP-dc:Title'] == 'New'
    assert properties['XMP-dc:Subject'] == ['y']
    assert 'XMP-dc:Description' not in properties
    assert properties['XMP-xmp:Rating'] == 3
    packet = ph.xml_box(done[1]).decode()
    assert packet.count('<rdf:Description') == 3
    assert 'Simple' not in packet and 'Attribute' not in packet


def test_a_new_packet_for_a_file_without_xmp(encoder, imageio, tmp_path):
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', tiff(IFD0, EXIF))
    _, done = convert(
        encoder,
        tmp_path / 'run',
        [original],
        ['1|title|Title', '1|keywords|k'],
    )
    properties = ph.xmp_properties(done[1])
    assert properties['XMP-dc:Title'] == 'Title'
    assert properties['XMP-dc:Subject'] == ['k']
    assert ph.xml_box(done[1])
    props = imageio(done[1])[str(done[1])]
    assert (props['title'], props['keywords']) == ('Title', 'k')


def test_xmp_without_rdf_is_kept(encoder, tmp_path):
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', xmp='not XMP at all')
    out, done = convert(encoder, tmp_path / 'run', [original], ['1|title|T'])
    assert ph.xml_box(done[1]) == b'not XMP at all'
    assert (
        "! title, caption and keywords not written: the XMP can't be read; "
        "the file's are kept"
    ) in said(out, 'IMG_0001')


def test_metadata_goes_by_index(encoder, photos, tmp_path):
    # Lines for photos that aren't in the job, fields photobatch doesn't know
    # and lines it can't read are ignored.
    a, b = photos['heic_srgb'], photos['jpeg']
    meta = [
        '2|title|Second',
        '7|title|None such',
        '1|colour|red',
        'title|no index',
        '1|title',
    ]
    _, done = convert(encoder, tmp_path / 'meta', [a, b], meta)
    _, plain = convert(encoder, tmp_path / 'plain', [a, b])
    assert ph.xml_box(done[1]) == ph.xml_box(plain[1])
    assert ph.exif_box(done[1]) == ph.exif_box(plain[1])
    assert ph.xmp_properties(done[2])['XMP-dc:Title'] == 'Second'


# ---------------------------------------------------------------------------
# What a removal leaves in the EXIF's bytes


@pytest.mark.parametrize('caption', ['', 'New caption'])
def test_a_value_shared_in_part_keeps_only_that_part(
        encoder, tmp_path, caption
):
    # The Artist points at the last word of the ImageDescription's string:
    # removing or replacing the caption zeroes the rest of it, not that word.
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', shared_value_tiff(True))
    assert ph.exif_tags(original)['IFD0:Artist'] == 'text'
    _, done = convert(
        encoder, tmp_path / 'run', [original], [f'1|caption|{caption}']
    )
    tags = ph.exif_tags(done[1])
    assert tags['IFD0:Artist'] == 'text'
    assert tags.get('IFD0:ImageDescription') == (caption or None)
    exif = ph.exif_box(done[1])
    assert b'text\0' in exif and b'Shared:' not in exif
    ph.validate(done[1])


@pytest.mark.parametrize('location', ['', '48.8584,2.2945'])
def test_a_rational_shared_in_part_keeps_only_that_part(
        encoder, tmp_path, location
):
    # ExposureTime and FocalLength point into the first rational (the whole
    # degrees) of GPSLatitude and GPSLongitude (TIFF allows it): the rest of
    # the old position (minutes, seconds, altitude, direction...) goes, those
    # two rationals stay, and the retained tags read as before.
    exif = tiff(
        IFD0,
        {
            **EXIF,
            0x829A: (5, 1, ('shares', 'gps', 0x0002, 0)),
            0x920A: (5, 1, ('shares', 'gps', 0x0004, 0)),
        },
        OLD_GPS,
    )
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', exif)
    before = ph.exif_tags(original)
    assert (before['ExifIFD:ExposureTime'], before['ExifIFD:FocalLength']) == (
        40,
        73,
    )
    _, done = convert(
        encoder, tmp_path / 'run', [original], [f'1|gps|{location}']
    )
    tags = ph.exif_tags(done[1])
    assert (tags['ExifIFD:ExposureTime'], tags['ExifIFD:FocalLength']) == (
        40,
        73,
    )
    assert tags['IFD0:Make'] == 'TestMake'
    data = done[1].read_bytes()
    assert not [b for b in OLD_BYTES if b in data]
    gps = ph.gps_of(done[1])
    if location:
        assert gps['GPSLatitude'] == pytest.approx(48.8584, abs=1e-7)
    else:
        assert gps == {}

    ph.validate(done[1])


def gps_ifd(little_endian):
    """An iPhone-like GPS IFD in either byte order (OLD_GPS is big-endian)."""
    r = lambda *pairs: ph.rationals(*pairs, little_endian=little_endian)
    return {
        0x0001: ascii_value('N'),
        0x0002: r((40, 1), (42, 1), (5270, 100)),
        0x0003: ascii_value('W'),
        0x0004: r((73, 1), (59, 1), (5371, 100)),
    }


@pytest.mark.parametrize('little_endian', [False, True])
@pytest.mark.parametrize('caption', ['A', 'NYC'])
@pytest.mark.parametrize(
    ('exif_ifd', 'gps', 'meta'),
    [
        # the GPS removed rewrites IFD0, then the caption is removed
        (True, True, ['1|gps|', '1|caption|']),
        # ... or replaced
        (True, True, ['1|gps|', '1|caption|New caption']),
        # a GPS added rewrites IFD0 for its pointer
        (True, False, ['1|gps|48.8584,2.2945', '1|caption|']),
        # a date added to a file without an Exif IFD rewrites IFD0 too
        (False, False, ['1|caption|']),
        (False, True, ['1|gps|', '1|caption|New caption']),
    ],
)
def test_an_inline_caption_leaves_no_copy_behind(
        encoder, tmp_path, little_endian, caption, exif_ifd, gps, meta
):
    # A caption of up to three characters lives in its IFD0 entry. An earlier
    # edit of this conversion that writes IFD0 anew (a location removed or
    # added, an Exif IFD pointer added for a date) copies the entry: the old
    # table, with that copy, must go when the caption is removed or replaced.
    exif = tiff(
        {**IFD0, 0x010E: ascii_value(caption)},
        EXIF if exif_ifd else None,
        gps_ifd(little_endian) if gps else None,
        little_endian=little_endian,
    )
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', exif)
    assert ph.exif_tags(original)['IFD0:ImageDescription'] == caption
    folder = tmp_path / 'run'
    ph.stage(folder, [original])
    if not exif_ifd:
        (folder / 'jxl_dates.txt').write_text('1|2024-01-01T17:00:00-05:00')

    (folder / 'jxl_meta.txt').write_text('\n'.join(meta))
    result = encoder.run([*ROUTES['jxl'], 'jxl_job.txt'], folder)
    assert result.returncode == 0, result.stdout
    out = ph.read_done(folder)[1][0]
    tags = ph.exif_tags(out)
    want = meta[-1].split('|')[2]
    assert tags.get('IFD0:ImageDescription') == (want or None)
    assert tags['IFD0:Make'] == 'TestMake'
    if not exif_ifd:
        assert tags['ExifIFD:DateTimeOriginal'] == '2024:01:01 17:00:00'

    exif_out = ph.exif_box(out)
    assert caption.encode() + b'\0' not in exif_out
    if gps:
        assert (
            ph.rationals((5270, 100), little_endian=little_endian)[2]
            not in exif_out
        )

    ph.validate(out)


def test_a_gps_pointer_with_another_count_still_zeroes_the_old_position(
        encoder, tmp_path
):
    # A GPSInfo entry with count 0 (malformed; the offset still sits in it):
    # the position behind it is zeroed when Photos has none, not only its
    # pointer dropped.
    exif = bytearray(tiff(IFD0, EXIF, OLD_GPS))
    entry = 8 + 2 + 2 * 12  # IFD0's third entry, GPSInfo (tags sorted)
    assert struct.unpack_from('>HHI', exif, entry) == (0x8825, 4, 1)
    struct.pack_into('>I', exif, entry + 4, 0)
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', bytes(exif))
    _, done = convert(encoder, tmp_path / 'run', [original], ['1|gps|'])
    assert ph.gps_of(done[1]) == {}
    assert not [b for b in OLD_BYTES if b in done[1].read_bytes()]
    assert ph.exif_tags(done[1])['IFD0:Make'] == 'TestMake'


def test_an_unreadable_exif_keeps_its_caption_and_says_so(
        encoder, imageio, tmp_path
):
    # IFD0 without a next-IFD offset (truncated): its ImageDescription can be
    # read but not rewritten, so the XMP gets Photos' caption and the log says
    # the EXIF's stays, which Photos shows first.
    exif = (
        b'MM\x00\x2a'
        + struct.pack('>IH', 8, 1)
        + struct.pack('>HHI', 0x010E, 2, 4)
        + b'Old\0'
    )
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', exif)
    assert ph.exif_tags(original)['IFD0:ImageDescription'] == 'Old'
    out, done = convert(
        encoder, tmp_path / 'run', [original], ['1|caption|New caption']
    )
    assert ph.exif_tags(done[1])['IFD0:ImageDescription'] == 'Old'
    assert ph.xmp_properties(done[1])['XMP-dc:Description'] == 'New caption'
    log = said(out, 'IMG_0001')
    assert 'caption from Photos (the file had another)' in log
    assert "! the EXIF's caption is kept: the EXIF can't be read" in log
    assert imageio(done[1])[str(done[1])]['caption'] == 'Old'


@pytest.mark.parametrize('which', ['exif', 'xmp'])
def test_a_caption_that_already_agrees_in_one_place_stays_there(
        encoder, tmp_path, which
):
    # The ImageDescription is Photos' caption and the XMP's isn't, or the
    # other way round: only the one that differs is written, the other byte
    # for byte as it was.
    caption = 'Same caption'
    exif = tiff(
        {**IFD0, 0x010E: ascii_value(caption if which == 'exif' else 'old')},
        EXIF,
    )
    xmp = xmp_packet(alt('description', caption if which == 'xmp' else 'old'))
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', exif, xmp)
    out, done = convert(
        encoder, tmp_path / 'run', [original], [f'1|caption|{caption}']
    )
    _, plain = convert(encoder, tmp_path / 'plain', [original])
    assert ph.exif_tags(done[1])['IFD0:ImageDescription'] == caption
    assert ph.xmp_properties(done[1])['XMP-dc:Description'] == caption
    if which == 'exif':
        assert ph.exif_box(done[1]) == ph.exif_box(plain[1])
        assert ph.xml_box(done[1]) != ph.xml_box(plain[1])
    else:
        assert ph.xml_box(done[1]) == ph.xml_box(plain[1])
        assert ph.exif_box(done[1]) != ph.exif_box(plain[1])

    assert 'caption from Photos (the file had another)' in said(
        out, 'IMG_0001'
    )
