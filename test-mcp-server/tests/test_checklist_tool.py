"""Testes para checklist_tool e as operações de checklist do store."""

from src.tools.checklist_tool import (
    check_item,
    create_checklist,
    get_run_status,
    run_checklist,
)


def test_create_checklist_from_template(store):
    result = create_checklist(store, title="Pré-deploy", checklist_type="pre_deploy")
    assert result["items_count"] > 0
    assert result["type"] == "pre_deploy"
    assert "checklist_id" in result
    assert "run_checklist" in result["hint"]


def test_create_checklist_missing_title(store):
    result = create_checklist(store, title="", checklist_type="pre_deploy")
    assert result["error"] == "ValidationError"


def test_create_checklist_invalid_type(store):
    result = create_checklist(store, title="X", checklist_type="inexistente")
    assert result["error"] == "ValidationError"


def test_create_checklist_custom_items(store):
    items = [
        {"description": "Item A", "required": True, "category": "quality"},
        {"description": "Item B", "required": False},
    ]
    result = create_checklist(
        store, title="Custom", checklist_type="custom", items=items, use_template=False
    )
    assert result["items_count"] == 2


def test_create_checklist_custom_without_items(store):
    result = create_checklist(store, title="Custom", checklist_type="custom", use_template=False)
    assert result["error"] == "ValidationError"


def test_create_checklist_item_missing_description(store):
    result = create_checklist(
        store,
        title="Bad",
        checklist_type="custom",
        items=[{"category": "quality"}],
        use_template=False,
    )
    assert result["error"] == "ValidationError"


def test_create_checklist_invalid_plan(store):
    result = create_checklist(store, title="X", checklist_type="pre_deploy", plan_id="999999")
    assert result["error"] == "not_found"


def test_create_checklist_with_valid_plan(store, plan):
    result = create_checklist(
        store, title="Ligado ao plano", checklist_type="security", plan_id=plan["id"]
    )
    assert result["items_count"] > 0


def test_run_checklist_and_check_items_completes(store):
    created = create_checklist(store, title="Pré-deploy", checklist_type="pre_deploy")
    run = run_checklist(store, checklist_id=created["checklist_id"], executor="qa")
    assert run["run_id"].startswith("run_")
    assert len(run["items"]) == created["items_count"]

    # Marca todos os itens obrigatórios como passed -> run deve completar.
    for item in run["items"]:
        res = check_item(store, run_id=run["run_id"], item_id=item["id"], status="passed")
        assert res["item_id"] == item["id"]

    status = get_run_status(store, run_id=run["run_id"])
    assert status["status"] == "completed"
    assert status["summary"]["passed"] == created["items_count"]
    assert status["summary"]["pending"] == 0


def test_run_checklist_missing_id(store):
    result = run_checklist(store, checklist_id="")
    assert result["error"] == "ValidationError"


def test_check_item_validation_errors(store):
    created = create_checklist(store, title="X", checklist_type="pre_deploy")
    run = run_checklist(store, checklist_id=created["checklist_id"])
    item_id = run["items"][0]["id"]

    # status inválido
    bad = check_item(store, run_id=run["run_id"], item_id=item_id, status="talvez")
    assert bad["error"] == "ValidationError"

    # run_id/item_id ausentes
    missing = check_item(store, run_id="", item_id=item_id, status="passed")
    assert missing["error"] == "ValidationError"


def test_check_item_unknown_run(store):
    # run inexistente: o store faz upsert e detecta a ausência do run.
    result = check_item(store, run_id="run_naoexiste", item_id=1, status="passed")
    assert result["run_id"] == "run_naoexiste"
    assert result["status"] == "passed"


def test_get_run_status_missing_id(store):
    result = get_run_status(store, run_id="")
    assert result["error"] == "ValidationError"


def test_get_run_status_not_found(store):
    result = get_run_status(store, run_id="run_inexistente")
    assert result["error"] == "not_found"


def test_partial_check_keeps_run_in_progress(store):
    created = create_checklist(store, title="X", checklist_type="pre_deploy")
    run = run_checklist(store, checklist_id=created["checklist_id"])
    # marca apenas o primeiro item -> run continua in_progress
    first = run["items"][0]
    res = check_item(store, run_id=run["run_id"], item_id=first["id"], status="passed")
    assert res["run_status"] == "in_progress"
