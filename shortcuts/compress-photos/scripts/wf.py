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
        93,
        'Placebo: no visible difference from the original, even in the sunset sky; files about 40% larger than at 88, and can be larger than the original',
    ),
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

# The HEIC route's choices: x265's RF (CRF; lower is better and larger), as
# (rf, description). Measured on a 24 MP iPhone photo (testdata/heic-quality-2):
# RF 22 is the point where the user saw no difference from the original.
HEIC_PRESETS = [
    (
        22,
        'Placebo: no visible difference from the original, even in the sky; saves only about 15%',
    ),
    (
        24,
        'Almost placebo: very little visual degradation; about 70% of the original’s size',
    ),
    (
        26,
        'Go-to option for everyday scenes: smooth sky, film grain and fine texture kept; about 60% of the original',
    ),
    (
        28,
        'Details well preserved; the finest texture starts to soften; about half the original',
    ),
    (
        29,
        'Details well preserved; fine texture a little softer; about 45% of the original',
    ),
    (
        30,
        'Fine texture softens; tiny steps may show in a clear blue sky; about 40% of the original',
    ),
    (
        31,
        'Small losses in details; faint steps in blue sky; about 38% of the original',
    ),
    (
        32,
        'Small losses in details; visible banding in blue sky; about a third of the original',
    ),
    (
        34,
        'Visible losses in details; blotches in blue sky; about 30% of the original',
    ),
    (
        36,
        'More losses in details; bigger blotches; edges start to ring; about a quarter of the original',
    ),
    (38, 'Details get smudged; blocky sky; about 23% of the original'),
    (40, 'It’s like watching RMVB videos in 2002; about 20% of the original'),
]
DEFAULT_RF = 26

