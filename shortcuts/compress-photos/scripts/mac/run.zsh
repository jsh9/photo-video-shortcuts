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
if [ -f "$WORK/jxl_job.txt" ]; then
  "$jxlbatch" --mac -q "$QUALITY" -e @EFFORT@ "${cores[@]}" -C "$WORK" jxl_job.txt >> "$LOG" 2>&1
else
  echo "ERROR: no photos to convert." >> "$LOG"
fi
