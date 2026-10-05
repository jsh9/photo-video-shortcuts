#!/usr/bin/env python3
"""
Generates the Mac shortcut "Compress Videos (macOS)" as a signed .shortcut
file.

Started while Photos is in front with videos selected (Share menu, right-click
> Share, the menu bar), it converts that selection: Photos exports the
originals, ffmpeg converts each video to H.265 or AV1 with Opus sound
(HandBrake's settings, asked as six questions), vidmeta copies the original's
metadata, the copies are imported into the originals' albums, and the originals
are collected in an album for the user to delete. Started any other way, it
says to select the videos in Photos: Shortcuts can't hand a script the original
videos (its picker re-renders them, and failed on some), so there is no picker.

The conversion is one Run Shell Script (scripts/mac/*.zsh with lib/mac's
progress window and finish step), which Shortcuts waits for however long it
takes; the AppleScripts are lib/mac/*.applescript, shared with Compress Photos
(macOS). tests/compress-videos/test_mac_script.py runs the script for real. See
../README.md and ../DEVELOPING.md.

Usage::

    build_mac_shortcuts.py --guess [--no-sign]
    build_mac_shortcuts.py --fetch https://www.icloud.com/shortcuts/<id>
    build_mac_shortcuts.py [--no-sign]
"""

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import vf  # noqa: E402
from vf import VERSION, Sample, variable, workflow  # noqa: E402

SAMPLE = HERE / 'sample' / 'Mac Sample.plist'
DIST = HERE.parent / 'dist'
OUT = HERE.parent / 'build' / 'shortcuts'

NAME = 'Compress Videos (macOS)'
HELP_URL = 'https://github.com/jsh9/photo-video-shortcuts/blob/main/shortcuts/compress-videos/README.md'
NOTIFY = 'Compress Videos'  # the notifications' title

# Where the script looks for its tools, in order. Ours are installed in
# ~/.local/bin as compress-videos-ffmpeg and compress-videos-ffprobe (see
# README.md): our build is minimal, so it must not take the place of another
# ffmpeg in the user's shell. Homebrew's ffmpeg is used when ours isn't
# installed. ffprobe is the file next to ffmpeg named like it, with "ffprobe"
# for "ffmpeg".
FFMPEG_PATHS = [
    '$HOME/.local/bin/compress-videos-ffmpeg',
    '$HOME/bin/compress-videos-ffmpeg',
    '/opt/homebrew/bin/ffmpeg',
    '/usr/local/bin/ffmpeg',
]
VIDMETA_PATHS = [
    '$HOME/.local/bin/vidmeta',
    '$HOME/bin/vidmeta',
    '/opt/homebrew/bin/vidmeta',
    '/usr/local/bin/vidmeta',
]
# The work folder: Photos exports the originals into it and imports the
# copies from it (AppleScript), and its sandbox reaches ~/Pictures.
WORK = '"$HOME/Pictures/.compress-videos-macos"'
# The album that collects the originals of the converted videos (a script
# can't delete them; the user deletes them from there).
ORIGINALS_ALBUM = 'Videos already compressed'
# The log, the progress window's script and its pid, and the last run's
# settings: a plain folder, so that Terminal never needs access to Pictures.
LOG_DIR = '"$HOME/Library/Caches/compress-videos-macos"'
ROUTE = 'videos'  # the log is <LOG_DIR>/videos.log
# A log line worth showing: "!" notes, errors, failed videos.
WARNINGS = r'(^|\n) *(!|ERROR|[0-9]+ failed)'

# ---------------------------------------------------------------------------
# The shell script (zsh): scripts/mac/*.zsh, with @PLACEHOLDERS@

MAC = HERE / 'mac'
# The Mac parts shared with the other tools: the progress window
# (progress.zsh, at encode.zsh's @PROGRESS@), finish.zsh and the AppleScripts.
LIB_MAC = HERE.parents[2] / 'lib' / 'mac'
# The placeholders that become Shortcuts variables: the six answers (vf.py)
# and Reuse ("1" for the last run's settings), and @LINES@, the export's
# "id|filename" lines (its Run AppleScript's result).
SLOTS = {
    '@CODEC@': 'Codec',
    '@PRESET@': 'Preset',
    '@TUNE@': 'Tune',
    '@RF@': 'RF',
    '@SIZE@': 'Size',
    '@AUDIO@': 'Audio',
    '@REUSE@': 'Reuse',
    '@LINES@': None,
}


