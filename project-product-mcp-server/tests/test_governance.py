import json

import httpx
import pytest
from project_product_mcp.config.settings import get_settings
from project_product_mcp.governance import GovernancePolicyEnforcementPoint

CLAIMS = {
    "sub": "user:7",
    "act": {"sub": "sales-agent"},
    "tenant_id": "devteam",
    "jti": "inner-1",
    "parent_jti": "front-1",
    "scopes": ["portfolio:product:delete"],
    "_actor_id": 7,
    "_environment_id": 0,
    "twin_id": "twin-1",
}
META = {
    "capability": "portfolio.product.delete",
    "required_scope": "portfolio:product:delete",
    "resource_type": "product",
    "data_domain": "portfolio",
}
ARGS = {
    "product_id": "11111111-1111-4111-8111-111111111111",
    "expected_version": 1,
    "idempotency_key": "delete-key",
}


@pytest.mark.asyncio
async def test_governance_allow_deny_and_pending_contracts():
    modes = iter(["allow", "deny", "pending_approval"])
    captured = []

    def handler(request: httpx.Request):
        payload = json.loads(request.content)
        captured.append((request.url.path, payload))
        if request.url.path.endswith("/evaluate"):
            mode = next(modes)
            return httpx.Response(200, json={"allowed": mode == "allow", "decision": mode})
        return httpx.Response(
            201, json={"approvalUid": "approval-1", "checkpointUid": "checkpoint-1"}
        )

    pep = GovernancePolicyEnforcementPoint(get_settings())
    await pep._client.aclose()
    pep._client = httpx.AsyncClient(
        base_url="http://governance.invalid:8000", transport=httpx.MockTransport(handler)
    )
    try:
        allow = await pep.evaluate(
            tool_name="product_delete", metadata=META, claims=dict(CLAIMS), arguments=ARGS
        )
        deny = await pep.evaluate(
            tool_name="product_delete", metadata=META, claims=dict(CLAIMS), arguments=ARGS
        )
        pending = await pep.evaluate(
            tool_name="product_delete", metadata=META, claims=dict(CLAIMS), arguments=ARGS
        )
    finally:
        await pep.aclose()
    assert allow.outcome == "allow" and deny.outcome == "deny"
    assert (pending.outcome, pending.approval_uid, pending.checkpoint_uid) == (
        "pending",
        "approval-1",
        "checkpoint-1",
    )
    evaluate_payload = captured[0][1]
    assert evaluate_payload["tenant_id"] == CLAIMS["tenant_id"]
    assert evaluate_payload["environment_id"] == 0
    assert evaluate_payload["subject"] == {
        "type": "agent",
        "id": "user:7",
        "profile": None,
        "teams": [],
        "domain": "portfolio",
    }
    assert evaluate_payload["context"]["agent_id"] == "sales-agent"
    parked = captured[-1][1]
    assert parked["ownerService"] == "platform-project-product"
    assert parked["principalUserId"] == "user:7"
    assert "token" not in json.dumps(parked).lower()
