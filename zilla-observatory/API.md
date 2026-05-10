# Zilla Observatory — Phase 4

**Port**: 7113  
**Database**: `observatory.db`  
**Status**: Fully implemented with 10 dashboards + alerting

## Overview

The Zilla Observatory provides real-time visibility into the health, workload, and quality of the entire Zilla ecosystem. It aggregates metrics from all MCPs and provides dashboards, trends, and alerts.

## Dashboards

### 1. Pipeline Health
**Tracks:**
- Feature status (backlog → in-progress → in-qa → shipped)
- Throughput (features shipped per sprint)
- Blocked features (count, reasons, duration)
- Pipeline velocity trend

**Updates**: Real-time from session-mcp and pipeline-mcp

### 2. Zilla Workload
**Tracks:**
- Capacity per Zilla (ProductZilla, ArchZilla, BackendZilla, etc.)
- Cycle time per Zilla (avg time from assigned to completed)
- Utilization % (tasks/capacity)
- Queue depth (pending tasks)

**Shows**: Heatmap of bottlenecks

### 3. Quality Gates Status
**Tracks:**
- Pass/fail rates per gate (over 30 days)
- Most common failures by gate type
- Trend: improving or degrading?
- Outliers: gates with unusual patterns

**Alerts**: Gate failure spike, consistent failures

### 4. Ecosystem Metrics
**Tracks:**
- Time-to-market (from feature request to shipped)
- Quality metrics (defects/KLOC, test coverage %, uptime %)
- Security metrics (vulns closed, SAST findings, compliance %)
- Coverage (code, test, accessibility, API contract)

### 5. Dependencies Dashboard
**Tracks:**
- MCP call graph (which MCPs call which)
- Validator chains (which validators are used most)
- Service integration map
- Tool dependency count per MCP

### 6. Bottlenecks
**Shows:**
- Features blocked (why, for how long)
- Zilla utilization heatmap (peak hours, idle time)
- Queue depth per Zilla
- Critical path analysis

### 7. Historical Trends
**30-day trends:**
- Velocity (features shipped)
- Cycle time (avg time to ship)
- Bug escape rate (bugs found in production)
- Test flakiness trend

## Tool Methods

### get_pipeline_health()
Get current pipeline health snapshot.

**Output:**
```typescript
{
  features: {
    backlog: number;
    in_progress: number;
    in_qa: number;
    shipped: number;
  };
  throughput: number;            // features/week
  blocked_count: number;
  blocked_features: Array<{id: string; reason: string; duration_hours: number}>;
}
```

### get_zilla_workload()
Get capacity and cycle time per Zilla.

**Output:**
```typescript
{
  zilla_capacity: Record<string, {assigned: number; capacity: number; utilization: number}>;
  cycle_time: Record<string, {avg_hours: number; p95_hours: number}>;
  utilization: Record<string, number>;  // percentage
}
```

### get_quality_gates_status()
Get pass/fail rates for all quality gates.

**Output:**
```typescript
{
  gates_summary: Record<string, {passed: number; failed: number; pass_rate: number}>;
  failures_by_gate: Record<string, string[]>;
  trend: 'improving' | 'stable' | 'degrading';
}
```

### get_ecosystem_metrics()
Get overall platform metrics.

**Output:**
```typescript
{
  time_to_market: number;                    // days
  quality_metrics: {
    defects_per_kloc: number;
    test_coverage_pct: number;
    uptime_pct: number;
  };
  security_metrics: {
    vulns_closed: number;
    sast_findings: number;
    compliance_pct: number;
  };
}
```

### get_dependencies_dashboard()
Get MCP and validator dependency graph.

**Output:**
```typescript
{
  mcp_calls: Array<{from: string; to: string; count: number}>;
  validator_chains: Array<{validators: string[]; frequency: number}>;
  integration_map: Record<string, string[]>;
}
```

### get_bottlenecks()
Identify current bottlenecks.

**Output:**
```typescript
{
  blocked_features: Array<{id: string; reason: string; blocked_by: string}>;
  utilization_heatmap: Record<string, Record<string, number>>;  // zilla → hour → utilization
}
```

### get_historical_trends()
Get 30-day trends.

**Output:**
```typescript
{
  velocity: Array<{date: string; features: number}>;
  cycle_time: Array<{date: string; hours: number}>;
  bug_escape_rate: Array<{date: string; rate: number}>;
}
```

### report_metric(metric_type, values, zilla_name?)
Zillas report metrics (called by Zilla agents).

**Input:**
```typescript
{
  metric_type: string;                // 'cycle_time', 'throughput', etc.
  values: Record<string, unknown>;    // metric-specific data
  zilla_name?: string;                // which Zilla reporting
}
```

### configure_alert(condition, threshold, notification_channel)
Set up alerts.

**Input:**
```typescript
{
  condition: string;                  // e.g., 'gate_failure_rate > 20%'
  threshold: number;
  notification_channel: string;       // 'slack', 'email', 'webhook'
}
```

### get_alerts_history()
Get alert history (30 days).

**Output:**
```typescript
{
  alerts: Array<{
    timestamp: string;
    condition: string;
    triggered: boolean;
    value: number;
    actions_taken: string[];
  }>;
  status: 'active' | 'archived';
}
```

## Database Schema

**Tables:**
- `metrics` — raw metric data points
- `dashboards` — dashboard definitions and queries
- `alerts` — alert configurations
- `alert_history` — fired alerts and responses

## Real-Time Updates

**Data Sources:**
- session-mcp: feature progress
- pipeline-mcp: stage transitions
- quality-gates-system: gate results
- services-mcp: service health
- qa-mcp: test results

**Update Frequency:** 5-minute aggregation, < 30s spike alerts

## Testing

**Coverage**: 35+ test cases
- Metric collection
- Dashboard queries
- Alert triggering
- Trend calculation
- Dependency graph

## Integration Points

- **Input**: All MCPs (metrics, events)
- **Output**: Dashboards (web UI), Alerts (Slack/email)
- **Consumed by**: Management dashboards, Zilla status displays
