"""Tools de políticas: camadas, fallback, contrato, ações proibidas."""

from __future__ import annotations

from ..knowledge.governance_repository import GovernanceRepository
from ..utils.validators import (
    coerce_string_list,
    normalize_contract_type,
    normalize_layer,
    require_non_empty_string,
    safe_lower,
)

# ----------------------------------------------------------------------- #
# Políticas de camada                                                     #
# ----------------------------------------------------------------------- #
_LAYER_POLICIES: dict[str, dict] = {
    "frontend": {
        "responsibilities": [
            "Consumir contratos REST/WebSocket/GraphQL definidos pelo backend.",
            "Renderizar estados de loading, erro, vazio e sucesso explicitamente.",
            "Validar entrada do usuário no cliente para UX (nunca como única validação).",
        ],
        "can_do": [
            "Cache local seguindo o padrão do projeto (SWR, React Query, etc.).",
            "Tratar erros traduzindo para mensagens UX a partir de códigos da API.",
            "Feature flags via configuração injetada (não hardcoded).",
        ],
        "cannot_do": [
            "Inventar regra de negócio (cálculo de imposto, permissão, desconto).",
            "Esconder erro de API com try/catch que devolve estado falso.",
            "Hardcoded de URL de API, tenant_id ou tokens.",
        ],
        "wrong_examples": [
            "try { return await api.createOrder(p); } catch { return {id:-1, status:'pending'}; }",
            "const API_URL = 'https://prod.example.com/api';  // hardcoded",
        ],
        "correct_examples": [
            "try { return await api.createOrder(p); } catch (err) { throw new OrderCreationError(err.message, {cause: err}); }",
            "const API_URL = config.apiBaseUrl;  // vem de configuração",
        ],
    },
    "backend": {
        "responsibilities": [
            "Definir e versionar contratos (REST/eventos).",
            "Validar entrada (autoritativo) e aplicar regras de negócio.",
            "Garantir observabilidade (logs estruturados + métricas).",
        ],
        "can_do": [
            "Retornar erros estruturados com código + mensagem.",
            "Rejeitar input inválido com 4xx claro.",
            "Emitir eventos de domínio com schema versionado.",
        ],
        "cannot_do": [
            "Vazar UX para a API (texto formatado para tela, traduções, cores).",
            "Fallback silencioso convertendo erro 500 em 200.",
            "Misturar lógica de transporte com lógica de negócio.",
        ],
        "wrong_examples": [
            "try: return process(req)\\nexcept: return {'status':'ok'}  # engole erro",
            "raise HTTPException(500, 'Ocorreu um erro, tente novamente em alguns minutos')  # mensagem de UX",
        ],
        "correct_examples": [
            "try: return process(req)\\nexcept ProviderError as e: log.exception(...); raise HTTPException(502, code='provider_unavailable')",
            "raise HTTPException(409, detail={'code':'order_already_paid','message':'Order is already paid'})",
        ],
    },
    "database": {
        "responsibilities": [
            "Garantir integridade referencial e constraints corretas.",
            "Versionar schema via migrations (Alembic, etc.).",
            "Manter índices apropriados a queries reais do produto.",
        ],
        "can_do": [
            "Criar tabela/coluna via migration reversível.",
            "Renomear coluna em duas etapas (add+backfill+swap+remove).",
            "Adicionar constraint NOT NULL com default ou backfill prévio.",
        ],
        "cannot_do": [
            "Rodar `DROP`/`TRUNCATE` em código de aplicação.",
            "Adicionar `NOT NULL` em coluna existente sem backfill.",
            "Migrar dados em hotpath de request HTTP.",
        ],
        "wrong_examples": [
            "ALTER TABLE orders ALTER COLUMN customer_id SET NOT NULL;  -- sem backfill em tabela grande",
            "session.execute('DROP TABLE legacy_orders')  -- DROP em código de app",
        ],
        "correct_examples": [
            "Migration: 1) add column nullable, 2) backfill em batch, 3) ALTER NOT NULL.",
            "Operação destrutiva via runbook controlado, não código de app.",
        ],
    },
    "integrations": {
        "responsibilities": [
            "Encapsular comunicação com sistema externo em cliente dedicado.",
            "Definir timeout, retry e circuit breaker explícitos.",
            "Logar correlation_id e métricas em toda chamada.",
        ],
        "can_do": [
            "Retry exponencial em erros transitórios (5xx, timeout).",
            "Circuit breaker para parceiro instável.",
            "Cache curto para reduzir carga em integrações idempotentes.",
        ],
        "cannot_do": [
            "Chamar parceiro externo sem timeout.",
            "Engolir erro do parceiro com try/except genérico.",
            "Fallback para mock/dado fake em produção sem flag explícita.",
        ],
        "wrong_examples": [
            "requests.get(url)  # sem timeout, sem retry, sem log",
            "try: provider.charge(amount)\\nexcept: pass  # silencioso",
        ],
        "correct_examples": [
            "httpx.get(url, timeout=5.0); log.info('provider_call', extra={'correlation_id':..., 'latency_ms':...})",
            "try: provider.charge(...)\\nexcept ProviderTimeout as e: metrics.inc('provider.timeout'); raise",
        ],
    },
    "infrastructure": {
        "responsibilities": [
            "Definir Dockerfile, compose, helm/k8s manifests do serviço.",
            "Garantir que pipelines de CI/CD reflitam o padrão do ecossistema.",
            "Manter secrets fora do repositório (cofre/SOPS/sealed-secrets).",
        ],
        "can_do": [
            "Atualizar versão de imagem base com justificativa.",
            "Adicionar variável de ambiente nova em `.env.example` documentada.",
            "Ajustar healthcheck/probes conforme contrato do template.",
        ],
        "cannot_do": [
            "Commitar `.env` real, secrets, certificados ou tokens.",
            "Pular hooks/CI com `--no-verify` ou flags equivalentes.",
            "Mudar `.gitignore`/`pyproject.toml`/`package.json` sem necessidade da tarefa.",
        ],
        "wrong_examples": [
            "git commit --no-verify -m 'fix'  # pula hooks",
            "ENV API_TOKEN=sk-real-token  # secret no Dockerfile",
        ],
        "correct_examples": [
            "ENV API_TOKEN  # injetado em runtime via cofre",
            "Atualização de versão em PR dedicado com changelog.",
        ],
    },
    "security": {
        "responsibilities": [
            "Garantir que toda rota é autenticada por padrão.",
            "Aplicar autorização por tenant/scope/role explicitamente.",
            "Manter logs livres de credenciais e PII bruta.",
        ],
        "can_do": [
            "Adicionar rate limit em rotas sensíveis.",
            "Rotacionar tokens/segredos via cofre.",
            "Auditar acesso a recursos sensíveis com logs estruturados.",
        ],
        "cannot_do": [
            "Bypass de autenticação 'só para resolver bug rápido'.",
            "Logar token, senha, CPF ou cartão em texto puro.",
            "Aceitar input do cliente como ID de tenant (deve vir do token).",
        ],
        "wrong_examples": [
            "if request.headers.get('X-Skip-Auth'): return handler()  # bypass",
            "log.info(f'login {user.email} pwd={user.password}')  # senha em log",
        ],
        "correct_examples": [
            "@requires_auth\\ndef handler(...): tenant_id = ctx.tenant_id  # vem do token",
            "log.info('login_success', extra={'user_id': user.id})",
        ],
    },
    "observability": {
        "responsibilities": [
            "Garantir que toda integração crítica tem log + métrica + alerta.",
            "Padronizar campos: request_id, tenant_id, correlation_id, user_id.",
            "Manter dashboards e SLOs alinhados ao SLA do produto.",
        ],
        "can_do": [
            "Adicionar contadores/histogramas para fluxo crítico novo.",
            "Adicionar tracing distribuído entre serviços via OTel.",
            "Criar alerta com runbook documentado.",
        ],
        "cannot_do": [
            "Engolir exceção sem `log.exception(...)`.",
            "Métrica sem unidade (latency_ms vs latency_s).",
            "Logar payload bruto contendo PII.",
        ],
        "wrong_examples": [
            "except Exception: pass",
            "metrics.timer('latency').observe(t)  # qual unidade?",
        ],
        "correct_examples": [
            "except ProviderError: log.exception('provider_failed', extra={...}); metrics.inc('provider.fail'); raise",
            "metrics.histogram('latency_ms', value=t_ms)",
        ],
    },
    "testing": {
        "responsibilities": [
            "Bugfix sem teste de regressão é incompleto.",
            "Cobertura é resultado, não meta — mas teste deve cobrir caminho crítico.",
            "Testes determinísticos: sem `time.sleep` arbitrário, sem ordem dependente.",
        ],
        "can_do": [
            "Usar fakes/stubs para serviços externos em testes unitários.",
            "Testes de integração com banco real em containers efêmeros.",
            "Snapshot tests para contratos estáveis.",
        ],
        "cannot_do": [
            "Apagar teste para fazer build passar.",
            "Marcar teste como `skip` permanentemente sem ADR.",
            "Mockar o sistema sob teste (perde valor do teste).",
        ],
        "wrong_examples": [
            "@pytest.mark.skip('flaky')  # sem ADR, sem owner",
            "mock.patch('myapp.OrderService.calc')  # mockando o que está sendo testado",
        ],
        "correct_examples": [
            "def test_calc_with_zero_items(): ...  # caso de regressão do bug #1234",
            "Integration test com Postgres real via testcontainers.",
        ],
    },
}


