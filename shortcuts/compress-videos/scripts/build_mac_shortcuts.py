#!/usr/bin/env python3
"""
Generates the Mac shortcut "Compress Videos (macOS)" as a signed .shortcut
file.

It works only on videos selected in Photos. Started while Photos is in front
with videos selected (Share menu, right-click > Share, the menu bar), it
converts that selection: Photos exports the originals, ffmpeg converts each
video to H.265 or AV1 with Opus sound (HandBrake's settings, asked as six
questions), vidmeta copies the original's metadata, the copies are imported
into the originals' albums, and the originals are collected in an album for the
user to delete. Started any other way (the Shortcuts app, Spotlight...), it
only says to select the videos in Photos: Shortcuts can't hand a script the
original videos (its picker re-renders them, and failed on some), so there is
no picker.

The conversion is one Run Shell Script (scripts/mac/*.zsh with lib/mac's
progress window and finish step), which Shortcuts waits for however long it
takes; a first run of the same script, its planning pass, names the videos it
will convert, which scripts/mac/bridge.applescript puts into an album so that
Find Photos gets Photos' current version of each (an edited video is converted
as it looks, its edit burnt in). The other AppleScripts are
lib/mac/*.applescript, shared with Compress Photos (macOS).
tests/compress-videos/test_mac_script.py runs the script for real. See
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
from vf import VERSION, Ref, Sample, variable, workflow  # noqa: E402

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
# Free space the work folder's disk must have before Photos exports anything,
# per selected item, for its original and its copy: about three minutes of 4K
# iPhone video. Generous for short clips and photos; once the files are
# exported, the conversion script checks their real size.
ROOM_PER_ITEM = 500_000_000  # bytes
# The album that collects the originals of the converted videos (a script
# can't delete them; the user deletes them from there).
ORIGINALS_ALBUM = 'Videos already compressed'
# The album through which Find Photos gets Photos' current version of each
# video to convert (bridge.applescript fills it by id): top level, made after
# the planning pass and deleted before the conversion, so it shows for
# seconds. A run that dies leaves it, and the next run deletes it first.
BRIDGE_ALBUM = 'Compress Videos (working)'
# The keyword each copy gets in Photos after the import (import.applescript,
# copyKeywords), with its original's, to find the copies there; in Photos'
# library only, the same word as Compress Photos' (wfkit's). No format or
# quality keywords (Compress Photos adds "jxl" and "q=83", or "heic" and
# "RF=26").
COPY_KEYWORD = vf.COPY_KEYWORD
FORMAT_KEYWORDS = {}
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
# and Reuse ("1" for the last run's settings), @LINES@, the export's
# "id|date|filename" lines (its Run AppleScript's result), and, in the
# conversion only (empty in the planning pass, which runs before them), the
# album script's answer, the files' dates and the album's deletion.
SLOTS = {
    '@CODEC@': 'Codec',
    '@PRESET@': 'Preset',
    '@TUNE@': 'Tune',
    '@RF@': 'RF',
    '@SIZE@': 'Size',
    '@AUDIO@': 'Audio',
    '@REUSE@': 'Reuse',
    '@LINES@': None,
    '@BRIDGE@': 'Bridge',
    '@DATES@': 'Dates',
    '@CLOSED@': 'Closed',
}
# The slots the planning pass leaves empty
CONVERSION_SLOTS = {'@BRIDGE@', '@DATES@', '@CLOSED@'}


def script_text(phase='convert'):
    """
    The script as one text with the @SLOTS@ still in it: common.zsh, then
    selection.zsh with encode.zsh (and lib/mac's progress.zsh) at its @RUN@.
    The planning pass (``phase`` "plan") ends at selection.zsh's @PLAN_END@,
    where it exits.
    """
    text = (MAC / 'common.zsh').read_text() + (
        MAC / 'selection.zsh'
    ).read_text()
    if phase == 'plan':
        text = text[: text.index('@PLAN_END@\n')]
    else:
        text = text.replace('@PLAN_END@\n', '')

    text = text.replace('@RUN@\n', (MAC / 'encode.zsh').read_text())
    text = text.replace('@PROGRESS@\n', (LIB_MAC / 'progress.zsh').read_text())
    for placeholder, value in {
        '@PHASE@': phase,
        '@BRIDGE_ALBUM@': BRIDGE_ALBUM,
        '@NAME@': NAME,
        '@VERSION@': VERSION,
        '@HELP_URL@': HELP_URL,
        '@WORK@': WORK,
        '@LOG_DIR@': LOG_DIR,
        '@ROUTE@': ROUTE,
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


def script(lines, phase='convert'):
    """
    The script's text parts: strings, the @SLOTS@ variables, and ``lines`` (the
    export's output) for @LINES@; the planning pass has nothing for the
    conversion's slots.
    """
    parts = []
    for piece in re.split(f'({"|".join(SLOTS)})', script_text(phase)):
        if piece in SLOTS:
            if phase == 'plan' and piece in CONVERSION_SLOTS:
                continue

            parts.append(variable(SLOTS[piece]) if SLOTS[piece] else lines)
        elif piece:
            parts.append(piece)

    return parts


def applescript_text(name):
    """
    lib/mac/<name>.applescript (shared with the other tools), or this tool's
    own mac/<name>.applescript (bridge), with @NAME@, @ORIGINALS_ALBUM@,
    @BRIDGE_ALBUM@, @COPY_KEYWORD@, @FORMAT_KEYWORDS@ and @QUALITY_PREFIXES@
    (AppleScript lists, empty here) filled in, and @OLD_ORIGINALS_ALBUM@, an
    earlier version's review album, which Compress Videos never had: the same
    album again (``vf.applescript_text``: plain text, the values going in
    through the action's input).
    """
    path = MAC / f'{name}.applescript'
    if not path.exists():
        path = LIB_MAC / f'{name}.applescript'

    return vf.applescript_text(
        path,
        NAME=NAME,
        BRIDGE_ALBUM=BRIDGE_ALBUM,
        ORIGINALS_ALBUM=ORIGINALS_ALBUM,
        OLD_ORIGINALS_ALBUM=ORIGINALS_ALBUM,
        COPY_KEYWORD=COPY_KEYWORD,
        FORMAT_KEYWORDS=list(FORMAT_KEYWORDS),
        QUALITY_PREFIXES=list(FORMAT_KEYWORDS.values()),
    )


def prepare_script(count):
    """
    The first Run Shell Script's parts: an empty work folder, whose path it
    prints (the export script's input), if its disk has ROOM_PER_ITEM for each
    of the ``count`` items selected in Photos; else an "ERROR: ..." line, so
    that Photos never fills the disk with the export.
    """
    return (
        f'W={WORK}; rm -rf "$W"; mkdir -p "$W/in"\nn=',
        count,
        '\n'
        '[[ $n == <-> ]] || n=0\n'
        f'need=$(( n * {ROOM_PER_ITEM} ))\n'
        'free=$(( $(df -k "$W" | awk \'NR == 2 { print $4 }\') * 1024 ))\n'
        'if (( free < need )); then\n'
        "  printf 'ERROR: not enough free space for the %d item(s) selected in "
        'Photos: about %.1f GB is needed (the exported originals and their '
        "copies), %.1f GB is free. Select fewer videos, or free some space.' "
        '$n $(( need / 1e9 )) $(( free / 1e9 ))\n'
        'else\n'
        '  printf "%s" "$W"\n'
        'fi',
    )


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
        + 'rm -rf "$W/in" "$W"/vid_*(N)'
    )


# ---------------------------------------------------------------------------
# The shortcut


def build(sample):
    b = vf.Builder(sample)
    b.comment(
        f'{NAME} {VERSION}. '
        'Converts the videos selected in Photos to H.265 or AV1 with ffmpeg (Run '
        "Shell Script), with HandBrake's settings and Opus sound, keeping their "
        'metadata (date, location, camera, lens), HDR and Dolby Vision. It works '
        'only on videos selected in Photos: select them there, then Share > '
        f'{NAME}. Run from the Shortcuts app or anywhere else, it only says so; it '
        'has no picker. Photos exports the originals (an edited video is converted '
        'as it looks in Photos, its edit burnt in, through the album '
        f'"{BRIDGE_ALBUM}", which it deletes before converting), the copies are '
        "imported into the originals' albums, and the originals go into the album "
        f'"{ORIGINALS_ALBUM}" for you to delete. Photos, Live Photos and slo-mo '
        'videos are skipped. AV1 plays only on Macs with M3 or later, iPhone 15 Pro '
        'or later. Needs ffmpeg, ffprobe and vidmeta in ~/.local/bin and Allow '
        'Running Scripts in Shortcuts > Settings > Advanced. '
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
    # The work folder, if there is room for the export, before any question.
    count = b.match_text(probe, r'\d+')
    work = b.run_shell_script(*prepare_script(count))

    def no_room():
        b.notification(NOTIFY, work)
        b.stop()

    b.if_has_value(b.match_text(work, '^ERROR'), no_room, lambda: None)
    last = b.run_shell_script(
        f'sed -n "s/^SUMMARY=//p" {LOG_DIR}/last-settings.txt 2>/dev/null || true'
    )
    vf.settings(b, last)
    b.notification(
        NOTIFY,
        'Converting the videos among the ',
        count,
        ' item(s) selected in Photos… A Terminal window follows the progress.',
    )
    ids = b.run_applescript(applescript_text('export'), input_ref=work)
    renderings(b, ids)
    result = b.run_shell_script(*script(ids), input_ref=as_media('Renderings'))
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


def renderings(b, ids):
    """
    Photos' current version of each video the conversion will convert, for the
    script to compare with the exported original (selection.zsh): the planning
    pass (the same script, PHASE "plan") prints their "id|date|filename" lines;
    bridge.applescript puts those videos into the album BRIDGE_ALBUM and
    answers "BRIDGE n" (the variable Bridge); if it holds any, Find Photos gets
    them as library items (the variable Renderings), whose files Shortcuts
    makes from Photos' current version (an edited video's rendering, an
    unedited one's original), and their dates in Photos go to the variable
    Dates (by position). The album is deleted then, before the conversion (the
    variable Closed, "CLOSED"): Renderings holds library items, not the
    album's. Otherwise Renderings stays unset, and the conversion gets no
    files.

    Find Photos has no try: should it fail (Shortcuts without access to the
    photo library), Shortcuts stops the run there, before anything is
    converted, and the next run deletes the album. Only the videos the
    conversion will convert go into the album: a slo-mo, the one kind seen to
    fail when Shortcuts made its file, never does.
    """
    plan = b.run_shell_script(*script(ids, 'plan'))
    b.set_variable(
        'Bridge',
        b.run_applescript(applescript_text('bridge'), input_ref=plan),
    )

    def find():
        found = b.find_photos_in_album(BRIDGE_ALBUM)
        b.set_variable('Renderings', found)
        b.repeat_each(
            found, lambda: video_date(b, vf.REPEAT_ITEM, vf.REPEAT_INDEX)
        )

    b.if_has_value(
        b.match_text(variable('Bridge'), r'^BRIDGE [1-9]'), find, lambda: None
    )
    b.set_variable(
        'Closed',
        b.run_applescript(
            applescript_text('bridge'), input_ref=b.text('close')
        ),
    )


def as_media(name):
    """
    The variable ``name`` as Media (Shortcuts' type menu on a variable:
    WFAVAssetContentItem), so that a library video becomes its video. Passed as
    it is, Run Shell Script asks each item for a file of any type, and
    ContentKit (WFPhotoMediaContentItem, iOS 18.2:
    preferredAssetResourceForType:) gives the first full-size rendering among
    the asset's resources: for an edited video, a still JPEG of it (seen on
    macOS 27: IMG_1970.jpeg, 301 KB, for an edited .MOV). As Media, the item is
    PhotoKit's AVAsset of the video's current version (generateAVAsset:
    requestAVAssetForVideo, default version), whose file Shortcuts copies (an
    AVURLAsset) or exports passthrough: an unedited video's original, an edited
    one's rendering.
    """
    ref = variable(name)
    return Ref({
        **ref.value,
        'Aggrandizements': [
            {
                'Type': 'WFCoercionVariableAggrandizement',
                'CoercionItemClass': 'WFAVAssetContentItem',
            }
        ],
    })


def video_date(b, item, index):
    """
    Appends "index|date" to the variable Dates: ``item``'s date in Photos (Get
    Details ▸ Date Taken, the asset's creation date), as ISO 8601 with the
    time, to tell apart two videos whose files share a name.
    """
    taken = b.photo_details(item, 'Date Taken')
    b.if_has_value(
        b.match_text(taken, '.'),
        lambda: b.append_variable(
            'Dates', b.text(index, '|', b.format_date(taken))
        ),
        lambda: None,
    )


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
