"""
The parts of the Compress Photos shortcuts that both platforms share.

Used by build_shortcuts.py (the iPhone shortcuts, with a-Shell) and
build_mac_shortcuts.py (the Mac shortcuts, with Run Shell Script): the quality
presets and their contact-card list, and the still-photo filter. The generic
builder (text and variable encoding, built-in actions, writing and signing the
file) is lib/wfkit.py, shared with the other shortcuts and re-exported here.
"""

import re
import sys
from pathlib import Path

# the repository's lib/, with the generic builder
_LIB = str(Path(__file__).resolve().parents[3] / 'lib')
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from wfkit import *  # noqa: E402, F401, F403

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
# Shared by the shortcuts and jxlbatch; shown in each shortcut's first note.
VERSION = (TOOL / 'VERSION').read_text(encoding='utf-8').strip()
EFFORT = 7
HELP_URL = 'https://github.com/jsh9/photo-video-shortcuts/tree/main/shortcuts/compress-photos'

# The quality choices offered, as (quality, description). Shortcuts can't
# preselect a choice, so the default is marked in its title.
QUALITY_PRESETS = [
    (
        88,
        'Almost placebo: very little visual degradation (even the most challenging scene, the sunset sky, can be rendered very well)',
    ),
    (
        83,
        'Go-to option for everyday scenes (almost perfect blue sky); film grains well preserved',
    ),
    (
        72,
        'Details well preserved, but tiny color banding in blue sky; film grains start to get affected',
    ),
    (63, 'Details well preserved; a bit more color banding in blue sky'),
    (52, 'Small losses in details; more color banding in blue sky'),
    (40, 'Visible losses in details; color blotches in blue sky'),
    (30, 'More losses in details; bigger color blotches in blue sky'),
    (20, 'Details get smudged; color artifacts in blue sky'),
    (10, 'It’s like watching RMVB videos in 2002'),
    (5, 'It’s like watching bad RMVB videos in 2002'),
]
DEFAULT_QUALITY = 83


# ---------------------------------------------------------------------------
# Shared parts of the shortcuts


# The variables collecting each kind of skipped item, and what the
# notification calls them.
SKIPPED = [
    ('Skipped Live Photos', 'Live Photo(s)'),
    ('Skipped Videos', 'video(s)'),
]


def keep_still_photos(b, photos):
    """
    Returns the variable Stills: the still photos (screenshots included) among
    ``photos``, as they are, to convert.

    Live Photos and videos are skipped, and a notification counts each kind. If
    nothing is left, the shortcut stops there, before asking for a quality.

    Each item is sorted by its own details, which Get Details of Images reads
    in memory from the item, and the item itself is kept (the share sheet's
    files, so its Send As choice): Media Type is Image (for a Live Photo too),
    Video or Audio; Photo Type is a list (HDR, Panorama, Burst, Live Photo),
    empty for a plain still photo or a screenshot, so it is only read when it
    has a value, and a list put into Match Text's text is one entry per line.
    An item whose Media Type is unknown is converted, as before 0.3.0. An image
    that isn't in the photo library (shared from Files, say) says Image with no
    Photo Type, so it is converted too.

    Not Filter Photos, which 0.3.0 used and which failed on every photo: with
    photos from the library as input, Shortcuts turns a Photo Type condition
    into a Photos-framework predicate on the key ``mediaSubtype``, which
    PHAsset objects don't answer, and evaluates it on the input in memory, so
    the action throws (NSUnknownKeyException) and the shortcut dies; and with
    an item that isn't in the library, it searches the whole library instead of
    testing the item.

    The variable Skipped Echo is set to an ``echo`` command of the
    notification's text when something was skipped, for the shell (a-Shell or
    zsh) to repeat it in its output.
    """

    def add_to(name):
        return lambda: b.append_variable(name, REPEAT_ITEM)

    def per_item():
        media = b.photo_details(REPEAT_ITEM, 'Media Type')

        def by_media_type():
            image = b.match_text(media, '^Image$')
            b.if_has_value(image, by_photo_type, add_to('Skipped Videos'))

        def by_photo_type():
            types = b.photo_details(REPEAT_ITEM, 'Photo Type')

            def by_live_photo():
                live = b.match_text(types, 'Live Photo')
                b.if_has_value(
                    live, add_to('Skipped Live Photos'), add_to('Stills')
                )

            b.if_has_value(types, by_live_photo, add_to('Stills'))

        b.if_has_value(media, by_media_type, add_to('Stills'))

    b.repeat_each(photos, per_item)

    # "2 Live Photo(s), 1 video(s)": an entry for each kind of item skipped.
    def count(name, kind):
        return lambda: b.append_variable(
            'Skipped', b.text(b.count(variable(name)), ' ', kind)
        )

    for name, kind in SKIPPED:
        b.if_has_value(variable(name), count(name, kind), lambda: None)

    def say_skipped(prefix=''):
        note = b.text(
            f'{prefix}Skipped ',
            b.combine(variable('Skipped'), ', '),
            ': only still photos are converted.',
        )
        b.notification('JPEG XL', note)
        if not prefix:
            # The notification is gone as soon as a-Shell comes to the front,
            # so the shell prints the note too.
            b.set_variable('Skipped Echo', b.text('echo "', note, '"'))

    def nothing_left():
        # Skipped is empty when there were no items at all.
        b.if_has_value(
            variable('Skipped'),
            lambda: say_skipped('Nothing to convert. '),
            lambda: b.notification('JPEG XL', 'Nothing to convert.'),
        )
        b.stop()

    b.if_has_value(
        variable('Stills'),
        lambda: b.if_has_value(variable('Skipped'), say_skipped, lambda: None),
        nothing_left,
    )
    return variable('Stills')


