"""Generated JPEG XMP fixtures, checked through every encoder build."""

import hashlib
import io
import struct
import xml.etree.ElementTree as ET

import numpy as np
import photo_helpers as ph
import pytest
from PIL import Image

RDF = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
DC = 'http://purl.org/dc/elements/1.1/'
TIFF = 'http://ns.adobe.com/tiff/1.0/'
NOTE = 'http://ns.adobe.com/xmp/note/'
CUSTOM = 'https://example.org/metadata/'
STANDARD = b'http://ns.adobe.com/xap/1.0/\0'
EXTENDED = b'http://ns.adobe.com/xmp/extension/\0'
# Reproduces the 100,012-byte description that disappeared in the old build.
LONG_DESCRIPTION = 'description ' + 'x' * 100000


def packet(body='', attrs='', prefix='rdf', declarations='', wrapper=''):
    xml = (
        f'<x:xmpmeta xmlns:x="adobe:ns:meta/" {wrapper}>'
        f'<{prefix}:RDF xmlns:{prefix}="{RDF}" xmlns:dc="{DC}" '
        f'xmlns:t="{TIFF}" xmlns:n="{NOTE}" xmlns:c="{CUSTOM}" {declarations}>'
        f'<{prefix}:Description {prefix}:about="" {attrs}>{body}'
        f'</{prefix}:Description></{prefix}:RDF></x:xmpmeta>'
    )
    return xml.encode('utf-8')


def app1(payload):
    assert len(payload) <= 65533
    return b'\xff\xe1' + struct.pack('>H', len(payload) + 2) + payload


def fragments(extended, guid, chunk=60000):
    return [
        EXTENDED
        + guid.encode()
        + struct.pack('>II', len(extended), offset)
        + extended[offset : offset + chunk]
        for offset in range(0, len(extended), chunk)
    ]


def extended_pair(extended=None, body='', attrs='', **kwargs):
    extended = extended or packet(
        f'<dc:description>{LONG_DESCRIPTION}</dc:description>'
    )
    guid = hashlib.md5(extended).hexdigest().upper()
    base = packet(body, f'n:HasExtendedXMP="{guid}" {attrs}', **kwargs)
    return base, extended, fragments(extended, guid)


def jpeg(path, base, parts=(), extension_first=False):
    """A JPEG with ``base`` (or each packet in a list) as standard XMP."""
    buffer = io.BytesIO()
    ph.scene(97, 61).save(buffer, format='JPEG', quality=95)
    bases = base if isinstance(base, list) else [base]
    segments = [app1(STANDARD + b) for b in bases]
    extra = [app1(p) for p in parts]
    segments = extra + segments if extension_first else segments + extra
    path.write_bytes(
        buffer.getvalue()[:2] + b''.join(segments) + buffer.getvalue()[2:]
    )
    return path


def xml_box(path):
    packets = xml_boxes(path)
    assert len(packets) == 1
    return packets[0]


def xml_boxes(path):
    data = path.read_bytes()
    offset, packets = 0, []
    while offset < len(data):
        length, name = struct.unpack_from('>I4s', data, offset)
        header = 8
        if length == 1:
            length = struct.unpack_from('>Q', data, offset + 8)[0]
            header = 16
        elif length == 0:
            length = len(data) - offset

        assert length >= header
        assert name != b'brob', 'metadata must remain uncompressed'
        if name == b'xml ':
            packets.append(data[offset + header : offset + length])

        offset += length

    return packets


def canonical(e):
    # ElementTree expands every name to its namespace URI. Attribute order and
    # indentation are irrelevant; RDF array order and text remain significant.
    children = list(e)
    if not children and not e.attrib:
        return ('scalar', e.text or '')

    return (
        tuple(sorted(e.attrib.items())),
        e.text if e.text and (not children or e.text.strip()) else '',
        tuple(
            (c.tag, canonical(c), c.tail if c.tail and c.tail.strip() else '')
            for c in children
        ),
    )


