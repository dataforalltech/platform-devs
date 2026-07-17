from __future__ import annotations

from .artifact_tool import delete_artifact, get_artifact, list_artifacts, save_artifact
from .bug_report_tool import (
    classify_bug_severity,
    delete_bug_report,
    get_bug_report,
    list_bug_reports,
    save_bug_report,
    update_bug_status,
)
from .generator_tool import (
    generate_api_tests,
    generate_cypress_tests,
    generate_e2e_tests,
    generate_gherkin_scenarios,
    generate_k6_performance_test,
    generate_playwright_tests,
    generate_quality_gate,
    generate_regression_suite,
    generate_smoke_test_suite,
    generate_uat_checklist,
    generate_unit_tests,
)
from .quality_gate_tool import (
    delete_quality_gate,
    get_quality_gate,
    list_quality_gates,
    set_quality_gate,
)
from .test_case_tool import (
    delete_test_case,
    get_test_case,
    list_test_cases,
    save_test_case,
    update_test_case,
)
from .test_plan_tool import (
    delete_test_plan,
    get_test_plan,
    list_test_plans,
    save_test_plan,
    update_test_plan,
)

__all__ = [
    # Test Plans
    "save_test_plan",
    "list_test_plans",
    "get_test_plan",
    "update_test_plan",
    "delete_test_plan",
    # Test Cases
    "save_test_case",
    "list_test_cases",
    "get_test_case",
    "update_test_case",
    "delete_test_case",
    # Bug Reports
    "save_bug_report",
    "list_bug_reports",
    "get_bug_report",
    "update_bug_status",
    "delete_bug_report",
    "classify_bug_severity",
    # Quality Gates
    "set_quality_gate",
    "list_quality_gates",
    "get_quality_gate",
    "delete_quality_gate",
    # Artifacts
    "save_artifact",
    "list_artifacts",
    "get_artifact",
    "delete_artifact",
    # Geradores determinísticos (COMPUTE PURO — sem DB/LLM)
    "generate_gherkin_scenarios",
    "generate_unit_tests",
    "generate_e2e_tests",
    "generate_api_tests",
    "generate_playwright_tests",
    "generate_cypress_tests",
    "generate_k6_performance_test",
    "generate_regression_suite",
    "generate_smoke_test_suite",
    "generate_uat_checklist",
    "generate_quality_gate",
]
