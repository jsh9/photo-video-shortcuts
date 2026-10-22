"""
The generated shortcut (scripts/build_shortcuts.py), checked without a device:
its blocks and variables, that it uses only Shortcuts' own actions (no
a-Shell), its note and surfaces, the image steps' settings, and the EXIF
segment's layout; on the Mac, its AppleScripts compiling against Photos'
dictionary and its scripts running only on a Mac. What it does is run on a
model in test_stack_flow.py and test_mac_route.py.
"""

import base64
import io
import struct

import PIL.Image
import pytest
import stack_helpers as sh

BUILT_IN = 'is.workflow.actions.'
# Shortcuts' actions that only the Mac has (or that run a script anywhere).
MAC_ONLY = {
    'runshellscript',
    'runapplescript',
    'runjavascriptforautomation',
    'runsshscript',
    'file.select',
}


def of(actions, kind):
    return [a for a in actions if sh.ident(a) == BUILT_IN + kind]


def test_blocks_balanced(actions):
    list(sh.walk(actions))


def test_outputs_used_after_they_exist(actions):
    seen = set()
    for action in actions:
        for ref in sh.references(sh.params(action)):
            if ref.get('Type') == 'ActionOutput':
                assert ref['OutputUUID'] in seen, ref

        seen.add(sh.params(action).get('UUID'))


def test_repeat_variables_in_scope(actions):
    for action, depth in sh.walk(actions):
        for ref in sh.references(sh.params(action)):
            if ref.get('VariableName') in ('Repeat Item', 'Repeat Index'):
                assert depth == 1, sh.ident(action)  # no nested repeats


def test_only_built_in_actions(actions):
    assert all(sh.ident(a).startswith(BUILT_IN) for a in actions)


def test_mac_only_actions_run_only_on_a_mac(actions):
    # Run AppleScript and Run Shell Script (the Mac's route from Photos) sit
    # in the branch of the If on Device Model "^Mac", or in the cleanup that
    # only that route reaches (From Photos); the iPhone never runs them.
    (mac,) = [
        a
        for a in of(actions, 'text.match')
        if sh.params(a)['WFMatchTextPattern'] == '^Mac'
    ]
    on_mac = dict(
        (id(a), inside)
        for a, inside in sh.inside_if_on(actions, sh.params(mac)['UUID'])
    )
    from_photos = dict(
        (id(a), inside)
        for a, inside in sh.inside_if_on(actions, 'From Photos')
    )
    mac_only = [
        a for a in actions if sh.ident(a).removeprefix(BUILT_IN) in MAC_ONLY
    ]
    # probe, the work folder, export, stage, and the cleanup after saving,
    # before "Nothing to stack" and when nothing could be combined
    assert len(mac_only) == 7
    for action in mac_only:
        assert on_mac[id(action)] or from_photos[id(action)], action


def test_applescripts_are_plain_text(gen, actions):
    # A Shortcuts variable inside a Run AppleScript's text keeps it from
    # compiling; the export's input is the work folder.
    scripts = of(actions, 'runapplescript')
    assert [sh.params(a)['Script'] for a in scripts] == [
        gen.applescript('probe'),
        gen.applescript('export'),
    ]
    assert 'Input' not in sh.params(scripts[0])
    assert 'Input' in sh.params(scripts[1])


