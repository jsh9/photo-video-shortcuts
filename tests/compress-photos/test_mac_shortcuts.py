"""
The generated Mac shortcuts (scripts/build_mac_shortcuts.py), checked without
importing them: their structure, surfaces, the Run Shell Script and Run
AppleScript actions, the quality presets, and the file names and lines they
share with jxlbatch. The script itself runs for real in test_mac_script.py.
"""

import pathlib

import photo_helpers as ph
import pytest

PHOTOS = 'Compress Photos (macOS)'
FILES = 'Compress Photo Files (macOS)'
RUN_SHELL = 'is.workflow.actions.runshellscript'
RUN_APPLESCRIPT = 'is.workflow.actions.runapplescript'
GET_FILE = 'is.workflow.actions.documentpicker.open'
MENU = 'is.workflow.actions.choosefrommenu'
# values for every variable the shortcuts' texts can mention
VALUES = {
    'Matches': '83',
    'Cores': 'all',
    'HDR': 'keep',
    'Combined Text': 'IMG_0001.HEIC',
    'Skipped Echo': '',
    'AppleScript Result': 'ID|2024-01-01 17:00:00|IMG_0001.HEIC',
    'Dates': '1|2024-01-01T17:00:00-05:00',
}


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
        assert p['InputMode'] in ('as arguments', 'to stdin')

    # The batch script gets the photos (or files) as its input, as
    # arguments; the finish scripts get the outcome on stdin; the small
    # follow-up scripts (log, prepare) have no input.
    batch = [
        a
        for a in scripts
        if 'Input' in ph.params(a)
        and ph.params(a)['InputMode'] == 'as arguments'
    ]
    assert len(batch) == 1
    text = ph.render(ph.params(batch[0])['Script'], VALUES)
    assert "QUALITY='83'" in text
    assert "CORES='all'" in text
    assert 'for f in "$@"; do' in text
    assert (
        '"$jxlbatch" --mac -q "$QUALITY" -e 7 "${cores[@]}" "${hdr[@]}" -C "$WORK" jxl_job.txt'
        in text
    )
    assert 'open -a Terminal "$cmd"' in text
    assert (
        'echo \\$\\$ > ' in text
    )  # the window records its pid for finish.zsh
    assert 'jxl_in_$' in text and 'jxl_done.txt' in text
    for a in scripts:
        if ph.params(a).get('InputMode') == 'to stdin':
            script = ph.params(a)['Script']
            assert 'Done. You can close this window.' in script
            assert 'pkill' not in script  # ends its own window, by pid


def menu_cases(actions, start):
    """
    The case and end markers of the Choose from Menu starting at ``start``.
    """
    group = ph.params(actions[start])['GroupingIdentifier']
    return [
        i
        for i in range(start + 1, len(actions))
        if ph.ident(actions[i]) == MENU
        and ph.params(actions[i])['GroupingIdentifier'] == group
    ]


def check_menu_in_each_route(shortcuts, prompt, choices, var, position):
    """
    In each route of each shortcut, a Choose from Menu with ``prompt`` and
    ``choices`` (titles) sets the variable ``var`` to each choice's value, and
    sits at ``position`` (0: first after the quality list, 1: next) among the
    menus between the quality list and the batch script.
    """
    for name, routes in ((PHOTOS, 2), (FILES, 1)):
        actions = shortcuts[name]
        idents = [ph.ident(a) for a in actions]
        qualities = [
            i
            for i, x in enumerate(idents)
            if x == 'is.workflow.actions.choosefromlist'
        ]
        batches = [
            i
            for i, a in enumerate(actions)
            if ph.ident(a) == RUN_SHELL
            and 'jxl_job.txt' in str(ph.params(a)['Script'])
        ]
        assert len(qualities) == len(batches) == routes
        for quality, batch in zip(qualities, batches, strict=True):
            starts = [
                i
                for i in range(quality, batch)
                if ph.ident(actions[i]) == MENU
                and ph.params(actions[i])['WFControlFlowMode'] == 0
            ]
            start = starts[position]
            p = ph.params(actions[start])
            assert p['WFMenuPrompt'] == prompt
            assert p['WFMenuItems'] == [t for t, _ in choices]
            cases = menu_cases(actions, start)
            assert [
                ph.params(actions[i])['WFControlFlowMode'] for i in cases
            ] == [1] * len(choices) + [2]
            for i, (title, value) in zip(cases[:-1], choices, strict=True):
                assert ph.params(actions[i])['WFMenuItemTitle'] == title
                assert idents[i + 1 : i + 3] == [
                    'is.workflow.actions.gettext',
                    'is.workflow.actions.setvariable',
                ]
                assert (
                    ph.render(
                        ph.params(actions[i + 1])['WFTextActionText'], {}
                    )
                    == value
                )
                assert ph.params(actions[i + 2])['WFVariableName'] == var


