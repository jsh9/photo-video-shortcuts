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
typeset -a origs edited unchecked
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
          # Edited: a copy of the rendering. photobatch can't read it where
          # Shortcuts keeps it (its group container, which macOS guards as
          # another app's data, kTCCServiceSystemPolicyAppDataDetailed, and a
          # background run can't ask for: "Operation not permitted"); Apple's
          # cp and cmp can (macOS 27), so by their paths, not another on PATH.
          if /bin/cp "$r" "$WORK/jxl_in_$n.orig" 2>/dev/null; then
            src=''
            edited+=("$name")
          else
            rm -f "$WORK/jxl_in_$n.orig"
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
# The edited photos (no "!": it is what Photos shows), and those that couldn't
# be checked: each, or, when no rendering came at all, the reason in one line.
if (( ${#edited} )); then
  echo "${#edited} edited photo(s) are converted as they look in Photos now (the edit can't be reverted on the copy): ${(j:, :)edited}" >> "$LOG"
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
    dest=$(unique "$WORK/out/$name")
    mv "$WORK/$file" "$dest" || continue
    printf '%s|%s|%s|%s|%s\n' "$dest" "${ids[${origs[$idx]}]}" "$flag" "${dest:t}" "$KEYWORDS"
  done < "$WORK/jxl_done.txt"
fi
