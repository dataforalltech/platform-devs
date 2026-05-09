"""Loader de arquivos Markdown da knowledge-base.

Cada arquivo `.md` na pasta knowledge-base/ é carregado como um KnowledgeDocument
e quebrado em seções (a partir dos headings `#`/`##`/`###`). A estrutura é
intencionalmente simples para permitir busca textual sem indexação externa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class KnowledgeSection:
    """Uma seção dentro de um documento Markdown."""

    heading: str
    level: int
    content: str
    start_line: int


@dataclass
class KnowledgeDocument:
    """Documento Markdown carregado, com seções pré-extraídas."""

    name: str
    path: Path
    raw_text: str
    sections: list[KnowledgeSection] = field(default_factory=list)

    @property
    def lower_text(self) -> str:
        return self.raw_text.lower()


class MarkdownLoader:
    """Carrega todos os .md de uma pasta para a memória."""

    def __init__(self, kb_path: Path) -> None:
        self.kb_path = kb_path

    def load_all(self) -> list[KnowledgeDocument]:
        if not self.kb_path.exists():
            raise FileNotFoundError(
                f"Pasta knowledge-base não encontrada: {self.kb_path}. "
                "Verifique GOVERNANCE_KB_PATH ou crie a pasta."
            )
        if not self.kb_path.is_dir():
            raise NotADirectoryError(f"GOVERNANCE_KB_PATH não é um diretório: {self.kb_path}")

        docs: list[KnowledgeDocument] = []
        for path in sorted(self.kb_path.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            sections = self._extract_sections(text)
            docs.append(
                KnowledgeDocument(
                    name=path.name,
                    path=path,
                    raw_text=text,
                    sections=sections,
                )
            )
        return docs

    @staticmethod
    def _extract_sections(text: str) -> list[KnowledgeSection]:
        """Quebra o texto por headings; cada seção contém todo o conteúdo até o próximo heading."""
        matches = list(_HEADING_RE.finditer(text))
        if not matches:
            return [
                KnowledgeSection(
                    heading="(documento)",
                    level=0,
                    content=text.strip(),
                    start_line=1,
                )
            ]

        sections: list[KnowledgeSection] = []
        for idx, match in enumerate(matches):
            level = len(match.group(1))
            heading = match.group(2).strip()
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            start_line = text.count("\n", 0, match.start()) + 1
            sections.append(
                KnowledgeSection(
                    heading=heading,
                    level=level,
                    content=content,
                    start_line=start_line,
                )
            )
        return sections
