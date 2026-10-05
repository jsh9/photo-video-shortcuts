"""Release completeness, archive integrity, and mocked GitHub comparisons."""

import base64
from contextlib import nullcontext
import json
import os
import sys
import time
import zipfile
from types import SimpleNamespace

import pytest
import release

ENCODERS = ['jxlbatch.wasm', 'jxlbatch-scalar.wasm', 'jxlbatch-macos']
SHORTCUTS = ['Compress Photos.shortcut', 'JXL-Import.shortcut']
MAC_SHORTCUTS = [
    'Compress Photos (macOS).shortcut',
    'Compress Photo Files (macOS).shortcut',
]
PLATFORMS = {'iphone': SHORTCUTS, 'mac': MAC_SHORTCUTS}


def tool(tmp_path, name='compress-photos', version='0.1.0', shortcuts=None):
    path = tmp_path / 'shortcuts' / name
    path.mkdir(parents=True)
    (path / 'VERSION').write_text(version + '\n')
    (path / 'release.json').write_text(
        json.dumps({
            'encoders': ENCODERS,
            'shortcuts': PLATFORMS if shortcuts is None else shortcuts,
        })
    )
    return release.Tool(path)


def outputs(t, sign=True):
    for name in ENCODERS:
        path = t.path / 'dist' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'encoder')

    for name in SHORTCUTS + MAC_SHORTCUTS:
        path = (
            t.path / 'dist' / name
            if sign
            else t.path
            / 'build'
            / 'shortcuts'
            / (name.removesuffix('.shortcut') + '.unsigned.wflow')
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'SHORTCUT-' + name.encode())


def test_tool_names(tmp_path):
    t = tool(tmp_path)
    assert t.title == 'Compress Photos'
    assert t.tag == 'compress-photos-v0.1.0'
    # The iPhone ZIP keeps the name from before there were Mac shortcuts.
    assert t.zip_name('iphone') == 'compress-photos-shortcuts-v0.1.0'
    assert t.zip_name('mac') == 'compress-photos-mac-shortcuts-v0.1.0'
    assert list(t.shortcut_names) == ['iphone', 'mac']


def test_plain_shortcut_list_means_iphone(tmp_path):
    t = tool(tmp_path, shortcuts=SHORTCUTS)
    assert t.shortcut_names == {'iphone': SHORTCUTS}


@pytest.mark.parametrize(
    'name,kind',
    [
        ('jxlbatch.wasm', 'wasm'),
        ('jxlbatch-scalar.wasm', 'wasm'),
        ('jxlbatch-macos', 'native'),
        ('.wasm', None),
        ('', None),
        ('jxlbatch.exe', None),
        ('jxlbatch.macos.bin', None),
    ],
)
def test_encoder_kind(name, kind):
    assert release.encoder_kind(name) == kind


@pytest.mark.parametrize('version', ['0.1', 'v0.1.0', 'dev', '1.2.3.4'])
def test_tool_rejects_bad_version(tmp_path, version):
    with pytest.raises(release.ReleaseError):
        tool(tmp_path, version=version)


@pytest.mark.parametrize(
    'manifest',
    [
        None,
        {},
        {'encoders': []},
        {
            'encoders': ['../encoder.wasm'],
            'shortcuts': SHORTCUTS,
        },
        {'encoders': [], 'shortcuts': []},
        {
            'encoders': ENCODERS,
            'shortcuts': SHORTCUTS * 2,
        },
        {'encoders': 'oops', 'shortcuts': SHORTCUTS},
        {'encoders': ['jxlbatch.exe'], 'shortcuts': SHORTCUTS},
        {'encoders': ENCODERS, 'shortcuts': {}},
        {'encoders': ENCODERS, 'shortcuts': {'windows': SHORTCUTS}},
        {'encoders': ENCODERS, 'shortcuts': {'iphone': []}},
        {'encoders': ENCODERS, 'shortcuts': {'iphone': 'oops'}},
        # the same file on two platforms
        {
            'encoders': ENCODERS,
            'shortcuts': {'iphone': SHORTCUTS, 'mac': SHORTCUTS},
        },
    ],
)
def test_invalid_manifest(tmp_path, manifest):
    t = tool(tmp_path)
    path = t.path / 'release.json'
    if manifest is None:
        path.unlink()
    else:
        path.write_text(json.dumps(manifest))

    with pytest.raises(release.ReleaseError, match='release'):
        release.Tool(t.path)


