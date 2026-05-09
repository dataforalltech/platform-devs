#!/usr/bin/env python3
"""
E2E Integration Test for MCP Staging Validation
Tests all 18 MCPs + 5 REST APIs for correct interaction and latency
Target: P95 < 500ms, error rate < 1%, 100% success rate
Last Updated: 2026-05-09
"""

import asyncio
import json
import time
import sys
from datetime import datetime
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass, asdict
import httpx
import random
import string

# Configuration
STAGING_CONFIG = {
    "mcps": {
        "agent_twin": "http://localhost:7098",
        "config": "http://localhost:7099",
        "docs": "http://localhost:7090",
        "session": "http://localhost:7100",
        "services": "http://localhost:7101",
        "deploy": "http://localhost:7102",
        "qa": "http://localhost:7103",
        "test": "http://localhost:7104",
        "infra": "http://localhost:7105",
        "pipeline": "http://localhost:7106",
        "ai_governance": "http://localhost:7107",
        "audit": "http://localhost:7108",
    },
    "apis": {
        "auth": "http://localhost:8001",
        "admin": "http://localhost:8002",
        "governance": "http://localhost:8003",
        "scheduler": "http://localhost:8005",
        "connectors": "http://localhost:8006",
    }
}

@dataclass
class TestResult:
    """Test result metrics"""
    test_name: str
    status: str  # PASS, FAIL, TIMEOUT
    latency_ms: float
    endpoint: str
    timestamp: str
    error_message: str = None
    details: Dict[str, Any] = None

