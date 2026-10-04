#!/usr/bin/env python3
"""
Generates the two iPhone shortcuts as signed .shortcut files.

- "Compress Photos": share-sheet shortcut that stages the still photos in
  a-Shell (Live Photos and videos are skipped) and runs jxlbatch (see
  ../README.md).
- "JXL-Import": started by a-Shell when encoding is done; saves the JXL files
  to Photos and cleans up.

a-Shell's actions (and a few built-in ones whose parameter names vary between
iOS versions) are copied from a real shortcut built on the iPhone and fetched
through its iCloud link: scripts/sample/JXL Sample.plist (see --fetch). If the
sample lacks one of those actions, the script stops with an error instead of
writing a shortcut that won't work.

Usage::

    build_shortcuts.py --guess [--no-sign]
    build_shortcuts.py --fetch https://www.icloud.com/shortcuts/<id>
    build_shortcuts.py [--no-sign]
"""

import argparse
import copy
import json
import plistlib
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / 'sample' / 'JXL Sample.plist'
DIST = HERE.parent / 'dist'
OUT = HERE.parent / 'build' / 'shortcuts'
# Shared by the shortcuts and jxlbatch; shown in each shortcut's first note.
VERSION = (HERE.parent / 'VERSION').read_text(encoding='utf-8').strip()

NAME_A = 'Compress Photos'
NAME_B = (
    'JXL-Import'  # a-Shell starts it by name; no spaces, so no URL escaping
)
EFFORT = 7
OBJ = '￼'  # placeholder for a variable inside a text field

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
# Sample handling


def fetch_sample(link):
    record_id = link.rstrip('/').split('/')[-1]
    api = f'https://www.icloud.com/shortcuts/api/records/{record_id}'
    with urllib.request.urlopen(api) as resp:
        record = json.load(resp)

    url = record['fields']['shortcut']['value']['downloadURL']
    with urllib.request.urlopen(url) as resp:
        data = resp.read()

    workflow = plistlib.loads(data)
    SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    with open(SAMPLE, 'wb') as f:
        plistlib.dump(workflow, f, fmt=plistlib.FMT_XML)

    print(f'saved {SAMPLE}')


class Sample:
    def __init__(self, source):
        if isinstance(source, dict):
            self.workflow = source
        else:
            with open(source, 'rb') as f:
                self.workflow = plistlib.load(f)

        self.actions = self.workflow['WFWorkflowActions']

    def template(self, suffix):
        """First sample action whose identifier ends with ``suffix``."""
        for a in self.actions:
            if a['WFWorkflowActionIdentifier'].endswith(suffix):
                return copy.deepcopy(a)

        sys.exit(f'the sample shortcut has no action ending in "{suffix}"')


# a-Shell's app ID (a-Shell.xcodeproj).
ASHELL_BUNDLE_ID = 'AsheKube.app.a-Shell'


def guessed_workflow():
    """
    Hand-written templates for --guess, used when no real sample exists.

    a-Shell's actions are stored as "AsheKube.app.a-Shell.<Intent>" with only
    their own parameters (names from a-Shell's
    Base.lproj/Intents.intentdefinition), as in shortcuts shared in a-Shell's
    GitHub issues (#74, #279, #311, #423, #439, #546). Adding an
    IntentAppDefinition block makes them "Unknown Action".
    """

    def action(identifier, params):
        return {
            'WFWorkflowActionIdentifier': identifier,
            'WFWorkflowActionParameters': params,
        }

    def ashell(intent, params):
        return action(
            f'{ASHELL_BUNDLE_ID}.{intent}', {'ShowWhenRun': False, **params}
        )

    return {
        'WFWorkflowClientVersion': '3514.0.4',
        'WFWorkflowMinimumClientVersion': 900,
        'WFWorkflowMinimumClientVersionString': '900',
        'WFWorkflowIcon': {
            'WFWorkflowIconStartColor': 4282601983,
            'WFWorkflowIconGlyphNumber': 59511,
        },
        'WFWorkflowOutputContentItemClasses': [],
        'WFWorkflowTypes': ['ActionExtension'],
        'WFWorkflowInputContentItemClasses': ['WFImageContentItem'],
        'WFWorkflowNoInputBehavior': {
            'Name': 'WFWorkflowNoInputBehaviorAskForInput',
            'Parameters': {'ItemClass': 'WFPhotoMediaContentItem'},
        },
        'WFWorkflowActions': [
            action('is.workflow.actions.setitemname', {}),
            action('is.workflow.actions.savetocameraroll', {}),
            ashell('PutFileIntent', {}),
            ashell('GetFileIntent', {}),
            ashell(
                'ExecuteCommandIntent', {'command': 'ls', 'Show-command': True}
            ),
        ],
    }


