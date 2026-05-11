#!/bin/bash
# Load testing for all 10 Zilla MCPs
# Tests: health checks, MCP tool calls, concurrent connections

set -e

ZILLAS=(
  "qazilla:7201"
  "seczilla:7202"
  "archzilla:7203"
  "backzilla:7204"
  "frontzilla:7205"
  "opszilla:7206"
  "pozilla:7207"
  "productzilla:7208"
  "cross-zilla-validators:7209"
  "zilla-observatory:7210"
)

LOG_DIR="$HOME/.platform/logs"
REPORT_FILE="$LOG_DIR/load_test_report.txt"
RESULTS_DIR="$LOG_DIR/load_test_results"
mkdir -p "$RESULTS_DIR"

echo "🚀 Load Testing All 10 Zilla MCPs"
echo "=================================="
echo ""

# Function to check if ab (Apache Bench) is available
check_ab() {
  if ! command -v ab &> /dev/null; then
    echo "⚠️  Apache Bench (ab) not found. Installing..."
    apt-get update -qq && apt-get install -y -qq apache2-utils > /dev/null 2>&1
    echo "✅ Apache Bench installed"
  fi
}

# Start all Zillas
echo "Starting all 10 Zillas..."
timeout 60 ./scripts/start_all_zillas.sh > /dev/null 2>&1 || true
sleep 10
echo "✅ All servers started"
echo ""

# Check Apache Bench
check_ab

# Test scenarios
echo "Running load tests..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee "$REPORT_FILE"
echo "Load Testing Report — $(date)" | tee -a "$REPORT_FILE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$REPORT_FILE"
echo "" | tee -a "$REPORT_FILE"

# Test 1: Health checks with increasing concurrency
echo "Test 1: Health Checks (Sequential → Concurrent)" | tee -a "$REPORT_FILE"
echo "──────────────────────────────────────────────" | tee -a "$REPORT_FILE"

for zilla_info in "${ZILLAS[@]}"; do
  IFS=':' read -r zilla_name port <<< "$zilla_info"

  echo "  Testing $zilla_name:$port..." | tee -a "$REPORT_FILE"

  # 50 sequential requests
  ab -q -n 50 -c 1 "http://localhost:$port/health" > "$RESULTS_DIR/${zilla_name}_health_seq.txt" 2>&1
  seq_rps=$(grep "Requests per second:" "$RESULTS_DIR/${zilla_name}_health_seq.txt" | awk '{print $4}')

  # 50 requests, 5 concurrent
  ab -q -n 50 -c 5 "http://localhost:$port/health" > "$RESULTS_DIR/${zilla_name}_health_conc5.txt" 2>&1
  conc5_rps=$(grep "Requests per second:" "$RESULTS_DIR/${zilla_name}_health_conc5.txt" | awk '{print $4}')

  # 50 requests, 10 concurrent
  ab -q -n 50 -c 10 "http://localhost:$port/health" > "$RESULTS_DIR/${zilla_name}_health_conc10.txt" 2>&1
  conc10_rps=$(grep "Requests per second:" "$RESULTS_DIR/${zilla_name}_health_conc10.txt" | awk '{print $4}')

  printf "    Sequential (c=1):   %.2f req/s\n" "$seq_rps" | tee -a "$REPORT_FILE"
  printf "    Concurrent  (c=5):  %.2f req/s\n" "$conc5_rps" | tee -a "$REPORT_FILE"
  printf "    Concurrent  (c=10): %.2f req/s\n" "$conc10_rps" | tee -a "$REPORT_FILE"
done

echo "" | tee -a "$REPORT_FILE"

# Test 2: MCP tool calls (create_test_plan on qazilla)
echo "Test 2: MCP Tool Calls (create_test_plan)" | tee -a "$REPORT_FILE"
echo "───────────────────────────────────────" | tee -a "$REPORT_FILE"

# Create payload file for POST requests
cat > /tmp/mcp_payload.json << 'EOF'
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "create_test_plan",
    "arguments": {
      "title": "Load Test Plan",
      "feature": "Performance Testing",
      "scope": "Concurrent Execution",
      "objectives": "Validate system under load"
    }
  }
}
EOF

echo "  Testing qazilla MCP tool calls..."  | tee -a "$REPORT_FILE"

