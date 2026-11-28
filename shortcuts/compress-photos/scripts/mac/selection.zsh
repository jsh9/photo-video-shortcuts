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
# original is converted; one whose rendering differs is edited: Compress
# Photos Helper saves its copy with the edit, which can then be reverted in
# Photos (below), or, when it can't, a copy of the rendering is converted (the
# edit burnt in), under the original's name, with the keyword "burnt-in". Only
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
typeset -a origs unchecked ens
# The edited photos' job indices (ens), and each one's id in Photos; their
# renderings are in $WORK/renders, by job index. photobatch can't read a
# rendering where Shortcuts keeps it (its group container, which macOS guards
# as another app's data, kTCCServiceSystemPolicyAppDataDetailed, and a
# background run can't ask for: "Operation not permitted"); Apple's cp and cmp
# can (macOS 27), so by their paths, not another on PATH.
typeset -A eid
mkdir -p "$WORK/renders"
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
          # Edited: its original stays job n for now (below)
          if /bin/cp "$r" "$WORK/renders/$n" 2>/dev/null; then
            ens+=($n)
            eid[$n]=${ids[$name]}
          else
            /bin/rm -f "$WORK/renders/$n"
            unchecked+=("$name")
          fi;;
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
# Edited photos: each is saved with its edit, so that the edit can still be
# reverted in Photos. Compress Photos Helper (PhotoKit) reads its edit record
# now, and after the conversion makes one photo of three things: the copy of
# its original (job n, in the chosen format), the edit record, and the copy of
# its rendering (the look, always HEIC: Photos keeps no JPEG XL look),
# converted apart in $WORK/looks. A photo whose edit can't be kept (no helper,
# no access to Photos, an edit made by another app...) is converted from its
# rendering instead, the edit burnt in (burnt: why): its rendering becomes job
# n now, or, when Photos doesn't take the copy with its edit, is converted
# apart after all, in $WORK/bake (late: why). The helper works in $E (emptied
# by every run, and of the photos' files once done); it is found in
# ~/Applications or /Applications (PHOTOEDITS: another program, run directly,
# and no other; the tests use it), started with `open -W`, and answers in
# $E/COMMAND.out: its "photoedits <version> protocol 2" line first, one line
# per photo, then "end" (it writes the file again after each line).
E="$HOME/Library/Caches/compress-photos-macos/edits"
typeset -A eok enote lookof burnt late
helper=''
[ -d "$E" ] && /bin/rm -r "$HOME/Library/Caches/compress-photos-macos/edits"
# photoedits COMMAND: runs the helper's COMMAND on $E. 0: it answered whole;
# 1: no answer; 2: another protocol; 3: cut short (its lines so far count)
photoedits() {
  local first
  /bin/rm -f "$E/$1.out"
  if [[ $helper == *.app ]]; then
    open -W -n -g -a "$helper" --args "$1" "$E" >> "$LOG" 2>&1
  else
    "$helper" "$1" "$E" >> "$LOG" 2>&1
  fi
  [ -f "$E/$1.out" ] || return 1
  first=$(head -1 "$E/$1.out")
  [[ $first == 'photoedits '* ]] || return 1
  [[ $first == *' protocol 2' ]] || return 2
  [ "$(tail -1 "$E/$1.out")" = end ] || return 3
}
if (( ${#ens} )); then
  if (( ${+PHOTOEDITS} )); then
    places=("$PHOTOEDITS")
  else
    places=("$HOME/Applications/Compress Photos Helper.app" "/Applications/Compress Photos Helper.app")
  fi
  for c in "${places[@]}"; do
    if [ -n "$c" ] && [ -e "$c" ]; then helper=$c; break; fi
  done
  why=''
  if [ -z "$helper" ]; then
    why='Compress Photos Helper is not installed (see Installation in @HELP_URL@)'
  else
    mkdir -p "$E"
    for n in $ens; do
      mkdir -p "$E/$n"
      ln -s "$WORK/in/${origs[$n]}" "$E/$n/original"
      print -r -- "$n|${eid[$n]}" >> "$E/check.txt"
    done
    photoedits check
    case $? in
      1) why='Compress Photos Helper gave no answer';;
      2) why="Compress Photos Helper doesn't match this shortcut ($(head -1 "$E/check.out")): install both from the same release (see Updating in @HELP_URL@)";;
      *)
        if ! grep -qx 'access|3' "$E/check.out"; then
          why='Compress Photos Helper has no full access to Photos (System Settings > Privacy & Security > Photos)'
        else
          while IFS='|' read -r n verdict note || [ -n "$n" ]; do
            [[ $n == <-> ]] && [ -n "${eid[$n]}" ] || continue
            if [ "$verdict" = ok ]; then
              eok[$n]=1
              enote[$n]=$note
            else
              burnt[$n]=$note
            fi
          done < "$E/check.out"
        fi;;
    esac
  fi
  k=0
  for n in $ens; do
    if [ -z "${eok[$n]}" ]; then
      [ -n "${burnt[$n]}" ] || burnt[$n]=${why:-Compress Photos Helper gave no answer for it}
      /bin/rm -f "$WORK/jxl_in_$n.orig"
      mv "$WORK/renders/$n" "$WORK/jxl_in_$n.orig"
      continue
    fi
    # its look: its rendering, with the photo's date and location lines
    mkdir -p "$WORK/looks"
    k=$((k + 1))
    lookof[$n]=$k
    ln -s "$WORK/renders/$n" "$WORK/looks/jxl_in_$k.orig"
    printf '%d|%s\n' "$k" "${origs[$n]}" >> "$WORK/looks/jxl_job.txt"
    for f in jxl_dates.txt jxl_meta.txt; do
      [ -f "$WORK/$f" ] && grep "^$n|" "$WORK/$f" | sed "s/^$n|/$k|/" >> "$WORK/looks/$f"
    done
  done
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
# JPEG XL); then the helper saves each one's copy with its edit (ecreated: its
# id in Photos).
typeset -A ecreated basefile basename_ lookfile
if [ -f "$WORK/looks/jxl_job.txt" ]; then
  { echo; echo "The edited photos' looks, as Photos shows them (HEIC):"; } >> "$LOG"
  case $FORMAT in
    heic) lrf=$QUALITY;;
    *) lrf=26;;
  esac
  "$photobatch" --mac --heic --rf "$lrf" "${cores[@]}" "${hdr[@]}" -C "$WORK/looks" jxl_job.txt >> "$LOG" 2>&1
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
      late[$n]="its original or its look didn't convert (see above)"
    elif /bin/cp "$WORK/$b" "$E/$n/base.${b:e}" && /bin/cp "$WORK/looks/$l" "$E/$n/look.heic"; then
      print -r -- "$n|${basename_[$n]}" >> "$E/create.txt"
    else
      late[$n]="its files couldn't be copied for Compress Photos Helper"
    fi
  done
  if [ -s "$E/create.txt" ]; then
    photoedits create
    rc=$?
    if (( rc != 1 && rc != 2 )) && ! grep -qx 'access|3' "$E/create.out"; then
      for n in $ens; do
        [ -n "${lookof[$n]}" ] && [ -z "${late[$n]}" ] &&
          late[$n]='Compress Photos Helper has no full access to Photos (System Settings > Privacy & Security > Photos)'
      done
    elif (( rc != 1 && rc != 2 )); then
      while IFS='|' read -r n verdict id note || [ -n "$n" ]; do
        [[ $n == <-> ]] && [ -n "${eid[$n]}" ] || continue
        case $verdict in
          created) ecreated[$n]=$id
            note=${enote[$n]}${enote[$n]:+${note:+; }}$note
            [ -n "$note" ] && echo "! ${origs[$n]}: saved with its edit, but it may not come out right ($note): look at it in Photos" >> "$LOG";;
          unsure) ecreated[$n]=$id
            echo "! ${origs[$n]}: saved with its edit, but $note${enote[$n]:+ (also: ${enote[$n]})}: look at it in Photos" >> "$LOG";;
          failed) late[$n]="Photos didn't take the copy with its edit ($id)";;
        esac
      done < "$E/create.out"
    fi
    # the photos the helper gave no answer for: it may have saved them
    while IFS='|' read -r n rest || [ -n "$n" ]; do
      [[ $n == <-> ]] && [ -z "${ecreated[$n]}${late[$n]}" ] || continue
      late[$n]='Compress Photos Helper gave no answer when saving it (Photos may also have its copy with the edit)'
    done < "$E/create.txt"
  fi
  kept=()
  for n in $ens; do
    [ -n "${ecreated[$n]}" ] && kept+=("${origs[$n]}")
  done
  if (( ${#kept} )); then
    echo "${#kept} edited photo(s) are saved with their edits, which can be reverted in Photos: ${(j:, :)kept}" >> "$LOG"
  fi
fi
# the helper's copies of the photos (its answers stay, for a look)
for d in "$E"/<->(N/); do /bin/rm -r "$d"; done
# The edited photos Photos didn't take with their edits: their renderings,
# converted now (bakeof: job index -> the photo's)
typeset -A bakeof
if (( ${#late} )); then
  mkdir -p "$WORK/bake"
  j=0
  for n in $ens; do
    [ -n "${late[$n]}" ] || continue
    burnt[$n]=${late[$n]}
    j=$((j + 1))
    bakeof[$j]=$n
    ln -s "$WORK/renders/$n" "$WORK/bake/jxl_in_$j.orig"
    printf '%d|%s\n' "$j" "${origs[$n]}" >> "$WORK/bake/jxl_job.txt"
    for f in jxl_dates.txt jxl_meta.txt; do
      [ -f "$WORK/$f" ] && grep "^$n|" "$WORK/$f" | sed "s/^$n|/$j|/" >> "$WORK/bake/$f"
    done
  done
  { echo; echo "The edited photos that couldn't be saved with their edits, as Photos shows them ($FORMAT_NAME):"; } >> "$LOG"
  "$photobatch" --mac "${fmt[@]}" "${cores[@]}" "${hdr[@]}" -C "$WORK/bake" jxl_job.txt >> "$LOG" 2>&1
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
# Each result becomes <work>/out/Name.jxl (never replacing a file), and one
# output line per result, "path|original id|delete or keep|Name.jxl|keywords",
# for import.applescript; a copy the helper already saved in Photos is
# "id:<its id>|original id|...". Nothing when nothing was converted. The
# keywords are the copy's format and quality (KEYWORDS, common.zsh:
# "jxl,q=83", "heic,RF=26"), and "burnt-in" for an edited photo whose edit is
# burnt in, which import.applescript gives it in Photos only, with "compr"
# (never in the file).
mkdir -p "$WORK/out"
typeset -a results baked
# result FILE INDEX FLAG NAME [KEYWORD]: moves FILE into out/, and its line
# into results
result() {
  local dest
  dest=$(unique "$WORK/out/$4")
  mv "$1" "$dest" || return 1
  results+=("$dest|${ids[${origs[$2]}]}|$3|${dest:t}|$KEYWORDS${5:+,$5}")
}
if [ -f "$WORK/jxl_done.txt" ]; then
  while IFS='|' read -r file idx flag name || [ -n "$file" ]; do
    [ -n "$file" ] || continue
    [ -z "$name" ] && name=$flag  # a line from an older photobatch: file|index|name
    if [ -n "${ecreated[$idx]}" ]; then
      results+=("id:${ecreated[$idx]}|${ids[${origs[$idx]}]}|$flag|$name|$KEYWORDS")
    elif [ -n "${burnt[$idx]}" ] && [ -z "${late[$idx]}" ]; then
      result "$WORK/$file" "$idx" "$flag" "$name" burnt-in && baked+=($idx)
    elif [ -z "${eid[$idx]}" ]; then
      result "$WORK/$file" "$idx" "$flag" "$name"
    fi  # else an edited photo's original: its copy comes from the bake
  done < "$WORK/jxl_done.txt"
fi
if [ -f "$WORK/bake/jxl_done.txt" ]; then
  while IFS='|' read -r file j flag name || [ -n "$file" ]; do
    [ -n "$file" ] && [ -n "${bakeof[$j]}" ] || continue
    [ -z "$name" ] && name=$flag
    result "$WORK/bake/$file" "${bakeof[$j]}" "$flag" "$name" burnt-in && baked+=(${bakeof[$j]})
  done < "$WORK/bake/jxl_done.txt"
fi
# The photos whose edits are burnt in, by reason: last before Photos' work,
# so that the log's end shows them.
if (( ${#baked} )); then
  typeset -A byreason
  typeset -a reasons
  for n in $baked; do
    r=${burnt[$n]}
    (( ${+byreason[$r]} )) || reasons+=("$r")
    byreason[$r]+="${byreason[$r]:+, }${origs[$n]}"
  done
  {
    echo
    echo "! ${#baked} edited photo(s) are saved with their edits burnt in: each copy looks as Photos shows the photo, but its edit can't be reverted. They have the keyword \"burnt-in\" in Photos."
    for r in "${reasons[@]}"; do echo "!   $r: ${byreason[$r]}"; done
  } >> "$LOG"
fi
# What follows is Photos' work (import.applescript), which the progress window
# would otherwise show nothing of.
if (( ${#results} )); then
  { echo; echo "Now Photos imports the files, adds them to their albums and collects the originals..."; } >> "$LOG"
  print -rl -- "${results[@]}"
fi
