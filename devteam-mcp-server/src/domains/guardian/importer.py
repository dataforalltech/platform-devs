"""Importador markdown→DB do hub de governança (ADR-018 Fase 1b).

Escopo HONESTO desta fase (documentado para não prometer mais do que entrega):

Importa as **7 camadas estruturadas** do hub (`principles/adr/standards/
reference-architecture/runbooks/it/decisions`) — as únicas com front-matter
uniformemente obrigatório (`type/camada/status/escopo/ultima_atualizacao`) e
convenção de nome de arquivo estável o bastante para derivar um `directive_uid`.

Deliberadamente FORA de escopo nesta fase (ver HANDOFF-GUARDIAN-FASE1.md):
- `lib-change-requests/`, `handoffs/`, `specs/` — front-matter rico e
  heterogêneo (vocabulário de status próprio, campos de gestão de mudança sem
  coluna equivalente) que exigiria extensão de schema (EAV ou colunas
  específicas por kind) — Fase 1c.
- Relações `governado_por`/matriz de rastreabilidade N:N:N:N
  (`documentation-model.md`) — exige uma tabela de arestas tipadas
  (`gov_directive_reference`), fora do núcleo versionado da Fase 1 — Fase 2.
- Paridade completa com `scripts/validate_hub.py` do template (templates YAML,
  políticas K8s/Istio, Statement of Applicability, "semantic currentness") —
  esse script cobre superfícies de infra/segurança que não são
  responsabilidade do guardian (que é "registry+policy, NÃO executor" — D18).
  `validate_hub()` aqui cobre só a parte de GOVERNANÇA DOCUMENTAL: drift entre
  o filesystem e o `gov_directive`/`gov_directive_version` persistidos.

Corpo (`body_context`/`body_decision`): heurística de split por heading —
Fase 2 é que trará as child tables tipadas por seção; aqui o corpo inteiro é
preservado (nada se perde), só dividido em dois campos por conveniência.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

# Camada de diretório → kind do guardian (KIND_CAPABILITIES em db/store.py).
LAYER_KIND: dict[str, str] = {
    "principles": "principle",
    "adr": "adr",
    "standards": "standard",
    "reference-architecture": "reference_arch",
    "runbooks": "runbook",
    "it": "work_instruction",
    "decisions": "platform_decision",
}

_FRONT_MATTER = re.compile(r"^---\r?\n(?P<yaml>.*?)\r?\n---\r?\n?", re.DOTALL)
_H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_DECISION_HEADING = re.compile(
    r"^##\s+(Decisão|Decision|MUST)\b.*$", re.IGNORECASE | re.MULTILINE
)
_TITLE_PREFIX = re.compile(r"^[A-Z]+-[\w-]+\s*[—-]\s*", re.IGNORECASE)

# UID derivado do NOME DE ARQUIVO (mais estável que o front-matter, que nem sempre
# tem um campo de id explícito — ver achados da pesquisa no handoff).
_UID_PATTERNS: dict[str, re.Pattern[str]] = {
    "adr": re.compile(r"^(?P<num>\d{4})-"),
    "principles": re.compile(r"^(?P<uid>P-\d{3})-"),
    "standards": re.compile(r"^(?P<uid>STD-[A-Z]+-\d{3})-"),
    "reference-architecture": re.compile(r"^(?P<uid>ARCH-\d{3})-"),
    "runbooks": re.compile(r"^(?P<uid>RUNBOOK-[a-z0-9-]+)\.md$"),
    "it": re.compile(r"^(?P<uid>IT-\d{3})-"),
    # decisions/adr-0001.md tem namespace PRÓPRIO — colidiria com adr/0001-*.md
    # se usássemos "ADR-0001" para os dois (são documentos DIFERENTES: ADR de
    # produto/serviço vs. ADR de escopo plataforma).
    "decisions": re.compile(r"^adr-(?P<num>\d{4})\.md$"),
}

# Vocabulário de status aceito na importação — superset do STATUS_VOCAB core do
# guardian (db/store.py) porque o hub real tem drift observado (`vigente` em
# runbooks, `historico-substituido` em princípios/adrs históricos). Ver seed
# desses códigos extras em GuardianStore.seed_reference_data.
IMPORT_STATUS_ALIASES: dict[str, str] = {
    "vigente": "aceito",
}


class ImporterError(ValueError):
    """Erro ao parsear um arquivo do hub — não aborta o scan, é coletado por arquivo."""


@dataclass(frozen=True)
class ImportedDoc:
    """Um documento do hub já parseado e pronto para `GuardianStore.import_directive`."""

    directive_uid: str
    kind: str
    title: str
    scope: str
    status: str
    body_context: str | None
    body_decision: str | None
    source_path: str  # relativo ao hub_root — só para diagnóstico, não persistido


def _derive_uid(layer: str, filename: str) -> str:
    pattern = _UID_PATTERNS[layer]
    m = pattern.match(filename)
    if not m:
        raise ImporterError(
            f"nome de arquivo não bate com a convenção de {layer!r}: {filename!r}"
        )
    if layer == "adr":
        return f"ADR-{m.group('num')}"
    if layer == "decisions":
        return f"PLATFORM-ADR-{m.group('num')}"
    return m.group("uid")


def _extract_title(front_matter: dict, body: str, fallback: str) -> str:
    title = front_matter.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    h1 = _H1.search(body)
    if h1:
        return _TITLE_PREFIX.sub("", h1.group(1)).strip()
    return fallback


def _split_body(body: str) -> tuple[str | None, str | None]:
    """Heurística Fase 1b: divide em contexto/decisão pelo primeiro heading de
    decisão conhecido. Sem heading correspondente, tudo vira body_context —
    nada é descartado."""
    stripped = body.strip()
    if not stripped:
        return None, None
    m = _DECISION_HEADING.search(stripped)
    if not m:
        return stripped, None
    context = stripped[: m.start()].strip()
    decision = stripped[m.start() :].strip()
    return (context or None), (decision or None)


def parse_markdown_doc(layer: str, path: Path, hub_root: Path) -> ImportedDoc:
    """Parseia um único arquivo do hub. Levanta `ImporterError` com uma mensagem
    clara em qualquer falha (sem front-matter, campo obrigatório ausente, status
    fora do vocabulário aceito, nome de arquivo fora da convenção)."""
    rel = str(path.relative_to(hub_root))
    text = path.read_text(encoding="utf-8")
    m = _FRONT_MATTER.match(text)
    if not m:
        raise ImporterError(f"{rel}: sem front-matter YAML (--- ... ---) no topo")
    try:
        front_matter = yaml.safe_load(m.group("yaml")) or {}
    except yaml.YAMLError as exc:
        raise ImporterError(f"{rel}: front-matter YAML inválido ({exc})") from exc
    if not isinstance(front_matter, dict):
        raise ImporterError(f"{rel}: front-matter não é um mapeamento YAML")

    body = text[m.end() :]
    kind = LAYER_KIND[layer]
    uid = _derive_uid(layer, path.name)
    title = _extract_title(front_matter, body, fallback=path.stem)

    raw_status = str(front_matter.get("status") or "").strip()
    status = IMPORT_STATUS_ALIASES.get(raw_status, raw_status)
    if not status:
        raise ImporterError(f"{rel}: front-matter sem campo 'status'")

    body_context, body_decision = _split_body(body)
    return ImportedDoc(
        directive_uid=uid,
        kind=kind,
        title=title,
        scope="platform",  # ADR-018: archetype colapsado em platform por ora
        status=status,
        body_context=body_context,
        body_decision=body_decision,
        source_path=rel,
    )


def discover_hub_files(hub_root: Path) -> list[tuple[str, Path]]:
    """Lista (layer, path) de todo `*.md` nas 7 camadas estruturadas, excluindo
    `README.md` (índice da pasta, não é uma diretriz)."""
    found: list[tuple[str, Path]] = []
    for layer, layer_dir in ((layer, hub_root / layer) for layer in LAYER_KIND):
        if not layer_dir.is_dir():
            continue
        for path in sorted(layer_dir.glob("*.md")):
            if path.name.upper() == "README.md".upper():
                continue
            found.append((layer, path))
    return found


def scan_hub(hub_root: Path) -> tuple[list[ImportedDoc], list[dict[str, str]]]:
    """Varre o hub inteiro; retorna (docs parseados com sucesso, erros por arquivo).

    Um arquivo malformado NÃO aborta o scan — vira uma entrada em `errors`
    (mesmo padrão de "loud via log" do auto-discovery de domínios).
    """
    docs: list[ImportedDoc] = []
    errors: list[dict[str, str]] = []
    for layer, path in discover_hub_files(hub_root):
        try:
            docs.append(parse_markdown_doc(layer, path, hub_root))
        except ImporterError as exc:
            errors.append({"path": str(path.relative_to(hub_root)), "error": str(exc)})
    return docs, errors


__all__ = [
    "LAYER_KIND",
    "IMPORT_STATUS_ALIASES",
    "ImporterError",
    "ImportedDoc",
    "parse_markdown_doc",
    "discover_hub_files",
    "scan_hub",
]
