#!/usr/bin/env python3
"""
Generates the two Mac shortcuts as signed .shortcut files.

- "Compress Photos (macOS)": started while Photos is in front with photos
  selected, it converts that selection (Photos exports the originals, the
  copies are imported into the originals' albums, and the originals whose copy
  has everything they have are collected in an album for the user to delete);
  started any other way, it shows a photo picker and saves the copies to
  Photos, in the originals' albums, leaving the originals alone.
- "Compress Photo Files (macOS)": image files or folders from Finder (Quick
  Actions) → .jxl files next to the originals.

Both run jxlbatch (the native macOS build, dist/jxlbatch-macos, installed as
~/.local/bin/jxlbatch) through Shortcuts' Run Shell Script action, which waits
for the script, so there is no a-Shell, no helper shortcut and no handoff. The
shell scripts are in scripts/mac/*.zsh and lib/mac/*.zsh (the progress window
and the finish step), the AppleScripts in lib/mac/*.applescript (lib/ is shared
with the other tools' shortcuts); tests/compress-photos/test_mac_script.py runs
the shell scripts for real. See ../README-mac.md and ../DEVELOPING.md.

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

import wf  # noqa: E402
from wf import (  # noqa: E402
    EFFORT,
    ORIGINALS_ALBUM,
    REPEAT_ITEM,
    SHORTCUT_INPUT,
    VERSION,
    Sample,
    choose_quality,
    collect_in_album,
    copy_to_albums,
    keep_still_photos,
    variable,
    workflow,
)

SAMPLE = HERE / 'sample' / 'Mac Sample.plist'
DIST = HERE.parent / 'dist'
OUT = HERE.parent / 'build' / 'shortcuts'

NAME_PHOTOS = 'Compress Photos (macOS)'
NAME_FILES = 'Compress Photo Files (macOS)'
HELP_URL = 'https://github.com/jsh9/photo-video-shortcuts/blob/main/shortcuts/compress-photos/README-mac.md'
ENCODER_URL = 'https://github.com/jsh9/photo-video-shortcuts/releases/latest/download/jxlbatch-macos'

# Where the script looks for the encoder, in order. ~/.local/bin is the
# documented install location (see README-mac.md); the others are common
# places a user may put it instead.
ENCODER_PATHS = [
    '$HOME/.local/bin/jxlbatch',
    '$HOME/bin/jxlbatch',
    '/usr/local/bin/jxlbatch',
    '/opt/homebrew/bin/jxlbatch',
]
# The work folders, one per user and fixed, so that the shortcut's later steps
# find the results without parsing the script's output.
#
# Compress Photos (macOS) from its picker: a folder inside Shortcuts' own folder in iCloud
# Drive, because Get File, with a path relative to that folder, is the only
# way a file written by a script gets into Shortcuts on the Mac (checked on
# macOS 26: Run AppleScript's file results come back empty, and Get File
# refuses absolute paths). Shortcuts reads it locally; the files are gone
# before iCloud has much to sync.
SHORTCUTS_FOLDER = '"$HOME/Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents"'
WORK_NAME = 'compress-photos-macos'
WORK_PHOTOS = f'{SHORTCUTS_FOLDER}/{WORK_NAME}'
# Compress Photo Files (macOS) needs no bridge: the user's temporary folder
# (TMPDIR ends with a slash on macOS).
WORK_FILES = f'"${{TMPDIR:-/tmp/}}{WORK_NAME}"'
# Compress Photos (macOS) on the photos selected in Photos: Photos itself
# exports the originals into this folder and imports the results from it
# (AppleScript), and its sandbox reaches ~/Pictures but not the folders above.
WORK_SELECTION = f'"$HOME/Pictures/.{WORK_NAME}"'
# The converted originals are collected in the album wf.ORIGINALS_ALBUM (a
# script can't delete photos; the user deletes them from there): the
# selection route by photo id (import.applescript), the picker route by the
# photos themselves (wf.collect_in_album).
# Where every route keeps its log and the progress window's script: a plain
# folder, so that Terminal (the progress window) never needs access to
# iCloud Drive or Pictures (common.zsh sets the same path). Each route has its
# own files there (<route>.log, <route>.command, <route>.pid), so that runs of
# different routes don't clobber each other.
LOG_DIR = '"$HOME/Library/Caches/compress-photos-macos"'
ROUTES = {
    WORK_PHOTOS: 'photos-picker',
    WORK_SELECTION: 'photos-selection',
    WORK_FILES: 'files',
}
# Where the file shortcut saves when it can't write next to the original.
FALLBACK_FOLDER = '"$HOME/Pictures/JPEG XL"'
# A log line worth showing: jxlbatch's "!" notes, errors, failed photos.
WARNINGS = r'(^|\n) *(!|ERROR|[0-9]+ failed)'
# The question after the quality: how the Mac's cores are used, as a menu
# (two short choices; the first is the usual one). Each title's value is what
# the script reads in CORES (run.zsh): "all" converts several photos at a
# time with all the cores (jxlbatch -j 0), "one" converts one photo at a time
# on one thread (-j 1 -t 1), leaving the Mac free for other work.
CORES_PROMPT = 'Cores to use'
CORES_CHOICES = [
    ('All cores (fast)', 'all'),
    ('One core (keeps the Mac responsive)', 'one'),
]
# The third question: whether an HDR photo's HDR goes into the JPEG XL. The
# script reads HDR (run.zsh): "drop" adds jxlbatch --sdr, so every photo is
# saved as an ordinary 8-bit SDR JPEG XL (smaller, no banding in smooth skies,
# and shown correctly by viewers that can't tone-map HDR); anything else keeps
# the HDR (PQ).
HDR_PROMPT = 'HDR'
HDR_CHOICES = [
    ('Keep HDR', 'keep'),
    ('Drop HDR (smaller; shows right in any viewer)', 'drop'),
]

# ---------------------------------------------------------------------------
# The shell script (zsh): scripts/mac/*.zsh, with @PLACEHOLDERS@

MAC = HERE / 'mac'
# The Mac parts shared with the other tools: the progress window
# (progress.zsh, at run.zsh's @PROGRESS@), finish.zsh and the AppleScripts.
LIB_MAC = HERE.parents[2] / 'lib' / 'mac'
# The placeholders that become Shortcuts variables, and the variable each one
# is in the shortcut: the chosen quality (Match Text's Matches), the cores
# choice (the variable Cores, see choose_cores), the lines of NAMES or PATHS
# (Combine Text), and Skipped Echo (an echo of what the shortcut skipped;
# empty when nothing was, which leaves ">> $LOG" alone, a command that only
# touches the log).
SLOTS = {
    '@QUALITY@': 'Matches',
    '@CORES@': 'Cores',
    '@HDR@': 'HDR',
    '@LINES@': 'Combined Text',
    '@SKIPPED@': 'Skipped Echo',
}


def work_setup(work):
    """
    The script lines that set WORK and start it empty. The selection route
    keeps the folder: Photos has already exported the originals into it. The
    Photos shortcut's picker route also notes, before the folder is created,
    whether Shortcuts' iCloud Drive folder is missing (iCloud Drive off for
    Shortcuts): Get File then finds nothing and the shortcut reports every
    photo as not saved.
    """
    if work == WORK_SELECTION:
        return f'WORK={work}\nmkdir -p "$WORK"'

    fresh = f'WORK={work}\nrm -rf "$WORK"\nmkdir -p "$WORK"'
    if work != WORK_PHOTOS:
        return fresh

    return (
        f"icloud_missing=''\n"
        f'[ -d {SHORTCUTS_FOLDER} ] || icloud_missing=1\n' + fresh
    )


def work_check(work):
    """The note about the missing iCloud Drive folder, once the log exists."""
    if work != WORK_PHOTOS:
        return ''

    return (
        '[ -n "$icloud_missing" ] && echo "! Shortcuts\' iCloud Drive folder '
        'not found: the results cannot reach Photos. Turn on iCloud Drive for '
        'Shortcuts in System Settings > Apple Account > iCloud > Drive." '
        '>> "$LOG"'
    )


def script_text(name, body, label, work):
    """
    The script as one text with the five @SLOTS@ still in it: common.zsh, then
    ``body`` (photos.zsh or files.zsh) with run.zsh at its @RUN@.
    """
    text = (MAC / 'common.zsh').read_text() + (MAC / body).read_text()
    text = text.replace('@RUN@\n', (MAC / 'run.zsh').read_text())
    text = text.replace('@PROGRESS@\n', (LIB_MAC / 'progress.zsh').read_text())
    for placeholder, value in {
        '@NAME@': name,
        '@VERSION@': VERSION,
        '@HELP_URL@': HELP_URL,
        '@EFFORT@': str(EFFORT),
        '@ROUTE@': ROUTES[work],
        '@WORK_SETUP@': work_setup(work),
        '@WORK_CHECK@': work_check(work),
        '@FINISH@': (LIB_MAC / 'finish.zsh')
        .read_text()
        .replace('@ROUTE@', ROUTES[work]),
        '@FALLBACK@': FALLBACK_FOLDER,
        '@LABEL@': label,
        '@CANDIDATES@': ' '.join(f'"{p}"' for p in ENCODER_PATHS),
        '@LOOKED@': ', '.join(p.replace('$HOME', '~') for p in ENCODER_PATHS),
    }.items():
        text = text.replace(placeholder, value)

    left = [s for s in re.findall('@[A-Z_]+@', text) if s not in SLOTS]
    assert not left, f'unknown placeholders: {left}'
    return text


def applescript_text(name):
    """
    lib/mac/<name>.applescript, with @NAME@ and @ORIGINALS_ALBUM@ filled in.
    Plain text: a Shortcuts variable inside a Run AppleScript's text keeps it
    from compiling (it then produces no output and no error; seen on macOS 26),
    so values go in through the action's input
    (``wf.Builder.run_applescript``).
    """
    text = (LIB_MAC / f'{name}.applescript').read_text()
    text = text.replace('@NAME@', NAME_PHOTOS)
    text = text.replace('@ORIGINALS_ALBUM@', ORIGINALS_ALBUM)
    assert not re.findall('@[A-Z_]+@', text), name
    return text


def finish_script(work):
    """
    The last Run Shell Script of a Photos route (input: the outcome, to stdin):
    appends it to the log, ends this run's progress window (finish.zsh: "Done",
    then the window's own tail, by its recorded pid), and removes the work
    files. The selection route keeps out/: Photos may reference the imported
    files instead of copying them (Photos ▸ Settings ▸ Importing), and the next
    run starts by emptying the folder anyway.
    """
    route = ROUTES[work]
    cleanup = (
        'rm -rf "$W/in" "$W"/jxl_*'
        if work == WORK_SELECTION
        else 'rm -rf "$W"'
    )
    return (
        f'W={work}; LOGDIR={LOG_DIR}; LOG="$LOGDIR/{route}.log"\n'
        '{ echo; cat; echo; } >> "$LOG"\n'
        + (LIB_MAC / 'finish.zsh').read_text().replace('@ROUTE@', route)
        + cleanup
    )


def script(name, body, label, work, quality, cores, hdr, lines):
    """The Run Shell Script text parts: strings and the five variables."""
    refs = {
        '@QUALITY@': quality,
        '@CORES@': cores,
        '@HDR@': hdr,
        '@LINES@': lines,
        '@SKIPPED@': variable('Skipped Echo'),
    }
    parts = []
    for piece in re.split(
        '(@QUALITY@|@CORES@|@HDR@|@LINES@|@SKIPPED@)',
        script_text(name, body, label, work),
    ):
        if piece in refs:
            parts.append(refs[piece])
        elif piece:
            parts.append(piece)

    return parts


def choose_value(b, prompt, choices, name):
    """
    A Choose from Menu with ``prompt`` and ``choices`` ((title, value) pairs)
    whose cases set the variable ``name`` to the chosen value, for the script;
    returns the variable.
    """

    def choose(value):
        return lambda: b.set_variable(name, b.text(value))

    b.choose_from_menu(
        prompt, {title: choose(value) for title, value in choices}
    )
    return variable(name)


def choose_cores(b):
    """Asks how to use the Mac's cores (CORES_CHOICES); the variable Cores."""
    return choose_value(b, CORES_PROMPT, CORES_CHOICES, 'Cores')


