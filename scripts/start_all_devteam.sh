#!/bin/bash
# Multi-server orchestration: Start all 10 DevTeam MCPs simultaneously
# Ports: 7201-7210

set -e

DEVTEAM=(
  "qa-engineer-mcp-server:7201"
  "security-mcp-server:7202"
  "architecture-mcp-server:7203"
  "backend-mcp-server:7204"
  "frontend-pixelfera-mcp-server:7205"
  "devops-mcp-server:7206"
  "product-owner-mcp-server:7207"
  "product-manager-mcp-server:7208"
  "cross-devteam-validators:7209"
  "devteam-observatory:7210"
)

REPO_ROOT="/home/dev/repos/platform-devs"
LOG_DIR="$HOME/.platform/logs"
mkdir -p "$LOG_DIR"

echo "🚀 Starting all 10 DevTeam MCPs..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Start each DevTeam in background
for devteam_info in "${DEVTEAM[@]}"; do
  IFS=':' read -r devteam_dir port <<< "$devteam_info"
  devteam_name="${devteam_dir%-mcp-server}"
  devteam_name="${devteam_name%-pixelfera}"

  # Determine Python file name
  if [ "$devteam_dir" = "cross-devteam-validators" ]; then
    py_file="cross_devteam_validators_mcp.py"
  elif [ "$devteam_dir" = "devteam-observatory" ]; then
    py_file="devteam_observatory_mcp.py"
  else
    py_file="${devteam_name}_mcp.py"
  fi

  devteam_path="$REPO_ROOT/$devteam_dir"
  log_file="$LOG_DIR/${devteam_name}.log"

  if [ ! -f "$devteam_path/$py_file" ]; then
    echo "❌ $devteam_name: Python file not found at $devteam_path/$py_file"
    continue
  fi

  echo "▶️  Starting $devteam_name (port $port)..."

  # Start in background, capture PID
  cd "$devteam_path"
  PORT=$port python3 "$py_file" >> "$log_file" 2>&1 &
  pid=$!
  echo "$pid" > "$LOG_DIR/${devteam_name}.pid"

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

for devteam_info in "${DEVTEAM[@]}"; do
  IFS=':' read -r devteam_dir port <<< "$devteam_info"
  devteam_name="${devteam_dir%-mcp-server}"
  devteam_name="${devteam_name%-pixelfera}"

  if curl -s http://localhost:$port/health | grep -q "healthy"; then
    echo "✅ $devteam_name (port $port) is healthy"
  else
    echo "❌ $devteam_name (port $port) health check failed"
    all_healthy=false
  fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$all_healthy" = true ]; then
  echo "🎉 All 10 DevTeam started successfully!"
  echo ""
  echo "Running DevTeam:"
  ps aux | grep -E "_mcp.py" | grep -v grep || true
  echo ""
  echo "Logs: $LOG_DIR"
  exit 0
else
  echo "⚠️  Some servers may not be healthy. Check logs:"
  ls -la "$LOG_DIR"/*.log
  exit 1
fi
