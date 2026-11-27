# @NAME@ (the Mac's route from Photos): Photos exported each selected item's
# current version into $WORK/in/<n>, in the selection's order, and ITEMS has
# its "n|date" lines (export.applescript). This copies each item's picture
# into Shortcuts' iCloud Drive folder ($SHARED: Get File reads only there on
# the Mac, and Photos' sandbox can't write there), lists them in list.txt
# ("n/name" lines, Get File's paths below $SHARED) and
# the items with no picture (videos) in skipped.txt, and writes date.txt: the
# latest date plus @DELAY@ seconds, as Format Date's ISO 8601 text, with the
# Mac's offset on that date. The lists have no newline at their end, which
# Split Text could take for an empty last line.
setopt extendedglob nullglob
WORK=@WORK@
SHARED=@SHARED@
ITEMS=$(cat <<'STACK_LINES'
@LINES@
STACK_LINES
)
rm -rf "$SHARED"
mkdir -p "$SHARED" || exit 1
typeset -a names skipped
latest=''
for line in "${(@f)ITEMS}"; do
  n=${line%%|*}
  [[ $n == <-> ]] || continue  # not an item's line
  when=${line#*|}
  pictures=("$WORK/in/$n"/*.(#i)(heic|heif|jpg|jpeg|png|tif|tiff))
  if (( ! ${#pictures} )); then
    skipped+=("$n")
    continue
  fi
  # n/IMG_1234.jpeg: the export's own name (the stack is named after the
  # first photo's), in a folder of its own, as two items may share a name
  name="$n/${pictures[1]:t}"
  mkdir -p "$SHARED/$n" && cp "${pictures[1]}" "$SHARED/$name" || exit 1
  names+=("$name")
  [ -n "$when" ] || continue
  # the clock time, on the Mac's time zone rules for that date
  seconds=$(date -j -f '%Y-%m-%d %H:%M:%S' "$when" +%s 2>/dev/null) || continue
  if [ -z "$latest" ] || (( seconds > latest )); then latest=$seconds; fi
done
print -rn -- "${(pj:\n:)names}" > "$SHARED/list.txt"
print -rn -- "${(pj:\n:)skipped}" > "$SHARED/skipped.txt"
: > "$SHARED/date.txt"
if [ -n "$latest" ]; then
  iso=$(date -j -r $(( latest + @DELAY@ )) '+%Y-%m-%dT%H:%M:%S%z')
  print -rn -- "${iso[1,-3]}:${iso[-2,-1]}" > "$SHARED/date.txt"
fi
rm -rf "$WORK"