def properties(xml, normalize=False):
    root = ET.fromstring(xml)
    result = {}
    for desc in root.iter(f'{{{RDF}}}Description'):
        # Only top-level RDF descriptions; nested descriptions are structures.
        if desc not in list(root.find(f'.//{{{RDF}}}RDF')):
            continue

        for name, value in desc.attrib.items():
            if name.startswith(f'{{{RDF}}}') or name.startswith(
                '{http://www.w3.org/XML/'
            ):
                continue

            if normalize and name == f'{{{NOTE}}}HasExtendedXMP':
                continue

            if normalize and name == f'{{{TIFF}}}Orientation':
                value = '1'

            assert name not in result, f'duplicate property: {name}'
            result[name] = ('scalar', value)

        for e in desc:
            if normalize and e.tag == f'{{{NOTE}}}HasExtendedXMP':
                continue

            if normalize and e.tag == f'{{{TIFF}}}Orientation':
                e.text = '1'

            assert e.tag not in result, f'duplicate property: {e.tag}'
            result[e.tag] = canonical(e)

    return result


def convert(encoder, folder, photo):
    ph.stage(folder, [photo])
    result = encoder.run(['-q', '100', '-e', '1', 'jxl_job.txt'], folder)
    assert result.returncode == 0, result.stdout + result.stderr
    done = ph.read_done(folder)
    assert set(done) == {1}
    return done[1][0]


@pytest.mark.parametrize('reordered', [False, True])
def test_long_description_preserved(encoder, tmp_path, reordered):
    base, ext, parts = extended_pair(attrs='dc:format="image/jpeg"')
    if reordered:
        parts.reverse()

    photo = jpeg(tmp_path / 'long.jpg', base, parts, extension_first=reordered)
    out = convert(encoder, tmp_path / 'job', photo)
    actual = properties(xml_box(out))
    assert actual == properties(base, True) | properties(ext, True)
    assert actual[f'{{{DC}}}description'] == ('scalar', LONG_DESCRIPTION)
    assert f'{{{NOTE}}}HasExtendedXMP' not in actual


@pytest.mark.parametrize('extended', [False, True])
@pytest.mark.parametrize('attribute', [False, True])
def test_orientation_uses_namespace_not_prefix(
        encoder, tmp_path, extended, attribute
):
    orientation = 'camera:Orientation="6"' if attribute else ''
    body = '' if attribute else '<camera:Orientation>6</camera:Orientation>'
    orient = packet(body, orientation, declarations=f'xmlns:camera="{TIFF}"')
    if extended:
        base, ext, parts = extended_pair(orient)
    else:
        base, ext, parts = orient, None, []

    photo = jpeg(tmp_path / 'orientation.jpg', base, parts)
    out = convert(encoder, tmp_path / 'job', photo)
    actual = properties(xml_box(out))
    assert actual[f'{{{TIFF}}}Orientation'] == ('scalar', '1')
    reference = Image.open(photo).transpose(Image.Transpose.ROTATE_270)
    decoded = ph.decode_jxl(out, tmp_path / 'out.png')
    assert decoded.size == reference.size
    # stb_image and libjpeg round a few decoded JPEG samples differently.
    assert (
        np.max(
            np.abs(
                np.asarray(decoded, dtype=int)
                - np.asarray(reference, dtype=int)
            )
        )
        <= 2
    )


def test_namespace_scopes_arrays_structures_and_unicode(encoder, tmp_path):
    ext = packet(
        '<dc:subject><r:Bag><r:li>街道 &amp; sunset 🌇</r:li><r:li>café</r:li></r:Bag></dc:subject>'
        '<c:Record r:parseType="Resource"><c:Label><![CDATA[A < B]]></c:Label>'
        '<c:Coordinates><r:Description c:Latitude="12.34" c:Longitude="56.78"/></c:Coordinates></c:Record>'
        '<dc:creator><r:Seq><r:li>one</r:li><r:li>two</r:li></r:Seq></dc:creator>',
        prefix='r',
        wrapper=f'xmlns:scope="{CUSTOM}"',
    )
    # Move a namespace declaration to the wrapper, so cloning the description
    # must retain an ancestor's scope; use a conflicting prefix in the base.
    ext = (
        ext
        .replace(f'xmlns:c="{CUSTOM}" '.encode(), b'')
        .replace(b'<c:', b'<scope:')
        .replace(b'</c:', b'</scope:')
        .replace(b' c:', b' scope:')
    )
    base, _, parts = extended_pair(
        ext,
        body='<c:Label>base</c:Label>',
        declarations='xmlns:scope="https://example.org/other/"',
    )
    out = convert(
        encoder, tmp_path / 'job', jpeg(tmp_path / 'nested.jpg', base, parts)
    )
    assert properties(xml_box(out)) == properties(base, True) | properties(
        ext, True
    )


