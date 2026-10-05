"""Fixtures for the Compress Videos tests (macOS: they use AVFoundation)."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import video_helpers as vh  # noqa: E402

TOOL = vh.TOOL


def built(path):
    """
    ``path`` if build-macos.sh has made it; else the test is skipped locally
    and fails in CI.
    """
    vh.need(
        path.exists(),
        f'{path} is missing: run shortcuts/compress-videos/scripts/build-macos.sh',
    )
    return path


@pytest.fixture(scope='session')
def version():
    """The tool's VERSION, shared by its binaries and its shortcut."""
    return vh.VERSION


@pytest.fixture(scope='session')
def vidmeta():
    """The helper built with the address and undefined-behavior sanitizers."""
    return built(TOOL / 'build' / 'vidmeta')


@pytest.fixture(scope='session')
def vidmeta_release():
    """The helper as released (dist/vidmeta-macos)."""
    return built(TOOL / 'dist' / 'vidmeta-macos')


@pytest.fixture(scope='session')
def gen():
    return vh.load_generator()


@pytest.fixture(scope='session')
def vf(gen):
    return sys.modules['vf']  # the generator's own


@pytest.fixture(scope='session')
def sample(vf):
    return vf.Sample(vf.guessed_workflow())


@pytest.fixture(scope='session')
def actions(gen, sample):
    return gen.build(sample)


@pytest.fixture(scope='session')
def tools(vidmeta):
    """
    The real ffmpeg and ffprobe the conversions use: ours (dist/), or the one
    the FFMPEG environment variable names (Homebrew's, say; CI runs both), with
    the ffprobe next to it; and vidmeta with the sanitizers.
    """
    if os.environ.get('FFMPEG'):
        ffmpeg = Path(os.environ['FFMPEG'])
        ffprobe = ffmpeg.with_name('ffprobe')
    else:
        ffmpeg = built(TOOL / 'dist' / 'ffmpeg-macos')
        ffprobe = built(TOOL / 'dist' / 'ffprobe-macos')

    vh.need(ffmpeg.exists() and ffprobe.exists(), f'{ffmpeg} is missing')
    return {'ffmpeg': ffmpeg, 'ffprobe': ffprobe, 'vidmeta': vidmeta}


@pytest.fixture(scope='session')
def helpers(tmp_path_factory):
    """The Swift helpers, compiled once: make_video and avmeta."""
    folder = tmp_path_factory.mktemp('helpers')
    return {
        name: vh.compile_swift(vh.HERE / f'{name}.swift', folder / name)
        for name in ('make_video', 'avmeta')
    }


@pytest.fixture(scope='session')
def videos(tmp_path_factory, helpers):
    """The test videos (video_helpers.VIDEOS), written once: {name: path}."""
    return vh.make_videos(
        tmp_path_factory.mktemp('videos'), helpers['make_video']
    )