# ---------------------------------------------------------------------------
# Variables and text


def new_uuid():
    return str(uuid.uuid4()).upper()


class Ref:
    """A reference to a variable or to an earlier action's output."""

    def __init__(self, value):
        self.value = value


def output_of(action, name):
    return Ref({
        'Type': 'ActionOutput',
        'OutputUUID': action['WFWorkflowActionParameters']['UUID'],
        'OutputName': name,
    })


def variable(name):
    return Ref({'Type': 'Variable', 'VariableName': name})


SHORTCUT_INPUT = Ref({'Type': 'ExtensionInput'})
REPEAT_ITEM = variable('Repeat Item')
REPEAT_ITEM_2 = variable('Repeat Item 2')  # item of a repeat inside a repeat
REPEAT_INDEX = variable('Repeat Index')


def attachment(ref):
    return {'Value': ref.value, 'WFSerializationType': 'WFTextTokenAttachment'}


def text(*parts):
    """Text field mixing literal strings and variables."""
    string, attachments = '', {}
    for part in parts:
        if isinstance(part, Ref):
            pos = len(string.encode('utf-16-le')) // 2
            attachments[f'{{{pos}, 1}}'] = part.value
            string += OBJ
        else:
            string += part

    value = {'string': string}
    if attachments:
        value['attachmentsByRange'] = attachments

    return {'Value': value, 'WFSerializationType': 'WFTextTokenString'}


def plain_or_text(*parts):
    """A plain string when there are no variables, else a text field."""
    if all(isinstance(p, str) for p in parts):
        return ''.join(parts)

    return text(*parts)


# ---------------------------------------------------------------------------
# Actions


