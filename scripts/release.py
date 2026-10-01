#!/usr/bin/env python3
"""
Builds every shortcut and publishes a GitHub release for one of them.

Each shortcut lives in shortcuts/<name>/ with a VERSION file shared by its
.shortcut files and its encoder. A release is named after the shortcut that
changed, for example "compress-photos-v0.1.0", but carries the current files of
all shortcuts, so the README's "latest" download links always work:

- <name>-shortcuts-v<version>.zip: the shortcut's .shortcut files, inside a
  folder of the same name (the files keep their names with spaces);
- the shortcut's encoders (dist/*.wasm), with fixed names.

Before publishing, it checks the git state, the changelog entry, that every
file was rebuilt in this run, and that each encoder reports its VERSION. It
runs on a Mac: signing the shortcuts needs macOS and an Apple ID.

Usage::

    scripts/release.py compress-photos                     # build, check, publish
    scripts/release.py compress-photos --dry-run           # build and check only
    scripts/release.py compress-photos --dry-run --no-sign # as in CI
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import check_changelog  # scripts/check_changelog.py

ROOT = Path(__file__).resolve().parent.parent
SHORTCUTS = ROOT / 'shortcuts'
CHANGELOG = ROOT / 'CHANGELOG.md'
OUT = ROOT / 'dist' / 'release'
BRANCH = 'main'
SEMVER = re.compile(r'\d+\.\d+\.\d+')


class ReleaseError(Exception):
    pass


def run(cmd, cwd=None, capture=False):
    """Runs a command, stopping the release if it fails."""
    print('$', ' '.join(str(c) for c in cmd))
    result = subprocess.run(
        [str(c) for c in cmd], cwd=cwd, text=True, capture_output=capture
    )
    if result.returncode != 0:
        if capture:
            sys.stderr.write(result.stdout + result.stderr)

        raise ReleaseError(f'command failed: {" ".join(str(c) for c in cmd)}')

    return result.stdout if capture else ''


def git(*args):
    return run(['git', *args], cwd=ROOT, capture=True).strip()


class Tool:
    """One shortcut folder: shortcuts/<name>/ with a VERSION file."""

    def __init__(self, path):
        self.path = path
        self.name = path.name
        self.title = check_changelog.title(self.name)  # "Compress Photos"
        self.version = (path / 'VERSION').read_text(encoding='utf-8').strip()
        if not SEMVER.fullmatch(self.version):
            raise ReleaseError(
                f'{path / "VERSION"}: "{self.version}" is not X.Y.Z'
            )

    @property
    def tag(self):
        return f'{self.name}-v{self.version}'

    @property
    def zip_name(self):
        return f'{self.name}-shortcuts-v{self.version}'


def find_tools():
    tools = [
        Tool(p)
        for p in sorted(SHORTCUTS.iterdir())
        if (p / 'VERSION').exists()
    ]
    if not tools:
        raise ReleaseError(f'no shortcuts/<name>/VERSION found in {SHORTCUTS}')

    return tools


def changelog_entry(tool):
    """
    The tool's changelog entry, after checking that CHANGELOG.md matches every
    shortcut's VERSION (the same checks as the pre-commit hook).
    """
    errors = check_changelog.problems(ROOT)
    if errors:
        raise ReleaseError('; '.join(errors))

    text = CHANGELOG.read_text(encoding='utf-8')
    return next(
        body
        for name, version, _, body in check_changelog.entries(text)
        if name == tool.title and version == tool.version
    )


def check_git(tool):
    """Clean, up-to-date main branch; the tag must not exist yet."""
    if git('status', '--porcelain'):
        raise ReleaseError('uncommitted changes; commit or stash them first')

    branch = git('rev-parse', '--abbrev-ref', 'HEAD')
    if branch != BRANCH:
        raise ReleaseError(
            f'on branch "{branch}"; releases come from {BRANCH}'
        )

    git('fetch', '--quiet', '--tags', 'origin', BRANCH)
    if git('rev-parse', 'HEAD') != git('rev-parse', f'origin/{BRANCH}'):
        raise ReleaseError(f'{BRANCH} is not the same as origin/{BRANCH}')

    if git('tag', '--list', tool.tag) or git(
        'ls-remote', '--tags', 'origin', f'refs/tags/{tool.tag}'
    ):
        raise ReleaseError(f'tag {tool.tag} already exists')


def build(tool, sign):
    """Builds a tool's encoders and shortcuts with its own scripts."""
    scripts = tool.path / 'scripts'
    if (scripts / 'build-wasm.sh').exists():
        run([scripts / 'build-wasm.sh'], cwd=tool.path)

    cmd = [sys.executable, scripts / 'build_shortcuts.py', '--guess']
    if not sign:
        cmd.append('--no-sign')

    run(cmd, cwd=tool.path)


def fresh(path, since):
    """A build output, which must have been written in this run."""
    if path.stat().st_mtime < since:
        raise ReleaseError(
            f'{path} was not rebuilt in this run (left over from an earlier '
            'build?); delete it and run again'
        )

    return path


