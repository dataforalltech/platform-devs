# Portado de `devops-mcp-server/tests/test_generator_tool.py` pelo fan-out de testes.
#
# O código de tool do agregador é byte-a-byte o do servidor legado; só o caminho
# de import muda. Gerado por `scripts/port_domain_tests.py` — reexecutar é
# idempotente. Editar aqui diverge da origem: corrija no legado e reexecute, ou
# aposente o legado (ver ROADMAP, fechar o strangler).

"""Unidade dos geradores determinísticos de IaC (COMPUTE PURO — sem DB, sem LLM).

Estes testes NÃO tocam o MySQL: os geradores são funções puras ``spec -> dict``.
Cada gerador tem ao menos uma fixture-spec com asserts em marcadores-chave do output,
mais um teste global de DETERMINISMO (mesma spec chamada 2x → output idêntico)."""

from __future__ import annotations

import pytest

from src.domains.devops.tools.generator_tool import (
    generate_docker_compose,
    generate_dockerfile,
    generate_github_actions_pipeline,
    generate_helm_chart,
    generate_kubernetes_manifest,
    generate_terraform_module,
)

# ── Fixtures de spec (reaproveitadas nos testes de conteúdo e de determinismo) ─
DOCKERFILE_SPECS = [
    {"language": "python", "app_dir": "svc", "port": 8000, "extra_system_deps": ["gcc", "libpq-dev"]},
    {"language": "node", "package_manager": "pnpm", "version": "20", "port": 3000},
    {"language": "go", "port": 8080},
    {"language": "java", "version": "21"},
]
COMPOSE_SPEC = {
    "version": "3.9",
    "services": [
        {"name": "web", "image": "nginx:1.27", "ports": ["80:80"], "depends_on": ["db"]},
        {
            "name": "db",
            "image": "postgres:16",
            "environment": {"POSTGRES_PASSWORD": "x", "POSTGRES_DB": "app"},
        },
    ],
    "networks": ["backend"],
}
K8S_SPECS = {
    "Deployment": {
        "kind": "Deployment",
        "name": "api",
        "image": "registry/api",
        "replicas": 3,
        "port": 8080,
        "env": {"LOG_LEVEL": "info", "ENV": "prod"},
        "resources": {"requests": {"cpu": "100m"}, "limits": {"cpu": "500m"}},
    },
    "Service": {"kind": "Service", "name": "api", "port": 8080},
    "Ingress": {"kind": "Ingress", "name": "api", "port": 80},
    "ConfigMap": {"kind": "ConfigMap", "name": "api-cfg", "env": {"A": "1", "B": "2"}},
}
TERRAFORM_SPEC = {
    "provider": "aws",
    "resources": [
        {
            "type": "aws_instance",
            "name": "web",
            "args": {"ami": "ami-123", "instance_type": "t3.micro", "count": 2},
        },
    ],
    "variables": {"region": {"type": "string", "default": "us-east-1", "description": "AWS region"}},
    "outputs": {"instance_id": "aws_instance.web.id"},
}
HELM_SPEC = {
    "name": "myapp",
    "image": "registry/myapp",
    "port": 8080,
    "app_version": "2.1.0",
    "values": {"debug": True},
}
GHA_SPEC = {
    "name": "ci",
    "on": ["push", "pull_request"],
    "jobs": [
        {
            "name": "build",
            "runs_on": "ubuntu-latest",
            "steps": [
                {"name": "Checkout", "uses": "actions/checkout@v4"},
                {"name": "Build", "run": "make build", "with": {"cache": "true"}},
            ],
        }
    ],
}


# ── 1. Dockerfile ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("spec", DOCKERFILE_SPECS)
def test_generate_dockerfile_markers(spec):
    out = generate_dockerfile(spec)
    art = out["artifact"]
    assert out["kind"] == "dockerfile"
    assert out["filename"] == "Dockerfile"
    assert "FROM" in art
    # multi-stage: pelo menos duas etapas FROM + um COPY --from=builder
    assert art.count("FROM ") >= 2
    assert "COPY --from=builder" in art


def test_generate_dockerfile_port_and_sysdeps():
    out = generate_dockerfile(DOCKERFILE_SPECS[0])
    art = out["artifact"]
    assert "EXPOSE 8000" in art
    # deps de sistema ordenadas de forma estável
    assert "gcc libpq-dev" in art


def test_generate_dockerfile_rejects_unsupported_language():
    out = generate_dockerfile({"language": "rust"})
    assert out["error"] == "unsupported_language"


# ── 2. docker-compose ─────────────────────────────────────────────────────────
def test_generate_docker_compose_markers():
    out = generate_docker_compose(COMPOSE_SPEC)
    art = out["artifact"]
    assert out["kind"] == "compose"
    assert "services:" in art
    assert 'version: "3.9"' in art
    assert "web:" in art and "db:" in art
    assert "depends_on:" in art
    assert "networks:" in art


