"""Tools de Artefato de Segurança — persiste o relatório/scan gerado pelo agente.

Este é o "guarda-chuva" das antigas tools compute-only (incident_response/attack_surface/
compliance/code_review/dependency/secrets/headers/password_policy): em vez de cuspir
template fixo, o agente gera o `content` (o relatório/achados) e `save_security_artifact`
o persiste como histórico append-only, classificado por `kind` e `target`.

A avaliação determinística de política de senha (NIST SP 800-63B) foi **dobrada** aqui:
quando `kind == "password_policy"` e o `meta` traz a `policy`, `save_security_artifact`
roda o avaliador puro (`check_password_policy`) e anexa o resultado ao `meta`. O
avaliador segue exposto como função pura para reuso/teste. Thin wrappers sobre o
`SecurityStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import SecurityStore

VALID_KINDS = frozenset(
    {
        "incident_plan",
        "attack_surface",
        "compliance",
        "code_review",
        "dep_risk",
        "secrets_scan",
        "headers",
        "password_policy",
    }
)


def check_password_policy(policy: dict | None = None) -> dict[str, Any]:
    """Avalia uma política de senha contra NIST SP 800-63B. Cálculo puro, determinístico."""
    policy = policy or {}
    min_len = int(policy.get("min_length", 0))
    findings: list[dict[str, str]] = []

    if min_len < 8:
        findings.append(
            {
                "issue": "Comprimento mínimo abaixo de 8",
                "severity": "high",
                "fix": "Exija >= 8 (ideal 12+) caracteres.",
            }
        )
    if policy.get("require_complexity"):
        findings.append(
            {
                "issue": "Regras de complexidade obrigatórias",
                "severity": "low",
                "fix": "NIST desaconselha composição forçada; prefira comprimento + blocklist.",
            }
        )
    if policy.get("periodic_rotation"):
        findings.append(
            {
                "issue": "Rotação periódica forçada",
                "severity": "low",
                "fix": "NIST recomenda rotacionar só sob suspeita de comprometimento.",
            }
        )
    if not policy.get("check_breached_passwords"):
        findings.append(
            {
                "issue": "Sem verificação contra senhas vazadas",
                "severity": "medium",
                "fix": "Compare com blocklist (ex: HaveIBeenPwned k-anonymity).",
            }
        )
    if not policy.get("mfa"):
        findings.append(
            {
                "issue": "MFA não exigido",
                "severity": "high",
                "fix": "Exija MFA, preferindo WebAuthn/TOTP a SMS.",
            }
        )
    if not policy.get("rate_limit_login"):
        findings.append(
            {
                "issue": "Sem rate limiting / lockout no login",
                "severity": "medium",
                "fix": "Aplique throttling e proteção contra credential stuffing.",
            }
        )

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: order.get(f["severity"], 9))

    return {
        "standard": "NIST SP 800-63B",
        "evaluated_policy": policy,
        "findings": findings,
        "compliant": not any(f["severity"] in ("high", "critical") for f in findings),
    }


async def save_security_artifact(
    store: SecurityStore,
    kind: str,
    target: str,
    content: str | None = None,
    meta: Any = None,
) -> dict[str, Any]:
    """Persiste um artefato de segurança. `kind` inválido → erro sem persistir.

    Fold determinístico: em `password_policy`, se `meta.policy` vier, roda
    `check_password_policy` e anexa o resultado em `meta.assessment`."""
    if kind not in VALID_KINDS:
        return {"error": "invalid_kind", "kind": kind, "valid": sorted(VALID_KINDS)}
    if kind == "password_policy" and isinstance(meta, dict) and isinstance(meta.get("policy"), dict):
        meta = {**meta, "assessment": check_password_policy(meta["policy"])}
    artifact = await store.save_artifact(kind=kind, target=target, content=content, meta=meta)
    return {"saved": True, "security_artifact": artifact}


async def list_security_artifacts(
    store: SecurityStore, kind: str | None = None, target: str | None = None, limit: int = 50
) -> dict[str, Any]:
    artifacts = await store.list_artifacts(kind=kind, target=target, limit=limit)
    return {
        "total": len(artifacts),
        "filters": {"kind": kind, "target": target},
        "security_artifacts": artifacts,
    }


async def get_security_artifact(store: SecurityStore, artifact_id: int) -> dict[str, Any]:
    artifact = await store.get_artifact(artifact_id)
    if artifact is None:
        return {"error": "not_found", "id": artifact_id}
    return artifact


async def delete_security_artifact(store: SecurityStore, artifact_id: int) -> dict[str, Any]:
    deleted = await store.delete_artifact(artifact_id)
    return {"deleted": deleted > 0, "id": artifact_id, "deleted_count": deleted}
