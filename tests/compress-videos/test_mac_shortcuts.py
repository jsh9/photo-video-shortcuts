"""
The generated Mac shortcut (scripts/build_mac_shortcuts.py), checked without
importing it: its structure and surfaces, the Photos selection as its only
route, the six questions and "Same as last time", the Run Shell Script and Run
AppleScript actions, and the notifications. The script itself runs for real in
test_mac_script.py.
"""

import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest
import video_helpers as vh

NAME = 'Compress Videos (macOS)'
RUN_SHELL = 'is.workflow.actions.runshellscript'
RUN_APPLESCRIPT = 'is.workflow.actions.runapplescript'
MENU = 'is.workflow.actions.choosefrommenu'
LIST = 'is.workflow.actions.choosefromlist'
MATCH = 'is.workflow.actions.text.match'
NOTIFICATION = 'is.workflow.actions.notification'
# values for every variable the shortcut's texts can mention
VALUES = {
    'Codec': 'h265',
    'Preset': 'medium',
    'Tune': 'none',
    'RF': '24',
    'Size': '2K',
    'Audio': '160',
    'Reuse': '',
    'AppleScript Result': 'ID|IMG_0001.MOV',
    'Shell Script Result': 'H.265 · preset medium',
    'Matches': '3',
}


def of(actions, kind):
    return [a for a in actions if vh.ident(a) == kind]


def matches(actions, pattern):
    return [
        a
        for a in of(actions, MATCH)
        if vh.params(a).get('WFMatchTextPattern') == pattern
    ]


def test_name_and_note(gen, actions, version):
    assert gen.NAME == NAME
    assert gen.VERSION == version
    note = vh.params(actions[0])['WFCommentActionText']
    assert note.startswith(f'{NAME} {version}. ')
    for text in (
        'Allow Running Scripts',
        '~/.local/bin',
        gen.ORIGINALS_ALBUM,
        gen.HELP_URL,
        'AV1 plays only',
    ):
        assert text in note


def test_blocks_balanced(actions):
    list(vh.walk(actions))


def test_outputs_used_after_they_exist(actions):
    seen = set()
    for action in actions:
        for ref in vh.references(vh.params(action)):
            if ref.get('Type') == 'ActionOutput':
                assert ref['OutputUUID'] in seen, ref

        seen.add(vh.params(action).get('UUID'))


def test_photos_selection_is_the_only_route(gen, actions):
    # No picker (Shortcuts re-renders picked videos, and failed on some), no
    # Shortcut Input, no Get File or Save to Photo Album (the import script
    # does it), no Delete Photos (a script can't; originals are collected).
    for action in actions:
        assert vh.ident(action) not in (
            'is.workflow.actions.selectphoto',
            'is.workflow.actions.documentpicker.open',
            'is.workflow.actions.savetocameraroll',
            'is.workflow.actions.deletephotos',
            'is.workflow.actions.waittoreturn',
        )
        assert not vh.ident(action).startswith('AsheKube.app.a-Shell.')
        assert "'ExtensionInput'" not in repr(vh.params(action))


def branches(actions, uuid):
    """
    The actions of the Then and Otherwise branches of the If whose condition is
    the output ``uuid``.
    """
    start = next(
        i
        for i, a in enumerate(actions)
        if vh.ident(a) == 'is.workflow.actions.conditional'
        and vh.params(a)['WFControlFlowMode'] == 0
        and uuid in repr(vh.params(a)['WFInput'])
    )
    group = vh.params(actions[start])['GroupingIdentifier']
    marks = [
        i
        for i, a in enumerate(actions)
        if vh.ident(a) == 'is.workflow.actions.conditional'
        and vh.params(a)['GroupingIdentifier'] == group
    ]
    then, otherwise, end = marks
    return actions[then + 1 : otherwise], actions[otherwise + 1 : end]


def test_probe_first_and_a_note_without_a_selection(gen, actions):
    # The probe comes first; without a selection in Photos, the shortcut
    # shows any probe error, says what to do, and stops, before any question.
    assert vh.ident(actions[1]) == RUN_APPLESCRIPT
    assert vh.params(actions[1])['Script'] == gen.applescript_text('probe')
    selection = matches(actions, '^SELECTION')
    assert len(selection) == 1
    then, otherwise = branches(actions, vh.params(selection[0])['UUID'])
    assert then == []
    kinds = [vh.ident(a) for a in otherwise]
    assert kinds[-2:] == [NOTIFICATION, 'is.workflow.actions.exit']
    note = vh.render(
        vh.params(otherwise[-2])['WFNotificationActionBody'], VALUES
    )
    assert note == (
        f'Select the videos in Photos, then choose Share > {NAME} '
        '(or right-click > Share).'
    )
    assert LIST not in kinds and MENU not in kinds
    # "ERROR: ..." from the probe is shown first
    errors = matches(otherwise, '^ERROR')
    assert len(errors) == 1
    error_then, _ = branches(otherwise, vh.params(errors[0])['UUID'])
    assert [vh.ident(a) for a in error_then] == [NOTIFICATION]
    assert "'AppleScript Result'" in repr(vh.params(error_then[0]))