def choose_hdr(b):
    """Asks whether to keep HDR (HDR_CHOICES); the variable HDR."""
    return choose_value(b, HDR_PROMPT, HDR_CHOICES, 'HDR')


# ---------------------------------------------------------------------------
# The two shortcuts


def build_photos(sample):
    b = wf.Builder(sample)
    b.comment(
        f'{NAME_PHOTOS} {VERSION}. '
        'Converts photos to JPEG XL with jxlbatch (Run Shell Script), keeping their '
        'metadata. Only still photos are converted: Live Photos and videos are '
        'skipped. Started while Photos is in front with photos selected (Share menu, '
        'right-click > Shortcuts, menu bar), it converts that selection: Photos '
        "exports the originals, the JPEG XL copies are imported into the originals' "
        f'albums, and the converted originals go into the album "{ORIGINALS_ALBUM}" '
        'for you to review and delete. Started any other way, it shows a photo picker, saves the '
        "copies to Photos in the originals' albums, and collects the originals in that album too. "
        'Needs jxlbatch in ~/.local/bin and Allow Running Scripts in Shortcuts > Settings > '
        f'Advanced. Setup and help: {HELP_URL}'
    )

    # Where the photos come from: the shortcut's input (never on the Mac:
    # Photos' Share menu passes a JPEG that Shortcuts can't read), else the
    # photos selected in Photos when Photos is in front, else a picker.
    def without_input():
        probe = b.run_applescript(applescript_text('probe'))

        def picker():
            # "ERROR: ..." (for example, Shortcuts may not control Photos) is
            # shown, so the user knows why the picker opens instead.
            b.if_has_value(
                b.match_text(probe, '^ERROR'),
                lambda: b.notification('JPEG XL', probe),
                lambda: None,
            )
            b.set_variable('Photos', b.select_photos())

        b.if_has_value(
            b.match_text(probe, '^SELECTION'),
            lambda: b.set_variable('Selection', probe),
            picker,
        )

    b.if_has_value(
        SHORTCUT_INPUT,
        lambda: b.set_variable('Photos', SHORTCUT_INPUT),
        without_input,
    )
    b.if_has_value(
        variable('Selection'),
        lambda: selection_route(b),
        lambda: picker_route(b),
    )
    return b.actions


