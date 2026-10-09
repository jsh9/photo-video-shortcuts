# Each input is one photo; its job name is the photo's name from Shortcuts
# (NAMES), or else the file's. jxlbatch strips the extension and adds .jxl.
names=("${(@f)NAMES}")
i=0
for f in "$@"; do
  i=$((i + 1))
  ln -s "${f:A}" "$WORK/jxl_in_$i.orig"
  printf '%d|%s\n' "$i" "${names[$i]:-${f:t}}" >> "$WORK/jxl_job.txt"
done
# The photos' dates in Photos, "index|2024-01-01T17:00:00-05:00" each (the
# shortcut's Dates, one per line; none for a photo without one): jxlbatch
# writes a date into the copy's EXIF when the original's capture date is
# another moment or missing.
DATES=$(cat <<'JXL_DATES'
@DATES@
JXL_DATES
)
[ -n "$DATES" ] && print -r -- "$DATES" > "$WORK/jxl_dates.txt"
@RUN@
# One line per converted photo, jxl_done.txt's "file|index|delete or keep|Name.jxl";
# the shortcut reads each file from the work folder with Get File (the only
# way a file gets from a script into Shortcuts on the Mac; see the shortcut).
# Nothing when nothing was converted. The work folder stays for the shortcut,
# which removes it at the end (and the next run starts by removing what's
# left).
if [ -f "$WORK/jxl_done.txt" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [ -n "$line" ] && printf '%s\n' "$line"
  done < "$WORK/jxl_done.txt"
fi
