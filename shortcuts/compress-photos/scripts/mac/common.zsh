# @NAME@ @VERSION@, @ROUTE@: converts photos with photobatch.
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
# unique PATH: PATH if nothing is there, else "PATH 2", "PATH 3"... (before
# the extension: "Name 2.heic")
unique() {
  local dest=$1 base=${1%.*} ext=${1##*.} k=2
  while [ -e "$dest" ]; do dest="$base $k.$ext"; k=$((k + 1)); done
  print -r -- "$dest"
}
@WORK_CHECK@
VERSION='@VERSION@'
WATCH=${WATCH:-1}  # 0: no Terminal window following the progress
FORMAT='@FORMAT@'  # heic: HEIC (x265, QUALITY is the RF); anything else: JPEG XL (QUALITY is the quality)
QUALITY='@QUALITY@'
# The format's name for the log, and the keywords the selection route gives
# each copy in Photos (selection.zsh, import.applescript): its format and
# quality, "heic,rf=26" or "jxl,q=83"; every copy of a run has the same.
case $FORMAT in
  heic) FORMAT_NAME=HEIC; KEYWORDS="heic,rf=$QUALITY";;
  *) FORMAT_NAME='JPEG XL'; KEYWORDS="jxl,q=$QUALITY";;
esac
CORES='@CORES@'  # all: several photos at a time, every core; one: one photo, one thread
HDR='@HDR@'  # keep: HDR photos keep their HDR; drop: every photo becomes SDR
# @LABEL@: one per input file, in the same order (see the shortcut)
@LABEL@=$(cat <<'JXL_LINES'
@LINES@
JXL_LINES
)
@SKIPPED@ >> "$LOG"
photobatch=''
for c in "${JXLBATCH:-}" @CANDIDATES@; do  # JXLBATCH: an override (used by the tests)
  if [ -n "$c" ] && [ -x "$c" ]; then photobatch=$c; break; fi
done
if [ -z "$photobatch" ]; then
  echo "ERROR: photobatch is not installed (looked in @LOOKED@)." >> "$LOG"
  echo "Install it: see @HELP_URL@" >> "$LOG"
  exit 0
fi
if ! "$photobatch" --version 2>/dev/null | grep -q "^photobatch $VERSION "; then
  echo "! $photobatch is not photobatch $VERSION, the version this shortcut was made for; see Updating in @HELP_URL@" >> "$LOG"
fi
