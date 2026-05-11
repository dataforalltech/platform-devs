#!/bin/bash
# Stop all Zilla MCPs gracefully

ZILLAS=(
  "qazilla"
  "seczilla"
  "archzilla"
  "backzilla"
  "frontzilla"
  "opszilla"
  "pozilla"
  "productzilla"
  "cross-zilla-validators"
  "zilla-observatory"
)

LOG_DIR="$HOME/.platform/logs"

echo "🛑 Stopping all Zilla MCPs..."

for zilla in "${ZILLAS[@]}"; do
  pid_file="$LOG_DIR/${zilla%-validators}.pid"

  if [ -f "$pid_file" ]; then
    pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid"
      echo "✅ Stopped $zilla (PID: $pid)"
      rm "$pid_file"
    else
      echo "⚠️  $zilla (PID: $pid) not running"
      rm "$pid_file"
    fi
  else
    # Try to kill by process name
    pkill -f "${zilla}_mcp.py" || true
    echo "✅ Stopped $zilla (by process name)"
  fi
done

echo ""
echo "All Zillas stopped."
