#!/usr/bin/env python3
"""
Checks that CHANGELOG.md matches each shortcut's VERSION file.

For every shortcuts/<name>/VERSION, CHANGELOG.md must have a dated entry, and
it must be the newest (topmost) entry for that shortcut::

    ## [<Title> <version>] - YYYY-MM-DD

Runs as a pre-commit hook, and scripts/release.py uses the same checks.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADING = re.compile(
    r'^## \[(?P<title>.+) (?P<version>\d+\.\d+\.\d+)\] - (?P<date>.*)$',
    re.MULTILINE,
)
DATE = re.compile(r'\d{4}-\d{2}-\d{2}')


def title(name):
    """The changelog title of shortcuts/<name>: "Compress Photos"."""
    return name.replace('-', ' ').title()


def entries(text):
    """(title, version, date, body) for each version entry, top first."""
    found = list(HEADING.finditer(text))
    result = []
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        result.append((
            m['title'],
            m['version'],
            m['date'].strip(),
            text[m.end() : end].strip(),
        ))

    return result


def version_key(version):
    return tuple(int(part) for part in version.split('.'))


def problems(root=ROOT):
    """Every mismatch between CHANGELOG.md and the VERSION files."""
    all_entries = entries((root / 'CHANGELOG.md').read_text(encoding='utf-8'))
    errors = []
    for version_file in sorted((root / 'shortcuts').glob('*/VERSION')):
        name = title(version_file.parent.name)
        version = version_file.read_text(encoding='utf-8').strip()
        where = version_file.relative_to(root)
        mine = [e for e in all_entries if e[0] == name]
        matching = [e for e in mine if e[1] == version]
        if not matching:
            errors.append(
                f'{where} is {version}, but CHANGELOG.md has no '
                f'"## [{name} {version}] - YYYY-MM-DD" entry'
            )
            continue

        if len(matching) > 1:
            errors.append(f'CHANGELOG.md has {name} {version} more than once')

        if not DATE.fullmatch(matching[0][2]):
            errors.append(
                f'CHANGELOG.md: the {name} {version} entry needs a date '
                f'(YYYY-MM-DD), not "{matching[0][2]}"'
            )

        newer = [
            e[1] for e in mine if version_key(e[1]) > version_key(version)
        ]
        if newer:
            errors.append(
                f'{where} is {version}, but CHANGELOG.md already has {name} '
                + ', '.join(newer)
            )
        elif mine[0][1] != version:
            errors.append(
                f'CHANGELOG.md: the {name} {version} entry must come before '
                f'the other {name} entries'
            )

    return errors


def main():
    errors = problems()
    for error in errors:
        print(error, file=sys.stderr)

    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
