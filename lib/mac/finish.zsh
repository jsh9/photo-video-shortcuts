# The finish step (lib/mac, shared by the Mac shortcuts' scripts): if this run
# opened a progress window (progress.zsh: the route's script in LOGDIR), the
# log ends with "Done" and the window's tail is ended by its recorded pid.
# Needs LOGDIR and LOG, as progress.zsh does.
if [ -e "$LOGDIR/@ROUTE@.command" ]; then
  echo "Done. You can close this window." >> "$LOG"
  sleep 1
  [ -e "$LOGDIR/@ROUTE@.pid" ] && kill "$(cat "$LOGDIR/@ROUTE@.pid")" 2>/dev/null
  rm -f "$LOGDIR/@ROUTE@.pid" "$LOGDIR/@ROUTE@.command"
fi
