"""
Which items Compress Photos converts: still photos (screenshots included). Live
Photos and videos are skipped, with a count of each kind, and when nothing is
left the shortcut stops before asking for a quality.

The shortcut runs here, up to its quality list, on a small model of Shortcuts.
Each item is sorted by Get Details of Images, which Shortcuts reads in memory
from the item (ContentKit's WFImageContentItem and WFPhotoMediaContentItem, iOS
18.2):

- Media Type is one value: Image (also for a Live Photo), Video or Audio. An
  image that isn't in the photo library (e.g. shared from Files) says Image
  too.
- Photo Type is a list (HDR, Panorama, Burst, Live Photo); a still photo's, a
  screenshot's and a Files image's is empty.
- A list put into a text field (Match Text) becomes one entry per line.

Filter Photos isn't used, and must not come back: see keep_still_photos in
build_shortcuts.py.
"""

import re
from dataclasses import dataclass, field

import photo_helpers as ph
import pytest

STILLS_ONLY = 'only still photos are converted.'


@dataclass(eq=False)  # compared by identity: the shortcut must keep the item
class Item:
    name: str
    media_type: str | None = 'Image'
    photo_types: list = field(default_factory=list)


STILL = Item('IMG_0001')
HDR = Item('IMG_0002', photo_types=['HDR'])
SCREENSHOT = Item('IMG_0003')  # a screenshot has no Photo Type
PANORAMA = Item('IMG_0004', photo_types=['Panorama'])
BURST = Item('IMG_0005', photo_types=['Burst'])
LIVE = Item('IMG_0006', photo_types=['Live Photo'])
HDR_LIVE = Item('IMG_0007', photo_types=['HDR', 'Live Photo'])
VIDEO = Item('IMG_0008', media_type='Video')
FROM_FILES = Item('scan')  # not in the library: Image, no Photo Type
UNKNOWN = Item('odd', media_type=None)  # no details at all: converted


class Stopped(Exception):
    """Stop This Shortcut ran."""


class QualityAsked(Exception):
    """The shortcut reached its quality list."""


class Shortcuts:
    """
    Runs a shortcut's actions until it stops or asks for the quality. Only the
    actions before the quality list are modeled.
    """

    def __init__(self, actions, shortcut_input, picked):
        self.actions = actions
        self.shortcut_input = shortcut_input
        self.picked = picked
        self.variables, self.outputs = {}, {}
        self.notifications = []
        self.groups = {}
        for i, action in enumerate(actions):
            p = ph.params(action)
            if ph.ident(action) in ph.CONTROL_FLOW:
                marks = self.groups.setdefault(p['GroupingIdentifier'], {})
                marks[p['WFControlFlowMode']] = i

    def run(self):
        """'stopped' or 'quality asked'."""
        try:
            self.block(0, len(self.actions), [])
        except Stopped:
            return 'stopped'
        except QualityAsked:
            return 'quality asked'

        raise AssertionError('the shortcut ended without asking for a quality')

    def block(self, start, end, repeats):
        i = start
        while i < end:
            action = self.actions[i]
            p = ph.params(action)
            if ph.ident(action) == 'is.workflow.actions.conditional':
                marks = self.groups[p['GroupingIdentifier']]
                assert p['WFCondition'] == 100  # has any value
                if has_value(self.value(p['WFInput']['Variable'], repeats)):
                    self.block(i + 1, marks[1], repeats)
                else:
                    self.block(marks[1] + 1, marks[2], repeats)

                i = marks[2] + 1
            elif ph.ident(action) == 'is.workflow.actions.repeat.each':
                last = self.groups[p['GroupingIdentifier']][2]
                items = as_list(self.value(p['WFInput'], repeats))
                for index, item in enumerate(items, 1):
                    self.block(i + 1, last, [*repeats, (item, index)])

                i = last + 1
            else:
                self.step(action, repeats)
                i += 1

    def step(self, action, repeats):
        p = ph.params(action)
        kind = ph.ident(action).removeprefix('is.workflow.actions.')
        result = None
        if kind == 'comment':
            pass
        elif kind == 'setvariable':
            self.variables[p['WFVariableName']] = as_list(
                self.value(p['WFInput'], repeats)
            )
        elif kind == 'appendvariable':
            self.variables.setdefault(p['WFVariableName'], []).extend(
                as_list(self.value(p['WFInput'], repeats))
            )
        elif kind == 'selectphoto':
            result = list(self.picked)
        elif kind == 'properties.images':
            item = self.value(p['WFInput'], repeats)
            result = photo_details(item, p['WFContentItemPropertyName'])
        elif kind == 'text.match':
            flags = 0 if p['WFMatchTextCaseSensitive'] else re.IGNORECASE
            result = re.findall(
                p['WFMatchTextPattern'], self.text(p['text'], repeats), flags
            )
        elif kind == 'count':
            result = len(as_list(self.value(p['Input'], repeats)))
        elif kind == 'gettext':
            result = self.text(p['WFTextActionText'], repeats)
        elif kind == 'text.combine':
            separator = {'New Lines': '\n', 'Custom': None}[
                p['WFTextSeparator']
            ] or p['WFTextCustomSeparator']
            items = as_list(self.value(p['text'], repeats))
            result = separator.join(str(item) for item in items)
        elif kind == 'notification':
            self.notifications.append(
                self.text(p['WFNotificationActionBody'], repeats)
            )
        elif kind == 'exit':
            raise Stopped
        elif kind == 'choosefromlist':
            raise QualityAsked
        elif kind in ('setitemname', 'detect.contacts'):
            pass  # the quality list's contact cards
        else:
            raise AssertionError(f'not modeled: {ph.ident(action)}')

        if 'UUID' in p:
            self.outputs[p['UUID']] = result

    def value(self, field, repeats):
        ref = field['Value'] if 'WFSerializationType' in field else field
        if ref['Type'] == 'ExtensionInput':
            return self.shortcut_input

        if ref['Type'] == 'ActionOutput':
            return self.outputs[ref['OutputUUID']]

        name = ref['VariableName']
        loops = {'Repeat Item': 1, 'Repeat Item 2': 2, 'Repeat Index': 1}
        if name in loops:
            item, index = repeats[loops[name] - 1]
            return index if name == 'Repeat Index' else item

        return self.variables.get(name)

    def text(self, field, repeats):
        """A text field's value; a list variable is one item per line."""
        if isinstance(field, str):
            return field

        value = field['Value']
        text = value['string']
        attachments = sorted(
            value.get('attachmentsByRange', {}).items(),
            key=lambda kv: int(kv[0].strip('{}').split(',')[0]),
        )
        for _, ref in attachments:
            items = as_list(self.value(ref, repeats))
            text = text.replace(ph.OBJ, '\n'.join(map(str, items)), 1)

        return text


