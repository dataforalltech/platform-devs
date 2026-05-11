#!/bin/bash
# Setup monitoring and log aggregation for all 10 Zilla MCPs

set -e

LOG_DIR="$HOME/.platform/logs"
MONITORING_DIR="$HOME/.platform/monitoring"
mkdir -p "$LOG_DIR" "$MONITORING_DIR"

echo "🔧 Setting up Zilla Monitoring & Log Aggregation"
echo "=================================================="
echo ""

# 1. Configure log rotation with logrotate
echo "1️⃣  Configuring log rotation..."

LOGROTATE_CONFIG="/tmp/zillas-logrotate"
cat > "$LOGROTATE_CONFIG" << 'EOF'
# Zilla MCP logs rotation
~/.platform/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    notifempty
    create 0644 dev dev
    sharedscripts
    postrotate
        # Restart services if needed
        # sudo systemctl reload zillas
    endscript
}
EOF

if [ -d "/etc/logrotate.d" ]; then
  echo "  📝 logrotate configuration template created"
  echo "  ℹ️  To install: sudo cp $LOGROTATE_CONFIG /etc/logrotate.d/zillas"
else
  echo "  ⚠️  logrotate not available (advanced feature)"
fi

echo ""

# 2. Create log archival script
echo "2️⃣  Creating log archival script..."

cat > "$MONITORING_DIR/archive_logs.sh" << 'EOF'
#!/bin/bash
# Archive old logs

LOG_DIR="$HOME/.platform/logs"
ARCHIVE_DIR="$HOME/.platform/logs/archive"
mkdir -p "$ARCHIVE_DIR"

# Archive logs older than 7 days
find "$LOG_DIR" -name "*.log" -type f -mtime +7 -exec gzip -v {} \;
find "$LOG_DIR" -name "*.log.gz" -type f -exec mv {} "$ARCHIVE_DIR/" \;

echo "✅ Logs archived: $(ls $ARCHIVE_DIR/*.log.gz 2>/dev/null | wc -l) files"
EOF

chmod +x "$MONITORING_DIR/archive_logs.sh"
echo "  ✅ Created: $MONITORING_DIR/archive_logs.sh"
echo ""

# 3. Create health check monitoring script
echo "3️⃣  Creating health monitoring dashboard..."

cat > "$MONITORING_DIR/monitor_health.py" << 'EOF'
#!/usr/bin/env python3
"""
Continuous health monitoring for all 10 Zilla MCPs
Polls /health endpoint every 30 seconds and alerts on failures
"""
import os
import json
import time
from urllib import request, error
from datetime import datetime

ZILLAS = [
    ("qazilla", 7201),
    ("seczilla", 7202),
    ("archzilla", 7203),
    ("backzilla", 7204),
    ("frontzilla", 7205),
    ("opszilla", 7206),
    ("pozilla", 7207),
    ("productzilla", 7208),
    ("cross-zilla-validators", 7209),
    ("zilla-observatory", 7210),
]

LOG_DIR = os.path.expanduser("~/.platform/logs")
MONITORING_LOG = os.path.join(LOG_DIR, "monitoring.log")
ALERT_LOG = os.path.join(LOG_DIR, "alerts.log")

def log_message(level, message):
    timestamp = datetime.now().isoformat()
    log_entry = f"[{timestamp}] {level}: {message}"
    print(log_entry)
    with open(MONITORING_LOG, "a") as f:
        f.write(log_entry + "\n")

def check_health():
    """Check health of all Zillas"""
    healthy = []
    unhealthy = []

    for zilla_name, port in ZILLAS:
        url = f"http://localhost:{port}/health"
        try:
            with request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    healthy.append(zilla_name)
                else:
                    unhealthy.append((zilla_name, f"HTTP {response.status}"))
        except error.URLError as e:
            unhealthy.append((zilla_name, f"Connection refused"))
        except Exception as e:
            unhealthy.append((zilla_name, str(e)))

    return healthy, unhealthy

def alert(message):
    """Write alert to alert log"""
    timestamp = datetime.now().isoformat()
    alert_entry = f"[{timestamp}] ALERT: {message}"
    with open(ALERT_LOG, "a") as f:
        f.write(alert_entry + "\n")
    print(f"🚨 {message}")

