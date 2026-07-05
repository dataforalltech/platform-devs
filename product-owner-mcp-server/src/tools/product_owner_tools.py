"""Product-Owner Product Management Tools.

Cada ferramenta deriva sua saída dos parâmetros de entrada (não retorna constantes).
Ferramentas com cálculo padrão (RICE, priorização, user stories) implementam a lógica
exata. As demais montam um artefato estruturado a partir dos inputs (scaffold), o que é
útil e determinístico; onde o julgamento de produto/LLM agregaria valor, o texto é
sinalizado como esboço para refino humano.
"""
from __future__ import annotations

from typing import Any, Optional

# ── Helpers ────────────────────────────────────────────────────────────────── #


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in (text or "").strip()]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "item"


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


# ── Cálculo exato: RICE ──────────────────────────────────────────────────────── #


def calculate_rice_score(
    reach: float,
    impact: float,
    confidence: float,
    effort: float,
    feature: Optional[str] = None,
) -> dict[str, Any]:
    """Calcula RICE score: (Reach × Impact × Confidence) / Effort.

    Args:
        reach: Número de pessoas/eventos alcançados por período (>= 0).
        impact: Impacto por usuário. Escala usual: 3=massivo, 2=alto, 1=médio,
            0.5=baixo, 0.25=mínimo (> 0).
        confidence: Confiança na estimativa, como fração 0–1 (ex.: 0.8 = 80%)
            ou percentual 1–100 (ex.: 80). Normalizado para 0–1.
        effort: Esforço em pessoa-mês/pessoa-sprint (> 0).
        feature: Nome opcional da feature avaliada, refletido no resultado.
    """
    errors: list[str] = []
    if reach < 0:
        errors.append("reach must be >= 0")
    if impact <= 0:
        errors.append("impact must be > 0")
    if confidence <= 0:
        errors.append("confidence must be > 0")
    if effort <= 0:
        errors.append("effort must be > 0 (division by zero)")

    # Normaliza confidence: aceita 0–1 (fração) ou 1–100 (percentual).
    confidence_fraction = confidence / 100.0 if confidence > 1 else confidence
    if confidence_fraction > 1:
        errors.append("confidence out of range (expected 0-1 fraction or 1-100 percent)")

    if errors:
        return {"error": "invalid_input", "details": errors, "feature": feature}

    score = (reach * impact * confidence_fraction) / effort
    return {
        "feature": feature,
        "score": round(score, 2),
        "formula": "(reach * impact * confidence) / effort",
        "breakdown": {
            "reach": reach,
            "impact": impact,
            "confidence": round(confidence_fraction, 4),
            "confidence_percent": round(confidence_fraction * 100, 2),
            "effort": effort,
            "numerator": round(reach * impact * confidence_fraction, 4),
        },
    }


# ── Priorização de backlog ─────────────────────────────────────────────────── #


def prioritize_backlog(
    items: list[dict[str, Any]],
    framework: str = "RICE",
) -> dict[str, Any]:
    """Prioriza itens do backlog e retorna ordenado (desc) com rank.

    Args:
        items: Lista de itens. Cada item pode trazer um `score` já calculado,
            ou os campos RICE (`reach`, `impact`, `confidence`, `effort`) para
            cálculo automático quando framework=RICE. Um `name`/`title`/`id`
            identifica o item.
        framework: Framework de priorização: RICE (padrão), ICE ou MoSCoW.
    """
    framework_norm = (framework or "RICE").upper()
    scored: list[dict[str, Any]] = []

    for raw in _as_list(items):
        if not isinstance(raw, dict):
            item = {"name": str(raw)}
        else:
            item = dict(raw)
        name = item.get("name") or item.get("title") or item.get("id") or "item"

        score = item.get("score")
        computed_from: Optional[str] = "provided_score" if score is not None else None

        if score is None and framework_norm == "RICE":
            try:
                reach = float(item.get("reach", 0))
                impact = float(item.get("impact", 0))
                confidence = float(item.get("confidence", 0))
                effort = float(item.get("effort", 0))
                if effort > 0:
                    conf = confidence / 100.0 if confidence > 1 else confidence
                    score = round((reach * impact * conf) / effort, 2)
                    computed_from = "rice_fields"
            except (TypeError, ValueError):
                score = None

        if score is None and framework_norm == "ICE":
            try:
                impact = float(item.get("impact", 0))
                confidence = float(item.get("confidence", 0))
                ease = float(item.get("ease", item.get("effort", 0)))
                conf = confidence / 100.0 if confidence > 1 else confidence
                score = round(impact * conf * ease, 2)
                computed_from = "ice_fields"
            except (TypeError, ValueError):
                score = None

        scored.append(
            {
                "name": name,
                "score": score if score is not None else 0,
                "scored": score is not None,
                "computed_from": computed_from or "default_zero",
                "item": item,
            }
        )

    if framework_norm == "MOSCOW":
        order = {"MUST": 0, "SHOULD": 1, "COULD": 2, "WONT": 3, "WON'T": 3}
        ranked = sorted(
            scored,
            key=lambda e: (order.get(str(e["item"].get("moscow", "COULD")).upper(), 2), -e["score"]),
        )
    else:
        ranked = sorted(scored, key=lambda e: e["score"], reverse=True)

    for i, entry in enumerate(ranked, start=1):
        entry["rank"] = i

    return {
        "prioritization_framework": framework_norm,
        "count": len(ranked),
        "prioritized_items": ranked,
    }


