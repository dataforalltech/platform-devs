"""Ferramentas de gerenciamento de checklists e execução de runs."""

from __future__ import annotations

from typing import Any

from ..db.store import TestStore

_VALID_ITEM_STATUSES = {"passed", "failed", "na", "blocked"}
_VALID_CHECKLIST_TYPES = {
    "pre_deploy", "post_deploy", "code_review", "security",
    "accessibility", "data_integrity", "custom",
}

# ── Templates de checklist ────────────────────────────────────────────────── #

_CHECKLIST_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "pre_deploy": [
        {"description": "Todos os testes unitários passando (green CI)", "required": True, "category": "quality"},
        {"description": "Cobertura de testes >= threshold mínimo do projeto", "required": True, "category": "quality"},
        {"description": "Linter/type-check sem erros", "required": True, "category": "quality"},
        {"description": "Code review aprovado por >= 1 revisor", "required": True, "category": "process"},
        {"description": "Migrações de banco testadas (UP e DOWN)", "required": True, "category": "database"},
        {"description": "Variáveis de ambiente de produção configuradas", "required": True, "category": "infra"},
        {"description": "Feature flags configuradas corretamente", "required": False, "category": "infra"},
        {"description": "Logs de auditoria para ações sensíveis implementados", "required": True, "category": "security"},
        {"description": "Endpoints novos documentados no Swagger/OpenAPI", "required": False, "category": "docs"},
        {"description": "Breaking changes comunicados ao time", "required": True, "category": "process"},
        {"description": "Rollback plan definido e testado", "required": True, "category": "process"},
        {"description": "Dependências de outros serviços verificadas (contratos)", "required": True, "category": "integration"},
    ],
    "post_deploy": [
        {"description": "Health check do serviço retornando 200", "required": True, "category": "health"},
        {"description": "Logs sem erros críticos (primeiros 5 min)", "required": True, "category": "health"},
        {"description": "Métricas de latência dentro do SLA", "required": True, "category": "performance"},
        {"description": "Taxa de erro (5xx) abaixo de 1%", "required": True, "category": "health"},
        {"description": "Migrações de banco aplicadas com sucesso", "required": True, "category": "database"},
        {"description": "Smoke test dos fluxos críticos executado", "required": True, "category": "quality"},
        {"description": "Integrações externas funcionando", "required": True, "category": "integration"},
        {"description": "Cache invalidado onde necessário", "required": False, "category": "performance"},
        {"description": "Alertas de monitoramento configurados", "required": False, "category": "infra"},
    ],
    "code_review": [
        {"description": "Lógica de negócio correta e alinhada ao requisito", "required": True, "category": "correctness"},
        {"description": "Sem código duplicado (DRY)", "required": False, "category": "quality"},
        {"description": "Sem secrets ou credenciais hardcoded (tokens, senhas, API keys)", "required": True, "category": "security"},
        {"description": "Sem IDs, URLs ou emails hardcoded de ambientes específicos (dev/hml/prod)", "required": True, "category": "hardcoded"},
        {"description": "Sem stubs, mocks ou fakes em código de produção (apenas em tests/)", "required": True, "category": "hardcoded"},
        {"description": "Sem dados fictícios (Lorem ipsum, 'test@test.com', '123456') em componentes de produção", "required": True, "category": "hardcoded"},
        {"description": "Sem flags de debug ou console.log/print em produção", "required": True, "category": "hardcoded"},
        {"description": "Inputs validados e sanitizados", "required": True, "category": "security"},
        {"description": "Erros tratados adequadamente (sem swallowed exceptions)", "required": True, "category": "quality"},
        {"description": "Queries SQL com índices adequados / sem N+1", "required": True, "category": "performance"},
        {"description": "Testes cobrindo os cenários adicionados/modificados", "required": True, "category": "quality"},
        {"description": "Nomes de variáveis/funções claros e descritivos", "required": False, "category": "readability"},
        {"description": "Comentários explicam o 'por quê', não o 'o quê'", "required": False, "category": "readability"},
        {"description": "Sem TODO/FIXME sem issue associada", "required": False, "category": "quality"},
        {"description": "Alterações em schema/contratos são backwards-compatible ou versionadas", "required": True, "category": "compatibility"},
    ],
    "security": [
        {"description": "Autenticação requerida em todos os endpoints protegidos", "required": True, "category": "auth"},
        {"description": "Autorização (RBAC/ABAC) validada corretamente", "required": True, "category": "auth"},
        {"description": "Inputs protegidos contra SQL injection", "required": True, "category": "injection"},
        {"description": "Inputs protegidos contra XSS", "required": True, "category": "injection"},
        {"description": "CSRF protection em endpoints de mutação", "required": True, "category": "csrf"},
        {"description": "Rate limiting configurado em endpoints sensíveis", "required": True, "category": "resilience"},
        {"description": "Dados sensíveis não expostos em logs", "required": True, "category": "data"},
        {"description": "Dados sensíveis criptografados em repouso", "required": True, "category": "data"},
        {"description": "Headers de segurança configurados (HSTS, CSP, X-Frame)", "required": False, "category": "headers"},
        {"description": "Dependências sem CVEs críticos conhecidos", "required": True, "category": "deps"},
        {"description": "Secrets rotacionados e não versionados no git", "required": True, "category": "secrets"},
    ],
    "accessibility": [
        {"description": "Todos os elementos interativos acessíveis por teclado", "required": True, "category": "keyboard"},
        {"description": "Imagens com atributo alt descritivo", "required": True, "category": "images"},
        {"description": "Contraste de cores >= 4.5:1 (WCAG AA)", "required": True, "category": "color"},
        {"description": "Labels em todos os campos de formulário", "required": True, "category": "forms"},
        {"description": "Mensagens de erro descritivas e associadas ao campo", "required": True, "category": "forms"},
        {"description": "Ordem de foco (tab order) lógica", "required": True, "category": "keyboard"},
        {"description": "Landmarks ARIA presentes (main, nav, header)", "required": False, "category": "aria"},
        {"description": "Sem conteúdo piscante que cause convulsões (< 3 flashes/s)", "required": True, "category": "motion"},
        {"description": "Textos redimensionáveis até 200% sem perda de conteúdo", "required": False, "category": "text"},
    ],
    "data_integrity": [
        # ── Dados hardcoded / stubs / fakes ──────────────────────────────── #
        {"description": "Nenhum ID hardcoded de registro real (user_id, tenant_id, org_id)", "required": True, "category": "hardcoded"},
        {"description": "Nenhuma URL hardcoded de ambiente (localhost, dev.api.com, hml.api.com)", "required": True, "category": "hardcoded"},
        {"description": "Nenhum token, chave de API ou senha hardcoded no código ou bundle", "required": True, "category": "hardcoded"},
        {"description": "Nenhum dado faker (Lorem ipsum, 'John Doe', 'test@test.com', '000-0000')", "required": True, "category": "hardcoded"},
        {"description": "Nenhum stub ou mock exportado fora de pastas de teste (tests/, __mocks__/, fixtures/)", "required": True, "category": "hardcoded"},
        {"description": "Nenhum feature flag hardcoded como true/false (deve vir de configuração)", "required": True, "category": "hardcoded"},
        {"description": "Sem console.log, print() ou debug() ativo em produção", "required": True, "category": "hardcoded"},
        {"description": "Dados de seed/fixture não vazam para ambiente de produção", "required": True, "category": "hardcoded"},
        # ── Campos em tela sem informação ─────────────────────────────────── #
        {"description": "Nenhum campo exibe 'null', 'undefined', 'NaN' ou string vazia sem tratamento", "required": True, "category": "ui_fields"},
        {"description": "Nenhum campo de nome/título exibe ID bruto (UUID, número) no lugar do label", "required": True, "category": "ui_fields"},
        {"description": "Campos de data formatados no locale correto (não ISO raw)", "required": True, "category": "ui_fields"},
        {"description": "Campos de valor monetário exibem símbolo e precisão de casas decimais corretos", "required": True, "category": "ui_fields"},
        {"description": "Campos de percentual exibem '%' e não fração decimal crua (0.85 → 85%)", "required": True, "category": "ui_fields"},
        {"description": "Campos opcionais vazios exibem placeholder ou '—' (não ficam em branco silencioso)", "required": True, "category": "ui_fields"},
        {"description": "Listas/tabelas com zero registros exibem estado vazio com mensagem explicativa", "required": True, "category": "ui_fields"},
        {"description": "Campos de imagem/avatar com fallback quando URL é inválida ou ausente", "required": True, "category": "ui_fields"},
        {"description": "Campos longos (descrição, bio) truncados com ellipsis e opção de expandir", "required": False, "category": "ui_fields"},
        {"description": "Campos de status exibem label legível, não enum interno (ACTIVE → Ativo)", "required": True, "category": "ui_fields"},
        {"description": "Tooltips ou labels secundários presentes quando campo tem restrição de negócio", "required": False, "category": "ui_fields"},
        {"description": "Campos calculados (total, saldo) exibem loading enquanto aguardam dados", "required": True, "category": "ui_fields"},
    ],
}


