"""Entidades canônicas do domínio `guardian` (ADR-018) — Pydantic v2.

Dirigem duas camadas do ORM canônico (`platform_database.orm`): DDL IR
(`create_table_from_model` — injeta as colunas-padrão da plataforma) e o Repository
(CRUD tipado). Fase 1 (ADR-018): o núcleo versionado das diretrizes.

Convenções (playbook §5): colunas de auditoria/controle padrão (``id``, ``id_user_*``,
``create_on``, ``active``, ``excluded``, ``timestamp_refresh``, ``scope``) são injetadas
pela fábrica de schema — NÃO são redeclaradas aqui. Colunas de chave natural/filtro
carregam ``max_length`` explícito (viram ``VARCHAR(n)`` indexável, não ``TEXT``).

Rejeição de JSON-blob (ADR-018 D18.2): front-matter → colunas; prosa genuína (contexto/
decisão/racional) → ``TEXT``; nada de lista/objeto estruturado serializado em coluna.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GovKindCapabilityRow(BaseModel):
    """Referência: capacidades de cada kind (camada, RFC2119, file:line, forma do corpo).

    Absorve o que era derivado do kind (ADR-018 D18 N1): ``allows_rfc2119`` só p/ standard/
    ADR-decisão; ``allows_fileline`` só p/ reference_arch; ``body_shape`` declara prosa×typed.
    Chave natural única: ``kind``.
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    kind: str = Field(max_length=40)  # chave natural -> VARCHAR(40)
    layer: int | None = None  # 1..5 ou NULL
    allows_rfc2119: bool = False
    allows_fileline: bool = False
    body_shape: str = Field(default="prose", max_length=24)  # prose | typed | mixed


class GovStatusVocabRow(BaseModel):
    """Referência: vocabulário controlado de status (substitui o CHECK ``status ∈ vocab``).

    Chave natural única: ``code``.
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    code: str = Field(
        max_length=32
    )  # aceito | proposto | substituido | retirado | arquivado ...
    applies_to_kind: str | None = Field(default=None, max_length=40)
    is_terminal: bool = False


class GovDirectiveRow(BaseModel):
    """Cabeçalho de uma diretriz — identidade natural imutável ``directive_uid`` (D18.3).

    Nunca soft-deletada (D18.8): mudança de conteúdo = nova versão; obsolescência =
    supersedência (``superseded_by_uid``). Escopo hierárquico (D18.4): baseline<archetype<
    platform<project — ``archetype`` foi ativado na Fase 2 (antes só existia reservado
    no rank, colapsado em ``platform`` por decisão do usuário na Fase 1).
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    directive_uid: str = Field(
        max_length=64
    )  # chave natural única (ex.: STD-SEC-001, ADR-0005, P-005)
    kind: str = Field(max_length=40)
    directive_scope: str = Field(
        default="platform", max_length=24
    )  # baseline | archetype | platform | project
    scope_rank: int = Field(
        default=1
    )  # materializado: baseline=0, archetype=2, platform=1, project=3
    project_ref: str | None = Field(
        default=None, max_length=64
    )  # referência FRACA ao project-product (D18.6)
    archetype_ref: str | None = Field(
        default=None, max_length=64
    )  # referência FRACA ao registro de arquétipo (Fase 2) — obrigatória sse scope='archetype'
    title: str = Field(max_length=300)
    superseded_by_uid: str | None = Field(default=None, max_length=64)
    owner_ref: str | None = Field(default=None, max_length=64)


class GovDirectiveVersionRow(BaseModel):
    """Revisão append-only de uma diretriz — a vigência mora aqui (D18.3/D18.6).

    Chave natural única: ``(directive_uid, version)``. Invariante "exatamente uma vigente
    por uid" é app-level via ``store.transaction()`` (MySQL não tem índice parcial).
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    directive_uid: str = Field(max_length=64)
    version: int = 1
    status: str = Field(default="proposto", max_length=32)
    is_current: bool = True
    body_context: str | None = None  # prosa (Contexto/Enunciado/Racional) — TEXT
    body_decision: str | None = (
        None  # prosa da Decisão (ADR) — único RFC2119 fora de Standard
    )
    change_reason: str | None = None
    author_ref: str | None = Field(default=None, max_length=64)
    content_sha256: str | None = Field(default=None, max_length=64)


class GovLcrDetailRow(BaseModel):
    """Metadados de gestão de mudança específicos de Library Change Request
    (ADR-018 Fase 1c) — SEM equivalente em ``gov_directive``/``gov_directive_version``
    (achado real na pesquisa do hub: LCR carrega campos de risco/versionamento que uma
    diretriz normativa comum não tem). Relação 1:1 com uma diretriz de
    ``kind='lib_change_request'``. Chave natural única: ``directive_uid``.
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    directive_uid: str = Field(max_length=64)
    biblioteca: str | None = Field(default=None, max_length=120)
    repositorio: str | None = Field(default=None, max_length=200)
    versao_atual: str | None = Field(default=None, max_length=32)
    versao_alvo: str | None = Field(default=None, max_length=32)
    tipo: str | None = Field(
        default=None, max_length=24
    )  # patch | minor | major | nao-aplicavel
    breaking: bool = False
    urgencia: str | None = Field(default=None, max_length=24)
    aprovador: str | None = Field(default=None, max_length=64)
    solicitante: str | None = Field(default=None, max_length=120)
    achado: str | None = Field(
        default=None, max_length=64
    )  # ref a control id de auditoria (ex.: CRY-02)
    data_solicitacao: str | None = Field(
        default=None, max_length=10
    )  # YYYY-MM-DD, imutável (distinto de ultima_atualizacao)