def test_cores_menu_after_the_quality_in_each_route(gen, shortcuts):
    # After the quality list, a Choose from Menu asks how to use the cores:
    # "All cores (fast)" first (the usual choice), then "One core". Each case
    # sets the variable Cores to the value the script reads, and the batch
    # script turns "one" into one photo at a time on one thread (jxlbatch
    # -j 1 -t 1) and anything else into several photos at a time with all the
    # cores (-j 0).
    assert gen.CORES_CHOICES == [
        ('All cores (fast)', 'all'),
        ('One core (keeps the Mac responsive)', 'one'),
    ]
    check_menu_in_each_route(
        shortcuts, gen.CORES_PROMPT, gen.CORES_CHOICES, 'Cores', 0
    )
    for name in (PHOTOS, FILES):
        for text in ph.shell_scripts(
            shortcuts[name], {**VALUES, 'Cores': 'one'}
        ):
            if '"$jxlbatch"' in text:
                assert "CORES='one'" in text
                assert 'one) cores=(-j 1 -t 1);;' in text
                assert '*) cores=(-j 0);;' in text
                assert (
                    '"${cores[@]}" "${hdr[@]}" -C "$WORK" jxl_job.txt' in text
                )


def test_hdr_menu_after_the_cores_in_each_route(gen, shortcuts):
    # The third question: keep an HDR photo's HDR (the usual choice, first),
    # or drop it, which the script turns into jxlbatch --sdr: every photo is
    # then an ordinary SDR JPEG XL.
    assert gen.HDR_CHOICES == [
        ('Keep HDR', 'keep'),
        ('Drop HDR (smaller; shows right in any viewer)', 'drop'),
    ]
    check_menu_in_each_route(
        shortcuts, gen.HDR_PROMPT, gen.HDR_CHOICES, 'HDR', 1
    )
    for name in (PHOTOS, FILES):
        for text in ph.shell_scripts(
            shortcuts[name], {**VALUES, 'HDR': 'drop'}
        ):
            if '"$jxlbatch"' in text:
                assert "HDR='drop'" in text
                assert 'drop) hdr=(--sdr);;' in text
                assert '*) hdr=();;' in text


def test_photos_results_read_with_get_file_from_the_shortcuts_folder(
        gen, shortcuts
):
    # Each output line is "file|index|delete or keep|Name.jxl": the file is
    # read from the work folder inside Shortcuts' iCloud Drive folder with Get
    # File (the one bridge from a script to Shortcuts on the Mac: AppleScript
    # file results come back empty, absolute paths are refused), renamed to
    # Name.jxl and saved.
    actions = shortcuts[PHOTOS]
    gets = [a for a in actions if ph.ident(a) == GET_FILE]
    assert len(gets) == 1
    p = ph.params(gets[0])
    assert p['WFFileStorageService'] == 'iCloud Drive'
    assert p['WFShowFilePicker'] is False
    assert ph.render(
        p['WFGetFilePath'], {'Item from List': 'jxl_out_1.jxl'}
    ) == (f'{gen.WORK_NAME}/jxl_out_1.jxl')
    # the picker route (the Otherwise branch of "If Selection") runs no
    # AppleScript but the probe before the branch
    for action, inside in ph.inside_if_on(actions, "'Selection'"):
        if ph.ident(action) == RUN_APPLESCRIPT and not inside:
            assert 'is Photos in front' in ph.params(action)['Script']

    idents = [ph.ident(a) for a in actions]
    assert (
        idents.index(GET_FILE)
        < idents.index(
            'is.workflow.actions.setitemname', idents.index(GET_FILE)
        )
        < idents.index('is.workflow.actions.savetocameraroll')
    )
    # the script's work folder is that folder, and the follow-up scripts use it
    picker_texts = [
        text
        for text in ph.shell_scripts(actions, VALUES)
        if '/Pictures/.' not in text and not text.startswith('cat ')
    ]
    assert len(picker_texts) == 2  # the batch and the finish script
    for text in picker_texts:
        assert 'iCloud~is~workflow~my~workflows/Documents' in text
        assert gen.WORK_NAME in text


