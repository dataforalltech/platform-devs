"""Fase 5 — ingestão de assets do runtime para o Platform Catalog (ADR-014).

Runbooks, Personas(+Prompts), Policies e ADRs viram **assets versionados** (envelope
ADR-010) escritos em `platform-catalog/catalog/assets/<kind>/`. Cada asset publicado
emite `AssetPublished` no `platform.asset.v1` (ADR-012). O Runbook passa a referenciar
**Operation** (resolvida do tool via o catálogo); tool não resolvida cai em fallback e
é sinalizada. Critérios da Fase 5: runbook por Operation, persona com allow-list,
prompt catalogado, ADR consultável, lifecycle emite evento.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from app.dev_agent.catalog.policy import DEFAULT_POLICIES
from app.dev_agent.catalog.records import DirCatalogSource
from app.dev_agent.events import EventEmitter, EventSink
from app.dev_agent.profiles.registry import PROFILES
from app.dev_agent.runbook.catalog import RUNBOOK_CATALOG

_REPO = Path(__file__).resolve().parents[4]
_ASSETS = _REPO / "platform-catalog" / "catalog" / "assets"
_API_VERSION = "catalog.platform.dev/v1"


def _entity(kind: str, uid: str, spec: dict, *, version: str = "1.0.0",
            lifecycle: str = "active", owner: str = "platform", title: str = "",
            tags: list[str] | None = None, relations: list[dict] | None = None) -> dict:
    return {
        "apiVersion": _API_VERSION, "kind": kind,
        "metadata": {"name": uid, "uid": uid, "title": title or uid, "owner": owner,
                     "tags": tags or [], "lifecycle": lifecycle, "version": version},
        "spec": spec, "relations": relations or [],
    }


# --- builders (source -> asset dicts) ---------------------------------------
def build_runbook_assets(source: DirCatalogSource | None = None) -> list[dict]:
    """Runbook -> asset; cada task referencia a Operation resolvida do tool (fallback: tool)."""
    src = source or DirCatalogSource()
    assets = []
    for rid, rb in RUNBOOK_CATALOG.items():
        tasks, relations, unresolved = [], [], 0
        for tid, t in rb.tasks.items():
            if t.operation_id is not None:
                # Operation-first (ADR-009): a Operation é o alvo; a tool concreta
                # é resolvida do catálogo (determinística), podendo faltar se não
                # houver binding (não deve ocorrer para runbooks entregues).
                op_id = t.operation_id
                resolved = src.record_for_operation(op_id) is not None
                tool = src.tool_for_operation(op_id)
            else:
                # Legacy: tool bound directly; a Operation é resolvida do tool.
                rec = src.record(t.tool)
                op_id = rec.operation_id if rec is not None else None
                resolved = op_id is not None
                tool = t.tool
            if resolved:
                relations.append({"verb": "uses", "target": op_id})
            else:
                unresolved += 1
            tasks.append({"task_id": tid, "operation_id": op_id, "tool": tool,
                          "responsible": t.responsible, "required": t.required,
                          "depends_on": list(t.depends_on), "resolved": resolved})
        assets.append(_entity(
            "Runbook", f"runbook.{rid}",
            {"runbook_id": rid, "description": rb.name, "responsible_profile": rb.responsible_profile,
             "tasks": tasks, "unresolved_tools": unresolved},
            version=rb.version, title=rb.name, tags=["runbook", rb.responsible_profile],
            relations=relations,
        ))
    return assets


def build_persona_and_prompt_assets() -> list[dict]:
    """Persona -> asset com allow-list catalogada (da policy) + Prompt como asset."""
    assets = []
    for pid, cls in sorted(PROFILES.items()):
        fm = getattr(cls, "front_matter", {}) or {}
        pol = DEFAULT_POLICIES.get(pid)
        allow = ({"allowed_effects": sorted(pol.allowed_effects), "max_blast": pol.max_blast,
                  "allowed_domains": sorted(pol.allowed_domains)} if pol else
                 {"allowed_effects": ["read"], "max_blast": "none", "allowed_domains": []})
        prompt_uid = f"prompt.{pid}"
        assets.append(_entity(
            "Persona", f"persona.{pid}",
            {"persona_id": pid, "model": getattr(cls, "model", ""),
             "capabilities": fm.get("capabilities", []), "allow_list": allow},
            title=fm.get("display_name", pid), tags=["persona", pid],
            relations=[{"verb": "uses", "target": prompt_uid}],
        ))
        assets.append(_entity(
            "Prompt", prompt_uid,
            {"persona_id": pid, "content_ref": f"knowledge/profiles/{pid}.md",
             "front_matter_keys": sorted(fm.keys())},
            title=f"system prompt · {pid}", tags=["prompt", pid],
            relations=[{"verb": "part-of", "target": f"persona.{pid}"}],
        ))
    return assets


def build_policy_assets() -> list[dict]:
    """DEFAULT_POLICIES -> Policy asset por persona (governs a persona)."""
    assets = []
    for pid, pol in sorted(DEFAULT_POLICIES.items()):
        assets.append(_entity(
            "Policy", f"policy.{pid}",
            {"subject": pid, "allowed_effects": sorted(pol.allowed_effects),
             "max_blast": pol.max_blast, "allowed_domains": sorted(pol.allowed_domains)},
            title=f"policy · {pid}", tags=["policy", pid],
            relations=[{"verb": "governs", "target": f"persona.{pid}"}],
        ))
    return assets


_ADR_REL = re.compile(r"ADR-(\d{3})")


def build_adr_assets() -> list[dict]:
    """ADR-*.md (raiz) -> ADR asset consultável (title/status + relações a outras ADRs)."""
    assets = []
    for f in sorted(_REPO.glob("ADR-*.md")):
        text = f.read_text(encoding="utf-8", errors="ignore")
        num_m = re.match(r"ADR-(\d{3})", f.name)
        if not num_m:
            continue
        num = num_m.group(1)
        title = text.splitlines()[0].lstrip("# ").strip() if text else f.stem
        status_m = re.search(r"\*\*Status:\*\*\s*([^\n·]+)", text)
        status = status_m.group(1).strip() if status_m else "unknown"
        # relações: as ADRs citadas em "Relacionadas:" (exceto ela mesma)
        rel_line = re.search(r"Relacionadas:\*\*?([^\n]*)", text)
        related = sorted(set(_ADR_REL.findall(rel_line.group(1)))) if rel_line else []
        relations = [{"verb": "derivedFrom", "target": f"adr.{r}"} for r in related if r != num]
        assets.append(_entity(
            "ADR", f"adr.{num}", {"number": num, "status": status, "path": f.name},
            title=title, tags=["adr"], lifecycle="active", relations=relations,
        ))
    return assets


# --- ingestão ---------------------------------------------------------------
def build_all(source: DirCatalogSource | None = None) -> list[dict]:
    return (build_runbook_assets(source) + build_persona_and_prompt_assets()
            + build_policy_assets() + build_adr_assets())


def ingest_all(*, sink: EventSink | None = None, write: bool = True,
               source: DirCatalogSource | None = None) -> dict:
    """Constrói todos os assets, escreve YAML no catálogo e emite AssetPublished."""
    assets = build_all(source)
    emitter = EventEmitter(sink, correlation_id="asset-ingest")
    counts: dict[str, int] = {}
    for a in assets:
        kind = a["kind"]
        counts[kind] = counts.get(kind, 0) + 1
        if write:
            d = _ASSETS / kind.lower()
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{a['metadata']['uid']}.yaml").write_text(
                yaml.safe_dump(a, sort_keys=False, allow_unicode=True), encoding="utf-8")
        emitter.asset_published(asset_ref=a["metadata"]["uid"], kind=kind,
                                version=a["metadata"]["version"], owner=a["metadata"]["owner"])
    return {"total": len(assets), "by_kind": counts,
            "unresolved_runbook_tools": sum(a["spec"].get("unresolved_tools", 0)
                                            for a in assets if a["kind"] == "Runbook")}


def promote(*, asset_ref: str, kind: str, version: str, approver: str,
            sink: EventSink | None = None, from_: str = "draft", to: str = "active") -> None:
    """Promove um asset (draft->active) e emite AssetPromoted."""
    EventEmitter(sink, correlation_id=f"promote/{asset_ref}").asset_promoted(
        asset_ref=asset_ref, kind=kind, version=version, from_=from_, to=to, approver=approver)


def main() -> None:
    from app.dev_agent.events import LoggingEventSink
    summary = ingest_all(sink=LoggingEventSink())
    print(f"ingeridos {summary['total']} assets: {summary['by_kind']}; "
          f"tools de runbook não resolvidas: {summary['unresolved_runbook_tools']}")


if __name__ == "__main__":
    main()
