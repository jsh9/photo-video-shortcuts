"""
The Mac's route from Photos, run on the model of Shortcuts (shortcut_model.py)
with the shortcut's real zsh scripts in a pretend home folder, and a stand-in
for Photos' answers to the AppleScripts (Photos can't be scripted here): no
picker when Photos has a selection; the photos stacked in the selection's order
under their own names; a video skipped; the date Photos gives, plus 5 seconds,
with the Mac's offset on that date; the copies removed from iCloud Drive
afterwards. With no selection the picker shows; an error stops with its text;
the iPhone and Finder's input never run a script. Also stage.zsh alone, on odd
names and dates.
"""

import datetime as dt
import io
import subprocess
import zoneinfo

import PIL.Image
import pytest
import shortcut_model as sm
import stack_helpers as sh

NEW_YORK = zoneinfo.ZoneInfo('America/New_York')


@pytest.fixture(scope='module')
def jpeg():
    return (sh.FIXTURES / 'imageio.jpg').read_bytes()


class Photos:
    """
    Photos' side of the AppleScripts: the probe's answer, and the export of
    ``items`` ((file name, (width, height) or None for a video, the date as
    Photos' clock shows it)) into the work folder, one folder per item.
    """

    def __init__(self, gen, home, items, probe=None, export_error=None):
        self.gen, self.home, self.items = gen, home, items
        self.probe = probe or f'SELECTION {len(items)}'
        self.export_error = export_error
        self.exported = False

    def __call__(self, script, given):
        if script == self.gen.applescript('probe'):
            return self.probe

        assert script == self.gen.applescript('export')
        (work,) = given
        assert work == str(self.home / 'Pictures' / '.stack-photos-macos')
        assert sorted(
            p.name
            for p in (self.home / 'Pictures' / '.stack-photos-macos').iterdir()
        ) == ['in']
        if self.export_error:
            return self.export_error

        lines = ''
        for n, (name, size, when) in enumerate(self.items, 1):
            folder = (
                self.home / 'Pictures' / '.stack-photos-macos' / 'in' / str(n)
            )
            folder.mkdir(parents=True)
            if size is None:
                (folder / name).write_bytes(b'movie')
            else:
                PIL.Image.new('RGB', size, (200, 30, 30)).save(
                    folder / name, 'JPEG'
                )

            lines += f'{n}|{when}\n'

        self.exported = True
        return lines


ITEMS = [
    ('IMG_0001.jpeg', (403, 302), '2026-05-01 09:00:00'),
    ('IMG_0002.jpeg', (302, 403), '2026-05-02 19:15:59'),
    ('IMG_0003.mov', None, '2026-06-01 00:00:00'),  # a video: skipped
    ('IMG 0004.jpeg', (118, 256), '2026-04-30 23:59:59'),
]


def shared(home):
    return home / sm.ICLOUD_SHORTCUTS / 'stack-photos-macos'


def run_mac(gen, actions, home, photos, answers, jpeg, **kw):
    (home / sm.ICLOUD_SHORTCUTS).mkdir(parents=True, exist_ok=True)
    (home / 'Pictures').mkdir(exist_ok=True)
    s = sm.Shortcuts(
        actions,
        shortcut_input=kw.pop('shortcut_input', None),
        picked=kw.pop('picked', ()),
        answers=answers,
        jpeg=jpeg,
        device='Mac',
        applescript=photos,
        home=home,
        tz=dt.timezone(dt.timedelta(hours=-4)),
        **kw,
    )
    return s.run(), s


def exif_date(data):
    with PIL.Image.open(io.BytesIO(data)) as image:
        sub = image.getexif().get_ifd(0x8769)
        return sub.get(0x9003), sub.get(0x9011)


def test_selection_from_photos(gen, actions, jpeg, tmp_path):
    photos = Photos(gen, tmp_path, ITEMS)
    result, s = run_mac(
        gen,
        actions,
        tmp_path,
        photos,
        sh.answers(gen, gen.HORIZONTAL, '3:4', gen.CROP),
        jpeg,
    )
    assert result == 'done'
    assert s.pickers == 0 and photos.exported
    ((_, tiles),) = s.combined
    assert [t.name for t in tiles] == ['IMG_0001', 'IMG_0002', 'IMG 0004']
    (saved,) = s.saved
    assert saved.name == 'IMG_0001-stack.jpg'
    # the latest of the photos' dates (the video's isn't counted), + 5 s, on
    # the Mac's clock with its offset that day
    assert exif_date(saved.data) == ('2026:05:02 19:16:04', '-04:00')
    assert s.notifications[-1].endswith(' Skipped 1 video(s).')
    kinds = [kind for kind, _ in s.scripts]
    assert kinds == ['applescript', 'shell', 'applescript', 'shell', 'shell']
    assert s.scripts[-1][1] == f'rm -rf {gen.SHARED}'
    assert not shared(tmp_path).exists()  # removed after saving
    assert not (tmp_path / 'Pictures' / '.stack-photos-macos').exists()


def test_iphone_never_runs_a_script(gen, actions, jpeg):
    picked = [sm.Img(4032, 3024, name='A'), sm.Img(3024, 4032, name='B')]
    s = sm.Shortcuts(
        actions,
        picked=picked,
        answers=sh.answers(gen, gen.VERTICAL, gen.KEEP),
        jpeg=jpeg,
        device='iPhone',
    )
    assert s.run() == 'done'
    assert s.pickers == 1 and not s.scripts