def create_checklist(
    store: TestStore,
    *,
    title: str,
    checklist_type: str,
    items: list[dict[str, Any]] | None = None,
    plan_id: str | None = None,
    use_template: bool = True,
) -> dict[str, Any]:
    """Cria um checklist com itens customizados ou a partir de template padrão."""
    if not title:
        return {"error": "ValidationError", "details": "title é obrigatório"}
    if checklist_type not in _VALID_CHECKLIST_TYPES:
        return {
            "error": "ValidationError",
            "details": f"checklist_type deve ser um de: {sorted(_VALID_CHECKLIST_TYPES)}",
        }
    if plan_id and not store.get_plan(plan_id):
        return {"error": "not_found", "details": f"Plano '{plan_id}' não encontrado"}

    if use_template and checklist_type in _CHECKLIST_TEMPLATES and not items:
        items = _CHECKLIST_TEMPLATES[checklist_type]
    elif not items:
        return {"error": "ValidationError", "details": "items é obrigatório quando use_template=False ou type='custom'"}

    for i, item in enumerate(items):
        if "description" not in item:
            return {"error": "ValidationError", "details": f"item[{i}] precisa de 'description'"}

    result = store.create_checklist(
        title=title,
        checklist_type=checklist_type,
        items=items,
        plan_id=plan_id,
    )
    result["hint"] = f"Use run_checklist(checklist_id='{result['checklist_id']}') para iniciar uma execução."
    return result


