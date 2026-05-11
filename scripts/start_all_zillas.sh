#!/bin/bash
# Multi-server orchestration: Start all 10 Zilla MCPs simultaneously
# Ports: 7201-7210

set -e

ZILLAS=(
  "qazilla-mcp-server:7201"
  "seczilla-mcp-server:7202"
  "archzilla-mcp-server:7203"
  "backzilla-mcp-server:7204"
  "frontzilla-pixelfera-mcp-server:7205"
  "opszilla-mcp-server:7206"
  "pozilla-mcp-server:7207"
  "productzilla-mcp-server:7208"
  "cross-zilla-validators:7209"
  "zilla-observatory:7210"
)

REPO_ROOT="/home/dev/repos/platform-devs"
LOG_DIR="$HOME/.platform/logs"
mkdir -p "$LOG_DIR"

echo "🚀 Starting all 10 Zilla MCPs..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Start each Zilla in background
for zilla_info in "${ZILLAS[@]}"; do
  IFS=':' read -r zilla_dir port <<< "$zilla_info"
  zilla_name="${zilla_dir%-mcp-server}"
  zilla_name="${zilla_name%-pixelfera}"

  # Determine Python file name
  if [ "$zilla_dir" = "cross-zilla-validators" ]; then
    py_file="cross_zilla_validators_mcp.py"
  elif [ "$zilla_dir" = "zilla-observatory" ]; then
    py_file="zilla_observatory_mcp.py"
  else
    py_file="${zilla_name}_mcp.py"
  fi

  zilla_path="$REPO_ROOT/$zilla_dir"
  log_file="$LOG_DIR/${zilla_name}.log"

  if [ ! -f "$zilla_path/$py_file" ]; then
    echo "❌ $zilla_name: Python file not found at $zilla_path/$py_file"
    continue
  fi

  echo "▶️  Starting $zilla_name (port $port)..."

  # Start in background, capture PID
  cd "$zilla_path"
  PORT=$port python3 "$py_file" >> "$log_file" 2>&1 &
  pid=$!
  echo "$pid" > "$LOG_DIR/${zilla_name}.pid"

  echo "   PID: $pid | Log: $log_file"
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⏳ Waiting for servers to start..."
sleep 8

# Validate all are running
echo ""
echo "✅ Validating servers..."
all_healthy=true

for zilla_info in "${ZILLAS[@]}"; do
  IFS=':' read -r zilla_dir port <<< "$zilla_info"
  zilla_name="${zilla_dir%-mcp-server}"
  zilla_name="${zilla_name%-pixelfera}"

  if curl -s http://localhost:$port/health | grep -q "healthy"; then
    echo "✅ $zilla_name (port $port) is healthy"
  else
    echo "❌ $zilla_name (port $port) health check failed"
    all_healthy=false
  fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$all_healthy" = true ]; then
  echo "🎉 All 10 Zillas started successfully!"
  echo ""
  echo "Running Zillas:"
  ps aux | grep -E "_mcp.py" | grep -v grep || true
  echo ""
  echo "Logs: $LOG_DIR"
  exit 0
else
  echo "⚠️  Some servers may not be healthy. Check logs:"
  ls -la "$LOG_DIR"/*.log
  exit 1
fi
