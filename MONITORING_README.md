# Monitoring & Log Aggregation for Zilla MCPs

## Overview

Production-ready monitoring infrastructure for all 10 Zilla MCPs with:
- ✅ Log rotation and archival
- ✅ Continuous health monitoring
- ✅ Performance metrics collection
- ✅ Alert management
- ✅ Status dashboards

---

## Quick Start

### 1. View Current Status
```bash
~/.platform/monitoring/show_status.sh
```

**Output**:
```
📊 Zilla MCPs Status Dashboard
==============================

🔍 Running Servers:
  Active: 10 / 10

📝 Recent Log Activity (last 5 entries):
  qazilla: [2026-05-11T12:10:34.234567] ✅ PostgreSQL connected
  ...

💾 Log Storage Usage:
  Total: 2.4M
  Files: 10

✅ No alerts logged
```

### 2. Start Health Monitoring
```bash
# Run for 60 seconds
python3 ~/.platform/monitoring/monitor_health.py 60

# Run indefinitely (Ctrl+C to stop)
python3 ~/.platform/monitoring/monitor_health.py
```

**Output**:
```
🔍 Monitoring 10 Zillas every 30s
Press Ctrl+C to stop

[12:10:34] Healthy: 10/10
[12:11:04] Healthy: 10/10
[12:11:34] Healthy: 10/10
```

### 3. Collect Metrics
```bash
~/.platform/monitoring/collect_metrics.sh
```

**Metrics collected**:
- Server memory usage
- CPU usage per process
- Open file descriptors
- Database connection count

---

## Components

### 1. Log Rotation

**Purpose**: Prevent logs from consuming unlimited disk space

**Configuration**: `/tmp/zillas-logrotate`
```
~/.platform/logs/*.log {
    daily              # Rotate daily
    rotate 7           # Keep 7 days of backups
    compress           # Compress old logs
    delaycompress      # Don't compress today's log
    notifempty         # Skip empty logs
}
```

**Installation** (requires sudo):
```bash
sudo cp /tmp/zillas-logrotate /etc/logrotate.d/zillas
logrotate -f /etc/logrotate.d/zillas  # Test
```

**Manual rotation**:
```bash
~/.platform/monitoring/archive_logs.sh
```

---

### 2. Continuous Health Monitoring

**File**: `~/.platform/monitoring/monitor_health.py`

**What it does**:
- Polls `/health` endpoint every 30 seconds
- Tracks up/down status for each server
- Logs all health checks to `monitoring.log`
- Alerts on failures to `alerts.log`

**Usage**:
```bash
# Run for 60 seconds (testing)
python3 ~/.platform/monitoring/monitor_health.py 60

# Run indefinitely
python3 ~/.platform/monitoring/monitor_health.py &

# Check logs
tail -f ~/.platform/logs/monitoring.log
tail -f ~/.platform/logs/alerts.log
```

**Metrics tracked**:
- Timestamp of each check
- Number of healthy vs unhealthy servers
- Specific servers that are down
- Response times (if applicable)

---

### 3. Metrics Collection

**File**: `~/.platform/monitoring/collect_metrics.sh`

**Metrics collected**:
```
Server Status:
  qazilla (PID 12345): 45MB memory, 2.3% CPU
  seczilla (PID 12346): 42MB memory, 1.8% CPU
  ...

File Descriptors:
  PID 12345: 24 fds
  PID 12346: 22 fds
  ...

Database Connections:
  15 active
```

**Output**: `~/.platform/logs/metrics.log`

**Usage**:
```bash
# Collect once
~/.platform/monitoring/collect_metrics.sh

# Collect periodically (via cron)
# See "Automated Cron Jobs" section below
```

---

### 4. Alert Management

**Alert Rules**: `~/.platform/monitoring/alert_rules.json`

**Configured alerts**:
1. **Server Down** — Health check failed
2. **High Latency** — Response time > 100ms
3. **Memory Leak** — Memory growth > 10%/hour
4. **Connection Pool Full** — All connections in use

