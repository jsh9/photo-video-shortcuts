export COLUMNS=100
if [ "$WATCH" = 1 ]; then
  # A Terminal window follows the log while jxlbatch runs; the shortcut's last
  # step ends it with "Done" (see the finish script in build_mac_shortcuts.py).
  print -r -- '#!/bin/zsh' > "$LOGDIR/progress.command"
  print -r -- "exec tail -n +1 -f ${(q)LOG}" >> "$LOGDIR/progress.command"
  chmod +x "$LOGDIR/progress.command"
  open -a Terminal "$LOGDIR/progress.command" 2>>"$LOG" || true
fi
if [ -f "$WORK/jxl_job.txt" ]; then
  "$jxlbatch" --mac -q "$QUALITY" -e @EFFORT@ -C "$WORK" jxl_job.txt >> "$LOG" 2>&1
else
  echo "ERROR: no photos to convert." >> "$LOG"
fi
