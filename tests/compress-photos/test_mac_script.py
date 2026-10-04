"""
The Mac shortcuts' shell script (scripts/mac/*.zsh, as Run Shell Script gets
it), run for real with zsh and a jxlbatch build: staging, the result lines the
Photos shortcut saves, the files the Finder shortcut writes, the log, and the
encoder checks. Also that the macOS encoder's output is byte for byte the
WebAssembly build's.
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
        self.work = self.tmp / 'compress-photos-macos'
        self.jxlbatch = jxlbatch

    def env(self, jxlbatch=None):
        return dict(
            os.environ,
            JXLBATCH=str(jxlbatch or self.jxlbatch),
            TMPDIR=f'{self.tmp}/',
            HOME=str(self.home),
        )

    def scripts(self, shortcut, quality='83', lines='', skipped=''):
        """The shortcut's Run Shell Script texts, variables filled in."""
        return ph.shell_scripts(
            self.shortcuts[shortcut],
            {
                'Matches': quality,
                'Combined Text': lines,
                'Skipped Echo': skipped,
            },
        )

    def run(self, script, *args, jxlbatch=None):
        """Runs a script as Shortcuts does: zsh, the files as arguments."""
        return subprocess.run(
            ['zsh', '-c', script, 'zsh', *map(str, args)],
            env=self.env(jxlbatch),
            capture_output=True,
            text=True,
        )

    def batch(self, shortcut, *args, **values):
        """The shortcut's main script (the one with the photos as input)."""
        result = self.run(self.scripts(shortcut, **values)[0], *args)
        assert result.returncode == 0, result.stderr
        assert result.stderr == ''
        return result.stdout

    @property
    def log(self):
        return (self.work / 'jxl_log.txt').read_text()


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
        f'{mac.work}/jxl_out_1.jxl|1|delete|IMG_0001.jxl',
        f'{mac.work}/jxl_out_2.jxl|2|delete|IMG_0002.jxl',
    ]
    for line in out.splitlines():
        path = line.split('|')[0]
        assert os.path.getsize(path) > 0

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
    _, show_log, cleanup = mac.scripts('photos')
    assert mac.run(show_log).stdout == mac.log
    assert mac.run(cleanup).returncode == 0
    assert not mac.work.exists()
    # the log script after cleanup: nothing, and no error
    result = mac.run(show_log)
    assert (result.returncode, result.stdout) == (0, '')


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
    result = mac.run(mac.scripts('photos')[0], a, jxlbatch='/nonexistent')
    assert (result.returncode, result.stdout, result.stderr) == (0, '', '')
    assert 'ERROR: jxlbatch is not installed' in mac.log
    assert '~/.local/bin/jxlbatch' in mac.log
    assert 'README-mac.md' in mac.log


def test_encoder_of_another_version_is_noted(mac):
    fake = mac.root / 'jxlbatch'
    fake.write_text('#!/bin/sh\necho "jxlbatch 0.0.1 (fake)"\n')
    fake.chmod(0o755)
    a = photo(mac.root / 'in', 'hdr/o1.heic', 'IMG_0001.HEIC')
    result = mac.run(mac.scripts('photos')[0], a, jxlbatch=fake)
    assert result.returncode == 0
    assert f'! {fake} is not jxlbatch {VERSION}' in mac.log


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
    assert not mac.work.exists()
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
    thread count).
    """
    fixtures = [
        FIXTURES / 'hdr' / 'o1.heic',
        FIXTURES / 'hdr' / 'edited_in_photos.heic',
        FIXTURES / 'hdr' / 'apple_older.heic',
        FIXTURES / 'hdr' / 'not_iphone_o6.heic',
        FIXTURES / 'heif' / 'rotate_then_crop.heic',
    ]
    results = {}
    for encoder in (wasm, macos):
        folder = tmp_path / encoder.name
        folder.mkdir()
        ph.stage(folder, fixtures)
        result = encoder.run(['-q', '83', '-e', '7', 'jxl_job.txt'], folder)
        assert result.returncode == 0, result.stdout
        results[encoder.name] = {
            p.name: p.read_bytes() for p in folder.glob('jxl_out_*.jxl')
        } | {'done': (folder / 'jxl_done.txt').read_text()}

    assert len(results[wasm.name]) == len(fixtures) + 1
    assert results[wasm.name] == results[macos.name]