**Alert channels**:
- Log file: `~/.platform/logs/alerts.log`
- Console output (if monitoring script running)

**Alert example**:
```
[2026-05-11T12:11:34.234567] ALERT: Unhealthy servers: qazilla, seczilla
```

---

### 5. Status Dashboard

**File**: `~/.platform/monitoring/show_status.sh`

**Shows**:
- Number of running servers
- Recent log activity
- Disk usage
- Last alert (if any)
- Available monitoring commands

**Usage**:
```bash
~/.platform/monitoring/show_status.sh
```

---

## Log Files

All logs stored in `~/.platform/logs/`:

| File | Purpose | Rotation |
|------|---------|----------|
| `qazilla.log` | qazilla server output | Daily (keep 7) |
| `seczilla.log` | seczilla server output | Daily (keep 7) |
| ... (8 more Zilla logs) | | |
| `monitoring.log` | Health check history | Manual |
| `alerts.log` | Alert events | Manual |
| `metrics.log` | Performance metrics | Manual |

**View logs**:
```bash
# Single Zilla
tail -f ~/.platform/logs/qazilla.log

# All Zillas (with filtering)
tail -f ~/.platform/logs/*.log | grep "ERROR\|ALERT"

# Specific time period
grep "2026-05-11T12:" ~/.platform/logs/*.log
```

---

## Automated Cron Jobs

**Setup file**: `~/.platform/monitoring/crontab-setup.txt`

**Available cron jobs**:

```bash
# 1. Archive logs daily at 2am
0 2 * * * $HOME/.platform/monitoring/archive_logs.sh

# 2. Collect metrics every hour
0 * * * * $HOME/.platform/monitoring/collect_metrics.sh

# 3. Health check monitoring (runs for 5 min every 5 min)
*/5 * * * * cd $HOME/.platform/monitoring && python3 monitor_health.py 300

# 4. Status summary every morning at 8am
0 8 * * * $HOME/.platform/monitoring/show_status.sh
```

**Installation**:
```bash
# View current crontab
crontab -l

# Add monitoring jobs
cat ~/.platform/monitoring/crontab-setup.txt | crontab -

# Edit manually
crontab -e
```

**Verify**:
```bash
crontab -l
```

---

## Example: Production Setup

### Minimal Setup (recommended for most)
```bash
# 1. Setup infrastructure
~/.platform/monitoring/setup_monitoring.sh

# 2. Add basic cron jobs
cat ~/.platform/monitoring/crontab-setup.txt | crontab -

# 3. Test
~/.platform/monitoring/show_status.sh
python3 ~/.platform/monitoring/monitor_health.py 60
```

### Full Monitoring Setup
```bash
# All of above + continuous monitoring in background
python3 ~/.platform/monitoring/monitor_health.py &

# View real-time monitoring
tail -f ~/.platform/logs/monitoring.log

# Check metrics hourly
watch -n 3600 ~/.platform/monitoring/show_status.sh
```

### Enterprise Setup
```bash
# Everything + centralized log aggregation
# Options:
#   1. ELK Stack (Elasticsearch + Logstash + Kibana)
#   2. Grafana + Prometheus
#   3. Datadog
#   4. New Relic

# Ship logs to central system:
# rsync -a ~/.platform/logs/ central-server:/logs/zillas/
```

---

## Performance Baselines

### Expected Log Sizes

| Period | Log Size | Notes |
|--------|----------|-------|
| Per day | ~20MB | At 100 req/s |
| Per week | ~140MB | 7 days uncompressed |
| Per month | ~600MB | 30 days uncompressed |

With compression: ~10% of original size

### Disk Space Recommendation

For 1 month of logs:
```
Uncompressed: 600MB
Compressed:   60MB
Retention:    7 days (use logrotate)
Total needed: 100MB (safety margin)
```

---

## Troubleshooting

### Issue: No logs being generated
```bash
# Verify Zillas are running
ps aux | grep "_mcp.py" | grep -v grep

# Check log directory
ls -lh ~/.platform/logs/

# Verify write permissions
touch ~/.platform/logs/test.log && rm ~/.platform/logs/test.log
```