def test_surfaces(gen, sample, actions):
    wf = gen.videos_workflow(sample, actions)
    assert wf['WFWorkflowTypes'] == ['ActionExtension']  # the Share menu
    assert wf['WFWorkflowInputContentItemClasses'] == ['WFAVAssetContentItem']
    assert wf['WFWorkflowName'] == NAME


def unescaped(value):
    """A vCard text value as Contacts shows it."""
    return re.sub(r'\\(.)', r'\1', value)


def card_lists(actions, values=None):
    """Each contact-card list: (prompt, [(title, description)])."""
    lists = []
    for i, a in enumerate(actions):
        if vh.ident(a) != LIST:
            continue

        prompt = vh.params(a)['WFChooseFromListActionPrompt']
        source = actions[i - 3]  # Text -> Set Name -> Get Contacts -> list
        if vh.ident(source) != 'is.workflow.actions.gettext':
            continue

        text = vh.render(
            vh.params(source)['WFTextActionText'], values or VALUES
        )
        if 'BEGIN:VCARD' not in text:
            continue

        cards = re.findall(
            r'N;CHARSET=utf-8:(.*)\nORG;CHARSET=utf-8:(.*)\n', text
        )
        lists.append((
            prompt,
            [(unescaped(title), unescaped(org)) for title, org in cards],
        ))

    return lists


def test_questions_in_order(vf, actions):
    # codec (menu) -> preset (cards) -> tune (menu, H.265 only) -> RF (list)
    # -> size (cards) -> audio (cards); per codec branch, then shared.
    asked = []
    for a in actions:
        p = vh.params(a)
        if vh.ident(a) == MENU and p['WFControlFlowMode'] == 0:
            asked.append(p['WFMenuPrompt'])
        elif (
            vh.ident(a) == LIST
            and p['WFChooseFromListActionPrompt'] != 'Settings'
        ):
            asked.append(p['WFChooseFromListActionPrompt'])

    assert asked == [
        vf.CODEC_PROMPT,
        vf.PRESET_PROMPT,  # H.265
        vf.TUNE_PROMPT,
        vf.RF_PROMPT,
        vf.PRESET_PROMPT,  # AV1: no tune
        vf.RF_PROMPT,
        vf.SIZE_PROMPT,
        vf.AUDIO_PROMPT,
    ]


def test_lists_titles_descriptions_and_defaults(vf, actions):
    lists = card_lists(actions)
    by_prompt = {}
    for prompt, cards in lists:
        by_prompt.setdefault(prompt, []).append(cards)

    presets = by_prompt[vf.PRESET_PROMPT]
    assert presets == [
        [
            (vf.titled(p, vf.DEFAULT_PRESETS[codec]), d)
            for p, d in vf.PRESETS[codec]
        ]
        for codec in ('h265', 'av1')
    ]
    assert presets[0][1] == ('medium (default)', "HandBrake's default")
    assert presets[1][0] == (
        '5 (default)',
        "SVT-AV1's and HandBrake's default",
    )
    assert by_prompt[vf.SIZE_PROMPT] == [
        [(vf.titled(s, vf.DEFAULT_SIZE), d) for s, d in vf.SIZES]
    ]
    assert by_prompt[vf.SIZE_PROMPT][0][1][0] == '2K (default)'
    assert by_prompt[vf.AUDIO_PROMPT] == [
        [
            (vf.titled(f'{k} kbps', f'{vf.DEFAULT_AUDIO} kbps'), d)
            for k, d in vf.AUDIO_KBPS
        ]
    ]
    assert by_prompt[vf.AUDIO_PROMPT][0][3] == (
        '160 kbps (default)',
        'Essentially transparent',
    )
    # The menus: codec and tune titles.
    menus = {
        vh.params(a)['WFMenuPrompt']: vh.params(a)['WFMenuItems']
        for a in of(actions, MENU)
        if vh.params(a)['WFControlFlowMode'] == 0
    }
    assert menus[vf.CODEC_PROMPT] == [t for t, _ in vf.CODECS]
    assert menus[vf.TUNE_PROMPT] == ['none (default)', vf.TUNES[1][0]]
    assert 'iPhone 15 Pro or later' in menus[vf.CODEC_PROMPT][1]