def test_every_imported_original_is_collected(gen, shortcuts):
    # Each result line carries jxlbatch's "delete" or "keep" ("keep": the
    # JPEG XL lacks the original's HDR, which the log says too). Nothing acts
    # on it any more: the selection route's import.applescript collects every
    # imported file's original in ORIGINALS_ALBUM, and the shortcut's own
    # actions never match the flag.
    actions = shortcuts[PHOTOS]
    assert not [
        a
        for a in actions
        if ph.ident(a) == 'is.workflow.actions.text.match'
        and ph.params(a).get('WFMatchTextPattern') == '^delete$'
    ]
    script = gen.applescript_text('import')
    assert 'set end of toCollect to origId' in script
    assert 'is "delete"' not in script
    assert gen.ORIGINALS_ALBUM == 'Compressed to JXL'
    assert gen.ORIGINALS_ALBUM in script


def album_saves(actions, album):
    """
    The Save to Photo Album actions whose album is a text holding ``album``.
    """
    texts = {
        ph.params(a)['UUID']
        for a in actions
        if ph.ident(a) == 'is.workflow.actions.gettext'
        and ph.params(a)['WFTextActionText']['Value'] == {'string': album}
    }
    return [
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


def test_picker_route_collects_the_originals_without_deleting(gen, shortcuts):
    # Delete Photos needs a prompt the Shortcuts app often can't show on
    # macOS 26, so nothing is deleted. The picker route collects each saved
    # copy's original in ORIGINALS_ALBUM by the item itself (Save to Photo
    # Album adds a library photo to an album without a copy), unless the
    # photo's albums already list it; the selection route collects by id
    # (import.applescript).
    actions = shortcuts[PHOTOS]
    assert not [
        a for a in actions if ph.ident(a) == 'is.workflow.actions.deletephotos'
    ]
    saves = album_saves(actions, gen.ORIGINALS_ALBUM)
    assert len(saves) == 1
    pattern = f'(^|\\n){gen.ORIGINALS_ALBUM}($|\\n)'
    checks = [
        i
        for i, a in enumerate(actions)
        if ph.ident(a) == 'is.workflow.actions.text.match'
        and ph.params(a).get('WFMatchTextPattern') == pattern
    ]
    assert len(checks) == 1
    assert checks[0] < saves[0]
    # in the picker route (the Otherwise branch of "If Selection"), after the
    # copy was saved
    inside = dict(
        (id(action), inside)
        for action, inside in ph.inside_if_on(actions, "'Selection'")
    )
    assert not inside[id(actions[saves[0]])]
    copies = [
        i
        for i, a in enumerate(actions)
        if ph.ident(a) == 'is.workflow.actions.savetocameraroll'
        and i not in saves
    ]
    assert copies and copies[0] < saves[0]


def test_probe_error_is_shown_before_the_picker(gen, shortcuts):
    # "ERROR: ..." from the probe (for example, Shortcuts may not control
    # Photos) is shown in a notification; the probe never launches Photos.
    actions = shortcuts[PHOTOS]
    probe = gen.applescript_text('probe')
    assert 'if application "Photos" is running then' in probe
    errors = [
        a
        for a in actions
        if ph.ident(a) == 'is.workflow.actions.text.match'
        and ph.params(a).get('WFMatchTextPattern') == '^ERROR'
    ]
    assert len(errors) == 1
    shown = [
        inside
        for action, inside in ph.inside_if_on(
            actions, ph.params(errors[0])['UUID']
        )
        if ph.ident(action) == 'is.workflow.actions.notification'
        and "'AppleScript Result'" in repr(ph.params(action))
    ]
    assert shown == [True]
    for name in ('export', 'import'):
        assert 'with timeout of 3600 seconds' in gen.applescript_text(name)


def test_photos_log_shown_only_with_warnings(gen, shortcuts):
    # In each route, Quick Look runs inside "If (log matches WARNINGS) has
    # any value", and before the delete prompt.
    actions = shortcuts[PHOTOS]
    warns = [
        ph.params(a)['UUID']
        for a in actions
        if ph.ident(a) == 'is.workflow.actions.text.match'
        and ph.params(a).get('WFMatchTextPattern') == gen.WARNINGS
    ]
    assert len(warns) == 2  # the selection route and the picker route
    idents = [ph.ident(a) for a in actions]
    looks = [
        i
        for i, a in enumerate(actions)
        if ph.ident(a) == 'is.workflow.actions.previewdocument'
    ]
    assert len(looks) == 2
    for warn, look in zip(warns, looks, strict=True):
        flags = [inside for _, inside in ph.inside_if_on(actions, warn)]
        assert flags[look]

    del idents


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
            'Cores': 'all',
            'HDR': 'keep',
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

    for text in ph.shell_scripts(shortcuts[PHOTOS], VALUES):
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


def test_photos_nothing_follows_a_save_that_produced_nothing(shortcuts):
    # Set Name and Save to Photo Album output nothing when Run AppleScript
    # gave no file (seen on a Mac: the original was then deleted with no
    # copy saved). So the album additions (the copy's, and the original's
    # collection in ORIGINALS_ALBUM) and the saved count all sit inside "If
    # (Saved Photo Media) has any value".
    actions = shortcuts[PHOTOS]
    saves = [
        ph.params(a)['UUID']
        for a in actions
        if ph.ident(a) == 'is.workflow.actions.savetocameraroll'
        and 'WFCameraRollSelectedGroup' not in ph.params(a)
    ]
    assert len(saves) == 1
    guarded = {'Saved Photos': 0, 'albums': 0}
    for action, inside in ph.inside_if_on(actions, saves[0]):
        p = ph.params(action)
        if ph.ident(action) == 'is.workflow.actions.appendvariable' and (
            p['WFVariableName'] == 'Saved Photos'
        ):
            assert inside, p['WFVariableName']
            guarded[p['WFVariableName']] += 1
        elif ph.ident(action) == 'is.workflow.actions.savetocameraroll' and (
            'WFCameraRollSelectedGroup' in p
        ):
            assert inside, 'album addition outside the saved check'
            guarded['albums'] += 1

    assert guarded == {'Saved Photos': 1, 'albums': 2}
    # The count in the notification is of the photos actually saved.
    counts = [
        a
        for a in actions
        if ph.ident(a) == 'is.workflow.actions.count'
        and "'Saved Photos'" in repr(ph.params(a)['Input'])
    ]
    assert len(counts) == 1


def test_photos_selection_route_through_applescript(gen, shortcuts):
    # Started while Photos is in front with photos selected, the shortcut
    # converts that selection: a probe (Run AppleScript) decides, Photos
    # exports the originals (export.applescript, input: the work folder),
    # the script converts them, and Photos imports the results
    # (import.applescript, input: the script's output lines).
    actions = shortcuts[PHOTOS]
    scripts = [a for a in actions if ph.ident(a) == RUN_APPLESCRIPT]
    assert [ph.params(a)['Script'][:40] for a in scripts] == [
        gen.applescript_text(n)[:40] for n in ('probe', 'export', 'import')
    ]
    # Plain text only: a Shortcuts variable in the script text keeps a Run
    # AppleScript from compiling (seen on macOS 26); values go in as input.
    for a in scripts:
        assert isinstance(ph.params(a)['Script'], str)

    probe, export, imp = scripts
    assert 'Input' not in ph.params(probe)
    assert 'Input' in ph.params(export) and 'Input' in ph.params(imp)
    # the export's input is the prepare script's output (the work folder),
    # the import's input the selection script's output (the plan lines)
    ids = {ph.params(a)['UUID']: a for a in actions if 'UUID' in ph.params(a)}
    for a, marker in ((export, 'mkdir -p "$W/in"'), (imp, 'in/*(.N)')):
        ref = next(ph.references(ph.params(a)['Input']))
        source = ph.params(ids[ref['OutputUUID']])['Script']
        assert marker in ph.render(source, VALUES)

    # the probe's SELECTION answer selects the route
    matches = [
        a
        for a in actions
        if ph.ident(a) == 'is.workflow.actions.text.match'
        and ph.params(a).get('WFMatchTextPattern') == '^SELECTION'
    ]
    assert len(matches) == 1
    # the selection route's scripts work in ~/Pictures (Photos' sandbox
    # reaches it), the picker route's in the iCloud Drive folder
    texts = ph.shell_scripts(actions, VALUES)
    selection = [t for t in texts if 'in/*(.N)' in t]
    assert len(selection) == 1
    assert '"$HOME/Pictures/.compress-photos-macos"' in selection[0]
    assert 'rm -rf "$WORK"' not in selection[0]  # Photos exported into it
    assert gen.ORIGINALS_ALBUM in gen.applescript_text('import')


def test_photos_selection_route_notifies_without_a_picker(shortcuts):
    # In the selection branch there is no Select Photos and no Delete Photos
    # (a script can't delete; the originals are collected in an album).
    actions = shortcuts[PHOTOS]
    probe_uuid = next(
        ph.params(a)['UUID']
        for a in actions
        if ph.ident(a) == 'is.workflow.actions.text.match'
        and ph.params(a).get('WFMatchTextPattern') == '^SELECTION'
    )
    pickers = [
        inside
        for action, inside in ph.inside_if_on(actions, probe_uuid)
        if ph.ident(action) == 'is.workflow.actions.selectphoto'
    ]
    assert pickers == [False]  # the picker is in the Otherwise branch
    for action, inside in ph.inside_if_on(actions, "'Selection'"):
        if ph.ident(action) in (
            'is.workflow.actions.deletephotos',
            'is.workflow.actions.selectphoto',
            'is.workflow.actions.savetocameraroll',
            GET_FILE,
        ):
            assert not inside, ph.ident(action)


def test_applescripts_compile(gen):
    # osacompile reads Photos' dictionary without launching it.
    import shutil
    import subprocess
    import tempfile

    ph.need(shutil.which('osacompile'), 'osacompile is needed')
    with tempfile.TemporaryDirectory() as folder:
        for name in ('probe', 'export', 'import'):
            src = pathlib.Path(folder) / f'{name}.applescript'
            src.write_text(gen.applescript_text(name))
            result = subprocess.run(
                ['osacompile', '-o', str(src.with_suffix('.scpt')), str(src)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert result.returncode == 0, (name, result.stderr)


def test_photos_dates_in_photos_go_to_jxlbatch(gen, shortcuts):
    # The picker route reads each photo's date in Photos (Date Taken) in the
    # repeat that collects the names (ph.check_photo_dates), and its batch
    # script gets Dates; the selection route has them from Photos' AppleScript
    # (export.applescript: "id|date|filename"), and the Finder shortcut, whose
    # files aren't in Photos, none.
    actions = shortcuts[PHOTOS]
    (format_at,) = ph.check_photo_dates(actions)
    batches = [
        i
        for i, a in enumerate(actions)
        if ph.ident(a) == RUN_SHELL and 'Dates' in repr(ph.params(a)['Script'])
    ]
    assert len(batches) == 1 and format_at < batches[0]
    script = ph.render(ph.params(actions[batches[0]])['Script'], VALUES)
    assert 'for f in "$@"; do' in script  # the picker route's
    assert '1|2024-01-01T17:00:00-05:00\nJXL_DATES' in script
    assert 'set dateText to my wallTime(date of m)' in gen.applescript_text(
        'export'
    )
    assert not ph.check_photo_dates(shortcuts[FILES])
