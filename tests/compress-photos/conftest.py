"""Fixtures for the Compress Photos tests (macOS: they use Apple's ImageIO)."""

import itertools
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import photo_helpers as ph  # noqa: E402

WASM = ph.TOOL / 'dist' / 'jxlbatch.wasm'
WASM_SCALAR = ph.TOOL / 'dist' / 'jxlbatch-scalar.wasm'
NATIVE = ph.TOOL / 'build' / 'jxlbatch'
MACOS = ph.TOOL / 'dist' / 'jxlbatch-macos'  # the Mac shortcuts' encoder


@pytest.fixture(scope='session')
def helpers(tmp_path_factory):
    """
    The Swift helpers, compiled once: make_photo, imageio_props and hdr_pixels.
    """
    folder = tmp_path_factory.mktemp('helpers')
    return {
        name: ph.compile_swift(ph.HERE / f'{name}.swift', folder / name)
        for name in ('make_photo', 'imageio_props', 'hdr_pixels')
    }


def wasm_encoder(path):
    ph.need(path.exists(), f'{path} is missing; run scripts/build-wasm.sh')
    ph.need(shutil.which('wasmtime'), 'wasmtime is needed (brew install)')
    return ph.Encoder(
        path.name, ['wasmtime', 'run', '--dir', '{dir}::.', path]
    )


@pytest.fixture(scope='session')
def wasm():
    """The WebAssembly build that ships to a-Shell."""
    return wasm_encoder(WASM)


def native_encoder(path, label, build_script):
    ph.need(path.exists(), f'{path} is missing; run {build_script}')
    probe = ph.run([path, '--version'])
    ph.need(
        probe.returncode == 0,
        f'{path} does not run: ' + (probe.stderr.splitlines() or [''])[0],
    )
    return ph.Encoder(label, [path])


@pytest.fixture(scope='session')
def macos():
    """The static macOS build that ships for the Mac shortcuts."""
    return native_encoder(MACOS, 'macos', 'scripts/build-macos.sh')


@pytest.fixture(
    scope='session', params=['wasm', 'wasm-scalar', 'native', 'macos']
)
def encoder(request):
    """
    Every build: SIMD and scalar WebAssembly, the native Mac build against
    Homebrew's libraries (fast to build, for development), and the static macOS
    build that ships for the Mac shortcuts.
    """
    if request.param == 'wasm':
        return wasm_encoder(WASM)

    if request.param == 'wasm-scalar':
        return wasm_encoder(WASM_SCALAR)

    if request.param == 'macos':
        return native_encoder(MACOS, 'macos', 'scripts/build-macos.sh')

    return native_encoder(NATIVE, 'native', 'build-native.sh')


@pytest.fixture(scope='session')
def need_tools():
    for tool in ('exiftool', 'djxl', 'sips'):
        ph.need(shutil.which(tool), f'{tool} is needed')


@pytest.fixture(scope='session')
def photos(tmp_path_factory, helpers, need_tools):
    """The generated test photos: {name: path} (see photo_helpers.PHOTOS)."""
    return ph.make_photos(
        tmp_path_factory.mktemp('photos'), helpers['make_photo']
    )


@pytest.fixture(scope='session')
def imageio(helpers):
    """Reads what Apple's ImageIO (and so Photos) sees: {path: fields}."""

    def read(*paths):
        out = ph.run(
            [helpers['imageio_props'], '--json', *paths], check=True
        ).stdout
        return {r['path']: r for r in json.loads(out)}

    return read


@pytest.fixture(scope='session')
def apple_hdr(helpers, tmp_path_factory):
    """
    Apple's HDR rendering of an image (Core Image, with its gain map and
    orientation applied), as Photos shows it: linear Display P3, 1.0 = SDR
    white.
    """
    folder = tmp_path_factory.mktemp('apple-hdr')
    count = itertools.count()

    def render(path):
        out = folder / f'{next(count)}.f32'
        return ph.apple_hdr_pixels(helpers['hdr_pixels'], path, out)

    return render


@pytest.fixture(scope='session')
def apple_sdr(helpers, tmp_path_factory):
    """
    How an SDR screen shows an image (ImageIO's SDR decoding): linear Display
    P3, 1.0 = SDR white.
    """
    folder = tmp_path_factory.mktemp('apple-sdr')
    count = itertools.count()

    def render(path):
        out = folder / f'{next(count)}.f32'
        return ph.apple_sdr_pixels(helpers['hdr_pixels'], path, out)

    return render


@pytest.fixture(scope='session')
def batch(tmp_path_factory, wasm, photos):
    """
    All test photos converted in one batch at quality 83, as the shortcut runs
    it. ``results``: {name: (original, jxl, saved name)}; ``output``: what
    jxlbatch printed; ``kept``: the names whose original jxl_done.txt marks to
    keep (not to offer for deletion).
    """
    folder = tmp_path_factory.mktemp('batch')
    staged = ph.stage(folder, list(photos.values()))
    result = wasm.run(['-q', '83', '-e', '7', 'jxl_job.txt'], folder)
    assert result.returncode == 0, result.stdout + result.stderr
    done = ph.read_done(folder)
    results, kept = {}, set()
    for name, path in photos.items():
        index = next(i for i, p in staged.items() if p == path)
        jxl, saved = done.get(index, (None, None))
        results[name] = (path, jxl, saved)
        if index in ph.kept_originals(folder):
            kept.add(name)

    return SimpleNamespace(results=results, output=result.stdout, kept=kept)