def test_rf_lists_mark_each_codec_default(vf, actions):
    rf_texts = []
    for i, a in enumerate(actions):
        p = vh.params(a)
        if (
            vh.ident(a) == LIST
            and p['WFChooseFromListActionPrompt'] == vf.RF_PROMPT
        ):
            text = actions[i - 2]  # Text -> Split Text -> list
            rf_texts.append(vh.render(vh.params(text)['WFTextActionText'], {}))

    assert [t.splitlines() for t in rf_texts] == [
        [vf.titled(rf, vf.DEFAULT_RFS[codec]) for rf in vf.RF_VALUES]
        for codec in ('h265', 'av1')
    ]
    assert '24 (default)' in rf_texts[0] and '30 (default)' in rf_texts[1]
    assert vf.RF_VALUES == [19, 20, 21, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40]


def test_each_answer_reaches_the_script(gen, actions):
    # Each question sets its variable to the first word of the chosen title
    # (the menus to their values), and the script reads the variables.
    for name in ('Preset', 'RF', 'Size', 'Audio'):
        sets = [
            i
            for i, a in enumerate(actions)
            if vh.ident(a) == 'is.workflow.actions.setvariable'
            and vh.params(a)['WFVariableName'] == name
        ]
        assert sets
        for i in sets:
            assert vh.ident(actions[i - 1]) == MATCH
            assert vh.params(actions[i - 1])['WFMatchTextPattern'] == r'^\S+'

    values = {}
    for a in of(actions, 'is.workflow.actions.setvariable'):
        name = vh.params(a)['WFVariableName']
        if name in ('Codec', 'Tune', 'Reuse'):
            ref = next(vh.references(vh.params(a)['WFInput']))
            text = next(
                b
                for b in actions
                if vh.params(b).get('UUID') == ref['OutputUUID']
            )
            values.setdefault(name, []).append(
                vh.render(vh.params(text)['WFTextActionText'], {})
            )

    assert values == {
        'Reuse': ['1'],
        'Codec': ['h265', 'av1'],
        'Tune': ['none', 'grain'],
    }
    text = next(
        t
        for t in vh.shell_scripts(
            actions,
            {
                **VALUES,
                'Codec': 'av1',
                'Preset': '4',
                'RF': '32',
                'Size': '720p',
                'Audio': '96',
                'Tune': '',
            },
        )
        if 'vid_done.txt' in t
    )
    for line in (
        "CODEC='av1'",
        "PRESET='4'",
        "TUNE=''",
        "RF='32'",
        "SIZE='720p'",
        "AUDIO='96'",
        "REUSE=''",
    ):
        assert f'\n{line}\n' in text


def test_same_as_last_time(vf, actions):
    # The last run's summary (a script reading last-settings.txt) titles the
    # first card; choosing it sets Reuse, and the questions are asked only
    # when Reuse has no value.
    summary = next(
        a
        for a in of(actions, RUN_SHELL)
        if 'last-settings.txt' in str(vh.params(a)['Script'])
        and 'SUMMARY' in str(vh.params(a)['Script'])
    )
    assert vh.params(summary)['Script'].startswith('sed -n "s/^SUMMARY=//p"')
    settings = [
        cards for prompt, cards in card_lists(actions) if prompt == 'Settings'
    ]
    assert settings == [
        [
            (f'{vf.SAME_TITLE}: H.265 · preset medium', vf.SAME_DESCRIPTION),
            (vf.CHOOSE_TITLE, vf.CHOOSE_DESCRIPTION),
        ]
    ]
    reuse = next(
        a
        for a in of(actions, 'is.workflow.actions.conditional')
        if "'Reuse'" in repr(vh.params(a).get('WFInput', ''))
    )
    asked = [
        inside
        for a, inside in vh.inside_if_on(actions, "'Reuse'")
        if vh.ident(a) == MENU and vh.params(a)['WFControlFlowMode'] == 0
    ]
    assert asked == [
        False,
        False,
    ]  # codec and tune menus: the Otherwise branch
    assert reuse


def test_shell_scripts_use_zsh(gen, actions):
    scripts = of(actions, RUN_SHELL)
    for a in scripts:
        p = vh.params(a)
        assert p['Shell'] == '/bin/zsh'
        assert p['InputMode'] in ('as arguments', 'to stdin')

    # Only the finish script has an input: the outcome, on stdin.
    with_input = [a for a in scripts if 'Input' in vh.params(a)]
    assert len(with_input) == 1
    assert vh.params(with_input[0])['InputMode'] == 'to stdin'
    finish = vh.params(with_input[0])['Script']
    assert 'Done. You can close this window.' in finish
    assert 'rm -rf "$W/in" "$W"/vid_*' in finish
    text = next(
        t for t in vh.shell_scripts(actions, VALUES) if 'vid_done.txt' in t
    )
    assert '"$HOME/Pictures/.compress-videos-macos"' in text
    assert 'open -a Terminal "$cmd"' in text
    assert 'while the conversion runs' in text
    assert "VERSION='" + gen.VERSION + "'" in text
    assert not re.findall('@[A-Z_]+@', text)


