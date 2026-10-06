# @NAME@ @VERSION@, @ROUTE@: converts photos with jxlbatch.
# Help: @HELP_URL@
setopt extendedglob
@WORK_SETUP@
# The log (and the progress window's script) stay out of iCloud Drive and
# Pictures: Terminal reads them without asking for access to those folders.
# One log per route, so that runs of different routes don't clobber each other.
LOGDIR="$HOME/Library/Caches/compress-photos-macos"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/@ROUTE@.log"
: > "$LOG"
# unique PATH: PATH if nothing is there, else "PATH 2", "PATH 3"... (for .jxl)
unique() {
  local dest=$1 base=${1%.jxl} k=2
  while [ -e "$dest" ]; do dest="$base $k.jxl"; k=$((k + 1)); done
  print -r -- "$dest"
}
@WORK_CHECK@
VERSION='@VERSION@'
WATCH=${WATCH:-1}  # 0: no Terminal window following the progress
QUALITY='@QUALITY@'
CORES='@CORES@'  # all: several photos at a time, every core; one: one photo, one thread
HDR='@HDR@'  # keep: HDR photos become HDR (PQ) JPEG XL; drop: every photo becomes SDR
# @LABEL@: one per input file, in the same order (see the shortcut)
@LABEL@=$(cat <<'JXL_LINES'
@LINES@
JXL_LINES
)
@SKIPPED@ >> "$LOG"
jxlbatch=''
for c in "${JXLBATCH:-}" @CANDIDATES@; do  # JXLBATCH: an override (used by the tests)
  if [ -n "$c" ] && [ -x "$c" ]; then jxlbatch=$c; break; fi
done
if [ -z "$jxlbatch" ]; then
  echo "ERROR: jxlbatch is not installed (looked in @LOOKED@)." >> "$LOG"
  echo "Install it: see @HELP_URL@" >> "$LOG"
  exit 0
fi
if ! "$jxlbatch" --version 2>/dev/null | grep -q "^jxlbatch $VERSION "; then
  echo "! $jxlbatch is not jxlbatch $VERSION, the version this shortcut was made for; see Updating in @HELP_URL@" >> "$LOG"
fi
