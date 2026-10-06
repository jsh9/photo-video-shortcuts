"""
The generated shortcuts (scripts/build_shortcuts.py), checked without an
iPhone: their structure, the a-Shell actions, the quality presets, and the file
names they share with jxlbatch.
"""

import photo_helpers as ph
import pytest


@pytest.fixture(scope='module')
def gen():
    return ph.load_generator()


@pytest.fixture(scope='module')
def shortcuts(gen):
    sample = gen.Sample(gen.guessed_workflow())
    return {
        gen.NAME_A: gen.build_compress(sample),
        gen.NAME_B: gen.build_import(sample),
    }


@pytest.mark.parametrize('name', ['Compress Photos', 'JXL-Import'])
def test_blocks_balanced(shortcuts, name):
    list(ph.walk(shortcuts[name]))


@pytest.mark.parametrize('name', ['Compress Photos', 'JXL-Import'])
def test_outputs_used_after_they_exist(shortcuts, name):
    seen = set()
    for action in shortcuts[name]:
        for ref in ph.references(ph.params(action)):
            if ref.get('Type') == 'ActionOutput':
                assert ref['OutputUUID'] in seen, ref

        seen.add(ph.params(action).get('UUID'))


@pytest.mark.parametrize('name', ['Compress Photos', 'JXL-Import'])
def test_repeat_variables_in_scope(shortcuts, name):
    # "Repeat Item 2" is the item of a repeat inside a repeat.
    for action, depth in ph.walk(shortcuts[name]):
        for ref in ph.references(ph.params(action)):
            var = ref.get('VariableName', '')
            if var == 'Repeat Item 2':
                assert depth >= 2, ph.ident(action)
            elif var in ('Repeat Item', 'Repeat Index'):
                assert depth >= 1, ph.ident(action)


@pytest.mark.parametrize('name', ['Compress Photos', 'JXL-Import'])
def test_ashell_actions(shortcuts, name):
    # An IntentAppDefinition block made them "Unknown Action" on the iPhone.
    allowed = {'ExecuteCommandIntent', 'PutFileIntent', 'GetFileIntent'}
    for action in shortcuts[name]:
        if ph.ident(action).startswith('AsheKube.app.a-Shell.'):
            assert ph.ident(action).rsplit('.', 1)[1] in allowed
            assert 'IntentAppDefinition' not in ph.params(action)


def test_quality_presets(gen, shortcuts):
    cards_text = next(
        ph.render(ph.params(a)['WFTextActionText'], {})
        for a in shortcuts[gen.NAME_A]
        if ph.ident(a) == 'is.workflow.actions.gettext'
        and 'BEGIN:VCARD' in str(ph.params(a)['WFTextActionText'])
    )
    cards = cards_text.split('END:VCARD')[:-1]
    assert len(cards) == len(gen.QUALITY_PRESETS)
    for card, (quality, description) in zip(
        cards, gen.QUALITY_PRESETS, strict=True
    ):
        fields = dict(
            line.split(':', 1) for line in card.strip().splitlines()[1:]
        )
        title = fields['N;CHARSET=utf-8']
        default = ' (default)' if quality == gen.DEFAULT_QUALITY else ''
        assert title == f'{quality}{default}'
        org = fields['ORG;CHARSET=utf-8'].replace('\\;', ';')
        assert org == description


def test_notes_show_version(gen, shortcuts):
    version = (ph.TOOL / 'VERSION').read_text().strip()
    assert gen.VERSION == version
    for name, actions in shortcuts.items():
        first = ph.params(actions[0])['WFCommentActionText']
        assert f'{gen.NAME_A} {version}' in first, name


def test_import_shortcut_started_by_name(gen, shortcuts):
    # a-Shell opens JXL-Import by URL, so its name must not change.
    assert gen.NAME_B == 'JXL-Import'
    commands = ph.ashell_commands(
        shortcuts[gen.NAME_A], {'Matches': 83, 'Skipped Echo': ''}
    )
    assert any(
        c.endswith('open shortcuts://run-shortcut?name=JXL-Import')
        for c in commands
    )


def test_cleanup_removes_every_file(gen):
    # Everything the shortcut and jxlbatch leave in a-Shell's folder.
    for pattern in (
        'jxl_in_*',
        'jxl_out_*',
        'jxl_albums_*',
        'jxl_job.txt',
        'jxl_done.txt',
        'jxl_started',
    ):
        assert pattern in gen.CLEANUP.split()