class Builder:
    def __init__(self, sample):
        self.sample = sample
        self.actions = []

    def add(self, identifier_or_template, params):
        if isinstance(identifier_or_template, dict):
            action = identifier_or_template
            action['WFWorkflowActionParameters'].update(params)
        else:
            action = {
                'WFWorkflowActionIdentifier': identifier_or_template,
                'WFWorkflowActionParameters': dict(params),
            }

        action['WFWorkflowActionParameters']['UUID'] = new_uuid()
        self.actions.append(action)
        return action

    # built-in actions with stable, well-known parameters
    def comment(self, body):
        return self.add(
            'is.workflow.actions.comment', {'WFCommentActionText': body}
        )

    def get_name(self, ref):
        return output_of(
            self.add(
                'is.workflow.actions.getitemname', {'WFInput': attachment(ref)}
            ),
            'Name',
        )

    def text(self, *parts):
        return output_of(
            self.add(
                'is.workflow.actions.gettext',
                {'WFTextActionText': text(*parts)},
            ),
            'Text',
        )

    def append_variable(self, name, ref):
        self.add(
            'is.workflow.actions.appendvariable',
            {'WFVariableName': name, 'WFInput': attachment(ref)},
        )

    @staticmethod
    def separator_params(ref, separator):
        """Parameters shared by Combine Text and Split Text."""
        params = {'text': attachment(ref)}
        if separator == '\n':
            params['WFTextSeparator'] = 'New Lines'
        else:
            params.update({
                'WFTextSeparator': 'Custom',
                'WFTextCustomSeparator': separator,
            })

        return params

    def combine(self, ref, separator):
        return output_of(
            self.add(
                'is.workflow.actions.text.combine',
                self.separator_params(ref, separator),
            ),
            'Combined Text',
        )

    def split(self, ref, separator):
        return output_of(
            self.add(
                'is.workflow.actions.text.split',
                self.separator_params(ref, separator),
            ),
            'Split Text',
        )

    def item_from_list(self, ref, which):
        a = self.add(
            'is.workflow.actions.getitemfromlist',
            {'WFInput': attachment(ref), 'WFItemSpecifier': which},
        )
        return output_of(a, 'Item from List')

    def text_from_input(self, ref):
        return output_of(
            self.add(
                'is.workflow.actions.detect.text', {'WFInput': attachment(ref)}
            ),
            'Text',
        )

    def count(self, ref):
        return output_of(
            self.add(
                'is.workflow.actions.count',
                {'Input': attachment(ref), 'WFCountType': 'Items'},
            ),
            'Count',
        )

    def notification(self, title, *body):
        self.add(
            'is.workflow.actions.notification',
            {
                'WFNotificationActionTitle': title,
                'WFNotificationActionBody': text(*body),
            },
        )

    def repeat_each(self, ref, body):
        group = new_uuid()
        self.actions.append({
            'WFWorkflowActionIdentifier': 'is.workflow.actions.repeat.each',
            'WFWorkflowActionParameters': {
                'GroupingIdentifier': group,
                'WFControlFlowMode': 0,
                'WFInput': attachment(ref),
            },
        })
        body()
        end = {
            'WFWorkflowActionIdentifier': 'is.workflow.actions.repeat.each',
            'WFWorkflowActionParameters': {
                'GroupingIdentifier': group,
                'WFControlFlowMode': 2,
                'UUID': new_uuid(),
            },
        }
        self.actions.append(end)
        return output_of(end, 'Repeat Results')

    # If/Otherwise with the "has any value" condition (code 100). Format as
    # written by Cherri (github.com/electrikmilk/cherri, shortcutgen.go).
    def if_has_value(self, ref, then, otherwise):
        group = new_uuid()

        def mark(mode, extra):
            self.actions.append({
                'WFWorkflowActionIdentifier': 'is.workflow.actions.conditional',
                'WFWorkflowActionParameters': {
                    'GroupingIdentifier': group,
                    'WFControlFlowMode': mode,
                    **extra,
                },
            })

        mark(
            0,
            {
                'WFCondition': 100,
                'WFInput': {'Type': 'Variable', 'Variable': attachment(ref)},
            },
        )
        then()
        mark(1, {})
        otherwise()
        mark(2, {'UUID': new_uuid()})

    def set_variable(self, name, ref):
        self.add(
            'is.workflow.actions.setvariable',
            {'WFVariableName': name, 'WFInput': attachment(ref)},
        )

    def select_photos(self):
        # Images only: the picker hides videos (Live Photos are images).
        a = self.add(
            'is.workflow.actions.selectphoto',
            {'WFSelectMultiplePhotos': True, 'WFPhotoPickerTypes': ['Images']},
        )
        return output_of(a, 'Photos')

    def stop(self):
        self.add('is.workflow.actions.exit', {})

    def item_at_index(self, list_ref, index_ref):
        a = self.add(
            'is.workflow.actions.getitemfromlist',
            {
                'WFInput': attachment(list_ref),
                'WFItemSpecifier': 'Item At Index',
                'WFItemIndex': index_ref
                if isinstance(index_ref, int)
                else attachment(index_ref),
            },
        )
        return output_of(a, 'Item from List')

    def wait_to_return(self):
        self.add('is.workflow.actions.waittoreturn', {})

    def delete_photos(self, ref):
        # iOS always asks the user to confirm before photos are deleted.
        self.add(
            'is.workflow.actions.deletephotos', {'photos': attachment(ref)}
        )

    def photo_details(self, ref, name):
        """
        Get Details of Images: the property ``name`` of ``ref``.

        Shortcuts reads it in memory from the item itself (a photo from the
        library answers with its asset's details); nothing is looked up in the
        photo library. Format from a shortcut built on the iPhone (Album). The
        property names are Shortcuts' own English names, whatever the phone's
        language, and the output is named after the property.
        """
        a = self.add(
            'is.workflow.actions.properties.images',
            {'WFContentItemPropertyName': name, 'WFInput': attachment(ref)},
        )
        return output_of(a, name)

    # Albums: saving an already saved photo (Saved Photo Media) to an album
    # adds it there; it doesn't make another copy.
    def photo_albums(self, ref):
        return self.photo_details(ref, 'Album')

    def contacts_from_input(self, ref):
        a = self.add(
            'is.workflow.actions.detect.contacts', {'WFInput': attachment(ref)}
        )
        return output_of(a, 'Contacts')

    def choose_from_list(self, ref, prompt):
        a = self.add(
            'is.workflow.actions.choosefromlist',
            {
                'WFInput': attachment(ref),
                'WFChooseFromListActionPrompt': prompt,
                'WFChooseFromListActionSelectMultiple': False,
            },
        )
        return output_of(a, 'Chosen Item')

    def match_text(self, ref, pattern):
        a = self.add(
            'is.workflow.actions.text.match',
            {
                'text': text(ref),
                'WFMatchTextPattern': pattern,
                'WFMatchTextCaseSensitive': True,
            },
        )
        return output_of(a, 'Matches')

    def save_to_album(self, media_ref, album_ref):
        self.add(
            'is.workflow.actions.savetocameraroll',
            {
                'WFInput': attachment(media_ref),
                'WFCameraRollSelectedGroup': attachment(album_ref),
            },
        )

    # actions copied from the sample
    def set_name(self, ref, *name):
        a = self.sample.template('is.workflow.actions.setitemname')
        return output_of(
            self.add(
                a,
                {
                    'WFInput': attachment(ref),
                    'WFName': text(*name),
                    'WFDontIncludeFileExtension': True,
                },
            ),
            'Renamed Item',
        )

    def save_to_photos(self, ref):
        a = self.sample.template('is.workflow.actions.savetocameraroll')
        return output_of(
            self.add(a, {'WFInput': attachment(ref)}), 'Saved Photo Media'
        )

    # a-Shell's parameter names are from its Base.lproj/Intents.intentdefinition.
    # Text parameters are stored as plain strings unless they contain a
    # variable, as the Shortcuts app does.
    def ashell_put_file(self, ref):
        a = self.sample.template('PutFileIntent')
        return self.add(a, {'file': attachment(ref), 'overwrite': True})

    def ashell_get_file(self, *name, error_if_missing=True):
        a = self.sample.template('GetFileIntent')
        # copyFile: return the data, not a link (a-Shell's iOS 18 workaround
        # for files deleted after being shown). Without errorIfNotFound, a
        # missing file gives no output.
        params = {
            'fileName': plain_or_text(*name),
            'errorIfNotFound': error_if_missing,
            'copyFile': True,
        }
        return output_of(self.add(a, params), 'File')

    def ashell_execute(self, *command, keep_going, open_app):
        """
        One a-Shell command text; several commands go on separate lines.

        open_app: 'open' (run in a-Shell, needed for WebAssembly) or 'close'
        (run in the background, for built-in commands like rm).
        """
        a = self.sample.template('ExecuteCommandIntent')
        params = {
            'command': plain_or_text(*command),
            'openWindow': open_app,
            'keepGoing': keep_going,
            'Show-command': True,
        }
        return self.add(a, params)


