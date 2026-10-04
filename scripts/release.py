#!/usr/bin/env python3
"""
Builds every shortcut and publishes a GitHub release for one of them.

Each shortcut lives in shortcuts/<name>/ with a VERSION file shared by its
.shortcut files and its encoder. A release is named after the shortcut that
changed, for example "compress-photos-v0.1.0", but carries the current files of
all shortcuts, so the README's "latest" download links always work:

- <name>-shortcuts-v<version>.zip: the shortcut's .shortcut files, inside a
  folder of the same name (the files keep their names with spaces);
- the encoders declared in the tool's release.json, with fixed names.

Before publishing, it checks the git state, the changelog entry, that every
file was rebuilt in this run, and that each encoder reports its VERSION. It
runs on a Mac: signing the shortcuts needs macOS and an Apple ID.

Usage::

    scripts/release.py compress-photos                     # build, check, publish
    scripts/release.py compress-photos --dry-run           # build and check only
    scripts/release.py compress-photos --dry-run --no-sign # as in CI
"""

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.parse import quote

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

        manifest = path / 'release.json'
        try:
            declared = json.loads(manifest.read_text(encoding='utf-8'))
        except (OSError, ValueError) as e:
            raise ReleaseError(
                f'{manifest}: cannot read release manifest: {e}'
            ) from e

        if not isinstance(declared, dict) or set(declared) != {
            'encoders',
            'shortcuts',
        }:
            raise ReleaseError(
                f'{manifest}: expected encoders and shortcuts lists'
            )

        names = []
        for key, suffix in (('encoders', '.wasm'), ('shortcuts', '.shortcut')):
            files = declared[key]
            if not isinstance(files, list) or (
                key == 'shortcuts' and not files
            ):
                raise ReleaseError(
                    f'{manifest}: {key} must be a list (shortcuts cannot be empty)'
                )

            for name in files:
                if (
                    not isinstance(name, str)
                    or '/' in name
                    or '\\' in name
                    or not name.endswith(suffix)
                    or name == suffix
                ):
                    raise ReleaseError(
                        f'{manifest}: invalid {key} filename: {name!r}'
                    )

            names.extend(files)

        if len(names) != len(set(names)):
            raise ReleaseError(f'{manifest}: duplicate filenames')

        self.encoder_names = declared['encoders']
        self.shortcut_names = declared['shortcuts']

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
            f'on branch "{branch}", but releases are published from {BRANCH}: '
            f'merge your changes into {BRANCH}, then run '
            f'"git checkout {BRANCH} && git pull" and try again'
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
    """A nonempty, declared output written during the current tool build."""
    if not path.is_file():
        raise ReleaseError(f'{path}: required release file is missing')

    stat = path.stat()
    if not stat.st_size:
        raise ReleaseError(f'{path}: required release file is empty')

    if stat.st_mtime < since:
        raise ReleaseError(f'{path} was not rebuilt in this run')

    return path


def encoders(tool, since):
    return [
        fresh(tool.path / 'dist' / name, since) for name in tool.encoder_names
    ]


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
    """Declared shortcuts, mapped to unsigned build filenames in CI."""
    files = []
    for name in tool.shortcut_names:
        path = (
            tool.path / 'dist' / name
            if sign
            else tool.path
            / 'build'
            / 'shortcuts'
            / (name[: -len('.shortcut')] + '.unsigned.wflow')
        )
        files.append((fresh(path, since), name))

    return files


def verify_zip(tool, path, files):
    """Reopen the ZIP and check its exact members, CRCs, and source bytes."""
    expected = [f'{tool.zip_name}/{name}' for name in tool.shortcut_names]
    sources = {f'{tool.zip_name}/{name}': src for src, name in files}
    try:
        with zipfile.ZipFile(path) as z:
            members = z.namelist()
            if sorted(members) != sorted(expected) or set(sources) != set(
                expected
            ):
                raise ReleaseError(
                    f'{path}: ZIP members do not match release.json'
                )

            bad = z.testzip()
            if bad:
                raise ReleaseError(f'{path}: ZIP CRC failure: {bad}')

            for name in expected:
                if z.read(name) != sources[name].read_bytes():
                    raise ReleaseError(
                        f'{path}: ZIP contents differ from {sources[name]}'
                    )
    except (OSError, zipfile.BadZipFile, RuntimeError) as e:
        raise ReleaseError(f'{path}: cannot verify ZIP: {e}') from e


def make_zip(tool, files):
    """Package only the manifest's complete list, then verify the archive."""
    names = [name for _, name in files]
    if sorted(names) != sorted(tool.shortcut_names):
        raise ReleaseError(
            f'{tool.name}: shortcut files do not match release.json'
        )

    path = OUT / f'{tool.zip_name}.zip'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for src, name in files:
            z.write(src, f'{tool.zip_name}/{name}')

    verify_zip(tool, path, files)
    return path


def github(endpoint, missing_ok=False, paginate=False):
    """Read GitHub JSON; only an explicit 404 can mean a missing VERSION."""
    cmd = ['gh', 'api', endpoint]
    if paginate:
        cmd += ['--paginate', '--slurp']

    try:
        result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    except OSError as e:
        raise ReleaseError(f'cannot read GitHub release baseline: {e}') from e

    if result.returncode:
        if missing_ok and '(HTTP 404)' in result.stderr:
            return None

        raise ReleaseError(
            f'cannot read GitHub release baseline: {result.stderr.strip()}'
        )

    try:
        return json.loads(result.stdout)
    except ValueError as e:
        raise ReleaseError(
            'cannot read GitHub release baseline: invalid JSON'
        ) from e


