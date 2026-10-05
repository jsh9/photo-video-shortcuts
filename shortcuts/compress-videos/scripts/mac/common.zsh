# @NAME@ @VERSION@: converts the videos selected in Photos with ffmpeg.
# Help: @HELP_URL@
setopt extendedglob
# Photos exported the originals into $WORK/in (export.applescript); the copies
# go to $WORK/out, where Photos imports them from (import.applescript).
WORK=@WORK@
mkdir -p "$WORK"
# The log (and the progress window's script) stay out of Pictures: Terminal
# reads them without asking for access to that folder.
LOGDIR=@LOG_DIR@
mkdir -p "$LOGDIR"
LOG="$LOGDIR/@ROUTE@.log"
: > "$LOG"
VERSION='@VERSION@'
WATCH=${WATCH:-1}  # 0: no Terminal window following the progress
NICE=${NICE:-10}  # ffmpeg's priority (nice): 10 keeps the Mac responsive
DOLBY=${DOLBY:-1}  # 0: convert Dolby Vision videos as plain HDR
PROGRESS_EVERY=${PROGRESS_EVERY:-5}  # seconds between progress lines
# The shortcut's choices, the first word of each list's title; with REUSE=1,
# the last run's settings instead (SETTINGS, written after each batch).
CODEC='@CODEC@'
PRESET='@PRESET@'
TUNE='@TUNE@'
RF='@RF@'
SIZE='@SIZE@'
AUDIO='@AUDIO@'
REUSE='@REUSE@'
# IDS: one "id|filename" line per item selected in Photos (or "ERROR: ...")
IDS=$(cat <<'VID_LINES'
@LINES@
VID_LINES
)
SETTINGS="$LOGDIR/last-settings.txt"
# unique PATH: PATH if nothing is there, else "PATH 2", "PATH 3"... (for .mp4)
unique() {
  local dest=$1 base=${1%.mp4} k=2
  while [ -e "$dest" ]; do dest="$base $k.mp4"; k=$((k + 1)); done
  print -r -- "$dest"
}
# size_text BYTES: "880 KB", "171 MB", "1.2 GB"
size_text() {
  if (( $1 >= 1000000000 )); then printf '%.1f GB' $(( $1 / 1e9 ))
  elif (( $1 >= 1000000 )); then printf '%.0f MB' $(( $1 / 1e6 ))
  else printf '%.0f KB' $(( $1 / 1e3 ))
  fi
}
# duration_text SECONDS: "2:05", "1:02:05"
duration_text() {
  local s
  s=$(printf '%.0f' $1)
  if (( s >= 3600 )); then printf '%d:%02d:%02d' $((s / 3600)) $((s % 3600 / 60)) $((s % 60))
  else printf '%d:%02d' $((s / 60)) $((s % 60))
  fi
}
if [ "$REUSE" = 1 ] && [ -f "$SETTINGS" ]; then
  while IFS='=' read -r key value; do
    case $key in
      CODEC|PRESET|TUNE|RF|SIZE|AUDIO) typeset "$key=$value";;
    esac
  done < "$SETTINGS"
fi
# Each setting is checked: the values are the lists' (see vf.py).
bad=''
case $CODEC in
  h265)
    CODEC_TEXT='H.265'; venc=libx265
    case $PRESET in fast|medium|slow) ;; *) bad="preset '$PRESET'";; esac
    case $TUNE in none|grain) ;; *) bad="tune '$TUNE'";; esac;;
  av1)
    CODEC_TEXT='AV1'; venc=libsvtav1
    case $PRESET in [2-5]) ;; *) bad="preset '$PRESET'";; esac
    TUNE='';;  # SVT-AV1 is always tuned for visual quality (tune=0)
  *) bad="codec '$CODEC'";;
esac
case $SIZE in
  4K) LIMIT=3840;;
  2K) LIMIT=2560;;
  1080p) LIMIT=1920;;
  720p) LIMIT=1280;;
  *) bad="largest size '$SIZE'";;
esac
[[ $RF == <1-63> ]] || bad="RF '$RF'"
[[ $AUDIO == <6-510> ]] || bad="audio bitrate '$AUDIO'"
if [ -n "$bad" ]; then
  echo "ERROR: unexpected $bad; run the shortcut again and choose the settings." >> "$LOG"
  exit 0