def get_layer_policy(repo: GovernanceRepository, layer: str) -> dict:
    """Retorna a política de uma camada específica."""
    layer_norm = normalize_layer(layer)
    if not layer_norm:
        raise ValueError("layer é obrigatório")
    payload = _LAYER_POLICIES.get(layer_norm)
    if not payload:
        raise ValueError(f"layer sem política definida: {layer_norm}")

    doc = repo.get_layer_document(layer_norm)
    source = doc.name if doc else f"{layer_norm}.md"

    return {
        "layer": layer_norm,
        **payload,
        "source": source,
    }


# ----------------------------------------------------------------------- #
# Ações proibidas                                                         #
# ----------------------------------------------------------------------- #
_FORBIDDEN_ACTIONS = [
    {
        "id": "silent-fallback",
        "action": "Criar fallback silencioso (try/except retornando dado fake) para 'fazer funcionar'.",
        "reason": "Esconde a falha real, retarda detecção em produção e mascara incidentes.",
        "correct_alternative": "Propagar a exceção com contexto, logar com `log.exception(...)`, emitir métrica e deixar a UI tratar.",
        "applies_to": ["frontend", "backend", "integrations"],
    },
    {
        "id": "hardcoded-config",
        "action": "Chumbar URL, credencial, token, ID de tenant ou data no código.",
        "reason": "Quebra reproduzibilidade, expõe segredos, impede operação multi-ambiente.",
        "correct_alternative": "Vir de configuração (env var, cofre, settings tipado).",
        "applies_to": ["frontend", "backend", "infrastructure", "security"],
    },
    {
        "id": "cross-layer-shortcut",
        "action": "Resolver bug de backend aplicando workaround no frontend (ou vice-versa).",
        "reason": "Solução na camada errada, dificulta manutenção, mascara dívida técnica.",
        "correct_alternative": "Corrigir na camada responsável; abrir issue/ADR se a fronteira for ambígua.",
        "applies_to": ["frontend", "backend"],
    },
    {
        "id": "generic-try-except",
        "action": "Usar `try/except Exception: pass` em integração.",
        "reason": "Engole exceções, bloqueia observabilidade e esconde bugs.",
        "correct_alternative": "Capturar exceção específica, logar com contexto, decidir explicitamente entre re-raise e fallback documentado.",
        "applies_to": ["backend", "integrations"],
    },
    {
        "id": "mock-in-prod",
        "action": "Manter `MockProvider` ou retorno fake em código produtivo para contornar serviço caído.",
        "reason": "Mock em produção mascara problemas reais e cria divergência prod/teste.",
        "correct_alternative": "Failover documentado com flag explícita + alerta + plano de retorno.",
        "applies_to": ["backend", "integrations"],
    },
    {
        "id": "contract-break",
        "action": "Alterar contrato (API, evento, schema) sem atualizar consumidores e testes.",
        "reason": "Quebra cadeia de dependências em produção; consumidor descobre em runtime.",
        "correct_alternative": "Versionar contrato, comunicar consumidores, manter compatibilidade durante deprecation.",
        "applies_to": ["backend", "integrations"],
    },
    {
        "id": "delete-tests",
        "action": "Apagar ou marcar como skip permanente um teste para fazer o build passar.",
        "reason": "Esconde regressão, engana o pipeline, vira dívida silenciosa.",
        "correct_alternative": "Investigar a causa real do teste falhar; se o teste estava errado, corrigir o teste com PR explicando.",
        "applies_to": ["testing"],
    },
    {
        "id": "auth-bypass",
        "action": "Adicionar bypass de autenticação ou autorização para resolver bug rapidamente.",
        "reason": "Cria vulnerabilidade real e duradoura; bypass viraliza por copy-paste.",
        "correct_alternative": "Resolver o bug propriamente; se rota precisa ser pública, exige ADR e revisão de segurança.",
        "applies_to": ["security", "backend"],
    },
    {
        "id": "premature-abstraction",
        "action": "Criar classe/factory/service apenas para 'deixar genérico'.",
        "reason": "Abstração prematura é dívida imediata; três usos similares < uma abstração errada.",
        "correct_alternative": "Aceitar repetição até existir caso de uso real; abstrair com base em código existente.",
        "applies_to": ["frontend", "backend"],
    },
    {
        "id": "skip-hooks",
        "action": "Pular hooks de pré-commit ou CI com `--no-verify`, `--skip-tests`, etc.",
        "reason": "Hooks existem por motivo — pulá-los introduz a regressão que eles protegem contra.",
        "correct_alternative": "Investigar o motivo do hook falhar e corrigir a causa real.",
        "applies_to": ["infrastructure", "testing"],
    },
    {
        "id": "weakened-validation",
        "action": "Reduzir validações ou checagens de segurança para passar build.",
        "reason": "Cria vulnerabilidade ou dado inválido em produção.",
        "correct_alternative": "Corrigir a causa real do input inválido na origem.",
        "applies_to": ["backend", "security"],
    },
    {
        "id": "broad-refactor",
        "action": "Refatorar amplamente arquivos não relacionados durante uma tarefa pequena.",
        "reason": "Polui o diff, dificulta revisão e bissecção quando algo quebra.",
        "correct_alternative": "PR dedicado de refactor, com escopo descrito e testes preservados.",
        "applies_to": ["frontend", "backend", "database"],
    },
    {
        "id": "unjustified-dependency",
        "action": "Adicionar nova dependência sem justificativa ou alternativa avaliada.",
        "reason": "Aumenta supply chain risk, tempo de build e superfície de manutenção.",
        "correct_alternative": "Avaliar dependências existentes; se nova é necessária, justificar no PR.",
        "applies_to": ["frontend", "backend", "infrastructure"],
    },
    {
        "id": "missing-observability",
        "action": "Adicionar integração crítica sem log estruturado, métrica e alerta.",
        "reason": "Cria cegueira operacional — falha em produção sem evidência.",
        "correct_alternative": "Log + métrica + alerta + runbook antes de fazer merge.",
        "applies_to": ["backend", "integrations", "observability"],
    },
]


