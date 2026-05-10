#!/usr/bin/env python3
"""
Load Testing for MCP Staging Environment
Simulates 100 concurrent agents making 50 tool calls per second for 10 minutes
Target: P95 < 500ms, error rate < 1%, 99% success rate
Last Updated: 2026-05-09
"""

import asyncio
import json
import time
import sys
import random
from datetime import datetime
from typing import Dict, List, Any
from dataclasses import dataclass, asdict, field
import httpx
from collections import defaultdict

# Configuration
LOAD_TEST_CONFIG = {
    "duration_seconds": 600,  # 10 minutes
    "concurrent_agents": 100,
    "calls_per_agent_per_second": 0.5,  # 50 calls total per second across all agents
    "endpoints": [
        ("auth", "POST", "http://localhost:8001/login"),
        ("admin_users", "GET", "http://localhost:8002/users"),
        ("scheduler", "POST", "http://localhost:8005/tasks"),
        ("governance", "POST", "http://localhost:8003/validate"),
        ("config", "POST", "http://localhost:7099/get_env_config"),
    ]
}

@dataclass
class LoadTestMetric:
    """Individual request metric"""
    timestamp: float
    endpoint: str
    method: str
    status_code: int
    latency_ms: float
    success: bool
    error: str = None

@dataclass
class LoadTestSummary:
    """Load test summary"""
    start_time: str
    end_time: str
    duration_seconds: float
    total_requests: int
    successful_requests: int
    failed_requests: int
    success_rate_pct: float
    error_rate_pct: float
    latency_min_ms: float
    latency_max_ms: float
    latency_avg_ms: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    throughput_rps: float
    errors_by_type: Dict[str, int] = field(default_factory=dict)
    requests_by_endpoint: Dict[str, int] = field(default_factory=dict)
    verdict: str = "UNKNOWN"