def run_monitor(interval=30, duration=None):
    """
    Run continuous monitoring
    interval: seconds between health checks
    duration: total seconds to run (None = infinite)
    """
    start_time = time.time()
    check_count = 0
    alert_count = 0

    log_message("INFO", "Monitoring started")
    print(f"🔍 Monitoring {len(ZILLAS)} Zillas every {interval}s")
    print("Press Ctrl+C to stop\n")

    try:
        while True:
            check_count += 1
            healthy, unhealthy = check_health()

            timestamp = datetime.now().strftime("%H:%M:%S")
            status_line = f"[{timestamp}] Healthy: {len(healthy)}/10"

            if unhealthy:
                alert_count += 1
                unhealthy_names = ", ".join([name for name, _ in unhealthy])
                status_line += f" | Unhealthy: {unhealthy_names}"
                alert(f"Unhealthy servers: {unhealthy_names}")

            print(status_line)

            if duration and (time.time() - start_time) >= duration:
                break

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\n🛑 Monitoring stopped")

    # Print summary
    print(f"\n📊 Summary:")
    print(f"  Checks run:       {check_count}")
    print(f"  Alerts triggered: {alert_count}")
    print(f"  Duration:         {int(time.time() - start_time)}s")

    log_message("INFO", f"Monitoring stopped after {check_count} checks")

if __name__ == "__main__":
    import sys
    duration = None
    if len(sys.argv) > 1:
        try:
            duration = int(sys.argv[1])
            print(f"⏱️  Will run for {duration} seconds")
        except ValueError:
            print("Usage: monitor_health.py [duration_seconds]")
            sys.exit(1)

    run_monitor(interval=30, duration=duration)
EOF

chmod +x "$MONITORING_DIR/monitor_health.py"
echo "  ✅ Created: $MONITORING_DIR/monitor_health.py"
echo ""

# 4. Create metrics collector
echo "4️⃣  Creating metrics collector..."

cat > "$MONITORING_DIR/collect_metrics.sh" << 'EOF'
#!/bin/bash
# Collect performance metrics for all Zillas

METRICS_FILE="$HOME/.platform/logs/metrics.log"

echo "$(date '+%Y-%m-%d %H:%M:%S') --- Collecting Metrics ---" >> "$METRICS_FILE"

# Server memory and CPU usage
echo "Server Status:" >> "$METRICS_FILE"
ps aux | grep "_mcp.py" | grep -v grep | awk '{print $2, $6 "KB", $3 "%"}' >> "$METRICS_FILE"

# Open file descriptors
echo "File Descriptors:" >> "$METRICS_FILE"
for pid in $(ps aux | grep "_mcp.py" | grep -v grep | awk '{print $2}'); do
  if [ -d "/proc/$pid/fd" ]; then
    fd_count=$(ls -1 /proc/$pid/fd 2>/dev/null | wc -l)
    echo "PID $pid: $fd_count fds" >> "$METRICS_FILE"
  fi
done

# Database connections
echo "Database Connections:" >> "$METRICS_FILE"
netstat -an 2>/dev/null | grep "5432\|ESTABLISHED" | wc -l >> "$METRICS_FILE" || echo "N/A" >> "$METRICS_FILE"

echo "✅ Metrics collected to $METRICS_FILE"
EOF

chmod +x "$MONITORING_DIR/collect_metrics.sh"
echo "  ✅ Created: $MONITORING_DIR/collect_metrics.sh"
echo ""

# 5. Create alert rules
echo "5️⃣  Creating alert rules configuration..."

cat > "$MONITORING_DIR/alert_rules.json" << 'EOF'
{
  "rules": [
    {
      "name": "server_down",
      "condition": "health_check_failed",
      "threshold": 1,
      "action": "alert",
      "message": "Server is down!"
    },
    {
      "name": "high_latency",
      "condition": "latency > 100ms",
      "threshold": 5,
      "action": "warn",
      "message": "High latency detected"
    },
    {
      "name": "memory_leak",
      "condition": "memory_growth_rate > 10%/hour",
      "threshold": 3,
      "action": "alert",
      "message": "Potential memory leak detected"
    },
    {
      "name": "connection_pool_full",
      "condition": "active_connections >= pool_size",
      "threshold": 1,
      "action": "warn",
      "message": "Connection pool at capacity"
    }
  ],
  "alert_channels": [
    {
      "type": "log_file",
      "path": "~/.platform/logs/alerts.log"
    },
    {
      "type": "console",
      "enabled": true
    }
  ],
  "monitoring_interval_seconds": 30,
  "log_retention_days": 7
}
EOF

echo "  ✅ Created: $MONITORING_DIR/alert_rules.json"
echo ""

# 6. Create dashboard/summary script
echo "6️⃣  Creating monitoring dashboard..."

cat > "$MONITORING_DIR/show_status.sh" << 'EOF'
#!/bin/bash
# Show current status of all Zillas

