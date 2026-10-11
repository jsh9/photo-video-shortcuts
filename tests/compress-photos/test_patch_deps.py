"""
scripts/patch_deps.py: each edit to a dependency checkout is idempotent, and a
checkout patched before the encoder's rename (its comments say jxlbatch) is
recognised and renamed rather than refused.
"""

import importlib.util

import photo_helpers as ph
import pytest

spec = importlib.util.spec_from_file_location(
    'patch_deps', ph.TOOL / 'scripts' / 'patch_deps.py'
)
patch_deps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch_deps)

OLD = 'line a\n    // marker\nline b\n'
NEW = 'line a\n    // photobatch: inserted\n    // marker\nline b\n'


@pytest.mark.parametrize(
    'text',
    [OLD, NEW, NEW.replace('photobatch', 'jxlbatch')],
    ids=['pristine', 'patched', 'patched before the rename'],
)
def test_replace_leaves_the_edit_in_place(tmp_path, text):
    (tmp_path / 'x.c').write_text(text)
    patch_deps.replace(tmp_path, 'x.c', OLD, NEW)
    assert (tmp_path / 'x.c').read_text() == NEW


def test_replace_refuses_other_code(tmp_path):
    (tmp_path / 'x.c').write_text('something else\n')
    with pytest.raises(SystemExit):
        patch_deps.replace(tmp_path, 'x.c', OLD, NEW)
