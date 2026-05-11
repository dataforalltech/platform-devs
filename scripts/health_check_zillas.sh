#!/bin/bash
# Health check for all Zilla MCPs

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

echo "🏥 Zilla Health Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

all_healthy=true
healthy_count=0
total_count=${#ZILLAS[@]}

for zilla_info in "${ZILLAS[@]}"; do
  IFS=':' read -r zilla_name port <<< "$zilla_info"

  # Check if port is open
  if timeout 2 bash -c "</dev/tcp/127.0.0.1/$port" 2>/dev/null; then
    # Check health endpoint
    response=$(curl -s -w "\n%{http_code}" http://localhost:$port/health 2>/dev/null)
    http_code=$(echo "$response" | tail -n 1)

    if [ "$http_code" = "200" ]; then
      echo "✅ $zilla_name:$port — Healthy"
      ((healthy_count++))
    else
      echo "⚠️  $zilla_name:$port — HTTP $http_code"
      all_healthy=false
    fi
  else
    echo "❌ $zilla_name:$port — Not responding"
    all_healthy=false
  fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Status: $healthy_count / $total_count healthy"

if [ "$all_healthy" = true ]; then
  echo "🎉 All Zillas are healthy!"
  exit 0
else
  echo "⚠️  Some Zillas need attention"
  exit 1
fi
