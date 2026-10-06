# One video at a time, with the encoder on every core; ffmpeg runs niced so
# the Mac stays responsive. Decoding and encoding are done in software, on the
# CPU (-hwaccel none, x265, SVT-AV1), never by the Mac's media engines. Each
# video is checked (codec, pixel format, duration) and gets the original's
# metadata (vidmeta) before it counts.
export SVT_LOG=2  # SVT-AV1: warnings only (its own info lines are long)
# scaled WIDTH HEIGHT: the copy's size as the scale filter makes it (the
# frame fitted in a LIMIT x LIMIT box, so the long edge is at most LIMIT
# whatever the orientation; never enlarged; even sizes), with libavfilter's
# arithmetic (ff_scale_adjust_dimensions: the aspect ratio rounded to the
# nearest even size, then rounded down to an even one)
scaled() {
  local w=$1 h=$2 sw sh tw th
  sw=$(( w < LIMIT ? w : LIMIT )) sh=$(( h < LIMIT ? h : LIMIT ))
  tw=$(( (sh * w + h) / (2 * h) * 2 )) th=$(( (sw * h + w) / (2 * w) * 2 ))
  (( tw < sw )) && sw=$tw
  (( th < sh )) && sh=$th
  print $(( sw / 2 * 2 )) $(( sh / 2 * 2 ))
}
# dovi_rate WIDTH PIXELS-PER-SECOND: the VBV rate (kbit/s) HandBrake gives
# x265 for Dolby Vision (libhb/dovi_common.c, hb_dovi_levels): the high-tier
# rate of the first Dolby Vision level the size fits, since x265 allows the
# high tier by default.
dovi_rate() {
  local level
  for level in 22118400:1280:50 27648000:1280:50 49766400:1920:70 \
      62208000:2560:70 124416000:3840:70 199065600:3840:130 248832000:3840:130 \
      398131200:3840:130 497664000:3840:130 995328000:3840:240 \
      995328000:7680:240 1990656000:7680:480 3981312000:7680:800; do
    local parts=("${(@s.:.)level}")
    if (( $2 <= parts[1] && $1 <= parts[2] )); then
      print $(( parts[3] * 1000 ))
      return
    fi
  done
  print 800000
}
# progress_lines FRAMES FPS: ffmpeg's -progress output (key=value lines,
# about once a second) -> a log line every PROGRESS_EVERY seconds. The share
# done, the speed and the time left come from the frames encoded: ffmpeg's own
# time and speed follow the sound, which runs ahead of a video encoder that
# buffers frames.
progress_lines() {
  local key value frame=0 fps=0 started=$SECONDS last=$SECONDS line elapsed total=$1
  while IFS='=' read -r key value; do
    case $key in
      frame) frame=$value;;
      fps) fps=$value;;
      progress)
        [ "$value" = continue ] || continue
        (( SECONDS - last >= PROGRESS_EVERY )) || continue
        last=$SECONDS
        [[ $frame == <-> ]] || frame=0
        [[ $fps == [0-9.]## ]] || fps=0
        (( elapsed = SECONDS - started ))
        line=$(printf '  %3.0f%%  frame %d/%d  %.0f fps' $(( 100.0 * frame / total )) $frame $total $fps)
        if (( frame > 0 && elapsed > 0 && $2 > 0 )); then
          line+="  $(printf '%.1f' $(( frame / $2 / elapsed )))×"
          line+="  ETA $(duration_text $(( (total - frame) * elapsed / (frame * 1.0) )))"
        fi
        print -r -- "$line";;
    esac
  done
}
# shown COMMAND...: the command as the log shows it, as one could type it in
# the work folder: ffmpeg by its name (its path is at the top of the log), the
# files relative to the work folder, and the arguments that need it quoted.
shown() {
  local arg line="  "
  for arg; do
    case $arg in
      "$ffmpeg") arg=ffmpeg;;
      "$WORK"/*) arg=${arg#$WORK/};;
    esac
    [[ $arg == *[[:space:]\'\"\$\(\)\|\;\&\*\?\<\>\[\]]* ]] && arg=${(qqq)arg}
    line+="$arg "
  done
  print -r -- "${line% }"
}
# fail MESSAGE: the current video failed; its copy goes
fail() {
  echo "  ! $1" >> "$LOG"
  rm -f "$out"
  failed=$((failed + 1))
}
converted=0 bytes_in=0 bytes_out=0
failed=$unreadable  # the videos ffprobe couldn't read count as failed
if (( njobs )); then
@PROGRESS@
  t0=$SECONDS
  for n in {1..$njobs}; do
    in=${J[$n,file]} name=${J[$n,name]} out="$WORK/vid_out_$n.mp4"
    w=${J[$n,w]} h=${J[$n,h]} dur=${J[$n,duration]:-0} pix=${J[$n,pix]}
    fps=$(printf '%.3f' ${J[$n,avg]})
    fps=${${fps%%0#}%.}
    kind="${w}×${h} $fps fps"
    case ${J[$n,transfer]} in
      arib-std-b67) kind+=" HLG";;
      smpte2084) kind+=" PQ";;
    esac
    [[ $pix =~ 'p(10|12)' ]] && kind+=" ${match[1]}-bit"
    [ -n "${J[$n,dv]}" ] && kind+=" Dolby Vision"
    target="$CODEC_TEXT $PRESET${TUNE:+ tune $TUNE} RF $RF"
    if [ -n "${J[$n,audio]}" ]; then
      target+=", Opus $AUDIO kbps"
      [ -n "${J[$n,ac2]}" ] && target+=" (stereo)"
    else
      target+=", no sound"
    fi
    [ -n "${J[$n,carry]}" ] && target+=", Dolby Vision kept"
    { echo; echo "[$n/$njobs] $name  $kind, $(size_text ${J[$n,size]}) → $target"; } >> "$LOG"
    (( ${J[$n,videos]} > 1 )) && echo "  (it has ${J[$n,videos]} video tracks; the first is converted)" >> "$LOG"
    # The command: HandBrake's settings as ffmpeg options (see DEVELOPING.md).
    cmd=(nice -n "$NICE" "$ffmpeg" -hide_banner -nostdin -v warning -nostats -progress pipe:1 -y
      -hwaccel none -noautorotate -i "$in" -map 0:v:0)
    [ -n "${J[$n,audio]}" ] && cmd+=(-map "0:${J[$n,audio]}")
    cmd+=(-map_metadata -1 -fps_mode passthrough
      -vf "scale=w='min(iw,$LIMIT)':h='min(ih,$LIMIT)':force_original_aspect_ratio=decrease:force_divisible_by=2")
    if [ "$CODEC" = h265 ]; then
      fr=$(printf '%.0f' ${J[$n,avg]})
      (( fr < 1 )) && fr=1
      cmd+=(-c:v libx265 -preset "$PRESET" -crf "$RF")
      [ "$TUNE" = grain ] && cmd+=(-tune grain)
      cmd+=(-profile:v main10 -pix_fmt yuv420p10le)
      params="keyint=$((10 * fr)):min-keyint=$fr"
      if [ -n "${J[$n,carry]}" ]; then
        # Dolby Vision needs x265's VBV (its HRD), from the copy's size and
        # its pixels per second with the whole frames per second, as
        # HandBrake counts them
        dims=($(scaled $w $h))
        ow=${dims[1]} oh=${dims[2]}
        fpsi=${J[$n,rate]%/*}
        (( fpsi = ${J[$n,rate]#*/} > 0 ? fpsi / ${J[$n,rate]#*/} : fr ))
        vbv=$(dovi_rate $ow $(( ow * oh * fpsi )))
        params+=":vbv-bufsize=$vbv:vbv-maxrate=$vbv"
      fi
      cmd+=(-x265-params "$params")
      [ -n "${J[$n,carry]}" ] && cmd+=(-dolbyvision 1 -strict unofficial)
      cmd+=(-tag:v hvc1)
    else
      cmd+=(-c:v libsvtav1 -preset "$PRESET" -crf "$RF" -pix_fmt yuv420p10le
        -svtav1-params tune=0:enable-variance-boost=1:film-grain=8)
      [ -n "${J[$n,carry]}" ] && cmd+=(-dolbyvision 1 -strict unofficial)
    fi
    if [ -n "${J[$n,audio]}" ]; then
      cmd+=(-c:a libopus -b:a "${AUDIO}k")
      [ -n "${J[$n,ac2]}" ] && cmd+=(-ac 2)
    else
      cmd+=(-an)
    fi
    cmd+=("$out")
    shown "${cmd[@]}" >> "$LOG"
    started=$SECONDS
    # the frame count: the track's, else from the duration
    frames=${J[$n,frames]}
    [[ $frames == <1-> ]] || frames=$(printf '%.0f' $(( dur * ${J[$n,avg]} )))
    (( frames > 0 )) || frames=1
    "${cmd[@]}" 2> "$WORK/vid_err.txt" | progress_lines "$frames" "${J[$n,avg]}" >> "$LOG"
    rc=${pipestatus[1]}
    # ffmpeg's messages, without its note about the spatial audio track it
    # opens but doesn't use
    grep -v 'Guessed Channel Layout' "$WORK/vid_err.txt" | sed 's/^/  /' >> "$LOG"
    if (( rc != 0 )) || ! [ -s "$out" ]; then
      fail "ffmpeg could not convert it (exit status $rc)"
      continue
    fi
    # The check: the expected codec in 10 bits, and the whole duration; and
    # the copy's size, for the log.
    oc='' op='' od='' ow='' oh=''
    while IFS='=' read -r key value; do
      case $key in
        codec_name) oc=$value;;
        pix_fmt) op=$value;;
        duration) od=$value;;
        width) ow=$value;;
        height) oh=$value;;
      esac
    done < <("$ffprobe" -v error -select_streams v:0 -show_entries stream=codec_name,pix_fmt,duration,width,height -of default=nw=1 "$out" 2>/dev/null)
    want=hevc
    [ "$CODEC" = av1 ] && want=av1
    if [ "$oc" != "$want" ]; then
      fail "the copy has no $want video"
      continue
    fi
    if [ "$op" != yuv420p10le ]; then
      fail "the copy is not 10-bit ($op)"
      continue
    fi
    [[ $od == [0-9.]## ]] || od=0
    slack=$(( dur / 100.0 > 0.5 ? dur / 100.0 : 0.5 ))
    if (( dur > 0 && od < dur - slack )); then
      fail "only $(printf '%.0f' $(( 100.0 * od / dur )))% of the video was written"
      continue
    fi
    if ! "$vidmeta" copy "$in" "$out" > /dev/null 2> "$WORK/vid_err.txt"; then
      fail "the metadata could not be copied: $(cat "$WORK/vid_err.txt")"
      continue
    fi
    elapsed=$(( SECONDS - started ))
    (( elapsed < 1 )) && elapsed=1
    size_out=$(stat -f %z "$out")
    bytes_in=$(( bytes_in + ${J[$n,size]} ))
    bytes_out=$(( bytes_out + size_out ))
    echo "  $(size_text ${J[$n,size]}) → $(size_text $size_out) ($(( 100 * size_out / (${J[$n,size]} > 0 ? ${J[$n,size]} : 1) ))%)${ow:+, ${ow}×${oh}}, $(duration_text $elapsed) at $(printf '%.1f' $(( dur / elapsed )))× real time" >> "$LOG"
    printf 'vid_out_%d.mp4|%d|delete|%s\n' $n $n "${name:r}.mp4" >> "$WORK/vid_done.txt"
    converted=$((converted + 1))
  done
  rm -f "$WORK/vid_err.txt"
  {
    echo
    echo "Done: $converted of $((njobs + unreadable)) converted in $(duration_text $(( SECONDS - t0 )))."
    (( failed )) && echo "$failed failed; see the messages above."
    (( converted && bytes_in )) && echo "$(size_text $bytes_in) → $(size_text $bytes_out) ($(( 100 * bytes_out / bytes_in ))%)"
  } >> "$LOG"
elif (( failed )); then
  { echo; echo "Done: 0 of $failed converted."; echo "$failed failed; see the messages above."; } >> "$LOG"
elif [ -z "${space_error-}" ]; then
  echo "Nothing to convert: no videos among the selected items." >> "$LOG"
fi
# This run's settings, for "Same as last time" next time.
{
  print -r -- "CODEC=$CODEC"
  print -r -- "PRESET=$PRESET"
  print -r -- "TUNE=$TUNE"
  print -r -- "RF=$RF"
  print -r -- "SIZE=$SIZE"
  print -r -- "AUDIO=$AUDIO"
  print -r -- "SUMMARY=$SUMMARY"
} > "$SETTINGS"
