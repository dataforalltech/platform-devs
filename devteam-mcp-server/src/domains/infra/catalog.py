"""Catálogo de tools + dispatcher do domínio *infra* (consolidado no devteam-mcp).

Fatia "de negócio" do antigo `infra-mcp-server/src/server/mcp_server.py`: mantém intactos
o ``_TOOL_SCHEMAS`` (schemas + metadados de policy por tool) e o roteamento (``_run_tool``
→ ``dispatch``: ``_dispatch_compute`` p/ as tools compute-only e ``_dispatch_allocator``
p/ as tenant-scoped do allocator). O que ficou de FORA é o boot/serve/segurança (FastAPI,
PEP inner-token, stdio, tenant plumbing) — responsabilidade do AGREGADOR
(`src/server/mcp_server.py`), compartilhada por todos os domínios.

Diferenças vs. o server-fonte (strangler — fiel, sem inventar comportamento):
  * ``capability`` passa a ``devteam-mcp.infra_<op>`` (namespace do server consolidado +
    nome de tool já prefixado pelo domínio — o gateway não deriva por nome).
  * ``required_scope`` passa a ``infra:<recurso>:<ação>`` — PRESERVA o least-privilege
    por-tool, só troca o antigo prefixo de namespace ``infra-mcp`` pelo domínio ``infra``.
    (resource_type/data_domain seguem os valores ORIGINAIS do fonte.) Ambos são reescritos
    num único loop de normalização abaixo — o ``_TOOL_SCHEMAS`` é copiado byte-a-byte.
  * As CHAVES de ``_TOOL_SCHEMAS`` continuam os nomes de op SEM prefixo (``request_vm``); o
    ``plugin.register()`` prefixa (``infra_request_vm``) e o ``plugin.dispatch`` retira o
    prefixo antes de chamar ``dispatch`` daqui — a lógica de roteamento fica byte-a-byte.
  * O ``_run_tool`` do fonte (schema-ensure + ``for_tenant`` + roteamento) some: o agregador
    já garante o schema e abre a sessão tenant-scoped; a ``dispatch`` daqui recebe a sessão e
    constrói o ``AllocatorStore``. As deps de RUNTIME (provisioner/fernet/policy) — que
    viviam no nível de processo do ``build_server`` do fonte — são singletons lazy do domínio.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

from .config.secrets import load_secret
from .config.settings import Settings, get_settings
from .db.allocator_store import AllocatorPolicy, AllocatorStore
from .db.provisioner import ImmediateProvisioner, Provisioner, TerraformProvisioner
from .tools import (
    cancel_queued_request,
    cost_estimate_infracost,
    extend_lease,
    get_lease,
    get_lease_ssh_key,
    list_my_leases,
    list_pool,
    policy_scan_checkov,
    query_capacity,
    release_lease,
    request_vm,
    terraform_fmt_check,
    terraform_plan,
    terraform_show_plan,
    terraform_validate,
)
from .utils.logger import get_logger

_log = get_logger(__name__)

# Domínio canônico deste plugin — usado no capability/required_scope e como prefixo de
# tool (o agregador descobre o domínio por ``<domain>_<op>``).
DOMAIN = "infra"


# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara, além de description/schema, os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (reescrito no loop de normalização)
#   required_scope — escopo dominio:tipo:acao (least-privilege; prefixo normalizado)
#   resource_type  — tipo de recurso tocado (valor ORIGINAL do fonte)
#   data_domain    — domínio de dado (valor ORIGINAL do fonte)
# inputSchema MUST ser type=object com properties. Mutação → :write; consulta/plan/scan → :read.
# ─────────────────────────────────────────────────────────────────────────────
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "terraform_validate": {
        "description": (
            "Roda `terraform validate -json` no diretório. Retorna diagnostics "
            "estruturados (erros + warnings). Read-only — não modifica state nem "
            "consulta provider remoto."
        ),
        "capability": "infra-mcp.terraform_validate",
        "required_scope": "infra-mcp:terraform:read",
        "resource_type": "terraform",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Diretório do módulo terraform. Default: INFRA_TERRAFORM_ROOT.",
                },
            },
            "additionalProperties": False,
        },
    },
    "terraform_fmt_check": {
        "description": (
            "Roda `terraform fmt -check -diff` (recursivo). Não modifica arquivos. "
            "Retorna lista de arquivos não-formatados + diff."
        ),
        "capability": "infra-mcp.terraform_fmt_check",
        "required_scope": "infra-mcp:terraform:read",
        "resource_type": "terraform",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "recursive": {"type": "boolean", "default": True},
            },
            "additionalProperties": False,
        },
    },
    "terraform_plan": {
        "description": (
            "Roda `terraform plan -no-color -out=<file> -detailed-exitcode`. Retorna "
            "summary (add/change/destroy) + path do .tfplan binário (input para "
            "infracost e show-plan). Pode chamar provider remoto (rate limit)."
        ),
        "capability": "infra-mcp.terraform_plan",
        "required_scope": "infra-mcp:terraform:read",
        "resource_type": "terraform",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "out_file": {
                    "type": "string",
                    "description": "Caminho do .tfplan a gravar. Default: <path>/.infra-mcp.tfplan",
                },
                "var_file": {
                    "type": "string",
                    "description": "-var-file=... opcional",
                },
            },
            "additionalProperties": False,
        },
    },
    "terraform_show_plan": {
        "description": (
            "Devolve o terraform plan em JSON estruturado para análise programática "
            "(via `terraform show -json <plan>`). Use depois de terraform_plan."
        ),
        "capability": "infra-mcp.terraform_show_plan",
        "required_scope": "infra-mcp:terraform:read",
        "resource_type": "terraform",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "plan_path": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["plan_path"],
            "additionalProperties": False,
        },
    },
    "policy_scan_checkov": {
        "description": (
            "Roda checkov sobre código terraform (ou outro framework) e devolve "
            "findings agrupados por severity. Marca hard_stop=True se houver "
            "qualquer HIGH ou CRITICAL (cicd-deploy.md §4 #3 do ai-governance)."
        ),
        "capability": "infra-mcp.policy_scan_checkov",
        "required_scope": "infra-mcp:policy:read",
        "resource_type": "policy",
        "data_domain": "security",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "framework": {
                    "type": "string",
                    "enum": ["terraform", "terraform_plan", "kubernetes", "dockerfile", "all"],
                    "default": "terraform",
                },
                "skip_checks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de check_ids para ignorar (ex.: CKV_AZURE_42)",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    "cost_estimate_infracost": {
        "description": (
            "Roda `infracost diff --path <tfplan> --format json` e devolve delta "
            "mensal de custo. Marca hard_stop=True se delta > threshold (default "
            "+US$ 100/mês ou +20%, conforme cicd-deploy.md §4 #4)."
        ),
        "capability": "infra-mcp.cost_estimate_infracost",
        "required_scope": "infra-mcp:cost:read",
        "resource_type": "cost",
        "data_domain": "finops",
        "schema": {
            "type": "object",
            "properties": {
                "plan_path": {"type": "string"},
                "delta_usd_threshold": {"type": "number", "default": 100.0},
                "delta_pct_threshold": {"type": "number", "default": 20.0},
            },
            "required": ["plan_path"],
            "additionalProperties": False,
        },
    },
    # ----------------------- Phase 2a — VM allocator ----------------------- #
    "request_vm": {
        "description": (
            "Solicita capacidade ao allocator. Servidor decide entre lease em "
            "VM existente (compartilhamento), provisão de nova, fila ou denial. "
            "Spec restrita à whitelist (cpu-small/medium/large). gpu-a100 e "
            "high-mem exigem `human_approved=True` registrado out-of-band. "
            "Phase 2c: provisão via terraform real (INFRA_TF_MODULES_ROOT). "
            "Lease inicia PENDING e vai ACTIVE quando VM fica READY. "
            "Use get_lease(lease_id) para verificar connection_hint (endpoint SSH)."
        ),
        "capability": "infra-mcp.request_vm",
        "required_scope": "infra-mcp:lease:write",
        "resource_type": "lease",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "spec": {
                    "type": "string",
                    "enum": ["cpu-small", "cpu-medium", "cpu-large", "high-mem", "gpu-a100"],
                },
                "duration_min": {"type": "integer", "minimum": 1, "maximum": 4320},
                "owner": {"type": "string", "description": "Identificador do agente."},
                "exclusive": {"type": "boolean", "default": False},
                "priority": {"type": "string", "enum": ["low", "medium", "high"], "default": "low"},
                "purpose": {"type": "string", "description": "Descrição curta para audit."},
                "human_approved": {"type": "boolean", "default": False},
            },
            "required": ["spec", "duration_min", "owner"],
            "additionalProperties": False,
        },
    },
    "get_lease": {
        "description": "Estado atual de um lease (PENDING/ACTIVE/RELEASED/EXPIRED) + connection_hint.",
        "capability": "infra-mcp.get_lease",
        "required_scope": "infra-mcp:lease:read",
        "resource_type": "lease",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {"lease_id": {"type": "string"}},
            "required": ["lease_id"],
            "additionalProperties": False,
        },
    },
    "release_lease": {
        "description": (
            "Libera um lease. Idempotente — segundo release no mesmo lease é no-op. "
            "Quando última lease de uma VM é liberada, VM é terminada (Phase 2a)."
        ),
        "capability": "infra-mcp.release_lease",
        "required_scope": "infra-mcp:lease:write",
        "resource_type": "lease",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "lease_id": {"type": "string"},
                "by": {"type": "string", "description": "Quem chamou release (audit)."},
            },
            "required": ["lease_id"],
            "additionalProperties": False,
        },
    },
    "extend_lease": {
        "description": (
            "Estende a validade de um lease ativo. Cap absoluto: 24h totais e "
            "no máximo 3 extensões por lease."
        ),
        "capability": "infra-mcp.extend_lease",
        "required_scope": "infra-mcp:lease:write",
        "resource_type": "lease",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "lease_id": {"type": "string"},
                "additional_min": {"type": "integer", "minimum": 1, "maximum": 720},
            },
            "required": ["lease_id", "additional_min"],
            "additionalProperties": False,
        },
    },
    "list_my_leases": {
        "description": "Lista leases do owner (filtro opcional por status).",
        "capability": "infra-mcp.list_my_leases",
        "required_scope": "infra-mcp:lease:read",
        "resource_type": "lease",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["PENDING", "ACTIVE", "RELEASED", "EXPIRED"],
                },
            },
            "required": ["owner"],
            "additionalProperties": False,
        },
    },
    "list_pool": {
        "description": (
            "Snapshot do pool: VMs ativas + active_lease_count + custo/hora total. "
            "Visibilidade administrativa."
        ),
        "capability": "infra-mcp.list_pool",
        "required_scope": "infra-mcp:pool:read",
        "resource_type": "pool",
        "data_domain": "infrastructure",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "query_capacity": {
        "description": (
            "Planejamento sem efeito: 'haveria slot para essa spec sem violar "
            "hard stops?' Retorna can_satisfy_now + by_existing_vm/would_provision "
            "+ blocked_by quando recusado."
        ),
        "capability": "infra-mcp.query_capacity",
        "required_scope": "infra-mcp:capacity:read",
        "resource_type": "capacity",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "spec": {
                    "type": "string",
                    "enum": ["cpu-small", "cpu-medium", "cpu-large", "high-mem", "gpu-a100"],
                },
                "owner": {"type": "string", "description": "Para checar quota por agente."},
            },
            "required": ["spec"],
            "additionalProperties": False,
        },
    },
    # ----------------------- Phase 2f — SSH key per-VM --------------------- #
    "get_lease_ssh_key": {
        "description": (
            "Retorna a chave privada Ed25519 (PEM) para conectar via SSH à VM do lease. "
            "Requer lease em status ACTIVE. owner deve ser o titular do lease. "
            "A chave é deletada quando o lease é liberado — salve localmente antes do release. "
            "Uso: salvar em arquivo com chmod 600 e usar com ssh -i key.pem ubuntu@<host>."
        ),
        "capability": "infra-mcp.get_lease_ssh_key",
        "required_scope": "infra-mcp:secret:write",
        "resource_type": "secret",
        "data_domain": "secrets",
        "schema": {
            "type": "object",
            "properties": {
                "lease_id": {"type": "string"},
                "owner": {
                    "type": "string",
                    "description": "Identificador do agente titular do lease (autenticação).",
                },
            },
            "required": ["lease_id", "owner"],
            "additionalProperties": False,
        },
    },
    # ----------------------- Phase 2h — priority queue -------------------- #
    "cancel_queued_request": {
        "description": (
            "Cancela um request WAITING na fila de provisão de VM. "
            "Use quando o agente não precisa mais da VM aguardada (job cancelado, timeout). "
            "request_id foi retornado por request_vm quando outcome=QUEUED. "
            "Retorna erro se request_id não existe ou já foi FULFILLED/CANCELLED."
        ),
        "capability": "infra-mcp.cancel_queued_request",
        "required_scope": "infra-mcp:queue:write",
        "resource_type": "queue",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "ID retornado por request_vm (campo request_id quando outcome=QUEUED).",
                },
                "by": {
                    "type": "string",
                    "description": "Identificador de quem está cancelando (audit).",
                },
            },
            "required": ["request_id"],
            "additionalProperties": False,
        },
    },
}


# Normaliza capability/required_scope para o namespace do server consolidado (devteam-mcp),
# preservando resource_type/data_domain e o sufixo <recurso>:<ação> do least-privilege:
#   capability     → devteam-mcp.infra_<op>
#   required_scope → infra:<recurso>:<ação>   (troca só o antigo namespace ``infra-mcp``)
for _name, _meta in _TOOL_SCHEMAS.items():
    _meta["capability"] = f"devteam-mcp.{DOMAIN}_{_name}"
    _meta["required_scope"] = f"{DOMAIN}:{_meta['required_scope'].split(':', 1)[1]}"


# ── Dispatchers (compute-only sync × allocator async tenant-scoped) ───────────

# As 9 tools do allocator são async e tenant-scoped (recebem um AllocatorStore ligado à
# TenantSession do request). As 6 compute-only são sync (rodam CLIs) e recebem só settings.
_ALLOCATOR_TOOLS: frozenset[str] = frozenset(
    {
        "request_vm",
        "get_lease",
        "release_lease",
        "extend_lease",
        "list_my_leases",
        "list_pool",
        "query_capacity",
        "get_lease_ssh_key",
        "cancel_queued_request",
    }
)


def _dispatch_compute(name: str, a: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Despacha as tools compute-only (terraform/checkov/infracost) — ``tool(settings, ...)``.

    Roda em thread (``asyncio.to_thread``) para não bloquear o event loop com subprocessos.
    """
    if name == "terraform_validate":
        return terraform_validate(settings, path=a.get("path"))
    if name == "terraform_fmt_check":
        return terraform_fmt_check(settings, path=a.get("path"), recursive=a.get("recursive", True))
    if name == "terraform_plan":
        return terraform_plan(
            settings,
            path=a.get("path"),
            out_file=a.get("out_file"),
            var_file=a.get("var_file"),
        )
    if name == "terraform_show_plan":
        return terraform_show_plan(settings, plan_path=cast(str, a.get("plan_path")), path=a.get("path"))
    if name == "policy_scan_checkov":
        return policy_scan_checkov(
            settings,
            path=cast(str, a.get("path")),
            framework=a.get("framework", "terraform"),
            skip_checks=a.get("skip_checks"),
        )
    if name == "cost_estimate_infracost":
        return cost_estimate_infracost(
            settings,
            plan_path=cast(str, a.get("plan_path")),
            delta_usd_threshold=a.get("delta_usd_threshold"),
            delta_pct_threshold=a.get("delta_pct_threshold"),
        )
    raise KeyError(name)


