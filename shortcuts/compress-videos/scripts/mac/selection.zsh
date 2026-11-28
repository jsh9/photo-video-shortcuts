# The items selected in Photos: Photos exported their original files into
# $WORK/in (see export.applescript), and IDS has one "id|date|filename" line
# (the date unused here; older exporters gave "id|filename"; the name may
# have "|" itself) per selected item (or "ERROR: ..."). Only videos are
# converted. Photos are
# skipped, and so are Live Photos (a photo whose .mov of the same name is not
# an item of its own), videos whose picture this ffmpeg can't decode, and the
# videos a copy would lose something of: slo-mo, spatial video, log
# recordings (Apple Log), sound this ffmpeg can't read, Dolby Vision it can't
# carry.
# Everything skipped is counted (vid_skipped.txt, for the notification) and
# named in the log, before any video is converted.
#
# Edited videos (EDITS=1): the first run of this script (PHASE=plan) prints
# the "id|date|filename" line of each video it would convert, and exits;
# bridge.applescript puts those videos into the album "@BRIDGE_ALBUM@", and
# Shortcuts' Find Photos gets them as library items, whose files are Photos'
# current version of each: an edited video's rendering, an unedited one's
# original byte for byte. The second run (PHASE=convert) gets those files as
# its arguments, BRIDGE (the album script's answer, "BRIDGE n" or "ERROR:
# ..."), RDATES (their dates in Photos, "position|2024-01-01T17:00:00-05:00")
# and CLOSED (the album's deletion, "CLOSED"). A file is a video's when the
# names without extension are the same (case aside) and the dates, if both
# have one, at most a second apart, and neither has another match. A video
# whose file is the same bytes is unedited, and its original is converted; one
# whose file differs is edited, and Photos' version is converted instead, the
# edit burnt in, with the keyword "burnt-in" (its original still gives the
# copy its metadata, vidmeta copy). What a video is (slo-mo, spatial, a log
# recording) is decided by its original. Any other video is converted from
# its original, with a "!" line.
setopt nullglob
zmodload zsh/datetime
rm -f "$WORK"/vid_*  # a previous run's work files, if any
case $IDS in
  ERROR*) echo "$IDS" >> "$LOG";;
