"""
The Mac shortcuts' shell script (scripts/mac/*.zsh, as Run Shell Script gets
it), run for real with zsh and a photobatch build: staging, the result lines
the Photos shortcut saves, the files the Finder shortcut writes, the log, the
encoder checks, and the cores choice becoming photobatch's -j and -t. Also that
the macOS encoder's output is byte for byte the WebAssembly build's, also with
two photos at a time.
"""

import os
import pathlib
import re
import shutil
import subprocess

import photo_helpers as ph
import pytest

FIXTURES = ph.HERE / 'fixtures'
MACOS = ph.TOOL / 'dist' / 'photobatch-macos'
NATIVE = ph.TOOL / 'build' / 'photobatch'
VERSION = (ph.TOOL / 'VERSION').read_text().strip()


@pytest.fixture(scope='module')
def photobatch():
    """The macOS build if it exists, else the Homebrew-linked one."""
    for path in (MACOS, NATIVE):
        if path.exists() and ph.run([path, '--version']).returncode == 0:
            return path

    ph.need(False, f'{MACOS} or {NATIVE} is needed; run the build scripts')


@pytest.fixture(scope='module')
def gen():
    return ph.load_generator('build_mac_shortcuts')


@pytest.fixture(scope='module')
def shortcuts(gen):
    wf = ph.load_generator('wf')
    sample = wf.Sample(wf.guessed_workflow())
    return {
        'photos': gen.build_photos(sample),
        'files': gen.build_files(sample),
    }


class Mac:
    """
    A pretend Mac for one test: its own TMPDIR and HOME, so the work folder
    (``$TMPDIR/compress-photos-macos``) and the fallback folder
    (``~/Pictures/JPEG XL``) are the test's.
    """

    def __init__(self, root, shortcuts, photobatch):
        self.root = root
        self.shortcuts = shortcuts
        self.tmp = root / 'tmp'
        self.home = root / 'home'
        self.tmp.mkdir()
        self.home.mkdir()
        # the Photos shortcut's work folder (inside Shortcuts' iCloud Drive
        # folder) and the Finder shortcut's (in TMPDIR)
        self.icloud = (
            self.home
            / 'Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents'
        )
        self.icloud.mkdir(parents=True)
        self.work = self.icloud / 'compress-photos-macos'
        self.work_files = self.tmp / 'compress-photos-macos'
        # the selection route's: in ~/Pictures, where Photos' sandbox reaches
        self.selection_work = self.home / 'Pictures' / '.compress-photos-macos'
        (self.selection_work / 'in').mkdir(parents=True)
        # every route's log and progress-window script
        self.logdir = (
            self.home / 'Library' / 'Caches' / 'compress-photos-macos'
        )
        self.photobatch = photobatch
        # Compress Photos Helper's stand-in (fake_helper), if any: PHOTOEDITS
        self.photoedits = None

    def env(self, photobatch=None, watch=False):
        env = dict(
            os.environ,
            JXLBATCH=str(photobatch or self.photobatch),
            TMPDIR=f'{self.tmp}/',
            HOME=str(self.home),
            WATCH='1' if watch else '0',  # the Terminal progress window
            TZ='America/New_York',  # the Mac's time zone, for the dates
        )
        if self.photoedits:
            env['PHOTOEDITS'] = str(self.photoedits)

        if watch:
            # a fake `open` first on PATH records what the script opens
            fake = self.root / 'bin'
            fake.mkdir(exist_ok=True)
            (fake / 'open').write_text(
                f'#!/bin/sh\nprintf \'%s\\n\' "$@" >> "{self.root}/opened.txt"\n'
            )
            (fake / 'open').chmod(0o755)
            env['PATH'] = f'{fake}:{env["PATH"]}'

        return env

    # what the main script of each route contains
    MARKERS = {
        'photos': 'for f in "$@"; do',  # the picker route (files as input)
        'selection': 'in/*(.N)',  # the photos selected in Photos
        'files': 'paths=(',  # the Finder shortcut
    }

    def scripts(
            self,
            shortcut,
            quality='83',
            lines='',
            skipped='',
            fmt='jxl',
            cores='all',
            hdr='keep',
            dates='',
            meta='',
            bridge='',
    ):
        """The shortcut's Run Shell Script texts, variables filled in."""
        return ph.shell_scripts(
            self.shortcuts['photos' if shortcut == 'selection' else shortcut],
            {
                'Format': fmt,  # the format menu's value
                'Quality': quality,
                'Cores': cores,  # the cores menu's value
                'HDR': hdr,  # the HDR menu's value
                'Combined Text': lines,
                'Skipped Echo': skipped,
                'AppleScript Result': lines,  # the selection route's IDS
                # the picker route's dates in Photos; the selection route's
                # renderings' dates
                'Dates': dates,
                'Meta': meta,  # the picker route's locations
                'Bridge': bridge,  # bridge.applescript's answer
            },
        )

    def main_script(self, shortcut, **values):
        """The route's conversion script."""
        found = [
            s
            for s in self.scripts(shortcut, **values)
            if self.MARKERS[shortcut] in s
        ]
        assert len(found) == 1
        return found[0]

    def follow_ups(self, shortcut):
        """The route's log script and finish script, in order."""
        work = '/Pictures/.' if shortcut == 'selection' else 'iCloud~'
        scripts = self.scripts(shortcut)
        show_log = next(
            s
            for s in scripts
            if s.startswith('cat ') and f'{self.LOGS[shortcut]}.log' in s
        )
        finish = [
            s for s in scripts if 'Done. You can close' in s and work in s
        ]
        assert len(finish) == 1
        return [show_log, finish[0]]

    def run(self, script, *args, photobatch=None, stdin='', watch=False):
        """
        Runs a script as Shortcuts does: zsh, the files as arguments (or
        ``stdin`` for a script that reads its input).
        """
        return subprocess.run(
            ['zsh', '-c', script, 'zsh', *map(str, args)],
            env=self.env(photobatch, watch),
            input=stdin,
            capture_output=True,
            text=True,
        )

    # what photobatch reads, and so what may have a rendering
    READABLE = {'.heic', '.heif', '.hif', '.jpg', '.jpeg', '.png', '.jxl'}

    def renderings(self):
        """
        What Find Photos gives the selection route for photos that are all
        unedited: each exported still's bytes, named as Shortcuts names them
        (``IMG_0001.heic``, ``IMG_0002.jpeg``), in a folder of their own.
        """
        folder = self.root / 'renderings'
        folder.mkdir(exist_ok=True)
        files = []
        for f in sorted((self.selection_work / 'in').iterdir()):
            ext = f.suffix.lower()
            if ext in self.READABLE:
                ext = '.jpeg' if ext == '.jpg' else ext
                files.append(folder / (f.stem + ext))
                shutil.copyfile(f, files[-1])

        return files

    def batch(self, shortcut, *args, **values):
        """
        Runs the route's conversion script. The selection route gets
        ``renderings`` (by default ``self.renderings()``: every photo unedited)
        as its arguments, and ``bridge`` "BRIDGE n" for them.
        """
        if shortcut == 'selection' and not args:
            files = values.pop('renderings', None)
            args = self.renderings() if files is None else files
            values.setdefault('bridge', f'BRIDGE {len(args)}')

        result = self.run(self.main_script(shortcut, **values), *args)
        assert result.returncode == 0, result.stderr
        assert result.stderr == ''
        return result.stdout

    LOGS = {
        'photos': 'photos-picker',
        'selection': 'photos-selection',
        'files': 'files',
    }

    def log_file(self, shortcut='photos'):
        return self.logdir / f'{self.LOGS[shortcut]}.log'

    @property
    def log(self):
        """The picker route's log."""
        return self.log_file('photos').read_text()


@pytest.fixture
def mac(tmp_path, shortcuts, photobatch):
    return Mac(tmp_path, shortcuts, photobatch)


def photo(folder, fixture, name):
    folder.mkdir(parents=True, exist_ok=True)
    return shutil.copy(FIXTURES / fixture, folder / name)


