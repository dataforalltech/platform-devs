"""Testes para AuditStore e get_audit_log tool.

Cobre:
- Gravação de decisão (record)
- Consulta sem filtros
- Filtros por repo, risk_level, approved
- Paginação (limit, offset)
- Stats agregados
- Resiliência com arquivo ausente
- Ignorar linhas JSONL corrompidas
- get_audit_log tool (modo lista e stats)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.knowledge.audit_store import AuditStore
from src.tools.audit_tool import get_audit_log


# ---------------------------------------------------------------------- #
# Fixtures                                                                #
# ---------------------------------------------------------------------- #


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    return tmp_path / "audit" / "decisions.jsonl"


@pytest.fixture
def store(audit_path: Path) -> AuditStore:
    return AuditStore(path=audit_path)


def _make_result(
    *,
    repo: str = "platform-test",
    task: str = "Tarefa de teste",
    approved: bool = True,
    risk: str = "low",
    violations: list[str] | None = None,
    required_actions: list[str] | None = None,
    layers: list[str] | None = None,
    files_count: int = 3,
) -> dict:
    """Constrói um resultado sintético de validate_agent_decision."""
    violations = violations or []
    required_actions = required_actions or []
    layers = layers or ["backend"]
    result = {
        "approved": approved,
        "risk_level": risk,
        "violations": violations,
        "required_actions": required_actions,
        "recommendations": [],
        "notes": [],
        "input_summary": {
            "repository_name": repo,
            "task_description": task,
            "affected_files_count": files_count,
            "affected_layers": layers,
            "changes_contracts": False,
            "adds_fallback": False,
            "adds_dependency": False,
            "modifies_security": False,
        },
    }
    return result


# ---------------------------------------------------------------------- #
# Testes — AuditStore.record                                              #
# ---------------------------------------------------------------------- #


class TestAuditStoreRecord:
    def test_cria_arquivo_automaticamente(self, store: AuditStore) -> None:
        result = _make_result()
        store.record(result, result["input_summary"])
        assert store.path.exists()

    def test_grava_uma_linha_jsonl(self, store: AuditStore) -> None:
        result = _make_result(repo="platform-auth", risk="medium")
        store.record(result, result["input_summary"])
        lines = store.path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["repo"] == "platform-auth"
        assert entry["risk_level"] == "medium"

    def test_acumula_multiplas_linhas(self, store: AuditStore) -> None:
        for i in range(5):
            result = _make_result(repo=f"repo-{i}")
            store.record(result, result["input_summary"])
        lines = store.path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 5

    def test_campos_obrigatorios_presentes(self, store: AuditStore) -> None:
        result = _make_result(
            approved=False,
            risk="critical",
            violations=["Fallback silencioso detectado."],
            required_actions=["Remover o fallback."],
        )
        store.record(result, result["input_summary"])
        entry = json.loads(store.path.read_text(encoding="utf-8").splitlines()[0])
        required_keys = {
            "ts", "repo", "task_description", "approved", "risk_level",
            "violations_count", "violations", "required_actions_count",
            "required_actions", "affected_layers", "affected_files_count", "flags",
        }
        assert required_keys.issubset(entry.keys())

    def test_trunca_task_description_em_200_chars(self, store: AuditStore) -> None:
        long_task = "x" * 500
        result = _make_result(task=long_task)
        store.record(result, result["input_summary"])
        entry = json.loads(store.path.read_text(encoding="utf-8").splitlines()[0])
        assert len(entry["task_description"]) == 200

    def test_input_summary_embutido_no_result(self, store: AuditStore) -> None:
        """record() deve funcionar quando input_summary não é passado explicitamente."""
        result = _make_result(repo="platform-ml")
        # Não passamos input_summary explicitamente — deve ler de result["input_summary"]
        store.record(result)
        entry = json.loads(store.path.read_text(encoding="utf-8").splitlines()[0])
        assert entry["repo"] == "platform-ml"

    def test_flags_registrados(self, store: AuditStore) -> None:
        result = _make_result()
        result["input_summary"]["changes_contracts"] = True
        result["input_summary"]["adds_dependency"] = True
        store.record(result, result["input_summary"])
        entry = json.loads(store.path.read_text(encoding="utf-8").splitlines()[0])
        assert entry["flags"]["changes_contracts"] is True
        assert entry["flags"]["adds_dependency"] is True


# ---------------------------------------------------------------------- #
# Testes — AuditStore.query                                               #
# ---------------------------------------------------------------------- #


class TestAuditStoreQuery:
    def _populate(self, store: AuditStore, n: int = 10) -> None:
        for i in range(n):
            repo = "platform-auth" if i % 2 == 0 else "platform-ml"
            risk = "critical" if i % 3 == 0 else ("high" if i % 3 == 1 else "low")
            approved = risk not in ("critical",)
            result = _make_result(repo=repo, risk=risk, approved=approved)
            store.record(result, result["input_summary"])

    def test_retorna_lista_vazia_sem_arquivo(self, audit_path: Path) -> None:
        store = AuditStore(path=audit_path)
        # Não grava nada → arquivo não existe ainda
        assert store.query() == []

    def test_retorna_todas_sem_filtros(self, store: AuditStore) -> None:
        self._populate(store, 10)
        entries = store.query(limit=100)
        assert len(entries) == 10

    def test_ordem_cronologica_reversa(self, store: AuditStore) -> None:
        for repo in ["a", "b", "c"]:
            store.record(_make_result(repo=repo), _make_result(repo=repo)["input_summary"])
        entries = store.query(limit=10)
        # O mais recente (c) deve vir primeiro.
        assert entries[0]["repo"] == "c"
        assert entries[-1]["repo"] == "a"

    def test_filtro_por_repo_substring(self, store: AuditStore) -> None:
        self._populate(store, 10)
        entries = store.query(repo="platform-auth", limit=100)
        assert all("platform-auth" in e["repo"] for e in entries)

    def test_filtro_por_risk_level(self, store: AuditStore) -> None:
        self._populate(store, 9)
        entries = store.query(risk_level="critical", limit=100)
        assert all(e["risk_level"] == "critical" for e in entries)

    def test_filtro_por_approved_false(self, store: AuditStore) -> None:
        self._populate(store, 9)
        entries = store.query(approved=False, limit=100)
        assert all(e["approved"] is False for e in entries)

    def test_filtro_por_approved_true(self, store: AuditStore) -> None:
        self._populate(store, 9)
        entries = store.query(approved=True, limit=100)
        assert all(e["approved"] is True for e in entries)

    def test_limit_respeitado(self, store: AuditStore) -> None:
        self._populate(store, 10)
        entries = store.query(limit=3)
        assert len(entries) == 3

    def test_offset_paginacao(self, store: AuditStore) -> None:
        self._populate(store, 10)
        all_entries = store.query(limit=100, offset=0)
        page1 = store.query(limit=5, offset=0)
        page2 = store.query(limit=5, offset=5)
        # Juntas, as páginas devem cobrir os 10 registros.
        assert len(page1) + len(page2) == 10
        # A concatenação deve ser equivalente à consulta completa.
        combined = page1 + page2
        assert combined == all_entries

    def test_ignora_linhas_corrompidas(self, store: AuditStore) -> None:
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text(
            '{"ts":"2026-01-01T00:00:00Z","repo":"ok","risk_level":"low","approved":true,'
            '"violations":[],"required_actions":[],"affected_layers":[],'
            '"affected_files_count":1,"flags":{},"task_description":"ok",'
            '"violations_count":0,"required_actions_count":0}\n'
            "linha corrompida que não é json válido\n"
            '{"ts":"2026-01-02T00:00:00Z","repo":"ok2","risk_level":"low","approved":true,'
            '"violations":[],"required_actions":[],"affected_layers":[],'
            '"affected_files_count":1,"flags":{},"task_description":"ok2",'
            '"violations_count":0,"required_actions_count":0}\n',
            encoding="utf-8",
        )
        entries = store.query(limit=100)
        assert len(entries) == 2

    def test_limit_maximo_500(self, store: AuditStore) -> None:
        """Não pode retornar mais do que 500 entradas."""
        for _ in range(10):
            store.record(_make_result(), _make_result()["input_summary"])
        entries = store.query(limit=600)
        # limit é clampeado para 500; como só temos 10 entradas, retorna 10.
        assert len(entries) == 10


# ---------------------------------------------------------------------- #
# Testes — AuditStore.stats                                               #
# ---------------------------------------------------------------------- #


class TestAuditStoreStats:
    def test_stats_sem_arquivo(self, audit_path: Path) -> None:
        store = AuditStore(path=audit_path)
        s = store.stats()
        assert s["total"] == 0
        assert s["approved"] == 0
        assert s["blocked"] == 0

    def test_stats_total_e_contagens(self, store: AuditStore) -> None:
        store.record(_make_result(approved=True, risk="low"), _make_result(approved=True, risk="low")["input_summary"])
        store.record(_make_result(approved=False, risk="critical"), _make_result(approved=False, risk="critical")["input_summary"])
        s = store.stats()
        assert s["total"] == 2
        assert s["approved"] == 1
        assert s["blocked"] == 1

    def test_stats_block_rate(self, store: AuditStore) -> None:
        for _ in range(3):
            store.record(_make_result(approved=True), _make_result(approved=True)["input_summary"])
        store.record(_make_result(approved=False, risk="critical"), _make_result(approved=False, risk="critical")["input_summary"])
        s = store.stats()
        assert s["block_rate"] == pytest.approx(0.25, rel=1e-3)

    def test_stats_by_risk_level(self, store: AuditStore) -> None:
        for risk in ["low", "low", "high", "critical"]:
            approved = risk != "critical"
            store.record(
                _make_result(approved=approved, risk=risk),
                _make_result(approved=approved, risk=risk)["input_summary"],
            )
        s = store.stats()
        assert s["by_risk_level"].get("low", 0) == 2
        assert s["by_risk_level"].get("high", 0) == 1
        assert s["by_risk_level"].get("critical", 0) == 1

    def test_stats_top_repos(self, store: AuditStore) -> None:
        for _ in range(3):
            store.record(_make_result(repo="platform-auth"), _make_result(repo="platform-auth")["input_summary"])
        store.record(_make_result(repo="platform-ml"), _make_result(repo="platform-ml")["input_summary"])
        s = store.stats()
        repos = {item["repo"]: item["count"] for item in s["top_repos"]}
        assert repos["platform-auth"] == 3
        assert repos["platform-ml"] == 1


# ---------------------------------------------------------------------- #
# Testes — get_audit_log tool                                             #
# ---------------------------------------------------------------------- #


class TestGetAuditLogTool:
    def test_modo_lista_sem_filtros(self, repo, tmp_path: Path) -> None:
        audit = AuditStore(path=tmp_path / "decisions.jsonl")
        for i in range(5):
            r = _make_result(repo=f"repo-{i}")
            audit.record(r, r["input_summary"])
        result = get_audit_log(repo, audit)
        assert "entries" in result
        assert result["count"] == 5

    def test_modo_stats(self, repo, tmp_path: Path) -> None:
        audit = AuditStore(path=tmp_path / "decisions.jsonl")
        r = _make_result(approved=False, risk="critical")
        audit.record(r, r["input_summary"])
        result = get_audit_log(repo, audit, query="stats")
        assert "stats" in result
        assert result["stats"]["total"] == 1
        assert result["stats"]["blocked"] == 1

    def test_filtro_por_repo(self, repo, tmp_path: Path) -> None:
        audit = AuditStore(path=tmp_path / "decisions.jsonl")
        for name in ["platform-auth", "platform-ml", "platform-auth"]:
            r = _make_result(repo=name)
            audit.record(r, r["input_summary"])
        result = get_audit_log(repo, audit, filter_repo="platform-auth", limit=100)
        assert result["count"] == 2
        assert all("platform-auth" in e["repo"] for e in result["entries"])

    def test_filtro_por_risk_level(self, repo, tmp_path: Path) -> None:
        audit = AuditStore(path=tmp_path / "decisions.jsonl")
        audit.record(_make_result(risk="low"), _make_result(risk="low")["input_summary"])
        audit.record(_make_result(approved=False, risk="critical"), _make_result(approved=False, risk="critical")["input_summary"])
        result = get_audit_log(repo, audit, risk_level="critical", limit=100)
        assert result["count"] == 1
        assert result["entries"][0]["risk_level"] == "critical"

    def test_filtro_approved_false(self, repo, tmp_path: Path) -> None:
        audit = AuditStore(path=tmp_path / "decisions.jsonl")
        audit.record(_make_result(approved=True), _make_result(approved=True)["input_summary"])
        audit.record(_make_result(approved=False, risk="critical"), _make_result(approved=False, risk="critical")["input_summary"])
        result = get_audit_log(repo, audit, approved=False, limit=100)
        assert result["count"] == 1
        assert result["entries"][0]["approved"] is False

    def test_paginacao_limit_offset(self, repo, tmp_path: Path) -> None:
        audit = AuditStore(path=tmp_path / "decisions.jsonl")
        for i in range(10):
            r = _make_result(repo=f"repo-{i}")
            audit.record(r, r["input_summary"])
        full = get_audit_log(repo, audit, limit=100, offset=0)
        page1 = get_audit_log(repo, audit, limit=5, offset=0)
        page2 = get_audit_log(repo, audit, limit=5, offset=5)
        assert page1["count"] == 5
        assert page2["count"] == 5
        # A concatenação das páginas reproduz a consulta completa.
        combined = page1["entries"] + page2["entries"]
        assert combined == full["entries"]

    def test_store_vazio_retorna_lista_vazia(self, repo, tmp_path: Path) -> None:
        audit = AuditStore(path=tmp_path / "inexistente.jsonl")
        result = get_audit_log(repo, audit)
        assert result["entries"] == []
        assert result["count"] == 0

    def test_store_vazio_stats_zeros(self, repo, tmp_path: Path) -> None:
        audit = AuditStore(path=tmp_path / "inexistente.jsonl")
        result = get_audit_log(repo, audit, query="stats")
        assert result["stats"]["total"] == 0
