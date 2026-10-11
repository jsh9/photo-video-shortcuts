# The photos selected in Photos: Photos exported their original files into
# $WORK/in (see export.applescript), and IDS has one "id|date|filename" line
# per selected photo (or "ERROR: ..."); the date is the photo's in Photos,
# "2024-01-01 17:00:00" on the Mac's clock. A Live Photo's original is a
# photo plus a .mov with the same name: skipped, as on the iPhone, so its
# video is never lost; a video alone is skipped too. Other files are left to
# jxlbatch, which fails them with "unsupported format".
setopt nullglob
case $IDS in
  ERROR*) echo "$IDS" >> "$LOG";;
esac
# filename -> id and date. A name two selected photos share can't be told
# apart in the export, so it gets no id (its copy is saved but joins no
# album, and neither original is collected for deletion) and no date.
typeset -A ids dates seen
for line in "${(@f)IDS}"; do
  case $line in *'|'*'|'*) ;; *) continue;; esac
  rest=${line#*|}
  name=${rest#*|}
  if (( ${+seen[$name]} )); then
    if [ -n "${ids[$name]}" ]; then
      echo "! two or more selected photos are named $name: their copies are saved, but not added to albums, and the originals are not collected" >> "$LOG"
    fi
    ids[$name]=''
    dates[$name]=''
  else
    ids[$name]=${line%%|*}
    dates[$name]=${rest%%|*}
  fi
  seen[$name]=1
done
typeset -a origs
n=0; live=0; videos=0
for f in "$WORK"/in/*(.N); do
  name=${f:t}
  stem=${name:r}
  case ${name:e:l} in
    mov|mp4|m4v)
      [ -n "$(print -l "$WORK/in/${stem}".(#i)(heic|heif|hif|jpg|jpeg|png|dng)(.N))" ] || videos=$((videos + 1))
      continue;;
  esac
  if [ -n "$(print -l "$WORK/in/${stem}".(#i)(mov|mp4|m4v)(.N))" ]; then
    live=$((live + 1))
    continue
  fi
  n=$((n + 1))
  ln -s "$f" "$WORK/jxl_in_$n.orig"
  printf '%d|%s\n' "$n" "$name" >> "$WORK/jxl_job.txt"
  origs[$n]=$name
  # The date for jxlbatch (jxl_dates.txt), with the offset the Mac's time
  # zone had on that date: "2024-01-01T17:00:00-0500". jxlbatch writes it
  # into the copy's EXIF when the original's capture date is another moment
  # or missing. A clock time in the hour that repeats when daylight saving
  # time ends is two moments (AppleScript's dates are clock times): no date
  # then, so that no wrong moment is written; import.applescript gives the
  # copy its original's date in Photos anyway.
  if [ -n "${dates[$name]}" ]; then
    when=$(date -j -f '%Y-%m-%d %H:%M:%S' "${dates[$name]}" '+%s' 2>/dev/null) &&
      [ "$(date -r $((when + 3600)) '+%Y-%m-%d %H:%M:%S')" != "${dates[$name]}" ] &&
      [ "$(date -r $((when - 3600)) '+%Y-%m-%d %H:%M:%S')" != "${dates[$name]}" ] &&
      printf '%d|%s\n' "$n" "$(date -r "$when" '+%Y-%m-%dT%H:%M:%S%z')" >> "$WORK/jxl_dates.txt"
  fi
done
skipped=''
[ "$live" -gt 0 ] && skipped="$live Live Photo(s)"
[ "$videos" -gt 0 ] && skipped="${skipped:+$skipped, }$videos video(s)"
[ -n "$skipped" ] && echo "Skipped $skipped: only still photos are converted." >> "$LOG"
@RUN@
# What follows is Photos' work (import.applescript), which the progress window
# would otherwise show nothing of.
[ -f "$WORK/jxl_done.txt" ] && { echo; echo "Now Photos imports the files, adds them to their albums and collects the originals..."; } >> "$LOG"
# Each result becomes <work>/out/Name.jxl (never replacing a file), and one
# output line per result, "path|original id|delete or keep|Name.jxl", for
# import.applescript. Nothing when nothing was converted.
mkdir -p "$WORK/out"
if [ -f "$WORK/jxl_done.txt" ]; then
  while IFS='|' read -r file idx flag name || [ -n "$file" ]; do
    [ -n "$file" ] || continue
    [ -z "$name" ] && name=$flag  # a line from an older jxlbatch: file|index|name
    dest=$(unique "$WORK/out/$name")
    mv "$WORK/$file" "$dest" || continue
    printf '%s|%s|%s|%s\n' "$dest" "${ids[${origs[$idx]}]}" "$flag" "${dest:t}"
  done < "$WORK/jxl_done.txt"
fi
