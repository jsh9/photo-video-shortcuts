"""
What a photo has in Photos besides its date (jxl_meta.txt, written by the
shortcuts): photobatch writes its location into the EXIF's GPS IFD and its
title, caption and keywords into the XMP (dc:title, dc:description, dc:subject;
the caption into an EXIF ImageDescription the file has too), removes what
Photos doesn't have, and leaves a file that already agrees as it is. For every
build (SIMD and scalar WebAssembly, native, macOS), JPEG XL and HEIC.
"""

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
    Stages photos (a list), writes jxl_meta.txt from meta (its lines), and
    converts; returns (photobatch's output, {index: output file}).
    """
    ph.stage(folder, photos)
    if meta is not None:
        (folder / 'jxl_meta.txt').write_text('\n'.join(meta))

    result = encoder.run([*args, 'jxl_job.txt'], folder)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout, {
        i: out for i, (out, _) in ph.read_done(folder).items()
    }


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


def gps_of(path):
    """The GPS IFD's tags (exiftool, numbers as numbers): {name: value}."""
    return {
        k.split(':')[1]: v
        for k, v in ph.exif_tags(path).items()
        if k.startswith('GPS:')
    }


def box_exif(path):
    return box(path, 'Exif')


def box_xml(path):
    return box(path, 'xml ')


def box(path, kind):
    """A JPEG XL's box of this kind ('Exif', 'xml '), as bytes; b'' if none."""
    data = path.read_bytes()
    return next(
        (data[start:end] for k, start, end in ph._boxes(data) if k == kind),
        b'',
    )


def validate(path):
    out = ph.run(
        ['exiftool', '-validate', '-warning', '-a', '-s', '-s', '-s', path],
        check=True,
    ).stdout
    assert out.splitlines()[0] == 'OK', out


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
    gps = gps_of(done[1])
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
    validate(done[1])
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
    gps = gps_of(done[1])
    assert gps['GPSLatitudeRef'] == 'S' and gps['GPSLongitudeRef'] == 'E'
    assert gps['GPSLatitude'] == pytest.approx(33.8568, abs=1e-7)
    validate(done[1])
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
    assert gps_of(done[1]) == {
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
    validate(done[1])
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
    assert gps_of(done[1]) == {}
    data = done[1].read_bytes()
    assert not [b for b in OLD_BYTES if b in data]
    assert 'XMP-photoshop:City' not in ph.xmp_properties(done[1])
    tags = ph.exif_tags(done[1])
    assert tags['IFD0:Make'] == 'TestMake'
    assert tags['ExifIFD:DateTimeOriginal'] == '2024:05:06 07:08:09'
    validate(done[1])
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
    assert gps_of(done[1]) == {}
    data = done[1].read_bytes()
    assert not [b for b in OLD_BYTES if b in data]
    tags = ph.exif_tags(done[1])
    assert tags['IFD0:Make'] == 'TestMake'
    assert tags['ExifIFD:DateTimeOriginal'] == '2024:05:06 07:08:09'
    validate(done[1])
    assert 'location removed: Photos has none' in said(out, 'IMG_0001')


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
    assert box_exif(done[1]) == box_exif(plain[1])
    assert box_exif(done[2]) == box_exif(plain[2])
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
    gps = gps_of(done[1])
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
    assert box_exif(done[1]) == box_exif(plain[1])
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
    validate(done[1])
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
        assert box_exif(done[i]) == box_exif(plain[i])
        assert box_xml(done[i]) == box_xml(plain[i])

    assert 'from Photos' not in out and 'removed' not in out


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
        validate(done[i])

    assert 'IFD0:ImageDescription' not in ph.exif_tags(done[3])
    assert ph.xmp_properties(done[3])['XMP-dc:Description'] == 'New caption'
    assert 'IFD0:ImageDescription' not in ph.exif_tags(done[4])
    assert box_xml(done[4]) == b''
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
    validate(done[1])


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
    packet = box_xml(done[1]).decode()
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
    assert box_xml(done[1])
    props = imageio(done[1])[str(done[1])]
    assert (props['title'], props['keywords']) == ('Title', 'k')


def test_xmp_without_rdf_is_kept(encoder, tmp_path):
    original = photo(tmp_path / 'src', 'IMG_0001.PNG', xmp='not XMP at all')
    out, done = convert(encoder, tmp_path / 'run', [original], ['1|title|T'])
    assert box_xml(done[1]) == b'not XMP at all'
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
    assert box_xml(done[1]) == box_xml(plain[1])
    assert box_exif(done[1]) == box_exif(plain[1])
    assert ph.xmp_properties(done[2])['XMP-dc:Title'] == 'Second'
