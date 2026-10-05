if [ -e "$LOGDIR/@ROUTE@.command" ]; then
  echo "Done. You can close this window." >> "$LOG"
  sleep 1
  [ -e "$LOGDIR/@ROUTE@.pid" ] && kill "$(cat "$LOGDIR/@ROUTE@.pid")" 2>/dev/null
  rm -f "$LOGDIR/@ROUTE@.pid" "$LOGDIR/@ROUTE@.command"
fi
