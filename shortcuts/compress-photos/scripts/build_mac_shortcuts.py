#!/usr/bin/env python3
"""
Generates the two Mac shortcuts as signed .shortcut files.

- "Compress Photos (macOS)": photos from the Photos library (the Share menu in
  Photos, or a photo picker when started any other way) → JPEG XL copies in
  Photos, in the same albums, with the option to delete the originals.
- "Compress Photo Files (macOS)": image files or folders from Finder (Quick
  Actions) → .jxl files next to the originals.

Both run jxlbatch (the native macOS build, dist/jxlbatch-macos, installed as
~/.local/bin/jxlbatch) through Shortcuts' Run Shell Script action, which waits
for the script, so there is no a-Shell, no helper shortcut and no handoff. The
shell script is in ``SCRIPT_*`` below; tests/compress-photos/test_mac_script.py
runs it for real. See ../README-mac.md and ../DEVELOPING.md.

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
    REPEAT_ITEM,
    REPEAT_ITEM_2,
    SHORTCUT_INPUT,
    VERSION,
    Sample,
    choose_quality,
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
# The work folder: one per user, in the user's temporary folder (TMPDIR ends
# with a slash on macOS). Fixed, so that the shortcut's later steps can find
# the log and the results without parsing the script's output.
# Compress Photos (macOS): a folder inside Shortcuts' own folder in iCloud
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
# Where the file shortcut saves when it can't write next to the original.
FALLBACK_FOLDER = '"$HOME/Pictures/JPEG XL"'
# A log line worth showing: jxlbatch's "!" notes, errors, failed photos.
WARNINGS = r'(^|\n) *(!|ERROR|[0-9]+ failed)'

# ---------------------------------------------------------------------------
# The shell script (zsh): scripts/mac/*.zsh, with @PLACEHOLDERS@

MAC = HERE / 'mac'
# The placeholders that become Shortcuts variables, and the variable each one
# is in the shortcut: the chosen quality (Match Text's Matches), the lines of
# NAMES or PATHS (Combine Text), and Skipped Echo (an echo of what the
# shortcut skipped; empty when nothing was, which leaves ">> $LOG" alone, a
# command that only touches the log).
SLOTS = {
    '@QUALITY@': 'Matches',
    '@LINES@': 'Combined Text',
    '@SKIPPED@': 'Skipped Echo',
}


def work_setup(work):
    """
    The script lines that set WORK. For the Photos shortcut they also note,
    before the folder is created, whether Shortcuts' iCloud Drive folder is
    missing (iCloud Drive off for Shortcuts): Get File then finds nothing and
    the shortcut reports every photo as not saved.
    """
    if work != WORK_PHOTOS:
        return f'WORK={work}'

    return (
        f"icloud_missing=''\n"
        f'[ -d {SHORTCUTS_FOLDER} ] || icloud_missing=1\n'
        f'WORK={work}'
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
    The script as one text with the three @SLOTS@ still in it: common.zsh, then
    ``body`` (photos.zsh or files.zsh) with run.zsh at its @RUN@.
    """
    text = (MAC / 'common.zsh').read_text() + (MAC / body).read_text()
    text = text.replace('@RUN@\n', (MAC / 'run.zsh').read_text())
    for placeholder, value in {
        '@NAME@': name,
        '@VERSION@': VERSION,
        '@HELP_URL@': HELP_URL,
        '@EFFORT@': str(EFFORT),
        '@WORK_SETUP@': work_setup(work),
        '@WORK_CHECK@': work_check(work),
        '@FALLBACK@': FALLBACK_FOLDER,
        '@LABEL@': label,
        '@CANDIDATES@': ' '.join(f'"{p}"' for p in ENCODER_PATHS),
        '@LOOKED@': ', '.join(p.replace('$HOME', '~') for p in ENCODER_PATHS),
    }.items():
        text = text.replace(placeholder, value)

    left = [s for s in re.findall('@[A-Z_]+@', text) if s not in SLOTS]
    assert not left, f'unknown placeholders: {left}'
    return text


def script(name, body, label, work, quality, lines):
    """The Run Shell Script text parts: strings and the three variables."""
    refs = {
        '@QUALITY@': quality,
        '@LINES@': lines,
        '@SKIPPED@': variable('Skipped Echo'),
    }
    parts = []
    for piece in re.split(
        '(@QUALITY@|@LINES@|@SKIPPED@)',
        script_text(name, body, label, work),
    ):
        if piece in refs:
            parts.append(refs[piece])
        elif piece:
            parts.append(piece)

    return parts


# ---------------------------------------------------------------------------
# The two shortcuts


def build_photos(sample):
    b = wf.Builder(sample)
    b.comment(
        f'{NAME_PHOTOS} {VERSION}. '
        'Converts photos to JPEG XL with jxlbatch (Run Shell Script), keeping their '
        'metadata. Only still photos are converted: Live Photos and videos are '
        'skipped. From the Share menu in Photos or from a photo picker, it saves the '
        "JPEG XL copies to Photos, adds each to its original's albums, and offers to "
        'delete the originals (those whose JPEG XL has everything they have). Needs '
        'jxlbatch in ~/.local/bin and Allow Running Scripts in Shortcuts ▸ Settings ▸ '
        f'Advanced. Setup and help: {HELP_URL}'
    )
    b.if_has_value(
        SHORTCUT_INPUT,
        lambda: b.set_variable('Photos', SHORTCUT_INPUT),
        lambda: b.set_variable('Photos', b.select_photos()),
    )
    # From here on only the still photos: their positions in Stills are the
    # job indices, also when saving the results.
    photos = keep_still_photos(b, variable('Photos'))
    quality = choose_quality(b)
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
            b.combine(variable('Names'), '\n'),
        ),
        input_ref=photos,
    )

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

            # Only a photo that is in Photos now counts, joins its original's
            # albums, and lets the original be offered for deletion: a save
            # that produced nothing (for example because the file could not
            # be read) must never lead to a deletion.
            def when_saved():
                b.append_variable('Saved Photos', saved)
                index = b.item_at_index(parts, 2)
                original = b.item_at_index(photos, index)
                # "keep" means the JPEG XL lacks the original's HDR.
                delete = b.match_text(b.item_at_index(parts, 3), '^delete$')
                b.if_has_value(
                    delete,
                    lambda: b.append_variable('Converted', original),
                    lambda: None,
                )
                b.repeat_each(
                    b.photo_albums(original),
                    lambda: b.save_to_album(saved, REPEAT_ITEM_2),
                )

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
    # The log: shown when it has a note, an error or a failed photo (what the
    # iPhone user reads in a-Shell), before the originals can be deleted.
    log = b.text(
        b.run_shell_script(
            f'cat {WORK_PHOTOS}/jxl_log.txt 2>/dev/null || true'
        ),
        '\n',
        b.combine(variable('Not Saved'), '\n'),
    )
    b.if_has_value(
        b.match_text(log, WARNINGS), lambda: b.quick_look(log), lambda: None
    )
    b.run_shell_script(f'rm -rf {WORK_PHOTOS}')
    b.notification(
        'JPEG XL', 'Saved ', variable('Saved'), ' photo(s) to Photos.'
    )
    # Empty when nothing was converted or every original is kept. macOS asks
    # to confirm, and the photos go to Recently Deleted.
    b.if_has_value(
        variable('Converted'),
        lambda: b.delete_photos(variable('Converted')),
        lambda: None,
    )
    return b.actions


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
