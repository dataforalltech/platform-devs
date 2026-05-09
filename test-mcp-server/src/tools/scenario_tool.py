"""Ferramentas de construção e execução de cenários de teste."""

from __future__ import annotations

from typing import Any

from ..db.store import TestStore

_VALID_CATEGORIES = {
    "happy_path", "auth", "boundary", "error", "edge_case",
    "empty_state", "pagination", "performance", "schema", "concurrency",
}
_VALID_PRIORITIES = {"critical", "high", "medium", "low"}
_VALID_RESULT_STATUSES = {"passed", "failed", "blocked", "skipped"}

# ── Templates de geração de cenários ──────────────────────────────────────── #

_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "rest_api": [
        {"name": "Happy path — GET autenticado retorna lista", "category": "happy_path", "priority": "critical",
         "preconditions": "Usuário autenticado com role adequada", "steps": "GET {endpoint} com token válido",
         "expected_result": "Status 200, body com array de objetos, headers corretos"},
        {"name": "Sem autenticação retorna 401", "category": "auth", "priority": "critical",
         "preconditions": "Sem token ou token ausente", "steps": "GET {endpoint} sem Authorization header",
         "expected_result": "Status 401, body com mensagem de erro"},
        {"name": "Token expirado retorna 401", "category": "auth", "priority": "high",
         "preconditions": "Token JWT expirado", "steps": "GET {endpoint} com token expirado",
         "expected_result": "Status 401"},
        {"name": "Role insuficiente retorna 403", "category": "auth", "priority": "high",
         "preconditions": "Usuário autenticado com role sem permissão", "steps": "GET {endpoint} com token de role baixa",
         "expected_result": "Status 403"},
        {"name": "Paginação padrão funciona", "category": "pagination", "priority": "high",
         "preconditions": "Dados existentes no banco", "steps": "GET {endpoint}?page=1&limit=10",
         "expected_result": "Status 200, retorna até 10 itens, inclui metadados de paginação"},
        {"name": "Página além do total retorna array vazio", "category": "pagination", "priority": "medium",
         "preconditions": "Total de itens conhecido", "steps": "GET {endpoint}?page=9999",
         "expected_result": "Status 200, array vazio, sem erro"},
        {"name": "Estado vazio — sem dados retorna []", "category": "empty_state", "priority": "high",
         "preconditions": "Banco sem registros para o recurso", "steps": "GET {endpoint}",
         "expected_result": "Status 200, data: [], não retorna null"},
        {"name": "limit=0 ou negativo retorna 400", "category": "boundary", "priority": "medium",
         "preconditions": None, "steps": "GET {endpoint}?limit=0 e GET {endpoint}?limit=-1",
         "expected_result": "Status 400 com mensagem de validação"},
        {"name": "limit muito alto é truncado ou rejeitado", "category": "boundary", "priority": "medium",
         "preconditions": None, "steps": "GET {endpoint}?limit=10000",
         "expected_result": "Status 200 com limite máximo aplicado, ou 400"},
        {"name": "Resposta tem schema correto", "category": "schema", "priority": "critical",
         "preconditions": "Ao menos 1 item existente", "steps": "GET {endpoint}, inspecionar body",
         "expected_result": "Todos os campos obrigatórios presentes, tipos corretos, sem campos extras inesperados"},
        {"name": "Tempo de resposta < 500ms", "category": "performance", "priority": "medium",
         "preconditions": "Dataset realista (100+ registros)", "steps": "GET {endpoint}, medir latência",
         "expected_result": "p95 < 500ms"},
        {"name": "DB indisponível retorna 500 sem stack trace", "category": "error", "priority": "high",
         "preconditions": "Simular falha de conexão com banco", "steps": "GET {endpoint}",
         "expected_result": "Status 500, mensagem genérica sem expor detalhes internos"},
    ],
    "react_component": [
        {"name": "Componente renderiza sem crash com props padrão", "category": "happy_path", "priority": "critical",
         "preconditions": "Props mínimas fornecidas", "steps": "Montar componente com props padrão",
         "expected_result": "Renderiza sem erro, sem console.error"},
        {"name": "Loading state exibido enquanto dados carregam", "category": "happy_path", "priority": "high",
         "preconditions": "Request pendente", "steps": "Montar componente antes do fetch concluir",
         "expected_result": "Skeleton ou spinner visível"},
        {"name": "Estado vazio exibe mensagem adequada", "category": "empty_state", "priority": "high",
         "preconditions": "API retorna lista vazia", "steps": "Montar componente com data=[]",
         "expected_result": "Mensagem de 'nenhum resultado' visível, sem erro"},
        {"name": "Erro de API exibe fallback de erro", "category": "error", "priority": "critical",
         "preconditions": "API retorna 500", "steps": "Montar componente com request falhando",
         "expected_result": "ErrorBoundary ou mensagem de erro amigável, sem crash branco"},
        {"name": "Sem console.error na renderização normal", "category": "edge_case", "priority": "high",
         "preconditions": "Dados válidos", "steps": "Montar componente, verificar console",
         "expected_result": "Zero erros no console"},
        {"name": "Prop obrigatória ausente é tratada", "category": "boundary", "priority": "medium",
         "preconditions": None, "steps": "Montar sem prop obrigatória",
         "expected_result": "Erro de PropTypes/TypeScript ou fallback gracioso"},
        {"name": "Ações (botões, links) disparam callbacks corretos", "category": "happy_path", "priority": "high",
         "preconditions": "Handlers mockados", "steps": "Clicar em ação, verificar callback chamado",
         "expected_result": "Callback chamado com argumentos corretos"},
        {"name": "Componente não vaza event listeners no unmount", "category": "edge_case", "priority": "medium",
         "preconditions": None, "steps": "Montar e desmontar componente",
         "expected_result": "Sem memory leaks, cleanup executado"},
    ],
    "auth_flow": [
        {"name": "Login com credenciais válidas retorna token", "category": "happy_path", "priority": "critical",
         "preconditions": "Usuário existente e ativo", "steps": "POST /auth/login com email e senha válidos",
         "expected_result": "Status 200, access_token e refresh_token retornados"},
        {"name": "Login com senha errada retorna 401", "category": "auth", "priority": "critical",
         "preconditions": "Usuário existente", "steps": "POST /auth/login com senha incorreta",
         "expected_result": "Status 401, sem token"},
        {"name": "Login com usuário inexistente retorna 401", "category": "auth", "priority": "high",
         "preconditions": None, "steps": "POST /auth/login com email não cadastrado",
         "expected_result": "Status 401 (não 404, para não vazar existência de usuário)"},
        {"name": "Refresh token válido gera novo access token", "category": "happy_path", "priority": "critical",
         "preconditions": "refresh_token válido e não expirado", "steps": "POST /auth/refresh com refresh_token",
         "expected_result": "Novo access_token retornado"},
        {"name": "Refresh token expirado retorna 401", "category": "auth", "priority": "high",
         "preconditions": "refresh_token expirado", "steps": "POST /auth/refresh",
         "expected_result": "Status 401, forçar novo login"},
        {"name": "Logout invalida token", "category": "happy_path", "priority": "high",
         "preconditions": "Usuário logado", "steps": "POST /auth/logout, tentar usar token revogado",
         "expected_result": "Token revogado retorna 401 em chamadas subsequentes"},
        {"name": "Tentativas repetidas de login bloqueiam (rate limit)", "category": "boundary", "priority": "high",
         "preconditions": None, "steps": "10+ tentativas de login em sequência rápida",
         "expected_result": "Status 429 após threshold, com retry-after"},
    ],
    "db_migration": [
        {"name": "Migration UP executa sem erro", "category": "happy_path", "priority": "critical",
         "preconditions": "Banco no estado anterior", "steps": "Executar migration UP",
         "expected_result": "Sem erros, schema atualizado conforme esperado"},
        {"name": "Migration DOWN (rollback) executa sem erro", "category": "happy_path", "priority": "critical",
         "preconditions": "Banco com migration aplicada", "steps": "Executar migration DOWN",
         "expected_result": "Schema revertido, dados não corrompidos"},
        {"name": "Migration é idempotente", "category": "edge_case", "priority": "high",
         "preconditions": None, "steps": "Executar migration UP duas vezes",
         "expected_result": "Sem erro na segunda execução (IF NOT EXISTS / idempotência)"},
        {"name": "Dados existentes sobrevivem à migration", "category": "boundary", "priority": "critical",
         "preconditions": "Banco com dados realistas", "steps": "Executar UP, verificar dados",
         "expected_result": "Registros existentes preservados, sem truncate acidental"},
        {"name": "Coluna NOT NULL tem default ou backfill", "category": "schema", "priority": "critical",
         "preconditions": "Tabela com dados existentes", "steps": "Aplicar migration com nova coluna NOT NULL",
         "expected_result": "Migration não falha por constraint violation"},
    ],
    "websocket": [
        {"name": "Conexão WS estabelecida com token válido", "category": "happy_path", "priority": "critical",
         "preconditions": "Token JWT válido", "steps": "Conectar ao endpoint WS com token no header/query",
         "expected_result": "Handshake bem-sucedido, código 101"},
        {"name": "Conexão sem token é rejeitada", "category": "auth", "priority": "critical",
         "preconditions": None, "steps": "Conectar sem token",
         "expected_result": "Conexão recusada com código 4001 ou similar"},
        {"name": "Mensagem enviada e recebida corretamente", "category": "happy_path", "priority": "high",
         "preconditions": "Conexão estabelecida", "steps": "Enviar mensagem, aguardar echo/response",
         "expected_result": "Mensagem recebida com schema correto"},
        {"name": "Reconexão automática após queda", "category": "edge_case", "priority": "high",
         "preconditions": None, "steps": "Derrubar conexão, verificar cliente reconecta",
         "expected_result": "Cliente reconecta com backoff, sem duplicação de handlers"},
        {"name": "Heartbeat/ping mantém conexão viva", "category": "performance", "priority": "medium",
         "preconditions": "Conexão idle por 60s+", "steps": "Monitorar frames de ping/pong",
         "expected_result": "Conexão não é encerrada por timeout idle"},
    ],
    "form_validation": [
        {"name": "Submit com dados válidos funciona", "category": "happy_path", "priority": "critical",
         "preconditions": "Todos os campos obrigatórios preenchidos", "steps": "Preencher form, clicar submit",
         "expected_result": "Sucesso, feedback positivo ao usuário"},
        {"name": "Campo obrigatório vazio impede submit", "category": "boundary", "priority": "critical",
         "preconditions": None, "steps": "Deixar campo obrigatório em branco, submeter",
         "expected_result": "Mensagem de erro inline, submit bloqueado"},
        {"name": "Formato de email inválido exibe erro", "category": "boundary", "priority": "high",
         "preconditions": None, "steps": "Inserir 'nao-é-email', submeter",
         "expected_result": "Erro de formato exibido, submit bloqueado"},
        {"name": "Campos com limite de caracteres validam", "category": "boundary", "priority": "medium",
         "preconditions": None, "steps": "Inserir string além do max length",
         "expected_result": "Input truncado ou erro exibido"},
        {"name": "Submit duplo não cria duplicatas", "category": "concurrency", "priority": "high",
         "preconditions": None, "steps": "Clicar submit duas vezes rapidamente",
         "expected_result": "Apenas uma requisição enviada, botão desabilitado após primeiro click"},
        {"name": "Reset limpa todos os campos", "category": "happy_path", "priority": "medium",
         "preconditions": "Form com dados preenchidos", "steps": "Clicar reset/cancelar",
         "expected_result": "Todos os campos voltam ao estado inicial"},
        {"name": "Erro de API exibido ao usuário", "category": "error", "priority": "critical",
         "preconditions": None, "steps": "API retorna 400/500, submeter form",
         "expected_result": "Mensagem de erro amigável exibida, dados do form preservados"},
    ],
    "ui_data_validation": [
        {"name": "Campos não exibem 'null' ou 'undefined'", "category": "edge_case", "priority": "critical",
         "preconditions": "Registro com campos opcionais não preenchidos",
         "steps": "Abrir tela com dado incompleto, inspecionar visualmente cada campo",
         "expected_result": "Nenhum campo exibe string 'null', 'undefined', 'NaN' ou fica vazio sem tratamento"},
        {"name": "IDs brutos não vazam para a interface", "category": "edge_case", "priority": "critical",
         "preconditions": "Registro com referências (FK, enum, UUID)",
         "steps": "Abrir tela, verificar campos de nome, status, categoria, tipo",
         "expected_result": "Nenhum campo exibe UUID, número ou código interno — exibe label legível ao usuário"},
        {"name": "Dados hardcoded não aparecem em produção", "category": "edge_case", "priority": "critical",
         "preconditions": "Deploy em ambiente de produção ou hml",
         "steps": "Inspecionar source/bundle, verificar chamadas de rede via devtools, checar valores exibidos",
         "expected_result": "Sem 'Lorem ipsum', 'John Doe', 'test@test.com', IDs fixos ou URLs de dev hardcoded"},
        {"name": "Stubs e mocks não estão ativos em produção", "category": "edge_case", "priority": "critical",
         "preconditions": "Deploy em produção",
         "steps": "Abrir devtools > Network, navegar pelas funcionalidades e verificar destino das requisições",
         "expected_result": "Todas as requisições chegam ao backend real — sem interceptors de mock ativos"},
        {"name": "Datas exibidas no formato e locale corretos", "category": "schema", "priority": "high",
         "preconditions": "Registros com campos de data preenchidos",
         "steps": "Abrir tela com diferentes datas (passado, futuro, hoje), verificar formato",
         "expected_result": "Datas no formato local (dd/mm/aaaa), não ISO raw (2026-01-01T00:00:00Z)"},
        {"name": "Valores monetários formatados corretamente", "category": "schema", "priority": "high",
         "preconditions": "Registros com campos de valor ou preço",
         "steps": "Abrir tela com valores monetários variados (zero, centavos, milhares)",
         "expected_result": "R$ 1.234,56 (ou padrão do projeto) — não 1234.5600 ou valor bruto sem símbolo"},
        {"name": "Campos opcionais vazios exibem placeholder adequado", "category": "empty_state", "priority": "high",
         "preconditions": "Registro com campos opcionais não preenchidos",
         "steps": "Abrir tela de detalhe com dado sem campos opcionais",
         "expected_result": "Campo exibe '—', 'Não informado' ou placeholder definido — não fica em branco silencioso"},
        {"name": "Estado vazio de listas exibe mensagem explicativa", "category": "empty_state", "priority": "high",
         "preconditions": "Contexto sem registros para listar",
         "steps": "Abrir tela de listagem sem dados cadastrados",
         "expected_result": "Mensagem de estado vazio visível (ex: 'Nenhum item encontrado') — não tabela vazia sem explicação"},
        {"name": "Avatares e imagens têm fallback quando URL falha", "category": "error", "priority": "medium",
         "preconditions": "Registro com URL de imagem inválida, expirada ou ausente",
         "steps": "Abrir tela com imagem quebrada (bloquear URL no devtools ou usar URL inválida)",
         "expected_result": "Exibe avatar padrão ou iniciais do usuário — sem ícone quebrado visível"},
        {"name": "Campos de status exibem label legível", "category": "schema", "priority": "high",
         "preconditions": "Registros com diferentes valores de status/enum",
         "steps": "Abrir listagem e detalhe com itens em diferentes status",
         "expected_result": "Status exibe texto legível (Ativo, Inativo, Pendente) — não enum interno (ACTIVE, PENDING_REVIEW)"},
        {"name": "Campos calculados exibem loading enquanto aguardam", "category": "happy_path", "priority": "medium",
         "preconditions": "Conexão lenta simulada (devtools throttle)",
         "steps": "Abrir tela com throttle de rede ativo, observar campos calculados (total, saldo, contagem)",
         "expected_result": "Skeleton ou spinner visível durante carga — não exibe zero, vazio ou valor inconsistente"},
        {"name": "Percentuais exibem '%' e não fração decimal", "category": "schema", "priority": "medium",
         "preconditions": "Campos de taxa, desconto ou crescimento percentual",
         "steps": "Abrir tela com valores percentuais (ex: taxa de 85%)",
         "expected_result": "Campo exibe '85%' — não '0.85' ou '0.8500'"},
        {"name": "Truncamento de texto longo não quebra layout", "category": "boundary", "priority": "medium",
         "preconditions": "Registro com texto muito longo (200+ caracteres) em campo de descrição",
         "steps": "Abrir tela de listagem e detalhe com texto longo",
         "expected_result": "Texto truncado com '...' e opção de expandir — não vaza para fora do container"},
    ],
}


