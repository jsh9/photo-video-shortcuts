"""
A model of Shortcuts that runs Stack Photos end to end without a device: every
action the shortcut uses, with images as sizes and the date steps, texts and
base64 for real. What each action does is modeled on its decompiled code
(ActionKit and ContentKit, iOS 18.2), checked on the Mac where its helpers run
(see shortcuts/stack-photos/DEVELOPING.md):

- Get Details of Images reads in memory: Width and Height upright, Date Taken
  (Photos' date, or the EXIF date), Media Type.
- Calculate works in decimal (NSDecimalNumber, 38 digits); Round Number's
  Normal is half up, Always Round Down is down.
- Resize Image, Crop Image and Overlay Image keep the input's file type;
  Combine Images writes PNG when its inputs are mostly PNG, puts the images
  side by side from the top left, and is as high (wide) as the tallest
  (widest). Convert Image to JPEG gives the bytes the test passes in.
- Replace Text is NSString's regular-expression replacing: "$1" in the
  template is a group.
- Format Date (ISO 8601 with the time) is "2026-10-22T10:15:05-04:00", "Z" for
  a zero offset, in the device's time zone.
- A text field holding only a variable passes the variable's value (a date
  stays a date).

The image steps also check what the shortcut must never do: draw outside an
image, distort it, or (with ``strict``) enlarge a photo.
"""

import base64
import datetime as dt
import io
import re
from dataclasses import dataclass, replace
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, getcontext

import PIL.Image
import stack_helpers as sh

getcontext().prec = 38


@dataclass(frozen=True)
class Img:
    """An image as Shortcuts holds it; ``kind`` is its file type."""

    width: int
    height: int
    kind: str = 'heic'
    name: str = 'IMG_0001'
    date: dt.datetime | None = None
    media: str | None = 'Image'


@dataclass(frozen=True)
class File:
    """A file Shortcuts holds as bytes (Base64 Decode's output)."""

    data: bytes
    name: str = 'Text'


class Stopped(Exception):
    """Stop This Shortcut ran."""