# ---------------------------------------------------------------------------
# The two shortcuts


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
            # so a-Shell prints the note too (see run_jxlbatch).
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


def run_jxlbatch(b, quality, then):
    """
    a-Shell command: run jxlbatch, then the command ``then``.

    When this launches a-Shell, a-Shell restores its last session (its folder
    too) while it starts these commands, and its WebAssembly engine may still
    be loading, which ends jxlbatch before it runs. So wait 2 s, change to the
    Shortcuts folder (~shortcuts, where Put File saves), and run jxlbatch; then
    run it with --retry, which does nothing if the first run started (it
    created jxl_started). Not through dash: a-Shell adds ".wasm" to a command's
    name, dash doesn't, so it can't find jxlbatch.

    The variable Skipped Echo (an echo of what the shortcut skipped, set by
    keep_still_photos only when something was) is printed before and after the
    batch; unset, it leaves an empty line, which a-Shell ignores.
    """
    echo = variable('Skipped Echo')
    b.ashell_execute(
        'sleep 2\ncd ~shortcuts\n',
        echo,
        '\njxlbatch -q ',
        quality,
        f' -e {EFFORT} jxl_job.txt\njxlbatch --retry -q ',
        quality,
        f' -e {EFFORT} jxl_job.txt\n',
        echo,
        '\n' + then,
        keep_going=False,
        open_app='open',
    )