def selection_route(b):
    """
    The photos selected in Photos, through AppleScript (see mac/*.applescript):
    Photos exports their originals into WORK_SELECTION/in, the script converts
    them, and Photos imports the results into the originals' albums and
    collects the converted originals in ORIGINALS_ALBUM.
    """
    quality = choose_quality(b)
    cores = choose_cores(b)
    hdr = choose_hdr(b)
    count = b.match_text(variable('Selection'), r'\d+')
    b.notification(
        'JPEG XL',
        'Converting ',
        count,
        ' photo(s) selected in Photos… A notification follows when they are saved.',
    )
    # An empty work folder; its path is the export script's input.
    work = b.run_shell_script(
        f'W={WORK_SELECTION}; rm -rf "$W"; mkdir -p "$W/in"; printf "%s" "$W"'
    )
    ids = b.run_applescript(applescript_text('export'), input_ref=work)
    result = b.run_shell_script(
        *script(
            NAME_PHOTOS,
            'selection.zsh',
            'IDS',
            WORK_SELECTION,
            quality,
            cores,
            hdr,
            ids,
        )
    )
    # "imported=N", "collected=M", then "! ..." problem lines.
    outcome = b.run_applescript(applescript_text('import'), input_ref=result)
    lines = b.split(outcome, '\n')
    imported = b.match_text(b.item_at_index(lines, 1), r'\d+')
    collected = b.match_text(b.item_at_index(lines, 2), r'\d+')
    log = b.text(
        b.run_shell_script(
            f'cat {LOG_DIR}/{ROUTES[WORK_SELECTION]}.log 2>/dev/null || true'
        ),
        '\n',
        outcome,
    )
    b.if_has_value(
        b.match_text(log, WARNINGS), lambda: b.quick_look(log), lambda: None
    )
    b.run_shell_script(
        finish_script(WORK_SELECTION), input_ref=outcome, as_arguments=False
    )
    b.if_has_value(
        b.match_text(b.item_at_index(lines, 2), '^collected=[1-9]'),
        lambda: b.notification(
            'JPEG XL',
            'Saved ',
            imported,
            ' photo(s) to Photos. ',
            collected,
            f' original(s) are in the album "{ORIGINALS_ALBUM}" for you to review.',
        ),
        lambda: b.notification(
            'JPEG XL', 'Saved ', imported, ' photo(s) to Photos.'
        ),
    )


