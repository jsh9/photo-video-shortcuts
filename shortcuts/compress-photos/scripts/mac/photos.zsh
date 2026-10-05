# Each input is one photo; its job name is the photo's name from Shortcuts
# (NAMES), or else the file's. jxlbatch strips the extension and adds .jxl.
names=("${(@f)NAMES}")
i=0
for f in "$@"; do
  i=$((i + 1))
  ln -s "${f:A}" "$WORK/jxl_in_$i.orig"
  printf '%d|%s\n' "$i" "${names[$i]:-${f:t}}" >> "$WORK/jxl_job.txt"
done
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
