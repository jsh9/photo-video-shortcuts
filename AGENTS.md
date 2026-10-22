# Notes for AI agents

What a new agent session should know before working on this repository. It is
for any agent (Claude, Codex, Copilot, …); people should start with
[README.md](README.md).

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. What this repository is](#1-what-this-repository-is)
- [2. Read first](#2-read-first)
- [3. Repository layout](#3-repository-layout)
- [4. Environment: Mac or not](#4-environment-mac-or-not)
- [5. Checks before committing](#5-checks-before-committing)
- [6. Versions and the changelog](#6-versions-and-the-changelog)
- [7. Compatibility traps](#7-compatibility-traps)
- [8. Git and pull requests](#8-git-and-pull-requests)
- [9. Writing style](#9-writing-style)

______________________________________________________________________

<!--TOC-->

## 1. What this repository is

Apple Shortcuts that compress photos and videos, with the encoders they run:

- **Compress Photos** (`shortcuts/compress-photos/`): converts photos to HEIC
  or JPEG XL. On the iPhone, the shortcuts hand the photos to a-Shell, which
  runs `photobatch.wasm`; a-Shell then starts the helper shortcut
  *Compress-Photos-Import* by URL (from the share sheet) or switches back to
  *Compress Photos* (from the Shortcuts app). On the Mac, Run Shell Script runs
  the native encoder directly (released as `photobatch-macos`, installed as
  `photobatch`). The encoder is C (`src/`), built for WebAssembly (WASI),
  natively against Homebrew, and statically for macOS.
- **Compress Videos** (`shortcuts/compress-videos/`): Mac only for now; ffmpeg
  plus `vidmeta` (C) for the metadata.
- **Stack Photos** (`shortcuts/stack-photos/`): one shortcut for iPhone and Mac
  made of Shortcuts' own actions only (no encoder, no a-Shell, no scripts). It
  stacks photos and writes the stack's date into its JPEG's EXIF through Base64
  Encode, Replace Text and Base64 Decode.

The `.shortcut` files are **generated** by Python
(`shortcuts/<name>/scripts/build_*.py`, on top of `lib/wfkit.py`), never edited
by hand, and published on GitHub Releases, not committed.

## 2. Read first

| Before changing…                     | Read                                                                                                                                  |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| anything in a shortcut's folder      | its `DEVELOPING.md` (how it works, layout, building), e.g. [Compress Photos](shortcuts/compress-photos/DEVELOPING.md)                 |
| what users see or do                 | its `README.md` (iPhone) and `README-mac.md` (Mac), and the top-level [README.md](README.md) (installation)                           |
| tests                                | [tests/README.md](tests/README.md)                                                                                                    |
| versions, the changelog, `release.*` | [docs/releasing.md](docs/releasing.md)                                                                                                |
| a larger feature                     | the design and plan documents in [docs/](docs/) (`*-design.md`, `*-plan.md`) record past decisions and measurements; add one likewise |

## 3. Repository layout

| Path                              | What it is                                                                                         |
| --------------------------------- | -------------------------------------------------------------------------------------------------- |
| `shortcuts/<name>/`               | one tool: `VERSION`, `release.json`, docs, `src/` (encoder), `scripts/` (builds, shortcut builder) |
| `shortcuts/<name>/scripts/mac/`   | the zsh scripts the Mac shortcuts run (templates with `@VERSION@`-style placeholders)              |
| `lib/`                            | shared by all tools: `wfkit.py` (Shortcuts plist builder), `mac/` (AppleScripts, progress, finish) |
| `scripts/`                        | repository-wide: `release.py`, `check_changelog.py`                                                |
| `tests/<name>/`, `tests/scripts/` | pytest, one folder per tool, plus the repository scripts' tests                                    |
| `docs/`                           | shared docs, design notes and plans                                                                |
| `tools/`                          | standalone helpers (e.g. `photo-compare.html`)                                                     |
| `licenses/`                       | third-party licenses of what the release files contain                                             |

Not committed: `build/`, `dist/`, `.deps/` (downloaded toolchains and library
sources), and `tests/samples/` (personal photos and videos, which may contain
GPS locations; never commit them or test outputs made from them).

## 4. Environment: Mac or not

Building the encoders, signing shortcuts, and most tests need macOS on Apple
silicon with Xcode and Homebrew (see [tests/README.md](tests/README.md)). CI
(`.github/workflows/ci.yml`) runs them on `macos-latest`.

In a Linux container (a typical cloud agent session) you can still:

- run `pre-commit run --all-files` (`pip install pre-commit`);
- run `python3 -m pip install -r tests/requirements.txt` and then
  `python3 -m pytest tests/scripts tests/compress-photos/test_shortcuts.py tests/compress-photos/test_mac_shortcuts.py tests/stack-photos`.
  `test_written_file_is_valid` fails there because it needs macOS's `plutil`;
  tests whose build or tool is missing are skipped (in CI they fail instead).

Say plainly in your report what you could not build or run, and never claim a
shortcut was tested on a device unless it was.

## 5. Checks before committing

- `pre-commit run --all-files` must pass. It formats Python (muff, a Ruff fork:
  79 columns, single quotes; `muff.toml`), docstrings, and Markdown (mdformat,
  wrapped at 79 columns, numbered lists and headings, tables realigned, tables
  of contents between `<!--TOC-->` markers regenerated), and checks the
  changelog against each `VERSION`. Run it, then commit what it changed.
- Run the tests that cover what you changed (above, or `tox -e tests` on a
  Mac). Shortcut changes need a test in `tests/<name>/test_shortcuts.py` or
  `test_mac_shortcuts.py`, which read the generated actions.

## 6. Versions and the changelog

- Each tool has its own version in `shortcuts/<name>/VERSION`, shared by its
  shortcuts and its encoder. When a change alters what a tool ships (its
  shortcuts or encoders), bump that tool's `VERSION` (and only that tool's) and
  add a dated entry at the top of [CHANGELOG.md](CHANGELOG.md):
  `## [Compress Photos 0.8.1] - YYYY-MM-DD`, with `Added`, `Changed`, `Fixed`
  sections. Several changes can share one unreleased version.
- Docs-only and test-only changes need no bump.
- Don't rewrite entries of released versions; they describe what shipped.
- Tell users what they must update (shortcuts, encoders, or both); on the Mac
  the shortcuts warn when `photobatch --version` differs from their version.

## 7. Compatibility traps

- a-Shell starts *Compress-Photos-Import* by its name
  (`shortcuts://run-shortcut?name=…`). Renaming a shortcut means every user
  re-adds it: say so in the changelog and in the README's installation steps.
- The files the shortcuts and a-Shell exchange (`jxl_job.txt`, `jxl_done.txt`,
  `jxl_in_*`, `jxl_meta.txt`, …) form a protocol between the shortcuts and the
  encoder, which users may update separately: keep old encoders and old
  shortcuts working, or say in the changelog that both must be updated.
- a-Shell's action formats come from a real shortcut (`scripts/sample/*.plist`,
  via `--fetch`); `--guess` is the hand-written fallback. Don't change action
  identifiers or parameter names without evidence from a shortcut built on the
  device.
- The WebAssembly and macOS encoders must write the same bytes, so the iPhone
  and the Mac give the same copies; the tests compare them. JPEG XL inputs are
  the exception: libjxl's decoder rounds a little differently on the Mac (at
  most a level; `test_jxl_input.py`).
- The repository is GPL-3.0-or-later (x265 is linked in). A new third-party
  library needs its license in `licenses/`.

## 8. Git and pull requests

- **Branch names:** `yyyy-mm-dd-<brief-description>`, the date the work starts
  and a few hyphenated words for the task, e.g.
  `2026-10-01-fix-a-shell-launch`. If your tooling assigns a branch name, use
  that one.
- **Commit and PR titles:** say what changed for the user. A change that bumps
  a version starts with it:
  `Compress Photos 0.8.0: copies take their location from Photos`. Others say
  what they do:
  `Document the green stripe Photos shows for 12 MP JXLs imported on iPhone`.
- Commit bodies explain why, wrapped at about 72 columns.
- PRs are squash-merged into `main`; CI must be green.
- Don't create releases or tags: `scripts/release.py` publishes from the
  owner's Mac (signing needs an Apple ID).

## 9. Writing style

The docs are short, plain and concrete: what happens, on which platform, and
what the user does about it, with measured numbers where there are any. Match
the surrounding text, keep to 79 columns (mdformat rewraps), and update every
doc a change affects (grep for the names you change, including `docs/` and
`tests/README.md`).
