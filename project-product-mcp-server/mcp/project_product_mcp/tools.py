"""Provider-neutral MCP tools implemented exclusively through the private API."""

from __future__ import annotations

from typing import Any

from .client.api_client import ServiceApiClient, TrustedMcpContext

_AUDIT_FIELDS = {"is_active", "id_environment", "id_owner", "created_by", "updated_by"}


class InvalidToolResponseError(RuntimeError):
    """The private adapter returned a payload that cannot satisfy the MCP contract."""


def _public(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise InvalidToolResponseError("adapter record must be an object")
    for field in ("created_by", "updated_by"):
        actor_id = item.get(field)
        if isinstance(actor_id, bool) or not isinstance(actor_id, int) or actor_id < 1:
            raise InvalidToolResponseError("adapter record has invalid audit fields")
    result = {key: value for key, value in item.items() if key not in _AUDIT_FIELDS}
    result["created_by_ref"] = f"platform-admin:user:{item['created_by']}"
    result["updated_by_ref"] = f"platform-admin:user:{item['updated_by']}"
    return result


def _page(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise InvalidToolResponseError("adapter page must be an object")
    if "items" not in payload or "next_after_id" not in payload:
        raise InvalidToolResponseError("adapter page is missing required fields")
    items = payload["items"]
    next_after_id = payload["next_after_id"]
    if not isinstance(items, list) or not (next_after_id is None or isinstance(next_after_id, str)):
        raise InvalidToolResponseError("adapter page has invalid field types")
    return {
        "items": [_public(item) for item in items],
        "next_after_id": next_after_id,
    }


def _repository_page(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or "items" not in payload:
        raise InvalidToolResponseError("adapter repository page is missing required fields")
    items = payload["items"]
    if not isinstance(items, list):
        raise InvalidToolResponseError("adapter repository page has invalid field types")
    return {"items": [_public(item) for item in items]}


def _params(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


async def product_create(
    client: ServiceApiClient, args: dict[str, Any], context: TrustedMcpContext
) -> dict[str, Any]:
    return _public(await client.post("/api/internal/mcp/products", json=args, context=context))


async def product_get(
    client: ServiceApiClient, args: dict[str, Any], context: TrustedMcpContext
) -> dict[str, Any]:
    return _public(
        await client.get(f"/api/internal/mcp/products/{args['product_id']}", context=context)
    )


async def product_list(
    client: ServiceApiClient, args: dict[str, Any], context: TrustedMcpContext
) -> dict[str, Any]:
    payload = await client.get(
        "/api/internal/mcp/products",
        params=_params(
            status=args.get("status"), after_id=args.get("after_id"), limit=args.get("limit", 50)
        ),
        context=context,
    )
    return _page(payload)


async def product_update(
    client: ServiceApiClient, args: dict[str, Any], context: TrustedMcpContext
) -> dict[str, Any]:
    body = {
        "idempotency_key": args["idempotency_key"],
        "expected_version": args["expected_version"],
        **args["changes"],
    }
    return _public(
        await client.patch(
            f"/api/internal/mcp/products/{args['product_id']}", json=body, context=context
        )
    )


async def product_delete(
    client: ServiceApiClient, args: dict[str, Any], context: TrustedMcpContext
) -> dict[str, Any]:
    body = {
        "idempotency_key": args["idempotency_key"],
        "expected_version": args["expected_version"],
    }
    return await client.delete(
        f"/api/internal/mcp/products/{args['product_id']}", json=body, context=context
    )


async def project_create(
    client: ServiceApiClient, args: dict[str, Any], context: TrustedMcpContext
) -> dict[str, Any]:
    return _public(await client.post("/api/internal/mcp/projects", json=args, context=context))


async def project_get(
    client: ServiceApiClient, args: dict[str, Any], context: TrustedMcpContext
) -> dict[str, Any]:
    return _public(
        await client.get(f"/api/internal/mcp/projects/{args['project_id']}", context=context)
    )


async def project_list(
    client: ServiceApiClient, args: dict[str, Any], context: TrustedMcpContext
) -> dict[str, Any]:
    payload = await client.get(
        "/api/internal/mcp/projects",
        params=_params(
            product_id=args.get("product_id"),
            status=args.get("status"),
            after_id=args.get("after_id"),
            limit=args.get("limit", 50),
        ),
        context=context,
    )
    return _page(payload)


async def project_update(
    client: ServiceApiClient, args: dict[str, Any], context: TrustedMcpContext
) -> dict[str, Any]:
    body = {
        "idempotency_key": args["idempotency_key"],
        "expected_version": args["expected_version"],
        **args["changes"],
    }
    return _public(
        await client.patch(
            f"/api/internal/mcp/projects/{args['project_id']}", json=body, context=context
        )
    )


async def project_delete(
    client: ServiceApiClient, args: dict[str, Any], context: TrustedMcpContext
) -> dict[str, Any]:
    body = {
        "idempotency_key": args["idempotency_key"],
        "expected_version": args["expected_version"],
    }
    return await client.delete(
        f"/api/internal/mcp/projects/{args['project_id']}", json=body, context=context
    )


async def project_repository_attach(
    client: ServiceApiClient, args: dict[str, Any], context: TrustedMcpContext
) -> dict[str, Any]:
    body = {key: value for key, value in args.items() if key != "project_id"}
    payload = await client.post(
        f"/api/internal/mcp/projects/{args['project_id']}/repositories", json=body, context=context
    )
    return _public(payload)


async def project_repository_list(
    client: ServiceApiClient, args: dict[str, Any], context: TrustedMcpContext
) -> dict[str, Any]:
    payload = await client.get(
        f"/api/internal/mcp/projects/{args['project_id']}/repositories",
        params=_params(provider=args.get("provider"), role=args.get("role")),
        context=context,
    )
    return _repository_page(payload)


async def project_repository_detach(
    client: ServiceApiClient, args: dict[str, Any], context: TrustedMcpContext
) -> dict[str, Any]:
    body = {
        "idempotency_key": args["idempotency_key"],
        "expected_version": args["expected_version"],
    }
    return await client.delete(
        f"/api/internal/mcp/repositories/{args['binding_id']}", json=body, context=context
    )
