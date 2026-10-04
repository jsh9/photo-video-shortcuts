"""
The generated Mac shortcuts (scripts/build_mac_shortcuts.py), checked without
importing them: their structure, surfaces, the Run Shell Script and Run
AppleScript actions, the quality presets, and the file names and lines they
share with jxlbatch. The script itself runs for real in test_mac_script.py.
"""

import photo_helpers as ph
import pytest

PHOTOS = 'Compress Photos (macOS)'
FILES = 'Compress Photo Files (macOS)'
RUN_SHELL = 'is.workflow.actions.runshellscript'
RUN_APPLESCRIPT = 'is.workflow.actions.runapplescript'


@pytest.fixture(scope='module')
def gen():
    return ph.load_generator('build_mac_shortcuts')


@pytest.fixture(scope='module')
def wf():
    return ph.load_generator('wf')


@pytest.fixture(scope='module')
def sample(gen, wf):
    return wf.Sample(wf.guessed_workflow())


@pytest.fixture(scope='module')
def shortcuts(gen, sample):
    return {
        PHOTOS: gen.build_photos(sample),
        FILES: gen.build_files(sample),
    }


@pytest.fixture(scope='module')
def workflows(gen, sample, shortcuts):
    return {
        PHOTOS: gen.photos_workflow(sample, shortcuts[PHOTOS]),
        FILES: gen.files_workflow(sample, shortcuts[FILES]),
    }


def test_names(gen):
    assert gen.NAME_PHOTOS == PHOTOS
    assert gen.NAME_FILES == FILES


@pytest.mark.parametrize('name', [PHOTOS, FILES])
def test_blocks_balanced(shortcuts, name):
    list(ph.walk(shortcuts[name]))


@pytest.mark.parametrize('name', [PHOTOS, FILES])
def test_outputs_used_after_they_exist(shortcuts, name):
    seen = set()
    for action in shortcuts[name]:
        for ref in ph.references(ph.params(action)):
            if ref.get('Type') == 'ActionOutput':
                assert ref['OutputUUID'] in seen, ref

        seen.add(ph.params(action).get('UUID'))


@pytest.mark.parametrize('name', [PHOTOS, FILES])
def test_repeat_variables_in_scope(shortcuts, name):
    for action, depth in ph.walk(shortcuts[name]):
        for ref in ph.references(ph.params(action)):
            var = ref.get('VariableName', '')
            if var == 'Repeat Item 2':
                assert depth >= 2, ph.ident(action)
            elif var in ('Repeat Item', 'Repeat Index'):
                assert depth >= 1, ph.ident(action)


@pytest.mark.parametrize('name', [PHOTOS, FILES])
def test_no_ashell_and_no_handoff(shortcuts, name):
    # The Mac shortcuts run jxlbatch themselves and wait for it.
    for action in shortcuts[name]:
        assert not ph.ident(action).startswith('AsheKube.app.a-Shell.')
        assert ph.ident(action) != 'is.workflow.actions.waittoreturn'
        assert 'shortcuts://' not in repr(ph.params(action))


@pytest.mark.parametrize('name', [PHOTOS, FILES])
def test_shell_scripts_use_zsh_with_files_as_arguments(shortcuts, name):
    scripts = [a for a in shortcuts[name] if ph.ident(a) == RUN_SHELL]
    assert scripts
    for a in scripts:
        p = ph.params(a)
        assert p['Shell'] == '/bin/zsh'
        assert p['InputMode'] == 'as arguments'

    # The batch script gets the photos (or files) as its input; the small
    # follow-up scripts (log, cleanup) have no input.
    with_input = [a for a in scripts if 'Input' in ph.params(a)]
    assert len(with_input) == 1
    text = ph.render(
        ph.params(with_input[0])['Script'],
        {
            'Matches': '83',
            'Combined Text': 'IMG_0001.HEIC',
            'Skipped Echo': '',
        },
    )
    assert "QUALITY='83'" in text
    assert 'for f in "$@"; do' in text
    assert '-e 7 -C "$WORK" jxl_job.txt' in text
    assert 'jxl_in_$' in text and 'jxl_done.txt' in text


def test_photos_results_saved_through_applescript_files(shortcuts):
    # Each output line is "path|index|delete or keep|Name.jxl": the path
    # becomes a File through Run AppleScript, renamed to Name.jxl and saved.
    actions = shortcuts[PHOTOS]
    scripts = [a for a in actions if ph.ident(a) == RUN_APPLESCRIPT]
    assert len(scripts) == 1
    text = ph.render(ph.params(scripts[0])['Script'], {'Item from List': 'P'})
    assert (
        text == 'on run {input, parameters}\n\treturn POSIX file "P"\nend run'
    )
    idents = [ph.ident(a) for a in actions]
    assert (
        idents.index(RUN_APPLESCRIPT)
        < idents.index(
            'is.workflow.actions.setitemname', idents.index(RUN_APPLESCRIPT)
        )
        < idents.index('is.workflow.actions.savetocameraroll')
    )


def test_photos_kept_originals_not_offered_for_deletion(shortcuts):
    # As on the iPhone: an original joins Converted only inside "If (item 3
    # matches ^delete$) has any value".
    actions = shortcuts[PHOTOS]
    matches = [
        ph.params(a)['UUID']
        for a in actions
        if ph.ident(a) == 'is.workflow.actions.text.match'
        and ph.params(a).get('WFMatchTextPattern') == '^delete$'
    ]
    assert len(matches) == 1
    appended = 0
    for action, inside in ph.inside_if_on(actions, matches[0]):
        if ph.ident(action) == 'is.workflow.actions.appendvariable' and (
            ph.params(action)['WFVariableName'] == 'Converted'
        ):
            assert inside, 'an original joins Converted unconditionally'
            appended += 1

    assert appended == 1