def save_results(b, originals=None):
    """
    Saves the JPEG XL files listed in jxl_done.txt to Photos, each also to the
    albums its original is in.

    Each line is "file|index|delete or keep|name". With ``originals`` (the
    staged photos), the albums are read from the original at the line's index,
    and that original is added to the variable Converted (offered for deletion)
    if the line says "delete"; "keep" means the JPEG XL lacks the original's
    HDR. (A line from an older jxlbatch, "file|index|name", keeps it.) Without
    ``originals``, the albums are read from jxl_albums_<index>.txt, one album
    name per line, if that file exists. Returns the number of photos saved.
    """
    lines = b.split(b.text_from_input(b.ashell_get_file('jxl_done.txt')), '\n')

    def per_file():
        parts = b.split(REPEAT_ITEM, '|')
        file_name = b.item_from_list(parts, 'First Item')
        photo_name = b.item_from_list(parts, 'Last Item')
        saved = b.save_to_photos(
            b.set_name(b.ashell_get_file(file_name), photo_name)
        )
        index = b.item_at_index(parts, 2)

        def add_to_albums(albums):
            b.repeat_each(
                albums, lambda: b.save_to_album(saved, REPEAT_ITEM_2)
            )

        if originals:
            original = b.item_at_index(originals, index)
            delete = b.match_text(b.item_at_index(parts, 3), '^delete$')
            b.if_has_value(
                delete,
                lambda: b.append_variable('Converted', original),
                lambda: None,
            )
            add_to_albums(b.photo_albums(original))
        else:
            albums_file = b.ashell_get_file(
                'jxl_albums_', index, '.txt', error_if_missing=False
            )
            b.if_has_value(
                albums_file,
                lambda: add_to_albums(
                    b.split(b.text_from_input(albums_file), '\n')
                ),
                lambda: None,
            )

    b.repeat_each(lines, per_file)
    # Not the Repeat Results: a photo in no album adds nothing to those. A
    # failed save stops the shortcut, so every line here was saved.
    return b.count(lines)


CLEANUP = 'rm -f jxl_in_* jxl_out_* jxl_albums_* jxl_job.txt jxl_done.txt jxl_started'


def build_compress(sample):
    b = Builder(sample)
    b.comment(
        f'{NAME_A} {VERSION}. '
        'Converts photos to JPEG XL with a-Shell (jxlbatch), keeping their metadata. '
        'Only still photos are converted: Live Photos and videos are skipped. '
        'From the Photos share sheet, JXL-Import then saves the results. Started any '
        'other way, it shows a photo picker (which gives the original HEIF files), '
        'saves the results itself, and offers to delete the originals. Either way, '
        "each JPEG XL copy is also added to its original's albums. "
        'Setup and help: '
        'https://github.com/jsh9/photo-video-shortcuts/tree/main/shortcuts/compress-photos'
    )
    b.if_has_value(
        SHORTCUT_INPUT,
        lambda: b.set_variable('Photos', SHORTCUT_INPUT),
        lambda: b.set_variable('Photos', b.select_photos()),
    )
    # From here on only the still photos: they are staged, and their positions
    # in Stills are the job indices, also when saving the results.
    photos = keep_still_photos(b, variable('Photos'))
    quality = choose_quality(b)
    # A stale album file from an unfinished run would put a photo into the
    # wrong albums; jxl_in_* files are overwritten anyway.
    b.ashell_execute(
        'rm -f jxl_done.txt jxl_out_* jxl_albums_* jxl_started',
        keep_going=True,
        open_app='close',
    )

    # Only the original file goes to a-Shell: jxlbatch decodes HEIF, JPEG and
    # PNG itself, so there is no Convert Image step.
    def per_photo():
        name = b.get_name(REPEAT_ITEM)
        b.ashell_put_file(
            b.set_name(REPEAT_ITEM, 'jxl_in_', REPEAT_INDEX, '.orig')
        )
        b.append_variable('Jobs', b.text(REPEAT_INDEX, '|', name))

    b.repeat_each(photos, per_photo)
    b.ashell_put_file(
        b.set_name(b.combine(variable('Jobs'), '\n'), 'jxl_job.txt')
    )

    def from_share_sheet():
        # A share-sheet shortcut can't resume after a-Shell: JXL-Import saves,
        # and it no longer has the originals. So their album names go to
        # a-Shell too, as jxl_albums_<i>.txt (same order as jxl_in_<i>.orig).
        def write_albums():
            albums = b.photo_albums(REPEAT_ITEM)
            b.if_has_value(
                albums,
                lambda: b.ashell_put_file(
                    b.set_name(
                        b.combine(albums, '\n'),
                        'jxl_albums_',
                        REPEAT_INDEX,
                        '.txt',
                    )
                ),
                lambda: None,
            )

        b.repeat_each(photos, write_albums)
        run_jxlbatch(
            b, quality, f'open shortcuts://run-shortcut?name={NAME_B}'
        )

    def from_picker():
        run_jxlbatch(b, quality, 'open shortcuts://')
        b.wait_to_return()
        count = save_results(b, photos)
        b.ashell_execute(CLEANUP, keep_going=True, open_app='close')
        b.notification('JPEG XL', 'Saved ', count, ' photo(s) to Photos.')
        # Empty when every original is kept (or with an older jxlbatch).
        b.if_has_value(
            variable('Converted'),
            lambda: b.delete_photos(variable('Converted')),
            lambda: None,
        )

    b.if_has_value(SHORTCUT_INPUT, from_share_sheet, from_picker)
    return b.actions


