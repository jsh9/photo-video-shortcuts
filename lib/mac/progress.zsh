if [ "$WATCH" = 1 ]; then
  # A Terminal window follows the log while @ENCODER@ runs; it records its
  # process id so that the finish step can end exactly this window (finish.zsh).
  cmd="$LOGDIR/@ROUTE@.command"
  print -r -- '#!/bin/zsh' > "$cmd"
  print -r -- "echo \$\$ > ${(q)LOGDIR}/@ROUTE@.pid" >> "$cmd"
  print -r -- "exec tail -n +1 -f ${(q)LOG}" >> "$cmd"
  chmod +x "$cmd"
  open -a Terminal "$cmd" 2>>"$LOG" || true
fi
