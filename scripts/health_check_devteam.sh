#!/bin/bash
# Health check for all DevTeam MCPs

DEVTEAM=(
  "qa-engineer:7201"
  "security:7202"
  "architecture:7203"
  "backend:7204"
  "frontend:7205"
  "devops:7206"
  "product-owner:7207"
  "product-manager:7208"
  "cross-devteam-validators:7209"
  "devteam-observatory:7210"
)

echo "🏥 DevTeam Health Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

all_healthy=true
healthy_count=0
total_count=${#DEVTEAM[@]}

for devteam_info in "${DEVTEAM[@]}"; do
  IFS=':' read -r devteam_name port <<< "$devteam_info"

  # Check if port is open
  if timeout 2 bash -c "</dev/tcp/127.0.0.1/$port" 2>/dev/null; then
    # Check health endpoint
    response=$(curl -s -w "\n%{http_code}" http://localhost:$port/health 2>/dev/null)
    http_code=$(echo "$response" | tail -n 1)

    if [ "$http_code" = "200" ]; then
      echo "✅ $devteam_name:$port — Healthy"
      ((healthy_count++))
    else
      echo "⚠️  $devteam_name:$port — HTTP $http_code"
      all_healthy=false
    fi
  else
    echo "❌ $devteam_name:$port — Not responding"
    all_healthy=false
  fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Status: $healthy_count / $total_count healthy"

if [ "$all_healthy" = true ]; then
  echo "🎉 All DevTeam are healthy!"
  exit 0
else
  echo "⚠️  Some DevTeam need attention"
  exit 1
fi
