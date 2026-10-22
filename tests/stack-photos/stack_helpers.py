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
    inside_if_on,
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


def answers(gen, direction, ratio, fit=None, typed=False, gap=None):
    """
    The menus' answers in the order the shortcut asks: the direction, the ratio
    (or Keep), Pad or Crop (for a ratio), the size (the smallest photo's, or
    typed in: the number goes to the model's ``typed``), and the gap (None: No
    gap; else a percentage).
    """
    horizontal = direction == gen.HORIZONTAL
    out = [direction, ratio]
    if ratio != gen.KEEP:
        out.append(fit)

    out.append(gen.TYPED[horizontal] if typed else gen.SMALLEST[horizontal])
    out.append(gen.NO_GAP if gap is None else f'{gap}%')
    return out


def load_generator():
    """scripts/build_shortcuts.py as a module."""
    return shortcut_helpers.load_generator(TOOL / 'scripts', 'build_shortcuts')
