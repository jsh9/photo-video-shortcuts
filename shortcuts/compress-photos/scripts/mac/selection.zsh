# The photos selected in Photos: Photos exported their original files into
# $WORK/in (see export.applescript), and IDS has one "id|date|filename" line
# per selected photo (or "ERROR: ..."), then its "id<tab>field<tab>value"
# lines; the date is the photo's in Photos, "2024-01-01 17:00:00" on the
# Mac's clock. A Live Photo's original is a photo plus a .mov with the same
# name: skipped, as on the iPhone, so its video is never lost; a video alone
# is skipped too. Other files are left to photobatch, which fails them with
# "unsupported format".
#
# The files given as arguments are Photos' current version of the selected
# stills, as Shortcuts' Find Photos got them through the album
# "@BRIDGE_ALBUM@" (see build_mac_shortcuts.renderings): an edited photo's
# rendering, an unedited one's original byte for byte. BRIDGE is
# bridge.applescript's answer ("BRIDGE n", or "ERROR: ..."), RDATES their
# dates in Photos ("position|2024-01-01T17:00:00-05:00", on the Mac's clock).
# A rendering is a photo's when the names without extension are the same
# (case aside; Shortcuts names the files "IMG_1234.heic", "IMG_1234.jpeg") and
# the dates, if both have one, at most a second apart, and neither has another
# match. A paired photo whose rendering is the same bytes is unedited, and its
# original is converted; one whose rendering differs is edited, and a copy of
# the rendering is converted (the edit baked in), under the original's name. Only
# for the originals photobatch reads (HEIF, JPEG, PNG, JPEG XL, by their
# names): a RAW's rendering is never converted in its place, so its original
# is never collected. Any other photo is converted from its original, with a
# "!" line (also one photobatch converts though its name isn't listed).
setopt nullglob
zmodload zsh/datetime
case $IDS in
  ERROR*) echo "$IDS" >> "$LOG";;
