# Releasing

Releases are published by `scripts/release.py` from a Mac: signing the
shortcuts needs macOS and an Apple ID, so it can't run in GitHub Actions.

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Versions](#1-versions)
- [2. Steps](#2-steps)

______________________________________________________________________

<!--TOC-->

## 1. Versions

Each shortcut has its own version in `shortcuts/<name>/VERSION`, shared by its
`.shortcut` files (shown in the note at the top of each shortcut) and its
encoder (for example `jxlbatch --version`). The build scripts read it from
there.

## 2. Steps

1. Bump the shortcut's `VERSION` and add its entry to
   [CHANGELOG.md](../CHANGELOG.md), with the release date:
   `## [Compress Photos 0.2.0] - 2026-10-15`.
2. Merge to `main`.
3. On an up-to-date `main`, run:
   ```bash
   python3 scripts/release.py compress-photos
   ```

The script:

- checks that `main` is clean and the same as on GitHub, that the tag (for
  example `compress-photos-v0.2.0`) doesn't exist yet, and that the changelog
  has a dated entry for the version;
- builds every shortcut, not only the one being released, because every release
  carries the current files of all shortcuts, so the README's "latest" download
  links keep working;
- checks that each file was rebuilt in this run and that each encoder reports
  its shortcut's version;
- zips each shortcut's `.shortcut` files into `<name>-shortcuts-v<version>.zip`
  (inside, the files keep their names with spaces, which GitHub would turn into
  dots in a release file's own name);
- shows the files and release notes (the changelog entry, plus which shortcuts
  changed) and asks before publishing with `gh release create`.

To build and check without publishing, run it with `--dry-run`. CI runs
`--dry-run --no-sign` on every push.
