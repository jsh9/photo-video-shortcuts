"""
Integration: the commands the generated shortcut sends to a-Shell, run line by
line the way a-Shell runs them, against the real encoder; then JXL-Import's
reading of the results, and the cleanup.

The model of a-Shell follows its source (a-Shell/SceneDelegate.swift and
a-Shell-Intents/ExecuteCommandIntentHandler.swift):

- The lines run in one session: a ``cd`` carries over to the lines after it,
  and a failed line doesn't stop the rest.
- Shortcuts run in the Shortcuts folder (``$SHORTCUTS``, ``~shortcuts``),
  where Put File saves. But when a shortcut has to launch a-Shell, the folder
  a-Shell restores from its last session can take over. On the iPhone,
  jxlbatch then found the job neither in that folder nor through
  ``$SHORTCUTS``, so a launched a-Shell here starts in ~/Documents, without
  ``$SHORTCUTS``.
- ``jxlbatch`` is ``~/Documents/bin/jxlbatch.wasm``, run here by wasmtime. It
  can fail once, like a-Shell whose WebAssembly engine hasn't started.
- dash only runs files named exactly like the command, so it can't run
  ``jxlbatch.wasm``.
- ``sleep`` returns at once, and ``open`` records the URL that would switch
  back to Shortcuts.
"""

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import photo_helpers as ph
import pytest
from PIL import Image

QUALITY = 83
NOT_RUNNING = (
    'The WebAssembly interpreter is not running '
    '(either crashed or not yet started).'
)
LAUNCHED = pytest.mark.parametrize(
    'launched', [False, True], ids=['a-Shell open', 'a-Shell launched']
)


class AShell:
    """
    a-Shell running a shortcut's commands. ``launched``: the shortcut had to
    launch a-Shell, which then starts in the folder of its last session.
    """

    def __init__(self, root, wasm, launched):
        self.shortcuts = root / 'Shortcuts'
        self.documents = root / 'Documents'
        self.bin = self.documents / 'bin'
        shims = root / 'shims'
        for folder in (self.shortcuts, self.bin, shims):
            folder.mkdir(parents=True)

        # As on the iPhone: a .wasm file, not an executable.
        shutil.copy(wasm, self.bin / 'jxlbatch.wasm')
        (shims / 'sleep').write_text('#!/bin/sh\nexit 0\n')
        (shims / 'sleep').chmod(0o755)
        self.path = f'{shims}:{self.bin}:{os.environ["PATH"]}'
        self.env = {} if launched else {'SHORTCUTS': str(self.shortcuts)}
        self.cwd = self.documents if launched else self.shortcuts
        self.engine_ready = True
        self.output = ''
        self.opened = []

    def run(self, command):
        for line in command.split('\n'):
            if line.strip():
                self.line(line)

    def line(self, line):
        name, *args = shlex.split(line)
        if name == 'cd':
            self.cd(args[0] if args else '')
        elif name == 'sleep':
            pass
        elif name == 'open':
            self.opened.append(args[0])
        elif (self.bin / f'{name}.wasm').exists():
            self.wasm(self.bin / f'{name}.wasm', args)
        else:  # dash, rm and other commands
            self.shell(line)

    def cd(self, target):
        # Bookmarks, then $VARIABLES; plain "cd" goes to ~/Documents.
        bookmarks = {'~shortcuts': self.shortcuts, '~group': self.shortcuts}
        if target in bookmarks:
            self.cwd = bookmarks[target]
            return

        target = re.sub(r'\$(\w+)', lambda m: self.env.get(m[1], ''), target)
        folder = self.cwd / target if target else self.documents
        if folder.is_dir():
            self.cwd = folder.resolve()
        else:
            self.output += f'cd: {target}: No such file or directory\n'

    def wasm(self, path, args):
        if not self.engine_ready:
            self.engine_ready = True
            self.output += NOT_RUNNING + '\n'
            return

        env = dict(self.env, PWD=str(self.cwd))
        command = ['wasmtime', 'run', '--dir', f'{self.cwd}::.']
        if 'SHORTCUTS' in env:  # by its absolute path, as in a-Shell
            command += ['--dir', f'{self.shortcuts}::{self.shortcuts}']

        for name, value in env.items():
            command += ['--env', f'{name}={value}']

        self.record(ph.run([*command, path, *args], cwd=self.cwd))

    def shell(self, line):
        env = dict(os.environ, PATH=self.path, **self.env)
        self.record(
            subprocess.run(
                line,
                shell=True,
                cwd=self.cwd,
                env=env,
                capture_output=True,
                text=True,
            )
        )

    def record(self, result):
        self.output += result.stdout + result.stderr


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
    """Starts the a-Shell model: ``ashell(launched=False)``."""
    ph.need(shutil.which('dash'), 'dash is needed (part of macOS)')
    return lambda launched=False: AShell(
        tmp_path / 'a-Shell', Path(wasm.command[-1]), launched
    )


SKIPPED_NOTE = 'Skipped 1 Live Photo(s): only still photos are converted.'


def batch_command(actions, url, skipped=True):
    """
    The Execute Command that runs jxlbatch and then opens ``url``. With
    ``skipped``, the shortcut skipped a Live Photo and set Skipped Echo.
    """
    values = {
        'Matches': QUALITY,
        'Skipped Echo': f'echo "{SKIPPED_NOTE}"' if skipped else '',
    }
    commands = ph.ashell_commands(actions['compress'], values)
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
    lines = []
    for i, photo in enumerate(photos, 1):
        shutil.copy(photo, folder / f'jxl_in_{i}.orig')
        lines.append(
            ph.render(template, {'Repeat Index': i, 'Name': photo.stem})
        )

    (folder / 'jxl_job.txt').write_text('\n'.join(lines))