def done_lines(mac):
    """The picker route's results: jxl_done.txt's lines in the work folder."""
    return (mac.work / 'jxl_done.txt').read_text().splitlines()


def test_photos_leaves_one_line_per_result_in_jxl_done(mac):
    # Two library photos; the shortcut passes their names (the first only,
    # here: the second falls back to the file's name, comma and all). The
    # results are jxl_done.txt's lines, which the shortcut reads with Get
    # File; the script prints nothing, since Shortcuts types a script's output
    # by its content and would take three or more lines whose names each have
    # a comma for a CSV file.
    a = photo(mac.root / 'in', 'hdr/o1.heic', 'IMG_0001.HEIC')
    b = photo(mac.root / 'in', 'hdr/not_iphone_o6.heic', 'Trip, day 2.HEIC')
    out = mac.batch(
        'photos',
        a,
        b,
        lines='IMG_0001.HEIC',
        skipped='echo "Skipped 1 video(s): only still photos are converted."',
    )
    assert out == ''
    assert done_lines(mac) == [
        'jxl_out_1.jxl|1|delete|IMG_0001.jxl',
        'jxl_out_2.jxl|2|delete|Trip, day 2.jxl',
    ]
    for line in done_lines(mac):
        assert os.path.getsize(mac.work / line.split('|')[0]) > 0

    # The work folder stays for the shortcut to read the files; the log has
    # what the shortcut skipped and what photobatch printed.
    assert (mac.work / 'jxl_job.txt').read_text() == (
        '1|IMG_0001.HEIC\n2|Trip, day 2.HEIC\n'
    )
    assert mac.log.startswith('Skipped 1 video(s): only still photos')
    assert 'Done: 2 of 2 converted' in mac.log
    assert '[1/2] IMG_0001' in mac.log


def test_photos_dates_go_to_photobatch(mac):
    # The picker route's Dates ("index|date", from Shortcuts' Format Date)
    # become jxl_dates.txt as they are; photobatch writes them into the copies.
    a = photo(mac.root / 'in', 'hdr/o1.heic', 'IMG_0001.HEIC')
    b = photo(mac.root / 'in', 'hdr/srgb.heic', 'IMG_0002.HEIC')
    mac.batch('photos', a, b, dates='2|2024-07-01T09:30:00-04:00')
    assert (mac.work / 'jxl_dates.txt').read_text() == (
        '2|2024-07-01T09:30:00-04:00\n'
    )
    first, second = (mac.work / line.split('|')[0] for line in done_lines(mac))
    assert 'ExifIFD:DateTimeOriginal' not in ph.exif_tags(first)
    assert ph.exif_tags(second)['ExifIFD:DateTimeOriginal'] == (
        '2024:07:01 09:30:00'
    )
    # none at all: no file
    shutil.rmtree(mac.work)
    mac.batch('photos', a)
    assert not (mac.work / 'jxl_dates.txt').exists()


def test_photos_locations_go_to_photobatch(mac):
    # The picker route's Meta ("index|gps|...", wf.photo_location) becomes
    # jxl_meta.txt as it is; photobatch writes the location into the copy, or
    # removes the file's.
    a = photo(mac.root / 'in', 'hdr/o1.heic', 'IMG_0001.HEIC')
    b = photo(mac.root / 'in', 'hdr/srgb.heic', 'IMG_0002.HEIC')
    meta = '1|gps|\n2|gps|48.8584,2.2945'
    mac.batch('photos', a, b, meta=meta)
    assert (mac.work / 'jxl_meta.txt').read_text() == meta + '\n'
    first, second = (mac.work / line.split('|')[0] for line in done_lines(mac))
    assert not ph.gps_of(first)
    assert ph.gps_of(second)['GPSLatitude'] == pytest.approx(48.8584)
    # none at all: no file
    shutil.rmtree(mac.work)
    mac.batch('photos', a)
    assert not (mac.work / 'jxl_meta.txt').exists()


def test_photos_follow_up_scripts_read_the_log_and_clean_up(mac):
    a = photo(mac.root / 'in', 'hdr/o1.heic', 'IMG_0001.HEIC')
    mac.batch('photos', a)
    show_log, finish = mac.follow_ups('photos')
    assert mac.run(show_log).stdout == mac.log
    assert mac.run(finish, stdin='outcome line').returncode == 0
    assert not mac.work.exists()
    # the log stays (the last run's, in ~/Library/Caches) with the outcome
    result = mac.run(show_log)
    assert result.returncode == 0
    assert result.stdout.rstrip().endswith('outcome line')


def test_photos_nothing_converted_prints_nothing(mac, gen):
    bad = mac.root / 'in' / 'notes.txt'
    bad.parent.mkdir()
    bad.write_text('not a photo')
    assert mac.batch('photos', bad) == ''
    assert not (mac.work / 'jxl_done.txt').exists()
    assert 'unsupported format' in mac.log
    assert re.search(gen.WARNINGS, mac.log)


def test_photos_without_input(mac, gen):
    assert mac.batch('photos') == ''
    assert 'ERROR: no photos to convert.' in mac.log


def test_photos_notes_a_missing_icloud_folder(mac, gen):
    shutil.rmtree(mac.icloud)
    a = photo(mac.root / 'in', 'hdr/o1.heic', 'IMG_0001.HEIC')
    assert mac.batch('photos', a) == ''
    assert done_lines(mac) == ['jxl_out_1.jxl|1|delete|IMG_0001.jxl']
    assert "! Shortcuts' iCloud Drive folder not found" in mac.log
    assert re.search(gen.WARNINGS, mac.log)


def test_warnings_pattern(gen):
    pattern = re.compile(gen.WARNINGS)
    for line in (
        '  ! HDR gain map not used (malformed gain map metadata)',
        'ERROR: cannot read jxl_job.txt',
        'Done: 1 of 2 converted in 3 s\n1 failed; see the messages above.',
        "x\n  ! Apple's HDR profile not found",
    ):
        assert pattern.search(line), line

    for line in (
        'Done: 2 of 2 converted in 3 s',
        '[1/2] IMG_0001\n  HEIF 64x48, HDR 3.5×\n  4 KB -> 1 KB (33%)',
        'Skipped 1 video(s): only still photos are converted.',
    ):
        assert not pattern.search(line), line


def test_encoder_missing_is_reported_in_the_log(mac):
    a = photo(mac.root / 'in', 'hdr/o1.heic', 'IMG_0001.HEIC')
    result = mac.run(mac.main_script('photos'), a, photobatch='/nonexistent')
    assert (result.returncode, result.stdout, result.stderr) == (0, '', '')
    assert 'ERROR: photobatch is not installed' in mac.log
    assert '~/.local/bin/photobatch' in mac.log
    assert 'README-mac.md' in mac.log


def test_encoder_of_another_version_is_noted(mac):
    fake = fake_photobatch(mac, version='0.0.1')
    a = photo(mac.root / 'in', 'hdr/o1.heic', 'IMG_0001.HEIC')
    result = mac.run(mac.main_script('photos'), a, photobatch=fake)
    assert result.returncode == 0
    assert f'! {fake} is not photobatch {VERSION}' in mac.log


def fake_photobatch(mac, version=VERSION):
    """
    A stand-in for photobatch that answers --version with ``version`` (the
    shortcut's own by default, so the script's check passes) and records its
    arguments in <root>/args.txt instead of converting.
    """
    fake = mac.root / 'photobatch'
    fake.write_text(
        '#!/bin/sh\n'
        'case "$1" in\n'
        f'  --version) echo "photobatch {version} (fake)";;\n'
        f'  *) printf \'%s\\n\' "$@" > "{mac.root}/args.txt";;\n'
        'esac\n'
    )
    fake.chmod(0o755)
    return fake


