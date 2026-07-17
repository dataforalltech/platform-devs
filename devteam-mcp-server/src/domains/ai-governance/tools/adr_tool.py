"""Tool create_adr — cria docs/decisions/adr-NNNN.md usando o template canônico.

A ADR é escrita no repositório alvo (repo_path) ou, quando omitido, na pasta
docs/decisions/ relativa ao pai da knowledge-base (assumindo que o servidor
está co-localizado com o repositório).
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..knowledge.governance_repository import GovernanceRepository
from ..utils.validators import require_non_empty_string

_TZ = ZoneInfo("America/Sao_Paulo")

_ADR_TEMPLATE = """\
---
title: ADR-{number:04d} — {title}
type: adr
audiencia: devs + tech-lead
ultima_atualizacao: {datetime_str} America/Sao_Paulo
autor_ultima_edicao: ai-agent
status: proposto
data_decisao: {date_str}
decisores: tech-lead|platform-owner
escopo: plataforma
---

# ADR-{number:04d} — {title}

> **Architectural Decision Record.** Registra **uma** decisão arquitetural não-óbvia,
> seu contexto e suas consequências. Imutável após `status: aceito`.
> Se a decisão mudar, crie nova ADR e marque esta como `status: substituido`.

---

## 1. Status

`proposto` — desde `{date_str}`.

---

## 2. Contexto

{context}

---

## 3. Decisão

{decision}

---

## 4. Alternativas consideradas

| Alternativa | Por que NÃO foi escolhida |
|---|---|
| *(preencher)* | *(preencher)* |

---

## 5. Consequências

{consequences}

---

## 6. Validação

*(Como saberemos se a decisão foi acertada? Métricas, prazo de revisão.
Ex: "Revisar após 3 meses de produção se p95 latência do serviço X > 200ms")*

---

## 7. Referências

- AGENTS.md: *(seções relevantes)*
- ADRs relacionadas: *(se houver)*
- Discussão: *(link para PR ou issue)*

---

**Convenção de numeração:** ADRs são numeradas sequencialmente (`adr-0001.md`, `adr-0002.md`, …).
Nunca renumere — números de ADRs substituídas ficam vazios intencionalmente.
"""


def create_adr(
    repo: GovernanceRepository,
    title: str,
    context: str,
    decision: str,
    consequences: str,
    repo_path: str | None = None,
) -> dict:
    """Cria docs/decisions/adr-NNNN.md no repositório alvo.

    Parâmetros:
      title        — título curto da decisão (ex: "Usar Redis para cache de permissões")
      context      — cenário, forças em jogo e restrições (5-15 linhas)
      decision     — a decisão em voz ativa: "Vamos usar X para Y porque Z."
      consequences — consequências positivas, negativas e neutras
      repo_path    — caminho absoluto para o repositório alvo.
                     Se omitido, usa o pai da knowledge-base.
    """
    require_non_empty_string(title, "title")
    require_non_empty_string(context, "context")
    require_non_empty_string(decision, "decision")
    require_non_empty_string(consequences, "consequences")

    # Resolve caminho base
    if repo_path:
        base = Path(repo_path)
    else:
        # KB path típico: .../knowledge-base/ → sobe para raiz do repositório
        base = repo.kb_path.parent

    decisions_dir = base / "docs" / "decisions"

    if not decisions_dir.exists():
        try:
            decisions_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {
                "created": False,
                "error": f"Não foi possível criar {decisions_dir}: {e}",
                "notes": [
                    "Passe repo_path explicitamente apontando para a raiz do repositório alvo.",
                    f"Caminho tentado: {decisions_dir}",
                ],
            }

    # Próximo número de ADR
    existing = sorted(decisions_dir.glob("adr-*.md"))
    numbers: list[int] = []
    for f in existing:
        m = re.match(r"adr-(\d{4})\.md", f.name)
        if m:
            numbers.append(int(m.group(1)))
    next_num = max(numbers) + 1 if numbers else 1

    now = datetime.now(tz=_TZ)
    datetime_str = now.strftime("%Y-%m-%d %H:%M")
    date_str = now.strftime("%Y-%m-%d")

    content = _ADR_TEMPLATE.format(
        number=next_num,
        title=title,
        datetime_str=datetime_str,
        date_str=date_str,
        context=context,
        decision=decision,
        consequences=consequences,
    )

    filename = f"adr-{next_num:04d}.md"
    target = decisions_dir / filename

    if target.exists():
        return {
            "created": False,
            "error": f"Arquivo {filename} já existe — isso não deveria acontecer.",
            "notes": ["Verifique manualmente docs/decisions/ e ajuste a numeração."],
        }

    try:
        target.write_text(content, encoding="utf-8")
    except OSError as e:
        return {
            "created": False,
            "error": f"Falha ao escrever {target}: {e}",
        }

    # Caminho relativo seguro (funciona em Python 3.9+)
    try:
        relative_path = str(target.relative_to(base))
    except ValueError:
        relative_path = str(target)

    return {
        "created": True,
        "path": relative_path,
        "absolute_path": str(target),
        "adr_number": next_num,
        "filename": filename,
        "notes": [
            "ADR criada com status=proposto. Revisar e mudar para aceito após aprovação.",
            "Preencher a seção '4. Alternativas consideradas' manualmente.",
            "Preencher '7. Referências' com seções relevantes do AGENTS.md.",
        ],
    }