def generate_scenarios(
    store: TestStore,
    *,
    plan_id: str,
    category: str,
    context: str | None = None,
) -> dict[str, Any]:
    """Gera e salva cenários padrão baseados na categoria da feature."""
    if not plan_id:
        return {"error": "ValidationError", "details": "plan_id é obrigatório"}
    if category not in _TEMPLATES:
        return {
            "error": "ValidationError",
            "details": f"category deve ser um de: {sorted(_TEMPLATES.keys())}",
        }
    if not store.get_plan(plan_id):
        return {"error": "not_found", "details": f"Plano '{plan_id}' não encontrado"}

    templates = _TEMPLATES[category]
    created = []
    for tmpl in templates:
        name = tmpl["name"]
        steps = tmpl["steps"]
        # Substituir placeholder {endpoint} pelo context se fornecido
        if context:
            name = name.replace("{endpoint}", context)
            steps = steps.replace("{endpoint}", context)

        result = store.add_scenario(
            plan_id=plan_id,
            name=name,
            category=tmpl["category"],
            steps=steps,
            expected_result=tmpl["expected_result"],
            priority=tmpl["priority"],
            preconditions=tmpl.get("preconditions"),
        )
        created.append(result)

    return {
        "plan_id": plan_id,
        "category": category,
        "generated_count": len(created),
        "scenarios": created,
        "hint": f"Use add_scenario para adicionar cenários específicos além dos {len(created)} gerados.",
    }