async def _dispatch_allocator(name: str, a: dict[str, Any], store: AllocatorStore) -> dict[str, Any]:
    """Despacha as tools do allocator (async). O ``store`` já está ligado ao pool do tenant."""
    if name == "request_vm":
        return await request_vm(
            store,
            spec=cast(str, a.get("spec")),
            duration_min=cast(int, a.get("duration_min")),
            owner=cast(str, a.get("owner")),
            exclusive=a.get("exclusive", False),
            priority=a.get("priority", "low"),
            purpose=a.get("purpose"),
            human_approved=a.get("human_approved", False),
        )
    if name == "get_lease":
        return await get_lease(store, lease_id=cast(str, a.get("lease_id")))
    if name == "release_lease":
        return await release_lease(store, lease_id=cast(str, a.get("lease_id")), by=a.get("by"))
    if name == "extend_lease":
        return await extend_lease(
            store,
            lease_id=cast(str, a.get("lease_id")),
            additional_min=cast(int, a.get("additional_min")),
        )
    if name == "list_my_leases":
        return await list_my_leases(store, owner=cast(str, a.get("owner")), status=a.get("status"))
    if name == "list_pool":
        return await list_pool(store)
    if name == "query_capacity":
        return await query_capacity(store, spec=cast(str, a.get("spec")), owner=a.get("owner"))
    if name == "get_lease_ssh_key":
        return await get_lease_ssh_key(
            store, lease_id=cast(str, a.get("lease_id")), owner=cast(str, a.get("owner"))
        )
    if name == "cancel_queued_request":
        return await cancel_queued_request(store, request_id=cast(str, a.get("request_id")), by=a.get("by"))
    raise KeyError(name)


