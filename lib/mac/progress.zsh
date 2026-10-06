# The progress window (lib/mac, shared by the Mac shortcuts' scripts). Needs
# LOGDIR, a folder Terminal reads without asking for access (not Pictures or
# iCloud Drive); LOG, the log, in it; and WATCH, 1 to open the window. Its
# files are LOGDIR/@ROUTE@.command and LOGDIR/@ROUTE@.pid (@ROUTE@: the
# route's name, filled in by the generator), which finish.zsh uses too.
if [ "$WATCH" = 1 ]; then
  # A Terminal window follows the log while the conversion runs; it records
  # its process id so that the finish step can end exactly this window.
  cmd="$LOGDIR/@ROUTE@.command"
  print -r -- '#!/bin/zsh' > "$cmd"
  print -r -- "echo \$\$ > ${(q)LOGDIR}/@ROUTE@.pid" >> "$cmd"
  print -r -- "exec tail -n +1 -f ${(q)LOG}" >> "$cmd"
  chmod +x "$cmd"
  open -a Terminal "$cmd" 2>>"$LOG" || true
fi