def add_scenario(
    store: TestStore,
    *,
    plan_id: str,
    name: str,
    category: str,
    steps: str,
    expected_result: str,
    priority: str = "medium",
    preconditions: str | None = None,
) -> dict[str, Any]:
    """Adiciona um cenário de teste específico ao plano."""
    if not plan_id or not name or not steps or not expected_result:
        return {"error": "ValidationError", "details": "plan_id, name, steps e expected_result são obrigatórios"}
    if category not in _VALID_CATEGORIES:
        return {"error": "ValidationError", "details": f"category deve ser um de: {sorted(_VALID_CATEGORIES)}"}
    if priority not in _VALID_PRIORITIES:
        return {"error": "ValidationError", "details": f"priority deve ser um de: {sorted(_VALID_PRIORITIES)}"}
    if not store.get_plan(plan_id):
        return {"error": "not_found", "details": f"Plano '{plan_id}' não encontrado"}

    return store.add_scenario(
        plan_id=plan_id,
        name=name,
        category=category,
        steps=steps,
        expected_result=expected_result,
        priority=priority,
        preconditions=preconditions,
    )


def record_result(
    store: TestStore,
    *,
    plan_id: str,
    scenario_id: int,
    status: str,
    actual_result: str | None = None,
    notes: str | None = None,
    evidence: str | None = None,
) -> dict[str, Any]:
    """Registra o resultado da execução de um cenário."""
    if not plan_id or not scenario_id:
        return {"error": "ValidationError", "details": "plan_id e scenario_id são obrigatórios"}
    if status not in _VALID_RESULT_STATUSES:
        return {"error": "ValidationError", "details": f"status deve ser um de: {sorted(_VALID_RESULT_STATUSES)}"}
    if not store.get_plan(plan_id):
        return {"error": "not_found", "details": f"Plano '{plan_id}' não encontrado"}

    return store.record_result(
        plan_id=plan_id,
        scenario_id=scenario_id,
        status=status,
        actual_result=actual_result,
        notes=notes,
        evidence=evidence,
    )
