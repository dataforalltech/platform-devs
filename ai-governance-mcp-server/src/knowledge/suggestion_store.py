"""SuggestionStore — armazena sugestões cross-repo como arquivos JSON.

Estratégia: 1 sugestão = 1 arquivo `<id>.json` em `<store_dir>/`. ID é
ordenável por timestamp (`YYYYMMDDTHHMMSS-XXXXXXXX`), então `list()` devolve
ordem cronológica natural sem indexação.

Vantagens:

- Audit trail por padrão (cada sugestão é um arquivo git-trackeável).
- Sem concorrência: uma chamada MCP é atômica em termos de filesystem.
- Sem dep externa.

A camada nunca expõe paths absolutos para fora — só o `id`. Persistência é
detalhe interno; futuro storage pode ser DB sem mexer nas tools.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models.suggestion import (
    StatusChange,
    Suggestion,
    SuggestionCategory,
    SuggestionFilters,
    SuggestionSeverity,
    SuggestionStatus,
)
from ..utils.logger import get_logger

_log = get_logger(__name__)

_ID_RE = re.compile(r"^\d{8}T\d{12}-[a-f0-9]{8}$")


class SuggestionStoreError(ValueError):
    """Erro de persistência ou validação de sugestão."""


class SuggestionStore:
    """File-per-suggestion JSON store."""

    def __init__(self, store_dir: Path) -> None:
        self.store_dir = store_dir
        self.store_dir.mkdir(parents=True, exist_ok=True)
        _log.info(
            "suggestion_store_ready",
            extra={"extras": {"path": str(self.store_dir)}},
        )

    # ------------------------------------------------------------------ #
    # ID                                                                  #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _generate_id() -> str:
        # Inclui microssegundos para garantir ordering monotônica mesmo em
        # criações no mesmo segundo. O sufixo UUID resolve colisões muito
        # improváveis em microssegundos compartilhados.
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        suffix = uuid.uuid4().hex[:8]
        return f"{ts}-{suffix}"

    @staticmethod
    def _validate_id(suggestion_id: str) -> None:
        if not _ID_RE.match(suggestion_id):
            raise SuggestionStoreError(
                f"id inválido: {suggestion_id!r}. "
                "Formato esperado: YYYYMMDDTHHMMSSffffff-XXXXXXXX"
            )

    def _path(self, suggestion_id: str) -> Path:
        self._validate_id(suggestion_id)
        return self.store_dir / f"{suggestion_id}.json"

    # ------------------------------------------------------------------ #
    # Operações                                                            #
    # ------------------------------------------------------------------ #
    def create(
        self,
        *,
        source_agent: str,
        target_repo: str,
        category: SuggestionCategory,
        severity: SuggestionSeverity,
        title: str,
        description: str,
        source_repo: str | None = None,
        related_files: list[str] | None = None,
        references: list[str] | None = None,
        target_repo_canonical: str | None = None,
    ) -> Suggestion:
        """Cria uma nova sugestão e persiste no disco."""
        now = datetime.now(timezone.utc).isoformat()
        suggestion_id = self._generate_id()
        suggestion = Suggestion(
            id=suggestion_id,
            created_at=now,
            source_agent=source_agent,
            source_repo=source_repo,
            target_repo=target_repo,
            target_repo_canonical=target_repo_canonical,
            category=category,
            severity=severity,
            title=title,
            description=description,
            related_files=related_files or [],
            references=references or [],
            status="pending",
            status_history=[
                StatusChange(ts=now, status="pending", note="Criada", by=source_agent),
            ],
        )
        self._write(suggestion)
        _log.info(
            "suggestion_created",
            extra={
                "extras": {
                    "id": suggestion.id,
                    "target_repo": target_repo,
                    "category": category,
                    "severity": severity,
                }
            },
        )
        return suggestion

    def get(self, suggestion_id: str) -> Suggestion | None:
        path = self._path(suggestion_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise SuggestionStoreError(
                f"falha ao ler {suggestion_id}: {e}"
            ) from e
        return Suggestion.model_validate(data)

    def list(self, filters: SuggestionFilters | None = None) -> list[Suggestion]:
        """Lista sugestões aplicando filtros. Ordem: id descendente (mais novos primeiro)."""
        f = filters or SuggestionFilters()
        results: list[Suggestion] = []
        # Itera arquivos em ordem reversa pelo nome (id é sortable).
        for path in sorted(self.store_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                _log.warning(
                    "suggestion_unreadable",
                    extra={"extras": {"file": path.name}},
                )
                continue
            suggestion = Suggestion.model_validate(data)
            if f.target_repo and suggestion.target_repo != f.target_repo and suggestion.target_repo_canonical != f.target_repo:
                continue
            if f.status and suggestion.status != f.status:
                continue
            if f.category and suggestion.category != f.category:
                continue
            if f.severity and suggestion.severity != f.severity:
                continue
            if f.source_agent and suggestion.source_agent != f.source_agent:
                continue
            results.append(suggestion)
            if len(results) >= f.limit:
                break
        return results

    def update_status(
        self,
        suggestion_id: str,
        new_status: SuggestionStatus,
        *,
        note: str | None = None,
        by: str | None = None,
    ) -> Suggestion:
        suggestion = self.get(suggestion_id)
        if suggestion is None:
            raise SuggestionStoreError(f"sugestão não encontrada: {suggestion_id!r}")
        if new_status == suggestion.status and not note:
            # Sem mudança real — não polui o histórico.
            return suggestion
        change = StatusChange(
            ts=datetime.now(timezone.utc).isoformat(),
            status=new_status,
            note=note,
            by=by,
        )
        suggestion.status = new_status
        suggestion.status_history.append(change)
        self._write(suggestion)
        _log.info(
            "suggestion_status_changed",
            extra={
                "extras": {
                    "id": suggestion_id,
                    "from": suggestion.status_history[-2].status
                    if len(suggestion.status_history) >= 2
                    else None,
                    "to": new_status,
                    "by": by,
                }
            },
        )
        return suggestion

    def stats(self) -> dict[str, Any]:
        """Métricas resumidas do store."""
        total = 0
        by_status: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        by_target: dict[str, int] = {}
        for path in self.store_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            total += 1
            by_status[data.get("status", "?")] = (
                by_status.get(data.get("status", "?"), 0) + 1
            )
            by_severity[data.get("severity", "?")] = (
                by_severity.get(data.get("severity", "?"), 0) + 1
            )
            target = data.get("target_repo_canonical") or data.get("target_repo", "?")
            by_target[target] = by_target.get(target, 0) + 1
        return {
            "total": total,
            "by_status": dict(sorted(by_status.items())),
            "by_severity": dict(sorted(by_severity.items())),
            "by_target": dict(sorted(by_target.items(), key=lambda x: -x[1])),
            "store_dir": str(self.store_dir.name),
        }

    # ------------------------------------------------------------------ #
    # Internos                                                             #
    # ------------------------------------------------------------------ #
    def _write(self, suggestion: Suggestion) -> None:
        path = self._path(suggestion.id)
        # Escreve em arquivo temporário e move (atomicidade básica).
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(
                json.dumps(
                    suggestion.model_dump(),
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=False,
                )
                + "\n",
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError as e:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            raise SuggestionStoreError(
                f"falha ao gravar {suggestion.id}: {e}"
            ) from e