def dates_like_shortcut(actions, folder, dates):
    """
    Writes jxl_dates.txt with the lines the shortcut builds for ``dates``
    ({index: Format Date's text}): its Text "<Repeat Index>|<Formatted Date>"
    (wf.photo_date), joined by Combine Text.
    """
    template = next(
        ph.params(a)['WFTextActionText']
        for a in actions['compress']
        if ph.ident(a) == 'is.workflow.actions.gettext'
        and 'Formatted Date' in str(ph.params(a)['WFTextActionText'])
    )
    (folder / 'jxl_dates.txt').write_text(
        '\n'.join(
            ph.render(template, {'Repeat Index': i, 'Formatted Date': d})
            for i, d in dates.items()
        )
    )


def import_results(folder):
    """
    jxl_done.txt read the way JXL-Import reads it: split each line at "|"; the
    first item is the file, the last is the name, item 2 the index.
    """
    assert (folder / 'jxl_done.txt').exists(), 'nothing was converted'
    results = []
    for line in (folder / 'jxl_done.txt').read_text().split('\n'):
        parts = line.split('|')
        results.append((folder / parts[0], parts[-1], int(parts[1])))

    return results


def batches_started(shell):
    """How many times jxlbatch started converting the batch."""
    return len(re.findall(r'jxlbatch: \d+ photos?,', shell.output))


@LAUNCHED
@pytest.mark.parametrize(
    ('start', 'url'),
    [
        ('share sheet', 'shortcuts://run-shortcut?name=JXL-Import'),
        ('Shortcuts app', 'shortcuts://'),
    ],
)
def test_convert_and_return(actions, ashell, photos, launched, start, url):
    shell = ashell(launched)
    originals = [photos['heic_p3'], photos['jpeg']]
    stage_like_shortcut(actions, shell.shortcuts, originals)
    shell.run(batch_command(actions, url))
    assert shell.opened == [url]
    # What was skipped is printed before and after the batch.
    assert shell.output.count(SKIPPED_NOTE) == 2
    results = import_results(shell.shortcuts)
    assert [index for _, _, index in results] == [1, 2]
    for jxl, name, index in results:
        assert jxl.exists()
        assert name == f'{originals[index - 1].stem}.jxl'


def test_nothing_skipped_prints_nothing(actions, ashell, photos):
    # Skipped Echo unset: its lines are empty, which a-Shell ignores.
    shell = ashell(False)
    stage_like_shortcut(actions, shell.shortcuts, [photos['jpeg']])
    shell.run(batch_command(actions, 'shortcuts://', skipped=False))
    assert 'Skipped' not in shell.output
    assert len(import_results(shell.shortcuts)) == 1


@LAUNCHED
def test_retries_when_engine_not_ready(actions, ashell, photos, launched):
    shell = ashell(launched)
    stage_like_shortcut(actions, shell.shortcuts, [photos['jpeg']])
    shell.engine_ready = False
    shell.run(batch_command(actions, 'shortcuts://'))
    assert NOT_RUNNING in shell.output
    assert batches_started(shell) == 1, shell.output
    assert len(import_results(shell.shortcuts)) == 1


def test_no_retry_once_started(actions, ashell, tmp_path):
    # jxlbatch ran but converted nothing: running it again wouldn't help.
    shell = ashell()
    gif = tmp_path / 'not-a-photo.gif'
    Image.new('RGB', (8, 8)).save(gif)
    stage_like_shortcut(actions, shell.shortcuts, [gif])
    shell.run(batch_command(actions, 'shortcuts://'))
    assert batches_started(shell) == 1, shell.output
    assert not (shell.shortcuts / 'jxl_done.txt').exists()


def test_missing_job_says_where_it_looked(ashell):
    # So a failure on the iPhone shows why the job wasn't found.
    shell = ashell(launched=True)
    shell.run(f'jxlbatch -q {QUALITY} -e 7 jxl_job.txt')
    message = ' '.join(shell.output.split())
    assert 'cannot find jxl_job.txt' in message
    assert f'$PWD ({shell.documents})' in message
    assert '$SHORTCUTS (not set)' in message


@LAUNCHED
def test_dates_reach_jxlbatch(actions, ashell, photos, launched):
    # jxl_dates.txt, next to the job, is read wherever a-Shell started.
    shell = ashell(launched)
    originals = [photos['heic_p3'], photos['jpeg']]
    stage_like_shortcut(actions, shell.shortcuts, originals)
    dates_like_shortcut(
        actions, shell.shortcuts, {2: '2024-01-01T17:00:00-05:00'}
    )
    shell.run(batch_command(actions, 'shortcuts://'))
    (first, _, _), (second, _, _) = import_results(shell.shortcuts)
    assert ph.exif_tags(first)['ExifIFD:DateTimeOriginal'] == (
        '2024:05:06 07:08:09'
    )
    assert ph.exif_tags(second)['ExifIFD:DateTimeOriginal'] == (
        '2024:01:01 17:00:00'
    )
    assert 'date from Photos' in shell.output


def test_cleanup_leaves_nothing(actions, ashell, photos):
    shell = ashell()
    stage_like_shortcut(actions, shell.shortcuts, [photos['jpeg']])
    dates_like_shortcut(actions, shell.shortcuts, {1: '2024-01-01T17:00:00Z'})
    shell.run(batch_command(actions, 'shortcuts://'))
    (shell.shortcuts / 'jxl_albums_1.txt').write_text('Holidays')
    cleanup = next(
        c
        for c in ph.ashell_commands(actions['import'], {})
        if c.startswith('rm ')
    )
    shell.run(cleanup)
    assert sorted(p.name for p in shell.shortcuts.iterdir()) == []