# ── User stories ───────────────────────────────────────────────────────────── #


def generate_user_stories(
    feature: str,
    role: Optional[str] = None,
    roles: Optional[list[str]] = None,
    goals: Optional[list[str]] = None,
    benefit: Optional[str] = None,
) -> dict[str, Any]:
    """Gera user stories bem-formadas + critérios de aceite a partir de uma feature/épico.

    Args:
        feature: Feature ou épico de origem (obrigatório).
        role: Papel/persona principal (ex.: 'usuário autenticado').
        roles: Papéis adicionais; cada goal é multiplicado pelos papéis.
        goals: Objetivos/ações desejadas. Se ausente, deriva um objetivo da feature.
        benefit: Benefício/valor esperado. Se ausente, deriva da feature.
    """
    all_roles = [r for r in ([role] if role else []) + _as_list(roles) if r]
    if not all_roles:
        all_roles = ["usuário"]

    goal_list = [g for g in _as_list(goals) if g]
    if not goal_list:
        goal_list = [f"usar {feature}"]

    default_benefit = benefit or f"eu obtenha o valor entregue por {feature}"

    stories: list[dict[str, Any]] = []
    for r in all_roles:
        for g in goal_list:
            story_text = f"As a {r}, I want {g}, so that {default_benefit}."
            acceptance = [
                f"Dado que sou {r}, quando {g}, então o sistema conclui a ação com sucesso.",
                f"Dado um cenário inválido ao {g}, então o sistema exibe erro claro e não corrompe dados.",
                "A ação é registrada/auditável e reflete no estado do produto.",
            ]
            stories.append(
                {
                    "id": f"US-{_slug(feature)}-{_slug(r)}-{_slug(g)}"[:80],
                    "role": r,
                    "goal": g,
                    "benefit": default_benefit,
                    "story": story_text,
                    "acceptance_criteria": acceptance,
                }
            )

    return {
        "feature": feature,
        "count": len(stories),
        "user_stories": stories,
    }


# ── Análise de problema ─────────────────────────────────────────────────────── #


def analyze_product_problem(
    problem_statement: str,
    affected_users: Optional[list[str]] = None,
    symptoms: Optional[list[str]] = None,
    business_impact: Optional[str] = None,
) -> dict[str, Any]:
    """Estrutura a análise de um problema de negócio a partir do enunciado e sintomas.

    Args:
        problem_statement: Enunciado do problema (obrigatório).
        affected_users: Segmentos/papéis afetados.
        symptoms: Sintomas observados; usados para derivar hipóteses de causa raiz.
        business_impact: Impacto de negócio declarado (receita, churn, custo...).
    """
    symptom_list = [s for s in _as_list(symptoms) if s]
    root_causes = [
        {
            "symptom": s,
            "hypothesis": f"Possível causa por trás de: {s}",
            "needs_validation": True,
        }
        for s in symptom_list
    ]
    users = [u for u in _as_list(affected_users) if u]
    return {
        "problem_statement": problem_statement,
        "affected_users": users,
        "root_cause_hypotheses": root_causes,
        "business_impact": business_impact or "não informado",
        "user_pain": (
            f"{', '.join(users)} enfrentam: {problem_statement}"
            if users
            else problem_statement
        ),
        "market_opportunity": f"Resolver '{problem_statement}' pode desbloquear valor para {len(users) or 'os'} segmento(s).",
        "note": "root_cause_hypotheses são esboços que requerem validação com dados/entrevistas.",
    }