@pytest.mark.parametrize('sign', [True, False])
@pytest.mark.parametrize('platform', ['iphone', 'mac'])
def test_zip_exact_names_and_contents(tmp_path, monkeypatch, sign, platform):
    monkeypatch.setattr(release, 'OUT', tmp_path)
    t = tool(tmp_path)
    since = time.time()
    outputs(t, sign)
    files = release.shortcut_files(t, platform, sign, since)
    assert [name for _, name in files] == PLATFORMS[platform]
    # Old experimental outputs must never be swept into a release.
    (t.path / 'dist' / 'obsolete.wasm').write_bytes(b'old')
    assert [p.name for p in release.encoders(t, since)] == ENCODERS
    path = release.make_zip(t, platform, files)
    folder = t.zip_name(platform)
    assert (
        path.name
        == {
            'iphone': 'compress-photos-shortcuts-v0.1.0.zip',
            'mac': 'compress-photos-mac-shortcuts-v0.1.0.zip',
        }[platform]
    )
    with zipfile.ZipFile(path) as z:
        assert z.namelist() == [f'{folder}/{n}' for n in PLATFORMS[platform]]
        assert z.testzip() is None
        for src, name in files:
            assert z.read(f'{folder}/{name}') == src.read_bytes()


@pytest.mark.parametrize('name', ENCODERS + SHORTCUTS + MAC_SHORTCUTS)
@pytest.mark.parametrize('failure', ['missing', 'empty', 'stale'])
def test_required_files(tmp_path, name, failure):
    t = tool(tmp_path)
    since = time.time()
    outputs(t)
    path = t.path / 'dist' / name
    if failure == 'missing':
        path.unlink()
    elif failure == 'empty':
        path.write_bytes(b'')
    else:
        os.utime(path, (since - 3600, since - 3600))

    with pytest.raises(
        release.ReleaseError,
        match={
            'missing': 'missing',
            'empty': 'empty',
            'stale': 'not rebuilt',
        }[failure],
    ):
        if name in ENCODERS:
            release.encoders(t, since)
        else:
            platform = 'iphone' if name in SHORTCUTS else 'mac'
            release.shortcut_files(t, platform, True, since)


def test_missing_unsigned_import(tmp_path):
    t = tool(tmp_path)
    outputs(t, False)
    (t.path / 'build/shortcuts/JXL-Import.unsigned.wflow').unlink()
    with pytest.raises(release.ReleaseError, match='JXL-Import.*missing'):
        release.shortcut_files(t, 'iphone', False, time.time() - 60)


@pytest.mark.parametrize(
    'damage', ['missing', 'extra', 'duplicate', 'bytes', 'crc']
)
def test_zip_reopened_and_verified(tmp_path, monkeypatch, damage):
    monkeypatch.setattr(release, 'OUT', tmp_path)
    t = tool(tmp_path)
    outputs(t)
    files = release.shortcut_files(t, 'iphone', True, time.time() - 60)
    path = tmp_path / 'bad.zip'
    folder = t.zip_name('iphone')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED) as z:
        for src, name in files:
            if damage == 'missing' and name == SHORTCUTS[1]:
                continue

            z.writestr(
                f'{folder}/{name}',
                b'wrong' if damage == 'bytes' else src.read_bytes(),
            )

        if damage in ('extra', 'duplicate'):
            with (
                pytest.warns(UserWarning)
                if damage == 'duplicate'
                else nullcontext()
            ):
                z.writestr(
                    f'{folder}/{SHORTCUTS[0] if damage == "duplicate" else "extra"}',
                    b'x',
                )

    if damage == 'crc':
        path.write_bytes(
            path.read_bytes().replace(b'SHORTCUT-', b'CORRUPT--', 1)
        )

    with pytest.raises(release.ReleaseError, match='ZIP'):
        release.verify_zip(t, 'iphone', path, files)