esac
BRIDGE=$(cat <<'JXL_BRIDGE'
@BRIDGE@
JXL_BRIDGE
)
RDATES=$(cat <<'JXL_RDATES'
@DATES@
JXL_RDATES
)
renderings=("$@")
# clock TIME: the seconds of "2024-01-01 17:00:00" on the Mac's clock, or
# nothing
clock() { [ -n "$1" ] && strftime -r '%Y-%m-%d %H:%M:%S' "$1" 2>/dev/null; }
typeset -A rwhen
for line in "${(@f)RDATES}"; do
  [[ $line == <->'|'* ]] || continue
  d=${line#*|}
  rwhen[${line%%|*}]=$(clock "${d[1,10]} ${d[12,19]}")
done
# readable NAME: whether photobatch reads the file NAME (and a rendering may
# take its place)
readable() { [[ ${1:e:l} == (heic|heif|hif|jpg|jpeg|jpe|jfif|png|jxl) ]]; }
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
# The renderings' positions by name without extension, lowercased (the key
# has an "x" in front: a name may be only an extension)
typeset -A bystem
for (( k = 1; k <= ${#renderings}; k++ )); do
  bystem[x${${renderings[k]:t}:r:l}]+=" $k"
done
# candidates NAME: the positions of the renderings that may be the photo
# NAME's, in $reply
candidates() {
  local o w k
  o=$(clock "${dates[$1]}")
  reply=()
  for k in ${=bystem[x${${1:r}:l}]}; do
    w=${rwhen[$k]}
    [ -n "$o" ] && [ -n "$w" ] && (( w - o > 1 || o - w > 1 )) && continue
    reply+=($k)
  done
}
# how many of the exported photos each rendering may be
typeset -A claims
for f in "$WORK"/in/*(.N); do
  readable "${f:t}" || continue
  candidates "${f:t}"
  for k in $reply; do claims[$k]=$(( ${claims[$k]:-0} + 1 )); done
done
typeset -a origs edited unchecked ens
# the edited photos, by job index: Photos' rendering and the photo's id
typeset -A erender eid
n=0; live=0; videos=0
for f in "$WORK"/in/*(.N); do
  name=${f:t}
  stem=${name:r}
  case ${name:e:l} in
    mov|mp4|m4v)
      [ -n "$(print -l "$WORK/in/${stem}".(#i)(heic|heif|hif|jpg|jpeg|png|jxl|dng)(.N))" ] || videos=$((videos + 1))
      continue;;
  esac
  if [ -n "$(print -l "$WORK/in/${stem}".(#i)(mov|mp4|m4v)(.N))" ]; then
    live=$((live + 1))
    continue
  fi
  n=$((n + 1))
  src=$f
  if readable "$name"; then
    candidates "$name"
    if [ -n "${ids[$name]}" ] && (( ${#reply} == 1 )) && (( ${claims[${reply[1]}]:-0} == 1 )) && [ -r "${renderings[${reply[1]}]}" ]; then
      r=${renderings[${reply[1]}]}
      /usr/bin/cmp -s "$r" "$f" 2>/dev/null
      case $? in
        0) ;;  # unedited: its original
        1)
          # Edited (prototype): its original is converted as job n (the
          # base); Photos' rendering is converted apart, as the look, and
          # Compress Photos Helper saves both with the edit (below).
          edited+=("$name")
          ens+=($n)
          erender[$n]=$r
          eid[$n]=${ids[$name]};;
        *) unchecked+=("$name");;  # unreadable
      esac
    else
      unchecked+=("$name")
    fi
  fi
  [ -n "$src" ] && ln -s "$src" "$WORK/jxl_in_$n.orig"
  printf '%d|%s\n' "$n" "$name" >> "$WORK/jxl_job.txt"
  origs[$n]=$name
  # The date for photobatch (jxl_dates.txt), with the offset the Mac's time
  # zone had on that date: "2024-01-01T17:00:00-0500". photobatch writes it
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
# What else Photos has for each photo, from IDS' "id<tab>field<tab>value"
# lines (the location; the title, caption and keywords stay in Photos'
# library, so export.applescript gives none): jxl_meta.txt, by job index,
# values as they are, for photobatch to write into the copies. A name two
# selected photos share has no id, so no lines.
typeset -A jobs
for (( i = 1; i <= n; i++ )); do
  id=${ids[${origs[$i]}]}
  [ -n "$id" ] && jobs[$id]=$i
done
for line in "${(@f)IDS}"; do
  case $line in *$'\t'*$'\t'*) ;; *) continue;; esac
  id=${line%%$'\t'*}
  rest=${line#*$'\t'}
  [ -n "${jobs[$id]}" ] && printf '%d|%s|%s\n' "${jobs[$id]}" "${rest%%$'\t'*}" "${rest#*$'\t'}" >> "$WORK/jxl_meta.txt"
done
skipped=''
[ "$live" -gt 0 ] && skipped="$live Live Photo(s)"
[ "$videos" -gt 0 ] && skipped="${skipped:+$skipped, }$videos video(s)"
[ -n "$skipped" ] && echo "Skipped $skipped: only still photos are converted." >> "$LOG"
# Edited photos (prototype): each is saved with its edit, so that the edit can
# still be reverted in Photos. Compress Photos Helper (PhotoKit) reads its
# edit record now, and after the conversion makes one photo of three things:
# the copy of its original (job n, the chosen format), the edit record, and
# the copy of Photos' rendering (the look, always HEIC: Photos keeps no JPEG
# XL look), converted apart in $WORK/looks. Nothing is baked in: a photo whose
# edit can't be kept gets no copy, and its original isn't collected. The
# helper's files are in $E (where its PhotoKit calls were checked); it is
# found in ~/Applications or /Applications (PHOTOEDITS: another program,
# run directly; the tests use it), started with `open -W`, and answers in
# $E/COMMAND.out, whole only with its "photoedits ... protocol 1" first line
# and "end" last.
E="$HOME/Library/Caches/compress-photos-macos/edits"
typeset -A eok enote lookof
helper=''
# photoedits COMMAND: runs the helper's COMMAND on $E; 0 if it answered whole
photoedits() {
  /bin/rm -f "$E/$1.out"
  if [[ $helper == *.app ]]; then
    open -W -n -g -a "$helper" --args "$1" "$E" 2>> "$LOG"
  else
    "$helper" "$1" "$E" 2>> "$LOG"
  fi
  [ -f "$E/$1.out" ] && head -1 "$E/$1.out" | grep -q '^photoedits .* protocol 1$' && [ "$(tail -1 "$E/$1.out")" = end ]
}
if (( ${#ens} )); then
  [ -d "$E" ] && /bin/rm -r "$HOME/Library/Caches/compress-photos-macos/edits"
  mkdir -p "$E"
  for n in $ens; do
    mkdir -p "$E/$n"
    ln -s "$WORK/in/${origs[$n]}" "$E/$n/original"
    print -r -- "$n|${eid[$n]}" >> "$E/check.txt"
  done
  for c in "${PHOTOEDITS:-}" "$HOME/Applications/Compress Photos Helper.app" "/Applications/Compress Photos Helper.app"; do
    if [ -n "$c" ] && [ -e "$c" ]; then helper=$c; break; fi
  done
  names=()
  for n in $ens; do names+=("${origs[$n]}"); done
  if [ -z "$helper" ]; then
    echo "! Compress Photos Helper is not installed (~/Applications): ${#ens} edited photo(s) not converted: ${(j:, :)names}" >> "$LOG"
  elif ! photoedits check; then
    echo "! Compress Photos Helper gave no answer: ${#ens} edited photo(s) not converted: ${(j:, :)names}" >> "$LOG"
  elif ! grep -qx 'access|3' "$E/check.out"; then
    echo "! Compress Photos Helper has no full access to Photos (System Settings > Privacy & Security > Photos): ${#ens} edited photo(s) not converted: ${(j:, :)names}" >> "$LOG"
  else
    while IFS='|' read -r n verdict note || [ -n "$n" ]; do
      [[ $n == <-> ]] && [ -n "${eid[$n]}" ] || continue
      if [ "$verdict" = ok ]; then
        eok[$n]=1
        enote[$n]=$note
      else
        echo "! ${origs[$n]}: its edit can't be read ($note): not converted" >> "$LOG"
      fi
    done < "$E/check.out"
  fi
  # The looks: a copy of each rendering (photobatch can't read it where
  # Shortcuts keeps it, in its group container, which macOS guards as another
  # app's data; Apple's cp can), with the photo's date and location lines.
  mkdir -p "$WORK/looks"
  k=0
  for n in $ens; do
    [ -n "${eok[$n]}" ] || continue
    if ! /bin/cp "${erender[$n]}" "$WORK/looks/jxl_in_$((k + 1)).orig" 2>/dev/null; then
      echo "! ${origs[$n]}: Photos' rendering of it can't be read: not converted" >> "$LOG"
      unset "eok[$n]"
      continue
    fi
    k=$((k + 1))
    lookof[$n]=$k
    printf '%d|%s\n' "$k" "${origs[$n]}" >> "$WORK/looks/jxl_job.txt"
    for f in jxl_dates.txt jxl_meta.txt; do
      [ -f "$WORK/$f" ] && grep "^$n|" "$WORK/$f" | sed "s/^$n|/$k|/" >> "$WORK/looks/$f"
    done
  done
  # An edited photo whose edit can't be kept isn't converted at all.
  if [ -f "$WORK/jxl_job.txt" ]; then
    : > "$WORK/jxl_job.kept"
    while IFS='|' read -r n rest || [ -n "$n" ]; do
      [ -n "${erender[$n]}" ] && [ -z "${eok[$n]}" ] && continue
      print -r -- "$n|$rest" >> "$WORK/jxl_job.kept"
    done < "$WORK/jxl_job.txt"
    mv "$WORK/jxl_job.kept" "$WORK/jxl_job.txt"
    [ -s "$WORK/jxl_job.txt" ] || /bin/rm -f "$WORK/jxl_job.txt"
  fi
  kept=()
  for n in $ens; do
    [ -n "${eok[$n]}" ] && kept+=("${origs[$n]}${enote[$n]:+ (may not come out right: ${enote[$n]})}")
  done
  if (( ${#kept} )); then
    echo "${#kept} edited photo(s) are saved with their edits, which can be reverted in Photos (prototype): ${(j:, :)kept}" >> "$LOG"
  fi
fi
if (( ${#unchecked} && ${#renderings} )); then
  echo "! could not check ${#unchecked} photo(s) for edits: converted from the original file(s), without edits made in Photos. Look at the copies before deleting the originals: ${(j:, :)unchecked}" >> "$LOG"
elif (( ${#unchecked} )); then
  case $BRIDGE in
    ERROR*) why=$BRIDGE;;
    'BRIDGE '[1-9]*) why='Shortcuts found no photos in the album @BRIDGE_ALBUM@';;
    'BRIDGE 0') why='Photos put none of them into the album @BRIDGE_ALBUM@';;
    *) why='the album script gave no answer';;
  esac
  echo "! could not check the photos for edits ($why): edited photos are converted from their original files, without the edits. Look at the copies before deleting the originals." >> "$LOG"
fi
@RUN@
# The edited photos' looks, as HEIC (at the chosen RF; 26 when the copies are
# JPEG XL), then the helper makes each edited photo's copy.
typeset -A ecreated
if [ -f "$WORK/looks/jxl_job.txt" ]; then
  { echo; echo "The edited photos' looks, as Photos shows them (HEIC):"; } >> "$LOG"
  case $FORMAT in
    heic) lrf=$QUALITY;;
    *) lrf=26;;
  esac
  "$photobatch" --mac --heic --rf "$lrf" "${cores[@]}" "${hdr[@]}" -C "$WORK/looks" jxl_job.txt >> "$LOG" 2>&1
  typeset -A basefile basename_ lookfile
  if [ -f "$WORK/jxl_done.txt" ]; then
    while IFS='|' read -r file idx flag name || [ -n "$file" ]; do
      [ -n "$file" ] || continue
      basefile[$idx]=$file
      basename_[$idx]=${name:-$flag}
    done < "$WORK/jxl_done.txt"
  fi
  if [ -f "$WORK/looks/jxl_done.txt" ]; then
    while IFS='|' read -r file idx rest || [ -n "$file" ]; do
      [ -n "$file" ] && lookfile[$idx]=$file
    done < "$WORK/looks/jxl_done.txt"
  fi
  : > "$E/create.txt"
  for n in $ens; do
    [ -n "${lookof[$n]}" ] || continue
    b=${basefile[$n]}
    l=${lookfile[${lookof[$n]}]}
    if [ -z "$b" ] || [ -z "$l" ]; then
      echo "! ${origs[$n]}: not saved (its original or its look didn't convert; see above)" >> "$LOG"
      continue
    fi
    /bin/cp "$WORK/$b" "$E/$n/base.${b:e}" && /bin/cp "$WORK/looks/$l" "$E/$n/look.heic" &&
      print -r -- "$n|${basename_[$n]}" >> "$E/create.txt"
  done
  if [ -s "$E/create.txt" ]; then
    if ! photoedits create; then
      echo "! Compress Photos Helper gave no answer when saving the edited photos: none of them saved" >> "$LOG"
    else
      while IFS='|' read -r n verdict id note || [ -n "$n" ]; do
        [[ $n == <-> ]] && [ -n "${eid[$n]}" ] || continue
        case $verdict in
          created) ecreated[$n]=$id
            [ -n "$note" ] && echo "! ${origs[$n]}: saved with its edit; note: $note" >> "$LOG";;
          unsure) ecreated[$n]=$id
            echo "! ${origs[$n]}: saved with its edit, but $note" >> "$LOG";;
          *) echo "! ${origs[$n]}: Photos didn't take the copy with its edit ($id): not saved" >> "$LOG";;
        esac
      done < "$E/create.out"
    fi
  fi
fi
# A photo photobatch converted though readable() doesn't know its name (a
# JPEG named ".jpeg2", say: photobatch goes by the content) was never checked
# for edits.
typeset -a unlisted
if [ -f "$WORK/jxl_done.txt" ]; then
  while IFS='|' read -r file idx rest || [ -n "$file" ]; do
    [ -n "$file" ] && [ -n "${origs[$idx]}" ] && ! readable "${origs[$idx]}" && unlisted+=("${origs[$idx]}")
  done < "$WORK/jxl_done.txt"
fi
if (( ${#unlisted} )); then
  echo "! ${#unlisted} photo(s) not checked for edits (a file type the check doesn't know): converted from the original file(s), without edits made in Photos. Look at the copies before deleting the originals: ${(j:, :)unlisted}" >> "$LOG"
fi
# What follows is Photos' work (import.applescript), which the progress window
# would otherwise show nothing of.
[ -f "$WORK/jxl_done.txt" ] && { echo; echo "Now Photos imports the files, adds them to their albums and collects the originals..."; } >> "$LOG"
# Each result becomes <work>/out/Name.jxl (never replacing a file), and one
# output line per result, "path|original id|delete or keep|Name.jxl|keywords",
# for import.applescript. Nothing when nothing was converted. The keywords are
# the copy's format and quality (KEYWORDS, common.zsh: "jxl,q=83",
# "heic,RF=26"), which import.applescript gives it in Photos only, with
# "compr" (never in the file).
mkdir -p "$WORK/out"
if [ -f "$WORK/jxl_done.txt" ]; then
  while IFS='|' read -r file idx flag name || [ -n "$file" ]; do
    [ -n "$file" ] || continue
    [ -z "$name" ] && name=$flag  # a line from an older photobatch: file|index|name
    # An edited photo: its copy is already in Photos ("id:<its id>"), or it
    # has none (the log says why).
    if [ -n "${erender[$idx]}" ]; then
      [ -n "${ecreated[$idx]}" ] &&
        printf 'id:%s|%s|%s|%s|%s\n' "${ecreated[$idx]}" "${ids[${origs[$idx]}]}" "$flag" "$name" "$KEYWORDS"
      continue
    fi
    dest=$(unique "$WORK/out/$name")
    mv "$WORK/$file" "$dest" || continue
    printf '%s|%s|%s|%s|%s\n' "$dest" "${ids[${origs[$idx]}]}" "$flag" "${dest:t}" "$KEYWORDS"
  done < "$WORK/jxl_done.txt"
fi