@pytest.mark.parametrize(
    ('cores', 'options'),
    [
        ('all', ['-j', '0']),  # several photos at a time, every core
        ('one', ['-j', '1', '-t', '1']),  # one photo at a time, one thread
        ('', ['-j', '0']),  # anything else: all cores
    ],
)
def test_cores_choice_becomes_photobatch_options(mac, cores, options):
    # The shortcut's second question (All cores / One core) reaches the
    # script as CORES; run.zsh turns it into photobatch's -j and -t.
    a = photo(mac.root / 'in', 'hdr/srgb.heic', 'IMG_0001.HEIC')
    result = mac.run(
        mac.main_script('photos', cores=cores),
        a,
        photobatch=fake_photobatch(mac),
    )
    assert result.returncode == 0, result.stderr
    args = (mac.root / 'args.txt').read_text().splitlines()
    assert args == [
        '--mac',
        '-q',
        '83',
        '-e',
        '7',
        *options,
        '-C',
        str(mac.work),
        'jxl_job.txt',
    ]


@pytest.mark.parametrize(
    ('hdr', 'options'),
    [
        ('keep', []),  # HDR photos become HDR (PQ) JPEG XL
        ('drop', ['--sdr']),  # every photo becomes SDR
        ('', []),  # anything else: keep
    ],
)
def test_hdr_choice_becomes_photobatch_option(mac, hdr, options):
    # The shortcut's third question (Keep HDR / Drop HDR) reaches the script
    # as HDR; run.zsh turns "drop" into photobatch --sdr.
    a = photo(mac.root / 'in', 'hdr/srgb.heic', 'IMG_0001.HEIC')
    result = mac.run(
        mac.main_script('photos', hdr=hdr), a, photobatch=fake_photobatch(mac)
    )
    assert result.returncode == 0, result.stderr
    args = (mac.root / 'args.txt').read_text().splitlines()
    assert args == [
        '--mac',
        '-q',
        '83',
        '-e',
        '7',
        '-j',
        '0',
        *options,
        '-C',
        str(mac.work),
        'jxl_job.txt',
    ]


def exported(mac, fixture, name):
    """A file as Photos exports it into the selection route's work folder."""
    return photo(mac.selection_work / 'in', fixture, name)


def test_selection_converts_exported_originals(mac):
    # Photos exported the originals; IDS maps file names to photo ids. A
    # Live Photo is a photo plus a .mov with the same name (skipped, as on
    # the iPhone), a video alone is skipped, other files are left to
    # photobatch.
    exported(mac, 'hdr/o1.heic', 'IMG_0001.HEIC')
    exported(mac, 'hdr/not_used_color.heic', 'IMG_0002.HEIC')
    exported(mac, 'hdr/srgb.heic', 'IMG_0003.HEIC')
    (mac.selection_work / 'in' / 'IMG_0003.mov').write_text('video')
    (mac.selection_work / 'in' / 'clip.MOV').write_text('video')
    (mac.selection_work / 'in' / 'notes.txt').write_text('not a photo')
    out = mac.batch(
        'selection',
        lines=(
            'A1|2024-01-01 17:00:00|IMG_0001.HEIC\n'
            'A2|2024-07-01 09:30:00|IMG_0002.HEIC\n'
            'A3|2024-01-03 10:00:00|IMG_0003.HEIC\n'
            'A4||clip.MOV\n'
        ),
    )
    folder = mac.selection_work / 'out'
    assert out.splitlines() == [
        f'{folder}/IMG_0001.jxl|A1|delete|IMG_0001.jxl|jxl,q=83',
        f'{folder}/IMG_0002.jxl|A2|keep|IMG_0002.jxl|jxl,q=83',
    ]
    assert sorted(p.name for p in folder.iterdir()) == [
        'IMG_0001.jxl',
        'IMG_0002.jxl',
    ]
    log = mac.log_file('selection').read_text()
    assert log.startswith(
        'Skipped 1 Live Photo(s), 1 video(s): only still photos are converted.'
    )
    assert '[3/3] notes.txt' in log and 'unsupported format' in log
    assert 'IMG_0003' not in (mac.selection_work / 'jxl_job.txt').read_text()
    # the exported originals are untouched for Photos' sake
    assert (mac.selection_work / 'in' / 'IMG_0001.HEIC').exists()


def test_selection_heic_copies_say_their_format_and_rf(mac):
    # The result line's keywords follow the format: HEIC copies get "heic"
    # and the chosen RF (common.zsh's KEYWORDS), for import.applescript to
    # set in Photos.
    exported(mac, 'hdr/srgb.heic', 'IMG_0001.HEIC')
    out = mac.batch(
        'selection',
        fmt='heic',
        quality='26',
        lines='A1|2024-01-01 17:00:00|IMG_0001.HEIC\nA1\tgps\t\n',
    )
    folder = mac.selection_work / 'out'
    assert out.splitlines() == [
        f'{folder}/IMG_0001.heic|A1|delete|IMG_0001.heic|heic,RF=26',
    ]
    assert (folder / 'IMG_0001.heic').exists()


def test_selection_gives_the_copies_their_dates_in_photos(mac):
    # Photos gives each photo's date on the Mac's clock (here New York's);
    # the script adds that zone's offset on that date (winter, summer), and
    # photobatch writes it into the copy's EXIF. A photo without one in IDS
    # (notes.txt) or with an empty one gets none, nor does a clock time in
    # the hour that repeats when daylight saving time ends (1:30 on
    # 2024-11-03 is 1:30 EDT and 1:30 EST): it is two moments.
    exported(mac, 'hdr/o1.heic', 'IMG_0001.HEIC')
    exported(mac, 'hdr/srgb.heic', 'IMG_0002.HEIC')
    exported(mac, 'hdr/srgb.heic', 'IMG_0003.HEIC')
    exported(mac, 'hdr/srgb.heic', 'IMG_0004.HEIC')
    mac.batch(
        'selection',
        lines=(
            'A1|2024-01-01 17:00:00|IMG_0001.HEIC\n'
            'A2|2024-07-01 09:30:00|IMG_0002.HEIC\n'
            'A3||IMG_0003.HEIC\n'
            'A4|2024-11-03 01:30:00|IMG_0004.HEIC\n'
        ),
    )
    assert (mac.selection_work / 'jxl_dates.txt').read_text() == (
        '1|2024-01-01T17:00:00-0500\n2|2024-07-01T09:30:00-0400\n'
    )
    folder = mac.selection_work / 'out'
    for name, taken, offset in [
        ('IMG_0001.jxl', '2024:01:01 17:00:00', '-05:00'),
        ('IMG_0002.jxl', '2024:07:01 09:30:00', '-04:00'),
    ]:
        tags = ph.exif_tags(folder / name)
        assert tags['ExifIFD:DateTimeOriginal'] == taken
        assert tags['ExifIFD:OffsetTimeOriginal'] == offset

    assert 'ExifIFD:DateTimeOriginal' not in ph.exif_tags(
        folder / 'IMG_0003.jxl'
    )
    log = mac.log_file('selection').read_text()
    assert 'date from Photos: 2024:01:01 17:00:00 -05:00' in log


def test_selection_gives_the_copies_what_else_photos_has(mac):
    # export.applescript's "id<tab>gps<tab>value" lines become jxl_meta.txt
    # by job index, the values as they are; photobatch writes them into the
    # copies. A line for an item not converted (a video) is dropped. The
    # title, caption and keywords stay in Photos (import.applescript): none is
    # written.
    exported(mac, 'hdr/o1.heic', 'IMG_0001.HEIC')
    exported(mac, 'hdr/srgb.heic', 'IMG_0002.HEIC')
    (mac.selection_work / 'in' / 'clip.MOV').write_text('video')
    mac.batch(
        'selection',
        lines=(
            'A1|2024-01-01 17:00:00|IMG_0001.HEIC\n'
            'A2|2024-07-01 09:30:00|IMG_0002.HEIC\n'
            'A3||clip.MOV\n'
            'A1\tgps\t40.758442,-73.829767,11.73\n'
            'A2\tgps\t\n'
            'A3\tgps\t40.5,-73.25\n'
        ),
    )
    assert (mac.selection_work / 'jxl_meta.txt').read_text() == (
        '1|gps|40.758442,-73.829767,11.73\n2|gps|\n'
    )
    folder = mac.selection_work / 'out'
    first = folder / 'IMG_0001.jxl'
    tags = ph.exif_tags(first)
    assert tags['GPS:GPSLatitude'] == pytest.approx(40.758442, abs=1e-7)
    assert tags['GPS:GPSAltitude'] == 11.73
    log = mac.log_file('selection').read_text()
    for field in ('title', 'caption', 'keywords'):
        assert f'{field} from Photos' not in log
        assert f'{field} removed' not in log