@pytest.mark.parametrize('form', ['attribute', 'element', 'nested'])
def test_identical_properties_coalesced(encoder, tmp_path, form):
    if form == 'nested':
        body = (
            '<dc:subject><rdf:Bag><rdf:li>same</rdf:li></rdf:Bag></dc:subject>'
        )
        ext = packet(body.replace('rdf:', 'r:'), prefix='r')
        base, _, parts = extended_pair(ext, body=body)
    elif form == 'element':
        ext = packet(
            '<alias:format>same</alias:format>',
            declarations=f'xmlns:alias="{DC}"',
        )
        base, _, parts = extended_pair(ext, body='<dc:format>same</dc:format>')
    else:
        ext = packet('<dc:format>same</dc:format>')
        base, _, parts = extended_pair(ext, attrs='dc:format="same"')

    out = convert(
        encoder,
        tmp_path / 'job',
        jpeg(tmp_path / 'duplicate.jpg', base, parts),
    )
    assert properties(xml_box(out)) == properties(base, True)


@pytest.mark.parametrize('extended', [False, True])
def test_xpacket_wrapper_and_processing_instructions(
        encoder, tmp_path, extended
):
    payload = packet(
        '<dc:description><![CDATA[<?xpacket stays in text?>]]></dc:description>',
        attrs='t:Orientation="6"',
    )
    payload = (
        b'<?xpacket begin="\xef\xbb\xbf"?>' + payload + b'<?xpacket end="w"?>'
    )
    if extended:
        base, ext, parts = extended_pair(payload)
        base = (
            b'<?xpacket begin="\xef\xbb\xbf"?>' + base + b'<?xpacket end="w"?>'
        )
    else:
        base, ext, parts = payload, None, []

    out = convert(
        encoder, tmp_path / 'job', jpeg(tmp_path / 'wrapped.jpg', base, parts)
    )
    assert properties(xml_box(out)) == properties(payload, True)


@pytest.mark.parametrize('element', [False, True])
def test_extended_reference_uses_namespace(encoder, tmp_path, element):
    base, ext, parts = extended_pair()
    guid = hashlib.md5(ext).hexdigest().lower()
    if element:
        base = packet(
            f'<notice:HasExtendedXMP>{guid}</notice:HasExtendedXMP>',
            declarations=f'xmlns:notice="{NOTE}"',
        )
    else:
        base = packet(
            attrs=f'notice:HasExtendedXMP="{guid}"',
            declarations=f'xmlns:notice="{NOTE}"',
        )

    out = convert(
        encoder,
        tmp_path / 'job',
        jpeg(tmp_path / 'reference.jpg', base, parts),
    )
    assert properties(xml_box(out)) == properties(ext, True)


def test_default_rdf_namespace_and_inherited_language(encoder, tmp_path):
    ext = packet(
        '<dc:title><r:Alt><r:li xml:lang="x-default">标题</r:li></r:Alt></dc:title>',
        prefix='r',
        wrapper='xml:lang="fr"',
    )
    ext = (
        ext
        .replace(b'xmlns:r=', b'xmlns=')
        .replace(b'<r:', b'<')
        .replace(b'</r:', b'</')
        .replace(
            b' r:about',
            b' xmlns:r="http://www.w3.org/1999/02/22-rdf-syntax-ns#" r:about',
        )
    )
    base, _, parts = extended_pair(ext)
    out = convert(
        encoder, tmp_path / 'job', jpeg(tmp_path / 'default.jpg', base, parts)
    )
    root = ET.fromstring(xml_box(out))
    desc = next(
        d
        for d in root.iter(f'{{{RDF}}}Description')
        if d.find(f'{{{DC}}}title') is not None
    )
    assert desc.attrib['{http://www.w3.org/XML/1998/namespace}lang'] == 'fr'
    assert properties(xml_box(out)) == properties(ext, True)