def has_value(value):
    return value not in (None, '', [])


def as_list(value):
    if value is None:
        return []

    return list(value) if isinstance(value, list) else [value]


def photo_details(item, name):
    """Get Details of Images: the item's own value, read in memory."""
    if name == 'Media Type':
        return item.media_type

    assert name == 'Photo Type'
    return list(item.photo_types)


@pytest.fixture(scope='module')
def compress():
    gen = ph.load_generator()
    return gen.build_compress(gen.Sample(gen.guessed_workflow()))


def run(compress, items, start):
    """
    Runs Compress Photos on ``items``, from the share sheet or the picker.
    """
    shortcut_input = items if start == 'share sheet' else None
    shortcuts = Shortcuts(compress, shortcut_input, items)
    return shortcuts.run(), shortcuts


STARTS = pytest.mark.parametrize('start', ['share sheet', 'Shortcuts app'])


@STARTS
def test_converts_only_still_photos(compress, start):
    items = [LIVE, STILL, VIDEO, HDR, FROM_FILES, SCREENSHOT, HDR_LIVE]
    items += [PANORAMA, BURST, UNKNOWN]
    outcome, shortcuts = run(compress, items, start)
    assert outcome == 'quality asked'
    # The items themselves, in order: the share sheet's files are converted.
    stills = shortcuts.variables['Stills']
    assert [id(i) for i in stills] == [
        id(i)
        for i in (STILL, HDR, FROM_FILES, SCREENSHOT, PANORAMA, BURST, UNKNOWN)
    ]
    note = f'Skipped 2 Live Photo(s), 1 video(s): {STILLS_ONLY}'
    assert shortcuts.notifications == [note]
    # a-Shell prints the note too (the notification is gone when it opens).
    assert shortcuts.variables['Skipped Echo'] == [f'echo "{note}"']


@STARTS
def test_no_notification_when_nothing_skipped(compress, start):
    outcome, shortcuts = run(compress, [STILL, SCREENSHOT, FROM_FILES], start)
    assert outcome == 'quality asked'
    assert shortcuts.variables['Stills'] == [STILL, SCREENSHOT, FROM_FILES]
    assert shortcuts.notifications == []
    assert 'Skipped Echo' not in shortcuts.variables