def test_selection_duplicate_names_get_no_id(mac, gen):
    # Two selected photos with one file name can't be told apart in the
    # export: neither gets an id (no albums, nothing collected), and the log
    # says so; a photo with a unique name is unaffected.
    exported(mac, 'hdr/srgb.heic', 'IMG_0001.HEIC')
    exported(mac, 'hdr/srgb.heic', 'IMG_0001 (1).HEIC')
    exported(mac, 'hdr/o1.heic', 'IMG_0002.HEIC')
    out = mac.batch(
        'selection',
        lines=(
            'A|2024-01-01 17:00:00|IMG_0001.HEIC\n'
            'B|2024-01-02 17:00:00|IMG_0001.HEIC\n'
            'C|2024-01-03 17:00:00|IMG_0002.HEIC\n'
            'A\tgps\t40.5,-73.25\n'
            'B\tgps\t41.5,-74.25\n'
            'C\tgps\t42.5,-75.25\n'
        ),
    )
    folder = mac.selection_work / 'out'
    assert out.splitlines() == [
        f'{folder}/IMG_0001 (1).jxl||delete|IMG_0001 (1).jxl|jxl,q=83',
        f'{folder}/IMG_0001.jxl||delete|IMG_0001.jxl|jxl,q=83',
        f'{folder}/IMG_0002.jxl|C|delete|IMG_0002.jxl|jxl,q=83',
    ]
    log = mac.log_file('selection').read_text()
    assert (
        log.count('! two or more selected photos are named IMG_0001.HEIC') == 1
    )
    assert re.search(gen.WARNINGS, log)
    # nor a date, nor anything else: only IMG_0002 (the third job) has one
    assert (mac.selection_work / 'jxl_dates.txt').read_text() == (
        '3|2024-01-03T17:00:00-0500\n'
    )
    assert (mac.selection_work / 'jxl_meta.txt').read_text() == (
        '3|gps|42.5,-75.25\n'
    )
    # nor can their renderings be told apart: converted from the originals
    assert (
        '! could not check 2 photo(s) for edits: converted from the original '
        'file(s), without edits made in Photos. Look at the copies before '
        'deleting the originals: IMG_0001 (1).HEIC, IMG_0001.HEIC'
    ) in log


def rendering(mac, fixture, name, folder='renderings'):
    """A file as Shortcuts' Find Photos gives it to the selection route."""
    return photo(mac.root / folder, fixture, name)


def staged(mac, index):
    """
    What photobatch converts for job ``index``: the file a link points to (an
    original), or ``copy_of`` the bytes of a file staged as a copy (an edited
    photo's rendering, which photobatch can't read where Shortcuts keeps it).
    """
    path = mac.selection_work / f'jxl_in_{index}.orig'
    if path.is_symlink():
        return pathlib.Path(os.readlink(path))

    return copy_of(path)


def copy_of(path):
    return ('a copy of', pathlib.Path(path).read_bytes())


EDITED = 'edited photo(s) are saved with their edits'
UNCHECKED = '! could not check'


def fake_helper(mac, access='3', check='ok|', create='created', whole=True):
    """
    Compress Photos Helper's stand-in (PHOTOEDITS, run directly): "check"
    answers each job with ``check`` ("ok|notes" or "no|reason") and writes its
    Adjustments.plist; "create" answers ``create`` with the id "NEW-<n>/L0/001"
    when the three files are there, and keeps what it got in edits.seen.
    ``whole``: False leaves out the answer's "end".
    """
    end = 'print end' if whole else ':'
    script = mac.root / 'photoedits-fake'
    script.write_text(f"""#!/bin/zsh
E=$2
h='photoedits 0.13.0-prototype protocol 1'
case $1 in
  check)
    {{ print -r -- $h; print 'access|{access}'
      while IFS='|' read -r n id; do
        [ -n "$n" ] || continue
        print '<plist/>' > "$E/$n/Adjustments.plist"
        print -r -- "$n|{check}"
      done < "$E/check.txt"
      {end}; }} > "$E/check.out";;
  create)
    {{ print -r -- $h; print 'access|{access}'
      while IFS='|' read -r n name; do
        [ -n "$n" ] || continue
        b=("$E/$n"/base.*(N))
        if [ -n "$b[1]" ] && [ -f "$E/$n/look.heic" ] && [ -f "$E/$n/Adjustments.plist" ]; then
          print -r -- "$n|{create}|NEW-$n/L0/001|"
        else
          print -r -- "$n|failed|files missing"
        fi
      done < "$E/create.txt"
      {end}; }} > "$E/create.out"
    cp -R "$E" "$E.seen";;
esac
""")
    script.chmod(0o755)
    mac.photoedits = script


def look(mac, index):
    """The bytes of the edited photo's look staged as job ``index``."""
    return copy_of(mac.selection_work / 'looks' / f'jxl_in_{index}.orig')


def seen(mac, n):
    """The folder the helper got for edited photo ``n`` (base, look, plist)."""
    return mac.logdir / 'edits.seen' / str(n)


@pytest.mark.parametrize(
    ('fmt', 'quality', 'ext', 'look_rf'),
    [('jxl', '83', 'jxl', '26'), ('heic', '24', 'heic', '24')],
)
def test_selection_saves_an_edited_photo_with_its_edit(
        mac, fmt, quality, ext, look_rf
):
    # Prototype: an edited photo's original is converted (the base, in the
    # chosen format) and Photos' rendering apart (the look, always HEIC); the
    # helper saves both with the edit record and answers the new photo's id,
    # which the result line carries ("id:..."), with the original's id. The
    # unedited photo goes as before. Photos' date and location reach both.
    fake_helper(mac)
    exported(mac, 'hdr/o6.heic', 'IMG_0001.HEIC')
    exported(mac, 'hdr/srgb.heic', 'IMG_0002.HEIC')
    edited = rendering(mac, 'hdr/edited_in_photos.heic', 'IMG_0001.heic')
    unedited = rendering(mac, 'hdr/srgb.heic', 'IMG_0002.heic')
    out = mac.batch(
        'selection',
        renderings=[edited, unedited],
        fmt=fmt,
        quality=quality,
        dates=('1|2024-01-01T17:00:00-05:00\n2|2024-07-01T09:30:00-04:00\n'),
        lines=(
            'A1|2024-01-01 17:00:00|IMG_0001.HEIC\n'
            'A2|2024-07-01 09:30:00|IMG_0002.HEIC\n'
            'A1\tgps\t40.758442,-73.829767\n'
        ),
    )
    assert staged(mac, 1) == mac.selection_work / 'in' / 'IMG_0001.HEIC'
    assert staged(mac, 2) == mac.selection_work / 'in' / 'IMG_0002.HEIC'
    assert look(mac, 1) == copy_of(edited)
    keywords = f'heic,RF={quality}' if fmt == 'heic' else f'jxl,q={quality}'
    first, second = out.splitlines()
    fields = first.split('|')
    assert fields[0] == 'id:NEW-1/L0/001' and fields[1] == 'A1'
    assert fields[3:] == [f'IMG_0001.{ext}', keywords]
    assert second.split('|')[1:4:2] == ['A2', f'IMG_0002.{ext}']
    # what the helper got: the base, the HEIC look, the edit record
    got = seen(mac, 1)
    assert sorted(p.name for p in got.iterdir()) == [
        'Adjustments.plist',
        f'base.{ext}',
        'look.heic',
        'original',
    ]
    assert (got / 'look.heic').read_bytes()[4:12] == b'ftypheic'
    tags = ph.exif_tags(got / f'base.{ext}')
    assert tags['GPS:GPSLatitude'] == pytest.approx(40.758442, abs=1e-7)
    looks = mac.selection_work / 'looks'
    assert (looks / 'jxl_dates.txt').read_text() == (
        '1|2024-01-01T17:00:00-0500\n'
    )
    assert (looks / 'jxl_meta.txt').read_text() == (
        '1|gps|40.758442,-73.829767\n'
    )
    log = mac.log_file('selection').read_text()
    assert (
        f'1 {EDITED}, which can be reverted in Photos (prototype): '
        'IMG_0001.HEIC'
    ) in log
    assert f'HEIC, RF {look_rf}' in log  # the looks' run
    # no "!" line of the script's own (photobatch's are indented)
    assert not re.search(r'^!', log, re.MULTILINE)


