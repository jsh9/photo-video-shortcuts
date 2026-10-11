export COLUMNS=100
@PROGRESS@
# How the cores are used (the shortcut's second question, CORES): "one" is
# one photo at a time on one thread, so the Mac stays free for other work;
# anything else is several photos at a time, each with a share of the cores
# (jxlbatch picks how many from the cores and the memory).
case $CORES in
  one) cores=(-j 1 -t 1);;
  *) cores=(-j 0);;
esac
# The HDR choice (the third question, HDR): "drop" saves every photo as SDR
# (jxlbatch --sdr); anything else keeps an HDR photo's HDR.
case $HDR in
  drop) hdr=(--sdr);;
  *) hdr=();;
esac
# The format (the first question, FORMAT) and its quality: HEIC with x265 at
# the chosen RF, or JPEG XL at the chosen quality.
case $FORMAT in
  heic) fmt=(--heic --rf "$QUALITY");;
  *) fmt=(-q "$QUALITY" -e @EFFORT@);;
esac
if [ -f "$WORK/jxl_job.txt" ]; then
  "$jxlbatch" --mac "${fmt[@]}" "${cores[@]}" "${hdr[@]}" -C "$WORK" jxl_job.txt >> "$LOG" 2>&1
else
  echo "ERROR: no photos to convert." >> "$LOG"
fi
