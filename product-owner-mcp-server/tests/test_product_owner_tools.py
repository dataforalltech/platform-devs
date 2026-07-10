"""Testes das ferramentas do product-owner-mcp-server.

Cobre: matemática exata do RICE, ordenação da priorização, formato das user
stories e reflexo dos inputs nos artefatos (nenhuma saída constante).
"""

from __future__ import annotations

from src.tools.product_owner_tools import (
    analyze_product_problem,
    calculate_rice_score,
    define_mvp_scope,
    define_product_metrics,
    define_product_vision,
    generate_discovery_questions,
    generate_feature_spec,
    generate_go_to_market_brief,
    generate_handoff_to_architecture,
    generate_handoff_to_design,
    generate_handoff_to_engineering,
    generate_release_plan,
    generate_user_stories,
    map_product_risks,
    map_user_journey,
    map_user_personas,
    prioritize_backlog,
)


class TestRiceScore:
    def test_exact_math(self):
        # (1000 * 2 * 0.8) / 4 = 400
        r = calculate_rice_score(reach=1000, impact=2, confidence=0.8, effort=4)
        assert r["score"] == 400.0
        assert r["breakdown"]["confidence"] == 0.8

    def test_percentage_confidence_normalized(self):
        # confidence=80 (percent) deve virar 0.8 → mesmo resultado
        r = calculate_rice_score(reach=1000, impact=2, confidence=80, effort=4)
        assert r["score"] == 400.0
        assert r["breakdown"]["confidence"] == 0.8

    def test_reflects_feature_name(self):
        r = calculate_rice_score(reach=10, impact=1, confidence=1, effort=1, feature="Checkout")
        assert r["feature"] == "Checkout"
        assert r["score"] == 10.0

    def test_zero_effort_rejected(self):
        r = calculate_rice_score(reach=10, impact=1, confidence=1, effort=0)
        assert r["error"] == "invalid_input"
        assert any("effort" in d for d in r["details"])

    def test_negative_reach_rejected(self):
        r = calculate_rice_score(reach=-5, impact=1, confidence=1, effort=1)
        assert r["error"] == "invalid_input"


class TestPrioritizeBacklog:
    def test_sorted_desc_with_rank(self):
        items = [
            {"name": "A", "score": 10},
            {"name": "B", "score": 50},
            {"name": "C", "score": 30},
        ]
        r = prioritize_backlog(items)
        ranked = r["prioritized_items"]
        assert [e["name"] for e in ranked] == ["B", "C", "A"]
        assert [e["rank"] for e in ranked] == [1, 2, 3]
        assert ranked[0]["score"] == 50

    def test_computes_rice_when_no_score(self):
        items = [
            {
                "name": "low",
                "reach": 100,
                "impact": 1,
                "confidence": 0.5,
                "effort": 10,
            },  # 5
            {
                "name": "high",
                "reach": 100,
                "impact": 2,
                "confidence": 1,
                "effort": 1,
            },  # 200
        ]
        r = prioritize_backlog(items, framework="RICE")
        ranked = r["prioritized_items"]
        assert ranked[0]["name"] == "high"
        assert ranked[0]["computed_from"] == "rice_fields"
        assert ranked[0]["score"] == 200.0

    def test_moscow_ordering(self):
        items = [
            {"name": "x", "moscow": "COULD"},
            {"name": "y", "moscow": "MUST"},
            {"name": "z", "moscow": "SHOULD"},
        ]
        r = prioritize_backlog(items, framework="MoSCoW")
        assert [e["name"] for e in r["prioritized_items"]] == ["y", "z", "x"]


class TestUserStories:
    def test_story_format(self):
        r = generate_user_stories(
            feature="Login social",
            role="visitante",
            goals=["entrar com Google"],
            benefit="eu acesse sem criar senha",
        )
        s = r["user_stories"][0]
        assert s["story"] == ("As a visitante, I want entrar com Google, so that eu acesse sem criar senha.")
        assert s["acceptance_criteria"]
        assert r["feature"] == "Login social"

    def test_cartesian_roles_x_goals(self):
        r = generate_user_stories(
            feature="F",
            roles=["admin", "user"],
            goals=["g1", "g2"],
        )
        assert r["count"] == 4

    def test_defaults_when_minimal(self):
        r = generate_user_stories(feature="Busca")
        assert r["count"] == 1
        assert r["user_stories"][0]["story"].startswith("As a usuário, I want usar Busca")


class TestMvpScope:
    def test_splits_by_explicit_priority(self):
        r = define_mvp_scope(
            product="P",
            features=[
                {"name": "core1", "priority": "must"},
                {"name": "nice1", "priority": "should"},
                {"name": "maybe1", "priority": "could"},
                {"name": "no1", "priority": "wont"},
            ],
        )
        assert r["mvp_scope"]["core_features"] == ["core1"]
        assert r["mvp_scope"]["nice_to_haves"] == ["nice1"]
        assert r["mvp_scope"]["could_haves"] == ["maybe1"]
        assert r["mvp_scope"]["out_of_scope"] == ["no1"]

    def test_reflects_product(self):
        r = define_mvp_scope(product="MeuApp", features=["a"])
        assert r["product"] == "MeuApp"


