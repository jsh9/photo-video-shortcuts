# How the shortcuts work with a-Shell

Placeholder, for contributors. This page will describe the design shared by the
iPhone shortcuts:

- Shortcuts copies the inputs into a-Shell's shared folder and writes a job
  file; a-Shell runs a WebAssembly encoder on it.
- The handoff back: a-Shell opens an import shortcut by URL (from the share
  sheet), or switches back to the waiting shortcut (from the Shortcuts app).
- The marker files (`*_started`, `*_done.txt`) and the retry when a-Shell's
  WebAssembly engine is still starting.
- Limits: a-Shell must stay in the foreground; WebAssembly runs on one core;
  iOS stops a-Shell's engine if it uses too much memory.

Each shortcut's DEVELOPING.md has its details for now.