def script_text():
    """
    The conversion script as one text with the @SLOTS@ still in it: common.zsh,
    then selection.zsh with encode.zsh (and lib/mac's progress.zsh) at its
    @RUN@.
    """
    text = (MAC / 'common.zsh').read_text() + (
        MAC / 'selection.zsh'
    ).read_text()
    text = text.replace('@RUN@\n', (MAC / 'encode.zsh').read_text())
    text = text.replace('@PROGRESS@\n', (LIB_MAC / 'progress.zsh').read_text())
    for placeholder, value in {
        '@NAME@': NAME,
        '@VERSION@': VERSION,
        '@HELP_URL@': HELP_URL,
        '@WORK@': WORK,
        '@LOG_DIR@': LOG_DIR,
        '@ROUTE@': ROUTE,
        '@ENCODER@': 'ffmpeg',
        '@FFMPEG_CANDIDATES@': ' '.join(f'"{p}"' for p in FFMPEG_PATHS),
        '@FFMPEG_LOOKED@': ', '.join(
            p.replace('$HOME', '~') for p in FFMPEG_PATHS
        ),
        '@VIDMETA_CANDIDATES@': ' '.join(f'"{p}"' for p in VIDMETA_PATHS),
        '@VIDMETA_LOOKED@': ', '.join(
            p.replace('$HOME', '~') for p in VIDMETA_PATHS
        ),
    }.items():
        text = text.replace(placeholder, value)

    left = [s for s in re.findall('@[A-Z_]+@', text) if s not in SLOTS]
    assert not left, f'unknown placeholders: {left}'
    return text


def script(lines):
    """
    The conversion script's text parts: strings, the @SLOTS@ variables, and
    ``lines`` (the export's output) for @LINES@.
    """
    parts = []
    for piece in re.split(f'({"|".join(SLOTS)})', script_text()):
        if piece in SLOTS:
            parts.append(variable(SLOTS[piece]) if SLOTS[piece] else lines)
        elif piece:
            parts.append(piece)

    return parts


def applescript_text(name):
    """
    lib/mac/<name>.applescript, with @NAME@, @KIND@ and @ORIGINALS_ALBUM@
    filled in. Plain text: a Shortcuts variable inside a Run AppleScript's text
    keeps it from compiling (it then produces no output and no error; seen on
    macOS 26), so values go in through the action's input.
    """
    text = (LIB_MAC / f'{name}.applescript').read_text()
    text = text.replace('@NAME@', NAME).replace('@KIND@', 'converted video')
    text = text.replace('@ORIGINALS_ALBUM@', ORIGINALS_ALBUM)
    assert not re.findall('@[A-Z_]+@', text), name
    return text


def finish_script():
    """
    The last Run Shell Script (input: the outcome, on stdin): appends it to the
    log, ends the progress window (finish.zsh: "Done", then the window's own
    tail, by its recorded pid), and removes the originals Photos exported and
    the work files. out/ stays: Photos may reference the imported files instead
    of copying them (Photos ▸ Settings ▸ Importing), and the next run starts by
    emptying the folder anyway.
    """
    return (
        f'W={WORK}; LOGDIR={LOG_DIR}; LOG="$LOGDIR/{ROUTE}.log"\n'
        '{ echo; cat; echo; } >> "$LOG"\n'
        + (LIB_MAC / 'finish.zsh').read_text().replace('@ROUTE@', ROUTE)
        + 'rm -rf "$W/in" "$W"/vid_*'
    )


# ---------------------------------------------------------------------------
# The shortcut


