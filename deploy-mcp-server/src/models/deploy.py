"""Modelos Pydantic ativos do deploy-mcp-server."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MergeMethod = Literal["squash", "merge", "rebase"]
PRState = Literal["open", "closed", "all"]


class FileChange(BaseModel):
    """Arquivo a criar ou atualizar em um commit."""

    path: str = Field(..., description="Caminho relativo ao root do repositório.")
    content: str = Field(..., description="Conteúdo completo do arquivo.")


class CheckRun(BaseModel):
    """Check do provedor Git; não implica GitHub Actions."""

    name: str
    status: str
    conclusion: str | None = None
    url: str


class PRInfo(BaseModel):
    number: int
    title: str
    state: str
    url: str
    head: str
    base: str
    head_sha: str
    mergeable: bool | None = None
    mergeable_state: str | None = None
    draft: bool = False
    checks: list[CheckRun] = Field(default_factory=list)