def test_make_zip_refuses_incomplete_list(tmp_path, monkeypatch):
    t = tool(tmp_path)
    outputs(t)
    monkeypatch.setattr(release, 'OUT', tmp_path)
    with pytest.raises(release.ReleaseError, match='release.json'):
        release.make_zip(
            t, 'iphone', release.shortcut_files(t, 'iphone', True, 0)[:1]
        )
    # nor the other platform's files
    with pytest.raises(release.ReleaseError, match='release.json'):
        release.make_zip(
            t, 'mac', release.shortcut_files(t, 'iphone', True, 0)
        )


@pytest.mark.parametrize('name', ['jxlbatch.wasm', 'jxlbatch-macos'])
def test_encoder_version_checked(tmp_path, monkeypatch, name):
    t = tool(tmp_path)
    monkeypatch.setattr(release.shutil, 'which', lambda _: '/wasmtime')
    commands = []

    def run(cmd, **kw):
        commands.append([str(c) for c in cmd])
        return 'jxlbatch 0.2.0'

    monkeypatch.setattr(release, 'run', run)
    with pytest.raises(release.ReleaseError, match='not 0.1.0'):
        release.check_encoder_version(t, t.path / 'dist' / name)

    # A .wasm encoder runs through wasmtime, a Mac executable directly.
    expected = (
        ['wasmtime', 'run', str(t.path / 'dist' / name), '--version']
        if name.endswith('.wasm')
        else [str(t.path / 'dist' / name), '--version']
    )
    assert commands == [expected]


def test_native_encoder_needs_no_wasmtime(tmp_path, monkeypatch):
    t = tool(tmp_path)
    monkeypatch.setattr(release.shutil, 'which', lambda _: None)
    monkeypatch.setattr(release, 'run', lambda *a, **k: 'jxlbatch 0.1.0 (x)')
    release.check_encoder_version(t, t.path / 'dist/jxlbatch-macos')
    with pytest.raises(release.ReleaseError, match='wasmtime'):
        release.check_encoder_version(t, t.path / 'dist/jxlbatch.wasm')


def test_build_runs_every_build_script(tmp_path, monkeypatch):
    t = tool(tmp_path)
    scripts = t.path / 'scripts'
    scripts.mkdir()
    for name in (
        'build-wasm.sh',
        'build-macos.sh',
        'build_shortcuts.py',
        'build_mac_shortcuts.py',
    ):
        (scripts / name).write_text('')

    commands = []
    monkeypatch.setattr(
        release,
        'run',
        lambda cmd, **kw: commands.append([str(c) for c in cmd]),
    )
    release.build(t, sign=False)
    assert [c[-2:] if c[-1] == '--no-sign' else c[-1:] for c in commands] == [
        [str(scripts / 'build-wasm.sh')],
        [str(scripts / 'build-macos.sh')],
        ['--guess', '--no-sign'],
        ['--guess', '--no-sign'],
    ]
    assert commands[2][1] == str(scripts / 'build_shortcuts.py')
    assert commands[3][1] == str(scripts / 'build_mac_shortcuts.py')


def baseline(versions=None):
    return {'tag': 'compress-photos-v0.0.9', 'versions': versions or {}}


def test_states_and_notes_for_all_tools(tmp_path):
    photos = tool(tmp_path)
    videos = tool(tmp_path, 'compress-videos', '0.3.0')
    tools = [photos, videos]
    entries = {photos.name: '- Photo fixes', videos.name: '- Video fixes'}
    for previous, expected in [
        (None, ['comparison unavailable', 'comparison unavailable']),
        ({'tag': None, 'versions': {}}, ['new', 'new']),
        (baseline({photos.name: '0.0.9'}), ['updated', 'new']),
        (
            baseline({photos.name: '0.0.9', videos.name: '0.2.0'}),
            ['updated', 'updated'],
        ),
        (
            baseline({photos.name: '0.0.9', videos.name: '0.3.0'}),
            ['updated', 'unchanged'],
        ),
        (
            baseline({photos.name: '0.1.0', videos.name: '0.3.0'}),
            ['unchanged', 'unchanged'],
        ),
    ]:
        states = release.tool_states(tools, previous)
        assert list(states.values()) == expected
        notes = release.release_notes(photos, tools, previous, entries)
        for t, state in zip(tools, expected):
            assert f'{t.title} {t.version} (**{state}**): iPhone, Mac' in notes
            if state in ('new', 'updated'):
                assert entries[t.name] in notes
            elif state == 'unchanged':
                assert entries[t.name] not in notes

        if previous is None:
            assert 'Release comparisons unavailable' in notes
        elif previous['tag'] is None:
            assert 'First release' in notes

    assert photos.tag == 'compress-photos-v0.1.0'