FAILURES = [
    ('missing', 'missing'),
    ('overlap', 'overlap'),
    ('truncated', 'truncated'),
    ('mismatch', 'GUID'),
    ('oversized', '16 MiB'),
    ('total', 'total length'),
    ('no-reference', 'reference'),
    ('header', 'header'),
    ('bounds', 'declared length'),
    ('invalid-extended', 'invalid'),
    ('invalid-base', 'invalid'),
    ('conflict', 'conflicting'),
    ('unbound-prefix', 'invalid'),
    ('conflicting-array', 'conflicting'),
    ('unknown-entity', 'invalid'),
    ('invalid-character', 'invalid'),
    ('duplicate-namespace-attribute', 'invalid'),
    ('empty', 'zero length'),
    ('invalid-utf8', 'invalid'),
]


@pytest.mark.parametrize('failure,message', FAILURES)
def test_invalid_xmp_fails_only_that_photo(
        encoder, tmp_path, failure, message
):
    base, ext, parts = extended_pair()
    if failure == 'missing':
        parts = parts[1:]
    elif failure == 'overlap':
        parts.insert(1, parts[0])
    elif failure == 'truncated':
        parts[-1] = parts[-1][:-7]
    elif failure == 'mismatch':
        parts[0] = EXTENDED + b'0' * 32 + parts[0][len(EXTENDED) + 32 :]
    elif failure in ('oversized', 'total', 'empty'):
        total = {
            'oversized': 16 * 1024 * 1024 + 1,
            'total': len(ext) + 1,
            'empty': 0,
        }[failure]
        parts[0] = (
            parts[0][: len(EXTENDED) + 32]
            + struct.pack('>I', total)
            + parts[0][len(EXTENDED) + 36 :]
        )
    elif failure == 'no-reference':
        base = packet()
    elif failure == 'header':
        parts[0] = parts[0][: len(EXTENDED) + 39]
    elif failure == 'bounds':
        parts[-1] = (
            parts[-1][: len(EXTENDED) + 36]
            + struct.pack('>I', len(ext) + 1)
            + parts[-1][len(EXTENDED) + 40 :]
        )
    elif failure == 'invalid-extended':
        base, ext, parts = extended_pair(b'<invalid>')
    elif failure == 'invalid-base':
        base = b'<invalid>'
    elif failure == 'unbound-prefix':
        base, ext, parts = extended_pair(
            packet('<undeclared:tag>bad</undeclared:tag>')
        )
    elif failure == 'conflict':
        base, ext, parts = extended_pair(
            packet('<dc:format>different</dc:format>'),
            attrs='dc:format="base"',
        )
    elif failure == 'conflicting-array':
        body = '<dc:subject><rdf:Seq><rdf:li>A</rdf:li><rdf:li>B</rdf:li></rdf:Seq></dc:subject>'
        base, ext, parts = extended_pair(
            packet(body.replace('>A<', '>C<')), body=body
        )

    if failure == 'invalid-utf8':
        base, ext, parts = extended_pair(
            packet('<dc:description>text</dc:description>').replace(
                b'text', b'\xc0\xaf'
            )
        )
    elif failure == 'unknown-entity':
        base, ext, parts = extended_pair(
            packet('<dc:description>&undefined;</dc:description>')
        )
    elif failure == 'invalid-character':
        base, ext, parts = extended_pair(
            packet('<dc:description>&#0;</dc:description>')
        )
    elif failure == 'duplicate-namespace-attribute':
        base, ext, parts = extended_pair(
            packet(
                attrs='dc:format="one" alias:format="two"',
                declarations=f'xmlns:alias="{DC}"',
            )
        )

    photo = jpeg(tmp_path / 'bad.jpg', base, parts)
    good = jpeg(
        tmp_path / 'good.jpg',
        packet('<dc:description>keep me</dc:description>'),
    )
    folder = tmp_path / 'job'
    ph.stage(folder, [photo, good])
    result = encoder.run(['-q', '83', '-e', '1', 'jxl_job.txt'], folder)
    assert result.returncode == 0, result.stdout + result.stderr
    assert message in ' '.join(result.stdout.split()), result.stdout
    # The shortcut's deletion eligibility comes only from this result list.
    assert set(ph.read_done(folder)) == {2}
    assert not (folder / 'jxl_out_1.jxl').exists()
    assert properties(xml_box(folder / 'jxl_out_2.jxl')) == properties(
        packet('<dc:description>keep me</dc:description>')
    )