def test_selection_saves_a_jpeg_rendering_of_a_heic_as_its_look(mac):
    # An edit may come as a JPEG (Shortcuts names it .jpeg); photobatch reads
    # the format from the file, and the copy keeps the original's name.
    fake_helper(mac)
    exported(mac, 'hdr/srgb.heic', 'IMG_0001.HEIC')
    (mac.root / 'renderings').mkdir()
    edit = ph.noise_jpeg(mac.root / 'renderings' / 'IMG_0001.jpeg')
    out = mac.batch(
        'selection',
        renderings=[edit],
        lines='A1|2024-01-01 17:00:00|IMG_0001.HEIC\n',
    )
    assert out.split('|')[:4:3] == ['id:NEW-1/L0/001', 'IMG_0001.jxl']
    log = mac.log_file('selection').read_text()
    assert 'JPEG 320x240' in log and f'1 {EDITED}' in log


@pytest.mark.parametrize(
    'name',
    ['IMG_0001.heic', 'img_0001.heic', 'IMG_0001.HEIC', 'IMG_0001.jpeg'],
)
def test_selection_pairs_renderings_by_name_without_extension(mac, name):
    # Shortcuts names the files after the original, with its own extension
    # ("IMG_1711.JPG" came as "IMG_1711.jpeg" on macOS 27); case aside.
    fake_helper(mac)
    exported(mac, 'hdr/srgb.heic', 'IMG_0001.HEIC')
    r = rendering(mac, 'hdr/o1.heic', name)
    mac.batch(
        'selection',
        renderings=[r],
        lines='A1|2024-01-01 17:00:00|IMG_0001.HEIC\n',
    )
    assert look(mac, 1) == copy_of(r)


def test_selection_pairs_one_name_by_date(mac):
    # Two selected photos whose files share a name without extension (a HEIC
    # and a JPEG from two cameras): each rendering goes with the photo of its
    # date, to the second (Photos' AppleScript and Shortcuts' Date Taken give
    # the same; a second apart still counts).
    fake_helper(mac)
    exported(mac, 'hdr/srgb.heic', 'IMG_0001.HEIC')
    jpeg = ph.noise_jpeg(mac.selection_work / 'in' / 'IMG_0001.JPG')
    edit = rendering(mac, 'hdr/o1.heic', 'IMG_0001.heic')
    same = mac.root / 'renderings' / 'IMG_0001.jpeg'
    shutil.copyfile(jpeg, same)
    mac.batch(
        'selection',
        renderings=[same, edit],
        dates=('1|2024-02-02T08:00:00-05:00\n2|2024-01-01T17:00:01-05:00\n'),
        lines=(
            'A1|2024-01-01 17:00:00|IMG_0001.HEIC\n'
            'A2|2024-02-02 08:00:00|IMG_0001.JPG\n'
        ),
    )
    jobs = (mac.selection_work / 'jxl_job.txt').read_text().splitlines()
    by_name = {line.split('|')[1]: int(line.split('|')[0]) for line in jobs}
    assert staged(mac, by_name['IMG_0001.HEIC']) == (
        mac.selection_work / 'in' / 'IMG_0001.HEIC'
    )
    assert look(mac, 1) == copy_of(edit)
    assert staged(mac, by_name['IMG_0001.JPG']) == jpeg
    log = mac.log_file('selection').read_text()
    assert f'1 {EDITED}' in log and UNCHECKED not in log


@pytest.mark.parametrize(
    ('helper', 'said'),
    [
        (
            None,
            '! Compress Photos Helper is not installed (~/Applications): '
            '1 edited photo(s) not converted: IMG_0001.HEIC',
        ),
        (
            {'access': '2'},
            '! Compress Photos Helper has no full access to '
            'Photos (System Settings > Privacy & Security > Photos): 1 edited '
            'photo(s) not converted: IMG_0001.HEIC',
        ),
        (
            {'whole': False},
            '! Compress Photos Helper gave no answer: 1 edited '
            'photo(s) not converted: IMG_0001.HEIC',
        ),
        (
            {'check': 'no|Photos has no edit for it'},
            '! IMG_0001.HEIC: its '
            "edit can't be read (Photos has no edit for it): not converted",
        ),
        (
            {'create': 'failed'},
            "! IMG_0001.HEIC: Photos didn't take the copy "
            'with its edit (NEW-1/L0/001): not saved',
        ),
    ],
)
def test_selection_never_bakes_an_edit_in(mac, helper, said):
    # Prototype: an edited photo whose edit can't be kept gets no copy at all
    # (and so its original isn't collected), never one with the edit baked in
    # or without it; the log says why. The unedited photo goes as before.
    if helper is not None:
        fake_helper(mac, **helper)

    exported(mac, 'hdr/srgb.heic', 'IMG_0001.HEIC')
    exported(mac, 'hdr/o1.heic', 'IMG_0002.HEIC')
    out = mac.batch(
        'selection',
        renderings=[
            rendering(mac, 'hdr/o6.heic', 'IMG_0001.heic'),
            rendering(mac, 'hdr/o1.heic', 'IMG_0002.heic'),
        ],
        lines=(
            'A1|2024-01-01 17:00:00|IMG_0001.HEIC\n'
            'A2|2024-01-02 17:00:00|IMG_0002.HEIC\n'
        ),
    )
    assert [line.split('|')[1] for line in out.splitlines()] == ['A2']
    log = mac.log_file('selection').read_text()
    assert said in log


def test_selection_notes_what_may_not_come_out_right(mac):
    fake_helper(mac, check='ok|a Portrait photo: the copy has no depth data')
    exported(mac, 'hdr/srgb.heic', 'IMG_0001.HEIC')
    out = mac.batch(
        'selection',
        renderings=[rendering(mac, 'hdr/o6.heic', 'IMG_0001.heic')],
        lines='A1|2024-01-01 17:00:00|IMG_0001.HEIC\n',
    )
    assert out.startswith('id:NEW-1/L0/001|A1|')
    assert (
        'IMG_0001.HEIC (may not come out right: a Portrait photo: the copy '
        'has no depth data)'
    ) in mac.log_file('selection').read_text()


@pytest.mark.parametrize(
    'case', ['missing', 'two', 'other date', 'unreadable']
)
def test_selection_converts_an_unchecked_photo_from_its_original(mac, case):
    # A photo whose rendering is missing, or can't be told from another's, or
    # whose date is another, or that can't be read, is converted from its
    # original as before, and
    # the log says so (its original is collected all the same: the log opens).
    exported(mac, 'hdr/srgb.heic', 'IMG_0001.HEIC')
    exported(mac, 'hdr/srgb.heic', 'IMG_0002.HEIC')
    files = [rendering(mac, 'hdr/srgb.heic', 'IMG_0002.heic')]
    dates = ''
    if case == 'two':
        files += [
            rendering(mac, 'hdr/o1.heic', 'IMG_0001.heic', 'a'),
            rendering(mac, 'hdr/o6.heic', 'IMG_0001.heic', 'b'),
        ]
    elif case == 'other date':
        files.append(rendering(mac, 'hdr/o1.heic', 'IMG_0001.heic'))
        dates = '2|2024-01-01T18:00:00-05:00\n'
    elif case == 'unreadable':
        files.append(rendering(mac, 'hdr/o1.heic', 'IMG_0001.heic'))
        files[-1].chmod(0)

    out = mac.batch(
        'selection',
        renderings=files,
        dates=dates,
        lines=(
            'A1|2024-01-01 17:00:00|IMG_0001.HEIC\n'
            'A2|2024-01-02 17:00:00|IMG_0002.HEIC\n'
        ),
    )
    assert staged(mac, 1) == mac.selection_work / 'in' / 'IMG_0001.HEIC'
    assert staged(mac, 2) == mac.selection_work / 'in' / 'IMG_0002.HEIC'
    assert [line.split('|')[1] for line in out.splitlines()] == ['A1', 'A2']
    log = mac.log_file('selection').read_text()
    assert (
        '! could not check 1 photo(s) for edits: converted from the original '
        'file(s), without edits made in Photos. Look at the copies before '
        'deleting the originals: IMG_0001.HEIC'
    ) in log
    assert EDITED not in log


