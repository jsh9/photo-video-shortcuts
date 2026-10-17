"""
scripts/patch_deps.py: each edit to a dependency checkout is idempotent, and a
checkout patched before the encoder's rename (its comments say jxlbatch) is
recognised and renamed rather than refused. The Brotli box fix applies to the
pinned libjxl.
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


def test_brob_fix_applies_to_the_pinned_libjxl(tmp_path):
    """
    The Brotli box fix (libjxl 0.12's, see test_jxl_input.py's
    test_metadata_boxes) applies to box_content_decoder.cc as the pinned libjxl
    has it: Brotli is given the box only, with an error for a stream that ends
    after or before it; a second run leaves the file alone.
    """
    libjxl = ph.REPO / '.deps' / 'libjxl'
    ph.need((libjxl / '.git').exists(), 'the libjxl checkout (build-wasm.sh)')
    pristine = ph.run([
        'git',
        '-C',
        libjxl,
        'show',
        f'HEAD:{patch_deps.BOX_CONTENT}',
    ])
    assert pristine.returncode == 0, pristine.stderr
    path = tmp_path / patch_deps.BOX_CONTENT
    path.parent.mkdir(parents=True)
    path.write_text(pristine.stdout)

    patch_deps.patch_brob(tmp_path)
    patched = path.read_text()
    assert '&avail_in_brotli, &next_in' in patched
    errors = 'return JXL_DEC_ERROR;'
    assert patched.count(errors) == pristine.stdout.count(errors) + 2

    patch_deps.patch_brob(tmp_path)
    assert path.read_text() == patched