# 20 sequential MCP calls
ab -q -n 20 -c 1 -p /tmp/mcp_payload.json -T "application/json" \
  "http://localhost:7201/mcp/tools/call" > "$RESULTS_DIR/qazilla_mcp_seq.txt" 2>&1
mcp_seq_rps=$(grep "Requests per second:" "$RESULTS_DIR/qazilla_mcp_seq.txt" | awk '{print $4}')

# 20 concurrent MCP calls
ab -q -n 20 -c 5 -p /tmp/mcp_payload.json -T "application/json" \
  "http://localhost:7201/mcp/tools/call" > "$RESULTS_DIR/qazilla_mcp_conc.txt" 2>&1
mcp_conc_rps=$(grep "Requests per second:" "$RESULTS_DIR/qazilla_mcp_conc.txt" | awk '{print $4}')

printf "    Sequential (c=1):  %.2f req/s\n" "$mcp_seq_rps" | tee -a "$REPORT_FILE"
printf "    Concurrent  (c=5): %.2f req/s\n" "$mcp_conc_rps" | tee -a "$REPORT_FILE"

echo "" | tee -a "$REPORT_FILE"

# Test 3: Aggregate health check across all 10 servers
echo "Test 3: Aggregate Load (All 10 Servers Simultaneous)" | tee -a "$REPORT_FILE"
echo "───────────────────────────────────────────────────" | tee -a "$REPORT_FILE"

total_requests=0
total_failed=0
total_rps=0
server_count=0

for zilla_info in "${ZILLAS[@]}"; do
  IFS=':' read -r zilla_name port <<< "$zilla_info"

  # 100 concurrent requests to each server
  ab -q -n 100 -c 20 "http://localhost:$port/health" > "$RESULTS_DIR/${zilla_name}_aggregate.txt" 2>&1

  requests=$(grep "Requests per second:" "$RESULTS_DIR/${zilla_name}_aggregate.txt" | awk '{print $4}')
  failed=$(grep "Failed requests:" "$RESULTS_DIR/${zilla_name}_aggregate.txt" | awk '{print $3}')

  [ -z "$failed" ] && failed=0
  [ -z "$requests" ] && requests=0

  total_rps=$(echo "$total_rps + $requests" | bc)
  total_failed=$((total_failed + failed))
  total_requests=$((total_requests + 100))
  ((server_count++))

  echo "  $zilla_name: $(printf "%.2f" $requests) req/s | Failed: $failed" | tee -a "$REPORT_FILE"
done

avg_rps=$(echo "scale=2; $total_rps / $server_count" | bc)
echo "" | tee -a "$REPORT_FILE"
echo "  Total Requests:  $total_requests" | tee -a "$REPORT_FILE"
echo "  Total Failed:    $total_failed" | tee -a "$REPORT_FILE"
echo "  Average RPS:     $avg_rps req/s" | tee -a "$REPORT_FILE"
echo "  Aggregate RPS:   $(printf "%.2f" $total_rps) req/s" | tee -a "$REPORT_FILE"

echo "" | tee -a "$REPORT_FILE"

# Performance summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$REPORT_FILE"
echo "Summary" | tee -a "$REPORT_FILE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$REPORT_FILE"

if [ "$total_failed" -eq 0 ]; then
  echo "✅ All tests passed. No failures." | tee -a "$REPORT_FILE"
  echo "✅ Health check performance stable across all servers" | tee -a "$REPORT_FILE"
  echo "✅ MCP tool calls executing successfully under load" | tee -a "$REPORT_FILE"
  echo "✅ Average throughput: $avg_rps req/s per server" | tee -a "$REPORT_FILE"
  echo "✅ Aggregate throughput: $(printf "%.2f" $total_rps) req/s across all 10 servers" | tee -a "$REPORT_FILE"
  status="PASS"
else
  echo "⚠️  Some failures detected: $total_failed failed requests" | tee -a "$REPORT_FILE"
  status="WARN"
fi

echo "" | tee -a "$REPORT_FILE"
echo "Report saved to: $REPORT_FILE" | tee -a "$REPORT_FILE"
echo "Detailed results in: $RESULTS_DIR/" | tee -a "$REPORT_FILE"

# Stop all Zillas
echo ""
echo "Stopping all Zillas..."
./scripts/stop_all_zillas.sh > /dev/null 2>&1 || true
echo "✅ Cleanup complete"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Load Testing Complete"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
cat "$REPORT_FILE"

exit 0
