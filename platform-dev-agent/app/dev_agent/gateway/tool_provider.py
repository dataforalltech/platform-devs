"""``GatewayToolProvider`` — wrap gateway operations as capability-guarded tools.

The persona's ReAct loop (:class:`~app.dev_agent.profiles.base.ProfileBase`)
drives tools through a tiny duck-typed interface: it reads ``tool.name`` to build
its dispatch map and calls ``await tool.ainvoke(args)`` to run one. It never
requires a langchain ``BaseTool`` — only that pair. So each tool built here is a
minimal object exposing exactly ``.name`` / ``.description`` / ``.args_schema``
and an async ``ainvoke(args)``.

Every built tool is a *closure over one gateway operation* that, on invocation:

1. resolves the operation's :class:`Capability` via the single
   :class:`CapabilityResolver` authority (read vs write);
2. asks the single :class:`CapabilityEnforcer` whether ``profile`` may use that
   capability — raising :class:`CapabilityViolation` (a ``PermissionError``) when
   not. The ReAct loop catches this and turns the tool call into a tool error, so
   a denial never becomes a false success and never aborts the whole turn;
3. dispatches to the gateway via :meth:`GatewayToolClient.call_tool` with a fresh
   ``uuid4`` idempotency key, the resolved capability (so reads retry / writes do
   not), and a correlation dict built by :func:`build_correlation`;
4. redacts the output via :func:`redact` before returning it to the loop, so a
   sensitive payload never re-enters the LLM transcript.

This is the persona-guard half of the "single authority" contract (§1.1): it and
the executor-enforcer path both consume the same resolver + enforcer instances.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.dev_agent.capability import CapabilityEnforcer, CapabilityResolver
from app.dev_agent.gateway.client import GatewayToolClient, build_correlation
from app.dev_agent.security.redaction import redact


@dataclass(frozen=True)
class ToolSpec:
    """A lightweight description of a gateway operation to expose as a tool.

    ``name`` is the namespaced gateway id ``"<namespace>.<operationId>"`` — the
    same identifier the resolver, enforcer, redaction, and gateway all key on.
    """

    name: str
    description: str
    input_schema: dict[str, Any] | None = None


class _GatewayTool:
    """One capability-guarded gateway operation, shaped for ``ProfileBase``.

    Exposes the exact duck-typed surface the ReAct loop uses: ``.name`` (for the
    dispatch map) and ``async ainvoke(args)`` (to run). ``.description`` /
    ``.args_schema`` are provided for parity with langchain tools in case a real
    ``LLM.bind_tools`` inspects them; the loop itself only needs ``.name`` +
    ``ainvoke``.
    """

    def __init__(
        self,
        spec: ToolSpec,
        *,
        gateway: GatewayToolClient,
        enforcer: CapabilityEnforcer,
        caps: CapabilityResolver,
        profile_id: str,
        run_id: str,
        session_id: str,
        tenant_id: str | None,
    ) -> None:
        self.name = spec.name
        self.description = spec.description
        # langchain tools expose ``args_schema``; keep the attribute present.
        self.args_schema = spec.input_schema
        self._gateway = gateway
        self._enforcer = enforcer
        self._caps = caps
        self._profile_id = profile_id
        self._run_id = run_id
        self._session_id = session_id
        self._tenant_id = tenant_id

    async def ainvoke(self, args: dict[str, Any] | None = None) -> Any:
        """Resolve capability, enforce it, dispatch via the gateway, redact.

        Raises :class:`~app.dev_agent.capability.CapabilityViolation` when the
        profile lacks the required capability — the persona loop surfaces that as
        a tool error rather than a success.
        """
        arguments = dict(args or {})
        capability = self._caps.resolve(self.name)
        # Single authority: raises CapabilityViolation on a denied (profile, cap).
        self._enforcer.assert_allowed(
            profile=self._profile_id, capability=capability, tool=self.name
        )
        correlation = build_correlation(
            run_id=self._run_id,
            session_id=self._session_id,
            agent_profile=self._profile_id,
            tenant_id=self._tenant_id,
        )
        out = await self._gateway.call_tool(
            self.name,
            arguments,
            idempotency_key=str(uuid.uuid4()),
            capability=capability,
            correlation=correlation,
        )
        return redact(self.name, out)


class GatewayToolProvider:
    """Builds capability-guarded LLM tools from gateway operation specs.

    Holds the single ``gateway`` / ``enforcer`` / ``caps`` authorities and stamps
    them into every tool it builds, so the persona path cannot diverge from the
    executor path on what a write is or who may perform it.
    """

    def __init__(
        self,
        gateway: GatewayToolClient,
        enforcer: CapabilityEnforcer,
        *,
        caps: CapabilityResolver | None = None,
    ) -> None:
        self._gateway = gateway
        self._enforcer = enforcer
        self._caps = caps or CapabilityResolver()

    def build_tools(
        self,
        *,
        profile_id: str,
        specs: Sequence[ToolSpec],
        run_id: str = "",
        session_id: str = "",
        tenant_id: str | None = None,
    ) -> list[_GatewayTool]:
        """Return one guarded tool per spec, bound to ``profile_id`` + correlation.

        Each tool carries the correlation identity (``run_id`` / ``session_id`` /
        ``tenant_id``) so every gateway call it makes is traceable back to this
        run and profile.
        """
        return [
            _GatewayTool(
                spec,
                gateway=self._gateway,
                enforcer=self._enforcer,
                caps=self._caps,
                profile_id=profile_id,
                run_id=run_id,
                session_id=session_id,
                tenant_id=tenant_id,
            )
            for spec in specs
        ]


__all__ = ["GatewayToolProvider", "ToolSpec"]