def run_checklist(
    store: TestStore,
    *,
    checklist_id: str,
    executor: str | None = None,
) -> dict[str, Any]:
    """Inicia uma execução (run) de um checklist — retorna todos os itens a verificar."""
    if not checklist_id:
        return {"error": "ValidationError", "details": "checklist_id é obrigatório"}

    result = store.start_run(checklist_id=checklist_id, executor=executor)
    if not result:
        return {"error": "not_found", "details": f"Checklist '{checklist_id}' não encontrado"}

    result["hint"] = (
        f"Use check_item(run_id='{result['run_id']}', item_id=<id>, status='passed'|'failed'|'na'|'blocked') "
        f"para marcar cada item. {len(result.get('items', []))} itens aguardam verificação."
    )
    return result


def check_item(
    store: TestStore,
    *,
    run_id: str,
    item_id: int,
    status: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Marca um item do checklist como passed/failed/na/blocked."""
    if not run_id or not item_id:
        return {"error": "ValidationError", "details": "run_id e item_id são obrigatórios"}
    if status not in _VALID_ITEM_STATUSES:
        return {
            "error": "ValidationError",
            "details": f"status deve ser um de: {sorted(_VALID_ITEM_STATUSES)}",
        }

    result = store.check_item(run_id=run_id, item_id=item_id, status=status, notes=notes)
    if not result:
        return {"error": "not_found", "details": f"Run '{run_id}' ou item '{item_id}' não encontrado"}

    run_status = store.get_run_status(run_id)
    return {
        **result,
        "run_summary": run_status.get("summary", {}),
        "run_status": run_status.get("status", "in_progress"),
    }


def get_run_status(
    store: TestStore,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Retorna o status atual de uma execução de checklist com todos os itens."""
    if not run_id:
        return {"error": "ValidationError", "details": "run_id é obrigatório"}

    result = store.get_run_status(run_id)
    if not result:
        return {"error": "not_found", "details": f"Run '{run_id}' não encontrado"}
    return result
