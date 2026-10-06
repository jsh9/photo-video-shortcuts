"""
The Mac shortcuts' shell script (scripts/mac/*.zsh, as Run Shell Script gets
it), run for real with zsh and a jxlbatch build: staging, the result lines the
Photos shortcut saves, the files the Finder shortcut writes, the log, the
encoder checks, and the cores choice becoming jxlbatch's -j and -t. Also that
the macOS encoder's output is byte for byte the WebAssembly build's, also with
two photos at a time.
"""

import os
import re
import shutil
import subprocess

import photo_helpers as ph
import pytest

FIXTURES = ph.HERE / 'fixtures'
MACOS = ph.TOOL / 'dist' / 'jxlbatch-macos'
NATIVE = ph.TOOL / 'build' / 'jxlbatch'
VERSION = (ph.TOOL / 'VERSION').read_text().strip()


@pytest.fixture(scope='module')
def jxlbatch():
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

    def __init__(self, root, shortcuts, jxlbatch):
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
        self.jxlbatch = jxlbatch

    def env(self, jxlbatch=None, watch=False):
        env = dict(
            os.environ,
            JXLBATCH=str(jxlbatch or self.jxlbatch),
            TMPDIR=f'{self.tmp}/',
            HOME=str(self.home),
            WATCH='1' if watch else '0',  # the Terminal progress window
        )
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
            cores='all',
            hdr='keep',
    ):
        """The shortcut's Run Shell Script texts, variables filled in."""
        return ph.shell_scripts(
            self.shortcuts['photos' if shortcut == 'selection' else shortcut],
            {
                'Matches': quality,
                'Cores': cores,  # the cores menu's value
                'HDR': hdr,  # the HDR menu's value
                'Combined Text': lines,
                'Skipped Echo': skipped,
                'AppleScript Result': lines,  # the selection route's IDS
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

    def run(self, script, *args, jxlbatch=None, stdin='', watch=False):
        """
        Runs a script as Shortcuts does: zsh, the files as arguments (or
        ``stdin`` for a script that reads its input).
        """
        return subprocess.run(
            ['zsh', '-c', script, 'zsh', *map(str, args)],
            env=self.env(jxlbatch, watch),
            input=stdin,
            capture_output=True,
            text=True,
        )

    def batch(self, shortcut, *args, **values):
        """Runs the route's conversion script."""
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
def mac(tmp_path, shortcuts, jxlbatch):
    return Mac(tmp_path, shortcuts, jxlbatch)


def photo(folder, fixture, name):
    folder.mkdir(parents=True, exist_ok=True)
    return shutil.copy(FIXTURES / fixture, folder / name)


def test_photos_prints_one_line_per_result_with_the_path(mac):
    # Two library photos; the shortcut passes their names (the first only,
    # here: the second falls back to the file's name).
    a = photo(mac.root / 'in', 'hdr/o1.heic', 'IMG_0001.HEIC')
    b = photo(mac.root / 'in', 'hdr/not_iphone_o6.heic', 'IMG_0002.HEIC')
    out = mac.batch(
        'photos',
        a,
        b,
        lines='IMG_0001.HEIC',
        skipped='echo "Skipped 1 video(s): only still photos are converted."',
    )
    assert out.splitlines() == [
        'jxl_out_1.jxl|1|delete|IMG_0001.jxl',
        'jxl_out_2.jxl|2|delete|IMG_0002.jxl',
    ]
    for line in out.splitlines():
        assert os.path.getsize(mac.work / line.split('|')[0]) > 0

    # The work folder stays for the shortcut to read the files; the log has
    # what the shortcut skipped and what jxlbatch printed.
    assert (mac.work / 'jxl_job.txt').read_text() == (
        '1|IMG_0001.HEIC\n2|IMG_0002.HEIC\n'
    )
    assert mac.log.startswith('Skipped 1 video(s): only still photos')
    assert 'Done: 2 of 2 converted' in mac.log
    assert '[1/2] IMG_0001' in mac.log


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
    assert 'unsupported format' in mac.log
    assert re.search(gen.WARNINGS, mac.log)


def test_photos_without_input(mac, gen):
    assert mac.batch('photos') == ''
    assert 'ERROR: no photos to convert.' in mac.log


def test_photos_notes_a_missing_icloud_folder(mac, gen):
    shutil.rmtree(mac.icloud)
    a = photo(mac.root / 'in', 'hdr/o1.heic', 'IMG_0001.HEIC')
    assert mac.batch('photos', a).strip() == (
        'jxl_out_1.jxl|1|delete|IMG_0001.jxl'
    )
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
    result = mac.run(mac.main_script('photos'), a, jxlbatch='/nonexistent')
    assert (result.returncode, result.stdout, result.stderr) == (0, '', '')
    assert 'ERROR: jxlbatch is not installed' in mac.log
    assert '~/.local/bin/jxlbatch' in mac.log
    assert 'README-mac.md' in mac.log


def test_encoder_of_another_version_is_noted(mac):
    fake = fake_jxlbatch(mac, version='0.0.1')
    a = photo(mac.root / 'in', 'hdr/o1.heic', 'IMG_0001.HEIC')
    result = mac.run(mac.main_script('photos'), a, jxlbatch=fake)
    assert result.returncode == 0
    assert f'! {fake} is not jxlbatch {VERSION}' in mac.log


def fake_jxlbatch(mac, version=VERSION):
    """
    A stand-in for jxlbatch that answers --version with ``version`` (the
    shortcut's own by default, so the script's check passes) and records its
    arguments in <root>/args.txt instead of converting.
    """
    fake = mac.root / 'jxlbatch'
    fake.write_text(
        '#!/bin/sh\n'
        'case "$1" in\n'
        f'  --version) echo "jxlbatch {version} (fake)";;\n'
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
def test_cores_choice_becomes_jxlbatch_options(mac, cores, options):
    # The shortcut's second question (All cores / One core) reaches the
    # script as CORES; run.zsh turns it into jxlbatch's -j and -t.
    a = photo(mac.root / 'in', 'hdr/srgb.heic', 'IMG_0001.HEIC')
    result = mac.run(
        mac.main_script('photos', cores=cores), a, jxlbatch=fake_jxlbatch(mac)
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
def test_hdr_choice_becomes_jxlbatch_option(mac, hdr, options):
    # The shortcut's third question (Keep HDR / Drop HDR) reaches the script
    # as HDR; run.zsh turns "drop" into jxlbatch --sdr.
    a = photo(mac.root / 'in', 'hdr/srgb.heic', 'IMG_0001.HEIC')
    result = mac.run(
        mac.main_script('photos', hdr=hdr), a, jxlbatch=fake_jxlbatch(mac)
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
    # jxlbatch.
    exported(mac, 'hdr/o1.heic', 'IMG_0001.HEIC')
    exported(mac, 'hdr/not_used_color.heic', 'IMG_0002.HEIC')
    exported(mac, 'hdr/srgb.heic', 'IMG_0003.HEIC')
    (mac.selection_work / 'in' / 'IMG_0003.mov').write_text('video')
    (mac.selection_work / 'in' / 'clip.MOV').write_text('video')
    (mac.selection_work / 'in' / 'notes.txt').write_text('not a photo')
    out = mac.batch(
        'selection',
        lines='A1|IMG_0001.HEIC\nA2|IMG_0002.HEIC\nA3|IMG_0003.HEIC\nA4|clip.MOV\n',
    )
    folder = mac.selection_work / 'out'
    assert out.splitlines() == [
        f'{folder}/IMG_0001.jxl|A1|delete|IMG_0001.jxl',
        f'{folder}/IMG_0002.jxl|A2|keep|IMG_0002.jxl',
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


def test_selection_duplicate_names_get_no_id(mac, gen):
    # Two selected photos with one file name can't be told apart in the
    # export: neither gets an id (no albums, nothing collected), and the log
    # says so; a photo with a unique name is unaffected.
    exported(mac, 'hdr/srgb.heic', 'IMG_0001.HEIC')
    exported(mac, 'hdr/srgb.heic', 'IMG_0001 (1).HEIC')
    exported(mac, 'hdr/o1.heic', 'IMG_0002.HEIC')
    out = mac.batch(
        'selection',
        lines='A|IMG_0001.HEIC\nB|IMG_0001.HEIC\nC|IMG_0002.HEIC\n',
    )
    folder = mac.selection_work / 'out'
    assert out.splitlines() == [
        f'{folder}/IMG_0001 (1).jxl||delete|IMG_0001 (1).jxl',
        f'{folder}/IMG_0001.jxl||delete|IMG_0001.jxl',
        f'{folder}/IMG_0002.jxl|C|delete|IMG_0002.jxl',
    ]
    log = mac.log_file('selection').read_text()
    assert (
        log.count('! two or more selected photos are named IMG_0001.HEIC') == 1
    )
    assert re.search(gen.WARNINGS, log)


def test_selection_unknown_id_and_export_error(mac, gen):
    exported(mac, 'hdr/srgb.heic', 'IMG_0007 (1).HEIC')
    out = mac.batch('selection', lines='ERROR: Photos could not export\n')
    assert out.splitlines() == [
        f'{mac.selection_work}/out/IMG_0007 (1).jxl||delete|IMG_0007 (1).jxl'
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
    mac.batch('selection', lines='A1|IMG_0001.HEIC\n')
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
    assert 'jxlbatch: 3 photos, quality 72' in out
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


def test_files_unwritable_folder_falls_back(mac):
    album = mac.root / 'Pictures'
    a = photo(album, 'hdr/srgb.heic', 'a.heic')
    album.chmod(0o555)
    try:
        mac.batch('files', a, lines=f'{a}\n')
    finally:
        album.chmod(0o755)

    assert (mac.home / 'Pictures' / 'JPEG XL' / 'a.jxl').exists()


def test_macos_encoder_output_identical_to_wasm(wasm, macos, tmp_path):
    """
    Same libraries, same settings: the Mac shortcuts' encoder writes the same
    bytes as the iPhone's, HDR included (libjxl's output doesn't depend on the
    thread count), also converting two photos at a time (-j 2, as the
    shortcuts' "All cores" may).
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