def picker_route(b):
    """
    The photos in the variable Photos (the picker's, or the shortcut's input):
    Shortcuts passes them to the script as files, reads the results back with
    Get File from WORK_PHOTOS and saves them to Photos. Each saved copy's
    original is collected in ORIGINALS_ALBUM (collect_in_album, by the item
    itself; no lookup by name). Nothing is deleted: Shortcuts' Delete Photos
    needs a prompt the Shortcuts app often can't show on macOS 26.
    """
    # From here on only the still photos: their positions in Stills are the
    # job indices, also when saving the results.
    photos = keep_still_photos(b, variable('Photos'))
    quality = choose_quality(b)
    cores = choose_cores(b)
    hdr = choose_hdr(b)
    b.notification(
        'JPEG XL',
        'Converting ',
        b.count(photos),
        ' photo(s)… A notification follows when they are saved.',
    )
    # The photos' names, one per line in job order: Shortcuts names the files
    # it passes to the script, and the JPEG XL copies keep the photos' names.
    b.repeat_each(
        photos,
        lambda: b.append_variable('Names', b.text(b.get_name(REPEAT_ITEM))),
    )
    result = b.run_shell_script(
        *script(
            NAME_PHOTOS,
            'photos.zsh',
            'NAMES',
            WORK_PHOTOS,
            quality,
            cores,
            hdr,
            b.combine(variable('Names'), '\n'),
        ),
        input_ref=photos,
    )

    album = b.text(ORIGINALS_ALBUM)

    # Each output line is "file|index|delete or keep|Name.jxl"; no line when
    # nothing was converted (then Match Text finds no "|").
    def save_results():
        lines = b.split(result, '\n')

        def per_file():
            parts = b.split(REPEAT_ITEM, '|')
            file_name = b.item_from_list(parts, 'First Item')
            photo_name = b.item_from_list(parts, 'Last Item')
            # Get File reads it from the work folder inside Shortcuts' iCloud
            # Drive folder (see WORK_PHOTOS).
            file = b.get_file_from_shortcuts_folder(f'{WORK_NAME}/', file_name)
            saved = b.save_to_photos(b.set_name(file, photo_name))

            # Only a photo that is in Photos now counts and joins its
            # original's albums: a save that produced nothing (for example
            # because the file could not be read) is reported instead.
            def when_saved():
                b.append_variable('Saved Photos', saved)
                index = b.item_at_index(parts, 2)
                original = b.item_at_index(photos, index)
                albums = b.photo_albums(original)
                copy_to_albums(b, saved, albums)
                collect_in_album(b, original, album, albums)

            def not_saved():
                b.append_variable(
                    'Not Saved', b.text('! not saved to Photos: ', photo_name)
                )

            b.if_has_value(saved, when_saved, not_saved)

        b.repeat_each(lines, per_file)

    b.set_variable('Saved', b.text('0'))
    b.if_has_value(b.match_text(result, r'\|'), save_results, lambda: None)
    b.if_has_value(
        variable('Saved Photos'),
        lambda: b.set_variable('Saved', b.count(variable('Saved Photos'))),
        lambda: None,
    )
    # The log: shown when it has a note, an error, a failed photo or a copy
    # that didn't reach Photos (what the iPhone user reads in a-Shell).
    log = b.text(
        b.run_shell_script(
            f'cat {LOG_DIR}/{ROUTES[WORK_PHOTOS]}.log 2>/dev/null || true'
        ),
        '\n',
        b.combine(variable('Not Saved'), '\n'),
    )
    b.if_has_value(
        b.match_text(log, WARNINGS), lambda: b.quick_look(log), lambda: None
    )
    outcome = b.text(
        'Saved ',
        variable('Saved'),
        ' photo(s) to Photos.\n',
        b.combine(variable('Not Saved'), '\n'),
    )
    b.run_shell_script(
        finish_script(WORK_PHOTOS), input_ref=outcome, as_arguments=False
    )
    b.if_has_value(
        variable('Collected'),
        lambda: b.notification(
            'JPEG XL',
            'Saved ',
            variable('Saved'),
            ' photo(s) to Photos. ',
            b.count(variable('Collected')),
            f' original(s) are in the album "{ORIGINALS_ALBUM}" for you to review.',
        ),
        lambda: b.notification(
            'JPEG XL', 'Saved ', variable('Saved'), ' photo(s) to Photos.'
        ),
    )


