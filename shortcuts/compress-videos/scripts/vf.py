"""
The parts of the Compress Videos shortcut that are its own: the version and the
questions, HandBrake's choices for H.265 and AV1 with their titles and
descriptions, each one's default marked in its title. The generic builder (text
and variable encoding, built-in actions, writing and signing the file) is
lib/wfkit.py, shared with the other shortcuts and re-exported here.

Each question sets a variable to the first word of the chosen title (the codec
menu to its value), and scripts/mac/common.zsh turns the six into ffmpeg's
options.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
sys.path.insert(0, str(TOOL.parents[1] / 'lib'))

from wfkit import *  # noqa: E402, F401, F403

# Shared by the shortcut and vidmeta (and ffmpeg's version line); shown in the
# shortcut's first note.
VERSION = (TOOL / 'VERSION').read_text(encoding='utf-8').strip()

# Shortcuts can't preselect a choice, so the default is marked in its title.
DEFAULT_MARK = ' (default)'

# The questions, in the order they are asked. Menus show titles only; the
# lists with descriptions are contact cards (title, and the description in
# small grey text below it), as Compress Photos' quality list.
CODEC_PROMPT = 'Video codec'
CODECS = [  # (menu title, value)
    ('H.265 (x265): plays on every Apple device since 2017', 'h265'),
    (
        'AV1 (SVT-AV1): smaller files; plays on M3 Macs and iPhone 15 Pro or later',
        'av1',
    ),
]
PRESET_PROMPT = 'Preset'
PRESETS = {  # codec: [(preset, description)], fastest first
    'h265': [
        ('fast', 'Quickest, biggest file'),
        ('medium', "HandBrake's default"),
        ('slow', "Smallest file, about 2× medium's time"),
    ],
    'av1': [
        ('5', "SVT-AV1's and HandBrake's default"),
        ('4', 'Slower than 5, a little smaller'),
        ('3', 'Slower than 4, a little smaller'),
        ('2', 'Several times slower than 5; the smallest file'),
    ],
}
DEFAULT_PRESETS = {'h265': 'medium', 'av1': '5'}
TUNE_PROMPT = 'Tune'
TUNES = [  # (menu title, value); H.265 only: AV1 is always tuned for quality
    ('none', 'none'),
    (
        'grain: keeps film grain and fine noise instead of smoothing it; bigger files',
        'grain',
    ),
]
DEFAULT_TUNE = 'none'
RF_PROMPT = (
    'Quality (RF): lower is better and bigger; the numbers differ between '
    'x265 and SVT-AV1'
)
RF_VALUES = [19, 20, 21, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40]
DEFAULT_RFS = {'h265': 24, 'av1': 30}
SIZE_PROMPT = 'Largest size (the long edge; a video is never enlarged)'
SIZES = [  # (size, description)
    ('4K', '3840 px: 3840×2160, or 2160×3840 vertical'),
    ('2K', '2560 px: 2560×1440, or 1440×2560 vertical'),
    ('1080p', '1920 px: 1920×1080, or 1080×1920 vertical'),
    ('720p', '1280 px: 1280×720, or 720×1280 vertical'),
]
DEFAULT_SIZE = '2K'
AUDIO_PROMPT = 'Audio (Opus)'
AUDIO_KBPS = [  # (kbit/s, description)
    (64, 'Very good'),
    (96, 'Near transparent'),
    (128, 'Often transparent'),
    (160, 'Essentially transparent'),
    (192, 'Really transparent'),
    (256, 'Placebo'),
]
DEFAULT_AUDIO = 160
# The menu shown when the last run's settings are known.
SAME_TITLE = 'Same as last time'
SAME_DESCRIPTION = 'The settings of the last conversion'
CHOOSE_TITLE = 'Choose…'
CHOOSE_DESCRIPTION = 'Codec, preset, tune, RF, size and audio'


def titled(value, default):
    """A choice's title: its value, marked when it is the default."""
    return f'{value}{DEFAULT_MARK}' if value == default else str(value)


def vcard_escape(value):
    return value.replace('\\', '\\\\').replace(';', '\\;')