class GovLcrSubstitutionRow(BaseModel):
    """Aresta ``lcr → substituido_por`` — o front-matter do LCR carrega isso como uma
    LISTA YAML; aqui vira uma linha por alvo (rejeição de JSON-blob, D18.2), não uma
    coluna serializada. ``target_ref`` é referência FRACA (caminho/uid livre, sem FK —
    mesmo padrão de ``project_ref`` em ``gov_directive``). Chave natural única:
    ``(lcr_directive_uid, target_ref)``.
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    lcr_directive_uid: str = Field(max_length=64)
    target_ref: str = Field(max_length=200)


class GovDirectiveSectionRow(BaseModel):
    """Corpo tipado por seção (ADR-018 Fase 2) — uma linha por heading ``##`` do
    documento original, versionada junto com ``gov_directive_version``. Complementa
    (não substitui) ``body_context``/``body_decision`` da Fase 1: aqueles continuam
    existindo para o split heurístico contexto/decisão; as seções dão granularidade
    real por título (ex. "Consequências", "Enunciado", "Procedimento") — queryável,
    sem re-parsear markdown toda vez. Chave natural única:
    ``(directive_uid, version, order_index)`` — ``order_index`` (não ``section_key``)
    é o desambiguador porque headings podem se repetir (ex. duas seções
    "Consequências" — positivas/negativas — no mesmo documento).
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    directive_uid: str = Field(max_length=64)
    version: int = 1
    order_index: int = 0
    section_key: str = Field(max_length=80)  # heading normalizado (slug): "contexto"
    heading: str = Field(max_length=200)  # texto original do heading, sem normalizar
    content: str | None = None


class GovDirectiveRelationRow(BaseModel):
    """Aresta tipada entre diretrizes (ADR-018 Fase 2) — cobre `governado_por`
    (it/decisions/LCR → standard/ADR) E a matriz de rastreabilidade de
    ``documentation-model.md`` (ADR → Princípios/Standards/Reference Arch/Runbooks),
    modeladas uniformemente em vez de uma tabela por tipo de relação. ``to_ref`` é
    referência FRACA (sem FK — mesmo padrão de ``project_ref``): o alvo pode ser
    externo ao guardian (ex. a linha "MCP Gateway †" do hub, que cita decisões de
    OUTRO repositório por prosa, não por arquivo local). Chave natural única:
    ``(from_uid, to_ref, relation_type)``.
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    from_uid: str = Field(max_length=64)
    to_ref: str = Field(max_length=200)
    relation_type: str = Field(max_length=32)


class GovConformanceControlRow(BaseModel):
    """Estado de conformidade de um projeto frente a um control de governança
    (ADR-018 Fase 3) — inspirado no `service-conformance.yaml.template` do hub,
    mas persistido/consultável como registro, não um arquivo YAML solto por
    serviço. `project_ref` é referência FRACA ao project-product (D18.6, mesmo
    padrão de `gov_directive.project_ref`); `directive_uid` é opcional (nem todo
    control deriva de uma diretriz já registrada no guardian). Chave natural
    única: `(project_ref, control_id)` — reassessment é upsert, não histórico
    (o histórico de MUDANÇA de status fica fora de escopo desta fase; se
    precisar depois, vira um child table versionado como
    `gov_directive_version`).
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    project_ref: str = Field(max_length=64)
    control_id: str = Field(max_length=64)
    status: str = Field(
        max_length=24
    )  # blocked | fail | not_applicable | not_assessed | partial | pass
    reason: str | None = None  # obrigatório sse status != 'pass' (app-level)
    evidence: str | None = None  # obrigatório sse status == 'pass' (app-level)
    directive_uid: str | None = Field(default=None, max_length=64)
    assessed_by: str | None = Field(default=None, max_length=64)
    assessed_at: str | None = Field(default=None, max_length=10)  # YYYY-MM-DD


class GovWaiverRow(BaseModel):
    """Exceção temporária a um control de conformidade (ADR-018 Fase 3) —
    SEMPRE com validade e justificativa; nunca uma isenção permanente
    silenciosa (o oposto do "nada de JSON blob perdido" do domínio: aqui é
    "nada de exceção sem prazo"). `status` rastreia o ciclo de vida do próprio
    waiver (`active`/`expired`/`revoked`), não é o mesmo vocabulário de
    `GovConformanceControlRow.status`. Chave natural única:
    `(project_ref, control_id, expires_on)` — permite renovações (waivers
    sucessivos com validade diferente) sem duplicar o mesmo período.
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    project_ref: str = Field(max_length=64)
    control_id: str = Field(max_length=64)
    justification: str | None = None  # TEXT — prosa da justificativa
    approver_ref: str = Field(max_length=64)
    expires_on: str = Field(max_length=10)  # YYYY-MM-DD, obrigatório
    status: str = Field(default="active", max_length=16)  # active | expired | revoked


__all__ = [
    "GovKindCapabilityRow",
    "GovStatusVocabRow",
    "GovDirectiveRow",
    "GovDirectiveVersionRow",
    "GovLcrDetailRow",
    "GovLcrSubstitutionRow",
    "GovDirectiveSectionRow",
    "GovDirectiveRelationRow",
    "GovConformanceControlRow",
    "GovWaiverRow",
]