class TestInputReflection:
    """Garante que nenhuma tool retorna constante fixa — a saída depende do input."""

    def test_analyze_problem_reflects(self):
        r = analyze_product_problem(
            problem_statement="Checkout lento",
            affected_users=["comprador"],
            symptoms=["timeout no pagamento"],
        )
        assert r["problem_statement"] == "Checkout lento"
        assert r["root_cause_hypotheses"][0]["symptom"] == "timeout no pagamento"
        assert "comprador" in r["affected_users"]

    def test_metrics_reflect_objectives(self):
        r = define_product_metrics(product="P", objectives=["aumentar retenção"])
        assert r["kpis"][0]["objective"] == "aumentar retenção"
        assert r["north_star_metric"] == "aumentar retenção"

    def test_vision_reflects(self):
        r = define_product_vision(product="Orbit", target_audience="devs", problem="deploys frágeis")
        assert "Orbit" in r["vision"]
        assert "devs" in r["vision"]
        assert "deploys frágeis" in r["vision"]

    def test_discovery_questions_reflect(self):
        r = generate_discovery_questions(
            hypothesis="usuários abandonam no passo 3", unknowns=["motivo do abandono"]
        )
        assert any("passo 3" in q for q in r["research_questions"])
        assert any("motivo do abandono" in q for q in r["research_questions"])

    def test_feature_spec_derives_acceptance(self):
        r = generate_feature_spec(feature="Export CSV", requirements=["exportar filtrado"])
        assert r["feature"] == "Export CSV"
        assert any("exportar filtrado" in a for a in r["acceptance_criteria"])

    def test_gtm_reflects(self):
        r = generate_go_to_market_brief(product="P", target_segment="PME", value_proposition="mais rápido")
        assert r["target_segment"] == "PME"
        assert "mais rápido" in r["value_proposition"]

    def test_handoff_architecture_reflects(self):
        r = generate_handoff_to_architecture(
            feature="Sync", integrations=["Salesforce"], scale_expectations="10k rps"
        )
        assert r["integration_needs"] == ["Salesforce"]
        assert r["scale_expectations"] == "10k rps"

    def test_handoff_design_reflects(self):
        r = generate_handoff_to_design(feature="Onboarding", key_screens=["welcome", "profile"])
        assert r["key_screens"] == ["welcome", "profile"]

    def test_handoff_engineering_normalizes_stories(self):
        r = generate_handoff_to_engineering(
            feature="F",
            user_stories=["story a", {"story": "story b"}],
            dependencies=["auth-mcp"],
        )
        assert r["user_stories"][0] == {"story": "story a"}
        assert r["dependencies"] == ["auth-mcp"]

    def test_release_plan_phases(self):
        r = generate_release_plan(
            product="P",
            features=[{"name": "f1", "phase": "Beta"}, {"name": "f2", "phase": "Beta"}],
        )
        phases = {p["phase"]: p["features"] for p in r["phases"]}
        assert phases["Beta"] == ["f1", "f2"]

    def test_map_risks_categorizes(self):
        r = map_product_risks(
            feature="F",
            risks=[
                {"description": "ninguém quer", "category": "value"},
                {"description": "difícil de usar", "category": "usability"},
                {"description": "sem categoria"},
            ],
        )
        assert r["value_risks"] == ["ninguém quer"]
        assert r["usability_risks"] == ["difícil de usar"]
        assert r["uncategorized"] == ["sem categoria"]
        assert r["total_risks"] == 3

    def test_user_journey_builds_stages(self):
        r = map_user_journey(
            persona="Ana",
            steps=[
                {
                    "name": "descobre",
                    "touchpoint": "ads",
                    "emotion": "curiosa",
                    "pain": "ruído",
                },
                "cadastra",
            ],
        )
        assert r["persona"] == "Ana"
        assert r["stages"][0]["order"] == 1
        assert r["stages"][0]["stage"] == "descobre"
        assert r["touchpoints"] == ["ads"]
        assert r["emotions"]["descobre"] == "curiosa"
        assert r["pain_points"] == ["ruído"]
        assert r["stages"][1]["stage"] == "cadastra"

    def test_personas_structured(self):
        r = map_user_personas(
            personas=[
                {
                    "name": "Dev João",
                    "goals": ["shipar rápido"],
                    "pains": ["flaky tests"],
                }
            ]
        )
        assert r["count"] == 1
        assert r["personas"][0]["name"] == "Dev João"
        assert r["personas"][0]["goals"] == ["shipar rápido"]


# O contrato do servidor (schemas + campos de policy + PEP inner-token) agora é
# validado em test_mcp_server.py (sidecar mcp_http, Model C). O contrato FastMCP
# antigo (build_mcp/list_tools) foi aposentado.
