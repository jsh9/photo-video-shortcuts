"""
The generated Mac shortcuts (scripts/build_mac_shortcuts.py), checked without
importing them: their structure, surfaces, the Run Shell Script and Run
AppleScript actions, the quality presets, and the file names and lines they
share with photobatch. The script itself runs for real in test_mac_script.py.
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
    'Format': 'jxl',
    'Quality': '83',
    'Cores': 'all',
    'HDR': 'keep',
    'Combined Text': 'IMG_0001.HEIC',
    'Skipped Echo': '',
    'AppleScript Result': 'ID|2024-01-01 17:00:00|IMG_0001.HEIC',
    'Dates': '1|2024-01-01T17:00:00-05:00',
    'Meta': '1|gps|40.5,-73.25',
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
    # The Mac shortcuts run photobatch themselves and wait for it.
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
        '"$photobatch" --mac "${fmt[@]}" "${cores[@]}" "${hdr[@]}" -C "$WORK" jxl_job.txt'
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


def route_spans(shortcuts, name, routes):
    """
    Each route's actions as (start, batch): from after the previous route's
    batch script (or the start) to its own batch script (the Run Shell Script
    that converts).
    """
    actions = shortcuts[name]
    batches = [
        i
        for i, a in enumerate(actions)
        if ph.ident(a) == RUN_SHELL
        and 'jxl_job.txt' in str(ph.params(a)['Script'])
    ]
    assert len(batches) == routes
    return [
        (0 if k == 0 else batches[k - 1] + 1, batch)
        for k, batch in enumerate(batches)
    ]


def check_menu(actions, start, prompt, choices, var):
    """
    The Choose from Menu at ``start`` has ``prompt`` and ``choices`` (titles),
    and each case sets the variable ``var`` to the choice's value; returns the
    case indices (the menu's Choose from Menu actions with mode 1).
    """
    p = ph.params(actions[start])
    assert p['WFMenuPrompt'] == prompt
    assert p['WFMenuItems'] == [t for t, _ in choices]
    cases = menu_cases(actions, start)
    assert [ph.params(actions[i])['WFControlFlowMode'] for i in cases] == [
        1
    ] * len(choices) + [2]
    idents = [ph.ident(a) for a in actions]
    for i, (title, value) in zip(cases[:-1], choices, strict=True):
        assert ph.params(actions[i])['WFMenuItemTitle'] == title
        assert idents[i + 1 : i + 3] == [
            'is.workflow.actions.gettext',
            'is.workflow.actions.setvariable',
        ]
        assert (
            ph.render(ph.params(actions[i + 1])['WFTextActionText'], {})
            == value
        )
        assert ph.params(actions[i + 2])['WFVariableName'] == var

    return cases[:-1]


def test_format_menu_first_in_each_route_with_its_quality_list(
        gen, wf, shortcuts
):
    # The first question of each route: a Choose from Menu of the formats,
    # HEIC first. Each case sets the variable Format to the value the script
    # reads (FORMAT in common.zsh) and then shows that format's quality list
    # (a Choose from List of contact cards), whose number goes into Quality.
    assert wf.FORMATS == [
        (
            'HEIC: Apple’s own format; HDR shows exactly as the original',
            'heic',
        ),
        (
            'JPEG XL: HDR copies can show pink patches in bright skies (an Apple issue)',
            'jxl',
        ),
    ]
    for name, routes in ((PHOTOS, 2), (FILES, 1)):
        actions = shortcuts[name]
        for start, batch in route_spans(shortcuts, name, routes):
            menus = [
                i
                for i in range(start, batch)
                if ph.ident(actions[i]) == MENU
                and ph.params(actions[i])['WFControlFlowMode'] == 0
            ]
            cases = check_menu(
                actions, menus[0], wf.FORMAT_PROMPT, wf.FORMATS, 'Format'
            )
            for case, (_, value) in zip(cases, wf.FORMATS, strict=True):
                presets, default, prompt, _ = wf.QUALITY_LISTS[value]
                case_actions = actions[case + 3 : case + 10]
                kinds = [ph.ident(a).rsplit('.', 1)[1] for a in case_actions]
                assert kinds == [
                    'gettext',
                    'setitemname',
                    'contacts',
                    'choosefromlist',
                    'getitemname',
                    'match',
                    'setvariable',
                ], kinds
                cards = ph.render(
                    ph.params(case_actions[0])['WFTextActionText'], {}
                )
                assert cards.count('END:VCARD') == len(presets)
                assert f'N;CHARSET=utf-8:{default} (default)' in cards
                assert (
                    ph.params(case_actions[3])['WFChooseFromListActionPrompt']
                    == prompt
                )
                assert (
                    ph.params(case_actions[6])['WFVariableName'] == 'Quality'
                )


def check_menu_in_each_route(shortcuts, prompt, choices, var, position):
    """
    In each route of each shortcut, a Choose from Menu with ``prompt`` and
    ``choices`` (titles) sets the variable ``var`` to each choice's value, and
    sits at ``position`` (0: first after the format question, 1: next) among
    the menus between the format question (the Format menu with its quality
    lists) and the batch script.
    """
    for name, routes in ((PHOTOS, 2), (FILES, 1)):
        actions = shortcuts[name]
        for start, batch in route_spans(shortcuts, name, routes):
            # after the format question: past the last quality list
            quality = max(
                i
                for i in range(start, batch)
                if ph.ident(actions[i]) == 'is.workflow.actions.choosefromlist'
            )
            starts = [
                i
                for i in range(quality, batch)
                if ph.ident(actions[i]) == MENU
                and ph.params(actions[i])['WFControlFlowMode'] == 0
            ]
            check_menu(actions, starts[position], prompt, choices, var)


def test_cores_menu_after_the_quality_in_each_route(gen, shortcuts):
    # After the quality list, a Choose from Menu asks how to use the cores:
    # "All cores (fast)" first (the usual choice), then "One core". Each case
    # sets the variable Cores to the value the script reads, and the batch
    # script turns "one" into one photo at a time on one thread (photobatch
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
            if '"$photobatch"' in text:
                assert "CORES='one'" in text
                assert 'one) cores=(-j 1 -t 1);;' in text
                assert '*) cores=(-j 0);;' in text
                assert (
                    '"${cores[@]}" "${hdr[@]}" -C "$WORK" jxl_job.txt' in text
                )


def test_hdr_menu_after_the_cores_in_each_route(gen, shortcuts):
    # The third question: keep an HDR photo's HDR (the usual choice, first),
    # or drop it, which the script turns into photobatch --sdr: every photo is
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
            if '"$photobatch"' in text:
                assert "HDR='drop'" in text
                assert 'drop) hdr=(--sdr);;' in text
                assert '*) hdr=();;' in text


def test_photos_results_read_with_get_file_from_the_shortcuts_folder(
        gen, shortcuts
):
    # The results are jxl_done.txt's lines, "file|index|delete or keep|Name.jxl",
    # read from the work folder inside Shortcuts' iCloud Drive folder with Get
    # File (the one bridge from a script to Shortcuts on the Mac: AppleScript
    # file results come back empty, absolute paths are refused), as the iPhone
    # shortcut reads them, then Get Text from Input and Split Text, all inside
    # "If (File) has any value" (no file when nothing was converted). Not the
    # script's output, which Shortcuts types by its content: three or more
    # lines whose names each have a comma are a CSV file to it. Each line's
    # file is read with Get File too, renamed to Name.jxl and saved.
    actions = shortcuts[PHOTOS]
    gets = [a for a in actions if ph.ident(a) == GET_FILE]
    assert len(gets) == 2
    done, copy = (ph.params(g) for g in gets)
    for p in (done, copy):
        assert p['WFFileStorageService'] == 'iCloud Drive'
        assert p['WFShowFilePicker'] is False

    assert done['WFGetFilePath'] == f'{gen.WORK_NAME}/jxl_done.txt'
    assert done['WFFileErrorIfNotFound'] is False
    assert ph.render(
        copy['WFGetFilePath'], {'Item from List': 'jxl_out_1.jxl'}
    ) == (f'{gen.WORK_NAME}/jxl_out_1.jxl')
    idents = [ph.ident(a) for a in actions]
    i_done = idents.index(GET_FILE)
    get_text = actions[idents.index('is.workflow.actions.detect.text', i_done)]
    assert done['UUID'] in repr(ph.params(get_text)['WFInput'])
    split = actions[idents.index('is.workflow.actions.text.split', i_done)]
    assert ph.params(split)['WFTextSeparator'] == 'New Lines'
    assert ph.params(get_text)['UUID'] in repr(ph.params(split)['text'])
    for action, inside in ph.inside_if_on(actions, done['UUID']):
        if action in (get_text, split) or ph.ident(action) in (
            GET_FILE,
            'is.workflow.actions.savetocameraroll',
        ):
            assert inside is (action is not gets[0]), ph.ident(action)
    # no action reads the picker script's output
    batch = next(
        a
        for a in actions
        if ph.ident(a) == 'is.workflow.actions.runshellscript'
        and 'for f in "$@"; do' in repr(ph.params(a)['Script'])
    )
    assert not any(
        ph.params(batch)['UUID'] in repr(ph.params(a))
        for a in actions
        if a is not batch
    )
    # the picker route (the Otherwise branch of "If Selection") runs no
    # AppleScript but the probe before the branch
    for action, inside in ph.inside_if_on(actions, "'Selection'"):
        if ph.ident(action) == RUN_APPLESCRIPT and not inside:
            assert 'is Photos in front' in ph.params(action)['Script']

    i_copy = idents.index(GET_FILE, i_done + 1)
    assert (
        i_done
        < i_copy
        < idents.index('is.workflow.actions.setitemname', i_copy)
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
    # Each result line carries photobatch's "delete" or "keep" ("keep": the
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
    assert gen.ORIGINALS_ALBUM == 'Compressed originals'
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
            'Format': 'jxl',
            'Quality': '72',
            'Cores': 'all',
            'HDR': 'keep',
            'Combined Text': '/a/b.heic\n\n/c',
            'Skipped Echo': '',
        },
    )[0]
    assert "PATHS=$(cat <<'JXL_LINES'\n/a/b.heic\n\n/c\nJXL_LINES\n)" in text
    # a folder's photos: HEIF, JPEG, PNG and JPEG XL (since 0.10.0)
    assert '"$f"/*.(#i)(heic|heif|hif|jpg|jpeg|png|jxl)(N.)' in text


def test_selection_pairs_live_photo_videos_with_jpeg_xl_too(shortcuts):
    # A video with a photo of the same name is a Live Photo's: skipped as one,
    # not counted as a video, whatever the photo's format.
    texts = ph.shell_scripts(shortcuts[PHOTOS], VALUES)
    selection = [t for t in texts if 'in/*(.N)' in t]
    assert len(selection) == 1
    assert '(#i)(heic|heif|hif|jpg|jpeg|png|jxl|dng)(.N)' in selection[0]


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
    assert [rf for rf, _ in wf.HEIC_PRESETS] == [
        22,
        24,
        26,
        28,
        29,
        30,
        31,
        32,
        34,
        36,
        38,
        40,
    ]
    assert wf.DEFAULT_RF == 26
    for name, routes in ((PHOTOS, 2), (FILES, 1)):
        counts = [
            ph.render(ph.params(a)['WFTextActionText'], {}).count('END:VCARD')
            for a in shortcuts[name]
            if ph.ident(a) == 'is.workflow.actions.gettext'
            and 'BEGIN:VCARD' in str(ph.params(a)['WFTextActionText'])
        ]
        # per route, one list per format: HEIC first, then JPEG XL
        assert (
            counts == [len(wf.HEIC_PRESETS), len(wf.QUALITY_PRESETS)] * routes
        )


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
    script = gen.applescript_text('import')
    assert gen.ORIGINALS_ALBUM in script
    # an original already in the old review album: its copy must not join it
    assert gen.OLD_ORIGINALS_ALBUM in script
    # the copies' keywords, set in Photos after the import (copyKeywords):
    # "compr" (wfkit's, shared with Compress Videos), then the format and
    # quality common.zsh's KEYWORDS gives each result line, which the import
    # also knows to drop from the keywords of an original that is a copy
    assert gen.COPY_KEYWORD == 'compr' == gen.wf.COPY_KEYWORD
    assert gen.FORMAT_KEYWORDS == {'heic': 'rf=', 'jxl': 'q='}
    assert 'repeat with f in {"heic", "jxl"}' in script
    assert 'repeat with pfx in {"rf=", "q="}' in script
    assert 'set end of kws to "compr"' in script
    assert 'set keywords of copyItem to wantKeywords' in script
    assert (
        'heic) FORMAT_NAME=HEIC; KEYWORDS="heic,rf=$QUALITY";;' in selection[0]
    )
    assert (
        '*) FORMAT_NAME=\'JPEG XL\'; KEYWORDS="jxl,q=$QUALITY";;'
        in selection[0]
    )
    assert '"${dest:t}" "$KEYWORDS"' in selection[0]
    # a copy whose original is unknown (two selected photos with one name)
    # gets them too, with the keywords Photos read from its file
    assert (
        'set end of orphans to {found, item i of ownKeywords, jxlName}'
        in script
    )
    assert (
        'set keywords of (item 1 of o) to my copyKeywords(had, item 2 of o)'
        in script
    )


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


def run_handlers(gen, name, start, call):
    """
    Runs the handlers of lib/mac/<name>.applescript from the comment line
    ``start`` on (those that don't talk to Photos) with osascript, then
    ``call``; returns its result as text.
    """
    import shutil
    import subprocess

    ph.need(shutil.which('osascript'), 'osascript is needed')
    text = gen.applescript_text(name)
    script = text[text.index(start) :] + '\n' + call
    result = subprocess.run(
        ['osascript', '-'], input=script, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.rstrip('\n')


def test_export_lines_of_what_else_photos_has(gen):
    # export.applescript's lines for photobatch, from records like Photos'
    # "properties of" (fields by code): the location only, coordinates to 6
    # decimals without a real's text (which follows the Mac's number format),
    # an altitude of 0 left out, empty for none. The title, caption and
    # keywords stay in Photos' library: no lines for them.
    records = (
        '{«class ID  »:"A", «class IPlo»:{40.758441666667, -73.829766666667},'
        ' «class alti»:11.730902867811, «class pnam»:"T|x%" & tab & "y",'
        ' «class IPde»:"Line 1" & linefeed & "Line 2" & return,'
        ' «class IPkw»:{"a,b", "c"}}',
        '{«class ID  »:"B", «class IPlo»:{missing value, missing value},'
        ' «class alti»:missing value, «class pnam»:missing value,'
        ' «class IPde»:missing value, «class IPkw»:missing value}',
        '{«class ID  »:"C", «class IPlo»:{-0.00005, 25.7708431},'
        ' «class alti»:0.0, «class pnam»:"", «class IPde»:"",'
        ' «class IPkw»:{}}',
        # an altitude of 100 km or more (a corrupt GPSAltitude) is left out:
        # it would overflow decimalText's whole number ("6000000.0.0")
        '{«class ID  »:"D", «class IPlo»:{40.758441666667, -73.829766666667},'
        ' «class alti»:6.0E+6, «class pnam»:missing value,'
        ' «class IPde»:missing value, «class IPkw»:missing value}',
    )
    call = 'return ' + ' & '.join(
        f'metaLines("{i}", {r})' for i, r in zip('ABCD', records)
    )
    lines = run_handlers(gen, 'export', '-- "2024-01-01 17:00:00"', call)
    assert lines.split('\n') == [
        'A\tgps\t40.758442,-73.829767,11.73',
        'B\tgps\t',
        'C\tgps\t-0.000050,25.770843',
        'D\tgps\t40.758442,-73.829767',
    ]


def test_export_gives_no_title_caption_or_keywords(gen):
    # They stay in Photos' library, never in the copy's file: the export
    # doesn't read them for photobatch (Photos' codes: pnam, IPde, IPkw), and
    # the import sets them on the copy in Photos.
    export = gen.applescript_text('export')
    for code in ('«class pnam»', '«class IPde»', '«class IPkw»'):
        assert code not in export

    importer = gen.applescript_text('import')
    for field in ('name', 'description', 'keywords'):
        assert f'set {field} of copyItem to ' in importer


def test_export_and_import_guard_each_item_and_field(gen):
    # One item whose record can't be read doesn't fail the export (no lines
    # for it: the file's values stay); after the import, each field of a copy
    # is set in a try of its own, a failure logged as a "!" line.
    export = gen.applescript_text('export')
    assert 'try\n\t\t\t\t\t\tset metaText to metaText & my metaLines' in export
    importer = gen.applescript_text('import')
    assert importer.count('my notSet(got, ') == 6
    assert importer.count('on error e number errNum') >= 7


def test_import_compares_what_photos_has(gen):
    # import.applescript's comparisons of an original's fields with its
    # copy's: locations within 0.00001 degree, missing value and "" both none,
    # case counts, keywords in any order.
    calls = [
        'sameLocation({40.7584416, -73.8297666}, {40.758445, -73.829766})',
        'sameLocation({40.75, -73.82}, {40.76, -73.82})',
        'sameLocation({missing value, missing value}, {missing value, missing value})',
        'sameLocation({missing value, missing value}, {1.0, 2.0})',
        'sameText(missing value, "")',
        'sameText("a", "A")',
        'sameKeywords(missing value, {})',
        'sameKeywords({"a", "b"}, {"b", "a"})',
        'sameKeywords({"a"}, {"A"})',
        'sameKeywords({"a", "b"}, {"a"})',
    ]
    call = 'return {' + ', '.join(f'my {c}' for c in calls) + '}'
    got = run_handlers(
        gen, 'import', '-- Locations as Photos gives them', call
    )
    assert got.split(', ') == [
        'true',
        'false',
        'true',
        'false',
        'true',
        'false',
        'true',
        'true',
        'false',
        'false',
    ]


def test_import_reads_its_plan_from_text_or_a_file(gen, tmp_path):
    # Shortcuts passes the selection script's output to import.applescript as
    # a file ("stdout") when it takes it for CSV: three or more lines with the
    # same number of commas each, as 0.9.0's keywords ("jxl,q=63") give every
    # line. The plan
    # is then read from the file (UTF-8), whether it comes as an alias or a
    # file reference; an empty file is no lines, and text stays text. The
    # run reads every item of its input, and a plan it can't read (any
    # other error of the read) is a "!" line.
    plan = ''.join(
        f'/out/Café ({i}).jxl||delete|Café ({i}).jxl|jxl,q=63\n'
        for i in (1, 2, 3)
    )
    (tmp_path / 'stdout').write_text(plan, encoding='utf-8')
    (tmp_path / 'empty').write_bytes(b'')
    call = '\n'.join([
        f'set p to POSIX file "{tmp_path / "stdout"}"',
        f'set e to POSIX file "{tmp_path / "empty"}"',
        'set AppleScript\'s text item delimiters to "#"',
        'return {my planText(p as alias), my planText(p),'
        ' my planText(e as alias), my planText("a|b")} as text',
    ])
    got = run_handlers(gen, 'import', "-- The plan's text from one item", call)
    assert got == f'{plan}#{plan}##a|b'
    # any other error of the read is left to the run handler: a file
    # Shortcuts removed before the script read it (a stale alias; a file
    # reference to a missing file fails the same way) is -1700, "Can't make
    # alias ... into type file"
    (tmp_path / 'stale').write_text(plan, encoding='utf-8')
    call = '\n'.join([
        f'set s to (POSIX file "{tmp_path / "stale"}") as alias',
        'do shell script "rm " & quoted form of (POSIX path of s)',
        'try',
        '\tmy planText(s)',
        '\treturn "no error"',
        'on error number n',
        '\treturn n',
        'end try',
    ])
    got = run_handlers(gen, 'import', "-- The plan's text from one item", call)
    assert got == '-1700'

    importer = gen.applescript_text('import')
    assert 'my planText(item i of input)' in importer
    assert 'item 1 of input' not in importer
    assert '"! could not read the result lines ("' in importer


def test_import_gives_each_copy_its_keywords(gen):
    # import.applescript's keywords for a copy, set in Photos only: its
    # original's, then "compr" and its own from its result line (its format
    # and quality). A copy of a copy (its original has "compr") keeps none of
    # its original's format and quality keywords, nor a second "compr"; case
    # is ignored, as AppleScript compares text. An original that isn't a copy
    # keeps every keyword, a "HEIC" or "q=..." of the user's own too. A line
    # without keywords (Compress Videos'): "compr" only.
    cases = [
        ('missing value', 'jxl,q=83'),
        ('{"NYC", "skyline"}', 'heic,rf=26'),
        ('{"compr", "heic", "rf=26", "a,b"}', 'jxl,q=83'),
        ('{"Compr", "JXL", "Q=90"}', 'jxl,q=5'),
        ('{"HEIC", "q=high", "rf=26"}', 'jxl,q=83'),
        ('{"x"}', ''),
    ]
    call = '\n'.join([
        'set answers to {}',
        *(
            'set AppleScript\'s text item delimiters to "|"\n'
            f'set end of answers to (my copyKeywords({v}, "{own}")) as text'
            for v, own in cases
        ),
        "set AppleScript's text item delimiters to linefeed",
        'return answers as text',
    ])
    got = run_handlers(
        gen, 'import', '-- Locations as Photos gives them', call
    )
    assert got.split('\n') == [
        'compr|jxl|q=83',
        'NYC|skyline|compr|heic|rf=26',
        'a,b|compr|jxl|q=83',
        'compr|jxl|q=5',
        'HEIC|q=high|rf=26|compr|jxl|q=83',
        'x|compr',
    ]


def test_photos_dates_in_photos_go_to_photobatch(gen, shortcuts):
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
    assert 'set dateText to my wallTime(«class idat» of p)' in (
        gen.applescript_text('export')
    )
    assert not ph.check_photo_dates(shortcuts[FILES])


def test_photos_locations_in_photos_go_to_photobatch(gen, shortcuts):
    # The picker route reads each photo's location in Photos
    # (ph.check_photo_locations) before its batch script gets the photos'
    # files, and the script gets Meta; the selection route has the location
    # from Photos' AppleScript (export.applescript's "id<tab>gps<tab>value"
    # lines), and the Finder shortcut none.
    actions = shortcuts[PHOTOS]
    (read,) = ph.check_photo_locations(actions)
    batches = [
        i
        for i, a in enumerate(actions)
        if ph.ident(a) == RUN_SHELL and 'Meta' in repr(ph.params(a)['Script'])
    ]
    assert len(batches) == 1 and read < batches[0]
    script = ph.render(ph.params(actions[batches[0]])['Script'], VALUES)
    assert '1|gps|40.5,-73.25\nJXL_META' in script
    assert 'my metaLines(itemId, p)' in gen.applescript_text('export')
    assert not ph.check_photo_locations(shortcuts[FILES])