def build_files(sample):
    b = wf.Builder(sample)
    b.comment(
        f'{NAME_FILES} {VERSION}. '
        'Converts image files (HEIF, JPEG, PNG) to JPEG XL with jxlbatch (Run Shell '
        'Script), keeping their metadata. Select files or folders in Finder ▸ '
        'Quick Actions. Each .jxl is saved next to its original (never replacing a '
        'file); nothing is deleted, and Photos is not involved. Needs jxlbatch in '
        '~/.local/bin and Allow Running Scripts in Shortcuts ▸ Settings ▸ Advanced. '
        f'Setup and help: {HELP_URL}'
    )

    def no_input():
        b.notification(
            'JPEG XL',
            'Select files or folders in Finder, then run it from Quick Actions.',
        )
        b.stop()

    b.if_has_value(SHORTCUT_INPUT, lambda: None, no_input)
    quality = choose_quality(b)
    cores = choose_cores(b)
    hdr = choose_hdr(b)
    b.notification(
        'JPEG XL',
        'Converting ',
        b.count(SHORTCUT_INPUT),
        ' item(s)… A notification follows when the files are written.',
    )
    # Each input's real location, one per line in input order (an empty line
    # when Shortcuts doesn't know it), so the results land next to the
    # originals even when the script gets temporary copies.
    b.repeat_each(
        SHORTCUT_INPUT,
        lambda: b.append_variable(
            'Paths', b.text(b.file_details(REPEAT_ITEM, 'File Path'))
        ),
    )
    result = b.run_shell_script(
        *script(
            NAME_FILES,
            'files.zsh',
            'PATHS',
            WORK_FILES,
            quality,
            cores,
            hdr,
            b.combine(variable('Paths'), '\n'),
        ),
        input_ref=SHORTCUT_INPUT,
    )
    # The output is the log and, last, "Wrote N JPEG XL file(s)."
    b.if_has_value(
        b.match_text(result, WARNINGS),
        lambda: b.quick_look(result),
        lambda: None,
    )
    b.notification(
        'JPEG XL', b.item_from_list(b.split(result, '\n'), 'Last Item')
    )
    return b.actions


