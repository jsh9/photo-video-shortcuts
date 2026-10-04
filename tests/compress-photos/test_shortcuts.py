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


def walk(actions):
    """(action, repeat depth) in order, checking control flow nests."""
    stack = []
    for action in actions:
        p = ph.params(action)
        if ph.ident(action) in ph.CONTROL_FLOW:
            mode = p['WFControlFlowMode']
            if mode == 0:
                stack.append((p['GroupingIdentifier'], ph.ident(action)))
            else:
                assert stack, f'{ph.ident(action)} closes nothing'
                assert stack[-1] == (p['GroupingIdentifier'], ph.ident(action))
                if mode == 2:
                    stack.pop()

        depth = sum(1 for _, kind in stack if kind.endswith('repeat.each'))
        yield action, depth

    assert not stack, f'unclosed blocks: {stack}'


@pytest.mark.parametrize('name', ['Compress Photos', 'JXL-Import'])
def test_blocks_balanced(shortcuts, name):
    list(walk(shortcuts[name]))


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
    for action, depth in walk(shortcuts[name]):
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


def test_kept_originals_not_offered_for_deletion(shortcuts):
    # Each jxl_done.txt line is "file|index|delete or keep|name". An original
    # joins Converted (offered for deletion at the end) only inside "If
    # (item 3 matches ^delete$) has any value": "keep" (the JXL lacks its
    # HDR) and older jxlbatch lines (item 3 is then the name) keep it.
    actions = shortcuts['Compress Photos']
    matches = [
        ph.params(a)['UUID']
        for a in actions
        if ph.ident(a) == 'is.workflow.actions.text.match'
        and ph.params(a).get('WFMatchTextPattern') == '^delete$'
    ]
    assert len(matches) == 1
    groups, inside = set(), []
    appended = 0
    for action in actions:
        p = ph.params(action)
        if ph.ident(action) == 'is.workflow.actions.conditional':
            group, mode = p['GroupingIdentifier'], p['WFControlFlowMode']
            if mode == 0 and matches[0] in repr(p.get('WFInput')):
                groups.add(group)
                inside.append(group)
            elif group in groups and mode in (1, 2) and group in inside:
                inside.remove(group)

        if ph.ident(action) == 'is.workflow.actions.appendvariable' and (
            p['WFVariableName'] == 'Converted'
        ):
            assert inside, 'an original joins Converted unconditionally'
            appended += 1

    assert appended == 1


def test_delete_prompt_only_with_originals_to_delete(shortcuts):
    # When every original is "keep", Converted is empty: Delete Photos runs
    # only inside "If Converted has any value".
    actions = shortcuts['Compress Photos']
    deletes, open_groups = 0, []
    for action in actions:
        p = ph.params(action)
        if ph.ident(action) == 'is.workflow.actions.conditional':
            group, mode = p['GroupingIdentifier'], p['WFControlFlowMode']
            if mode == 0:
                open_groups.append((
                    group,
                    "'Converted'" in repr(p['WFInput']),
                ))
            elif mode == 1:
                open_groups[-1] = (group, False)  # the Otherwise branch
            else:
                open_groups.pop()

        if ph.ident(action) == 'is.workflow.actions.deletephotos':
            assert any(converted for _, converted in open_groups)
            deletes += 1

    assert deletes == 1
