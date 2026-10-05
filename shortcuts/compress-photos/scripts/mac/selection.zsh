# The photos selected in Photos: Photos exported their original files into
# $WORK/in (see export.applescript), and IDS has one "id|filename" line per
# selected photo (or "ERROR: ..."). A Live Photo's original is a photo plus a
# .mov with the same name: skipped, as on the iPhone, so its video is never
# lost; a video alone is skipped too. Other files are left to jxlbatch, which
# fails them with "unsupported format".
setopt nullglob
case $IDS in
  ERROR*) echo "$IDS" >> "$LOG";;
esac
# filename -> id. A name two selected photos share can't be told apart in
# the export, so it gets no id: its copy is saved but joins no album, and
# neither original is collected for deletion.
typeset -A ids seen
for line in "${(@f)IDS}"; do
  case $line in *'|'*) ;; *) continue;; esac
  name=${line#*|}
  if (( ${+seen[$name]} )); then
    if [ -n "${ids[$name]}" ]; then
      echo "! two or more selected photos are named $name: their copies are saved, but not added to albums, and the originals are not collected" >> "$LOG"
    fi
    ids[$name]=''
  else
    ids[$name]=${line%%|*}
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
