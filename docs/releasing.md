# Releasing

Placeholder. The release process, to be filled in before the first release:

1. Bump the changed shortcut's version (its shortcut files and its encoder
   share one version) and update [CHANGELOG.md](../CHANGELOG.md).
2. Build every shortcut's release files on a Mac: each `scripts/build-wasm.sh`
   and `scripts/build_shortcuts.py`. Signing the shortcuts needs macOS and an
   Apple ID, so releases are built locally.
3. Tag the release after the shortcut that changed, for example
   `compress-photos-v1.2.0`.
4. Attach the current files of **all** shortcuts, so the "latest" download
   links keep working for every shortcut. The notes say which files changed.
   - Each shortcut's `.shortcut` files go into one ZIP named after the shortcut
     and its version, for example `compress-photos-shortcuts-v0.1.0.zip`.
     Inside, the files keep their names with spaces (GitHub would replace the
     spaces in a release file's own name with dots).
   - Encoders are attached as they are, with fixed names (for example
     `jxlbatch.wasm`), so the "latest" download link in the README always
     works.
