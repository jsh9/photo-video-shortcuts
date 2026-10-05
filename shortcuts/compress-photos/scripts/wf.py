"""
Builds Shortcuts workflows (the plist inside a .shortcut file) in Python.

Shared by build_shortcuts.py (the iPhone shortcuts, with a-Shell) and
build_mac_shortcuts.py (the Mac shortcuts, with Run Shell Script): the text and
variable encoding, the built-in actions both use, the quality presets and their
contact-card list, the still-photo filter, and writing and signing the file.
"""

import copy
import json
import plistlib
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
# Shared by the shortcuts and jxlbatch; shown in each shortcut's first note.
VERSION = (TOOL / 'VERSION').read_text(encoding='utf-8').strip()
EFFORT = 7
OBJ = '￼'  # placeholder for a variable inside a text field
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
# Sample handling


def fetch_sample(link, path):
    """
    Downloads a shortcut shared by iCloud link and saves its workflow as an XML
    plist at ``path``, to be used as a sample.
    """
    record_id = link.rstrip('/').split('/')[-1]
    api = f'https://www.icloud.com/shortcuts/api/records/{record_id}'
    with urllib.request.urlopen(api) as resp:
        record = json.load(resp)

    url = record['fields']['shortcut']['value']['downloadURL']
    with urllib.request.urlopen(url) as resp:
        data = resp.read()

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as f:
        plistlib.dump(plistlib.loads(data), f, fmt=plistlib.FMT_XML)

    print(f'saved {path}')


class Sample:
    """
    A real shortcut (or a hand-written stand-in, see guessed_workflow) whose
    actions are copied for the few actions whose parameters vary between
    Shortcuts versions.
    """

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


def action(identifier, params):
    return {
        'WFWorkflowActionIdentifier': identifier,
        'WFWorkflowActionParameters': params,
    }


def guessed_workflow(actions=()):
    """
    A hand-written stand-in for a sample shortcut: a share-sheet workflow with
    the built-in actions copied by ``Builder`` (Set Name, Save to Photo Album),
    plus ``actions`` (a tool's own, e.g. a-Shell's).
    """
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
            *actions,
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
    """Appends actions to a list; each method returns the action's output."""

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
        # The system always asks the user to confirm before photos are deleted.
        self.add(
            'is.workflow.actions.deletephotos', {'photos': attachment(ref)}
        )

    def photo_details(self, ref, name):
        """
        Get Details of Images: the property ``name`` of ``ref``.

        Shortcuts reads it in memory from the item itself (a photo from the
        library answers with its asset's details); nothing is looked up in the
        photo library. Format from a shortcut built on the iPhone (Album). The
        property names are Shortcuts' own English names, whatever the device's
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

    def file_details(self, ref, name):
        """Get Details of Files: the property ``name`` (e.g. File Path)."""
        a = self.add(
            'is.workflow.actions.properties.files',
            {'WFContentItemPropertyName': name, 'WFInput': attachment(ref)},
        )
        return output_of(a, name)

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

    # macOS-only actions (Shortcuts for Mac; they need "Allow Running
    # Scripts" in Shortcuts ▸ Settings ▸ Advanced). Parameter names from the
    # Mac's Shortcuts frameworks (the strings "as arguments"/"to stdin" and
    # InputMode) and public shortcut files.
    def run_shell_script(self, *script, input_ref=None, as_arguments=True):
        """
        Run Shell Script (/bin/zsh): ``script`` is text with variables; the
        input items are passed as files, their paths as arguments ("$@") or on
        stdin. Returns the script's standard output as text.
        """
        params = {
            'Script': plain_or_text(*script),
            'Shell': '/bin/zsh',
            'InputMode': 'as arguments' if as_arguments else 'to stdin',
        }
        if input_ref is not None:
            params['Input'] = attachment(input_ref)

        return output_of(
            self.add('is.workflow.actions.runshellscript', params),
            'Shell Script Result',
        )

    def run_applescript(self, *script):
        """
        Run AppleScript. Its result is coerced to Shortcuts items: a file
        (``POSIX file "..."``) becomes a File item.
        """
        return output_of(
            self.add(
                'is.workflow.actions.runapplescript',
                {'Script': plain_or_text(*script)},
            ),
            'AppleScript Result',
        )

    def get_file_from_shortcuts_folder(self, *path, error_if_missing=False):
        """
        Get File: ``path`` relative to Shortcuts' own folder in iCloud Drive
        (text with variables). Without ``error_if_missing``, a missing file
        gives no output. Absolute paths are refused by Shortcuts on the Mac.
        """
        a = self.add(
            'is.workflow.actions.documentpicker.open',
            {
                'WFGetFilePath': plain_or_text(*path),
                'WFShowFilePicker': False,
                'WFFileErrorIfNotFound': error_if_missing,
                'WFFileStorageService': 'iCloud Drive',
            },
        )
        return output_of(a, 'File')

    def quick_look(self, ref):
        """Quick Look (Preview Document): shows text or a file in a window."""
        self.add(
            'is.workflow.actions.previewdocument', {'WFInput': attachment(ref)}
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


# ---------------------------------------------------------------------------
# The workflow and its file


def workflow(
        sample,
        name,
        actions,
        share_sheet,
        types=None,
        input_classes=None,
        quick_action_surfaces=None,
):
    """
    The complete workflow dictionary.

    With ``share_sheet``, the surfaces and input classes are copied from the
    sample (the iPhone shortcuts), unless ``types`` (e.g. ``['ActionExtension',
    'QuickActions']``), ``input_classes`` and ``quick_action_surfaces`` (e.g.
    ``['Finder', 'Services']``) say otherwise (the Mac shortcuts).
    """
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

        if types is not None:
            wf['WFWorkflowTypes'] = list(types)

        if input_classes is not None:
            wf['WFWorkflowInputContentItemClasses'] = list(input_classes)

        if quick_action_surfaces is not None:
            wf['WFQuickActionSurfaces'] = list(quick_action_surfaces)

        if 'ActionExtension' not in wf.get('WFWorkflowTypes', []):
            sys.exit('the sample shortcut is not set to Show in Share Sheet')
    else:
        wf['WFWorkflowTypes'] = []
        wf['WFWorkflowInputContentItemClasses'] = copy.deepcopy(
            s.get('WFWorkflowInputContentItemClasses', [])
        )

    return wf


def write(name, wf, sign, out, dist):
    """
    Writes ``out/<name>.unsigned.wflow`` (and a readable .plist copy) and, with
    ``sign``, the signed ``dist/<name>.shortcut`` (macOS's ``shortcuts sign``,
    which needs an Apple ID).
    """
    out.mkdir(parents=True, exist_ok=True)
    dist.mkdir(parents=True, exist_ok=True)
    # Only the signed files in dist/ get the .shortcut extension; this one can't
    # be imported on a device.
    unsigned = out / f'{name}.unsigned.wflow'
    with open(unsigned, 'wb') as f:
        plistlib.dump(wf, f, fmt=plistlib.FMT_BINARY)

    with open(out / f'{name}.plist', 'wb') as f:  # readable copy for review
        plistlib.dump(wf, f, fmt=plistlib.FMT_XML)

    subprocess.run(
        ['plutil', '-lint', str(unsigned)], check=True, capture_output=True
    )
    if not sign:
        print(f'wrote {unsigned} (unsigned)')
        return

    signed = dist / f'{name}.shortcut'
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