def build(sample):
    b = vf.Builder(sample)
    b.comment(
        f'{NAME} {VERSION}. '
        'Converts the videos selected in Photos to H.265 or AV1 with ffmpeg (Run '
        "Shell Script), with HandBrake's settings and Opus sound, keeping their "
        'metadata (date, location, camera, lens), HDR and Dolby Vision. Select the '
        'videos in Photos, then Share > Compress Videos (macOS): Photos exports the '
        "originals, the copies are imported into the originals' albums, and the "
        f'originals go into the album "{ORIGINALS_ALBUM}" for you to delete. Photos, '
        'Live Photos and slo-mo videos are skipped. AV1 plays only on Macs with M3 '
        'or later, iPhone 15 Pro or later. Needs ffmpeg, ffprobe and vidmeta in '
        '~/.local/bin and Allow Running Scripts in Shortcuts > Settings > Advanced. '
        f'Setup and help: {HELP_URL}'
    )
    # Only the videos selected in Photos, with Photos in front: Photos then
    # exports the originals, with their ids (albums, collection).
    probe = b.run_applescript(applescript_text('probe'))

    def not_selected():
        # "ERROR: ..." (for example, Shortcuts may not control Photos) is
        # shown first, so the user knows why nothing happens.
        b.if_has_value(
            b.match_text(probe, '^ERROR'),
            lambda: b.notification(NOTIFY, probe),
            lambda: None,
        )
        b.notification(
            NOTIFY,
            'Select the videos in Photos, then choose Share > '
            f'{NAME} (or right-click > Share).',
        )
        b.stop()

    b.if_has_value(
        b.match_text(probe, '^SELECTION'), lambda: None, not_selected
    )
    last = b.run_shell_script(
        f'sed -n "s/^SUMMARY=//p" {LOG_DIR}/last-settings.txt 2>/dev/null || true'
    )
    vf.settings(b, last)
    count = b.match_text(probe, r'\d+')
    b.notification(
        NOTIFY,
        'Converting the videos among the ',
        count,
        ' item(s) selected in Photos… A Terminal window follows the progress.',
    )
    # An empty work folder; its path is the export script's input.
    work = b.run_shell_script(
        f'W={WORK}; rm -rf "$W"; mkdir -p "$W/in"; printf "%s" "$W"'
    )
    ids = b.run_applescript(applescript_text('export'), input_ref=work)
    result = b.run_shell_script(*script(ids))
    # "imported=N", "collected=M", the times, then "! ..." problem lines.
    outcome = b.run_applescript(applescript_text('import'), input_ref=result)
    lines = b.split(outcome, '\n')
    imported = b.match_text(b.item_at_index(lines, 1), r'\d+')
    collected = b.match_text(b.item_at_index(lines, 2), r'\d+')
    log = b.text(
        b.run_shell_script(f'cat {LOG_DIR}/{ROUTE}.log 2>/dev/null || true'),
        '\n',
        outcome,
    )
    skipped = b.run_shell_script(
        f'cat {WORK}/vid_skipped.txt 2>/dev/null || true'
    )
    b.if_has_value(
        b.match_text(log, WARNINGS), lambda: b.quick_look(log), lambda: None
    )
    b.run_shell_script(finish_script(), input_ref=outcome, as_arguments=False)
    b.if_has_value(
        skipped, lambda: b.notification(NOTIFY, skipped), lambda: None
    )
    b.if_has_value(
        b.match_text(b.item_at_index(lines, 2), '^collected=[1-9]'),
        lambda: b.notification(
            NOTIFY,
            'Saved ',
            imported,
            ' video(s) to Photos. ',
            collected,
            f' original(s) are in the album "{ORIGINALS_ALBUM}" for you to delete.',
        ),
        lambda: b.notification(
            NOTIFY, 'Saved ', imported, ' video(s) to Photos.'
        ),
    )
    return b.actions


def videos_workflow(sample, actions):
    # The Share menu for videos (Photos' "Receive Media").
    return workflow(
        sample,
        NAME,
        actions,
        share_sheet=True,
        types=['ActionExtension'],
        input_classes=['WFAVAssetContentItem'],
    )


def write(name, workflow_dict, sign):
    vf.write(name, workflow_dict, sign, OUT, DIST)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        '--fetch',
        metavar='ICLOUD_LINK',
        help='download a sample shortcut built on the Mac from its iCloud link',
    )
    ap.add_argument(
        '--no-sign', action='store_true', help='write unsigned plists only'
    )
    ap.add_argument(
        '--sample',
        type=Path,
        default=SAMPLE,
        help='sample shortcut plist to use',
    )
    ap.add_argument(
        '--guess',
        action='store_true',
        help='use hand-written action templates instead of a sample (best guess)',
    )
    args = ap.parse_args()
    if args.fetch:
        vf.fetch_sample(args.fetch, SAMPLE)

    if args.guess:
        sample = Sample(vf.guessed_workflow())
    elif not args.sample.exists():
        sys.exit(
            f'missing {args.sample}: run with --fetch <iCloud link of a sample shortcut>, or --guess'
        )
    else:
        sample = Sample(args.sample)

    write(NAME, videos_workflow(sample, build(sample)), not args.no_sign)


if __name__ == '__main__':
    main()