# ── MVP scope ──────────────────────────────────────────────────────────────── #


def define_mvp_scope(
    product: str,
    features: list[Any],
    goal: Optional[str] = None,
) -> dict[str, Any]:
    """Divide features em must/should/could + out-of-scope para um MVP.

    Args:
        product: Nome do produto/iniciativa.
        features: Lista de features. Cada item pode ser string ou dict com
            `name` e opcional `priority` (must/should/could/wont) e `phase`.
        goal: Objetivo do MVP (foco do recorte).
    """
    must, should, could, out = [], [], [], []
    feats = _as_list(features)
    for idx, f in enumerate(feats):
        if isinstance(f, dict):
            name = f.get("name") or f.get("title") or f"feature-{idx+1}"
            priority = str(f.get("priority", "")).lower()
        else:
            name = str(f)
            priority = ""

        if priority in ("must", "must-have", "core"):
            must.append(name)
        elif priority in ("should", "should-have"):
            should.append(name)
        elif priority in ("could", "could-have", "nice-to-have"):
            could.append(name)
        elif priority in ("wont", "won't", "out", "out-of-scope"):
            out.append(name)
        else:
            # Sem prioridade explícita: heurística por ordem (primeiro terço = core).
            third = max(1, len(feats) // 3)
            if idx < third:
                must.append(name)
            elif idx < 2 * third:
                should.append(name)
            else:
                could.append(name)

    return {
        "product": product,
        "goal": goal or f"Validar a proposta de valor de {product} com o menor escopo viável.",
        "mvp_scope": {
            "core_features": must,
            "nice_to_haves": should,
            "could_haves": could,
            "out_of_scope": out,
        },
        "core_features": must,
        "nice_to_haves": should,
        "out_of_scope": out,
        "phases": [
            {"phase": "MVP", "includes": must},
            {"phase": "Fast-follow", "includes": should},
            {"phase": "Later", "includes": could},
        ],
        "note": "Itens sem `priority` explícita foram alocados por heurística de ordem; revise com o time.",
    }


# ── Métricas de produto ──────────────────────────────────────────────────────── #


def define_product_metrics(
    product: str,
    objectives: list[str],
    north_star: Optional[str] = None,
) -> dict[str, Any]:
    """Deriva KPIs e indicadores leading/lagging a partir dos objetivos.

    Args:
        product: Nome do produto.
        objectives: Objetivos de negócio/produto (cada um vira um KPI).
        north_star: Métrica North Star opcional.
    """
    objs = [o for o in _as_list(objectives) if o]
    kpis = [
        {
            "objective": o,
            "kpi": f"Taxa/valor associado a: {o}",
            "tracking_method": "instrumentação de eventos + dashboard analítico",
        }
        for o in objs
    ]
    return {
        "product": product,
        "north_star_metric": north_star or (objs[0] if objs else "não definida"),
        "kpis": kpis,
        "leading_indicators": [f"Sinal antecedente de '{o}'" for o in objs],
        "lagging_indicators": [f"Resultado consolidado de '{o}'" for o in objs],
        "tracking_method": "eventos de produto → warehouse → dashboards",
        "note": "Fórmulas exatas de cada KPI devem ser definidas com Analytics.",
    }


# ── Visão de produto ─────────────────────────────────────────────────────────── #


def define_product_vision(
    product: str,
    target_audience: str,
    problem: str,
    differentiator: Optional[str] = None,
    goals: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Monta visão/missão/objetivos/critérios de sucesso a partir dos inputs.

    Args:
        product: Nome do produto.
        target_audience: Público-alvo.
        problem: Problema central que o produto resolve.
        differentiator: Diferencial competitivo.
        goals: Objetivos estratégicos.
    """
    goal_list = [g for g in _as_list(goals) if g]
    diff = differentiator or "uma experiência superior"
    return {
        "product": product,
        "vision": f"Para {target_audience} que enfrentam {problem}, {product} oferece {diff}.",
        "mission": f"Ajudar {target_audience} a superar {problem} por meio de {product}.",
        "goals": goal_list or [f"Reduzir o impacto de {problem} para {target_audience}"],
        "success_criteria": [f"Evidência mensurável de que '{g}' foi atingido" for g in goal_list]
        or [f"Adoção e satisfação de {target_audience} acima da baseline"],
        "differentiator": diff,
    }


# ── Discovery questions ──────────────────────────────────────────────────────── #


def generate_discovery_questions(
    hypothesis: str,
    target_users: Optional[list[str]] = None,
    unknowns: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Gera perguntas de discovery/validação a partir da hipótese e das incógnitas.

    Args:
        hypothesis: Hipótese a validar (obrigatória).
        target_users: Usuários-alvo da pesquisa.
        unknowns: Pontos incertos que precisam ser esclarecidos.
    """
    users = [u for u in _as_list(target_users) if u]
    unknown_list = [u for u in _as_list(unknowns) if u]
    questions = [f"Como '{hypothesis}' se manifesta hoje no seu dia a dia?"]
    questions += [f"O que você entende sobre '{u}'?" for u in unknown_list]
    for u in users:
        questions.append(f"Sendo {u}, com que frequência você encontra essa situação?")
    return {
        "hypothesis": hypothesis,
        "target_users": users,
        "research_questions": questions,
        "validation_approach": (
            "Entrevistas qualitativas 1:1 seguidas de teste de solução; "
            "critério de validação: >= 60% confirma a dor sem indução."
        ),
        "note": "Perguntas são um roteiro-base; adapte para não induzir respostas.",
    }


# ── Feature spec ─────────────────────────────────────────────────────────────── #


def generate_feature_spec(
    feature: str,
    problem: Optional[str] = None,
    user_value: Optional[str] = None,
    requirements: Optional[list[str]] = None,
    acceptance_criteria: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Monta a especificação de uma feature a partir dos inputs.

    Args:
        feature: Nome da feature (obrigatório).
        problem: Problema que a feature resolve.
        user_value: Valor entregue ao usuário.
        requirements: Requisitos funcionais.
        acceptance_criteria: Critérios de aceite; se ausentes, derivados dos requisitos.
    """
    reqs = [r for r in _as_list(requirements) if r]
    acs = [a for a in _as_list(acceptance_criteria) if a]
    if not acs:
        acs = [f"Dado o requisito '{r}', então ele é atendido e verificável." for r in reqs]
    return {
        "feature": feature,
        "objective": problem or f"Entregar a capacidade '{feature}'.",
        "scope": {"requirements": reqs, "in_scope": reqs, "open_questions": []},
        "user_value": user_value or f"O usuário passa a poder {feature.lower()}.",
        "acceptance_criteria": acs,
        "feature_spec": {"feature": feature, "requirements": reqs, "acceptance_criteria": acs},
    }


# ── GTM brief ────────────────────────────────────────────────────────────────── #


def generate_go_to_market_brief(
    product: str,
    target_segment: str,
    value_proposition: str,
    channels: Optional[list[str]] = None,
    launch_date: Optional[str] = None,
) -> dict[str, Any]:
    """Monta um brief de Go-To-Market a partir dos inputs.

    Args:
        product: Produto/feature a lançar.
        target_segment: Segmento-alvo.
        value_proposition: Proposta de valor central.
        channels: Canais de lançamento.
        launch_date: Data/janela de lançamento.
    """
    channel_list = [c for c in _as_list(channels) if c] or ["site", "e-mail", "in-app"]
    return {
        "gtm_brief": {"product": product, "segment": target_segment},
        "target_segment": target_segment,
        "value_proposition": value_proposition,
        "key_messages": [
            f"{product} resolve a dor do segmento {target_segment}.",
            value_proposition,
            f"Disponível via {', '.join(channel_list)}.",
        ],
        "launch_timing": launch_date or "a definir",
        "channels": channel_list,
        "success_metrics": [
            "adoção nas primeiras 4 semanas",
            "taxa de ativação",
            "feedback qualitativo do segmento",
        ],
    }


# ── Handoffs ─────────────────────────────────────────────────────────────────── #


def generate_handoff_to_architecture(
    feature: str,
    requirements: Optional[list[str]] = None,
    integrations: Optional[list[str]] = None,
    scale_expectations: Optional[str] = None,
    constraints: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Monta o handoff para Arquitetura a partir dos inputs da feature.

    Args:
        feature: Feature de origem.
        requirements: Requisitos que geram necessidade técnica.
        integrations: Sistemas/serviços a integrar.
        scale_expectations: Expectativas de escala (volume, latência).
        constraints: Restrições (compliance, stack, prazo).
    """
    reqs = [r for r in _as_list(requirements) if r]
    return {
        "feature": feature,
        "architecture_handoff": {"feature": feature},
        "tech_requirements": [f"Derivado de '{r}'" for r in reqs] or [f"Suportar '{feature}'"],
        "integration_needs": [i for i in _as_list(integrations) if i],
        "scale_expectations": scale_expectations or "não informado",
        "constraints": [c for c in _as_list(constraints) if c],
        "open_questions": ["Modelo de dados?", "SLAs de latência/disponibilidade?"],
    }


def generate_handoff_to_design(
    feature: str,
    user_journeys: Optional[list[str]] = None,
    personas: Optional[list[str]] = None,
    key_screens: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Monta o handoff para Design a partir dos inputs da feature.

    Args:
        feature: Feature de origem.
        user_journeys: Jornadas relevantes.
        personas: Personas-alvo.
        key_screens: Telas/fluxos-chave a desenhar.
    """
    screens = [s for s in _as_list(key_screens) if s]
    return {
        "feature": feature,
        "design_handoff": {"feature": feature},
        "user_journeys": [j for j in _as_list(user_journeys) if j],
        "personas": [p for p in _as_list(personas) if p],
        "wireframes_brief": f"Wireframes para: {', '.join(screens)}" if screens else f"Wireframes de '{feature}'",
        "key_screens": screens,
        "design_tokens_needs": ["cores de estado", "tipografia", "espaçamento", "componentes de formulário"],
    }


def generate_handoff_to_engineering(
    feature: str,
    user_stories: Optional[list[Any]] = None,
    dependencies: Optional[list[str]] = None,
    acceptance_criteria: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Monta o handoff para Engenharia a partir dos inputs da feature.

    Args:
        feature: Feature de origem.
        user_stories: Histórias (strings ou dicts) que compõem a feature.
        dependencies: Dependências técnicas/de times.
        acceptance_criteria: Critérios de aceite globais da feature.
    """
    stories = _as_list(user_stories)
    normalized = [s if isinstance(s, dict) else {"story": str(s)} for s in stories]
    return {
        "feature": feature,
        "engineering_handoff": {"feature": feature},
        "user_stories": normalized,
        "acceptance_criteria": [a for a in _as_list(acceptance_criteria) if a],
        "dependencies": [d for d in _as_list(dependencies) if d],
        "definition_of_ready": [
            "história com critérios de aceite claros",
            "dependências mapeadas",
            "design disponível",
        ],
    }


# ── Release plan ─────────────────────────────────────────────────────────────── #


def generate_release_plan(
    product: str,
    features: list[Any],
    milestones: Optional[list[str]] = None,
    target_date: Optional[str] = None,
) -> dict[str, Any]:
    """Monta um plano de release faseado a partir das features e marcos.

    Args:
        product: Produto/iniciativa.
        features: Features a entregar (strings ou dicts com `name`/`phase`).
        milestones: Marcos temporais.
        target_date: Data-alvo do release final.
    """
    feats = _as_list(features)
    phases: dict[str, list[str]] = {}
    for idx, f in enumerate(feats):
        if isinstance(f, dict):
            name = f.get("name") or f.get("title") or f"feature-{idx+1}"
            phase = str(f.get("phase", "")) or None
        else:
            name = str(f)
            phase = None
        if not phase:
            phase = "Alpha" if idx < len(feats) / 3 else ("Beta" if idx < 2 * len(feats) / 3 else "GA")
        phases.setdefault(phase, []).append(name)

    phase_list = [{"phase": p, "features": items} for p, items in phases.items()]
    return {
        "product": product,
        "release_plan": {"product": product, "phases": phase_list},
        "phases": phase_list,
        "milestones": [m for m in _as_list(milestones) if m],
        "timeline": target_date or "a definir",
        "go_to_market": {"summary": f"Coordenar comunicação do release de {product}."},
        "success_metrics": ["adoção por fase", "estabilidade (erros/regressões)", "satisfação"],
        "risks": ["escopo por fase pode mudar", "dependências externas"],
        "note": "Alocação de fases sem `phase` explícita é heurística; ajuste com o time.",
    }


# ── Riscos de produto ────────────────────────────────────────────────────────── #


def map_product_risks(
    feature: str,
    risks: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Classifica riscos de produto nas 4 categorias de Cagan (valor, usabilidade, viabilidade, feasibility).

    Args:
        feature: Feature/iniciativa avaliada.
        risks: Lista de riscos. Cada item: `description` e opcional
            `category` (value|usability|viability|feasibility). Sem categoria,
            entra em `uncategorized`.
    """
    buckets = {
        "value_risks": [],
        "usability_risks": [],
        "viability_risks": [],
        "feasibility_risks": [],
        "uncategorized": [],
    }
    mapping = {
        "value": "value_risks",
        "usability": "usability_risks",
        "viability": "viability_risks",
        "feasibility": "feasibility_risks",
    }
    for r in _as_list(risks):
        if isinstance(r, dict):
            desc = r.get("description") or r.get("risk") or "risco"
            cat = str(r.get("category", "")).lower()
        else:
            desc = str(r)
            cat = ""
        buckets[mapping.get(cat, "uncategorized")].append(desc)

    return {
        "feature": feature,
        **buckets,
        "total_risks": sum(len(v) for v in buckets.values()),
        "note": "Riscos sem `category` ficam em 'uncategorized' para triagem.",
    }


# ── Jornada do usuário ───────────────────────────────────────────────────────── #


def map_user_journey(
    persona: str,
    steps: list[Any],
    scenario: Optional[str] = None,
) -> dict[str, Any]:
    """Monta a jornada do usuário em stages a partir dos passos fornecidos.

    Args:
        persona: Persona/ator da jornada.
        steps: Passos da jornada. Cada item pode ser string ou dict com
            `name`, `touchpoint`, `emotion`, `pain`.
        scenario: Cenário/contexto da jornada.
    """
    stages, touchpoints, emotions, pains = [], [], {}, []
    for idx, s in enumerate(_as_list(steps)):
        if isinstance(s, dict):
            name = s.get("name") or s.get("step") or f"stage-{idx+1}"
            touchpoint = s.get("touchpoint")
            emotion = s.get("emotion")
            pain = s.get("pain")
        else:
            name = str(s)
            touchpoint = emotion = pain = None
        stage = {"order": idx + 1, "stage": name, "touchpoint": touchpoint, "emotion": emotion, "pain": pain}
        stages.append(stage)
        if touchpoint:
            touchpoints.append(touchpoint)
        if emotion:
            emotions[name] = emotion
        if pain:
            pains.append(pain)

    return {
        "persona": persona,
        "scenario": scenario or "jornada padrão",
        "user_journey": {"persona": persona, "stages": stages},
        "stages": stages,
        "touchpoints": touchpoints,
        "emotions": emotions,
        "pain_points": pains,
    }


# ── Personas ─────────────────────────────────────────────────────────────────── #


def map_user_personas(
    personas: list[dict[str, Any]],
) -> dict[str, Any]:
    """Estrutura personas de usuário a partir dos inputs.

    Args:
        personas: Lista de personas. Cada item pode ser string (nome) ou dict
            com `name`, `demographics`, `goals`, `pains`, `behaviors`.
    """
    result = []
    for idx, p in enumerate(_as_list(personas)):
        if isinstance(p, dict):
            name = p.get("name") or f"persona-{idx+1}"
            result.append(
                {
                    "name": name,
                    "demographics": p.get("demographics", {}),
                    "goals": [g for g in _as_list(p.get("goals")) if g],
                    "pains": [pn for pn in _as_list(p.get("pains")) if pn],
                    "behaviors": [b for b in _as_list(p.get("behaviors")) if b],
                }
            )
        else:
            result.append(
                {"name": str(p), "demographics": {}, "goals": [], "pains": [], "behaviors": []}
            )
    return {"personas": result, "count": len(result)}