def test_exiftool_extended_description(encoder, tmp_path, need_tools):
    photo = tmp_path / 'exiftool.jpg'
    ph.scene(97, 61).save(photo, format='JPEG')
    description = tmp_path / 'description.txt'
    description.write_text(LONG_DESCRIPTION, encoding='utf-8')
    ph.run(
        [
            'exiftool',
            '-q',
            '-overwrite_original',
            f'-XMP-dc:Description<={description}',
            '-XMP-tiff:Orientation=6',
            '-n',
            photo,
        ],
        check=True,
    )
    assert EXTENDED in photo.read_bytes(), 'fixture must use JPEG extended XMP'
    out = convert(encoder, tmp_path / 'job', photo)
    assert ph.xmp_properties(photo) == ph.xmp_properties(out)
    assert ph.xmp_tags(out)['Description'] == LONG_DESCRIPTION


# Standard (non-extended) XMP is copied byte for byte: the strict XML checks
# above apply only when extended XMP has to be merged. Photos from other apps
# often carry XMP that isn't strict XML; they must still convert.
QUIRKS = {
    'trailing NUL': packet('<dc:description>x</dc:description>') + b'\0',
    'Latin-1 text': packet('<dc:description>cafe</dc:description>').replace(
        b'cafe', b'caf\xe9'
    ),
    'HTML entity': packet('<dc:description>a&nbsp;b</dc:description>'),
    'undeclared prefix': packet('<photoshop:City>Paris</photoshop:City>'),
    'not XML': b'<invalid>',
    'extension no longer in the file': extended_pair()[0],
}


@pytest.mark.parametrize('name', QUIRKS)
def test_standard_xmp_kept_as_is(encoder, tmp_path, name):
    payload = QUIRKS[name]
    out = convert(
        encoder, tmp_path / 'job', jpeg(tmp_path / 'quirk.jpg', payload)
    )
    assert xml_box(out) == payload


ORIENTED = {
    # Well-formed: the prefix bound to the TIFF namespace ("t" here) is used.
    'well-formed': (
        b'<?xpacket begin="\xef\xbb\xbf"?>\n'
        + packet(attrs='t:Orientation="6"')
        + b'\n<?xpacket end="w"?>',
        b't:Orientation="6"',
        b't:Orientation="1"',
    ),
    # Not strict XML: the conventional "tiff:" prefix is assumed.
    'not strict XML': (
        packet(
            '<tiff:Orientation>8</tiff:Orientation>',
            declarations=f'xmlns:tiff="{TIFF}"',
        )
        + b'\0',
        b'<tiff:Orientation>8<',
        b'<tiff:Orientation>1<',
    ),
}


@pytest.mark.parametrize('name', ORIENTED)
def test_orientation_reset_changes_only_that_digit(encoder, tmp_path, name):
    payload, before, after = ORIENTED[name]
    out = convert(
        encoder, tmp_path / 'job', jpeg(tmp_path / 'oriented.jpg', payload)
    )
    assert xml_box(out) == payload.replace(before, after)
    # Without EXIF, the XMP orientation turned the 97x61 pixels upright.
    assert ph.decode_jxl(out, tmp_path / 'out.png').size == (61, 97)


@pytest.mark.parametrize(
    'packets,kept',
    [
        ([b'', packet(body='<dc:format>A</dc:format>')], 1),
        (
            [
                packet(body='<dc:format>A</dc:format>'),
                packet(body='<dc:format>B</dc:format>'),
            ],
            0,
        ),
        ([b''], None),
    ],
    ids=['empty then packet', 'two packets', 'only empty'],
)
def test_first_nonempty_packet_kept(encoder, tmp_path, packets, kept):
    out = convert(
        encoder, tmp_path / 'job', jpeg(tmp_path / 'packets.jpg', packets)
    )
    assert xml_boxes(out) == ([] if kept is None else [packets[kept]])