def published_baseline(tools):
    """
    Latest published stable release and each included tool's VERSION there.
    """
    repo = run(
        [
            'gh',
            'repo',
            'view',
            '--json',
            'nameWithOwner',
            '--jq',
            '.nameWithOwner',
        ],
        capture=True,
    ).strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ReleaseError(
            'cannot read GitHub release baseline: invalid repository name'
        )

    pages = github(f'repos/{repo}/releases', paginate=True)
    if not isinstance(pages, list) or any(
        not isinstance(p, list) or any(not isinstance(r, dict) for r in p)
        for p in pages
    ):
        raise ReleaseError(
            'cannot read GitHub release baseline: invalid release list'
        )

    stable = [
        r
        for page in pages
        for r in page
        if not r.get('draft') and not r.get('prerelease')
    ]
    if not stable:
        return {'tag': None, 'versions': {}}

    latest = max(stable, key=lambda r: r.get('published_at') or '')
    tag = latest.get('tag_name')
    if not tag:
        raise ReleaseError(
            'cannot read GitHub release baseline: release has no tag'
        )

    # Verify that the tag still exists before treating a missing VERSION as a
    # new tool. A deleted tag must not make all tools appear new.
    ref = github(f'repos/{repo}/git/ref/tags/{quote(tag, safe="")}')
    if not isinstance(ref, dict) or ref.get('ref') != f'refs/tags/{tag}':
        raise ReleaseError(
            f'cannot read GitHub release baseline: invalid tag {tag}'
        )

    versions = {}
    for tool in tools:
        data = github(
            f'repos/{repo}/contents/shortcuts/{quote(tool.name, safe="")}/VERSION?ref={quote(tag, safe="")}',
            missing_ok=True,
        )
        if data is None:
            continue

        try:
            if data['encoding'] != 'base64':
                raise ValueError('unsupported encoding')

            version = (
                base64
                .b64decode(data['content'], validate=False)
                .decode('utf-8')
                .strip()
            )
        except (KeyError, TypeError, ValueError, UnicodeError) as e:
            raise ReleaseError(
                f'cannot read {tool.name}/VERSION at {tag}'
            ) from e

        if not SEMVER.fullmatch(version):
            raise ReleaseError(f'{tool.name}/VERSION at {tag} is not X.Y.Z')

        versions[tool.name] = version

    return {'tag': tag, 'versions': versions}


def comparison_baseline(tools, dry_run):
    try:
        return published_baseline(tools)
    except (ReleaseError, OSError) as e:
        if not dry_run:
            raise ReleaseError(f'release comparison unavailable: {e}') from e

        print(f'note: release comparisons unavailable (offline dry run): {e}')
        return None


def tool_states(tools, baseline):
    if baseline is None:
        return {t.name: 'comparison unavailable' for t in tools}

    previous = baseline['versions']
    return {
        t.name: (
            'new'
            if t.name not in previous
            else 'unchanged'
            if t.version == previous[t.name]
            else 'updated'
        )
        for t in tools
    }


def require_updated(tool, states):
    if states[tool.name] == 'unchanged':
        raise ReleaseError(
            f'{tool.title} {tool.version} is unchanged from the latest published release; bump VERSION before publishing'
        )


def release_notes(tool, tools, baseline, entries):
    states = tool_states(tools, baseline)
    if baseline is None:
        lines = [
            'Release comparisons unavailable: the GitHub baseline could not be read.',
            '',
        ]
    elif baseline['tag'] is None:
        lines = [
            'First release: no published, non-prerelease release exists.',
            '',
        ]
    else:
        lines = [f'Compared with `{baseline["tag"]}`.', '']

    # The selected tool keeps the title/tag; every changed tool gets its notes.
    for t in [tool] + [t for t in tools if t.name != tool.name]:
        if states[t.name] in ('new', 'updated') or (
            baseline is None and t is tool
        ):
            lines += [f'## {t.title} {t.version}', '', entries[t.name], '']

    lines += ['## Files in this release', '']
    for t in tools:
        lines.append(f'- {t.title} {t.version} (**{states[t.name]}**)')

    lines += [
        '',
        'Each release includes the current files of every shortcut. Update only the tools marked new or updated; see the README for how.',
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

    baseline = comparison_baseline(tools, args.dry_run)
    states = tool_states(tools, baseline)
    if not args.dry_run:
        require_updated(tool, states)

    entries = {
        t.name: changelog_entry(t)
        for t in tools
        if states[t.name] in ('new', 'updated')
        or (baseline is None and t is tool)
    }
    try:
        check_git(tool)
    except ReleaseError as e:
        if not args.dry_run:
            raise

        print(f'note (ignored in a dry run): {e}')

    sign = not args.no_sign
    if OUT.exists():
        shutil.rmtree(OUT)

    OUT.mkdir(parents=True)
    assets = []
    for t in tools:
        since = time.time()
        build(t, sign)
        for wasm in encoders(t, since):
            check_encoder_version(t, wasm)
            assets.append(wasm)

        assets.append(make_zip(t, shortcut_files(t, sign, since)))

    names = [a.name for a in assets]
    if len(names) != len(set(names)):
        raise ReleaseError(f'two release files share a name: {names}')

    notes = release_notes(tool, tools, baseline, entries)
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