@pytest.mark.parametrize(
    ('items', 'skipped'),
    [
        ([STILL, VIDEO, VIDEO], '2 video(s)'),
        ([HDR_LIVE, STILL], '1 Live Photo(s)'),
    ],
)
def test_counts_only_the_kinds_skipped(compress, items, skipped):
    outcome, shortcuts = run(compress, items, 'share sheet')
    assert outcome == 'quality asked'
    assert shortcuts.notifications == [f'Skipped {skipped}: {STILLS_ONLY}']


@STARTS
def test_stops_when_nothing_to_convert(compress, start):
    outcome, shortcuts = run(compress, [LIVE, VIDEO, HDR_LIVE], start)
    assert outcome == 'stopped'  # before the quality list
    assert 'Stills' not in shortcuts.variables
    assert shortcuts.notifications == [
        f'Nothing to convert. Skipped 2 Live Photo(s), 1 video(s): {STILLS_ONLY}'
    ]
    assert 'Skipped Echo' not in shortcuts.variables  # a-Shell never runs


@STARTS
def test_stops_when_no_items_at_all(compress, start):
    outcome, shortcuts = run(compress, [], start)
    assert outcome == 'stopped'
    assert 'Stills' not in shortcuts.variables
    assert shortcuts.notifications == ['Nothing to convert.']


def test_sorting_reads_each_item_in_memory(compress):
    # Get Details of Images on the item (Shortcuts' own English property
    # names, whatever the phone's language), then Match Text on the value.
    # Never Filter Photos: on photos from the library it turns a Photo Type
    # condition into a Photos-framework predicate on a key PHAsset objects
    # don't answer (mediaSubtype) and evaluates it in memory, which throws and
    # killed 0.3.0 on every photo; on an item not in the library it searches
    # the whole library instead.
    before_quality = []
    for action in compress:
        if ph.ident(action) == 'is.workflow.actions.choosefromlist':
            break

        before_quality.append(action)

    assert not any(
        ph.ident(a) == 'is.workflow.actions.filter.photos' for a in compress
    )
    repeat_item = {
        'Value': {'Type': 'Variable', 'VariableName': 'Repeat Item'},
        'WFSerializationType': 'WFTextTokenAttachment',
    }
    details = [
        ph.params(a)['WFContentItemPropertyName']
        for a in before_quality
        if ph.ident(a) == 'is.workflow.actions.properties.images'
        and ph.params(a)['WFInput'] == repeat_item
    ]
    assert details == ['Media Type', 'Photo Type']
    matches = [
        (
            ph.params(a)['WFMatchTextPattern'],
            ph.params(a)['WFMatchTextCaseSensitive'],
        )
        for a in before_quality
        if ph.ident(a) == 'is.workflow.actions.text.match'
    ]
    assert matches == [('^Image$', True), ('Live Photo', True)]


def test_picker_shows_images_only(compress):
    (picker,) = [
        ph.params(a)
        for a in compress
        if ph.ident(a) == 'is.workflow.actions.selectphoto'
    ]
    assert picker['WFPhotoPickerTypes'] == ['Images']
    assert picker['WFSelectMultiplePhotos'] is True


def test_only_stills_used_after_sorting(compress):
    # Photos (the share sheet's items or the picked photos) is read once, by
    # the sorting loop; staging, album files, collecting the originals in the
    # album (share sheet) and saving the results (whose job indices are
    # positions in the list) all use Stills.
    readers = [
        a
        for a in compress
        if any(
            r.get('VariableName') == 'Photos'
            for r in ph.references(ph.params(a))
        )
    ]
    assert [ph.ident(a) for a in readers] == [
        'is.workflow.actions.repeat.each'
    ]
    loops = [
        ph.params(a)['WFInput']['Value'].get('VariableName')
        for a in compress
        if ph.ident(a) == 'is.workflow.actions.repeat.each'
        and ph.params(a)['WFControlFlowMode'] == 0
        and a is not readers[0]
    ]
    assert loops.count('Stills') == 3  # staging, album files, collection
    originals = [
        ph.params(a)['WFInput']['Value'].get('VariableName')
        for a in compress
        if ph.ident(a) == 'is.workflow.actions.getitemfromlist'
        and ph.params(a)['WFItemSpecifier'] == 'Item At Index'
        and ph.params(a)['WFInput']['Value']['Type'] == 'Variable'
    ]
    assert originals == ['Stills']
