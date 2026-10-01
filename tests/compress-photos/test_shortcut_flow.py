"""
Integration: the commands the generated shortcut sends to a-Shell, run line by
line as a-Shell runs them, against the real encoder; then JXL-Import's reading
of the results, and the cleanup.

a-Shell's own commands are stood in for: ``jxlbatch`` runs the WebAssembly
build under wasmtime (and can fail once, like a-Shell whose WebAssembly engine
hasn't started), ``sleep`` returns at once, and ``open`` records the URL that
would switch back to Shortcuts.
"""

import os
import shutil
import subprocess

import photo_helpers as ph
import pytest
from PIL import Image

QUALITY = 83
SHIMS = {
    'jxlbatch': """#!/bin/sh
echo run >> "$LOG/jxlbatch.calls"
if [ -e "$LOG/fail_once" ]; then
  rm "$LOG/fail_once"
  echo "The WebAssembly interpreter is not running (either crashed or not yet started)." >&2
  exit 255
fi
exec wasmtime run --dir "$PWD::." "$WASM" "$@"
""",
    'sleep': '#!/bin/sh\nexit 0\n',
    'open': '#!/bin/sh\necho "$@" >> "$LOG/opened"\n',
}


@pytest.fixture(scope='module')
def gen():
    return ph.load_generator()


@pytest.fixture(scope='module')
def actions(gen):
    sample = gen.Sample(gen.guessed_workflow())
    return {
        'compress': gen.build_compress(sample),
        'import': gen.build_import(sample),
    }


@pytest.fixture
def ashell(tmp_path, wasm):
    """Runs a-Shell command text in a staged folder; returns the log folder."""
    ph.need(shutil.which('dash'), 'dash is needed (part of macOS)')
    bin_dir, log = tmp_path / 'bin', tmp_path / 'log'
    bin_dir.mkdir()
    log.mkdir()
    for name, script in SHIMS.items():
        (bin_dir / name).write_text(script)
        (bin_dir / name).chmod(0o755)

    env = dict(
        os.environ,
        PATH=f'{bin_dir}:{os.environ["PATH"]}',
        LOG=str(log),
        WASM=str(wasm.command[-1]),
    )

    def run(command, folder):
        # a-Shell runs each line in turn and carries on after errors.
        for line in command.split('\n'):
            if line.strip():
                subprocess.run(line, shell=True, cwd=folder, env=env)

    run.log = log
    return run


def batch_command(actions, url):
    """The Execute Command that runs jxlbatch and then opens ``url``."""
    commands = ph.ashell_commands(actions['compress'], {'Matches': QUALITY})
    return next(
        c
        for c in commands
        if 'jxlbatch' in c and c.split('\n')[-1] == f'open {url}'
    )


def stage_like_shortcut(actions, folder, photos):
    """
    Stages photos with the job line the shortcut builds: its Text action
    "<Repeat Index>|<Name>".
    """
    template = next(
        ph.params(a)['WFTextActionText']
        for a in actions['compress']
        if ph.ident(a) == 'is.workflow.actions.gettext'
        and '|' in str(ph.params(a)['WFTextActionText'])
    )
    folder.mkdir()
    lines = []
    for i, photo in enumerate(photos, 1):
        shutil.copy(photo, folder / f'jxl_in_{i}.orig')
        lines.append(
            ph.render(template, {'Repeat Index': i, 'Name': photo.stem})
        )

    (folder / 'jxl_job.txt').write_text('\n'.join(lines))


def import_results(folder):
    """
    jxl_done.txt read the way JXL-Import reads it: split each line at "|"; the
    first item is the file, the last is the name, item 2 the index.
    """
    results = []
    for line in (folder / 'jxl_done.txt').read_text().split('\n'):
        parts = line.split('|')
        results.append((folder / parts[0], parts[-1], int(parts[1])))

    return results


@pytest.mark.parametrize(
    ('start', 'url'),
    [
        ('share sheet', 'shortcuts://run-shortcut?name=JXL-Import'),
        ('Shortcuts app', 'shortcuts://'),
    ],
)
def test_convert_and_return(actions, ashell, photos, tmp_path, start, url):
    folder = tmp_path / 'ashell'
    originals = [photos['heic_p3'], photos['jpeg']]
    stage_like_shortcut(actions, folder, originals)
    ashell(batch_command(actions, url), folder)
    assert (ashell.log / 'opened').read_text().split() == [url]
    results = import_results(folder)
    assert [index for _, _, index in results] == [1, 2]
    for jxl, name, index in results:
        assert jxl.exists()
        assert name == f'{originals[index - 1].stem}.jxl'


def test_retries_when_engine_not_ready(actions, ashell, photos, tmp_path):
    folder = tmp_path / 'ashell'
    stage_like_shortcut(actions, folder, [photos['jpeg']])
    (ashell.log / 'fail_once').touch()
    ashell(batch_command(actions, 'shortcuts://'), folder)
    assert len((ashell.log / 'jxlbatch.calls').read_text().split()) == 2
    assert len(import_results(folder)) == 1


def test_no_retry_once_started(actions, ashell, tmp_path):
    # jxlbatch ran but converted nothing: running it again wouldn't help.
    folder = tmp_path / 'ashell'
    gif = tmp_path / 'not-a-photo.gif'
    Image.new('RGB', (8, 8)).save(gif)
    stage_like_shortcut(actions, folder, [gif])
    ashell(batch_command(actions, 'shortcuts://'), folder)
    assert len((ashell.log / 'jxlbatch.calls').read_text().split()) == 1
    assert not (folder / 'jxl_done.txt').exists()


def test_cleanup_leaves_nothing(actions, ashell, photos, tmp_path):
    folder = tmp_path / 'ashell'
    stage_like_shortcut(actions, folder, [photos['jpeg']])
    ashell(batch_command(actions, 'shortcuts://'), folder)
    (folder / 'jxl_albums_1.txt').write_text('Holidays')
    cleanup = next(
        c
        for c in ph.ashell_commands(actions['import'], {})
        if c.startswith('rm ')
    )
    ashell(cleanup, folder)
    assert sorted(p.name for p in folder.iterdir()) == []