def vcard_escape(value):
    return value.replace('\\', '\\\\').replace(';', '\\;')


def choose_quality(b):
    """
    Shows QUALITY_PRESETS as a list and returns the chosen quality.

    Menus in Shortcuts show only a title. So each preset is a contact card
    instead (a well-known Shortcuts technique): the name (N) is the title, and
    the company (ORG) is shown below it in small grey text.
    """
    cards = []
    for quality, description in QUALITY_PRESETS:
        title = (
            f'{quality} (default)'
            if quality == DEFAULT_QUALITY
            else str(quality)
        )
        cards.append(
            'BEGIN:VCARD\nVERSION:3.0\n'  # 3.0 for Unicode
            f'N;CHARSET=utf-8:{vcard_escape(title)}\n'
            f'ORG;CHARSET=utf-8:{vcard_escape(description)}\n'
            'END:VCARD'
        )

    cards_file = b.set_name(b.text('\n'.join(cards)), 'quality.vcf')
    chosen = b.choose_from_list(
        b.contacts_from_input(cards_file), 'JPEG XL quality'
    )
    # The title's number: "83 (default)" -> "83".
    return b.match_text(b.get_name(chosen), r'\d+')


# The album the converted originals are collected in, on both platforms. The
# shortcuts never delete photos: the user reviews the album and deletes.
ORIGINALS_ALBUM = 'Compressed to JXL'
assert re.fullmatch(r'[\w ]+', ORIGINALS_ALBUM)  # used in a regex as is


def copy_to_albums(b, copy, albums):
    """
    Adds the saved ``copy`` to each album name in ``albums`` (the original's,
    from Get Details of Images ▸ Album) except ORIGINALS_ALBUM: an original
    converted once before is in that album, and a copy there could be deleted
    with the originals.
    """

    def per_album():
        b.if_has_value(
            b.match_text(REPEAT_ITEM_2, f'^{ORIGINALS_ALBUM}$'),
            lambda: None,
            lambda: b.save_to_album(copy, REPEAT_ITEM_2),
        )

    b.repeat_each(albums, per_album)


def collect_in_album(b, photo, album):
    """
    Adds the library photo ``photo`` to ``album`` (a text ref holding
    ORIGINALS_ALBUM) unless it is already in it, and appends it to the variable
    Collected.

    Save to Photo Album adds a photo that is already in the library to the
    album as it is (no copy) when it isn't in that album yet; one that is would
    be saved again as a copy, hence the check (Get Details of Images ▸ Album,
    one album name per line). Checked from Photos' share sheet on iOS 26 with a
    diagnostic shortcut (2026-10-06): no copies, and the one-time permission
    prompt works there too.
    """
    already = b.match_text(
        b.photo_albums(photo), f'(^|\\n){ORIGINALS_ALBUM}($|\\n)'
    )

    def add():
        b.save_to_album(photo, album)
        b.append_variable('Collected', photo)

    b.if_has_value(already, lambda: None, add)
