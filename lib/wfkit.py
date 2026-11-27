"""
Builds Shortcuts workflows (the plist inside a .shortcut file) in Python.

Shared by every shortcut's generators: the text and variable encoding, the
built-in actions, the actions copied from a sample shortcut, and writing and
signing the file. Compress Photos' scripts/wf.py re-exports all of it, next to
its own parts (the quality list and the still-photo filter).
"""

import copy
import json
import plistlib
import re
import subprocess
import sys
import urllib.request
import uuid

# What `from wfkit import *` gives a tool's own module (Compress Photos'
# scripts/wf.py re-exports it this way).
__all__ = [
    'COPY_KEYWORD',
    'OBJ',
    'REPEAT_INDEX',
    'REPEAT_ITEM',
    'REPEAT_ITEM_2',
    'SHORTCUT_INPUT',
    'Builder',
    'Ref',
    'Sample',
    'action',
    'applescript_text',
    'attachment',
    'fetch_sample',
    'guessed_workflow',
    'new_uuid',
    'number',
    'output_of',
    'plain_or_text',
    'text',
    'variable',
    'workflow',
    'write',
]

OBJ = '￼'  # placeholder for a variable inside a text field
# The keyword every copy gets in Photos after a Mac import
# (lib/mac/import.applescript, copyKeywords), to find the copies there; in
# Photos' library only. One word for every tool, so that one smart album
# lists all their copies.
COPY_KEYWORD = 'compr'


def applescript_text(path, **values):
    """
    The AppleScript at ``path`` (lib/mac/<name>.applescript) with its
    @PLACEHOLDERS@ filled in: each keyword argument names one, and its value is
    the text to put there, or a list of texts, which becomes an AppleScript
    list literal (``{"heic", "jxl"}``; ``{}`` when empty). Plain text: a
    Shortcuts variable inside a Run AppleScript's text keeps it from compiling
    (it then produces no output and no error; seen on macOS 26), so values go
    in through the action's input (``Builder.run_applescript``).
    """
    text = path.read_text()
    for name, value in values.items():
        if not isinstance(value, str):
            value = '{' + ', '.join(f'"{v}"' for v in value) + '}'

        text = text.replace(f'@{name}@', value)

    assert not re.findall('@[A-Z_]+@', text), path.name
    return text


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


