from __future__ import annotations

import time
from typing import Any

import httpx


def run_api_tests(
    store: Any,
    settings: Any,
    *,
    base_url: str,
    endpoints: list[dict],
    timeout: float | None = None,
) -> dict:
    """
    Testa endpoints HTTP. Cada item em endpoints:
    {
      "path": "/api/users",
      "method": "GET",
      "headers": {},
      "body": {},
      "expect_status": 200,
      "expect_keys": ["id", "name"]
    }
    """
    if not base_url:
        return {
            "error": "ValidationError",
            "details": "base_url is required",
            "tool": "run_api_tests",
        }
    if not endpoints:
        return {
            "error": "ValidationError",
            "details": "endpoints list is required and cannot be empty",
            "tool": "run_api_tests",
        }

    http_timeout = timeout if timeout is not None else settings.http_timeout
    results: list[dict[str, Any]] = []
    total_passed = 0
    total_failed = 0

    with httpx.Client(base_url=base_url, timeout=http_timeout) as client:
        for ep in endpoints:
            path = ep.get("path", "/")
            method = ep.get("method", "GET").upper()
            headers = ep.get("headers") or {}
            body = ep.get("body")
            expect_status = ep.get("expect_status", 200)
            expect_keys: list[str] = ep.get("expect_keys") or []

            t0 = time.monotonic()
            failure_reason: str | None = None
            status_code: int = -1
            passed = False

            try:
                resp = client.request(
                    method=method,
                    url=path,
                    headers=headers,
                    json=body if body is not None else None,
                )
                status_code = resp.status_code
                response_ms = int((time.monotonic() - t0) * 1000)

                if status_code != expect_status:
                    failure_reason = (
                        f"expected status {expect_status}, got {status_code}"
                    )
                elif expect_keys:
                    try:
                        resp_json = resp.json()
                        missing = [k for k in expect_keys if k not in resp_json]
                        if missing:
                            failure_reason = f"missing keys in response: {missing}"
                    except Exception:  # noqa: BLE001
                        failure_reason = "response is not valid JSON"

                passed = failure_reason is None

            except httpx.TimeoutException:
                response_ms = int((time.monotonic() - t0) * 1000)
                failure_reason = "request timed out"
            except Exception as exc:  # noqa: BLE001
                response_ms = int((time.monotonic() - t0) * 1000)
                failure_reason = f"request error: {exc}"

            if passed:
                total_passed += 1
            else:
                total_failed += 1

            results.append(
                {
                    "path": path,
                    "method": method,
                    "status_code": status_code,
                    "response_ms": response_ms,
                    "passed": passed,
                    "failure_reason": failure_reason,
                }
            )

    run_id = store.save_run(
        run_type="api",
        status="passed" if total_failed == 0 else "failed",
        summary={"total": len(endpoints), "passed": total_passed, "failed": total_failed},
        details={"results": results[:20]},
        repo_path=base_url,
    )

    return {
        "total": len(endpoints),
        "passed": total_passed,
        "failed": total_failed,
        "results": results,
        "run_id": run_id,
    }


def generate_test_matrix(
    store: Any,
    settings: Any,
    *,
    base_url: str,
    scenarios: list[dict],
) -> dict:
    """
    Gera a matriz de testes: cada (cenário × payload) é um caso de teste.
    """
    if not base_url:
        return {
            "error": "ValidationError",
            "details": "base_url is required",
            "tool": "generate_test_matrix",
        }
    if not scenarios:
        return {
            "error": "ValidationError",
            "details": "scenarios list is required and cannot be empty",
            "tool": "generate_test_matrix",
        }

    matrix: list[dict[str, Any]] = []
    total_passed = 0
    total_failed = 0

    with httpx.Client(base_url=base_url, timeout=settings.http_timeout) as client:
        for scenario in scenarios:
            name = scenario.get("name", "unnamed")
            endpoint = scenario.get("endpoint", "/")
            method = scenario.get("method", "GET").upper()
            payloads: list[dict] = scenario.get("payloads") or [{}]
            expected_statuses: list[int] = scenario.get("expected_statuses") or [
                200
            ] * len(payloads)
            expected_keys_list: list[list[str]] = scenario.get("expected_keys") or [
                []
            ] * len(payloads)

            for idx, payload in enumerate(payloads):
                exp_status = (
                    expected_statuses[idx]
                    if idx < len(expected_statuses)
                    else 200
                )
                exp_keys: list[str] = (
                    expected_keys_list[idx]
                    if idx < len(expected_keys_list)
                    else []
                )

                t0 = time.monotonic()
                actual_status = -1
                failure_reason: str | None = None
                passed = False

                try:
                    resp = client.request(
                        method=method,
                        url=endpoint,
                        json=payload if payload else None,
                    )
                    actual_status = resp.status_code
                    response_ms = int((time.monotonic() - t0) * 1000)

                    if actual_status != exp_status:
                        failure_reason = (
                            f"expected status {exp_status}, got {actual_status}"
                        )
                    elif exp_keys:
                        try:
                            resp_json = resp.json()
                            missing = [k for k in exp_keys if k not in resp_json]
                            if missing:
                                failure_reason = f"missing keys: {missing}"
                        except Exception:  # noqa: BLE001
                            failure_reason = "response is not valid JSON"

                    passed = failure_reason is None

                except httpx.TimeoutException:
                    response_ms = int((time.monotonic() - t0) * 1000)
                    failure_reason = "request timed out"
                except Exception as exc:  # noqa: BLE001
                    response_ms = int((time.monotonic() - t0) * 1000)
                    failure_reason = f"request error: {exc}"

                if passed:
                    total_passed += 1
                else:
                    total_failed += 1

                matrix.append(
                    {
                        "scenario": name,
                        "payload_index": idx,
                        "payload": payload,
                        "expected_status": exp_status,
                        "actual_status": actual_status,
                        "response_ms": response_ms,
                        "passed": passed,
                        "failure_reason": failure_reason,
                    }
                )

    total_cases = len(matrix)
    run_id = store.save_run(
        run_type="api_matrix",
        status="passed" if total_failed == 0 else "failed",
        summary={
            "total_cases": total_cases,
            "passed": total_passed,
            "failed": total_failed,
        },
        details={"matrix_sample": matrix[:10]},
        repo_path=base_url,
    )

    return {
        "total_cases": total_cases,
        "passed": total_passed,
        "failed": total_failed,
        "matrix": matrix,
        "run_id": run_id,
    }
