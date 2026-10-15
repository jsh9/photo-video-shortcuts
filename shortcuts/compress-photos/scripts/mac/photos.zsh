# Each input is one photo; its job name is the photo's name from Shortcuts
# (NAMES), or else the file's. photobatch strips the extension and adds .jxl.
names=("${(@f)NAMES}")
i=0
for f in "$@"; do
  i=$((i + 1))
  ln -s "${f:A}" "$WORK/jxl_in_$i.orig"
  printf '%d|%s\n' "$i" "${names[$i]:-${f:t}}" >> "$WORK/jxl_job.txt"
done
# The photos' dates in Photos, "index|2024-01-01T17:00:00-05:00" each (the
# shortcut's Dates, one per line; none for a photo without one): photobatch
# writes a date into the copy's EXIF when the original's capture date is
# another moment or missing.
DATES=$(cat <<'JXL_DATES'
@DATES@
JXL_DATES
)
[ -n "$DATES" ] && print -r -- "$DATES" > "$WORK/jxl_dates.txt"
# Their locations in Photos, "index|gps|lat,lon" each (the shortcut's Meta;
# "index|gps|" for a photo Photos has no location for): photobatch writes a
# location into the copy's EXIF, or removes the file's.
META=$(cat <<'JXL_META'
@META@
JXL_META
)
[ -n "$META" ] && print -r -- "$META" > "$WORK/jxl_meta.txt"
@RUN@
# The results stay in jxl_done.txt, one line per converted photo,
# "file|index|delete or keep|Name.jxl" (no file when nothing was converted):
# the shortcut reads it, then each file, from the work folder with Get File,
# the one way a file gets from a script into Shortcuts on the Mac (see the
# shortcut). Nothing is printed: Shortcuts types a script's output by its
# content, and three or more lines whose names each have a comma would reach
# the shortcut as a CSV file, not as text. The work folder stays for the
# shortcut, which removes it at the end (and the next run starts by removing
# what's left). The script's status is 0 whatever photobatch's (1 for a batch
# with nothing converted): errors are in the log, and Run Shell Script would
# fail the shortcut on any other status.
exit 0