def test_applescripts_compile(gen, tmp_path):
    # osacompile reads Photos' dictionary without launching it.
    import shutil
    import subprocess

    sh.need(shutil.which('osacompile'), 'osacompile is needed')
    for name in ('probe', 'export'):
        src = tmp_path / f'{name}.applescript'
        src.write_text(gen.applescript(name))
        result = subprocess.run(
            ['osacompile', '-o', str(src.with_suffix('.scpt')), str(src)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (name, result.stderr)


# Each action's input, as shortcuts built on a device store it (shortcut files
# shared in suliveevil/My-Siri-Shortcuts, Shortcuts 1050; this repository's
# own for the rest): the key, and whether it is a text field (a
# WFTextTokenString holding the variable) or the variable itself. Shortcuts
# ignores a key it doesn't know: Calculate Statistics' input under "WFInput"
# reached it as nothing, and so did every size after it (Stack Photos'
# first Mac run, macOS 27).
INPUTS = {
    'statistics': ('Input', 'WFTextTokenAttachment'),
    'count': ('Input', 'WFTextTokenAttachment'),
    'math': ('WFInput', 'WFTextTokenAttachment'),
    'round': ('WFInput', 'WFTextTokenAttachment'),
    'image.resize': ('WFImage', 'WFTextTokenAttachment'),
    'image.crop': ('WFInput', 'WFTextTokenAttachment'),
    'overlayimageonimage': ('WFInput', 'WFTextTokenAttachment'),
    'image.combine': ('WFInput', 'WFTextTokenAttachment'),
    'image.convert': ('WFInput', 'WFTextTokenAttachment'),
    'base64encode': ('WFInput', 'WFTextTokenAttachment'),
    'text.replace': ('WFInput', 'WFTextTokenString'),
    'gettimebetweendates': ('WFInput', 'WFTextTokenString'),
    'adjustdate': ('WFDate', 'WFTextTokenString'),
    'format.date': ('WFDate', 'WFTextTokenString'),
    'properties.images': ('WFInput', 'WFTextTokenAttachment'),
    'getitemfromlist': ('WFInput', 'WFTextTokenAttachment'),
    'text.match': ('text', 'WFTextTokenString'),
    'text.split': ('text', 'WFTextTokenAttachment'),
    'detect.text': ('WFInput', 'WFTextTokenAttachment'),
    'savetocameraroll': ('WFInput', 'WFTextTokenAttachment'),
    'setitemname': ('WFInput', 'WFTextTokenAttachment'),
    'getitemname': ('WFInput', 'WFTextTokenAttachment'),
}


@pytest.mark.parametrize('kind', sorted(INPUTS))
def test_inputs_as_shortcuts_store_them(actions, kind):
    key, serialization = INPUTS[kind]
    found = of(actions, kind)
    assert found, kind
    for action in found:
        p = sh.params(action)
        assert key in p, (kind, sorted(p))
        assert p[key]['WFSerializationType'] == serialization, kind
        others = {'WFInput', 'Input', 'WFImage', 'WFDate', 'text'} - {key}
        if kind != 'overlayimageonimage':  # its overlay is WFImage
            assert not others & set(p), (kind, sorted(p))


def test_note(gen, actions):
    note = sh.params(actions[0])['WFCommentActionText']
    assert note.startswith(f'Stack Photos {sh.VERSION}. ')
    assert note.endswith(gen.HELP_URL)
    assert gen.VERSION == sh.VERSION


def test_surfaces(gen, actions):
    wf = gen.stack_workflow(gen.Sample(gen.wfkit.guessed_workflow()), actions)
    assert wf['WFWorkflowName'] == 'Stack Photos'
    assert wf['WFWorkflowHasShortcutInputVariables'] is True
    assert wf['WFWorkflowTypes'] == ['ActionExtension', 'QuickActions']
    assert wf['WFWorkflowInputContentItemClasses'] == ['WFImageContentItem']
    assert wf['WFQuickActionSurfaces'] == ['Finder', 'Services']


def test_picker_shows_images_only(actions):
    # with no input on an iPhone, or on a Mac with nothing selected in Photos
    pickers = of(actions, 'selectphoto')
    assert len(pickers) == 2
    for picker in pickers:
        p = dict(sh.params(picker))
        del p['UUID']
        assert p == {
            'WFSelectMultiplePhotos': True,
            'WFPhotoPickerTypes': ['Images'],
        }


def test_photos_resized_only_as_png(actions):
    # Every photo is converted to PNG before Resize Image, which keeps the
    # input's type: nothing is re-encoded lossily before the final JPEG. The
    # other resize is the pad canvas, a decoded PNG.
    made = {
        sh.params(a)['UUID']: a
        for a in of(actions, 'image.convert') + of(actions, 'base64encode')
    }
    resizes = of(actions, 'image.resize')
    assert len(resizes) == 5  # two kept shapes, crop, pad, the canvas
    for resize in resizes:
        source = made[sh.params(resize)['WFImage']['Value']['OutputUUID']]
        p = sh.params(source)
        assert (
            p.get('WFImageFormat') == 'PNG'
            or p.get('WFEncodeMode') == 'Decode'
        )


def test_final_jpeg(gen, actions):
    formats = [
        sh.params(a)['WFImageFormat'] for a in of(actions, 'image.convert')
    ]
    assert formats == ['PNG', 'JPEG']
    (jpeg,) = [
        a
        for a in of(actions, 'image.convert')
        if sh.params(a)['WFImageFormat'] == 'JPEG'
    ]
    assert sh.params(jpeg)['WFImageCompressionQuality'] == gen.QUALITY == 0.9
    assert all(
        sh.params(a)['WFImagePreserveMetadata'] is False
        for a in of(actions, 'image.convert')
    )
    combines = of(actions, 'image.combine')
    assert [sh.params(a)['WFImageCombineMode'] for a in combines] == [
        'Horizontally',
        'Vertically',
    ]
    assert all(sh.params(a)['WFImageCombineSpacing'] == '0' for a in combines)
    (save,) = of(actions, 'savetocameraroll')
    assert 'WFCameraRollSelectedGroup' not in sh.params(save)


def test_base64_on_one_line(actions):
    for action in of(actions, 'base64encode'):
        assert sh.params(action)['WFBase64LineBreakMode'] == 'None'


@pytest.mark.parametrize('with_jfif', [True, False])
def test_exif_slots_on_whole_groups(gen, with_jfif):
    data = gen.prefix_bytes(with_jfif)
    assert len(data) % 3 == 0
    pieces = gen.prefix_pieces(with_jfif)
    assert [p for p in pieces if p in ('date', 'offset')] == ['date'] * 3 + [
        'offset'
    ] * 3
    # the constant pieces put back around a date's and an offset's base64
    # give the segment with those values
    date, offset = b'2026:05:02 07:16:04', b'+09:00'
    values = {
        'date': base64.b64encode(date).decode().replace('=', ''),
        'offset': base64.b64encode(offset).decode(),
    }
    text = ''.join(values.get(p, p) for p in pieces)
    expected = gen.prefix_bytes(with_jfif).replace(
        gen.exif_segment(), gen.exif_segment(date, offset)
    )
    assert base64.b64decode(text) == expected


def test_exif_segment_read_by_pillow(gen):
    segment = gen.exif_segment(b'2026:05:02 07:16:04', b'+09:00')
    assert segment[:2] == b'\xff\xe1'
    assert struct.unpack('>H', segment[2:4])[0] == len(segment) - 2
    jpeg = io.BytesIO()
    PIL.Image.new('RGB', (8, 8)).save(jpeg, 'JPEG')
    data = jpeg.getvalue()
    with PIL.Image.open(io.BytesIO(data[:2] + segment + data[2:])) as image:
        tags = image.getexif()
        sub = tags.get_ifd(0x8769)

    assert tags[0x0132] == sub[0x9003] == sub[0x9004] == '2026:05:02 07:16:04'
    assert sub[0x9010] == sub[0x9011] == sub[0x9012] == '+09:00'
    assert sub[0x9000] == b'0232' and sub[0xA001] == 1


def test_patterns_match_imageio_jpeg(gen):
    # The committed fixture was written by imageio.swift (as Convert Image
    # writes); test_imageio.py checks that today's ImageIO still does.
    start = base64.b64encode(
        (sh.FIXTURES / 'imageio.jpg').read_bytes()
    ).decode()
    assert start.startswith(gen.MAIN_PATTERN.removeprefix('^'))
    assert start.startswith(gen.FALLBACK_PATTERN.removeprefix('^'))
