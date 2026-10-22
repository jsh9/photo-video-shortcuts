"""
Helpers for the Stack Photos tests: the generator, and the shared helpers for
reading a generated shortcut's actions (tests/shortcut_helpers.py).
"""

import sys
from pathlib import Path

_TESTS = str(Path(__file__).resolve().parents[1])
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

import shortcut_helpers  # noqa: E402
from shortcut_helpers import (  # noqa: E402, F401
    CONTROL_FLOW,
    OBJ,
    compile_swift,
    ident,
    need,
    params,
    references,
    render,
    run,
    walk,
)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TOOL = REPO / 'shortcuts' / 'stack-photos'
VERSION = (TOOL / 'VERSION').read_text(encoding='utf-8').strip()
FIXTURES = HERE / 'fixtures'


def load_generator():
    """scripts/build_shortcuts.py as a module."""
    return shortcut_helpers.load_generator(TOOL / 'scripts', 'build_shortcuts')