def test_unchanged_selected_tool_refuses_publish(tmp_path):
    t = tool(tmp_path)
    with pytest.raises(release.ReleaseError, match='unchanged'):
        release.require_updated(t, {t.name: 'unchanged'})


def mock_github(monkeypatch, pages, versions):
    monkeypatch.setattr(release, 'run', lambda *a, **k: 'owner/repo')
    calls = []

    def api(endpoint, **kwargs):
        calls.append((endpoint, kwargs))
        if endpoint.endswith('/releases'):
            return pages

        if '/git/ref/' in endpoint:
            return {'ref': 'refs/tags/baseline'}

        name = endpoint.split('/shortcuts/')[1].split('/')[0]
        version = versions.get(name)
        return (
            None
            if version is None
            else {
                'encoding': 'base64',
                'content': base64.b64encode(version.encode()).decode(),
            }
        )

    monkeypatch.setattr(release, 'github', api)
    return calls


def test_first_release_confirmed_by_api(tmp_path, monkeypatch):
    t = tool(tmp_path)
    calls = mock_github(monkeypatch, [[]], {})
    assert release.published_baseline([t]) == {'tag': None, 'versions': {}}
    assert len(calls) == 1


def test_latest_stable_release_and_versions_at_its_tag(tmp_path, monkeypatch):
    photos = tool(tmp_path)
    videos = tool(tmp_path, 'compress-videos')
    pages = [
        [
            {
                'tag_name': 'old',
                'published_at': '2025',
                'draft': False,
                'prerelease': False,
            },
            {
                'tag_name': 'preview',
                'published_at': '2027',
                'draft': False,
                'prerelease': True,
            },
        ],
        [
            {
                'tag_name': 'baseline',
                'published_at': '2026',
                'draft': False,
                'prerelease': False,
            },
            {
                'tag_name': 'draft',
                'published_at': '2028',
                'draft': True,
                'prerelease': False,
            },
        ],
    ]
    calls = mock_github(monkeypatch, pages, {photos.name: '0.0.9\n'})
    assert release.published_baseline([photos, videos]) == {
        'tag': 'baseline',
        'versions': {photos.name: '0.0.9'},
    }
    assert calls[1][0].endswith('/git/ref/tags/baseline')
    assert all('ref=baseline' in endpoint for endpoint, _ in calls[2:])


@pytest.mark.parametrize('dry_run', [True, False])
def test_failed_baseline_lookup(tmp_path, monkeypatch, capsys, dry_run):
    t = tool(tmp_path)

    def fail(_):
        raise release.ReleaseError('offline')

    monkeypatch.setattr(release, 'published_baseline', fail)
    if dry_run:
        assert release.comparison_baseline([t], True) is None
        assert 'comparisons unavailable' in capsys.readouterr().out
    else:
        with pytest.raises(release.ReleaseError, match='unavailable.*offline'):
            release.comparison_baseline([t], False)


@pytest.mark.parametrize(
    'status,missing_ok,expected',
    [
        (404, True, None),
        (404, False, 'error'),
        (403, True, 'error'),
        (500, True, 'error'),
        (200, False, {'ok': True}),
    ],
)
def test_github_only_explicit_404_means_missing(
        monkeypatch, status, missing_ok, expected
):
    monkeypatch.setattr(
        release.subprocess,
        'run',
        lambda *a, **k: SimpleNamespace(
            returncode=0 if status == 200 else 1,
            stdout='{"ok": true}',
            stderr=f'gh: request failed (HTTP {status})',
        ),
    )
    if expected == 'error':
        with pytest.raises(release.ReleaseError, match='baseline'):
            release.github('endpoint', missing_ok)
    else:
        assert release.github('endpoint', missing_ok) == expected