esac
# filename -> id. A name two selected items share can't be told apart in the
# export, so it gets no id: its copy is saved but joins no album, and neither
# original is collected for deletion. The exporter's "id<tab>field<tab>value"
# lines (what else Photos has for an item, for Compress Photos) have no "|":
# skipped.
typeset -A ids seen dates line_of
for line in "${(@f)IDS}"; do
  case $line in *'|'*) ;; *) continue;; esac
  # the name: what follows the date's "|", "|" and all (an older exporter's
  # line has no date: what follows the id's)
  rest=${line#*|}
  case $rest in *'|'*) name=${rest#*|} date=${rest%%|*};; *) name=$rest date='';; esac
  if (( ${+seen[$name]} )); then
    if [ -n "${ids[$name]}" ]; then
      echo "! two or more selected items are named $name: their copies are saved, but not added to albums, and the originals are not collected" >> "$LOG"
    fi
    ids[$name]=''
    dates[$name]=''
  else
    ids[$name]=${line%%|*}
    dates[$name]=$date
    line_of[$name]=$line
  fi
  seen[$name]=1
done
is_video() { case ${1:e:l} in mov|mp4|m4v) return 0;; esac; return 1; }
is_photo() {
  case ${1:e:l} in
    heic|heif|hif|jpg|jpeg|png|dng|tif|tiff|gif|webp|avif|jxl|cr2|cr3|nef|arw|orf|raf|rw2) return 0;;
  esac
  return 1
}
# pair FILE KIND: the file of KIND (photo or video) with FILE's name stem, if
# there is one (a Live Photo is exported as a photo and a .mov)
pair() {
  local g
  for g in "$WORK/in/${1:t:r}".*(.N); do
    [ "$g" = "$1" ] && continue
    is_$2 "${g:t}" && print -r -- "$g" && return 0
  done
  return 1
}
# rate N/D: a frame rate as a number
rate() {
  if [[ $1 == <->/<-> ]] && (( ${1#*/} > 0 )); then
    print -r -- $(( ${1%/*} / ${1#*/}.0 ))
  else
    print 0
  fi
}
# probe FILE: what ffprobe reads of the file into p_*: its first video track
# (p_vcodec: its codec),
# the number of video tracks, its audio tracks ("index:codec:channels") and
# its duration. Fails if ffprobe can't read the file.
probe() {
  local out line field key value sd
  local -A s
  p_videos=0 p_audio=() p_duration='' p_vcodec='' p_w='' p_h='' p_pix='' p_transfer='' p_avg='' p_r='' p_frames='' p_sd='' p_profile=''
  out=$("$ffprobe" -v error -show_entries "format=duration:stream=index,codec_type,codec_name,profile,width,height,pix_fmt,color_transfer,avg_frame_rate,r_frame_rate,nb_frames,duration,channels:stream_side_data=side_data_type" -of compact=p=0 "$1" 2>/dev/null) || return 1
  for line in "${(@f)out}"; do
    s=()
    sd=''
    for field in "${(@s:|:)line}"; do
      key=${field%%=*}
      value=${field#*=}
      case $key in
        *side_data_type) sd+="$value;";;
        *) s[$key]=$value;;
      esac
    done
    case ${s[codec_type]-} in
      video)
        p_videos=$((p_videos + 1))
        if (( p_videos == 1 )); then
          p_vcodec=${s[codec_name]-} p_w=${s[width]-} p_h=${s[height]-} p_pix=${s[pix_fmt]-} p_profile=${s[profile]-}
          p_transfer=${s[color_transfer]-} p_avg=${s[avg_frame_rate]-} p_r=${s[r_frame_rate]-}
          p_frames=${s[nb_frames]-} p_sd=$sd
          [[ ${s[duration]-} == [0-9.]## ]] && p_duration=${s[duration]}
        fi;;
      audio) p_audio+=("${s[index]-}:${s[codec_name]-}:${s[channels]-}");;
      '') [ -z "$p_duration" ] && [[ ${s[duration]-} == [0-9.]## ]] && p_duration=${s[duration]};;
    esac
  done
  return 0
}
# sound: the track of p_audio to convert, into a_pick: the first with at most
# 2 channels this ffmpeg can read (iPhones: the stereo AAC, before the
# 4-channel spatial audio, Apple's APAC, which ffmpeg can't read); else the
# first readable one, mixed down to stereo (a_ac2=1). Fails for a video with
# sound but none readable.
sound() {
  local a parts
  a_pick='' a_ac2=''
  for a in $p_audio; do
    parts=("${(@s.:.)a}")
    (( ${+decodable[${parts[2]}]} )) || continue
    if [[ ${parts[3]} == <-> ]] && (( ${parts[3]} <= 2 )); then
      a_pick=${parts[1]} a_ac2=''
      break
    fi
    [ -z "$a_pick" ] && a_pick=${parts[1]} a_ac2=1
  done
  ! (( $#p_audio )) || [ -n "$a_pick" ]
}
# kind_text WIDTH HEIGHT FPS TRANSFER PIX_FMT DV: "1920×1080 30 fps HLG
# 10-bit Dolby Vision", for the log
kind_text() {
  local fps k
  fps=$(printf '%.3f' $3)
  fps=${${fps%%0#}%.}
  k="${1}×${2} $fps fps"
  case $4 in
    arib-std-b67) k+=" HLG";;
    smpte2084) k+=" PQ";;
  esac
  [[ $5 =~ 'p(10|12)' ]] && k+=" ${match[1]}-bit"
  [ -n "$6" ] && k+=" Dolby Vision"
  print -r -- "$k"
}
# Photos' version of each video, in the conversion (see above)
BRIDGE=$(cat <<'VID_BRIDGE'
@BRIDGE@
VID_BRIDGE
)
RDATES=$(cat <<'VID_RDATES'
@DATES@
VID_RDATES
)
CLOSED=$(cat <<'VID_CLOSED'
@CLOSED@
VID_CLOSED
)
renderings=("$@")
# clock TIME: the seconds of "2024-01-01 17:00:00" on the Mac's clock, or
# nothing
clock() { [ -n "$1" ] && strftime -r '%Y-%m-%d %H:%M:%S' "$1" 2>/dev/null; }
typeset -A rwhen bystem claims
for line in "${(@f)RDATES}"; do
  [[ $line == <->'|'* ]] || continue
  d=${line#*|}
  rwhen[${line%%|*}]=$(clock "${d[1,10]} ${d[12,19]}")
done
# The files' positions by name without extension, lowercased (the key has an
# "x" in front: a name may be only an extension)
for (( k = 1; k <= ${#renderings}; k++ )); do
  bystem[x${${renderings[k]:t}:r:l}]+=" $k"
done
# candidates NAME: the positions of the files that may be the video NAME's, in
# $reply
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
# how many of the selected videos each file may be
for f in "$WORK"/in/*(.N); do
  is_video "${f:t}" && (( ${+seen[${f:t}]} )) || continue
  candidates "${f:t}"
  for k in $reply; do claims[$k]=$(( ${claims[$k]:-0} + 1 )); done
done
typeset -a unchecked burnt
typeset -A J  # the videos to convert: J[N,key]
njobs=0 unreadable=0 photos=0 live=0 novideo=0 slomo=0 spatial=0 logvideos=0 noaudio=0 dolby=0 editskip=0 others=0 total_in=0
for f in "$WORK"/in/*(.N); do
  name=${f:t}
  if is_video "$name"; then
    # a Live Photo's video: not an item of its own, next to its photo
    if ! (( ${+seen[$name]} )) && pair "$f" photo > /dev/null; then continue; fi
  elif is_photo "$name"; then
    if v=$(pair "$f" video) && ! (( ${+seen[${v:t}]} )); then
      live=$((live + 1))
      echo "Skipped $name: a Live Photo" >> "$LOG"
    else
      photos=$((photos + 1))
      echo "Skipped $name: a photo" >> "$LOG"
    fi
    continue
  else
    others=$((others + 1))
    echo "Skipped $name: not a video" >> "$LOG"
    continue
  fi
  if ! probe "$f" || (( p_videos == 0 )); then
    unreadable=$((unreadable + 1))
    echo "! $name: not a video ffprobe can read (unsupported format)" >> "$LOG"
    continue
  fi
  # A picture this ffmpeg can't decode (Apple ProRes, say, which our build
  # leaves out): skipped, rather than failing in ffmpeg.
  if [ -z "$p_vcodec" ] || ! (( ${+decodable[$p_vcodec]} )); then
    novideo=$((novideo + 1))
    echo "Skipped $name: this ffmpeg can't decode its video (${p_vcodec:-unknown codec})" >> "$LOG"
    continue
  fi
  avg=$(rate "$p_avg")
  # Slo-mo: Photos exports the recording at its capture rate (240 fps
  # averages 177 on an iPhone 17 Pro); the slow part is an edit, so a copy
  # would play at normal speed throughout. Recent iPhones say which a fast
  # video is, in its key full-frame-rate-playback-intent: 0 for slo-mo, 1
  # for a video that plays at its full rate (4K at 120 fps, say), which is
  # converted. vidmeta reads the key (ffprobe reads its 8-byte integer as 0).
  # A video without it (an older iPhone's, another camera's) is taken for
  # slo-mo above 61 fps on average. The average, not ffprobe's r_frame_rate,
  # which a variable-rate video can put far above its real rate (150 for a
  # Live Photo's video that averages 28). SLOMO=0: none is skipped.
  if [ "$SLOMO" = 1 ] && (( avg > 61 )); then
    intent=$("$vidmeta" key "$f" com.apple.quicktime.full-frame-rate-playback-intent 2>/dev/null)
    if [ "$intent" != 1 ]; then
      slomo=$((slomo + 1))
      if [ "$intent" = 0 ]; then
        echo "Skipped $name: slo-mo ($(printf '%.0f' $avg) fps on average); a copy would play at normal speed" >> "$LOG"
      else
        echo "Skipped $name: perhaps slo-mo ($(printf '%.0f' $avg) fps on average, and the file doesn't say); SLOMO=0 converts such videos" >> "$LOG"
      fi
      continue
    fi
  fi
  # Spatial video (MV-HEVC, two views): ffmpeg would keep one view.
  if [[ $p_sd == *(Stereo 3D|Stereoscopic)* || $p_profile == *Multiview* ]]; then
    spatial=$((spatial + 1))
    echo "Skipped $name: spatial video; a copy would keep one view only" >> "$LOG"
    continue
  fi
  # A log recording (Apple Log: iPhone 15 Pro and later, in ProRes) is a flat
  # picture meant to be graded with a LUT; a copy would look washed out. The
  # video's sample description names its log curve (a `logs` box, which
  # vidmeta reads; ffprobe shows only an unknown transfer). A ProRes video
  # with no known transfer is taken for one too, in case a recording lacks
  # the box.
  curve=$("$vidmeta" log "$f" 2>/dev/null)
  if [ -n "$curve" ] || { [ "$p_vcodec" = prores ] && [[ $p_transfer == (|unknown|reserved) ]]; }; then
    logvideos=$((logvideos + 1))
    case $curve in
      *apple-log) what="Apple Log";;
      '') what="perhaps a log recording (ProRes with no known color transfer)";;
      *) what="a log recording ($curve)";;
    esac
    echo "Skipped $name: $what, which needs a LUT; a copy would look flat" >> "$LOG"
    continue
  fi
  # The sound (see sound). A video with sound but none readable is skipped.
  if ! sound; then
    noaudio=$((noaudio + 1))
    echo "Skipped $name: this ffmpeg can't read its sound; a copy would be silent" >> "$LOG"
    continue
  fi
  dv=''
  [[ $p_sd == *'DOVI configuration record'* ]] && dv=1
  if [ -n "$dv" ] && [ "$DOLBY" = 1 ] && [ -z "$dovi_ok" ]; then
    dolby=$((dolby + 1))
    echo "Skipped $name: Dolby Vision, which this ffmpeg can't carry" >> "$LOG"
    continue
  fi
  # Edited in Photos? (the conversion only; see above)
  file=$f edited=''
  if [ "$PHASE" = convert ] && [ "$EDITS" = 1 ]; then
    candidates "$name"
    if [ -n "${ids[$name]}" ] && (( ${#reply} == 1 )) && (( ${claims[${reply[1]}]:-0} == 1 )) && [ -r "${renderings[${reply[1]}]}" ]; then
      r=${renderings[${reply[1]}]}
      /usr/bin/cmp -s "$r" "$f" 2>/dev/null
      case $? in
        0) ;;  # unedited: its original
        1) edited=$r;;
        *) unchecked+=("$name");;  # unreadable
      esac
    else
      unchecked+=("$name")
    fi
  fi
  if [ -n "$edited" ]; then
    # Photos' version, copied into the work folder: ffprobe and ffmpeg can't
    # read it where Shortcuts keeps it (its group container, which macOS
    # guards as another app's data); Apple's cp can. A plain copy, as Compress
    # Photos makes: ffprobe couldn't read a clone (cp -c) of an edited video's
    # file (macOS 27), which may keep the container's guard. It is converted
    # as it is, with its own size, length, sound and HDR; the original keeps
    # telling what the video is (above) and its metadata.
    okind=$(kind_text "$p_w" "$p_h" "$avg" "$p_transfer" "$p_pix" "$dv")
    osize=$(stat -f %z "$f") otransfer=$p_transfer opix=$p_pix odv=$dv oaudio=$#p_audio
    file="$WORK/vid_in_$((njobs + 1)).${edited:e:l}"
    why=''
    if ! /bin/cp "$edited" "$file" 2>/dev/null; then
      why="Photos' version of it can't be read"
    elif ! probe "$file" || (( p_videos == 0 )); then
      # what ffprobe says, and what the file is, for the log
      said=$("$ffprobe" -v error -show_entries format=format_name "$file" 2>&1 | head -2)
      why="ffprobe can't read Photos' version of it (${edited:t}, $(size_text $(stat -f %z "$file" 2>/dev/null || print 0))${said:+: ${said//$'\n'/; }})"
    elif [ -z "$p_vcodec" ] || ! (( ${+decodable[$p_vcodec]} )); then
      why="this ffmpeg can't decode Photos' version of it (${p_vcodec:-unknown codec})"
    elif ! sound; then
      why="this ffmpeg can't read the sound of Photos' version of it"
    else
      avg=$(rate "$p_avg")
      dv=''
      [[ $p_sd == *'DOVI configuration record'* ]] && dv=1
      [ -n "$dv" ] && [ "$DOLBY" = 1 ] && [ -z "$dovi_ok" ] &&
        why="Photos' version of it has Dolby Vision, which this ffmpeg can't carry"
    fi
    if [ -n "$why" ]; then
      editskip=$((editskip + 1))
      rm -f "$file"
      echo "Skipped $name: edited in Photos, and $why" >> "$LOG"
      continue
    fi
  fi
  njobs=$((njobs + 1))
  size=$(stat -f %z "$file")
  total_in=$((total_in + size))
  J[$njobs,file]=$file J[$njobs,orig]=$f J[$njobs,name]=$name J[$njobs,size]=$size
  J[$njobs,w]=$p_w J[$njobs,h]=$p_h J[$njobs,pix]=$p_pix J[$njobs,transfer]=$p_transfer
  J[$njobs,avg]=$avg J[$njobs,rate]=$p_avg J[$njobs,frames]=$p_frames J[$njobs,duration]=$p_duration
  J[$njobs,audio]=$a_pick J[$njobs,ac2]=$a_ac2 J[$njobs,dv]=$dv J[$njobs,videos]=$p_videos
  [ -n "$dv" ] && [ "$DOLBY" = 1 ] && J[$njobs,carry]=1
  if [ -n "$edited" ]; then
    J[$njobs,edited]=1 J[$njobs,okind]=$okind J[$njobs,osize]=$osize
    J[$njobs,otransfer]=$otransfer J[$njobs,opix]=$opix J[$njobs,odv]=$odv J[$njobs,oaudio]=$oaudio
  fi
done
skipped=()
(( photos )) && skipped+=("$photos photo(s)")
(( live )) && skipped+=("$live Live Photo(s)")
(( novideo )) && skipped+=("$novideo video(s) this ffmpeg can't decode")
(( slomo )) && skipped+=("$slomo slo-mo video(s)")
(( spatial )) && skipped+=("$spatial spatial video(s)")
(( logvideos )) && skipped+=("$logvideos Apple Log video(s)")
(( noaudio )) && skipped+=("$noaudio video(s) whose sound can't be read")
(( dolby )) && skipped+=("$dolby Dolby Vision video(s)")
(( editskip )) && skipped+=("$editskip edited video(s) whose Photos version can't be converted")
(( others )) && skipped+=("$others other file(s)")
if (( $#skipped )); then
  print -r -- "Skipped ${(j:, :)skipped}." > "$WORK/vid_skipped.txt"
  cat "$WORK/vid_skipped.txt" >> "$LOG"
fi
# The copies need room next to the originals Photos exported.
if (( njobs )); then
  free=$(( $(df -k "$WORK" | awk 'NR == 2 { print $4 }') * 1024 ))
  if (( free < total_in * 12 / 10 )); then
    echo "ERROR: not enough free space to convert $(size_text $total_in) of videos: $(size_text $(( total_in * 12 / 10 ))) needed, $(size_text $free) free. Free some space or select fewer videos." >> "$LOG"
    njobs=0
    space_error=1
  fi
fi
# The planning pass ends here: the videos to convert, for the album (none
# with EDITS=0, or without an id).
if [ "$PHASE" = plan ]; then
  if [ "$EDITS" = 1 ]; then
    for (( n = 1; n <= njobs; n++ )); do
      name=${J[$n,name]}
      [ -n "${ids[$name]}" ] && print -r -- "${line_of[$name]}"
    done
  fi
  exit 0
fi
@PLAN_END@
# The videos checked for edits, and those that couldn't be: each, or, when no
# file came at all, the reason in one line.
if [ "$EDITS" != 1 ]; then
  echo "Edits made in Photos are not looked for (EDITS=0): every video is converted from its original recording." >> "$LOG"
elif (( ${#unchecked} && ${#renderings} )); then
  echo "! could not check ${#unchecked} video(s) for edits: converted from the original file(s), without edits made in Photos. Play the copies before deleting the originals: ${(j:, :)unchecked}" >> "$LOG"
elif (( ${#unchecked} )); then
  case $BRIDGE in
    ERROR*) why=$BRIDGE;;
    'BRIDGE '[1-9]*) why='Shortcuts found no videos in the album @BRIDGE_ALBUM@';;
    'BRIDGE 0') why='Photos put none of them into the album @BRIDGE_ALBUM@';;
    *) why='the album script gave no answer';;
  esac
  echo "! could not check the videos for edits ($why): edited videos are converted from their original files, without the edits. Play the copies before deleting the originals." >> "$LOG"
fi
if [ "$EDITS" = 1 ] && [ "$CLOSED" != CLOSED ]; then
  echo "! could not delete the album @BRIDGE_ALBUM@ (${CLOSED:-the album script gave no answer}): Photos may add the copies to it too. Delete that album in Photos (its videos stay in the library)." >> "$LOG"
fi
@RUN@
# Each result becomes <work>/out/Name.mp4 (never replacing a file), and one
# output line per result, "path|original id|delete|Name.mp4|keywords", for
# import.applescript; a "|" in the original's name is "_" in the copy's
# (encode.zsh), so the line splits on "|". The keywords: "burnt-in" for an
# edited video's copy (with "compr", in Photos only), none otherwise.
# Nothing when nothing was converted.
mkdir -p "$WORK/out"
typeset -a results
if [ -f "$WORK/vid_done.txt" ]; then
  while IFS='|' read -r file idx flag name || [ -n "$file" ]; do
    [ -n "$file" ] || continue
    dest=$(unique "$WORK/out/$name")
    mv "$WORK/$file" "$dest" || continue
    if [ -n "${J[$idx,edited]-}" ]; then
      results+=("$dest|${ids[${J[$idx,name]}]-}|$flag|${dest:t}|burnt-in")
      burnt+=("${J[$idx,name]}")
    else
      results+=("$dest|${ids[${J[$idx,name]}]-}|$flag|${dest:t}")
    fi
  done < "$WORK/vid_done.txt"
fi
# The videos whose edits are burnt in: last before Photos' work, so that the
# log's end shows them (and the log opens).
if (( ${#burnt} )); then
  { echo; echo "! ${#burnt} edited video(s) are converted as they look in Photos, their edits burnt in: each copy plays as Photos shows the video (trimmed, cropped, rotated, filtered), but its edit can't be reverted. They have the keyword \"burnt-in\" in Photos: ${(j:, :)burnt}"; } >> "$LOG"
fi
# What follows is Photos' work (import.applescript), which the progress window
# would otherwise show nothing of.
if (( ${#results} )); then
  { echo; echo "Now Photos imports the videos, adds them to their albums and collects the originals..."; } >> "$LOG"
  print -rl -- "${results[@]}"
fi