def test_generate_docker_compose_requires_services():
    assert generate_docker_compose({"services": []})["error"] == "missing_services"


# ── 3. Kubernetes ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kind", ["Deployment", "Service", "Ingress", "ConfigMap"])
def test_generate_kubernetes_manifest_markers(kind):
    out = generate_kubernetes_manifest(K8S_SPECS[kind])
    art = out["artifact"]
    assert out["kind"] == "k8s_manifest"
    assert f"kind: {kind}" in art
    assert "apiVersion:" in art


def test_generate_kubernetes_deployment_details():
    art = generate_kubernetes_manifest(K8S_SPECS["Deployment"])["artifact"]
    assert "kind: Deployment" in art
    assert "replicas: 3" in art
    assert "containerPort: 8080" in art
    assert "requests:" in art and "limits:" in art


def test_generate_kubernetes_rejects_unsupported_kind():
    assert generate_kubernetes_manifest({"kind": "Job", "name": "x"})["error"] == "unsupported_kind"


# ── 4. Terraform ──────────────────────────────────────────────────────────────
def test_generate_terraform_module_markers():
    out = generate_terraform_module(TERRAFORM_SPEC)
    art = out["artifact"]
    assert out["kind"] == "terraform"
    assert out["filename"] == "main.tf"
    assert 'resource "aws_instance" "web"' in art
    assert "terraform {" in art
    assert 'provider "aws"' in art
    assert 'variable "region"' in art
    assert 'output "instance_id"' in art
    # escalar aspado x número cru
    assert 'ami = "ami-123"' in art
    assert "count = 2" in art


def test_generate_terraform_rejects_unsupported_provider():
    out = generate_terraform_module({"provider": "digitalocean", "resources": [{"type": "t", "name": "n"}]})
    assert out["error"] == "unsupported_provider"


# ── 5. Helm ───────────────────────────────────────────────────────────────────
def test_generate_helm_chart_markers():
    out = generate_helm_chart(HELM_SPEC)
    art = out["artifact"]
    assert out["kind"] == "helm_chart"
    assert isinstance(art, dict)
    for key in ("Chart.yaml", "values.yaml", "templates/deployment.yaml", "templates/service.yaml"):
        assert key in art
    assert "name: myapp" in art["Chart.yaml"]
    assert 'appVersion: "2.1.0"' in art["Chart.yaml"]
    assert "repository: registry/myapp" in art["values.yaml"]
    assert "{{ .Values.replicaCount }}" in art["templates/deployment.yaml"]


def test_generate_helm_chart_requires_image():
    assert generate_helm_chart({"name": "x"})["error"] == "missing_image"


# ── 6. GitHub Actions ─────────────────────────────────────────────────────────
def test_generate_github_actions_pipeline_markers():
    out = generate_github_actions_pipeline(GHA_SPEC)
    art = out["artifact"]
    assert out["kind"] == "github_actions"
    assert "name: ci" in art
    assert "jobs:" in art
    assert "runs-on: ubuntu-latest" in art
    assert "uses: actions/checkout@v4" in art
    assert "run: make build" in art
    assert "with:" in art


def test_generate_github_actions_requires_jobs():
    assert generate_github_actions_pipeline({"name": "x", "jobs": []})["error"] == "missing_jobs"


# ── Determinismo global (mesma spec chamada 2x → output idêntico) ─────────────
@pytest.mark.parametrize(
    "fn,spec",
    [
        (generate_dockerfile, DOCKERFILE_SPECS[0]),
        (generate_dockerfile, DOCKERFILE_SPECS[1]),
        (generate_docker_compose, COMPOSE_SPEC),
        (generate_kubernetes_manifest, K8S_SPECS["Deployment"]),
        (generate_kubernetes_manifest, K8S_SPECS["ConfigMap"]),
        (generate_terraform_module, TERRAFORM_SPEC),
        (generate_helm_chart, HELM_SPEC),
        (generate_github_actions_pipeline, GHA_SPEC),
    ],
)
def test_generators_are_deterministic(fn, spec):
    assert fn(dict(spec)) == fn(dict(spec))


def test_env_key_ordering_is_stable_regardless_of_input_order():
    # dicts com mesma composição mas ordens de inserção diferentes → mesmo output.
    a = generate_kubernetes_manifest({"kind": "ConfigMap", "name": "c", "env": {"A": "1", "B": "2"}})
    b = generate_kubernetes_manifest({"kind": "ConfigMap", "name": "c", "env": {"B": "2", "A": "1"}})
    assert a == b
