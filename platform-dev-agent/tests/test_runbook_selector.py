"""RunbookSelector: known mapping -> id, unknown -> None, closed enum, LLM fallback."""

from __future__ import annotations

import pytest

from app.dev_agent.runbook.catalog import RUNBOOK_CATALOG
from app.dev_agent.runbook_selector import RunbookSelector


def test_known_sub_intent_maps_to_existing_runbook() -> None:
    selector = RunbookSelector()
    runbook_id = selector.select(intent="x", entity_type=None, sub_intent="run_tests")
    assert runbook_id == "health_to_report"
    assert runbook_id in RUNBOOK_CATALOG


def test_entity_type_is_normalized_before_lookup() -> None:
    selector = RunbookSelector()
    # "Service-Health" -> "service_health" (strip/lower/dash->underscore).
    assert (
        selector.select(intent="x", entity_type="Service-Health", sub_intent="")
        == "health_to_report"
    )


def test_unknown_tokens_return_none() -> None:
    selector = RunbookSelector()
    assert selector.select(intent="x", entity_type="unknown", sub_intent="unknown") is None


def test_routes_pointing_at_unknown_runbook_are_rejected() -> None:
    with pytest.raises(ValueError):
        RunbookSelector(routes={"foo": "does_not_exist"})


def test_llm_fallback_only_accepts_ids_in_the_closed_set() -> None:
    class _GoodLLM:
        def select_runbook(self, *, intent, entity_type, sub_intent, allowed):  # noqa: ANN001
            return "health_to_report"

    class _BadLLM:
        def select_runbook(self, *, intent, entity_type, sub_intent, allowed):  # noqa: ANN001
            return "hallucinated_runbook"

    good = RunbookSelector(routes={}, llm_fallback=_GoodLLM())
    assert good.select(intent="x", entity_type=None, sub_intent="none") == "health_to_report"

    bad = RunbookSelector(routes={}, llm_fallback=_BadLLM())
    # Out-of-enum reply is rejected -> None.
    assert bad.select(intent="x", entity_type=None, sub_intent="none") is None


def test_no_llm_fallback_leaves_unmatched_as_none() -> None:
    selector = RunbookSelector(routes={})
    assert selector.select(intent="x", entity_type=None, sub_intent="none") is None
