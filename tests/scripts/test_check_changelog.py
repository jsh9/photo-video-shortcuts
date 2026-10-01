"""scripts/check_changelog.py: CHANGELOG.md against each shortcut's VERSION."""

import check_changelog
import pytest

ENTRY = """# Change Log

## [Compress Photos 0.1.0] - 2026-09-30

- Added
  - Compress Photos
"""


def repo(tmp_path, version, changelog):
    (tmp_path / 'shortcuts' / 'compress-photos').mkdir(parents=True)
    (tmp_path / 'shortcuts' / 'compress-photos' / 'VERSION').write_text(
        version + '\n'
    )
    (tmp_path / 'CHANGELOG.md').write_text(changelog)
    return tmp_path


def with_entry(version, date, below=False):
    entry = f'## [Compress Photos {version}] - {date}\n\n- Fixed\n  - x\n\n'
    if below:
        return ENTRY + '\n' + entry

    return ENTRY.replace(
        '## [Compress Photos 0.1.0]', entry + '## [Compress Photos 0.1.0]'
    )


@pytest.mark.parametrize(
    ('version', 'changelog', 'problem'),
    [
        ('0.1.0', ENTRY, None),
        ('0.2.0', with_entry('0.2.0', '2026-10-15'), None),
        ('0.2.0', ENTRY, 'has no "## [Compress Photos 0.2.0]'),
        ('0.2.0', with_entry('0.2.0', 'Unreleased'), 'needs a date'),
        (
            '0.2.0',
            with_entry('0.2.0', '2026-10-15', below=True),
            'must come before',
        ),
        ('0.1.0', with_entry('0.2.0', '2026-10-15'), 'already has'),
        (
            '0.1.0',
            ENTRY + '\n' + ENTRY.split('\n', 2)[2],
            'more than once',
        ),
    ],
    ids=[
        'matches',
        'bumped with dated entry on top',
        'bumped without entry',
        'entry not dated',
        'entry below the older one',
        'VERSION behind the changelog',
        'duplicate entry',
    ],
)
def test_problems(tmp_path, version, changelog, problem):
    errors = check_changelog.problems(repo(tmp_path, version, changelog))
    if problem is None:
        assert errors == []
    else:
        assert any(problem in e for e in errors), errors


def test_entries_bodies():
    entries = check_changelog.entries(with_entry('0.2.0', '2026-10-15'))
    assert [(t, v, d) for t, v, d, _ in entries] == [
        ('Compress Photos', '0.2.0', '2026-10-15'),
        ('Compress Photos', '0.1.0', '2026-09-30'),
    ]
    assert entries[0][3] == '- Fixed\n  - x'


def test_title():
    assert check_changelog.title('compress-photos') == 'Compress Photos'


def test_repository_changelog_matches():
    assert check_changelog.problems() == []
