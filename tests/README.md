# Tests

The tests run on a Mac: they check results with Apple's ImageIO, the framework
Photos uses. CI runs them on every push.

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Running them](#1-running-them)
- [2. What they cover](#2-what-they-cover)
- [3. Your own photos](#3-your-own-photos)

______________________________________________________________________

<!--TOC-->

## 1. Running them

From the repository root, with [tox](https://tox.wiki):

```bash
tox                              # build everything, then run all tests
tox -e tests                        # run the tests only (uses the existing builds)
tox -e tests -- -k orientation      # pass options to pytest
```

Or without tox, after building:

```bash
python3 -m pip install -r tests/requirements.txt
python3 -m pytest
```

They need:

- the builds: `shortcuts/compress-photos/scripts/build-wasm.sh` (and
  `build-native.sh` for the native build's tests);
- Homebrew `wasmtime exiftool jpeg-xl` (`djxl`, `jxlinfo`), plus `sips`,
  `swiftc` and `dash`, which come with macOS and Xcode.

A test whose build or tool is missing is skipped on your Mac and fails in CI.

## 2. What they cover

`compress-photos/`:

| File                    | What it checks                                                                                                                                                                                                                                     |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_shortcuts.py`     | the generated shortcuts: blocks and variables, a-Shell actions, quality presets, version in the notes, cleanup                                                                                                                                     |
| `test_encoder_cli.py`   | `jxlbatch` (SIMD and scalar WebAssembly, native): version, self-test, arguments, batches with failed photos, the `jxl_done.txt` format                                                                                                             |
| `test_conversion.py`    | end to end: photos written like an iPhone's (HEIC and JPEG, rotated, Display P3, 10-bit, PNG with transparency) keep their EXIF, XMP and what Photos reads, and look the same                                                                      |
| `test_xmp.py`           | ordinary and extended JPEG XMP across all three builds: long descriptions, reordered fragments, namespaces, arrays, structures, duplicate/conflicting properties, invalid packets and orientation                                                  |
| `test_orientation.py`   | all 8 EXIF orientations become upright pixels, exactly                                                                                                                                                                                             |
| `test_memory.py`        | a 24 MP photo at low quality stays well under the memory iOS allows a-Shell                                                                                                                                                                        |
| `test_shortcut_flow.py` | the shortcut's a-Shell commands run as a-Shell runs them (modeled on its source), with a-Shell already open or launched by the shortcut, and the retry when its engine is still starting; then JXL-Import's reading of the results and the cleanup |
| `test_samples.py`       | your own photos, if any (see below)                                                                                                                                                                                                                |

`scripts/`: release manifests, missing/empty/stale outputs, signed and unsigned
ZIP contents and CRCs, encoder versions, mocked GitHub baselines, per-tool
version comparisons and changelog checks.

## 3. Your own photos

Put your own test photos in `tests/samples/compress-photos/` (any subfolders).
`test_samples.py` runs the end-to-end checks on each of them, including the
primary photo's namespace-qualified XMP properties with structured values. HEIF
auxiliary images (depth, segmentation and gain maps) have their own metadata;
those packets are not mixed into the primary photo's properties. Only
orientation normalization and removal of `HasExtendedXMP` are allowed; without
any samples, it is skipped. That folder is not committed: personal photos often
contain GPS locations.
