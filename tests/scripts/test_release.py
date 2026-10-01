"""scripts/release.py: the parts that don't build or publish."""

import os
import time
import zipfile

import pytest
import release


def tool(tmp_path, name='compress-photos', version='0.1.0'):
    path = tmp_path / 'shortcuts' / name
    path.mkdir(parents=True)
    (path / 'VERSION').write_text(version + '\n')
    return release.Tool(path)


def test_tool_names(tmp_path):
    t = tool(tmp_path)
    assert t.title == 'Compress Photos'
    assert t.tag == 'compress-photos-v0.1.0'
    assert t.zip_name == 'compress-photos-shortcuts-v0.1.0'


@pytest.mark.parametrize('version', ['0.1', 'v0.1.0', 'dev', '1.2.3.4'])
def test_tool_rejects_bad_version(tmp_path, version):
    with pytest.raises(release.ReleaseError):
        tool(tmp_path, version=version)


def test_zip_keeps_names_inside_a_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(release, 'OUT', tmp_path)
    t = tool(tmp_path)
    src = tmp_path / 'a.unsigned.wflow'
    src.write_bytes(b'shortcut')
    path = release.make_zip(t, [(src, 'Compress Photos.shortcut')])
    assert path.name == 'compress-photos-shortcuts-v0.1.0.zip'
    with zipfile.ZipFile(path) as z:
        assert z.namelist() == [
            'compress-photos-shortcuts-v0.1.0/Compress Photos.shortcut'
        ]
        assert z.read(z.namelist()[0]) == b'shortcut'


def test_unsigned_shortcuts_named_like_signed(tmp_path):
    t = tool(tmp_path)
    built = t.path / 'build' / 'shortcuts'
    built.mkdir(parents=True)
    (built / 'JXL-Import.unsigned.wflow').write_bytes(b'x')
    files = release.shortcut_files(t, sign=False, since=time.time() - 60)
    assert [name for _, name in files] == ['JXL-Import.shortcut']


def test_stale_build_output_rejected(tmp_path):
    old = tmp_path / 'old.shortcut'
    old.write_bytes(b'x')
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    with pytest.raises(release.ReleaseError, match='not rebuilt'):
        release.fresh(old, since=time.time() - 60)


def test_release_notes(tmp_path):
    photos = tool(tmp_path)
    videos = tool(tmp_path, 'compress-videos', '0.3.0')
    notes = release.release_notes(photos, [photos, videos], '- Added\n  - x')
    assert notes.startswith('- Added\n  - x')
    assert '- Compress Photos 0.1.0 (updated in this release)' in notes
    assert '- Compress Videos 0.3.0 (unchanged)' in notes


def test_changelog_entry_uses_shared_check(tmp_path, monkeypatch):
    t = tool(tmp_path)
    changelog = tmp_path / 'CHANGELOG.md'
    changelog.write_text(
        '# Change Log\n\n## [Compress Photos 0.1.0] - 2026-09-30\n\n'
        '- Added\n  - x\n'
    )
    monkeypatch.setattr(release, 'ROOT', tmp_path)
    monkeypatch.setattr(release, 'CHANGELOG', changelog)
    assert release.changelog_entry(t) == '- Added\n  - x'
    changelog.write_text('# Change Log\n')
    with pytest.raises(release.ReleaseError, match='no "## \\[Compress'):
        release.changelog_entry(t)
