"""
Helpers for the Compress Videos tests: the generator, test videos written by
make_video.swift, running the Mac shortcut's conversion script as Shortcuts
does (in a pretend home folder, with the real tools or stand-ins), and what
ffprobe and AVFoundation (avmeta.swift) read in the results.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_TESTS = str(Path(__file__).resolve().parents[1])
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

import shortcut_helpers  # noqa: E402
from shortcut_helpers import (  # noqa: E402, F401
    compile_swift,
    ident,
    inside_if_on,
    need,
    params,
    references,
    render,
    run,
    shell_scripts,
    walk,
)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TOOL = REPO / 'shortcuts' / 'compress-videos'
VERSION = (TOOL / 'VERSION').read_text(encoding='utf-8').strip()
DIST = TOOL / 'dist'

# The test videos: make_video.swift's options. All 320x180, 2 s at 30 fps with
# stereo AAC and Apple's keys, unless said otherwise.
VIDEOS = {
    'sdr': ['--rotate', '90'],  # 8-bit, a vertical video's rotation flag
    'hlg': ['--hlg'],  # 10-bit HLG (and Dolby Vision 8.4 on macOS 27)
    'slomo': ['--fps', '120', '--seconds', '1', '--slomo'],  # marked slo-mo
    'fast': ['--fps', '120', '--seconds', '1'],  # 120 fps, played at that rate
    'two': ['--audio', 'surround,stereo', '--seconds', '1'],
    'silent': ['--audio', 'none', '--seconds', '1'],
    'big': ['--size', '1920x1080', '--seconds', '1', '--rotate', '90'],
    'four_three': ['--size', '1600x1200', '--seconds', '0.5'],
    'ntsc': ['--fps', '29.97', '--seconds', '1'],
    'bare': ['--no-keys', '--seconds', '1'],
}
# The keys an iPhone 17 Pro writes (docs/compress-videos-mac-design.md, 4.5),
# as AVFoundation reads them: identifier -> data type.
UTF8 = 'com.apple.metadata.datatype.UTF-8'
MOVIE_KEYS = {
    'mdta/com.apple.quicktime.creationdate': UTF8,
    'mdta/com.apple.quicktime.location.ISO6709': UTF8,
    'mdta/com.apple.quicktime.location.accuracy.horizontal': UTF8,
    'mdta/com.apple.quicktime.make': UTF8,
    'mdta/com.apple.quicktime.model': UTF8,
    'mdta/com.apple.quicktime.software': UTF8,
    'mdta/com.apple.quicktime.full-frame-rate-playback-intent': 'com.apple.metadata.datatype.int64',
    'mdta/com.apple.quicktime.metadata.1': 'com.apple.metadata.datatype.int8',
}
TRACK_KEYS = {
    'mdta/com.apple.quicktime.camera.lens_model (en-US)': UTF8,
    'mdta/com.apple.quicktime.camera.focal_length.35mm_equivalent (en-US)': UTF8,
    'mdta/com.apple.quicktime.camera.lens_irisfnumber (en-US)': UTF8,
    'mdta/com.apple.quicktime.apple-maker-note.74': 'com.apple.metadata.datatype.int32',
    'mdta/com.apple.quicktime.apple-maker-note.97': 'com.apple.metadata.datatype.int32',
}


def load_generator(name='build_mac_shortcuts'):
    """scripts/<name>.py (build_mac_shortcuts or vf) as a module."""
    return shortcut_helpers.load_generator(TOOL / 'scripts', name)


def make_videos(folder, make_video, names=None):
    """The test videos (VIDEOS, or ``names`` of them): {name: path}."""
    folder.mkdir(parents=True, exist_ok=True)
    made = {}
    for name in names or VIDEOS:
        path = folder / f'{name}.mov'
        result = run([make_video, path, *VIDEOS[name]])
        assert result.returncode == 0, result.stderr
        made[name] = path

    return made


def ffprobe_streams(ffprobe, path):
    """ffprobe's streams of a file (JSON), with their side data."""
    result = run([
        ffprobe,
        '-v',
        'error',
        '-show_streams',
        '-show_format',
        '-of',
        'json',
        path,
    ])
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def avmeta(helper, path):
    """What AVFoundation reads (avmeta.swift)."""
    result = run([helper, path])
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def homebrew(tool):
    """Homebrew's ffmpeg or ffprobe (with every decoder, for checking)."""
    for folder in ('/opt/homebrew/bin', '/usr/local/bin'):
        path = Path(folder) / tool
        if path.exists():
            return path

    return None