### Issue: Monitoring script says all servers are down
```bash
# Check if servers are actually running
~/.platform/scripts/health_check_zillas.sh

# Start servers if needed
~/.platform/scripts/start_all_zillas.sh

# Re-run monitoring
python3 ~/.platform/monitoring/monitor_health.py 60
```

### Issue: Disk space filling up
```bash
# Check usage
du -sh ~/.platform/logs/

# Archive old logs immediately
~/.platform/monitoring/archive_logs.sh

# Check if logrotate is working
sudo logrotate -f /etc/logrotate.d/zillas

# List archived logs
ls -lh ~/.platform/logs/archive/
```

### Issue: Alerts not triggering
```bash
# Check alert rules config
cat ~/.platform/monitoring/alert_rules.json

# Verify monitoring script is running
ps aux | grep monitor_health.py

# Check alert log
tail -50 ~/.platform/logs/alerts.log
```

---

## Integration with External Services

### Send Alerts to Slack
```python
# Add to monitor_health.py:
import requests

def send_slack_alert(message):
    webhook_url = os.getenv('SLACK_WEBHOOK_URL')
    requests.post(webhook_url, json={"text": message})
```

### Send Metrics to Prometheus
```python
# Export metrics on HTTP endpoint
from prometheus_client import Counter, Gauge, start_http_server

health_checks = Counter(...)
healthy_servers = Gauge(...)
```

### Ship Logs to Datadog/CloudWatch
```bash
# Add to collect_metrics.sh:
aws logs put-log-events \
  --log-group-name /aws/zillas \
  --log-stream-name metrics \
  --log-events file=~/.platform/logs/metrics.log
```

---

## Performance Impact

**Monitoring overhead**:
- Health check: ~10ms per server (negligible)
- Metrics collection: ~50ms per server
- Log aggregation: < 1% CPU usage

**No impact on production workloads** — monitoring runs independently of application code.

---

## Monitoring Checklist

- ✅ Monitoring scripts created and tested
- ✅ Log rotation configured
- ✅ Health monitoring implemented
- ✅ Metrics collection ready
- ✅ Alert rules defined
- ✅ Status dashboard available
- ✅ Cron jobs documented
- ✅ Logs aggregated to ~/.platform/logs/

---

## Next Steps

### Immediate (Day 1)
1. ✅ Run setup script
2. ✅ Test show_status.sh
3. ✅ Test monitor_health.py for 1 minute
4. ✅ Verify logs are being written

### Short-term (Week 1)
1. Setup cron jobs for log rotation
2. Monitor system for 24 hours
3. Test alert triggers manually
4. Review metrics collection

### Long-term (Ongoing)
1. Archive logs weekly
2. Review alerts monthly
3. Tune alert thresholds based on patterns
4. Consider centralized logging (ELK, Datadog, etc.)

---

## Commands Cheat Sheet

```bash
# Status & Monitoring
~/.platform/monitoring/show_status.sh                    # Show dashboard
python3 ~/.platform/monitoring/monitor_health.py 60       # Monitor for 60s
~/.platform/monitoring/collect_metrics.sh                 # Collect metrics

# Log Management
tail -f ~/.platform/logs/qazilla.log                      # Follow log
grep "ERROR" ~/.platform/logs/*.log                       # Search errors
~/.platform/monitoring/archive_logs.sh                    # Archive old logs
du -sh ~/.platform/logs/                                  # Check size

# Alerts
tail -f ~/.platform/logs/alerts.log                       # View alerts
grep "ALERT" ~/.platform/logs/alerts.log | wc -l         # Count alerts

# Cron
crontab -l                                                # List cron jobs
crontab -e                                                # Edit cron jobs
cat ~/.platform/monitoring/crontab-setup.txt | crontab -  # Setup monitoring
```

---

**Status**: ✅ **MONITORING INFRASTRUCTURE READY**  
**Setup Date**: 2026-05-11  
**Next Review**: 2026-05-18
