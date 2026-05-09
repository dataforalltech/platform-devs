from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from src.tools.api_tool import generate_test_matrix, run_api_tests


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


class _FakeClient:
    """Context manager that mimics httpx.Client."""

    def __init__(self, responses: list[MagicMock]):
        self._responses = iter(responses)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def request(self, **kwargs):
        return next(self._responses)


def test_run_api_tests_all_pass(store, settings):
    responses = [
        _mock_response(200, {"id": 1, "name": "Ana"}),
        _mock_response(201, {"id": 2}),
        _mock_response(200, {"status": "ok"}),
    ]
    endpoints = [
        {"path": "/users", "method": "GET", "expect_status": 200},
        {"path": "/users", "method": "POST", "body": {"name": "Ana"}, "expect_status": 201},
        {"path": "/health", "expect_status": 200},
    ]
    with patch("httpx.Client", return_value=_FakeClient(responses)):
        result = run_api_tests(store, settings, base_url="http://localhost:8000", endpoints=endpoints)

    assert result["total"] == 3
    assert result["passed"] == 3
    assert result["failed"] == 0


def test_run_api_tests_one_fail(store, settings):
    responses = [
        _mock_response(200),
        _mock_response(500),
    ]
    endpoints = [
        {"path": "/ok", "expect_status": 200},
        {"path": "/fail", "expect_status": 200},
    ]
    with patch("httpx.Client", return_value=_FakeClient(responses)):
        result = run_api_tests(store, settings, base_url="http://localhost:8000", endpoints=endpoints)

    assert result["failed"] == 1
    assert result["results"][1]["passed"] is False
    assert "500" in result["results"][1]["failure_reason"]


def test_run_api_tests_expect_keys_missing(store, settings):
    responses = [_mock_response(200, {"status": "ok"})]
    endpoints = [{"path": "/users/1", "expect_status": 200, "expect_keys": ["id", "name"]}]
    with patch("httpx.Client", return_value=_FakeClient(responses)):
        result = run_api_tests(store, settings, base_url="http://localhost:8000", endpoints=endpoints)

    assert result["failed"] == 1
    assert "missing" in result["results"][0]["failure_reason"]


def test_run_api_tests_timeout(store, settings):
    class _TimeoutClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def request(self, **kwargs):
            raise httpx.TimeoutException("timeout")

    endpoints = [{"path": "/slow", "expect_status": 200}]
    with patch("httpx.Client", return_value=_TimeoutClient()):
        result = run_api_tests(store, settings, base_url="http://localhost:8000", endpoints=endpoints)

    assert result["failed"] == 1
    assert "timed out" in result["results"][0]["failure_reason"]


def test_generate_test_matrix_success(store, settings):
    # 2 scenarios × 2 payloads each = 4 cases
    responses = [
        _mock_response(201, {"id": 1, "email": "a@b.com"}),
        _mock_response(422),
        _mock_response(200),
        _mock_response(404),
    ]
    scenarios = [
        {
            "name": "criar usuario",
            "endpoint": "/api/users",
            "method": "POST",
            "payloads": [{"email": "a@b.com"}, {"email": "invalido"}],
            "expected_statuses": [201, 422],
        },
        {
            "name": "buscar produto",
            "endpoint": "/api/products/1",
            "method": "GET",
            "payloads": [{}],
            "expected_statuses": [200],
        },
    ]
    # 3 cases total (2+1)
    responses = [
        _mock_response(201, {"id": 1}),
        _mock_response(422),
        _mock_response(200),
    ]
    with patch("httpx.Client", return_value=_FakeClient(responses)):
        result = generate_test_matrix(
            store, settings, base_url="http://localhost:8000", scenarios=scenarios
        )

    assert result["total_cases"] == 3
    assert result["passed"] == 3
    assert result["failed"] == 0


def test_generate_test_matrix_wrong_status(store, settings):
    responses = [_mock_response(500)]
    scenarios = [
        {
            "name": "criar usuario",
            "endpoint": "/api/users",
            "method": "POST",
            "payloads": [{"email": "a@b.com"}],
            "expected_statuses": [201],
        }
    ]
    with patch("httpx.Client", return_value=_FakeClient(responses)):
        result = generate_test_matrix(
            store, settings, base_url="http://localhost:8000", scenarios=scenarios
        )

    assert result["failed"] == 1
    assert result["matrix"][0]["passed"] is False
    assert "201" in result["matrix"][0]["failure_reason"]


def test_generate_test_matrix_empty_base_url(store, settings):
    result = generate_test_matrix(store, settings, base_url="", scenarios=[])
    assert result["error"] == "ValidationError"
    assert "base_url" in result["details"]