def photos_workflow(sample, actions):
    # The Share menu (Photos), and the photo picker when started elsewhere.
    return workflow(
        sample,
        NAME_PHOTOS,
        actions,
        share_sheet=True,
        types=['ActionExtension'],
        input_classes=['WFImageContentItem'],
    )


def files_workflow(sample, actions):
    # Finder's Quick Actions and the Services menu, with files and folders.
    return workflow(
        sample,
        NAME_FILES,
        actions,
        share_sheet=True,
        types=['ActionExtension', 'QuickActions'],
        input_classes=[
            'WFGenericFileContentItem',
            'WFImageContentItem',
            'WFFolderContentItem',
        ],
        quick_action_surfaces=['Finder', 'Services'],
    )


def write(name, workflow_dict, sign):
    wf.write(name, workflow_dict, sign, OUT, DIST)


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
        wf.fetch_sample(args.fetch, SAMPLE)

    if args.guess:
        sample = Sample(wf.guessed_workflow())
    elif not args.sample.exists():
        sys.exit(
            f'missing {args.sample}: run with --fetch <iCloud link of a sample shortcut>, or --guess'
        )
    else:
        sample = Sample(args.sample)

    write(
        NAME_PHOTOS,
        photos_workflow(sample, build_photos(sample)),
        not args.no_sign,
    )
    write(
        NAME_FILES,
        files_workflow(sample, build_files(sample)),
        not args.no_sign,
    )


if __name__ == '__main__':
    main()