def test_share_sheet_settings(gen, shortcuts):
    sample = gen.Sample(gen.guessed_workflow())
    compress = gen.workflow(sample, gen.NAME_A, shortcuts[gen.NAME_A], True)
    importer = gen.workflow(sample, gen.NAME_B, shortcuts[gen.NAME_B], False)
    assert 'ActionExtension' in compress['WFWorkflowTypes']
    assert (
        'WFImageContentItem' in compress['WFWorkflowInputContentItemClasses']
    )
    assert 'ActionExtension' not in importer['WFWorkflowTypes']


def test_written_file_is_valid(gen, shortcuts, tmp_path, monkeypatch):
    # write() checks the file with plutil; signing needs an Apple ID.
    monkeypatch.setattr(gen, 'OUT', tmp_path)
    monkeypatch.setattr(gen, 'DIST', tmp_path)
    sample = gen.Sample(gen.guessed_workflow())
    for name, actions in shortcuts.items():
        wf = gen.workflow(sample, name, actions, name == gen.NAME_A)
        gen.write(name, wf, sign=False)
        assert (tmp_path / f'{name}.unsigned.wflow').exists()


def test_originals_collected_in_the_album_never_deleted(gen, shortcuts):
    # The converted originals go into the album ORIGINALS_ALBUM (Save to
    # Photo Album adds a library photo there without a copy) unless the
    # photo's albums already list it; nothing is deleted. From the share
    # sheet, before a-Shell takes over (the shortcut is then over); from the
    # picker, after each copy is saved. jxlbatch's "delete"/"keep" flag in
    # jxl_done.txt is not acted on.
    actions = shortcuts['Compress Photos']
    idents = [ph.ident(a) for a in actions]
    assert 'is.workflow.actions.deletephotos' not in idents
    assert not [
        a
        for a in actions
        if ph.ident(a) == 'is.workflow.actions.text.match'
        and ph.params(a).get('WFMatchTextPattern') == '^delete$'
    ]
    texts = {
        ph.params(a)['UUID']
        for a in actions
        if ph.ident(a) == 'is.workflow.actions.gettext'
        and ph.params(a)['WFTextActionText']['Value']
        == {'string': gen.ORIGINALS_ALBUM}
    }
    saves = [
        i
        for i, a in enumerate(actions)
        if ph.ident(a) == 'is.workflow.actions.savetocameraroll'
        and ph
        .params(a)
        .get('WFCameraRollSelectedGroup', {})
        .get('Value', {})
        .get('OutputUUID')
        in texts
    ]
    pattern = f'(^|\\n){gen.ORIGINALS_ALBUM}($|\\n)'
    checks = [
        i
        for i, a in enumerate(actions)
        if ph.ident(a) == 'is.workflow.actions.text.match'
        and ph.params(a).get('WFMatchTextPattern') == pattern
    ]
    assert len(saves) == len(checks) == 2
    assert checks[0] < saves[0] < checks[1] < saves[1]
    # only library photos: an image from another app answers nothing to
    # Is Favorite, and Save to Photo Album would import it as a new photo
    favorites = [
        i
        for i, a in enumerate(actions)
        if ph.ident(a) == 'is.workflow.actions.properties.images'
        and ph.params(a)['WFContentItemPropertyName'] == 'Is Favorite'
    ]
    assert len(favorites) == 2
    assert favorites[0] < checks[0] and favorites[1] < checks[1]
    runs = [
        i
        for i, a in enumerate(actions)
        if ph.ident(a).startswith(gen.ASHELL_BUNDLE_ID)
        and 'jxlbatch' in repr(ph.params(a))
    ]
    assert saves[0] < runs[0], 'the share-sheet route collects before a-Shell'
    assert saves[1] > runs[-1], 'the picker route collects after the save'
    # The share-sheet route writes the originals' album lists (for
    # JXL-Import) before collecting them, or a re-converted photo's new copy
    # would join the review album.
    album_files = [
        i
        for i, a in enumerate(actions)
        if ph.ident(a) == 'is.workflow.actions.setitemname'
        and 'jxl_albums_' in repr(ph.params(a)['WFName'])
    ]
    assert album_files and max(album_files) < saves[0]
    # JXL-Import saves copies into their originals' albums only
    importer = shortcuts['JXL-Import']
    assert 'is.workflow.actions.deletephotos' not in [
        ph.ident(a) for a in importer
    ]