@pytest.mark.parametrize('sign', [True, False])
@pytest.mark.parametrize(
    'missing',
    [
        'jxlbatch-scalar.wasm',
        'jxlbatch-macos',
        'JXL-Import.shortcut',
        'Compress Photo Files (macOS).shortcut',
    ],
)
def test_main_rejects_missing_outputs_before_publishing(
        tmp_path, monkeypatch, sign, missing
):
    t = tool(tmp_path)
    monkeypatch.setattr(release, 'find_tools', lambda: [t])
    monkeypatch.setattr(
        release,
        'comparison_baseline',
        lambda *a: {'tag': None, 'versions': {}},
    )
    monkeypatch.setattr(release, 'changelog_entry', lambda _: '- Added')
    monkeypatch.setattr(release, 'check_git', lambda _: None)
    monkeypatch.setattr(release, 'check_encoder_version', lambda *a: None)
    monkeypatch.setattr(release, 'OUT', tmp_path / 'out')

    def incomplete_build(t, sign):
        outputs(t, sign)
        path = (
            t.path / 'dist' / missing
            if sign or missing in ENCODERS
            else t.path
            / 'build/shortcuts'
            / (missing.removesuffix('.shortcut') + '.unsigned.wflow')
        )
        path.unlink()

    monkeypatch.setattr(release, 'build', incomplete_build)
    monkeypatch.setattr(
        release, 'run', lambda *a, **k: pytest.fail('must not publish')
    )
    monkeypatch.setattr(
        sys,
        'argv',
        ['release.py', t.name] + ([] if sign else ['--dry-run', '--no-sign']),
    )
    with pytest.raises(release.ReleaseError, match='missing'):
        release.main()


def test_changelog_entry_uses_shared_check(tmp_path, monkeypatch):
    t = tool(tmp_path)
    changelog = tmp_path / 'CHANGELOG.md'
    changelog.write_text(
        '# Change Log\n\n## [Compress Photos 0.1.0] - 2026-09-30\n\n- Added\n  - x\n'
    )
    monkeypatch.setattr(release, 'ROOT', tmp_path)
    monkeypatch.setattr(release, 'CHANGELOG', changelog)
    assert release.changelog_entry(t) == '- Added\n  - x'
    changelog.write_text('# Change Log\n')
    with pytest.raises(release.ReleaseError, match='no "## \\[Compress'):
        release.changelog_entry(t)


def test_main_includes_every_changed_tool(tmp_path, monkeypatch, capsys):
    photos = tool(tmp_path)
    videos = tool(tmp_path, 'compress-videos', '0.3.0')
    videos.encoder_names = []
    tools = [photos, videos]
    monkeypatch.setattr(release, 'find_tools', lambda: tools)
    monkeypatch.setattr(
        release,
        'comparison_baseline',
        lambda *a: baseline({photos.name: '0.0.9', videos.name: '0.2.0'}),
    )
    queried = []

    def entry(t):
        queried.append(t.name)
        return f'- Fix {t.name}'

    monkeypatch.setattr(release, 'changelog_entry', entry)
    monkeypatch.setattr(release, 'check_git', lambda _: None)
    monkeypatch.setattr(release, 'check_encoder_version', lambda *a: None)
    monkeypatch.setattr(release, 'OUT', tmp_path / 'out')
    monkeypatch.setattr(release, 'build', outputs)
    monkeypatch.setattr(
        release, 'run', lambda *a, **k: pytest.fail('must not publish')
    )
    monkeypatch.setattr(
        sys, 'argv', ['release.py', photos.name, '--dry-run', '--no-sign']
    )
    release.main()
    printed = capsys.readouterr().out
    assert queried == [photos.name, videos.name]
    assert f'Release {photos.tag} ("Compress Photos 0.1.0")' in printed
    assert '- Fix compress-photos' in printed
    assert '- Fix compress-videos' in printed
    assert '**updated**' in printed


@pytest.mark.parametrize('pages', [{}, [None], [[None]], [[42]]])
def test_bad_release_list_is_not_a_first_release(tmp_path, monkeypatch, pages):
    t = tool(tmp_path)
    mock_github(monkeypatch, pages, {})
    with pytest.raises(release.ReleaseError, match='invalid release list'):
        release.published_baseline([t])


def test_missing_baseline_tag_is_not_a_first_release(tmp_path, monkeypatch):
    t = tool(tmp_path)
    mock_github(
        monkeypatch, [[{'tag_name': 'baseline', 'published_at': '2026'}]], {}
    )
    api = release.github

    def fail_tag(endpoint, **kw):
        if '/git/ref/' in endpoint:
            raise release.ReleaseError('tag missing (HTTP 404)')

        return api(endpoint, **kw)

    monkeypatch.setattr(release, 'github', fail_tag)
    with pytest.raises(release.ReleaseError, match='tag missing'):
        release.published_baseline([t])


