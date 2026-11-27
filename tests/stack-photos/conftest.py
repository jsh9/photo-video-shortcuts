"""Fixtures for the Stack Photos tests."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stack_helpers as sh  # noqa: E402


@pytest.fixture(scope='session')
def gen():
    return sh.load_generator()


@pytest.fixture(scope='session')
def actions(gen):
    return gen.build(gen.Sample(gen.wfkit.guessed_workflow()))


@pytest.fixture(scope='session')
def imageio(tmp_path_factory):
    """imageio.swift, compiled once (macOS)."""
    folder = tmp_path_factory.mktemp('helpers')
    return sh.compile_swift(sh.HERE / 'imageio.swift', folder / 'imageio')