def test_applescripts_in_order_with_their_inputs(gen, actions):
    scripts = of(actions, RUN_APPLESCRIPT)
    assert [vh.params(a)['Script'] for a in scripts] == [
        gen.applescript_text(n) for n in ('probe', 'export', 'import')
    ]
    for a in scripts:
        assert isinstance(vh.params(a)['Script'], str)  # no variables inside

    probe, export, imp = scripts
    assert 'Input' not in vh.params(probe)
    ids = {vh.params(a)['UUID']: a for a in actions if 'UUID' in vh.params(a)}
    for a, marker in ((export, 'mkdir -p "$W/in"'), (imp, 'vid_done.txt')):
        ref = next(vh.references(vh.params(a)['Input']))
        source = vh.params(ids[ref['OutputUUID']])['Script']
        assert marker in vh.render(source, VALUES)

    # the conversion script reads the export's lines
    conversion = next(
        a
        for a in of(actions, RUN_SHELL)
        if 'vid_done.txt' in str(vh.params(a)['Script'])
    )
    refs = [
        r
        for r in vh.references(vh.params(conversion)['Script'])
        if r.get('Type') == 'ActionOutput'
    ]
    assert [r['OutputUUID'] for r in refs] == [vh.params(export)['UUID']]
    text = gen.applescript_text('import')
    assert gen.ORIGINALS_ALBUM == 'Videos already compressed'
    assert f'"{gen.ORIGINALS_ALBUM}"' in text
    assert text.startswith(f'-- {NAME}: imports the files the shell made')
    assert 'with timeout of 3600 seconds' in gen.applescript_text('export')


def test_applescripts_compile(gen):
    # osacompile reads Photos' dictionary without launching it.
    vh.need(shutil.which('osacompile'), 'osacompile is needed')
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


def test_log_shown_only_with_warnings(gen, actions):
    warns = matches(actions, gen.WARNINGS)
    assert len(warns) == 1
    looks = [
        inside
        for a, inside in vh.inside_if_on(actions, vh.params(warns[0])['UUID'])
        if vh.ident(a) == 'is.workflow.actions.previewdocument'
    ]
    assert looks == [True]


def test_notifications(gen, actions):
    bodies = [
        vh.render(vh.params(a)['WFNotificationActionBody'], VALUES)
        for a in of(actions, NOTIFICATION)
    ]
    assert any(
        b.startswith('Converting the videos among the 3 item(s)')
        for b in bodies
    )
    assert any(
        b.startswith(
            'Saved 3 video(s) to Photos. 3 original(s) are in the album "Videos already compressed"'
        )
        for b in bodies
    )
    assert 'Saved 3 video(s) to Photos.' in bodies
    # the skipped items, from the script's vid_skipped.txt, when there are any
    skipped = next(
        a
        for a in of(actions, RUN_SHELL)
        if 'vid_skipped.txt' in str(vh.params(a)['Script'])
        and str(vh.params(a)['Script']).startswith('cat ')
    )
    shown = [
        inside
        for a, inside in vh.inside_if_on(actions, vh.params(skipped)['UUID'])
        if vh.ident(a) == NOTIFICATION
    ]
    assert True in shown
    for a in of(actions, NOTIFICATION):
        assert vh.params(a)['WFNotificationActionTitle'] == 'Compress Videos'


def test_written_file_is_valid(gen, sample, actions, tmp_path, monkeypatch):
    monkeypatch.setattr(gen, 'OUT', tmp_path)
    monkeypatch.setattr(gen, 'DIST', tmp_path)
    gen.write(NAME, gen.videos_workflow(sample, actions), sign=False)
    assert (tmp_path / f'{NAME}.unsigned.wflow').exists()


@pytest.mark.parametrize('codec', ['h265', 'av1'])
def test_lists_values_are_the_scripts(vf, codec):
    # The values the script accepts (common.zsh) are the lists'.
    assert [p for p, _ in vf.PRESETS[codec]] == (
        ['fast', 'medium', 'slow'] if codec == 'h265' else ['5', '4', '3', '2']
    )
    assert vf.DEFAULT_PRESETS[codec] in dict(vf.PRESETS[codec])
    assert vf.DEFAULT_RFS[codec] in vf.RF_VALUES
    assert [s for s, _ in vf.SIZES] == ['4K', '2K', '1080p', '720p']
    assert [k for k, _ in vf.AUDIO_KBPS] == [64, 96, 128, 160, 192, 256]
    assert [v for _, v in vf.TUNES] == ['none', 'grain']
