export COLUMNS=100
if [ -f "$WORK/jxl_job.txt" ]; then
  "$jxlbatch" -q "$QUALITY" -e @EFFORT@ -C "$WORK" jxl_job.txt >> "$LOG" 2>&1
else
  echo "ERROR: no photos to convert." >> "$LOG"
fi