def number(value):
    """
    A number field: a variable as an attachment (WorkflowKit's
    WFNumberSubstitutableState then resolves it to the number itself), a
    constant as a string, as the Shortcuts app writes both.
    """
    if isinstance(value, Ref):
        return attachment(value)

    return str(value)


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

    def _conditional(self, condition, ref, then, otherwise):
        """
        If/Otherwise on ``ref`` with ``condition`` (the If's parameters besides
        its input: WFCondition and what the condition needs). Format as written
        by Cherri (github.com/electrikmilk/cherri, shortcutgen.go).
        """
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
                **condition,
                'WFInput': {'Type': 'Variable', 'Variable': attachment(ref)},
            },
        )
        then()
        mark(1, {})
        otherwise()
        mark(2, {'UUID': new_uuid()})

    def if_has_value(self, ref, then, otherwise):
        """If/Otherwise with the "has any value" condition (code 100)."""
        self._conditional({'WFCondition': 100}, ref, then, otherwise)

    def if_true(self, ref, then, otherwise):
        """
        If/Otherwise on a Boolean (such as Get Details of Images ▸ Is
        Favorite): the condition "is" (code 4) with the switch on
        (WFConditionalActionBoolean). Format from a shortcut built on the
        iPhone (iOS 26), which leaves the switch at its default; it is written
        here, so the default doesn't matter. An input without a value (an image
        that isn't in the library has no Is Favorite) is not true.
        """
        self._conditional(
            {'WFCondition': 4, 'WFConditionalActionBoolean': True},
            ref,
            then,
            otherwise,
        )

    def favorite_photos(self, ref):
        """
        Photos' Favorite Photos: makes the photos ``ref`` favorites (its
        action, Favorite or Unfavorite, left at Favorite). An App Intent
        (FavoriteAssetsIntent, in PhotosUICore), stored as a shortcut built on
        the iPhone (iOS 26) stores it: the app's descriptor and the photos,
        which Shortcuts turns into the intent's AssetEntity from a library
        photo (com.apple.Photos.PHAsset).
        """
        return self.add(
            'com.apple.mobileslideshow.FavoriteAssetsIntent',
            {
                'AppIntentDescriptor': {
                    'AppIntentIdentifier': 'FavoriteAssetsIntent',
                    'BundleIdentifier': 'com.apple.mobileslideshow',
                    'Name': 'Photos',
                    'TeamIdentifier': '0000000000',
                },
                'assets': attachment(ref),
            },
        )

    def set_variable(self, name, ref):
        self.add(
            'is.workflow.actions.setvariable',
            {'WFVariableName': name, 'WFInput': attachment(ref)},
        )

    def choose_from_menu(self, prompt, cases):
        """
        Choose from Menu: ``cases`` maps each item's title to a function that
        adds the actions run when it is chosen, in the menu's order. Format as
        Shortcuts writes it (WFChooseFromMenuAction): a start with the prompt
        and the titles, one case per item carrying its title, and an end, all
        sharing a GroupingIdentifier.
        """
        group = new_uuid()

        def mark(mode, extra):
            self.actions.append({
                'WFWorkflowActionIdentifier': 'is.workflow.actions.choosefrommenu',
                'WFWorkflowActionParameters': {
                    'GroupingIdentifier': group,
                    'WFControlFlowMode': mode,
                    **extra,
                },
            })

        mark(0, {'WFMenuPrompt': prompt, 'WFMenuItems': list(cases)})
        for title, body in cases.items():
            mark(1, {'WFMenuItemTitle': title})
            body()

        mark(2, {'UUID': new_uuid()})

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

    def location_details(self, ref, name):
        """
        Get Details of Locations: the property ``name`` of the location
        ``ref``, as photo_details does for images (the same action class,
        WFContentItemPropertiesAction, with ``is.workflow.actions.properties
        .locations``, in the macOS 26 frameworks). Latitude and Longitude are
        text, the coordinate formatted with "%0.16g" (ContentKit's
        WFLocationContentItem, iOS 18.2): "." as the decimal point whatever the
        device's region. Altitude is a Number, which a text shows in the
        device's region's format.
        """
        a = self.add(
            'is.workflow.actions.properties.locations',
            {'WFContentItemPropertyName': name, 'WFInput': attachment(ref)},
        )
        return output_of(a, name)

    def format_date(self, ref):
        """
        Format Date, ISO 8601 with the time: "2024-01-01T17:00:00-05:00", the
        date as the device's clock shows it, with that time zone's offset on
        that date. Shortcuts formats it in the en_US_POSIX locale (Gregorian
        calendar, ASCII digits) whatever the device's settings, and in the
        device's time zone (ContentKit's NSDate(WFFormatting), iOS 18.2). The
        date goes in as a text field, as the Shortcuts app writes it.
        """
        a = self.add(
            'is.workflow.actions.format.date',
            {
                'WFDateFormatStyle': 'ISO 8601',
                'WFISO8601IncludeTime': True,
                'WFDate': text(ref),
            },
        )
        return output_of(a, 'Formatted Date')

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

    # Numbers, dates and images: built-in actions on both iPhone and Mac.
    # Parameter names and values from the decompiled actions (ActionKit, iOS
    # 18.2), checked against the Mac's frameworks and shortcuts built on a
    # device. Number fields (WFNumberFieldParameter: sizes, positions,
    # operands) take ``number(value)``: a variable keeps its number, so no
    # region's digits or separators get in the way.
    def calculate(self, ref, operation, operand):
        """
        Calculate: ``ref`` (+, -, ×, ÷) ``operand``, in decimal arithmetic
        (NSDecimalNumber).
        """
        a = self.add(
            'is.workflow.actions.math',
            {
                'WFInput': attachment(ref),
                'WFMathOperation': operation,
                'WFMathOperand': number(operand),
            },
        )
        return output_of(a, 'Calculation Result')

    def statistics(self, ref, operation):
        """
        Calculate Statistics: Minimum, Maximum... of the numbers ``ref``. Its
        input is "Input", as Count's (shortcuts built on a device); under
        "WFInput" it is ignored, the action gets nothing and gives nothing
        (seen on macOS 27).
        """
        a = self.add(
            'is.workflow.actions.statistics',
            {'Input': attachment(ref), 'WFStatisticsOperation': operation},
        )
        return output_of(a, 'Statistics')

    def round_number(self, ref, mode='Normal'):
        """
        Round Number to a whole number: Normal (half up), Always Round Up or
        Always Round Down.
        """
        a = self.add(
            'is.workflow.actions.round',
            {
                'WFInput': attachment(ref),
                'WFRoundTo': 'Ones Place',
                'WFRoundMode': mode,
            },
        )
        return output_of(a, 'Rounded Number')

    def time_between(self, start_ref, end_ref):
        """
        Get Time Between Dates in seconds: ``end_ref`` minus ``start_ref``
        (negative when it is earlier), a whole number. Both dates go in as text
        fields, as the Shortcuts app writes them.
        """
        a = self.add(
            'is.workflow.actions.gettimebetweendates',
            {
                'WFInput': text(end_ref),
                'WFTimeUntilFromDate': text(start_ref),
                'WFTimeUntilUnit': 'Seconds',
            },
        )
        return output_of(a, 'Time Between Dates')

    def add_seconds(self, date_ref, seconds_ref):
        """
        Adjust Date: ``date_ref`` plus ``seconds_ref`` seconds. The duration's
        magnitude is the variable's own dictionary, without the
        WFTextTokenAttachment wrapper: that is how WorkflowKit's
        WFQuantityParameterState writes it, and it reads a wrapped one as
        "Unknown Variable" (macOS 27).
        """
        a = self.add(
            'is.workflow.actions.adjustdate',
            {
                'WFDate': text(date_ref),
                'WFAdjustOperation': 'Add',
                'WFDuration': {
                    'Value': {'Magnitude': seconds_ref.value, 'Unit': 'sec'},
                    'WFSerializationType': 'WFQuantityFieldValue',
                },
            },
        )
        return output_of(a, 'Adjusted Date')

    def ask_number(self, prompt, default=None):
        """
        Ask for Input: a whole number, not negative, with ``default`` (a
        variable) filled in; returns the number typed. Keys as shortcuts built
        on a device store them (the default as the variable itself, under
        WFAskActionDefaultAnswerNumber); the two switches' names are in the
        Mac's frameworks.
        """
        params = {
            'WFAskActionPrompt': prompt,
            'WFInputType': 'Number',
            'WFAskActionAllowsDecimalNumbers': False,
            'WFAskActionAllowsNegativeNumbers': False,
        }
        if default is not None:
            params['WFAskActionDefaultAnswerNumber'] = attachment(default)

        return output_of(
            self.add('is.workflow.actions.ask', params), 'Provided Input'
        )

    def device_detail(self, name):
        """
        Get Device Details: ``name``. Device Model is the device's
        localizedModel: "iPhone", "iPad", or "Mac" (on the Mac in every
        language checked: English, Chinese, Japanese).
        """
        a = self.add(
            'is.workflow.actions.getdevicedetails', {'WFDeviceDetail': name}
        )
        return output_of(a, 'Device Details')

    def current_date(self):
        a = self.add(
            'is.workflow.actions.date', {'WFDateActionMode': 'Current Date'}
        )
        return output_of(a, 'Date')

    def replace_text(self, ref, pattern, *replacement):
        """
        Replace Text with a regular expression (case sensitive) on the text
        ``ref``: every match of ``pattern`` becomes ``replacement`` (text with
        variables), a template in which "$1" is a group and a backslash escapes
        (NSString's regular-expression replacing).
        """
        a = self.add(
            'is.workflow.actions.text.replace',
            {
                'WFInput': text(ref),
                'WFReplaceTextFind': pattern,
                'WFReplaceTextReplace': plain_or_text(*replacement),
                'WFReplaceTextRegularExpression': True,
                'WFReplaceTextCaseSensitive': True,
            },
        )
        return output_of(a, 'Updated Text')

    def base64(self, ref, mode):
        """
        Base64 Encode, ``mode`` Encode (a file's or a text's UTF-8 bytes to one
        line of text) or Decode (text to a file, whose type Shortcuts reads
        from its bytes).
        """
        a = self.add(
            'is.workflow.actions.base64encode',
            {
                'WFInput': attachment(ref),
                'WFEncodeMode': mode,
                'WFBase64LineBreakMode': 'None',
            },
        )
        return output_of(a, f'Base64 {mode}d')

    def resize_image(self, ref, width, height):
        """
        Resize Image to ``width`` × ``height`` pixels (the image's own
        orientation applied first); the result keeps the input's file type.
        """
        a = self.add(
            'is.workflow.actions.image.resize',
            {
                'WFImage': attachment(ref),
                'WFImageResizeKey': 'Size',
                'WFImageResizeWidth': number(width),
                'WFImageResizeHeight': number(height),
            },
        )
        return output_of(a, 'Resized Image')

    def crop_image(self, ref, x, y, width, height):
        """Crop Image: ``width`` × ``height`` from (``x``, ``y``), top left."""
        a = self.add(
            'is.workflow.actions.image.crop',
            {
                'WFInput': attachment(ref),
                'WFImageCropPosition': 'Custom',
                'WFImageCropX': number(x),
                'WFImageCropY': number(y),
                'WFImageCropWidth': number(width),
                'WFImageCropHeight': number(height),
            },
        )
        return output_of(a, 'Cropped Image')

    def overlay_image(self, base_ref, overlay_ref, x, y, width, height):
        """
        Overlay Image without its editor: ``overlay_ref`` drawn at (``x``,
        ``y``) from the top left of ``base_ref``, ``width`` × ``height``, not
        rotated, opaque. The result has the base's size.
        """
        a = self.add(
            'is.workflow.actions.overlayimageonimage',
            {
                'WFInput': attachment(base_ref),
                'WFImage': attachment(overlay_ref),
                'WFShouldShowImageEditor': False,
                'WFImagePosition': 'Custom',
                'WFImageX': number(x),
                'WFImageY': number(y),
                'WFImageWidth': number(width),
                'WFImageHeight': number(height),
                'WFRotation': '0',
                'WFOverlayImageOpacity': '100',
            },
        )
        return output_of(a, 'Overlaid Image')

    def combine_images(self, ref, mode):
        """
        Combine Images, ``mode`` Horizontally or Vertically, with no space
        between them: each image at its own size, side by side from the top
        left (WFImageCombineAction).
        """
        a = self.add(
            'is.workflow.actions.image.combine',
            {
                'WFInput': attachment(ref),
                'WFImageCombineMode': mode,
                'WFImageCombineSpacing': '0',
            },
        )
        return output_of(a, 'Combined Image')

    def convert_image(self, ref, image_format, quality=None):
        """
        Convert Image to ``image_format`` (JPEG, PNG, HEIF...), without the
        input's metadata; ``quality`` (0 to 1) is ImageIO's, for JPEG and HEIF.
        """
        params = {
            'WFInput': attachment(ref),
            'WFImageFormat': image_format,
            'WFImagePreserveMetadata': False,
        }
        if quality is not None:
            params['WFImageCompressionQuality'] = quality

        return output_of(
            self.add('is.workflow.actions.image.convert', params),
            'Converted Image',
        )

    # macOS-only actions (Shortcuts for Mac; they need "Allow Running
    # Scripts" in Shortcuts ▸ Settings ▸ Advanced). Parameter names from the
    # Mac's Shortcuts frameworks (the strings "as arguments"/"to stdin" and
    # InputMode) and public shortcut files.
    def run_shell_script(self, *script, input_ref=None, as_arguments=True):
        """
        Run Shell Script (/bin/zsh): ``script`` is text with variables; the
        input items are passed as files, their paths as arguments ("$@") or on
        stdin. Returns the script's standard output, which Shortcuts types by
        its content: text normally, but three or more newline-terminated lines
        with the same number of commas each are a CSV file to it (a ``dyn.``
        type), and the next action then gets a file named "stdout" instead of
        text. The first line's count is the header's and about nine in ten of
        the other lines must match it, so an odd line keeps short outputs text
        and long ones not (macOS 26, WorkflowKit's ``WFFileRepresentation``).
        Lines a later action reads go through a file the script writes instead
        (Get File), or the reader accepts a file (``planText`` in
        lib/mac/import.applescript); see
        shortcuts/compress-photos/DEVELOPING.md.
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

    def run_applescript(self, script, input_ref=None):
        """
        Run AppleScript. ``script`` is plain text: a Shortcuts variable inside
        the script text keeps the script from compiling (it then produces no
        output, without an error). Values go in through ``input_ref``, which
        the script reads as ``input`` in ``on run {input, parameters}`` (a
        list; a text item arrives as text, a file as an alias). The result
        comes back as text; a file result comes back as nothing (checked on
        macOS 26).
        """
        params = {'Script': script}
        if input_ref is not None:
            params['Input'] = attachment(input_ref)

        return output_of(
            self.add('is.workflow.actions.runapplescript', params),
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
