"""Capability + risk resolution — the SINGLE authority (critique §1.1).

There is exactly one place that decides, for a given gateway tool:

- its :class:`Capability` (read vs write), derived from the operation verb;
- its :class:`RiskLevel`, derived structurally (not from a nominal allow-list).

Both the persona path (guard) and the executor path (enforcer) — out of this
skeleton — MUST consume this resolver so a write cannot slip through one path
and not the other.

Risk derivation (critique §1.2): high risk is NOT a nominal allow-list of tool
names (fragile — misses ``push_to_registry``, ``merge_branch``, etc.). Instead
a write whose namespace owner is one of the destructive owners
(``deploy`` / ``infra`` / ``pipeline``) is HIGH by default; other writes are
MEDIUM; reads are LOW. An explicit per-task override always wins.
"""

from __future__ import annotations

from app.dev_agent.models.plan import Capability, RiskLevel

# Verbs that imply WRITE (locked decision).
_WRITE_PREFIXES: tuple[str, ...] = (
    "create_",
    "update_",
    "delete_",
    "generate_",
    "deploy_",
)

# Namespace owners whose MUTATIONs are intrinsically destructive => HIGH risk.
# Matched against the leading segment(s) of the tool namespace, e.g.
# "deploy-mcp" -> owner "deploy". This is structural, not a per-tool list.
_HIGH_RISK_OWNERS: frozenset[str] = frozenset({"deploy", "infra", "pipeline"})


def _split_tool(tool: str) -> tuple[str, str]:
    """Split ``"<namespace>.<operationId>"`` into ``(namespace, operation)``.

    Raises ``ValueError`` for a non-namespaced tool (defensive; the PlanItem
    validator already enforces the shape upstream).
    """
    if "." not in tool:
        raise ValueError(f"tool must be namespaced '<namespace>.<operationId>': {tool!r}")
    namespace, operation = tool.split(".", 1)
    return namespace, operation


def _owner_of(namespace: str) -> str:
    """Return the coarse owner of a namespace.

    ``"deploy-mcp"`` -> ``"deploy"``, ``"infra-mcp"`` -> ``"infra"``,
    ``"qa-mcp"`` -> ``"qa"``. The owner is the leading token before ``-`` or
    ``_`` (or the whole namespace when there is no separator).
    """
    for sep in ("-", "_"):
        if sep in namespace:
            return namespace.split(sep, 1)[0]
    return namespace


class CapabilityResolver:
    """Single authority for capability + risk of a gateway tool."""

    def __init__(self, overrides: dict[str, Capability] | None = None) -> None:
        # Per-tool capability overrides: "<namespace>.<operationId>" -> Capability
        self._overrides = overrides or {}

    def record_for_operation(self, operation_id: str) -> None:  # noqa: ARG002
        """Heuristic-only resolver has no catalog → no Operation record."""
        return None

    def tool_for_operation(self, operation_id: str) -> None:  # noqa: ARG002
        """Heuristic-only resolver has no catalog → no Operation→tool binding."""
        return None

    def resolve(self, tool: str, *, override: str | None = None) -> Capability:
        """Resolve the :class:`Capability` for ``tool``.

        Precedence: explicit ``override`` arg > constructor overrides > verb
        heuristic (write prefix => WRITE, else READ).
        """
        if override:
            return Capability(override)
        if tool in self._overrides:
            return self._overrides[tool]
        _, operation = _split_tool(tool)
        return Capability.WRITE if operation.startswith(_WRITE_PREFIXES) else Capability.READ

    def classify_risk(
        self,
        tool: str,
        capability: Capability,
        *,
        override: str | None = None,
    ) -> RiskLevel:
        """Derive the :class:`RiskLevel` for ``tool`` given its capability.

        - explicit ``override`` wins;
        - READ => LOW;
        - WRITE whose owner is destructive (deploy/infra/pipeline) => HIGH;
        - any other WRITE => MEDIUM.
        """
        if override:
            return RiskLevel(override)
        if capability is Capability.READ:
            return RiskLevel.LOW
        namespace, _ = _split_tool(tool)
        if _owner_of(namespace) in _HIGH_RISK_OWNERS:
            return RiskLevel.HIGH
        return RiskLevel.MEDIUM


class CapabilityViolation(PermissionError):
    """A profile lacks the capability required by a tool (enforcement, ON).

    Subclasses :class:`PermissionError` (not :class:`Exception` directly) so a
    caller can distinguish an authorization denial from an operational failure,
    yet it is still caught by a broad ``except Exception`` in the executor's
    per-item handler (critique §1.7: a violation turns the item into ERROR, it
    never aborts the whole plan).
    """


class CapabilityEnforcer:
    """The SINGLE runtime authority that authorizes a (profile, capability).

    Enforcement is always ON (no opt-in flag). Both the persona-guard path and
    the executor-enforcer path (critique §1.1) MUST consume this one authority
    so a write cannot slip through one path and not the other.

    ``allowed`` maps a profile id to the set of capabilities granted to it, e.g.
    ``{"qa-engineer": {Capability.READ}, "devops": {Capability.READ, Capability.WRITE}}``.
    A profile absent from the map is treated as READ-only (the safe default): it
    may perform reads but never writes.
    """

    def __init__(self, allowed: dict[str, set[Capability]]) -> None:
        self._allowed = allowed

    def assert_allowed(self, *, profile: str, capability: Capability, tool: str) -> None:
        """Raise :class:`CapabilityViolation` if ``profile`` may not use ``capability``.

        Returns ``None`` (authorized) or raises. Never mutates state.
        """
        granted = self._allowed.get(profile, {Capability.READ})
        if capability not in granted:
            raise CapabilityViolation(
                f"profile={profile!r} lacks capability={capability.value!r} "
                f"required by tool={tool!r}"
            )