@pytest.mark.parametrize(
    ('bridge', 'why'),
    [
        (
            'ERROR: Photos could not fill the album Compress Photos (working) '
            '(-1728: no)',
            'ERROR: Photos could not fill the album Compress Photos (working) '
            '(-1728: no)',
        ),
        (
            'BRIDGE 2',
            'Shortcuts found no photos in the album Compress Photos (working)',
        ),
        (
            'BRIDGE 0',
            'Photos put none of them into the album Compress Photos (working)',
        ),
        ('', 'the album script gave no answer'),
    ],
)
def test_selection_without_renderings_converts_the_originals(
        mac, gen, bridge, why
):
    # No rendering at all: every photo is converted from its original, as
    # before 0.12.0, with one "!" line saying why.
    exported(mac, 'hdr/srgb.heic', 'IMG_0001.HEIC')
    exported(mac, 'hdr/o1.heic', 'IMG_0002.HEIC')
    out = mac.batch(
        'selection',
        renderings=[],
        bridge=bridge,
        lines=(
            'A1|2024-01-01 17:00:00|IMG_0001.HEIC\n'
            'A2|2024-01-02 17:00:00|IMG_0002.HEIC\n'
        ),
    )
    assert [line.split('|')[1] for line in out.splitlines()] == ['A1', 'A2']
    assert staged(mac, 1) == mac.selection_work / 'in' / 'IMG_0001.HEIC'
    log = mac.log_file('selection').read_text()
    assert (
        f'! could not check the photos for edits ({why}): edited photos are '
        'converted from their original files, without the edits. Look at the '
        'copies before deleting the originals.'
    ) in log
    assert log.count(UNCHECKED) == 1
    assert re.search(gen.WARNINGS, log)


def test_selection_pairs_a_rendering_with_one_photo_only(mac):
    # Two selected photos with one name without extension and the same date
    # (a camera's HEIC and JPEG of one shot) and a single rendering: it may be
    # either's, so neither takes it (else the JPEG's copy could get the HEIC's
    # edit under the JPEG's id).
    exported(mac, 'hdr/srgb.heic', 'IMG_0001.HEIC')
    jpeg = ph.noise_jpeg(mac.selection_work / 'in' / 'IMG_0001.JPG')
    edit = rendering(mac, 'hdr/o1.heic', 'IMG_0001.heic')
    mac.batch(
        'selection',
        renderings=[edit],
        dates='1|2024-01-01T17:00:00-05:00\n',
        lines=(
            'A1|2024-01-01 17:00:00|IMG_0001.HEIC\n'
            'A2|2024-01-01 17:00:00|IMG_0001.JPG\n'
        ),
    )
    jobs = (mac.selection_work / 'jxl_job.txt').read_text().splitlines()
    by_name = {line.split('|')[1]: int(line.split('|')[0]) for line in jobs}
    assert staged(mac, by_name['IMG_0001.HEIC']) == (
        mac.selection_work / 'in' / 'IMG_0001.HEIC'
    )
    assert staged(mac, by_name['IMG_0001.JPG']) == jpeg
    log = mac.log_file('selection').read_text()
    assert '! could not check 2 photo(s) for edits' in log
    assert EDITED not in log


def test_selection_unreadable_rendering_is_unchecked(mac):
    # cmp can't read it (here a folder where Shortcuts' file would be): the
    # photo is converted from its original, with the "!" line.
    exported(mac, 'hdr/srgb.heic', 'IMG_0001.HEIC')
    folder = mac.root / 'renderings' / 'IMG_0001.heic'
    folder.mkdir(parents=True)
    mac.batch(
        'selection',
        renderings=[folder],
        lines='A1|2024-01-01 17:00:00|IMG_0001.HEIC\n',
    )
    assert staged(mac, 1) == mac.selection_work / 'in' / 'IMG_0001.HEIC'
    log = mac.log_file('selection').read_text()
    assert '! could not check 1 photo(s) for edits' in log


def test_selection_names_photobatch_reads_but_the_check_does_not_know(mac):
    # A JPEG named ".jpe" is checked like any JPEG; one whose name the check
    # doesn't know (an exiftool backup, ".JPG_original") is still converted
    # by photobatch, which goes by the content, so the log says it wasn't
    # checked for edits.
    fake_helper(mac)
    ph.noise_jpeg(mac.selection_work / 'in' / 'scan.jpe')
    ph.noise_jpeg(mac.selection_work / 'in' / 'IMG_0002.jpg').rename(
        mac.selection_work / 'in' / 'IMG_0002.JPG_original'
    )
    edit = rendering(mac, 'hdr/o1.heic', 'scan.jpeg')
    out = mac.batch(
        'selection',
        renderings=[edit],
        lines=(
            'A1|2024-01-01 17:00:00|scan.jpe\n'
            'A2|2024-01-02 17:00:00|IMG_0002.JPG_original\n'
        ),
    )
    assert [line.split('|')[1] for line in out.splitlines()] == ['A2', 'A1']
    assert out.splitlines()[1].startswith('id:NEW-2/L0/001|A1|')
    assert look(mac, 1) == copy_of(edit)
    log = mac.log_file('selection').read_text()
    assert f'1 {EDITED}' in log and 'scan.jpe' in log
    assert (
        "! 1 photo(s) not checked for edits (a file type the check doesn't "
        'know): converted from the original file(s), without edits made in '
        'Photos. Look at the copies before deleting the originals: '
        'IMG_0002.JPG_original'
    ) in log


@pytest.mark.parametrize(
    ('answer', 'logged'),
    [
        ('CLOSED', None),
        (
            'ERROR: Photos could not delete the album Compress Photos '
            '(working) (-1728: no)',
            '(ERROR: Photos could not delete the album Compress Photos '
            '(working) (-1728: no))',
        ),
        ('', '(the album script gave no answer)'),
    ],
)
def test_selection_logs_an_album_photos_would_not_delete(mac, answer, logged):
    # After the conversion the album is deleted; should Photos refuse, the
    # log says so before the import (whose copies then join it too).
    (script,) = [
        s for s in mac.scripts('selection', lines=answer) if 'JXL_CLOSED' in s
    ]
    mac.logdir.mkdir(parents=True, exist_ok=True)
    mac.log_file('selection').write_text('')
    assert mac.run(script).returncode == 0
    log = mac.log_file('selection').read_text()
    if logged is None:
        assert log == ''
    else:
        assert log == (
            f'! could not delete the album Compress Photos (working) {logged}: '
            'Photos may add the copies to it too. Delete that album in Photos '
            '(its photos stay in the library).\n'
        )


def test_selection_never_converts_a_raw_photos_rendering(mac):
    # photobatch can't read a RAW: its rendering doesn't take its place, so it
    # fails as before and its original is never collected; nor is a video's,
    # or a Live Photo's still.
    raw = mac.selection_work / 'in' / 'IMG_0001.DNG'
    raw.write_text('raw')
    exported(mac, 'hdr/srgb.heic', 'IMG_0002.HEIC')
    (mac.selection_work / 'in' / 'IMG_0002.mov').write_text('video')
    files = [
        rendering(mac, 'hdr/o1.heic', 'IMG_0001.heic'),
        rendering(mac, 'hdr/o1.heic', 'IMG_0002.heic'),
    ]
    out = mac.batch(
        'selection',
        renderings=files,
        lines=(
            'A1|2024-01-01 17:00:00|IMG_0001.DNG\n'
            'A2|2024-01-02 17:00:00|IMG_0002.HEIC\n'
        ),
    )
    assert out == ''
    assert staged(mac, 1) == raw
    assert 'IMG_0002' not in (mac.selection_work / 'jxl_job.txt').read_text()
    log = mac.log_file('selection').read_text()
    assert 'unsupported format' in log
    assert EDITED not in log and UNCHECKED not in log