def get_forbidden_actions(repo: GovernanceRepository, context: str | None = None) -> dict:
    """Lista ações proibidas, opcionalmente filtradas por contexto."""
    ctx = safe_lower(context)
    items = _FORBIDDEN_ACTIONS
    if ctx:
        items = [
            item
            for item in items
            if ctx in item["id"]
            or ctx in item["action"].lower()
            or any(ctx == applies for applies in item["applies_to"])
        ]
    return {
        "context": ctx,
        "total": len(items),
        "forbidden_actions": items,
    }


# ----------------------------------------------------------------------- #
# Política de fallback                                                    #
# ----------------------------------------------------------------------- #
def get_fallback_policy(
    repo: GovernanceRepository,
    scenario: str,
    service_name: str | None = None,
) -> dict:
    """Define quando fallback é permitido e quais condições são obrigatórias."""
    require_non_empty_string(scenario, "scenario")
    scenario_lower = scenario.lower()

    forbidden_keywords = ["silencioso", "silent", "esconder", "mascarar", "ocultar"]
    silent = any(kw in scenario_lower for kw in forbidden_keywords)

    if silent:
        return {
            "scenario": scenario,
            "service_name": service_name,
            "fallback_allowed": False,
            "mandatory_conditions": [],
            "required_logs_metrics": [],
            "required_tests": [],
            "required_documentation": [],
            "forbidden_cases": [
                "Fallback que retorna dado fake/sucesso falso quando upstream falha.",
                "Try/except genérico capturando e ignorando exceção.",
                "Conversão silenciosa de 5xx em 2xx.",
            ],
            "rationale": (
                "Fallback silencioso é proibido em qualquer cenário do ecossistema. "
                "Se o upstream falha, a falha precisa ser visível em log + métrica e "
                "tratada explicitamente."
            ),
        }

    return {
        "scenario": scenario,
        "service_name": service_name,
        "fallback_allowed": True,
        "mandatory_conditions": [
            "Fallback explícito e nomeado (não anônimo dentro de try/except).",
            "Decisão de fallback feita no caller, não escondida em camada baixa.",
            "Cenário de fallback documentado na seção de operação do serviço.",
            "Flag/feature toggle ou estado explícito quando fallback é usado.",
        ],
        "required_logs_metrics": [
            "log.warning('fallback_triggered', extra={'reason': ..., 'service': ...})",
            "Métrica `<service>.fallback.count` incrementada.",
            "Alerta se taxa de fallback > X% por janela Y (a definir por serviço).",
        ],
        "required_tests": [
            "Teste do happy path (upstream OK).",
            "Teste do path de fallback (upstream falha).",
            "Teste de timeout/circuit breaker se aplicável.",
        ],
        "required_documentation": [
            "Seção 'Comportamento em falha' no README do serviço.",
            "Runbook do alerta de fallback excessivo.",
        ],
        "forbidden_cases": [
            "Fallback retornando dado fake como se fosse sucesso real.",
            "Fallback sem alerta quando taxa fica anômala.",
            "Fallback em fluxo financeiro/transacional sem ADR explícito.",
        ],
        "rationale": (
            "Fallback é aceitável quando explícito, observável, testado e documentado. "
            "Tudo que não cumpre esses 4 critérios cai como fallback silencioso e é proibido."
        ),
    }


