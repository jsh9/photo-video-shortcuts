# photo-video-shortcuts

Shortcuts for iPhone (and, later, Mac) that compress your photos and videos
while keeping their metadata (capture date, location, camera) and their albums.
On iPhone, the heavy lifting runs in [a-Shell](https://holzschu.github.io/a-Shell_iOS/),
a free terminal app, because iOS has no JPEG XL encoder or quality-controlled
video encoder of its own.

| Shortcut | What it does | iPhone | Mac |
|---|---|---|---|
| [Compress Photos](shortcuts/compress-photos) | HEIF, JPEG and PNG photos → JPEG XL, saved back to Photos | Yes (with a-Shell) | Planned |
| [Compress Videos](shortcuts/compress-videos) | Videos → smaller H.265 or AV1 copies | Coming soon | Planned |

## Install

Each shortcut's README has the steps. In short: install a-Shell, download the
encoder in a-Shell with one command, then download the shortcuts from
[Releases](https://github.com/jsh9/photo-video-shortcuts/releases) on the iPhone.
Setup shared by all shortcuts: [docs/a-shell.md](docs/a-shell.md).

## Repository layout

| Path | What it is |
|---|---|
| `shortcuts/<name>/` | one folder per shortcut: its README, developer notes, encoder source and build scripts |
| `docs/` | documentation shared by all shortcuts |
| `tests/` | tests (coming soon); `tests/samples/` holds your own test photos and videos and is not committed |
| `licenses/` | licenses of the third-party libraries built into the release files |

## License

GPL-3.0-or-later; see [LICENSE](LICENSE). The release files include
third-party libraries under their own licenses; see [licenses/](licenses).
