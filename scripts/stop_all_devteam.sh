#!/bin/bash
# Stop all DevTeam MCPs gracefully

DEVTEAM=(
  "qa-engineer"
  "security"
  "architecture"
  "backend"
  "frontend"
  "devops"
  "product-owner"
  "product-manager"
  "cross-devteam-validators"
  "devteam-observatory"
)

LOG_DIR="$HOME/.platform/logs"

echo "🛑 Stopping all DevTeam MCPs..."

for devteam in "${DEVTEAM[@]}"; do
  pid_file="$LOG_DIR/${devteam%-validators}.pid"

  if [ -f "$pid_file" ]; then
    pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid"
      echo "✅ Stopped $devteam (PID: $pid)"
      rm "$pid_file"
    else
      echo "⚠️  $devteam (PID: $pid) not running"
      rm "$pid_file"
    fi
  else
    # Try to kill by process name
    pkill -f "${devteam}_mcp.py" || true
    echo "✅ Stopped $devteam (by process name)"
  fi
done

echo ""
echo "All DevTeam stopped."