# The first question: the output format, as a menu whose cases set the
# variable Format to the value (what the shell reads) and ask that format's
# quality (choose_format).
FORMAT_PROMPT = 'Format'
FORMATS = [
    ('HEIC: Apple’s own format; HDR shows exactly as the original', 'heic'),
    (
        'JPEG XL: HDR copies can show pink patches in bright skies (an Apple issue)',
        'jxl',
    ),
]
# What each format is called in notifications.
FORMAT_NAMES = {'heic': 'HEIC', 'jxl': 'JPEG XL'}
# The notifications' title: the shortcut, since the format isn't known yet
# when the first ones are shown.
TITLE = 'Compress Photos'


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
        b.notification(TITLE, note)
        if not prefix:
            # The notification is gone as soon as a-Shell comes to the front,
            # so the shell prints the note too.
            b.set_variable('Skipped Echo', b.text('echo "', note, '"'))

    def nothing_left():
        # Skipped is empty when there were no items at all.
        b.if_has_value(
            variable('Skipped'),
            lambda: say_skipped('Nothing to convert. '),
            lambda: b.notification(TITLE, 'Nothing to convert.'),
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


# Each format's quality list: the presets, the default, the prompt and the
# contact-card file's name.
QUALITY_LISTS = {
    'jxl': (
        QUALITY_PRESETS,
        DEFAULT_QUALITY,
        'JPEG XL quality',
        'quality.vcf',
    ),
    'heic': (
        HEIC_PRESETS,
        DEFAULT_RF,
        'HEIC quality (RF: lower is better)',
        'quality-heic.vcf',
    ),
}


def choose_quality(b, fmt='jxl'):
    """
    Shows the format's presets (QUALITY_LISTS) as a list and sets the variable
    Quality to the chosen number; returns the variable.

    Menus in Shortcuts show only a title. So each preset is a contact card
    instead (a well-known Shortcuts technique): the name (N) is the title, and
    the company (ORG) is shown below it in small grey text. A variable, not
    Match Text's own output, because each format's list is in its own case of
    the Format menu (choose_format), and what follows reads one Quality.
    """
    presets, default, prompt, file_name = QUALITY_LISTS[fmt]
    cards = []
    for quality, description in presets:
        title = f'{quality} (default)' if quality == default else str(quality)
        cards.append(
            'BEGIN:VCARD\nVERSION:3.0\n'  # 3.0 for Unicode
            f'N;CHARSET=utf-8:{vcard_escape(title)}\n'
            f'ORG;CHARSET=utf-8:{vcard_escape(description)}\n'
            'END:VCARD'
        )

    cards_file = b.set_name(b.text('\n'.join(cards)), file_name)
    chosen = b.choose_from_list(b.contacts_from_input(cards_file), prompt)
    # The title's number: "83 (default)" -> "83".
    b.set_variable('Quality', b.match_text(b.get_name(chosen), r'\d+'))
    return variable('Quality')


def choose_format(b):
    """
    The first question, a menu of FORMATS: its cases set the variable Format to
    the chosen value ("heic" or "jxl") and ask that format's quality
    (choose_quality, the variable Quality). Returns (Format, Quality).
    """

    def case(value):
        def body():
            b.set_variable('Format', b.text(value))
            choose_quality(b, value)

        return body

    b.choose_from_menu(
        FORMAT_PROMPT, {title: case(value) for title, value in FORMATS}
    )
    return variable('Format'), variable('Quality')


def photo_date(b, photo, index):
    """
    Appends "index|date" to the variable Dates: ``photo``'s date in Photos (Get
    Details of Images ▸ Date Taken), formatted as ISO 8601 with the time
    (``b.format_date``), for jxlbatch's jxl_dates.txt. jxlbatch writes it into
    the JPEG XL's EXIF when the original's capture date is another moment or
    missing (a date changed in Photos, or an image whose app removed it), so
    the copy shows the date Photos shows for the original.

    For a library photo, Date Taken is the asset's creationDate (ContentKit's
    WFPhotoMediaContentItem, iOS 18.2: ``asset.creationDate``), which Photos'
    Adjust Date and Time changes; for an image from another app it is the
    file's own EXIF date (WFImageContentItem: ``dateTaken`` from the metadata),
    or nothing, and then no line. Match Text turns the Date into matches (its
    text) or none, for If, as with Is Favorite (see collect_in_album).
    """
    taken = b.photo_details(photo, 'Date Taken')
    b.if_has_value(
        b.match_text(taken, '.'),
        lambda: b.append_variable(
            'Dates', b.text(index, '|', b.format_date(taken))
        ),
        lambda: None,
    )


# The album the converted originals are collected in, on both platforms. The
# shortcuts never delete photos: the user reviews the album and deletes.
ORIGINALS_ALBUM = 'Compressed originals'
# The album's name before 0.7.0 (when JPEG XL was the only format): a copy
# must not land there either (copy_to_albums).
OLD_ORIGINALS_ALBUM = 'Compressed to JXL'
assert re.fullmatch(r'[\w ]+', ORIGINALS_ALBUM)  # used in a regex as is
assert re.fullmatch(r'[\w ]+', OLD_ORIGINALS_ALBUM)


def copy_to_albums(b, copy, albums):
    """
    Adds the saved ``copy`` to each album name in ``albums`` (the original's,
    from Get Details of Images ▸ Album) except ORIGINALS_ALBUM: an original
    converted once before is in that album, and a copy there could be deleted
    with the originals.
    """

    def per_album():
        b.if_has_value(
            b.match_text(
                REPEAT_ITEM_2, f'^({ORIGINALS_ALBUM}|{OLD_ORIGINALS_ALBUM})$'
            ),
            lambda: None,
            lambda: b.save_to_album(copy, REPEAT_ITEM_2),
        )

    b.repeat_each(albums, per_album)


def collect_in_album(b, photo, album, albums=None):
    """
    Adds the library photo ``photo`` to ``album`` (a text ref holding
    ORIGINALS_ALBUM) unless it is already in it, and appends it to the variable
    Collected. ``albums``: the photo's album names if already read (Get Details
    of Images ▸ Album), else they are read here.

    Only a photo from the library is collected: an image shared from another
    app (Files) isn't in the library, and Save to Photo Album would import it
    as a new photo. Get Details of Images ▸ Is Favorite tells them apart: a
    library photo answers Yes or No, a file answers nothing (checked on iOS 26,
    2026-10-06, with a diagnostic shortcut); the Boolean goes through Match
    Text, since If can't test it for a value.

    Save to Photo Album adds a photo that is already in the library to the
    album as it is (no copy) when it isn't in that album yet; one that is would
    be saved again as a copy, hence the album check (one album name per line).
    Checked from Photos' share sheet on iOS 26 with a diagnostic shortcut
    (2026-10-06): no copies, and the one-time permission prompt works there
    too.
    """

    def collect():
        nonlocal albums
        if albums is None:
            albums = b.photo_albums(photo)

        already = b.match_text(albums, f'(^|\\n){ORIGINALS_ALBUM}($|\\n)')

        def add():
            b.save_to_album(photo, album)
            b.append_variable('Collected', photo)

        b.if_has_value(already, lambda: None, add)

    # Is Favorite is a Boolean, for which If offers no "has any value"
    # ("Please choose a value for each parameter in this action"): Match Text
    # turns it into matches (any text at all, "Yes" or "No" in any language)
    # or none.
    in_library = b.match_text(b.photo_details(photo, 'Is Favorite'), '.')
    b.if_has_value(in_library, collect, lambda: None)
