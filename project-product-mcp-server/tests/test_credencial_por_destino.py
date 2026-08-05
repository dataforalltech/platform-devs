"""Passo 1 da "Estratégia de migração" do STD-SEC-002: o destino no nome do segredo.

O que se verifica aqui é o mecanismo, não a prosa: enquanto o nome for
``internal_api_token``, existe exatamente um slot por serviço e o compartilhamento
entre destinos não é desvio de operação — é a única configuração possível. Com o
destino no nome, cada hop tem a sua credencial e o boot consegue recusar as duas
violações que são detectáveis de dentro do processo.

Referências: docs/standards/STD-SEC-002-service-to-service.md ("Estratégia de
migração", passo 1, e "Parâmetros de configuração") e a ADR-0026 do
platform-service-template, que recepciona o ADR-0012 do platform-infra.
"""

from __future__ import annotations

import pytest
from project_product_mcp.config import settings as config

API = "platform-project-product"
GOV = "platform-governance"

ENV_API = "INTERNAL_API_TOKEN__PLATFORM_PROJECT_PRODUCT"
ENV_GOV = "INTERNAL_API_TOKEN__PLATFORM_GOVERNANCE"


def _settings(**over: object) -> config.Settings:
    """Constrói as Settings do sidecar sem depender de um `.env` no cwd."""
    return config.Settings(_env_file=None, **over)


# ── fórmula do nome ───────────────────────────────────────────────────────────
def test_nome_no_vault_preserva_hifens_e_e_minusculo():
    assert config.target_vault_name(API) == "internal_api_token__platform-project-product"
    assert config.target_vault_name(GOV) == "internal_api_token__platform-governance"


def test_nome_no_ambiente_e_maiusculo_com_underscore():
    assert config.target_env_var(API) == ENV_API
    assert config.target_env_var(GOV) == ENV_GOV
    # dois underscores separam o prefixo do destino — um só tornaria ambíguo um
    # destino cujo nome canônico já contenha hífen.
    assert config.target_env_var(API).count("__") == 1
    assert config.target_env_var(API).startswith("INTERNAL_API_TOKEN__")


# ── resolução por destino ─────────────────────────────────────────────────────
def test_cada_destino_recebe_a_sua_credencial(monkeypatch):
    monkeypatch.setenv(ENV_API, "segredo-da-api")
    monkeypatch.setenv(ENV_GOV, "segredo-da-governance")
    s = _settings()
    assert s.INTERNAL_API_TOKENS == {API: "segredo-da-api", GOV: "segredo-da-governance"}
    # as vistas por papel continuam servindo os clientes já existentes
    assert s.INTERNAL_API_TOKEN.get_secret_value() == "segredo-da-api"
    assert s.GOVERNANCE_INTERNAL_TOKEN.get_secret_value() == "segredo-da-governance"


def test_destinos_declarados_explicitamente_em_targets(monkeypatch):
    monkeypatch.setenv(ENV_API, "a")
    monkeypatch.setenv(ENV_GOV, "b")
    s = _settings(INTERNAL_API_TARGETS=f"{API},{GOV}")
    assert sorted(s.INTERNAL_API_TOKENS) == sorted([API, GOV])


def test_nome_de_destino_invalido_recusa_o_boot(monkeypatch):
    """Nome fora do formato canônico recusa, em vez de derivar segredo inexistente."""
    monkeypatch.setenv(ENV_API, "a")
    monkeypatch.setenv(ENV_GOV, "b")
    with pytest.raises(ValueError, match="INTERNAL_API_TARGETS"):
        _settings(INTERNAL_API_TARGETS="Platform-Project-Product")
    with pytest.raises(ValueError, match="INTERNAL_API_TARGETS"):
        _settings(INTERNAL_API_TARGETS="platform_project_product")


# ── as três recusas de boot ───────────────────────────────────────────────────
def test_destino_sem_credencial_recusa_o_boot_tambem_em_local(monkeypatch):
    """Falha fechada em QUALQUER ambiente, não só em cloud.

    Um destino que some do mapa em silêncio escapa das duas verificações de
    segredo universal, que iteram exatamente sobre esse mapa — o boot que mais
    precisa ser recusado seria o único não inspecionado.
    """
    monkeypatch.setenv(ENV_API, "segredo-da-api")
    monkeypatch.delenv(ENV_GOV, raising=False)
    monkeypatch.delenv("GOVERNANCE_INTERNAL_TOKEN", raising=False)
    with pytest.raises(ValueError) as exc:
        _settings(RUNTIME_ENV="local")
    msg = str(exc.value)
    assert GOV in msg
    assert "internal_api_token__platform-governance" in msg
    assert ENV_GOV in msg
    # a mensagem diz o que provisionar, e nunca o valor de segredo nenhum
    assert "segredo-da-api" not in msg


def test_dois_destinos_com_o_mesmo_valor_recusam_o_boot(monkeypatch):
    """Um valor que autentica em dois destinos deixa um passar-se pelo outro."""
    monkeypatch.setenv(ENV_API, "mesmo-valor")
    monkeypatch.setenv(ENV_GOV, "mesmo-valor")
    with pytest.raises(ValueError) as exc:
        _settings()
    msg = str(exc.value)
    assert API in msg and GOV in msg
    assert "mesmo-valor" not in msg  # a mensagem não cita valor de segredo


def test_destino_igual_ao_proprio_sidecar_recusa_o_boot(monkeypatch):
    """Credencial escopada ao próprio chamador não está escopada a nada."""
    monkeypatch.setenv(ENV_API, "a")
    monkeypatch.setenv(ENV_GOV, "b")
    with pytest.raises(ValueError, match="SERVICE_TARGET_NAME"):
        _settings(SERVICE_TARGET_NAME="platform-project-product-mcp")


def test_nome_do_destino_nao_e_derivado_do_app_name(monkeypatch):
    """O destino é DECLARADO; derivar de APP_NAME tirando '-mcp' é o erro que o
    STD-SEC-002 proíbe nominalmente."""
    monkeypatch.setenv(ENV_API, "a")
    monkeypatch.setenv(ENV_GOV, "b")
    s = _settings()
    assert s.APP_NAME == "platform-project-product-mcp"
    assert s.SERVICE_TARGET_NAME == API
    assert s.SERVICE_TARGET_NAME != s.APP_NAME


def test_target_name_invalido_recusa(monkeypatch):
    monkeypatch.setenv(ENV_API, "a")
    monkeypatch.setenv(ENV_GOV, "b")
    # underscore não é nome canônico de serviço (^[a-z0-9][a-z0-9-]{1,62}$)
    with pytest.raises(ValueError):
        _settings(SERVICE_TARGET_NAME="platform_project_product")
    with pytest.raises(ValueError):
        _settings(SERVICE_TARGET_NAME="-comeca-com-hifen")


def test_target_name_e_normalizado_para_minusculo(monkeypatch):
    """Maiúsculas são normalizadas, não recusadas — igual ao template canônico."""
    monkeypatch.setenv(ENV_API, "a")
    monkeypatch.setenv(ENV_GOV, "b")
    assert _settings(SERVICE_TARGET_NAME=" Platform-Project-Product ").SERVICE_TARGET_NAME == API