# ── Runtime deps (nível de processo, como no ``build_server`` do fonte) ───────
# O provisioner (terraform real/mock) e o segredo Fernet (cifra as chaves SSH) viviam no
# nível de processo do server-fonte e eram passados a cada ``AllocatorStore``. O agregador
# não os injeta, então o domínio os constrói como singletons lazy (built once por processo),
# preservando o comportamento do fonte.
_PROVISIONER: Provisioner | None = None
_FERNET_RESOLVED: bool = False
_FERNET_KEY: bytes | None = None


def _get_provisioner(settings: Settings) -> Provisioner:
    """Constrói (uma vez por processo) o provisioner (terraform real ou mock).

    Corpo do ``_build_provisioner`` do server-fonte — ``tf_modules_root`` setado ⇒
    ``TerraformProvisioner`` real; ausente ⇒ ``ImmediateProvisioner`` (mock/testes)."""
    global _PROVISIONER
    if _PROVISIONER is not None:
        return _PROVISIONER
    if settings.tf_modules_root is not None:
        backend_config: dict[str, str] = {}
        if settings.tf_backend_config_json:
            try:
                backend_config = json.loads(settings.tf_backend_config_json)
            except Exception:  # noqa: BLE001
                _log.warning(
                    "backend_config_json_parse_error",
                    extra={"extras": {"raw": settings.tf_backend_config_json[:200]}},
                )
        provisioner: Provisioner = TerraformProvisioner(
            terraform_bin=settings.terraform_bin,
            backend_type=settings.tf_backend_type,
            backend_config=backend_config,
            infracost_bin=settings.infracost_bin,
            cost_cap_usd_month=settings.cost_cap_usd_month,
        )
        _log.info(
            "provisioner_terraform",
            extra={
                "extras": {
                    "tf_modules_root": str(settings.tf_modules_root),
                    "backend_type": settings.tf_backend_type,
                    "cost_cap_usd_month": settings.cost_cap_usd_month,
                }
            },
        )
    else:
        provisioner = ImmediateProvisioner()
        _log.info("provisioner_immediate", extra={"extras": {}})
    _PROVISIONER = provisioner
    return provisioner