class Shortcuts:
    """
    Runs ``actions`` with ``shortcut_input`` (None: started in the Shortcuts
    app), the photos the picker returns, the menu ``answers`` in order, the
    JPEG bytes Convert Image writes, and the device's time zone and clock.
    """

    def __init__(
            self,
            actions,
            shortcut_input=None,
            picked=(),
            answers=(),
            jpeg=b'',
            tz=dt.timezone(dt.timedelta(hours=-4)),
            now=dt.datetime(2026, 10, 22, 12, 0, 0, tzinfo=dt.UTC),
    ):
        self.actions = actions
        self.shortcut_input = shortcut_input
        self.picked = list(picked)
        self.answers = list(answers)
        self.jpeg = jpeg
        self.tz = tz
        self.now = now
        self.variables, self.outputs = {}, {}
        self.menus, self.notifications, self.saved = [], [], []
        self.resized, self.cropped, self.overlaid, self.combined = (
            [],
            [],
            [],
            [],
        )
        self.groups = {}
        for i, action in enumerate(actions):
            p = sh.params(action)
            if sh.ident(action) in sh.CONTROL_FLOW:
                marks = self.groups.setdefault(p['GroupingIdentifier'], {})
                marks.setdefault(p['WFControlFlowMode'], []).append(i)

    def run(self):
        """'done' or 'stopped'."""
        try:
            self.block(0, len(self.actions), [])
        except Stopped:
            return 'stopped'

        assert not self.answers, f'menus not asked: {self.answers}'
        return 'done'

    # control flow
    def block(self, start, end, repeats):
        i = start
        while i < end:
            action = self.actions[i]
            p = sh.params(action)
            kind = sh.ident(action).removeprefix('is.workflow.actions.')
            if kind in ('conditional', 'repeat.each', 'choosefrommenu'):
                marks = self.groups[p['GroupingIdentifier']]
                getattr(self, kind.replace('.', '_'))(p, marks, repeats)
                i = marks[2][0] + 1
            else:
                self.step(kind, p, repeats)
                i += 1

    def conditional(self, p, marks, repeats):
        assert p['WFCondition'] == 100  # has any value
        middle, last = marks[1][0], marks[2][0]
        if as_list(self.value(p['WFInput']['Variable'], repeats)):
            self.block(marks[0][0] + 1, middle, repeats)
        else:
            self.block(middle + 1, last, repeats)

    def repeat_each(self, p, marks, repeats):
        items = as_list(self.value(p['WFInput'], repeats))
        for index, item in enumerate(items, 1):
            self.block(marks[0][0] + 1, marks[2][0], [*repeats, (item, index)])

    def choosefrommenu(self, p, marks, repeats):
        prompt = self.text(p['WFMenuPrompt'], repeats)
        titles = p['WFMenuItems']
        assert self.answers, f'no answer for the menu "{prompt}"'
        answer = self.answers.pop(0)
        assert answer in titles, (answer, titles)
        self.menus.append((prompt, titles))
        cases = marks[1] + marks[2]
        for case, after in zip(cases, cases[1:]):
            if sh.params(self.actions[case])['WFMenuItemTitle'] == answer:
                self.block(case + 1, after, repeats)

    # actions
    def step(self, kind, p, repeats):
        result = getattr(self, 'do_' + kind.replace('.', '_'))(p, repeats)
        if 'UUID' in p:
            self.outputs[p['UUID']] = result

    def do_comment(self, p, repeats):
        pass

    def do_setvariable(self, p, repeats):
        self.variables[p['WFVariableName']] = as_list(
            self.value(p['WFInput'], repeats)
        )

    def do_appendvariable(self, p, repeats):
        self.variables.setdefault(p['WFVariableName'], []).extend(
            as_list(self.value(p['WFInput'], repeats))
        )

    def do_selectphoto(self, p, repeats):
        return list(self.picked)

    def do_properties_images(self, p, repeats):
        item = one(self.value(p['WFInput'], repeats))
        name = p['WFContentItemPropertyName']
        return {
            'Media Type': lambda: item.media,
            'Width': lambda: Decimal(item.width),
            'Height': lambda: Decimal(item.height),
            'Date Taken': lambda: item.date,
        }[name]()

    def do_text_match(self, p, repeats):
        assert p['WFMatchTextCaseSensitive']
        subject = self.text(p['text'], repeats)
        return [
            m.group(0) for m in re.finditer(p['WFMatchTextPattern'], subject)
        ]

    def do_count(self, p, repeats):
        assert p['WFCountType'] == 'Items'
        return Decimal(len(as_list(self.value(p['Input'], repeats))))

    def do_gettext(self, p, repeats):
        return self.text(p['WFTextActionText'], repeats)

    def do_number(self, p, repeats):
        return Decimal(p['WFNumberActionNumber'])

    def do_math(self, p, repeats):
        a = self.number(p['WFInput'], repeats)
        b = self.number(p['WFMathOperand'], repeats)
        return {
            '+': lambda: a + b,
            '-': lambda: a - b,
            '×': lambda: a * b,
            '÷': lambda: a / b,
        }[p['WFMathOperation']]()

    def do_statistics(self, p, repeats):
        numbers = [
            Decimal(n) for n in as_list(self.value(p['WFInput'], repeats))
        ]
        assert numbers
        operation = {'Minimum': min, 'Maximum': max}[
            p['WFStatisticsOperation']
        ]
        return operation(numbers)

    def do_round(self, p, repeats):
        assert p['WFRoundTo'] == 'Ones Place'
        mode = {'Normal': ROUND_HALF_UP, 'Always Round Down': ROUND_FLOOR}
        number = self.number(p['WFInput'], repeats)
        return number.quantize(Decimal(1), rounding=mode[p['WFRoundMode']])

    def do_date(self, p, repeats):
        assert p['WFDateActionMode'] == 'Current Date'
        return self.now

    def do_format_date(self, p, repeats):
        assert (
            p['WFDateFormatStyle'] == 'ISO 8601' and p['WFISO8601IncludeTime']
        )
        return self.iso(self.field(p['WFDate'], repeats))

    def iso(self, date):
        text = date.astimezone(self.tz).isoformat(timespec='seconds')
        return (
            text.removesuffix('+00:00') + 'Z'
            if text.endswith('+00:00')
            else text
        )

    def do_gettimebetweendates(self, p, repeats):
        assert p['WFTimeUntilUnit'] == 'Seconds'
        start = self.field(p['WFTimeUntilFromDate'], repeats)
        end = one(self.value(p['WFInput'], repeats))
        return Decimal(int((end - start).total_seconds()))

    def do_adjustdate(self, p, repeats):
        assert p['WFAdjustOperation'] == 'Add'
        duration = p['WFDuration']
        assert duration['WFSerializationType'] == 'WFQuantityFieldValue'
        assert duration['Value']['Unit'] == 'sec'
        magnitude = self.value(duration['Value']['Magnitude'], repeats)
        date = self.field(p['WFDate'], repeats)
        return date + dt.timedelta(seconds=int(one(magnitude)))

    def do_getitemfromlist(self, p, repeats):
        assert p['WFItemSpecifier'] == 'First Item'
        return as_list(self.value(p['WFInput'], repeats))[0]

    def do_getitemname(self, p, repeats):
        return one(self.value(p['WFInput'], repeats)).name

    def do_setitemname(self, p, repeats):
        assert p['WFDontIncludeFileExtension']  # the name is used as it is
        item = one(self.value(p['WFInput'], repeats))
        return replace(item, name=self.text(p['WFName'], repeats))

    def do_savetocameraroll(self, p, repeats):
        assert 'WFCameraRollSelectedGroup' not in p  # Recents
        self.saved.extend(as_list(self.value(p['WFInput'], repeats)))

    def do_notification(self, p, repeats):
        self.notifications.append(
            self.text(p['WFNotificationActionBody'], repeats)
        )

    def do_exit(self, p, repeats):
        raise Stopped

    def do_base64encode(self, p, repeats):
        assert p['WFBase64LineBreakMode'] == 'None'
        value = one(self.value(p['WFInput'], repeats))
        if p['WFEncodeMode'] == 'Encode':
            data = value.data if isinstance(value, File) else value.encode()
            return base64.b64encode(data).decode()

        assert p['WFEncodeMode'] == 'Decode'
        data = base64.b64decode(value, validate=True)
        if data.startswith(b'\x89PNG'):  # the pad canvas: a white pixel
            with PIL.Image.open(io.BytesIO(data)) as png:
                assert png.size == (1, 1)
                assert png.convert('RGB').getpixel((0, 0)) == (255, 255, 255)

            return Img(1, 1, kind='png', name='canvas')

        return File(data)

    def do_text_replace(self, p, repeats):
        assert p['WFReplaceTextRegularExpression']
        assert p['WFReplaceTextCaseSensitive']
        subject = self.text(p['WFInput'], repeats)
        template = self.text(p['WFReplaceTextReplace'], repeats)
        # NSRegularExpression's template: $n is a group, \ escapes
        python = re.sub(r'\$(\d)', r'\\\1', template.replace('\\', '\\\\'))
        return re.sub(p['WFReplaceTextFind'], python, subject)

    def do_image_convert(self, p, repeats):
        assert p['WFImagePreserveMetadata'] is False
        image = one(self.value(p['WFInput'], repeats))
        assert isinstance(image, Img)
        if p['WFImageFormat'] == 'PNG':
            return replace(image, kind='png')

        assert p['WFImageFormat'] == 'JPEG'
        self.stack = image
        return File(self.jpeg, name=image.name)

    def do_image_resize(self, p, repeats):
        assert p['WFImageResizeKey'] == 'Size'
        image = one(self.value(p['WFImage'], repeats))
        width = self.pixels(p['WFImageResizeWidth'], repeats)
        height = self.pixels(p['WFImageResizeHeight'], repeats)
        assert width > 0 and height > 0
        if image.name != 'canvas':  # a photo: not distorted
            assert (
                abs(width * image.height - height * image.width)
                <= (image.width + image.height) / 2
            ), (image, width, height)

        self.resized.append((image, width, height))
        return replace(image, width=width, height=height)

    def do_image_crop(self, p, repeats):
        assert p['WFImageCropPosition'] == 'Custom'
        image = one(self.value(p['WFInput'], repeats))
        x, y, width, height = (
            self.pixels(p[k], repeats)
            for k in (
                'WFImageCropX',
                'WFImageCropY',
                'WFImageCropWidth',
                'WFImageCropHeight',
            )
        )
        assert 0 <= x and 0 <= y and 0 < width and 0 < height
        assert x + width <= image.width and y + height <= image.height
        self.cropped.append((image, x, y, width, height))
        return replace(image, width=width, height=height)

    def do_overlayimageonimage(self, p, repeats):
        assert p['WFShouldShowImageEditor'] is False
        assert p['WFImagePosition'] == 'Custom'
        assert p['WFRotation'] == '0' and p['WFOverlayImageOpacity'] == '100'
        base = one(self.value(p['WFInput'], repeats))
        image = one(self.value(p['WFImage'], repeats))
        x, y, width, height = (
            self.pixels(p[k], repeats)
            for k in ('WFImageX', 'WFImageY', 'WFImageWidth', 'WFImageHeight')
        )
        assert (width, height) == (image.width, image.height)  # not scaled
        assert 0 <= x and 0 <= y
        assert x + width <= base.width and y + height <= base.height
        self.overlaid.append((base, image, x, y))
        return replace(base, name=image.name)

    def do_image_combine(self, p, repeats):
        assert p['WFImageCombineSpacing'] == '0'
        images = as_list(self.value(p['WFInput'], repeats))
        mode = p['WFImageCombineMode']
        if mode == 'Horizontally':
            width = sum(i.width for i in images)
            height = max(i.height for i in images)
        else:
            assert mode == 'Vertically'
            width = max(i.width for i in images)
            height = sum(i.height for i in images)

        pngs = sum(i.kind == 'png' for i in images)
        jpegs = sum(i.kind == 'jpeg' for i in images)
        self.combined.append((mode, images))
        return Img(
            width,
            height,
            kind='jpeg' if jpegs >= pngs else 'png',
            name='Stack',
        )

    # values
    def value(self, field, repeats):
        if isinstance(field, dict) and 'WFSerializationType' in field:
            if field['WFSerializationType'] == 'WFTextTokenString':
                return self.text(field, repeats)

            field = field['Value']

        if not isinstance(field, dict):
            return field

        if field['Type'] == 'ExtensionInput':
            return self.shortcut_input

        if field['Type'] == 'ActionOutput':
            return self.outputs[field['OutputUUID']]

        name = field['VariableName']
        if name in ('Repeat Item', 'Repeat Index'):
            item, index = repeats[-1]
            return Decimal(index) if name == 'Repeat Index' else item

        return self.variables.get(name)

    def field(self, field, repeats):
        """A text field: a lone variable passes its value."""
        value = field['Value']
        if value['string'] == sh.OBJ:
            return one(
                self.value(value['attachmentsByRange']['{0, 1}'], repeats)
            )

        return self.text(field, repeats)

    def text(self, field, repeats):
        """A text field's value; a list is one item per line."""
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
            text = text.replace(sh.OBJ, '\n'.join(map(str, items)), 1)

        return text

    def number(self, field, repeats):
        if isinstance(field, str):
            return Decimal(field)

        return Decimal(one(self.value(field, repeats)))

    def pixels(self, field, repeats):
        number = self.number(field, repeats)
        assert number == number.to_integral_value(), number  # whole pixels
        return int(number)


def as_list(value):
    if value is None or value == '':
        return []

    return list(value) if isinstance(value, list) else [value]


def one(value):
    items = as_list(value)
    assert len(items) == 1, items
    return items[0]
