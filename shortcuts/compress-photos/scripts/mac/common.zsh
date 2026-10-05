# @NAME@ @VERSION@: converts the photos Shortcuts passes as files ("$@")
# with jxlbatch. Help: @HELP_URL@
setopt extendedglob
@WORK_SETUP@
rm -rf "$WORK"
mkdir -p "$WORK"
LOG="$WORK/jxl_log.txt"
: > "$LOG"
@WORK_CHECK@
VERSION='@VERSION@'
QUALITY='@QUALITY@'
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