def vcard(title, description):
    """
    One contact card, as text parts: ``title`` and ``description`` are lists of
    strings and variables (a variable's text is inserted as it is).
    """

    def escaped(parts):
        return [vcard_escape(p) if isinstance(p, str) else p for p in parts]

    return [
        'BEGIN:VCARD\nVERSION:3.0\nN;CHARSET=utf-8:',  # 3.0 for Unicode
        *escaped(title),
        '\nORG;CHARSET=utf-8:',
        *escaped(description),
        '\nEND:VCARD',
    ]


def choose_card(b, prompt, cards, file_name):
    """
    Shows ``cards`` (text parts, see vcard) as a list and returns the chosen
    card's title. Menus in Shortcuts show only a title, so a list with
    descriptions is a list of contact cards (a well-known Shortcuts technique):
    the name is the title, the company the grey text below it.
    """
    parts = []
    for i, card in enumerate(cards):
        parts += (['\n'] if i else []) + card

    cards_file = b.set_name(b.text(*parts), file_name)
    chosen = b.choose_from_list(b.contacts_from_input(cards_file), prompt)
    return b.get_name(chosen)


def first_word(b, ref):
    """The first word of a title: "medium (default)" -> "medium"."""
    return b.match_text(ref, r'^\S+')


def choose_preset(b, codec):
    cards = [
        vcard([titled(preset, DEFAULT_PRESETS[codec])], [description])
        for preset, description in PRESETS[codec]
    ]
    title = choose_card(b, PRESET_PROMPT, cards, f'preset-{codec}.vcf')
    b.set_variable('Preset', first_word(b, title))


def choose_tune(b):
    def choose(value):
        return lambda: b.set_variable('Tune', b.text(value))

    b.choose_from_menu(
        TUNE_PROMPT,
        {titled(title, DEFAULT_TUNE): choose(value) for title, value in TUNES},
    )


def choose_rf(b, codec):
    """A plain list, one number per row."""
    rows = '\n'.join(titled(rf, DEFAULT_RFS[codec]) for rf in RF_VALUES)
    chosen = b.choose_from_list(b.split(b.text(rows), '\n'), RF_PROMPT)
    b.set_variable('RF', first_word(b, chosen))


def choose_size(b):
    cards = [
        vcard([titled(size, DEFAULT_SIZE)], [description])
        for size, description in SIZES
    ]
    title = choose_card(b, SIZE_PROMPT, cards, 'size.vcf')
    b.set_variable('Size', first_word(b, title))


def choose_audio(b):
    cards = [
        vcard([titled(f'{kbps} kbps', f'{DEFAULT_AUDIO} kbps')], [description])
        for kbps, description in AUDIO_KBPS
    ]
    title = choose_card(b, AUDIO_PROMPT, cards, 'audio.vcf')
    b.set_variable('Audio', first_word(b, title))


def ask_settings(b):
    """
    The six questions, in order: codec (a menu), preset (cards, per codec),
    tune (a menu; H.265 only), RF (a list; its default per codec), largest size
    (cards), audio (cards). Each answer is a variable: Codec, Preset, Tune, RF,
    Size, Audio.
    """

    def codec(value):
        def body():
            b.set_variable('Codec', b.text(value))
            choose_preset(b, value)
            if value == 'h265':
                choose_tune(b)

            choose_rf(b, value)

        return body

    b.choose_from_menu(
        CODEC_PROMPT, {title: codec(value) for title, value in CODECS}
    )
    choose_size(b)
    choose_audio(b)


def settings(b, last_summary):
    """
    The settings: when the last run's are known (``last_summary``, its text,
    has a value), a list offers them ("Same as last time", the settings in the
    title) or the six questions; the variable Reuse is "1" when they are
    reused, and the script then reads them itself (common.zsh).
    """

    def offer():
        cards = [
            vcard([SAME_TITLE + ': ', last_summary], [SAME_DESCRIPTION]),
            vcard([CHOOSE_TITLE], [CHOOSE_DESCRIPTION]),
        ]
        title = choose_card(b, 'Settings', cards, 'settings.vcf')
        b.if_has_value(
            b.match_text(title, f'^{SAME_TITLE}'),
            lambda: b.set_variable('Reuse', b.text('1')),
            lambda: None,
        )

    b.if_has_value(last_summary, offer, lambda: None)
    b.if_has_value(variable('Reuse'), lambda: None, lambda: ask_settings(b))
