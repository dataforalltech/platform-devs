"""Importador markdown→DB do hub de governança (ADR-018 Fase 1b + 1c).

Fase 1b: importa as **7 camadas estruturadas** do hub (`principles/adr/standards/
reference-architecture/runbooks/it/decisions`) — as únicas com front-matter
uniformemente obrigatório (`type/camada/status/escopo/ultima_atualizacao`) e
convenção de nome de arquivo estável o bastante para derivar um `directive_uid`.

Fase 1c: soma `lib-change-requests/` (LCR — metadados de gestão de mudança
capturados em `GovLcrDetailRow`/`GovLcrSubstitutionRow`, ver `db/store.py`),
`handoffs/` e `specs/` — estas 3 têm front-matter mais heterogêneo (o
`validate_hub.py` do template não as valida estruturalmente), então a
derivação de UID é mais permissiva (nome do arquivo inteiro, sem regex de
convenção) e o campo `status` tem um fallback ("aceito") quando ausente em
handoffs/specs — documentado como heurística, não uma convenção confirmada.

Deliberadamente FORA de escopo (ver HANDOFF-GUARDIAN-FASE1.md):
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
from typing import Any

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
    "lib-change-requests": "lib_change_request",
    "handoffs": "handoff",
    "specs": "spec",
}

# Camadas SEM convenção de nome de arquivo uniformemente imposta pelo hub (Fase
# 1c) — o UID é o stem inteiro do arquivo, sem regex de validação de formato.
# LCR em particular permite números duplicados com slugs diferentes
# (ex.: dois arquivos "LCR-005-*" coexistindo com assuntos distintos), então
# usar só o prefixo numérico colidiria — o stem completo é a única chave segura.
_LOOSE_UID_LAYERS = frozenset({"lib-change-requests", "handoffs", "specs"})

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
    """Um documento do hub já parseado e pronto para `GuardianStore.import_directive`.

    `lcr_detail`/`lcr_substituted_by` só são preenchidos para
    `kind == "lib_change_request"` (Fase 1c) — `None`/vazio para os demais kinds.
    `sections`/`governed_by` (Fase 2) são computados para QUALQUER kind — vazios
    quando o documento não tem heading `##` ou campo `governado_por`.
    """

    directive_uid: str
    kind: str
    title: str
    scope: str
    status: str
    body_context: str | None
    body_decision: str | None
    source_path: str  # relativo ao hub_root — só para diagnóstico, não persistido
    lcr_detail: dict[str, Any] | None = None
    lcr_substituted_by: tuple[str, ...] = ()
    sections: tuple[dict[str, Any], ...] = ()
    governed_by: tuple[str, ...] = ()


def _derive_uid(layer: str, filename: str) -> str:
    if layer in _LOOSE_UID_LAYERS:
        return filename[:-3] if filename.endswith(".md") else filename
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
        if layer in ("handoffs", "specs"):
            # Fallback documentado (não uma convenção confirmada do hub): estas
            # 2 camadas não têm front-matter estrutural uniformemente exigido.
            status = "aceito"
        else:
            raise ImporterError(f"{rel}: front-matter sem campo 'status'")

    body_context, body_decision = _split_body(body)
    lcr_detail = (
        _extract_lcr_detail(front_matter) if layer == "lib-change-requests" else None
    )
    lcr_substituted_by = _extract_lcr_substituted_by(front_matter)
    sections = _parse_sections(body)
    governed_by = _extract_governed_by(front_matter)
    return ImportedDoc(
        directive_uid=uid,
        kind=kind,
        title=title,
        scope="platform",  # ADR-018: docs do hub são globais, nunca archetype/project
        status=status,
        body_context=body_context,
        body_decision=body_decision,
        source_path=rel,
        lcr_detail=lcr_detail,
        sections=sections,
        governed_by=governed_by,
        lcr_substituted_by=lcr_substituted_by,
    )


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _extract_lcr_detail(front_matter: dict) -> dict[str, Any]:
    """Campos de gestão de mudança do LCR (ADR-018 Fase 1c) — front-matter direto,
    sem derivação. `None` onde ausente (colunas opcionais em `GovLcrDetailRow`)."""
    return {
        "biblioteca": front_matter.get("biblioteca"),
        "repositorio": front_matter.get("repositorio"),
        "versao_atual": _stringify(front_matter.get("versao_atual")),
        "versao_alvo": _stringify(front_matter.get("versao_alvo")),
        "tipo": front_matter.get("tipo"),
        "breaking": bool(front_matter.get("breaking", False)),
        "urgencia": front_matter.get("urgencia"),
        "aprovador": front_matter.get("aprovador"),
        "solicitante": front_matter.get("solicitante"),
        "achado": front_matter.get("achado"),
        "data_solicitacao": _stringify(front_matter.get("data_solicitacao")),
    }


def _extract_lcr_substituted_by(front_matter: dict) -> tuple[str, ...]:
    """`substituido_por` é uma LISTA no front-matter do LCR — normalizada em
    arestas (`GovLcrSubstitutionRow`), nunca serializada de volta (D18.2)."""
    raw = front_matter.get("substituido_por")
    if isinstance(raw, list):
        return tuple(str(item) for item in raw)
    if isinstance(raw, str) and raw.strip():
        return (raw.strip(),)
    return ()


def _extract_governed_by(front_matter: dict) -> tuple[str, ...]:
    """`governado_por` (ADR-018 Fase 2) — visto em `it/`/`decisions/`/LCR como
    texto livre (uma lista YAML OU uma string "STD-A, STD-B" separada por
    vírgula) referenciando os Standards/ADRs de quem o documento deriva.
    Normalizado em arestas `relation_type='governed_by'`, nunca guardado como
    string livre numa coluna."""
    raw = front_matter.get("governado_por")
    if isinstance(raw, list):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    if isinstance(raw, str) and raw.strip():
        return tuple(p.strip() for p in raw.split(",") if p.strip())
    return ()


def _slugify_heading(heading: str) -> str:
    ascii_ish = re.sub(r"[^\w\s-]", "", heading, flags=re.UNICODE).strip().lower()
    slug = re.sub(r"[\s_]+", "_", ascii_ish) or "secao"
    return slug[:80]


_SECTION_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _parse_sections(body: str) -> tuple[dict[str, Any], ...]:
    """Extrai TODAS as seções `##` do corpo, em ordem (ADR-018 Fase 2) — usado
    para popular `gov_directive_section`. Genérico por design: não hardcoda
    headings específicos por kind (o hub varia a convenção por camada — ADR usa
    Contexto/Decisão/Consequências, Princípio usa Enunciado/Racional/
    Implicações, IT usa Pré-requisitos/Procedimento — ver pesquisa no
    handoff); só segmenta por heading de nível 2, o que cobre todas elas
    uniformemente."""
    stripped = body.strip()
    matches = list(_SECTION_HEADING.finditer(stripped))
    if not matches:
        return ()
    sections = []
    for idx, m in enumerate(matches):
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(stripped)
        heading = m.group(1).strip()
        content = stripped[start:end].strip() or None
        sections.append(
            {
                "order_index": idx,
                "section_key": _slugify_heading(heading),
                "heading": heading,
                "content": content,
            }
        )
    return tuple(sections)


def discover_hub_files(hub_root: Path) -> list[tuple[str, Path]]:
    """Lista (layer, path) de todo `*.md` em `LAYER_KIND` (as 7 camadas estruturadas
    + lib-change-requests/handoffs/specs da Fase 1c), excluindo `README.md` (índice
    da pasta, não é uma diretriz)."""
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


# ---------------------------------------------------------------------------
# Matriz de rastreabilidade central (documentation-model.md) — validado contra
# o arquivo REAL do platform-service-template (80 relações extraídas, "MCP
# Gateway †" corretamente pulado — não tem ADR de 4 dígitos, é referência
# externa por prosa —, anotações *(retirado)*/*(substituído)* stripadas token
# a token, exceção STD-GW-001 capturada). Diferente de scan_hub (um arquivo por
# diretriz), esta é UMA tabela central que referencia várias diretrizes por ID
# textual — parser à parte, não integrado ao fluxo por-arquivo de import_hub.
# ---------------------------------------------------------------------------

_ANNOTATION = re.compile(r"\*\([^)]*\)\*")  # mesmo padrão de validate_hub.py
_ADR_ROW_UID = re.compile(r"^(\d{4})\b")
_EMPTY_CELL = frozenset({"-", "—", "–"})

# Coluna do cabeçalho (substring, case-insensitive) → relation_type. A ordem
# das colunas na tabela real é ADR|Princípio(s)|Standard(s)|Reference Arch.|
# Runbook(s), mas casamos por substring (não posição) para tolerar reordenação.
_MATRIX_COLUMN_RELATION: dict[str, str] = {
    "princípio": "traces_to_principle",
    "principio": "traces_to_principle",
    "standard": "traces_to_standard",
    "reference": "traces_to_reference_arch",
    "runbook": "traces_to_runbook",
}


def _clean_cell_tokens(cell: str) -> list[str]:
    """Remove anotações `*(...)*`, separa por vírgula, descarta placeholders
    de célula vazia (`-`/`—`/`–`)."""
    cleaned = _ANNOTATION.sub("", cell).strip()
    if not cleaned or cleaned in _EMPTY_CELL:
        return []
    return [
        t for t in (p.strip() for p in cleaned.split(",")) if t and t not in _EMPTY_CELL
    ]


def _find_section(text: str, heading_substring: str) -> str | None:
    """Corpo da seção cujo heading `##` contém `heading_substring`
    (case-insensitive), até o próximo heading de mesmo nível ou o fim do texto."""
    pattern = re.compile(
        rf"^##\s+.*{re.escape(heading_substring)}.*$", re.IGNORECASE | re.MULTILINE
    )
    m = pattern.search(text)
    if not m:
        return None
    start = m.end()
    next_heading = re.search(r"^##\s+", text[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end]


def _parse_markdown_table(section: str) -> tuple[list[str], list[list[str]]]:
    """Extrai a PRIMEIRA tabela markdown de uma seção: (headers, rows). Pula a
    linha separadora (`|---|---|`)."""
    lines = [ln for ln in section.splitlines() if ln.strip().startswith("|")]
    if len(lines) < 2:
        return [], []

    def _split_row(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    headers = _split_row(lines[0])
    rows = []
    for line in lines[1:]:
        cells = _split_row(line)
        if all(re.fullmatch(r":?-{1,}:?", c) for c in cells):
            continue  # linha separadora do markdown
        rows.append(cells)
    return headers, rows


def parse_traceability_matrix(model_text: str) -> dict[str, Any]:
    """Parseia `documentation-model.md` (texto já lido) → relações tipadas para
    `GuardianStore.add_relation`, exceções documentadas, e linhas puladas (não
    batem no padrão de ADR de 4 dígitos — ex. "MCP Gateway †", uma referência
    externa citada por prosa, não por arquivo local).

    Retorna `{"relations": [...], "exceptions": [...], "skipped_rows": [...]}`.
    Não faz I/O nem persiste nada — puro parsing, mesmo padrão de `scan_hub`."""
    relations: list[dict[str, str]] = []
    skipped_rows: list[str] = []

    matrix_section = _find_section(model_text, "rastreabilidade")
    if matrix_section:
        headers, rows = _parse_markdown_table(matrix_section)
        col_relation: dict[int, str] = {}
        for idx, header in enumerate(headers[1:], start=1):
            header_lower = header.lower()
            for key, relation_type in _MATRIX_COLUMN_RELATION.items():
                if key in header_lower:
                    col_relation[idx] = relation_type
                    break
        for row in rows:
            if not row:
                continue
            adr_cell = _ANNOTATION.sub("", row[0]).strip()
            m = _ADR_ROW_UID.match(adr_cell)
            if not m:
                skipped_rows.append(row[0])
                continue
            from_uid = f"ADR-{m.group(1)}"
            for idx, relation_type in col_relation.items():
                if idx >= len(row):
                    continue
                for token in _clean_cell_tokens(row[idx]):
                    relations.append(
                        {
                            "from_uid": from_uid,
                            "to_ref": token,
                            "relation_type": relation_type,
                        }
                    )

    exceptions: list[dict[str, str]] = []
    exceptions_section = _find_section(model_text, "fora da matriz")
    if exceptions_section:
        _, exception_rows = _parse_markdown_table(exceptions_section)
        for row in exception_rows:
            if len(row) >= 3:
                exceptions.append({"id": row[0], "reason": row[1], "source": row[2]})

    return {
        "relations": relations,
        "exceptions": exceptions,
        "skipped_rows": skipped_rows,
    }


__all__ = [
    "LAYER_KIND",
    "IMPORT_STATUS_ALIASES",
    "ImporterError",
    "ImportedDoc",
    "parse_markdown_doc",
    "discover_hub_files",
    "scan_hub",
    "parse_traceability_matrix",
]