def test_photos_delete_prompt_only_with_originals_to_delete(shortcuts):
    actions = shortcuts[PHOTOS]
    deletes = 0
    for action, inside in ph.inside_if_on(actions, "'Converted'"):
        if ph.ident(action) == 'is.workflow.actions.deletephotos':
            assert inside
            deletes += 1

    assert deletes == 1


def test_photos_log_shown_only_with_warnings(gen, shortcuts):
    # Quick Look runs inside "If (log matches WARNINGS) has any value", and
    # before the delete prompt.
    actions = shortcuts[PHOTOS]
    warn = [
        ph.params(a)['UUID']
        for a in actions
        if ph.ident(a) == 'is.workflow.actions.text.match'
        and ph.params(a).get('WFMatchTextPattern') == gen.WARNINGS
    ]
    assert len(warn) == 1
    looks = [
        (i, inside)
        for i, (action, inside) in enumerate(ph.inside_if_on(actions, warn[0]))
        if ph.ident(action) == 'is.workflow.actions.previewdocument'
    ]
    assert looks and all(inside for _, inside in looks)
    idents = [ph.ident(a) for a in actions]
    assert looks[0][0] < idents.index('is.workflow.actions.deletephotos')


def test_files_shortcut_never_touches_photos(shortcuts):
    for action in shortcuts[FILES]:
        assert ph.ident(action) not in (
            'is.workflow.actions.deletephotos',
            'is.workflow.actions.savetocameraroll',
            'is.workflow.actions.selectphoto',
        )


def test_files_passes_real_paths(shortcuts):
    # Get Details of Files ▸ File Path for each input, one line each (an empty
    # line when unknown), so the results land next to the originals.
    actions = shortcuts[FILES]
    details = [
        a
        for a in actions
        if ph.ident(a) == 'is.workflow.actions.properties.files'
    ]
    assert [ph.params(a)['WFContentItemPropertyName'] for a in details] == [
        'File Path'
    ]
    text = ph.shell_scripts(
        actions,
        {
            'Matches': '72',
            'Combined Text': '/a/b.heic\n\n/c',
            'Skipped Echo': '',
        },
    )[0]
    assert "PATHS=$(cat <<'JXL_LINES'\n/a/b.heic\n\n/c\nJXL_LINES\n)" in text


def test_surfaces(workflows):
    photos, files = workflows[PHOTOS], workflows[FILES]
    # Photos: the Share menu (and a picker when started elsewhere).
    assert photos['WFWorkflowTypes'] == ['ActionExtension']
    assert photos['WFWorkflowInputContentItemClasses'] == [
        'WFImageContentItem'
    ]
    # Files: Finder's Quick Actions and the Services menu, files and folders.
    assert set(files['WFWorkflowTypes']) == {'ActionExtension', 'QuickActions'}
    assert set(files['WFQuickActionSurfaces']) == {'Finder', 'Services'}
    assert set(files['WFWorkflowInputContentItemClasses']) >= {
        'WFGenericFileContentItem',
        'WFFolderContentItem',
    }
    for wf in workflows.values():
        assert wf['WFWorkflowHasShortcutInputVariables'] is True


def test_quality_presets_shared_with_iphone(gen, wf, shortcuts):
    ios = ph.load_generator()
    assert wf.QUALITY_PRESETS == ios.QUALITY_PRESETS
    for actions in shortcuts.values():
        cards = next(
            ph.render(ph.params(a)['WFTextActionText'], {})
            for a in actions
            if ph.ident(a) == 'is.workflow.actions.gettext'
            and 'BEGIN:VCARD' in str(ph.params(a)['WFTextActionText'])
        )
        assert cards.count('END:VCARD') == len(wf.QUALITY_PRESETS)


def test_notes_show_version(gen, shortcuts):
    version = (ph.TOOL / 'VERSION').read_text().strip()
    assert gen.VERSION == version
    for name, actions in shortcuts.items():
        first = ph.params(actions[0])['WFCommentActionText']
        assert f'{name} {version}' in first
        assert 'Allow Running Scripts' in first

    for text in ph.shell_scripts(
        shortcuts[PHOTOS],
        {'Matches': '', 'Combined Text': '', 'Skipped Echo': ''},
    ):
        if 'VERSION=' in text:
            assert f"VERSION='{version}'" in text


def test_written_file_is_valid(gen, workflows, tmp_path, monkeypatch):
    monkeypatch.setattr(gen, 'OUT', tmp_path)
    monkeypatch.setattr(gen, 'DIST', tmp_path)
    for name, wf in workflows.items():
        gen.write(name, wf, sign=False)
        assert (tmp_path / f'{name}.unsigned.wflow').exists()


def test_iphone_shortcuts_unchanged_by_refactor():
    # build_shortcuts.py still exports what its tests and docs rely on.
    ios = ph.load_generator()
    for name in (
        'NAME_A',
        'NAME_B',
        'QUALITY_PRESETS',
        'DEFAULT_QUALITY',
        'VERSION',
        'CLEANUP',
        'Sample',
        'guessed_workflow',
        'build_compress',
        'build_import',
        'workflow',
        'write',
    ):
        assert hasattr(ios, name), name
