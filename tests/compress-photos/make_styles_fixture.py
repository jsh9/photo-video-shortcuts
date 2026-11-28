"""
Writes fixtures/heif/styles_metadata.heic: a small HEIC whose picture has the
metadata item an iPhone's Photographic Style comes with, a 'uri ' item of the
type tag:apple.com,2023:photo:metadata:styles describing the picture ('cdsc').
Its data here is a stand-in (an iPhone's is about 57 KB, Apple's own format):
the test checks that photobatch's HEIC copy keeps it byte for byte, without
which Photos shows a copy's Style as a filter (macOS 27).

Needs what make_hdr_fixtures.py needs (ffmpeg with libx265). Run from anywhere:
python3 make_styles_fixture.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_hdr_fixtures as mk  # noqa: E402

STYLES = 'tag:apple.com,2023:photo:metadata:styles'
DATA = b'compress-photos test: Photographic Style metadata\n' * 8


def main():
    rgb = np.zeros((48, 64, 3), np.uint8)
    rgb[..., 0] = np.linspace(0, 255, 64)[None, :]
    rgb[..., 1] = np.linspace(0, 255, 48)[:, None]
    rgb[..., 2] = 128
    h = mk.Heif()
    h.primary = mk.coded(h, rgb)
    styles = h.add('uri ', DATA, hidden=True, mime=STYLES)
    h.refs.append(('cdsc', styles, [h.primary]))
    path = mk.LAYOUTS_OUT / 'styles_metadata.heic'
    h.write(path)
    print(f'{path.name} {path.stat().st_size} bytes')


if __name__ == '__main__':
    main()
