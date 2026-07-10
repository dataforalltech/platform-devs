"""Testes das tools do devops-mcp-server.

Foco: a saída deve ser DERIVADA DOS INPUTS (nada de constantes vazando). Cada
teste passa inputs custom e afirma que eles reaparecem na saída, e que os
defaults só aparecem quando o input correspondente é omitido.
"""

from __future__ import annotations

from src.tools.devops_tools import (
    generate_dockerfile,
    generate_github_actions_pipeline,
    generate_helm_chart,
    generate_kubernetes_manifest,
    stub_tool,
)


# ── generate_kubernetes_manifest ────────────────────────────────────────────── #
def test_k8s_manifest_derives_from_inputs():
    result = generate_kubernetes_manifest(application="billing-api", replicas=5)
    assert result["title"] == "Kubernetes Manifest: billing-api"
    assert result["application"] == "billing-api"
    assert result["replicas"] == 5
    # replicas propaga para o spec do Deployment (derivado, não fixo).
    assert result["manifests"]["deployment"]["spec"]["replicas"] == 5
    assert result["manifests"]["deployment"]["kind"] == "Deployment"
    assert result["manifests"]["service"]["kind"] == "Service"
    assert result["manifests"]["configmap"]["kind"] == "ConfigMap"
    assert result["status"] == "generated"


def test_k8s_manifest_defaults_when_omitted():
    result = generate_kubernetes_manifest()
    assert result["application"] == "app"
    assert result["replicas"] == 3
    assert result["manifests"]["deployment"]["spec"]["replicas"] == 3


def test_k8s_manifest_zero_replicas_is_respected():
    # 0 é um input válido e deve reaparecer (não substituído por default).
    result = generate_kubernetes_manifest(application="scaler", replicas=0)
    assert result["replicas"] == 0
    assert result["manifests"]["deployment"]["spec"]["replicas"] == 0


# ── generate_dockerfile ─────────────────────────────────────────────────────── #
def test_dockerfile_derives_from_inputs():
    result = generate_dockerfile(application="worker", runtime="node:20-alpine")
    assert result["title"] == "Dockerfile: worker"
    assert result["application"] == "worker"
    assert result["runtime"] == "node:20-alpine"
    # Multi-stage build determinístico.
    assert result["stages"] == ["builder", "runtime"]
    assert "Multi-stage build" in result["optimizations"]
    assert result["status"] == "generated"


def test_dockerfile_defaults_when_omitted():
    result = generate_dockerfile()
    assert result["application"] == "app"
    assert result["runtime"] == "python:3.11"


# ── generate_github_actions_pipeline ────────────────────────────────────────── #
def test_pipeline_derives_from_inputs():
    result = generate_github_actions_pipeline(application="checkout")
    assert result["title"] == "GitHub Actions Pipeline: checkout"
    assert result["application"] == "checkout"
    assert result["stages"] == ["build", "test", "deploy"]
    assert result["triggers"] == ["push", "pull_request"]
    assert result["status"] == "generated"


def test_pipeline_default_application():
    result = generate_github_actions_pipeline()
    assert result["application"] == "app"
    assert result["title"] == "GitHub Actions Pipeline: app"


# ── generate_helm_chart ─────────────────────────────────────────────────────── #
def test_helm_chart_derives_from_inputs():
    result = generate_helm_chart(app_name="payments")
    assert result["title"] == "Helm Chart: payments"
    assert result["app_name"] == "payments"
    assert result["values"]["replicas"] == 3
    assert result["values"]["image"]["tag"] == "latest"
    assert "deployment.yaml" in result["templates"]
    assert result["status"] == "generated"


def test_helm_chart_default_app_name():
    result = generate_helm_chart()
    assert result["app_name"] == "app"
    assert result["title"] == "Helm Chart: app"


# ── stub_tool (status) ──────────────────────────────────────────────────────── #
def test_stub_tool_reports_ok():
    assert stub_tool() == {"status": "ok"}