fi
SUMMARY="$CODEC_TEXT · preset $PRESET${TUNE:+ · tune $TUNE} · RF $RF · $SIZE · Opus $AUDIO kbps"
echo "Settings: $SUMMARY" >> "$LOG"
# The tools: ffmpeg and ffprobe (ours, or Homebrew's), and vidmeta.
ffmpeg=''
for c in "${FFMPEG:-}" @FFMPEG_CANDIDATES@; do  # FFMPEG: an override (used by the tests)
  if [ -n "$c" ] && [ -x "$c" ]; then ffmpeg=$c; break; fi
done
vidmeta=''
for c in "${VIDMETA:-}" @VIDMETA_CANDIDATES@; do  # VIDMETA: an override
  if [ -n "$c" ] && [ -x "$c" ]; then vidmeta=$c; break; fi
done
if [ -z "$ffmpeg" ]; then
  echo "ERROR: ffmpeg is not installed (looked in @FFMPEG_LOOKED@)." >> "$LOG"
  echo "Install it: see @HELP_URL@" >> "$LOG"
  exit 0
fi
# ffprobe: next to ffmpeg, named like it (compress-videos-ffprobe, ffprobe)
ffprobe=${FFPROBE:-${ffmpeg:h}/${${ffmpeg:t}/ffmpeg/ffprobe}}  # FFPROBE: an override
if ! [ -x "$ffprobe" ]; then
  echo "ERROR: $ffprobe is missing: it must be next to $ffmpeg." >> "$LOG"
  echo "Install it: see @HELP_URL@" >> "$LOG"
  exit 0
fi
if [ -z "$vidmeta" ]; then
  echo "ERROR: vidmeta is not installed (looked in @VIDMETA_LOOKED@)." >> "$LOG"
  echo "Install it: see @HELP_URL@" >> "$LOG"
  exit 0
fi
ffversion=$("$ffmpeg" -hide_banner -version 2>/dev/null | head -1)
ffversion=${${ffversion#ffmpeg version }%% *}
echo "ffmpeg: $ffmpeg ($ffversion)" >> "$LOG"
if [[ $ffversion =~ '^n?([0-9]+)\.([0-9]+)' ]]; then
  if (( match[1] < 7 || (match[1] == 7 && match[2] < 1) )); then
    echo "ERROR: $ffmpeg is version $ffversion; 7.1 or later is needed. Install the one made for this shortcut: see @HELP_URL@" >> "$LOG"
    exit 0
  fi
else
  echo "! could not read the version of $ffmpeg; 7.1 or later is needed" >> "$LOG"
fi
encoders=$("$ffmpeg" -hide_banner -encoders 2>/dev/null)
missing=''
for e in $venc libopus; do
  [[ $encoders == *" $e "* ]] || missing="${missing:+$missing and }$e"
done
if [ -n "$missing" ]; then
  echo "ERROR: $ffmpeg has no $missing encoder. Install the ffmpeg made for this shortcut: see @HELP_URL@" >> "$LOG"
  exit 0
fi
# Dolby Vision is carried with ffmpeg's -dolbyvision option (7.1 or later, in
# the x265 and SVT-AV1 encoders); without it, those videos are skipped.
dovi_ok=''
"$ffmpeg" -hide_banner -h "encoder=$venc" 2>/dev/null | grep -q -- '-dolbyvision' && dovi_ok=1
if [ -z "$dovi_ok" ] && [ "$DOLBY" = 1 ]; then
  echo "! $ffmpeg can't carry Dolby Vision: videos with it are skipped. Install the ffmpeg made for this shortcut: see @HELP_URL@" >> "$LOG"
fi
# The decoders, to choose an audio track this ffmpeg can read.
typeset -A decodable
for line in "${(@f)$("$ffmpeg" -hide_banner -decoders 2>/dev/null)}"; do
  words=(${=line})
  [[ ${words[1]} == [VAS]????? ]] && decodable[${words[2]}]=1
done
if [ "$("$vidmeta" --version 2>/dev/null)" != "vidmeta $VERSION" ]; then
  echo "! $vidmeta is not vidmeta $VERSION, the version this shortcut was made for; see Updating in @HELP_URL@" >> "$LOG"
fi
