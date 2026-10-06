# The items selected in Photos: Photos exported their original files into
# $WORK/in (see export.applescript), and IDS has one "id|filename" line per
# selected item (or "ERROR: ..."). Only videos are converted. Photos are
# skipped, and so are Live Photos (a photo whose .mov of the same name is not
# an item of its own), videos whose picture this ffmpeg can't decode, and the
# videos a copy would lose something of: slo-mo, spatial video, log
# recordings (Apple Log), sound this ffmpeg can't read, Dolby Vision it can't
# carry.
# Everything skipped is counted (vid_skipped.txt, for the notification) and
# named in the log, before any video is converted.
setopt nullglob
rm -f "$WORK"/vid_*  # a previous run's work files, if any
case $IDS in
  ERROR*) echo "$IDS" >> "$LOG";;
esac
# filename -> id. A name two selected items share can't be told apart in the
# export, so it gets no id: its copy is saved but joins no album, and neither
# original is collected for deletion.
typeset -A ids seen
for line in "${(@f)IDS}"; do
  case $line in *'|'*) ;; *) continue;; esac
  name=${line#*|}
  if (( ${+seen[$name]} )); then
    if [ -n "${ids[$name]}" ]; then
      echo "! two or more selected items are named $name: their copies are saved, but not added to albums, and the originals are not collected" >> "$LOG"
    fi
    ids[$name]=''
  else
    ids[$name]=${line%%|*}
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
typeset -A J  # the videos to convert: J[N,key]
njobs=0 unreadable=0 photos=0 live=0 novideo=0 slomo=0 spatial=0 logvideos=0 noaudio=0 dolby=0 others=0 total_in=0
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
  # The sound: the first track with at most 2 channels this ffmpeg can read
  # (iPhones: the stereo AAC, before the 4-channel spatial audio, Apple's
  # APAC, which ffmpeg can't read); else the first readable one, mixed down
  # to stereo. A video with sound but none readable is skipped.
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
  if (( $#p_audio )) && [ -z "$a_pick" ]; then
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
  njobs=$((njobs + 1))
  size=$(stat -f %z "$f")
  total_in=$((total_in + size))
  J[$njobs,file]=$f J[$njobs,name]=$name J[$njobs,size]=$size
  J[$njobs,w]=$p_w J[$njobs,h]=$p_h J[$njobs,pix]=$p_pix J[$njobs,transfer]=$p_transfer
  J[$njobs,avg]=$avg J[$njobs,rate]=$p_avg J[$njobs,frames]=$p_frames J[$njobs,duration]=$p_duration
  J[$njobs,audio]=$a_pick J[$njobs,ac2]=$a_ac2 J[$njobs,dv]=$dv J[$njobs,videos]=$p_videos
  [ -n "$dv" ] && [ "$DOLBY" = 1 ] && J[$njobs,carry]=1
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
@RUN@
# What follows is Photos' work (import.applescript), which the progress window
# would otherwise show nothing of.
[ -f "$WORK/vid_done.txt" ] && { echo; echo "Now Photos imports the videos, adds them to their albums and collects the originals..."; } >> "$LOG"
# Each result becomes <work>/out/Name.mp4 (never replacing a file), and one
# output line per result, "path|original id|delete|Name.mp4", for
# import.applescript. Nothing when nothing was converted.
mkdir -p "$WORK/out"
if [ -f "$WORK/vid_done.txt" ]; then
  while IFS='|' read -r file idx flag name || [ -n "$file" ]; do
    [ -n "$file" ] || continue
    dest=$(unique "$WORK/out/$name")
    mv "$WORK/$file" "$dest" || continue
    printf '%s|%s|%s|%s\n' "$dest" "${ids[${J[$idx,name]}]-}" "$flag" "${dest:t}"
  done < "$WORK/vid_done.txt"
fi