class LoadTester:
    """Performs load testing"""

    def __init__(self):
        self.metrics: List[LoadTestMetric] = []
        self.start_time = None
        self.end_time = None
        self.errors_by_type = defaultdict(int)
        self.requests_by_endpoint = defaultdict(int)

    async def agent_worker(self, agent_id: int, duration: float, session: httpx.AsyncClient):
        """Simulate a single agent making requests"""
        agent_start = time.time()
        call_interval = 1.0 / LOAD_TEST_CONFIG["calls_per_agent_per_second"]

        while time.time() - agent_start < duration:
            # Pick random endpoint
            endpoint_name, method, url = random.choice(LOAD_TEST_CONFIG["endpoints"])

            # Make request
            metric = await self._make_request(session, method, url, endpoint_name)
            self.metrics.append(metric)
            self.requests_by_endpoint[endpoint_name] += 1

            # Wait before next call
            await asyncio.sleep(call_interval)

    async def _make_request(
        self,
        session: httpx.AsyncClient,
        method: str,
        url: str,
        endpoint_name: str
    ) -> LoadTestMetric:
        """Make single HTTP request and record metrics"""
        start = time.time()
        timestamp = start

        try:
            if method == "GET":
                response = await session.get(url, timeout=5.0)
            elif method == "POST":
                payload = {
                    "test": True,
                    "timestamp": timestamp
                }
                response = await session.post(url, json=payload, timeout=5.0)
            else:
                raise ValueError(f"Unknown method: {method}")

            latency = (time.time() - start) * 1000
            success = 200 <= response.status_code < 300

            return LoadTestMetric(
                timestamp=timestamp,
                endpoint=endpoint_name,
                method=method,
                status_code=response.status_code,
                latency_ms=latency,
                success=success,
                error=None if success else f"HTTP {response.status_code}"
            )

        except asyncio.TimeoutError:
            latency = (time.time() - start) * 1000
            self.errors_by_type["timeout"] += 1
            return LoadTestMetric(
                timestamp=timestamp,
                endpoint=endpoint_name,
                method=method,
                status_code=0,
                latency_ms=latency,
                success=False,
                error="Timeout"
            )

        except Exception as e:
            latency = (time.time() - start) * 1000
            error_type = type(e).__name__
            self.errors_by_type[error_type] += 1
            return LoadTestMetric(
                timestamp=timestamp,
                endpoint=endpoint_name,
                method=method,
                status_code=0,
                latency_ms=latency,
                success=False,
                error=str(e)
            )

    def calculate_summary(self) -> LoadTestSummary:
        """Calculate test summary"""
        if not self.metrics:
            return LoadTestSummary(
                start_time=datetime.now().isoformat(),
                end_time=datetime.now().isoformat(),
                duration_seconds=0,
                total_requests=0,
                successful_requests=0,
                failed_requests=0,
                success_rate_pct=0,
                error_rate_pct=0,
                latency_min_ms=0,
                latency_max_ms=0,
                latency_avg_ms=0,
                latency_p50_ms=0,
                latency_p95_ms=0,
                latency_p99_ms=0,
                throughput_rps=0,
            )

        latencies = [m.latency_ms for m in self.metrics]
        latencies_sorted = sorted(latencies)

        successful = sum(1 for m in self.metrics if m.success)
        failed = len(self.metrics) - successful

        duration = (self.end_time - self.start_time) if self.start_time and self.end_time else 0
        throughput = len(self.metrics) / max(duration, 1)

        summary = LoadTestSummary(
            start_time=datetime.fromtimestamp(self.start_time).isoformat(),
            end_time=datetime.fromtimestamp(self.end_time).isoformat(),
            duration_seconds=duration,
            total_requests=len(self.metrics),
            successful_requests=successful,
            failed_requests=failed,
            success_rate_pct=(successful / len(self.metrics) * 100) if self.metrics else 0,
            error_rate_pct=(failed / len(self.metrics) * 100) if self.metrics else 0,
            latency_min_ms=min(latencies),
            latency_max_ms=max(latencies),
            latency_avg_ms=sum(latencies) / len(latencies),
            latency_p50_ms=latencies_sorted[len(latencies_sorted) // 2],
            latency_p95_ms=latencies_sorted[int(len(latencies_sorted) * 0.95)],
            latency_p99_ms=latencies_sorted[int(len(latencies_sorted) * 0.99)],
            throughput_rps=throughput,
            errors_by_type=dict(self.errors_by_type),
            requests_by_endpoint=dict(self.requests_by_endpoint),
        )

        # Determine verdict
        p95_pass = summary.latency_p95_ms < 500
        success_rate_pass = summary.success_rate_pct >= 99.0
        error_rate_pass = summary.error_rate_pct < 1.0

        summary.verdict = "PASS" if (p95_pass and success_rate_pass and error_rate_pass) else "FAIL"

        return summary

    async def run(self) -> Dict[str, Any]:
        """Run load test"""
        print("=" * 70)
        print("MCP STAGING LOAD TEST")
        print("=" * 70)
        print(f"Configuration:")
        print(f"  Duration: {LOAD_TEST_CONFIG['duration_seconds']}s")
        print(f"  Concurrent Agents: {LOAD_TEST_CONFIG['concurrent_agents']}")
        print(f"  Total Throughput: ~{LOAD_TEST_CONFIG['concurrent_agents'] * LOAD_TEST_CONFIG['calls_per_agent_per_second']:.0f} req/sec")
        print(f"  Endpoints: {len(LOAD_TEST_CONFIG['endpoints'])}")
        print()

        self.start_time = time.time()

        # Run load test with progress tracking
        print("Starting agents...")

        async with httpx.AsyncClient(timeout=10.0) as session:
            tasks = [
                self.agent_worker(
                    i,
                    LOAD_TEST_CONFIG["duration_seconds"],
                    session
                )
                for i in range(LOAD_TEST_CONFIG["concurrent_agents"])
            ]

            # Run with progress output
            try:
                await asyncio.gather(*tasks)
            except Exception as e:
                print(f"Error during load test: {e}")

        self.end_time = time.time()

        # Calculate results
        summary = self.calculate_summary()

        # Print results
        print()
        print("=" * 70)
        print("LOAD TEST RESULTS")
        print("=" * 70)
        print()
        print("Request Summary:")
        print(f"  Total Requests: {summary.total_requests}")
        print(f"  Successful: {summary.successful_requests}")
        print(f"  Failed: {summary.failed_requests}")
        print(f"  Success Rate: {summary.success_rate_pct:.2f}%")
        print(f"  Error Rate: {summary.error_rate_pct:.2f}%")
        print(f"  Throughput: {summary.throughput_rps:.2f} req/sec")
        print()

        print("Latency Metrics (milliseconds):")
        print(f"  Min: {summary.latency_min_ms:.2f}ms")
        print(f"  Avg: {summary.latency_avg_ms:.2f}ms")
        print(f"  P50: {summary.latency_p50_ms:.2f}ms")
        print(f"  P95: {summary.latency_p95_ms:.2f}ms (Target: <500ms)")
        print(f"  P99: {summary.latency_p99_ms:.2f}ms")
        print(f"  Max: {summary.latency_max_ms:.2f}ms")
        print()

        print("Requests by Endpoint:")
        for endpoint, count in summary.requests_by_endpoint.items():
            print(f"  {endpoint}: {count}")
        print()

        if summary.errors_by_type:
            print("Errors by Type:")
            for error_type, count in summary.errors_by_type.items():
                print(f"  {error_type}: {count}")
            print()

        print("=" * 70)
        print(f"VERDICT: {summary.verdict}")
        print("=" * 70)
        print(f"  ✓ P95 < 500ms: {summary.latency_p95_ms < 500} ({summary.latency_p95_ms:.2f}ms)")
        print(f"  ✓ Success Rate ≥ 99%: {summary.success_rate_pct >= 99.0} ({summary.success_rate_pct:.2f}%)")
        print(f"  ✓ Error Rate < 1%: {summary.error_rate_pct < 1.0} ({summary.error_rate_pct:.2f}%)")
        print("=" * 70)

        return {
            "summary": asdict(summary),
            "metrics": [asdict(m) for m in self.metrics],
        }

async def main():
    """Main entry point"""
    tester = LoadTester()
    try:
        report = await tester.run()

        # Save report
        report_path = "/tmp/staging-load-test-report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

        print(f"\n✓ Report saved to: {report_path}")

        # Exit with appropriate code
        exit_code = 0 if report["summary"]["verdict"] == "PASS" else 1
        sys.exit(exit_code)

    except KeyboardInterrupt:
        print("\nLoad test interrupted by user")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