def encoders(tool, since):
    found = [
        fresh(p, since) for p in sorted((tool.path / 'dist').glob('*.wasm'))
    ]
    if (tool.path / 'scripts' / 'build-wasm.sh').exists() and not found:
        raise ReleaseError(f'{tool.name}: no dist/*.wasm after the build')

    return found


def check_encoder_version(tool, wasm):
    """Each encoder must report the tool's VERSION (`<encoder> --version`)."""
    if not shutil.which('wasmtime'):
        raise ReleaseError('wasmtime is needed to check encoder versions')

    output = run(['wasmtime', 'run', wasm, '--version'], capture=True)
    if not re.search(rf'\b{re.escape(tool.version)}\b', output):
        raise ReleaseError(
            f'{wasm.name} reports "{output.strip()}", not {tool.version}'
        )


def shortcut_files(tool, sign, since):
    """(path, name inside the ZIP) for each of the tool's shortcuts."""
    if sign:
        files = [
            (p, p.name)
            for p in sorted((tool.path / 'dist').glob('*.shortcut'))
        ]
    else:  # unsigned build: build/shortcuts/<name>.unsigned.wflow
        files = [
            (p, p.name.replace('.unsigned.wflow', '.shortcut'))
            for p in sorted(
                (tool.path / 'build' / 'shortcuts').glob('*.unsigned.wflow')
            )
        ]

    if not files:
        raise ReleaseError(f'{tool.name}: no shortcuts after the build')

    return [(fresh(p, since), name) for p, name in files]


def make_zip(tool, files):
    """
    <name>-shortcuts-v<version>.zip, with the files in a folder of that name.
    """
    path = OUT / f'{tool.zip_name}.zip'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for src, name in files:
            z.write(src, f'{tool.zip_name}/{name}')

    return path


def release_notes(tool, tools, entry):
    lines = [entry, '', '## Files in this release', '']
    for t in tools:
        state = 'updated in this release' if t is tool else 'unchanged'
        lines.append(f'- {t.title} {t.version} ({state})')

    lines += [
        '',
        'Each release includes the current files of every shortcut. Update '
        'only the shortcuts marked as updated; see the README for how.',
    ]
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        'shortcut', help='folder name in shortcuts/, e.g. compress-photos'
    )
    ap.add_argument(
        '--dry-run',
        action='store_true',
        help='build and check, but do not publish',
    )
    ap.add_argument(
        '--no-sign',
        action='store_true',
        help='zip unsigned shortcuts (only with --dry-run, e.g. in CI)',
    )
    ap.add_argument(
        '--yes', action='store_true', help='publish without asking'
    )
    args = ap.parse_args()
    if args.no_sign and not args.dry_run:
        raise ReleaseError('--no-sign only works with --dry-run')

    tools = find_tools()
    tool = next((t for t in tools if t.name == args.shortcut), None)
    if not tool:
        raise ReleaseError(
            f'unknown shortcut "{args.shortcut}"; have: '
            + ', '.join(t.name for t in tools)
        )

    # In a dry run (e.g. CI on a pull request) the git state and the changelog
    # are reported, not enforced.
    entry = f'{tool.title} {tool.version}'
    for check in (lambda: changelog_entry(tool), lambda: check_git(tool)):
        try:
            entry = check() or entry
        except ReleaseError as e:
            if not args.dry_run:
                raise

            print(f'note (ignored in a dry run): {e}')

    sign = not args.no_sign
    since = time.time() - 1
    if OUT.exists():
        shutil.rmtree(OUT)

    OUT.mkdir(parents=True)
    assets = []
    for t in tools:
        build(t, sign)
        for wasm in encoders(t, since):
            check_encoder_version(t, wasm)
            assets.append(wasm)

        assets.append(make_zip(t, shortcut_files(t, sign, since)))

    names = [a.name for a in assets]
    if len(names) != len(set(names)):
        raise ReleaseError(f'two release files share a name: {names}')

    notes = release_notes(tool, tools, entry)
    print(f'\nRelease {tool.tag} ("{tool.title} {tool.version}"), files:')
    for a in assets:
        print(f'  {a.name}  ({a.stat().st_size / 1e3:,.0f} KB)')

    print('\nNotes:\n' + notes)
    if args.dry_run:
        print(f'Dry run: nothing published. ZIP files are in {OUT}.')
        return

    if (
        not args.yes
        and input(f'Publish {tool.tag}? [y/N] ').strip().lower() != 'y'
    ):
        print('Not published.')
        return

    with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False) as f:
        f.write(notes)

    run([
        'gh',
        'release',
        'create',
        tool.tag,
        *assets,
        '--title',
        f'{tool.title} {tool.version}',
        '--notes-file',
        f.name,
        '--target',
        git('rev-parse', 'HEAD'),
    ])
    Path(f.name).unlink()
    print(f'Published {tool.tag}.')


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as e:
        sys.exit(f'release: {e}')
