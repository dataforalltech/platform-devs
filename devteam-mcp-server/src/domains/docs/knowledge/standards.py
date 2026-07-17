from __future__ import annotations

# Tipos de doc detectáveis por nome de arquivo ou conteúdo
DOC_TYPES: dict[str, list[str]] = {
    "readme": ["README.md", "README.rst", "readme.md"],
    "changelog": ["CHANGELOG.md", "CHANGELOG.rst", "HISTORY.md"],
    "agents": ["AGENTS.md", "CLAUDE.md"],
    "adr": ["ADR-", "adr-", "docs/adr/", "docs/decisions/"],
    "runbook": ["RUNBOOK.md", "runbook.md", "docs/runbook"],
    "api": ["API.md", "api.md", "docs/api"],
}

# Seções obrigatórias por tipo de documento
SECTION_RULES: dict[str, dict] = {
    "readme": {
        "required_headings": ["Installation", "Usage"],
        "recommended_headings": ["Contributing", "License"],
        "min_words": 100,
    },
    "changelog": {
        "required_patterns": [r"## \[Unreleased\]", r"## \[\d+\.\d+\.\d+\]"],
        "required_headings": [],
        "format_hint": "Keep a Changelog (https://keepachangelog.com)",
    },
    "adr": {
        "required_headings": ["Status", "Context", "Decision", "Consequences"],
        "valid_statuses": ["proposed", "accepted", "deprecated", "superseded"],
        "min_words": 50,
    },
    "agents": {
        "required_headings": [],  # flexível — ao menos uma seção de política
        "min_words": 200,
    },
    "runbook": {
        "required_headings": ["Overview", "Steps"],
        "recommended_headings": ["Prerequisites", "Rollback"],
        "min_words": 100,
    },
    "api": {
        "required_headings": ["Authentication", "Endpoints"],
        "recommended_headings": ["Examples", "Errors"],
        "min_words": 150,
    },
}

# Nível de exigência de documentação por "standard"
REQUIRED_DOCS: dict[str, list[str]] = {
    "minimal": ["README.md"],
    "standard": ["README.md", "CHANGELOG.md"],
    "full": ["README.md", "CHANGELOG.md", "AGENTS.md"],
    "service": ["README.md", "CHANGELOG.md", "AGENTS.md", "RUNBOOK.md"],
}