LOG_DIR="$HOME/.platform/logs"

echo "📊 Zilla MCPs Status Dashboard"
echo "=============================="
echo ""

# Check running processes
echo "🔍 Running Servers:"
running=$(ps aux | grep "_mcp.py" | grep -v grep | wc -l)
echo "  Active: $running / 10"
echo ""

# Show recent log entries
echo "📝 Recent Log Activity (last 5 entries):"
for log in "$LOG_DIR"/*.log; do
  if [ -f "$log" ]; then
    name=$(basename "$log" .log)
    latest=$(tail -1 "$log" 2>/dev/null | cut -c1-80)
    echo "  $name: $latest"
  fi
done

echo ""

# Show disk usage
echo "💾 Log Storage Usage:"
if [ -d "$LOG_DIR" ]; then
  size=$(du -sh "$LOG_DIR" 2>/dev/null | cut -f1)
  echo "  Total: $size"
  echo "  Files: $(ls -1 "$LOG_DIR"/*.log 2>/dev/null | wc -l)"
fi

echo ""

# Show last alert (if any)
if [ -f "$LOG_DIR/alerts.log" ]; then
  echo "🚨 Last Alert:"
  tail -1 "$LOG_DIR/alerts.log"
else
  echo "✅ No alerts logged"
fi

echo ""

echo "📖 For detailed monitoring:"
echo "  tail -f $LOG_DIR/monitoring.log    (health checks)"
echo "  tail -f $LOG_DIR/alerts.log        (alerts)"
echo "  tail -f $LOG_DIR/metrics.log       (performance metrics)"
EOF

chmod +x "$MONITORING_DIR/show_status.sh"
echo "  ✅ Created: $MONITORING_DIR/show_status.sh"
echo ""

# 7. Create cron job template
echo "7️⃣  Creating cron job templates..."

cat > "$MONITORING_DIR/crontab-setup.txt" << 'EOF'
# Add these lines to your crontab (crontab -e) for automated monitoring:

# Archive logs daily at 2am
0 2 * * * $HOME/.platform/monitoring/archive_logs.sh >> $HOME/.platform/logs/cron.log 2>&1

# Collect metrics every hour
0 * * * * $HOME/.platform/monitoring/collect_metrics.sh >> $HOME/.platform/logs/cron.log 2>&1

# Health check monitoring (uncomment to enable)
# */5 * * * * cd $HOME/.platform/monitoring && python3 monitor_health.py 300

# Show status summary every morning
0 8 * * * $HOME/.platform/monitoring/show_status.sh >> $HOME/.platform/logs/summary.log 2>&1
EOF

echo "  ✅ Created: $MONITORING_DIR/crontab-setup.txt"
echo "  ℹ️  To use: cat crontab-setup.txt | crontab -"
echo ""

# 8. Summary
echo "=================================================="
echo "✅ Monitoring Setup Complete"
echo "=================================================="
echo ""
echo "📁 Monitoring Directory: $MONITORING_DIR"
echo ""
echo "🔧 Created Files:"
echo "  • archive_logs.sh        — Archive old logs"
echo "  • monitor_health.py      — Continuous health monitoring"
echo "  • collect_metrics.sh     — Performance metrics collection"
echo "  • show_status.sh         — Dashboard summary"
echo "  • alert_rules.json       — Alert configuration"
echo "  • crontab-setup.txt      — Cron job setup"
echo ""
echo "📖 Usage:"
echo ""
echo "  1. Quick status check:"
echo "     $MONITORING_DIR/show_status.sh"
echo ""
echo "  2. Start continuous monitoring (30s interval):"
echo "     python3 $MONITORING_DIR/monitor_health.py"
echo ""
echo "  3. Collect performance metrics:"
echo "     $MONITORING_DIR/collect_metrics.sh"
echo ""
echo "  4. Archive logs older than 7 days:"
echo "     $MONITORING_DIR/archive_logs.sh"
echo ""
echo "  5. Setup automated cron jobs:"
echo "     cat $MONITORING_DIR/crontab-setup.txt | crontab -"
echo ""
echo "📊 Log Files:"
echo "  • monitoring.log  — Health check history"
echo "  • alerts.log      — Alert events"
echo "  • metrics.log     — Performance metrics"
echo ""
echo "🔗 Next Steps:"
echo "  1. Run: ./show_status.sh"
echo "  2. Test: python3 monitor_health.py 60 (run for 60 seconds)"
echo "  3. Setup cron: cat crontab-setup.txt | crontab -"
echo ""