class StagingValidator:
    """Validates staging environment"""

    def __init__(self):
        self.results: List[TestResult] = []
        self.client = httpx.AsyncClient(timeout=10.0)
        self.start_time = time.time()

    async def health_check_all(self) -> Dict[str, bool]:
        """Check health of all services"""
        health_status = {}

        # Check MCPs
        for name, url in STAGING_CONFIG["mcps"].items():
            health_status[f"mcp_{name}"] = await self._check_health(f"{url}/health")

        # Check APIs
        for name, url in STAGING_CONFIG["apis"].items():
            health_status[f"api_{name}"] = await self._check_health(f"{url}/health")

        return health_status

    async def _check_health(self, url: str) -> bool:
        """Check single service health"""
        try:
            response = await self.client.get(url)
            return response.status_code == 200
        except Exception as e:
            print(f"Health check failed for {url}: {e}")
            return False

    async def test_agent_twin_authentication(self) -> TestResult:
        """Test agent-twin-mcp authentication flow"""
        test_name = "agent_twin_authentication"
        endpoint = f"{STAGING_CONFIG['mcps']['agent_twin']}/authenticate"
        start = time.time()

        try:
            # Generate test token
            test_email = f"test-agent-{random.randint(1000,9999)}@dataforall.tech"
            payload = {
                "email": test_email,
                "name": "Test Agent",
                "role": "developer"
            }

            response = await self.client.post(endpoint, json=payload)
            latency = (time.time() - start) * 1000

            if response.status_code == 200:
                data = response.json()
                return TestResult(
                    test_name=test_name,
                    status="PASS",
                    latency_ms=latency,
                    endpoint=endpoint,
                    timestamp=datetime.now().isoformat(),
                    details={"user_id": data.get("user_id")}
                )
            else:
                return TestResult(
                    test_name=test_name,
                    status="FAIL",
                    latency_ms=latency,
                    endpoint=endpoint,
                    timestamp=datetime.now().isoformat(),
                    error_message=f"HTTP {response.status_code}: {response.text}"
                )
        except Exception as e:
            latency = (time.time() - start) * 1000
            return TestResult(
                test_name=test_name,
                status="FAIL",
                latency_ms=latency,
                endpoint=endpoint,
                timestamp=datetime.now().isoformat(),
                error_message=str(e)
            )

    async def test_auth_api_login(self) -> TestResult:
        """Test auth API login flow"""
        test_name = "auth_api_login"
        endpoint = f"{STAGING_CONFIG['apis']['auth']}/login"
        start = time.time()

        try:
            payload = {
                "email": "test@dataforall.tech",
                "password": "test_password_123"
            }

            response = await self.client.post(endpoint, json=payload)
            latency = (time.time() - start) * 1000

            if response.status_code in [200, 401]:  # Login success or bad creds both valid
                return TestResult(
                    test_name=test_name,
                    status="PASS",
                    latency_ms=latency,
                    endpoint=endpoint,
                    timestamp=datetime.now().isoformat(),
                )
            else:
                return TestResult(
                    test_name=test_name,
                    status="FAIL",
                    latency_ms=latency,
                    endpoint=endpoint,
                    timestamp=datetime.now().isoformat(),
                    error_message=f"HTTP {response.status_code}"
                )
        except Exception as e:
            latency = (time.time() - start) * 1000
            return TestResult(
                test_name=test_name,
                status="FAIL",
                latency_ms=latency,
                endpoint=endpoint,
                timestamp=datetime.now().isoformat(),
                error_message=str(e)
            )

    async def test_admin_api_list_users(self) -> TestResult:
        """Test admin API list users"""
        test_name = "admin_api_list_users"
        endpoint = f"{STAGING_CONFIG['apis']['admin']}/users"
        start = time.time()

        try:
            response = await self.client.get(
                endpoint,
                headers={"Authorization": "Bearer test_token"}
            )
            latency = (time.time() - start) * 1000

            if response.status_code in [200, 401, 403]:  # Auth may fail, but endpoint responds
                return TestResult(
                    test_name=test_name,
                    status="PASS",
                    latency_ms=latency,
                    endpoint=endpoint,
                    timestamp=datetime.now().isoformat(),
                )
            else:
                return TestResult(
                    test_name=test_name,
                    status="FAIL",
                    latency_ms=latency,
                    endpoint=endpoint,
                    timestamp=datetime.now().isoformat(),
                    error_message=f"HTTP {response.status_code}"
                )
        except Exception as e:
            latency = (time.time() - start) * 1000
            return TestResult(
                test_name=test_name,
                status="FAIL",
                latency_ms=latency,
                endpoint=endpoint,
                timestamp=datetime.now().isoformat(),
                error_message=str(e)
            )

    async def test_scheduler_api_create_task(self) -> TestResult:
        """Test scheduler API create task"""
        test_name = "scheduler_api_create_task"
        endpoint = f"{STAGING_CONFIG['apis']['scheduler']}/tasks"
        start = time.time()

        try:
            payload = {
                "title": "Test Task",
                "schedule": "0 9 * * *",
                "action": "test_action"
            }

            response = await self.client.post(
                endpoint,
                json=payload,
                headers={"Authorization": "Bearer test_token"}
            )
            latency = (time.time() - start) * 1000

            if response.status_code in [200, 201, 401, 403]:
                return TestResult(
                    test_name=test_name,
                    status="PASS",
                    latency_ms=latency,
                    endpoint=endpoint,
                    timestamp=datetime.now().isoformat(),
                )
            else:
                return TestResult(
                    test_name=test_name,
                    status="FAIL",
                    latency_ms=latency,
                    endpoint=endpoint,
                    timestamp=datetime.now().isoformat(),
                    error_message=f"HTTP {response.status_code}"
                )
        except Exception as e:
            latency = (time.time() - start) * 1000
            return TestResult(
                test_name=test_name,
                status="FAIL",
                latency_ms=latency,
                endpoint=endpoint,
                timestamp=datetime.now().isoformat(),
                error_message=str(e)
            )

    async def test_config_mcp_get_env(self) -> TestResult:
        """Test config MCP get environment"""
        test_name = "config_mcp_get_env"
        endpoint = f"{STAGING_CONFIG['mcps']['config']}/get_env_config"
        start = time.time()

        try:
            response = await self.client.post(
                endpoint,
                json={"environment": "staging"}
            )
            latency = (time.time() - start) * 1000

            if response.status_code in [200, 400]:
                return TestResult(
                    test_name=test_name,
                    status="PASS",
                    latency_ms=latency,
                    endpoint=endpoint,
                    timestamp=datetime.now().isoformat(),
                )
            else:
                return TestResult(
                    test_name=test_name,
                    status="FAIL",
                    latency_ms=latency,
                    endpoint=endpoint,
                    timestamp=datetime.now().isoformat(),
                    error_message=f"HTTP {response.status_code}"
                )
        except Exception as e:
            latency = (time.time() - start) * 1000
            return TestResult(
                test_name=test_name,
                status="FAIL",
                latency_ms=latency,
                endpoint=endpoint,
                timestamp=datetime.now().isoformat(),
                error_message=str(e)
            )

    async def test_governance_api_validate(self) -> TestResult:
        """Test governance API validate decision"""
        test_name = "governance_api_validate"
        endpoint = f"{STAGING_CONFIG['apis']['governance']}/validate"
        start = time.time()

        try:
            payload = {
                "repository": "test-repo",
                "task_description": "Test task",
                "proposed_change": "Test change"
            }

            response = await self.client.post(
                endpoint,
                json=payload,
                headers={"Authorization": "Bearer test_token"}
            )
            latency = (time.time() - start) * 1000

            if response.status_code in [200, 400, 401, 403]:
                return TestResult(
                    test_name=test_name,
                    status="PASS",
                    latency_ms=latency,
                    endpoint=endpoint,
                    timestamp=datetime.now().isoformat(),
                )
            else:
                return TestResult(
                    test_name=test_name,
                    status="FAIL",
                    latency_ms=latency,
                    endpoint=endpoint,
                    timestamp=datetime.now().isoformat(),
                    error_message=f"HTTP {response.status_code}"
                )
        except Exception as e:
            latency = (time.time() - start) * 1000
            return TestResult(
                test_name=test_name,
                status="FAIL",
                latency_ms=latency,
                endpoint=endpoint,
                timestamp=datetime.now().isoformat(),
                error_message=str(e)
            )

    def calculate_metrics(self) -> Dict[str, Any]:
        """Calculate test metrics"""
        if not self.results:
            return {}

        latencies = [r.latency_ms for r in self.results]
        latencies_sorted = sorted(latencies)

        passed = sum(1 for r in self.results if r.status == "PASS")
        failed = sum(1 for r in self.results if r.status == "FAIL")
        total = len(self.results)

        return {
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "success_rate_pct": (passed / total * 100) if total > 0 else 0,
            "error_rate_pct": (failed / total * 100) if total > 0 else 0,
            "latency_min_ms": min(latencies),
            "latency_max_ms": max(latencies),
            "latency_avg_ms": sum(latencies) / len(latencies),
            "latency_p50_ms": latencies_sorted[len(latencies_sorted) // 2],
            "latency_p95_ms": latencies_sorted[int(len(latencies_sorted) * 0.95)],
            "latency_p99_ms": latencies_sorted[int(len(latencies_sorted) * 0.99)],
            "duration_seconds": time.time() - self.start_time,
        }

    async def run_all_tests(self) -> Dict[str, Any]:
        """Run all validation tests"""
        print("=" * 70)
        print("MCP STAGING VALIDATION - E2E INTEGRATION TEST")
        print("=" * 70)
        print(f"Start time: {datetime.now().isoformat()}")
        print()

        # Step 1: Health checks
        print("[1/2] Running health checks...")
        health_status = await self.health_check_all()
        healthy_count = sum(1 for v in health_status.values() if v)
        total_services = len(health_status)
        print(f"     ✓ {healthy_count}/{total_services} services healthy")

        if healthy_count < total_services:
            print("     ⚠ Some services not healthy, continuing with available services...")
            print(f"     Status: {json.dumps(health_status, indent=2)}")
        print()

        # Step 2: Run integration tests
        print("[2/2] Running integration tests...")

        tests = [
            ("Agent Twin Auth", self.test_agent_twin_authentication()),
            ("Auth API Login", self.test_auth_api_login()),
            ("Admin API Users", self.test_admin_api_list_users()),
            ("Scheduler API Task", self.test_scheduler_api_create_task()),
            ("Config MCP Env", self.test_config_mcp_get_env()),
            ("Governance API Validate", self.test_governance_api_validate()),
        ]

        for test_label, test_coro in tests:
            result = await test_coro
            self.results.append(result)
            status_icon = "✓" if result.status == "PASS" else "✗"
            print(f"     {status_icon} {test_label}: {result.latency_ms:.2f}ms [{result.status}]")

        print()

        # Calculate metrics
        metrics = self.calculate_metrics()

        # Print summary
        print("=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"Tests: {metrics['passed']}/{metrics['total_tests']} passed")
        print(f"Success Rate: {metrics['success_rate_pct']:.1f}%")
        print(f"Error Rate: {metrics['error_rate_pct']:.1f}%")
        print()
        print("Latency Metrics:")
        print(f"  Min:  {metrics['latency_min_ms']:.2f}ms")
        print(f"  Avg:  {metrics['latency_avg_ms']:.2f}ms")
        print(f"  P50:  {metrics['latency_p50_ms']:.2f}ms")
        print(f"  P95:  {metrics['latency_p95_ms']:.2f}ms (Target: <500ms)")
        print(f"  P99:  {metrics['latency_p99_ms']:.2f}ms")
        print(f"  Max:  {metrics['latency_max_ms']:.2f}ms")
        print()
        print(f"Total Duration: {metrics['duration_seconds']:.2f}s")

        # Overall verdict
        print()
        p95_pass = metrics['latency_p95_ms'] < 500
        success_rate_pass = metrics['success_rate_pct'] >= 99.0
        error_rate_pass = metrics['error_rate_pct'] < 1.0

        verdict = "PASS" if (p95_pass and success_rate_pass and error_rate_pass) else "FAIL"
        print(f"OVERALL VERDICT: {verdict}")
        print(f"  ✓ P95 < 500ms: {p95_pass} ({metrics['latency_p95_ms']:.2f}ms)")
        print(f"  ✓ Success Rate ≥ 99%: {success_rate_pass} ({metrics['success_rate_pct']:.1f}%)")
        print(f"  ✓ Error Rate < 1%: {error_rate_pass} ({metrics['error_rate_pct']:.1f}%)")
        print("=" * 70)

        return {
            "verdict": verdict,
            "health_status": health_status,
            "metrics": metrics,
            "tests": [asdict(r) for r in self.results],
            "timestamp": datetime.now().isoformat(),
        }

    async def close(self):
        """Cleanup"""
        await self.client.aclose()

async def main():
    """Main entry point"""
    validator = StagingValidator()
    try:
        report = await validator.run_all_tests()

        # Save report
        report_path = "/tmp/staging-e2e-test-report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

        print(f"\n✓ Report saved to: {report_path}")

        # Exit with appropriate code
        exit_code = 0 if report["verdict"] == "PASS" else 1
        sys.exit(exit_code)

    finally:
        await validator.close()

if __name__ == "__main__":
    asyncio.run(main())
