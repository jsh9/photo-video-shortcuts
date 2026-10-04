# Releasing

Releases are published by `scripts/release.py` from a Mac: signing the
shortcuts needs macOS and an Apple ID, so it can't run in GitHub Actions.

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Versions](#1-versions)
- [2. Required files](#2-required-files)
- [3. Release comparisons](#3-release-comparisons)
- [4. Steps](#4-steps)

______________________________________________________________________

<!--TOC-->

## 1. Versions

Each shortcut has its own version in `shortcuts/<name>/VERSION`, shared by its
`.shortcut` files (shown in the note at the top of each shortcut) and its
encoder (for example `jxlbatch --version`). The build scripts read it from
there.

Bump only the tools that change.

## 2. Required files

Each tool with a `VERSION` also needs a `release.json`. Compress Photos
declares:

```json
{
  "encoders": ["jxlbatch.wasm", "jxlbatch-scalar.wasm", "jxlbatch-macos"],
  "shortcuts": {
    "iphone": ["Compress Photos.shortcut", "JXL-Import.shortcut"],
    "mac": ["Compress Photos (macOS).shortcut", "Compress Photo Files (macOS).shortcut"]
  }
}
```

`shortcuts` is a list (iPhone shortcuts) or a dictionary with the platforms
`iphone` and `mac`. An encoder is a `.wasm` file (run with `wasmtime`) or a
native Mac executable, a name without an extension (run directly; releases are
built on a Mac).

Encoder files and signed shortcuts come from that tool's `dist/`. Every
declared file must exist, contain data, and have been regenerated during its
current build. Extra files in `dist/` are ignored. The script runs each
encoder's `--version` and checks it against the tool's `VERSION`.

Each platform gets its own ZIP, `<name>-shortcuts-v<version>.zip` for the
iPhone (the name from before there were Mac shortcuts, so existing links keep
working) and `<name>-mac-shortcuts-v<version>.zip` for the Mac, with exactly
the declared shortcuts under a folder of the ZIP's name. After writing a ZIP,
the script reopens it, checks every member and CRC, and compares its contents
with the source bytes. A missing shortcut or encoder fails the check, including
CI's dry run.

With `--no-sign`, each declared `Name.shortcut` maps to
`build/shortcuts/Name.unsigned.wflow`. The ZIP still uses the `.shortcut`
member names; these unsigned ZIPs are for validation and cannot be published.

## 3. Release comparisons

The script reads GitHub's published releases, excludes drafts and prereleases,
and selects the most recently published stable release. It then reads each
included tool's `VERSION` at that release's tag, including tools other than the
one selected for the release title and tag.

The notes mark a tool **new** when it had no version at that tag, **updated**
when its version differs, or **unchanged** when it matches. Notes include the
current changelog entry for every new or updated tool, with the lines of each
paragraph or list item joined into one: `CHANGELOG.md` is wrapped at 79
columns, but GitHub shows every newline in a release's notes as a line break.
An unchanged selected tool cannot be published; bump its version first. A
successful lookup that finds no published stable releases marks every included
tool new.

Publishing stops if the baseline lookup fails. An offline dry run may continue,
but both the console output and generated notes explicitly say comparisons are
unavailable. CI passes its existing read-only `GH_TOKEN` to this step; no
publishing permissions are needed. Local release checks require an
authenticated `gh` CLI with read access to the repository.

## 4. Steps

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
  links keep working (for Compress Photos: `build-wasm.sh`, `build-macos.sh`,
  `build_shortcuts.py` and `build_mac_shortcuts.py`);
- checks the complete `release.json` file lists, freshness, nonempty outputs,
  encoder versions and ZIP integrity;
- zips each platform's `.shortcut` files into `<name>-shortcuts-v<version>.zip`
  (iPhone) and `<name>-mac-shortcuts-v<version>.zip` (Mac); inside, the files
  keep their names with spaces and parentheses, which GitHub would alter in a
  release file's own name;
- shows the files and release notes (every changed tool's changelog entry, plus
  the version comparison for all tools) and asks before publishing with
  `gh release create`.

To build and check without publishing, run it with `--dry-run`. CI runs
`--dry-run --no-sign` on every push.

For local delivery verification, run from the repository root:

```bash
python3 -m tox
pre-commit run --all-files
python3 scripts/release.py compress-photos --dry-run --no-sign
python3 scripts/release.py compress-photos --dry-run
```

The last command regenerates signed shortcuts and verifies their ZIP. A dry run
permits a working branch with uncommitted changes; it still enforces the
required build files and archive checks. It never creates a tag or release.