def _get_fernet_key(settings: Settings) -> bytes | None:
    """Resolve (uma vez por processo) o segredo Fernet que cifra as chaves SSH por VM.

    Vault-fallback → env (``INFRA_LEASE_SECRET`` / ``settings.lease_secret``), idêntico ao
    ``build_server`` do fonte. Ausente ⇒ ``None`` (o ``AllocatorStore`` gera uma chave
    efêmera por store — chaves SSH não persistem entre restarts, comportamento do fonte)."""
    global _FERNET_RESOLVED, _FERNET_KEY
    if not _FERNET_RESOLVED:
        fernet_raw = load_secret("INFRA_LEASE_SECRET", env_fallback=settings.lease_secret)
        _FERNET_KEY = fernet_raw.encode() if fernet_raw else None
        _FERNET_RESOLVED = True
    return _FERNET_KEY


# ── Dispatcher (roteia compute × allocator; recebe a sessão ligada ao tenant) ──


async def dispatch(name: str, args: dict[str, Any], session: Any) -> dict[str, Any]:
    """Despacha a chamada (async). ``name`` é o nome de op SEM prefixo de domínio (o
    ``plugin.dispatch`` já o retirou); ``session`` já está ligada ao pool do tenant.

    Replica o ``_run_tool`` do server-fonte (menos o schema-ensure + ``for_tenant``, que o
    agregador faz): tools do allocator abrem um ``AllocatorStore`` ligado à sessão do tenant
    + as deps de RUNTIME (provisioner/fernet/policy, nível de processo); tools compute-only
    rodam o CLI em thread (``asyncio.to_thread``). ``KeyError`` p/ tool desconhecida
    (propagado pelos sub-dispatchers)."""
    settings = get_settings()
    if name in _ALLOCATOR_TOOLS:
        store = AllocatorStore(
            session,
            provisioner=_get_provisioner(settings),
            policy=AllocatorPolicy(),
            fernet_key=_get_fernet_key(settings),
            tf_modules_root=settings.tf_modules_root,
            provision_timeout_sec=settings.provision_timeout_sec,
        )
        return await _dispatch_allocator(name, args, store)
    return await asyncio.to_thread(_dispatch_compute, name, args, settings)