def build_import(sample):
    b = Builder(sample)
    b.comment(
        f'{NAME_B} ({NAME_A} {VERSION}). '
        'Started by a-Shell when jxlbatch finishes. Saves the converted JPEG XL '
        'files to Photos. Keep this name: a-Shell starts it by name.'
    )
    count = save_results(b)
    b.ashell_execute(CLEANUP, keep_going=True, open_app='close')
    b.notification('JPEG XL', 'Saved ', count, ' photo(s) to Photos.')
    return b.actions


def workflow(sample, name, actions, share_sheet):
    s = sample.workflow
    wf = {
        k: copy.deepcopy(s[k])
        for k in (
            'WFWorkflowClientVersion',
            'WFWorkflowMinimumClientVersion',
            'WFWorkflowMinimumClientVersionString',
            'WFWorkflowIcon',
            'WFWorkflowOutputContentItemClasses',
        )
        if k in s
    }
    wf.update({
        'WFWorkflowName': name,
        'WFWorkflowActions': actions,
        'WFWorkflowImportQuestions': [],
        'WFWorkflowHasShortcutInputVariables': share_sheet,
    })
    if share_sheet:
        for k in (
            'WFWorkflowTypes',
            'WFWorkflowInputContentItemClasses',
            'WFQuickActionSurfaces',
        ):
            if k in s:
                wf[k] = copy.deepcopy(s[k])

        if 'ActionExtension' not in wf.get('WFWorkflowTypes', []):
            sys.exit('the sample shortcut is not set to Show in Share Sheet')
    else:
        wf['WFWorkflowTypes'] = []
        wf['WFWorkflowInputContentItemClasses'] = copy.deepcopy(
            s.get('WFWorkflowInputContentItemClasses', [])
        )

    return wf


def write(name, wf, sign):
    OUT.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)
    # Only the signed files in dist/ get the .shortcut extension; this one can't
    # be imported on a phone.
    unsigned = OUT / f'{name}.unsigned.wflow'
    with open(unsigned, 'wb') as f:
        plistlib.dump(wf, f, fmt=plistlib.FMT_BINARY)

    with open(OUT / f'{name}.plist', 'wb') as f:  # readable copy for review
        plistlib.dump(wf, f, fmt=plistlib.FMT_XML)

    subprocess.run(
        ['plutil', '-lint', str(unsigned)], check=True, capture_output=True
    )
    if not sign:
        print(f'wrote {unsigned} (unsigned)')
        return

    signed = DIST / f'{name}.shortcut'
    subprocess.run(
        [
            'shortcuts',
            'sign',
            '--mode',
            'anyone',
            '--input',
            str(unsigned),
            '--output',
            str(signed),
        ],
        check=True,
    )
    print(f'wrote {signed}')


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        '--fetch',
        metavar='ICLOUD_LINK',
        help='download the sample shortcut from its iCloud link',
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
        fetch_sample(args.fetch)

    if args.guess:
        sample = Sample(guessed_workflow())
    elif not args.sample.exists():
        sys.exit(
            f'missing {args.sample}: run with --fetch <iCloud link of the sample shortcut>, or --guess'
        )
    else:
        sample = Sample(args.sample)

    write(
        NAME_A,
        workflow(sample, NAME_A, build_compress(sample), share_sheet=True),
        not args.no_sign,
    )
    write(
        NAME_B,
        workflow(sample, NAME_B, build_import(sample), share_sheet=False),
        not args.no_sign,
    )


if __name__ == '__main__':
    main()