# ----------------------------------------------------------------------- #
# Política de alteração de contrato                                       #
# ----------------------------------------------------------------------- #
def get_contract_change_policy(
    repo: GovernanceRepository,
    provider_service: str,
    consumer_services: list[str] | str | None,
    contract_type: str,
    proposed_change: str,
) -> dict:
    """Devolve regras + checklist para mudança de contrato."""
    require_non_empty_string(provider_service, "provider_service")
    require_non_empty_string(proposed_change, "proposed_change")
    contract_norm = normalize_contract_type(contract_type)
    consumers = coerce_string_list(consumer_services)

    change_lower = proposed_change.lower()
    breaking_keywords = [
        "remov",
        "delete",
        "rename",
        "renomear",
        "alterar tipo",
        "change type",
        "mudar campo",
        "drop",
        "obrigat",
        "required",
    ]
    is_breaking = any(kw in change_lower for kw in breaking_keywords)

    risk_level = "high" if is_breaking else "medium"
    if not consumers:
        # Provider sem consumidor declarado: alto risco — provavelmente o agente
        # está afirmando "ninguém usa", o que é raramente verdade.
        risk_level = "high" if is_breaking else "high"

    compat_rules = [
        "Adicionar campo opcional é compatível.",
        "Remover campo, renomear ou mudar tipo é breaking change.",
        "Tornar campo obrigatório (antes opcional) é breaking change.",
        "Mudar semântica de campo existente é breaking change.",
    ]
    if contract_norm == "event":
        compat_rules += [
            "Eventos são versionados — mudanças breaking exigem novo `topic_v2`.",
            "Consumidores legados continuam recebendo `v1` durante deprecation.",
        ]
    if contract_norm == "database":
        compat_rules += [
            "Renomear coluna em duas etapas: add+backfill+swap+remove.",
            "DROP de coluna só após remover todos os reads/writes.",
        ]
    if contract_norm == "api":
        compat_rules += [
            "Versionar via path (`/v1`, `/v2`) ou via header explícito.",
            "Manter `v1` em paralelo até consumidores migrarem.",
        ]

    expected_impacts = (
        ["Consumidores legados quebram em runtime se a mudança for deployada."]
        if is_breaking
        else ["Mudança aditiva — consumidores continuam funcionando sem alteração."]
    )
    if not consumers:
        expected_impacts.append(
            "Lista de consumidores não foi declarada — o agente DEVE buscar no monorepo "
            "e em outros repositórios antes de prosseguir."
        )

    update_checklist = [
        "Listar consumidores reais via grep no monorepo + lista de serviços que dependem do provider.",
        "Atualizar schema/OpenAPI/AsyncAPI no provider.",
        "Comunicar consumidores via canal de coordenação.",
        "Atualizar libs cliente (se houver).",
        "Definir janela de deprecation se for breaking.",
    ]
    if is_breaking:
        update_checklist += [
            "Manter contrato antigo em paralelo até todos consumidores migrarem.",
            "Adicionar deprecation warning no contrato antigo.",
            "Definir data de remoção do contrato antigo.",
        ]

    mandatory_tests = [
        "Testes de contrato no provider (validam o schema declarado).",
        "Testes de integração entre provider e ao menos um consumidor.",
    ]
    if contract_norm == "api":
        mandatory_tests.append("Smoke test contra ambiente de homologação após deploy.")
    if contract_norm == "event":
        mandatory_tests.append("Replay de eventos legados em ambiente de homologação.")

    mandatory_docs = [
        "ADR descrevendo motivação e plano de migração (se breaking).",
        "Atualização de README do provider.",
        "Changelog com versão semver bump correto.",
    ]

    return {
        "provider_service": provider_service,
        "consumer_services": consumers,
        "contract_type": contract_norm,
        "proposed_change": proposed_change,
        "is_breaking_change": is_breaking,
        "risk_level": risk_level,
        "compatibility_rules": compat_rules,
        "expected_impacts": expected_impacts,
        "update_checklist": update_checklist,
        "mandatory_tests": mandatory_tests,
        "mandatory_documentation": mandatory_docs,
    }