def test_finder_input_runs_no_script(gen, actions, jpeg, tmp_path):
    files = [sm.Img(4032, 3024, name='A'), sm.Img(3024, 4032, name='B')]
    result, s = run_mac(
        gen,
        actions,
        tmp_path,
        None,
        sh.answers(gen, gen.VERTICAL, gen.KEEP),
        jpeg,
        shortcut_input=files,
    )
    assert result == 'done'
    assert s.pickers == 0 and not s.scripts


def test_nothing_selected_shows_the_picker(gen, actions, jpeg, tmp_path):
    photos = Photos(gen, tmp_path, ITEMS, probe='NONE')
    picked = [sm.Img(4032, 3024, name='A')]
    result, s = run_mac(
        gen,
        actions,
        tmp_path,
        photos,
        sh.answers(gen, gen.VERTICAL, gen.KEEP),
        jpeg,
        picked=picked,
    )
    assert result == 'done'
    assert s.pickers == 1 and not photos.exported
    assert [kind for kind, _ in s.scripts] == ['applescript']


@pytest.mark.parametrize('where', ['probe', 'export'])
def test_an_error_stops_with_its_text(gen, actions, jpeg, tmp_path, where):
    error = 'ERROR: Photos could not be asked (-1743: Not authorized).'
    photos = Photos(
        gen,
        tmp_path,
        ITEMS,
        probe=error if where == 'probe' else None,
        export_error=error if where == 'export' else None,
    )
    result, s = run_mac(gen, actions, tmp_path, photos, [], jpeg)
    assert result == 'stopped'
    assert s.notifications == [error]
    assert s.pickers == 0 and not s.saved


def test_only_videos_selected(gen, actions, jpeg, tmp_path):
    photos = Photos(
        gen, tmp_path, [('IMG_0003.mov', None, '2026-06-01 00:00:00')]
    )
    result, s = run_mac(gen, actions, tmp_path, photos, [], jpeg)
    assert result == 'stopped'
    assert s.notifications == ['Nothing to stack: no photos were given.']
    assert not shared(tmp_path).exists()  # cleaned up before stopping


def test_no_dates_in_photos(gen, actions, jpeg, tmp_path):
    # Photos gives no date: Get Details' (none in the exported files here),
    # so the time of the run.
    items = [(name, size, '') for name, size, _ in ITEMS if size]
    now = dt.datetime(2026, 10, 22, 16, 4, 5, tzinfo=dt.UTC)
    photos = Photos(gen, tmp_path, items)
    result, s = run_mac(
        gen,
        actions,
        tmp_path,
        photos,
        sh.answers(gen, gen.HORIZONTAL, gen.KEEP),
        jpeg,
        now=now,
    )
    assert result == 'done'
    assert exif_date(s.saved[0].data) == ('2026:10:22 12:04:05', '-04:00')


def stage(gen, home, lines, files, tz='America/New_York'):
    """stage.zsh alone, with ``files`` ({"n/name": bytes}) exported."""
    work = home / 'Pictures' / '.stack-photos-macos'
    for path, data in files.items():
        (work / 'in' / path).parent.mkdir(parents=True, exist_ok=True)
        (work / 'in' / path).write_bytes(data)

    (home / sm.ICLOUD_SHORTCUTS).mkdir(parents=True, exist_ok=True)
    before, _, after = gen.stage_script(None)
    result = subprocess.run(
        ['/bin/zsh', '-c', before + lines + after],
        env={'HOME': str(home), 'TZ': tz, 'PATH': '/usr/bin:/bin'},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    out = shared(home)
    return {
        f: (out / f'{f}.txt').read_text() for f in ('list', 'skipped', 'date')
    }


def test_stage_odd_names_and_dates(gen, tmp_path):
    files = {
        '1/Beach | day: 1.HEIC': b'heic',
        '2/same.jpeg': b'jpeg',
        '3/same.jpeg': b'jpeg',
        '4/clip.m4v': b'movie',
        '5/scan.PNG': b'png',
    }
    lines = '\n'.join([
        '1|2026-03-08 02:30:00',  # a time the clocks skip: read as 03:30
        '2|not a date',
        '3|2026-11-01 01:30:00',  # the repeated hour: the first of the two
        '4|2027-01-01 00:00:00',  # a video: no picture, its date not counted
        '5|',
    ])
    out = stage(gen, tmp_path, lines, files)
    assert (
        out['list']
        == '1/Beach | day: 1.HEIC\n2/same.jpeg\n3/same.jpeg\n5/scan.PNG'
    )
    assert out['skipped'] == '4'
    assert out['date'] == '2026-11-01T01:30:05-04:00'
    assert not (tmp_path / 'Pictures' / '.stack-photos-macos').exists()


@pytest.mark.parametrize(
    'tz,expected',
    [
        ('America/New_York', '2026-07-04T21:15:05-04:00'),
        ('Asia/Kolkata', '2026-07-04T21:15:05+05:30'),
        ('UTC', '2026-07-04T21:15:05+00:00'),
    ],
)
def test_stage_offsets(gen, tmp_path, tz, expected):
    out = stage(gen, tmp_path, '1|2026-07-04 21:15:00', {'1/a.jpeg': b'x'}, tz)
    assert out['date'] == expected


def test_stage_no_dates_no_pictures(gen, tmp_path):
    out = stage(gen, tmp_path, 'ERROR: something', {})
    assert out == {'list': '', 'skipped': '', 'date': ''}