def test_bad_baseline_version_is_not_a_new_tool(tmp_path, monkeypatch):
    t = tool(tmp_path)
    mock_github(
        monkeypatch,
        [[{'tag_name': 'baseline', 'published_at': '2026'}]],
        {t.name: 'invalid'},
    )
    with pytest.raises(release.ReleaseError, match='not X.Y.Z'):
        release.published_baseline([t])


WRAPPED = """\
- Changed
  - Only still photos from the photo library are converted, screenshots
    included. Live Photos, videos and items not from Photos (e.g. images shared
    from Files) in the selection are skipped.
  - The photo picker (when started from the Shortcuts app) no longer shows
    videos.
  - Update the shortcuts; `jxlbatch.wasm` is unchanged.
- Full diff
  - https://github.com/jsh9/photo-video-shortcuts/pull/8"""


def test_unwrap_joins_wrapped_list_items():
    assert release.unwrap(WRAPPED) == (
        '- Changed\n'
        '  - Only still photos from the photo library are converted, '
        'screenshots included. Live Photos, videos and items not from Photos '
        '(e.g. images shared from Files) in the selection are skipped.\n'
        '  - The photo picker (when started from the Shortcuts app) no longer '
        'shows videos.\n'
        '  - Update the shortcuts; `jxlbatch.wasm` is unchanged.\n'
        '- Full diff\n'
        '  - https://github.com/jsh9/photo-video-shortcuts/pull/8'
    )


def test_unwrap_joins_paragraphs_and_lazy_continuations():
    text = 'First line\nsecond line.\n\n1. one\ntwo\n2) three\n   four\n'
    assert release.unwrap(text) == (
        'First line second line.\n\n1. one two\n2) three four\n'
    )


def test_unwrap_is_idempotent_and_keeps_blank_lines():
    once = release.unwrap(WRAPPED + '\n\n- Fixed\n  - a\n    b\n')
    assert release.unwrap(once) == once
    assert once.endswith('\n\n- Fixed\n  - a b\n')


def test_unwrap_leaves_other_blocks_alone():
    text = (
        '- Intro text\n'
        '  continues\n'
        '\n'
        '  ```\n'
        '  not wrapped\n'
        '  - kept as is\n'
        '  ```\n'
        '\n'
        '| a | b |\n'
        '| - | - |\n'
        '| 1 | 2 |\n'
        '\n'
        '> quoted\n'
        '> lines\n'
        '\n'
        '## Heading\n'
        'after the heading\n'
        'and more\n'
    )
    assert release.unwrap(text) == text.replace(
        'Intro text\n  continues', 'Intro text continues'
    ).replace('after the heading\nand more', 'after the heading and more')


@pytest.mark.parametrize('end', ['\\', '  '])
def test_unwrap_keeps_hard_line_breaks(end):
    text = f'- first{end}\n  second\n  third\n'
    assert release.unwrap(text) == f'- first{end}\n  second third\n'


def test_unwrap_does_not_take_a_fence_close_for_a_new_fence():
    text = '~~~\n```\n~~~\nplain\ntext\n'
    assert release.unwrap(text) == '~~~\n```\n~~~\nplain text\n'


def test_release_notes_have_no_wrapped_lines(tmp_path):
    photos = tool(tmp_path)
    notes = release.release_notes(
        photos,
        [photos],
        baseline({photos.name: '0.0.9'}),
        {photos.name: WRAPPED},
    )
    assert WRAPPED not in notes
    assert release.unwrap(WRAPPED) in notes
    assert 'screenshots included.' in notes


def test_every_changelog_entry_unwraps_to_one_line_per_item():
    """No line of the real changelog is left as a continuation line."""
    text = release.CHANGELOG.read_text(encoding='utf-8')
    found = list(release.check_changelog.entries(text))
    assert found
    for name, version, _, body in found:
        previous = ''
        for line in release.unwrap(body).split('\n'):
            if previous.strip() and line.strip():
                assert release.LIST_ITEM.match(line), (name, version, line)

            previous = line
