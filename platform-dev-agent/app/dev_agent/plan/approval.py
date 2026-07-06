"""Human approval gate (N1 plan-level + N2 per-item high-risk).

Two levels of approval, both explicit:

- **N1 — plan selection.** An item executes only if it is in
  :attr:`ApprovalDecision.approved_item_ids`. Selection arrives either as a
  closed list of item *labels*, as the sentinel ``"__approve_all__"``, or as a
  verbal confirmation from a *closed* whitelist. Verbal / "approve all" cover
  **only N1** — never high-risk (critique §2.3).
- **N2 — per-item high-risk.** An item with ``risk == HIGH`` executes only if it
  was confirmed *individually* through the explicit signal
  ``{"__confirm_high__": [item_id, ...]}``. "Approve all" and verbal
  confirmation NEVER cover high-risk. A high-risk item with no answer at all is
  reported as *unanswered* (distinct from rejected, critique §1.11 / §2.3): the
  caller can re-issue the poll and warn the human rather than silently skipping
  what may have been the whole point of the run.

The gate is pure: :meth:`ApprovalGate.resolve` turns a raw poll ``response_value``
into an :class:`ApprovalDecision`; :meth:`ApprovalGate.build_high_risk_poll`
builds the dedicated N2 ``poll_multi`` block (only the HIGH items).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.dev_agent.models.plan import Plan, RiskLevel

# Sentinel meaning "the human approved the whole plan (N1)".
APPROVE_ALL = "__approve_all__"
# Key of the explicit, per-item high-risk confirmation signal (N2).
CONFIRM_HIGH = "__confirm_high__"


@dataclass
class ApprovalDecision:
    """The resolved authorization for a plan.

    - ``approved_item_ids`` — items cleared by N1 (may execute, subject to N2).
    - ``high_risk_confirmed_ids`` — HIGH items individually confirmed via N2.
    - ``high_risk_unanswered_ids`` — HIGH items that were approved at N1 but got
      no N2 answer (neither confirmed nor explicitly rejected). Distinct from a
      rejection so the caller can re-prompt instead of silently dropping them
      (critique §1.11 / §2.3).
    - ``rejected`` — the human rejected the whole plan.
    """

    approved_item_ids: set[str] = field(default_factory=set)
    high_risk_confirmed_ids: set[str] = field(default_factory=set)
    high_risk_unanswered_ids: set[str] = field(default_factory=set)
    rejected: bool = False


class ApprovalGate:
    """Turn a raw poll response into an :class:`ApprovalDecision`.

    N1 selection is by item *label* (or the ``__approve_all__`` sentinel, or a
    verbal confirmation from a closed whitelist). N2 high-risk confirmation is
    ONLY via the explicit ``{"__confirm_high__": [item_id, ...]}`` signal —
    verbal/all never covers high-risk.
    """

    # Closed whitelist — verbal confirmation covers N1 only (never high-risk).
    _VERBAL_APPROVE_ALL: frozenset[str] = frozenset(
        {
            "sim",
            "ok",
            "pode",
            "aprovar",
            "executar",
            "pode executar",
            "aprovar todos",
            "executar tudo",
            "confirmar",
            "yes",
            "approve",
            "approve all",
        }
    )
    # Closed whitelist of explicit whole-plan rejection.
    _VERBAL_REJECT: frozenset[str] = frozenset(
        {"nao", "não", "no", "cancelar", "rejeitar", "reject", "cancel", "abortar"}
    )

    def resolve(self, plan: Plan, *, response_value: Any) -> ApprovalDecision:
        """Resolve ``response_value`` against ``plan`` into an :class:`ApprovalDecision`.

        Accepted shapes:
        - ``None`` / empty                 -> nothing approved (caller re-polls).
        - a verbal string in the reject whitelist -> ``rejected=True``.
        - the ``"__approve_all__"`` sentinel or a verbal-approve string
          -> every item approved at N1 (high-risk still needs N2).
        - a ``list[str]`` of labels        -> those items approved at N1.
        - a ``dict`` may carry N1 (``"__approve_all__": True`` or ``"labels": [...]``)
          and/or N2 (``"__confirm_high__": [item_id, ...]``).
        """
        approve_all, approved_labels, confirmed_high, rejected = self._parse(
            response_value
        )

        if rejected:
            return ApprovalDecision(rejected=True)

        # N1 — nothing selected and no "approve all" => caller re-issues the poll.
        if not approve_all and not approved_labels and not confirmed_high:
            return ApprovalDecision()

        if approve_all:
            selected = list(plan.items)
        else:
            selected = [i for i in plan.items if i.label in approved_labels]

        approved_ids = {i.item_id for i in selected}

        # An explicit high-risk confirmation implicitly approves that item at N1
        # too (you cannot confirm a step you did not select).
        high_by_id = {i.item_id: i for i in plan.items if i.risk is RiskLevel.HIGH}
        confirmed_ids = {iid for iid in confirmed_high if iid in high_by_id}
        approved_ids |= confirmed_ids

        # N2 — a HIGH item that is approved at N1 but NOT individually confirmed
        # is *unanswered* (not rejected): verbal/all never covers high-risk.
        unanswered_ids = {
            iid
            for iid in high_by_id
            if iid in approved_ids and iid not in confirmed_ids
        }

        return ApprovalDecision(
            approved_item_ids=approved_ids,
            high_risk_confirmed_ids=confirmed_ids,
            high_risk_unanswered_ids=unanswered_ids,
        )

    def _parse(
        self, response_value: Any
    ) -> tuple[bool, set[str], set[str], bool]:
        """Normalize the raw response into ``(approve_all, labels, confirmed_high, rejected)``."""
        approve_all = False
        approved_labels: set[str] = set()
        confirmed_high: set[str] = set()
        rejected = False

        if response_value is None:
            return approve_all, approved_labels, confirmed_high, rejected

        if isinstance(response_value, str):
            text = response_value.strip()
            if text == APPROVE_ALL:
                approve_all = True
            else:
                lowered = text.lower()
                if lowered in self._VERBAL_REJECT:
                    rejected = True
                elif lowered in self._VERBAL_APPROVE_ALL:
                    approve_all = True
            return approve_all, approved_labels, confirmed_high, rejected

        if isinstance(response_value, list):
            if APPROVE_ALL in response_value:
                approve_all = True
            approved_labels = {v for v in response_value if v != APPROVE_ALL}
            return approve_all, approved_labels, confirmed_high, rejected

        if isinstance(response_value, dict):
            if response_value.get(APPROVE_ALL) is True:
                approve_all = True
            labels = response_value.get("labels")
            if isinstance(labels, list):
                approved_labels = set(labels)
            highs = response_value.get(CONFIRM_HIGH)
            if isinstance(highs, list):
                confirmed_high = set(highs)
            if response_value.get("rejected") is True:
                rejected = True
            return approve_all, approved_labels, confirmed_high, rejected

        return approve_all, approved_labels, confirmed_high, rejected

    @staticmethod
    def build_high_risk_poll(plan: Plan) -> dict[str, Any]:
        """Build the dedicated N2 ``poll_multi`` block (HIGH items only).

        Confirmation is per item: the block carries the ``item_ids`` so the
        caller can normalize the human's selection back into a
        ``{"__confirm_high__": [item_id, ...]}`` signal for :meth:`resolve`.
        """
        highs = [i for i in plan.items if i.risk is RiskLevel.HIGH]
        return {
            "type": "poll_multi",
            "question": f"Confirme os {len(highs)} passo(s) de ALTO RISCO a executar:",
            "question_id": f"{plan.question_id}_highrisk",
            "options": [f"{i.label} [{i.tool}]" for i in highs],
            "min_select": 0,
            "max_select": len(highs),
            "metadata": {
                "plan_id": plan.plan_id,
                "item_ids": [i.item_id for i in highs],
                "confirm_key": CONFIRM_HIGH,
            },
        }