class Mac:
    """
    A pretend Mac for one test: its own home folder, where Photos "exported"
    the originals (``export``) into the shortcut's work folder, and the
    shortcut's conversion script, run as Run Shell Script runs it (zsh), with
    ``tools`` (ffmpeg, ffprobe, vidmeta: real ones or stand-ins).
    """

    def __init__(self, root, actions, tools):
        self.root = root
        self.actions = actions
        self.tools = tools
        self.home = root / 'home'
        self.work = self.home / 'Pictures' / '.compress-videos-macos'
        (self.work / 'in').mkdir(parents=True)
        self.logdir = (
            self.home / 'Library' / 'Caches' / 'compress-videos-macos'
        )

    def export(self, source, name):
        """A file as Photos exports it into the work folder's in/."""
        dest = self.work / 'in' / name
        shutil.copy(source, dest)
        return dest

    def env(self, watch=False, path=None, **extra):
        env = dict(
            os.environ,
            HOME=str(self.home),
            WATCH='1' if watch else '0',
            FFMPEG=str(self.tools['ffmpeg']),
            FFPROBE=str(self.tools['ffprobe']),
            VIDMETA=str(self.tools['vidmeta']),
            **extra,
        )
        if path:
            env['PATH'] = f'{path}:{env["PATH"]}'

        return env

    def scripts(self, ids='', **settings):
        """The shortcut's Run Shell Script texts, variables filled in."""
        values = {
            'Codec': 'h265',
            'Preset': 'medium',
            'Tune': 'none',
            'RF': '24',
            'Size': '2K',
            'Audio': '160',
            'Reuse': '',
            'AppleScript Result': ids,
            'Matches': '1',  # the number of items selected in Photos
        }
        values.update(settings)
        return shell_scripts(self.actions, values)

    def conversion(self, ids='', **settings):
        found = [
            s for s in self.scripts(ids, **settings) if 'vid_done.txt' in s
        ]
        assert len(found) == 1
        return found[0]

    def follow_ups(self):
        """The log script, the skipped script and the finish script."""
        scripts = self.scripts()
        show_log = next(
            s for s in scripts if s.startswith('cat ') and 'videos.log' in s
        )
        skipped = next(
            s
            for s in scripts
            if 'vid_skipped.txt' in s and s.startswith('cat ')
        )
        finish = next(s for s in scripts if 'Done. You can close' in s)
        return show_log, skipped, finish

    def run(self, script, stdin='', watch=False, path=None, **extra):
        return subprocess.run(
            ['zsh', '-c', script, 'zsh'],
            env=self.env(watch, path, **extra),
            input=stdin,
            capture_output=True,
            text=True,
        )

    def convert(self, ids='', watch=False, path=None, env=None, **settings):
        """Runs the conversion script; returns its output lines."""
        result = self.run(
            self.conversion(ids, **settings),
            watch=watch,
            path=path,
            **(env or {}),
        )
        assert result.returncode == 0, result.stderr
        assert result.stderr == '', result.stderr
        return result.stdout.splitlines()

    @property
    def log(self):
        return (self.logdir / 'videos.log').read_text()

    @property
    def skipped(self):
        path = self.work / 'vid_skipped.txt'
        return path.read_text().strip() if path.exists() else ''