def test_selection_name_with_field_separators(mac):
    # A "|" in a photo's name would split the result line: photobatch names
    # the copy with "_" for it, and for ":", "/", "\" and control characters
    # (clean_name; test_encoder_cli's test_saved_names_are_safe), and the
    # exporter's "id|date|filename" line is read past its second "|", so the
    # photo still gets its id.
    exported(mac, 'hdr/srgb.heic', 'My|Photo: 1.HEIC')
    out = mac.batch(
        'selection', lines='A1|2024-01-01 17:00:00|My|Photo: 1.HEIC\n'
    )
    folder = mac.selection_work / 'out'
    assert out.splitlines() == [
        f'{folder}/My_Photo_ 1.jxl|A1|delete|My_Photo_ 1.jxl|jxl,q=83'
    ]
    assert (mac.selection_work / 'jxl_job.txt').read_text() == (
        '1|My|Photo: 1.HEIC\n'
    )


def test_selection_unknown_id_and_export_error(mac, gen):
    exported(mac, 'hdr/srgb.heic', 'IMG_0007 (1).HEIC')
    out = mac.batch('selection', lines='ERROR: Photos could not export\n')
    assert out.splitlines() == [
        f'{mac.selection_work}/out/IMG_0007 (1).jxl||delete|IMG_0007 (1).jxl|jxl,q=83'
    ]
    log = mac.log_file('selection').read_text()
    assert log.startswith('ERROR: Photos could not export')
    assert re.search(gen.WARNINGS, log)


def test_selection_nothing_exported(mac, gen):
    assert mac.batch('selection', lines='') == ''
    assert (
        'ERROR: no photos to convert.' in mac.log_file('selection').read_text()
    )


def test_selection_follow_up_scripts(mac):
    exported(mac, 'hdr/srgb.heic', 'IMG_0001.HEIC')
    mac.batch('selection', lines='A1|2024-01-01 17:00:00|IMG_0001.HEIC\n')
    assert (mac.selection_work / 'jxl_dates.txt').exists()
    show_log, finish = mac.follow_ups('selection')
    assert mac.run(show_log).stdout == mac.log_file('selection').read_text()
    assert mac.run(finish, stdin='outcome line').returncode == 0
    # in/ and the job files go; out/ stays (Photos may reference its files)
    assert not (mac.selection_work / 'in').exists()
    assert not list(mac.selection_work.glob('jxl_*'))
    assert (mac.selection_work / 'out' / 'IMG_0001.jxl').exists()
    assert (
        mac.log_file('selection').read_text().rstrip().endswith('outcome line')
    )


def test_progress_window_follows_the_log_and_ends_with_done(mac):
    # With WATCH=1 (the default), the script writes progress.command (a
    # `tail -f` of the log) and opens it in Terminal; the finish script
    # appends the outcome and "Done" and ends the tail.
    a = photo(mac.root / 'in', 'hdr/srgb.heic', 'IMG_0001.HEIC')
    result = mac.run(mac.main_script('photos'), a, watch=True)
    assert result.returncode == 0, result.stderr
    command = (mac.logdir / 'photos-picker.command').read_text()
    assert command.startswith('#!/bin/zsh\necho $$ > ')
    assert '\nexec tail -n +1 -f ' in command
    # zsh's (q) quoting escapes spaces and tildes
    assert str(mac.log_file('photos')) in command.replace('\\', '')
    assert (mac.root / 'opened.txt').read_text().splitlines() == [
        '-a',
        'Terminal',
        str(mac.logdir / 'photos-picker.command'),
    ]
    # a real tail, as the Terminal window would run it, with its pid recorded
    # as the .command does
    tail = subprocess.Popen(
        ['tail', '-n', '+1', '-f', str(mac.log_file('photos'))],
        stdout=subprocess.PIPE,
        text=True,
    )
    (mac.logdir / 'photos-picker.pid').write_text(f'{tail.pid}\n')
    try:
        finish = mac.follow_ups('photos')[1]
        assert (
            mac.run(finish, stdin='Saved 1 photo(s) to Photos.').returncode
            == 0
        )
        shown, _ = tail.communicate(timeout=10)
    finally:
        tail.kill()

    assert shown.rstrip().endswith(
        'Saved 1 photo(s) to Photos.\nDone. You can close this window.'
    )
    assert 'Done: 1 of 1 converted' in shown
    assert not mac.work.exists()


def test_no_progress_window_when_off(mac):
    a = photo(mac.root / 'in', 'hdr/srgb.heic', 'IMG_0001.HEIC')
    mac.batch('photos', a)
    assert not list(mac.logdir.glob('*.command'))
    assert not (mac.root / 'opened.txt').exists()


def test_files_progress_window_ends_in_the_script(mac):
    album = mac.root / 'Pictures'
    a = photo(album, 'hdr/srgb.heic', 'a.heic')
    result = mac.run(mac.main_script('files', lines=f'{a}\n'), a, watch=True)
    assert result.returncode == 0, result.stderr
    assert (mac.root / 'opened.txt').read_text().splitlines()[-1] == str(
        mac.logdir / 'files.command'
    )
    # the log ended with the count and "Done" before the folder went away
    assert 'Wrote 1 JPEG XL file(s).\nDone. You can close this window.' in (
        result.stdout
    )
    assert not (mac.logdir / 'files.command').exists()


def test_files_next_to_originals_folders_and_fallback(mac):
    # A file and a folder with their real paths (from Get Details of Files),
    # and a temporary copy whose location Shortcuts doesn't know.
    album = mac.root / 'My Photos'
    a = photo(album, 'heif/rotate_then_crop.heic', 'a b.heic')
    c = photo(album / 'sub', 'hdr/srgb.heic', 'c.HEIC')
    (album / 'sub' / 'notes.txt').write_text('not a photo')
    copy = photo(mac.tmp, 'hdr/o1.heic', 'copy.heic')
    out = mac.batch(
        'files',
        a,
        album / 'sub',
        copy,
        quality='72',
        lines=f'{a}\n{album / "sub"}\n',
    )
    lines = out.splitlines()
    assert lines[-1] == 'Wrote 3 JPEG XL file(s).'
    assert 'photobatch: 3 photos, quality 72' in out
    assert sorted(
        p.relative_to(mac.root) for p in mac.root.rglob('*.jxl')
    ) == [
        (album / 'a b.jxl').relative_to(mac.root),
        (album / 'sub' / 'c.jxl').relative_to(mac.root),
        (mac.home / 'Pictures' / 'JPEG XL' / 'copy.jxl').relative_to(mac.root),
    ]
    assert f'-> {album / "a b.jxl"}' in out
    # the folder's non-image file was never staged
    assert 'notes' not in out
    # the work folder is gone
    assert not mac.work_files.exists()
    assert c.exists() and a.exists()  # originals untouched


def test_files_never_replaces_a_file(mac):
    album = mac.root / 'Pictures'
    a = photo(album, 'hdr/srgb.heic', 'a.heic')
    (album / 'a.jxl').write_bytes(b'mine')
    for expected in ('a 2.jxl', 'a 3.jxl'):
        mac.batch('files', a, lines=f'{a}\n')
        assert (album / expected).exists()

    assert (album / 'a.jxl').read_bytes() == b'mine'


