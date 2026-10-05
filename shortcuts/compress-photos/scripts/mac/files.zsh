# Each input is a file or a folder (its image files; subfolders are not
# entered). PATHS holds each input's real location (Get Details of Files ▸ File
# Path), since Shortcuts may pass a temporary copy.
trap 'rm -rf "$WORK"' EXIT
paths=("${(@f)PATHS}")
typeset -a dests
n=0
stage() {  # stage SOURCE DESTINATION-FOLDER NAME
  n=$((n + 1))
  ln -s "${1:A}" "$WORK/jxl_in_$n.orig"
  printf '%d|%s\n' "$n" "$3" >> "$WORK/jxl_job.txt"
  dests[$n]=$2
}
i=0
for f in "$@"; do
  i=$((i + 1))
  orig=${paths[$i]}  # the real location, from the shortcut
  if [ -z "$orig" ]; then
    orig=${f:A}
    case $orig in  # a copy in a temporary or Library folder: location unknown
      "${TMPDIR:-/tmp/}"*|/tmp/*|/private/tmp/*|/var/folders/*|/private/var/folders/*|"$HOME/Library/"*) orig='';;
    esac
  fi
  if [ -d "$f" ]; then
    for g in "$f"/*.(#i)(heic|heif|hif|jpg|jpeg|png)(N.); do stage "$g" "$orig" "${g:t}"; done
  else
    stage "$f" "${orig:+${orig:h}}" "${${orig:-$f}:t}"
  fi
done
@RUN@
# Each result goes next to its original, as Name.jxl, never replacing a file
# ("Name 2.jxl"). When the original's location is unknown (above) or can't be
# written, the result goes to FALLBACK instead.
FALLBACK=@FALLBACK@
wrote=0
move() {  # move RESULT DESTINATION-FOLDER NAME.jxl
  local dir=$2
  if [ -z "$dir" ] || ! [ -d "$dir" ] || ! [ -w "$dir" ]; then dir=$FALLBACK; fi
  mkdir -p "$dir" || return
  local dest
  dest=$(unique "$dir/$3")
  mv "$1" "$dest" && wrote=$((wrote + 1)) && echo "  -> $dest" >> "$LOG"
}
if [ -f "$WORK/jxl_done.txt" ]; then
  while IFS='|' read -r file idx flag name || [ -n "$file" ]; do
    [ -z "$name" ] && name=$flag  # a line from an older jxlbatch: file|index|name
    [ -n "$file" ] && move "$WORK/$file" "${dests[$idx]}" "$name"
  done < "$WORK/jxl_done.txt"
fi
# The log ends with the count; the progress window, if any, with "Done".
{ echo; echo "Wrote $wrote JPEG XL file(s)."; } >> "$LOG"
@FINISH@
# The output: the log, then the count.
cat "$LOG"
echo
echo "Wrote $wrote JPEG XL file(s)."
