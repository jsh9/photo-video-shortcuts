export COLUMNS=100
if [ "$WATCH" = 1 ]; then
  # A Terminal window follows the log while jxlbatch runs; it records its
  # process id so that the finish step can end exactly this window (finish.zsh).
  cmd="$LOGDIR/@ROUTE@.command"
  print -r -- '#!/bin/zsh' > "$cmd"
  print -r -- "echo \$\$ > ${(q)LOGDIR}/@ROUTE@.pid" >> "$cmd"
  print -r -- "exec tail -n +1 -f ${(q)LOG}" >> "$cmd"
  chmod +x "$cmd"
  open -a Terminal "$cmd" 2>>"$LOG" || true
fi
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