def test_files_converts_jpeg_xl_in_folders(mac):
    # A folder's JPEG XL photos are converted too (0.10.0); the copy of
    # "x.jxl" can't take its name, so it is "x 2.jxl", and the original stays.
    album = mac.root / 'Album'
    album.mkdir()
    ph.scene(320, 240, seed=5).save(mac.tmp / 'x.png')
    ph.run(['cjxl', mac.tmp / 'x.png', album / 'x.jxl', '-d', '0'], check=True)
    original = (album / 'x.jxl').read_bytes()
    photo(album, 'hdr/srgb.heic', 'b.heic')
    out = mac.batch('files', album, quality='72', lines=f'{album}\n')
    assert out.splitlines()[-1] == 'Wrote 2 JPEG XL file(s).'
    assert 'JPEG XL 320x240' in out
    assert sorted(p.name for p in album.iterdir()) == [
        'b.heic',
        'b.jxl',
        'x 2.jxl',
        'x.jxl',
    ]
    assert (album / 'x.jxl').read_bytes() == original


def test_files_name_and_place_from_the_real_path(mac):
    # Shortcuts may hand the script a renamed copy: the result still takes
    # the original's name and folder.
    album = mac.root / 'Pictures'
    album.mkdir()
    real = album / 'Holiday.HEIC'
    copy = photo(mac.tmp, 'hdr/srgb.heic', 'F3A1-2.heic')
    out = mac.batch('files', copy, lines=f'{real}\n')
    assert out.splitlines()[-1] == 'Wrote 1 JPEG XL file(s).'
    assert (album / 'Holiday.jxl').exists()
    assert not list(mac.tmp.glob('*.jxl'))


@pytest.mark.parametrize(
    ('fmt', 'options'),
    [
        ('heic', ['--heic', '--rf', '26']),  # HEIC: x265 at the RF
        ('jxl', ['-q', '26', '-e', '7']),  # JPEG XL at the quality
        ('', ['-q', '26', '-e', '7']),  # anything else: JPEG XL
    ],
)
def test_format_choice_becomes_photobatch_options(mac, fmt, options):
    # The shortcut's first question (HEIC / JPEG XL) reaches the script as
    # FORMAT with the chosen number in QUALITY; run.zsh turns them into
    # photobatch --heic --rf or -q -e.
    a = photo(mac.root / 'in', 'hdr/srgb.heic', 'IMG_0001.HEIC')
    result = mac.run(
        mac.main_script('photos', fmt=fmt, quality='26'),
        a,
        photobatch=fake_photobatch(mac),
    )
    assert result.returncode == 0, result.stderr
    args = (mac.root / 'args.txt').read_text().splitlines()
    assert args == [
        '--mac',
        *options,
        '-j',
        '0',
        '-C',
        str(mac.work),
        'jxl_job.txt',
    ]


def test_files_heic_route_writes_heic_next_to_originals(mac):
    # The HEIC route: .heic copies next to the originals, "Name 2.heic" when
    # a file is there, the fallback folder ~/Pictures/HEIC, and the count
    # names the format.
    album = mac.root / 'My Photos'
    a = photo(album, 'hdr/o1.heic', 'a b.heic')
    copy = photo(mac.tmp, 'hdr/srgb.heic', 'copy.heic')
    out = mac.batch('files', a, copy, fmt='heic', quality='30', lines=f'{a}\n')
    assert out.splitlines()[-1] == 'Wrote 2 HEIC file(s).'
    assert 'photobatch: 2 photos, HEIC, RF 30' in out
    assert (album / 'a b 2.heic').exists()  # "a b.heic" is the original
    assert (mac.home / 'Pictures' / 'HEIC' / 'copy.heic').exists()
    assert not list(mac.root.rglob('*.jxl'))
    mac.batch('files', a, fmt='heic', quality='30', lines=f'{a}\n')
    assert (album / 'a b 3.heic').exists()


def test_photos_heic_route_names_the_copies_heic(mac):
    # The picker route's lines for the shortcut (jxl_done.txt) end in the
    # copy's name with the HEIC extension.
    a = photo(mac.root / 'in', 'hdr/o1.heic', 'IMG_0001.HEIC')
    result = mac.run(
        mac.main_script(
            'photos', fmt='heic', quality='26', lines='IMG_0001.HEIC\n'
        ),
        a,
    )
    assert (result.returncode, result.stdout) == (0, ''), result.stderr
    assert done_lines(mac) == ['jxl_out_1.heic|1|delete|IMG_0001.heic']
    assert (mac.work / 'jxl_out_1.heic').exists()


def test_files_unwritable_folder_falls_back(mac):
    album = mac.root / 'Pictures'
    a = photo(album, 'hdr/srgb.heic', 'a.heic')
    album.chmod(0o555)
    try:
        mac.batch('files', a, lines=f'{a}\n')
    finally:
        album.chmod(0o755)

    assert (mac.home / 'Pictures' / 'JPEG XL' / 'a.jxl').exists()


def test_files_larger_copy_is_written_and_opens_no_log(mac, gen):
    # A copy not smaller than its original (a JPEG at lossless) is written
    # next to it like any other. The log has photobatch's note on one line
    # (run.zsh's COLUMNS=100 keeps it from wrapping, which FILE_WARNINGS's
    # lookahead needs: at photobatch's default width it would break after
    # "the") and the summary line; it matches WARNINGS, so the Photos
    # shortcut opens Quick Look, but not FILE_WARNINGS, so the Finder
    # shortcut doesn't.
    album = mac.root / 'My Photos'
    album.mkdir()
    a = ph.noise_jpeg(album / 'noise.jpg')
    out = mac.batch('files', a, quality='100', lines=f'{a}\n')
    assert out.splitlines()[-1] == 'Wrote 1 JPEG XL file(s).'
    size_in, size_out = a.stat().st_size, (album / 'noise.jxl').stat().st_size
    assert size_out > size_in
    log = mac.log_file('files').read_text()
    [note] = [line for line in log.splitlines() if ph.NOT_SMALLER in line]
    ph.check_not_smaller_note(note, size_in, size_out)
    assert ph.NOT_SMALLER_ONE in log.splitlines()
    assert re.search(gen.WARNINGS, log)
    assert not re.search(gen.FILE_WARNINGS, log)


def test_macos_encoder_output_identical_to_wasm(wasm, macos, tmp_path):
    """
    Same libraries, same settings: the Mac shortcuts' encoder writes the same
    bytes as the iPhone's, HDR included (libjxl's output doesn't depend on the
    thread count), also converting two photos at a time (-j 2, as the
    shortcuts' "All cores" may), and with dates, locations, titles, captions
    and keywords from Photos written into the EXIF and XMP.
    """
    fixtures = [
        FIXTURES / 'hdr' / 'o1.heic',
        FIXTURES / 'hdr' / 'edited_in_photos.heic',
        FIXTURES / 'hdr' / 'apple_older.heic',
        FIXTURES / 'hdr' / 'not_iphone_o6.heic',
        FIXTURES / 'heif' / 'rotate_then_crop.heic',
    ]
    results = {}
    for label, encoder, args in (
        ('wasm', wasm, []),
        ('macos', macos, []),
        ('macos-j2', macos, ['-j', '2']),
    ):
        folder = tmp_path / label
        folder.mkdir()
        ph.stage(folder, fixtures)
        (folder / 'jxl_dates.txt').write_text(
            '1|2024-01-01T17:00:00-05:00\n3|2022-02-02T10:00:00.250+09:00\n'
        )
        (folder / 'jxl_meta.txt').write_text(
            '1|gps|40.758441666667,-73.829766666667,11.730902867811\n'
            '2|gps|5e-05,-179.99999999\n3|gps|\n'
            '1|title|Caf\u00e9\n2|caption|Two%0Alines\n3|keywords|a,b%2Cc\n'
        )
        result = encoder.run(
            ['-q', '83', '-e', '7', *args, 'jxl_job.txt'], folder
        )
        assert result.returncode == 0, result.stdout
        results[label] = {
            p.name: p.read_bytes() for p in folder.glob('jxl_out_*.jxl')
        } | {'done': (folder / 'jxl_done.txt').read_text()}

    assert len(results['wasm']) == len(fixtures) + 1
    for label, got in results.items():
        assert got == results['wasm'], label
