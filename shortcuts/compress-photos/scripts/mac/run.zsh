export COLUMNS=100
if [ "$WATCH" = 1 ]; then
  # A Terminal window follows the log while jxlbatch runs; the shortcut's last
  # step ends it with "Done" (see the finish script in build_mac_shortcuts.py).
  print -r -- '#!/bin/zsh' > "$WORK/progress.command"
  print -r -- "exec tail -n +1 -f ${(q)LOG}" >> "$WORK/progress.command"
  chmod +x "$WORK/progress.command"
  open -a Terminal "$WORK/progress.command" 2>>"$LOG" || true
fi
if [ -f "$WORK/jxl_job.txt" ]; then
  "$jxlbatch" --mac -q "$QUALITY" -e @EFFORT@ -C "$WORK" jxl_job.txt >> "$LOG" 2>&1
else
  echo "ERROR: no photos to convert." >> "$LOG"
fi
