"""Geradores determinísticos de IaC (COMPUTE PURO — sem LLM, sem DB).

Diferente das tools stateful (``save_*``/``set_*``), estas tools NÃO tocam o
``DevopsStore``: são funções puras ``spec: dict -> dict`` que renderizam artefatos
de infra-as-code (Dockerfile, docker-compose, manifestos Kubernetes, módulos
Terraform, Helm charts e workflows do GitHub Actions) por template de string.

Contrato de saída (uniforme): cada gerador devolve
``{"artifact": <str|dict>, "filename": <str>, "kind": <str>}`` em caso de sucesso,
ou ``{"error": <slug>, ...}`` quando a spec é inválida.

**Determinismo (requisito duro):** sem ``random``, ``datetime.now``, ``uuid`` ou
qualquer hash de tempo. Chaves de dicionários de entrada (env/values/with/args)
são renderizadas em ordem alfabética estável, de modo que a MESMA spec produza
SEMPRE o MESMO byte-a-byte. Só depende da stdlib → importável/testável sem banco.
"""

from __future__ import annotations

import json
from typing import Any

# ── Constantes de suporte ─────────────────────────────────────────────────────
SUPPORTED_LANGUAGES = frozenset({"python", "node", "go", "java"})
SUPPORTED_TF_PROVIDERS = frozenset({"aws", "gcp", "azure"})
SUPPORTED_K8S_KINDS = frozenset({"Deployment", "Service", "Ingress", "ConfigMap"})
_DEFAULT_PM = {"python": "pip", "node": "npm", "go": "go", "java": "maven"}
_TF_PROVIDER_SOURCE = {
    "aws": "hashicorp/aws",
    "gcp": "hashicorp/google",
    "azure": "hashicorp/azurerm",
}


# ── Helpers de renderização (YAML/HCL por string, determinísticos) ────────────
def _yaml_scalar(value: Any) -> str:
    """Renderiza um escalar YAML. Bool/int/float saem crus; o resto é aspado."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return '"{}"'.format(str(value).replace('"', '\\"'))


def _yaml_block(data: dict[str, Any], indent: int) -> list[str]:
    """Serializa um dict plano como linhas ``chave: escalar`` (chaves ordenadas)."""
    pad = " " * indent
    return [f"{pad}{key}: {_yaml_scalar(data[key])}" for key in sorted(data)]


def _hcl_value(value: Any, indent: int = 0) -> str:
    """Renderiza um valor HCL: string aspada, número/bool cru, lista/map inline."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_hcl_value(v) for v in value) + "]"
    if isinstance(value, dict):
        pad = " " * (indent + 2)
        inner = "\n".join(f"{pad}{k} = {_hcl_value(value[k], indent + 2)}" for k in sorted(value))
        return "{\n" + inner + "\n" + " " * indent + "}"
    return json.dumps(str(value))


# ── 1. Dockerfile ─────────────────────────────────────────────────────────────
def generate_dockerfile(spec: dict[str, Any]) -> dict[str, Any]:
    language = str(spec.get("language", "")).strip().lower()
    if language not in SUPPORTED_LANGUAGES:
        return {"error": "unsupported_language", "language": language, "valid": sorted(SUPPORTED_LANGUAGES)}

    app_dir = str(spec.get("app_dir") or ".")
    port = spec.get("port")
    version = spec.get("version")
    pm = str(spec.get("package_manager") or _DEFAULT_PM[language])
    sys_deps = list(spec.get("extra_system_deps") or [])
    expose = f"EXPOSE {int(port)}\n" if port is not None else ""

    if sys_deps:
        deps = " ".join(sorted(str(d) for d in sys_deps))
        apt = (
            "RUN apt-get update && apt-get install -y --no-install-recommends "
            f"{deps} && rm -rf /var/lib/apt/lists/*\n"
        )
    else:
        apt = ""

    if language == "python":
        ver = version or "3.12"
        content = (
            f"# syntax=docker/dockerfile:1\n"
            f"FROM python:{ver}-slim AS builder\n"
            f"WORKDIR /app\n"
            f"{apt}"
            f"COPY {app_dir}/requirements.txt ./\n"
            f"RUN pip install --no-cache-dir --prefix=/install -r requirements.txt\n\n"
            f"FROM python:{ver}-slim\n"
            f"WORKDIR /app\n"
            f"COPY --from=builder /install /usr/local\n"
            f"COPY {app_dir} .\n"
            f"{expose}"
            f'CMD ["python", "main.py"]\n'
        )
    elif language == "node":
        ver = version or "20"
        content = (
            f"# syntax=docker/dockerfile:1\n"
            f"FROM node:{ver}-alpine AS builder\n"
            f"WORKDIR /app\n"
            f"COPY {app_dir}/package*.json ./\n"
            f"RUN {pm} install\n"
            f"COPY {app_dir} .\n"
            f"RUN {pm} run build\n\n"
            f"FROM node:{ver}-alpine\n"
            f"WORKDIR /app\n"
            f"COPY --from=builder /app .\n"
            f"{expose}"
            f'CMD ["{pm}", "start"]\n'
        )
    elif language == "go":
        ver = version or "1.22"
        content = (
            f"# syntax=docker/dockerfile:1\n"
            f"FROM golang:{ver}-alpine AS builder\n"
            f"WORKDIR /src\n"
            f"COPY {app_dir} .\n"
            f"RUN CGO_ENABLED=0 go build -o /app/server ./...\n\n"
            f"FROM alpine:3.20\n"
            f"WORKDIR /app\n"
            f"{apt}"
            f"COPY --from=builder /app/server /app/server\n"
            f"{expose}"
            f'ENTRYPOINT ["/app/server"]\n'
        )
    else:  # java
        ver = version or "21"
        content = (
            f"# syntax=docker/dockerfile:1\n"
            f"FROM eclipse-temurin:{ver}-jdk AS builder\n"
            f"WORKDIR /build\n"
            f"COPY {app_dir} .\n"
            f"RUN ./mvnw -q -DskipTests package\n\n"
            f"FROM eclipse-temurin:{ver}-jre\n"
            f"WORKDIR /app\n"
            f"COPY --from=builder /build/target/*.jar app.jar\n"
            f"{expose}"
            f'ENTRYPOINT ["java", "-jar", "app.jar"]\n'
        )

    return {"artifact": content, "filename": "Dockerfile", "kind": "dockerfile"}


# ── 2. docker-compose ─────────────────────────────────────────────────────────
def generate_docker_compose(spec: dict[str, Any]) -> dict[str, Any]:
    services = spec.get("services")
    if not isinstance(services, list) or not services:
        return {"error": "missing_services"}

    version = str(spec.get("version") or "3.9")
    lines: list[str] = [f'version: "{version}"', "services:"]

    for svc in services:
        name = str(svc.get("name", "")).strip()
        if not name:
            return {"error": "service_missing_name", "service": svc}
        lines.append(f"  {name}:")
        image = svc.get("image")
        build = svc.get("build")
        if image:
            lines.append(f"    image: {image}")
        if build:
            lines.append(f"    build: {build}")
        ports = svc.get("ports") or []
        if ports:
            lines.append("    ports:")
            lines.extend(f'      - "{p}"' for p in ports)
        environment = svc.get("environment") or {}
        if environment:
            lines.append("    environment:")
            lines.extend(_yaml_block(environment, 6))
        depends = svc.get("depends_on") or []
        if depends:
            lines.append("    depends_on:")
            lines.extend(f"      - {d}" for d in depends)

    networks = spec.get("networks") or []
    if networks:
        lines.append("networks:")
        for net in networks:
            lines.append(f"  {net}:")
            lines.append("    driver: bridge")

    return {"artifact": "\n".join(lines) + "\n", "filename": "docker-compose.yml", "kind": "compose"}


# ── 3. Manifesto Kubernetes ───────────────────────────────────────────────────
def generate_kubernetes_manifest(spec: dict[str, Any]) -> dict[str, Any]:
    kind = str(spec.get("kind", "")).strip()
    if kind not in SUPPORTED_K8S_KINDS:
        return {"error": "unsupported_kind", "kind": kind, "valid": sorted(SUPPORTED_K8S_KINDS)}
    name = str(spec.get("name", "")).strip()
    if not name:
        return {"error": "missing_name"}

    namespace = spec.get("namespace")
    image = spec.get("image")
    port = spec.get("port")
    replicas = int(spec.get("replicas", 1))
    env = spec.get("env") or {}
    resources = spec.get("resources") or {}

    meta = [f"  name: {name}"]
    if namespace:
        meta.append(f"  namespace: {namespace}")

    if kind == "Deployment":
        lines = ["apiVersion: apps/v1", "kind: Deployment", "metadata:", *meta]
        lines += [
            "spec:",
            f"  replicas: {replicas}",
            "  selector:",
            "    matchLabels:",
            f"      app: {name}",
            "  template:",
            "    metadata:",
            "      labels:",
            f"        app: {name}",
            "    spec:",
            "      containers:",
            f"        - name: {name}",
            f"          image: {image or name}:latest",
        ]
        if port is not None:
            lines += ["          ports:", f"            - containerPort: {int(port)}"]
        if env:
            lines.append("          env:")
            for key in sorted(env):
                lines += [f"            - name: {key}", f"              value: {_yaml_scalar(env[key])}"]
        if resources:
            lines.append("          resources:")
            for scope in ("requests", "limits"):
                block = resources.get(scope)
                if isinstance(block, dict) and block:
                    lines.append(f"            {scope}:")
                    lines += _yaml_block(block, 14)
    elif kind == "Service":
        p = int(port) if port is not None else 80
        lines = [
            "apiVersion: v1",
            "kind: Service",
            "metadata:",
            *meta,
            "spec:",
            "  selector:",
            f"    app: {name}",
            "  ports:",
            f"    - port: {p}",
            f"      targetPort: {p}",
            "  type: ClusterIP",
        ]
    elif kind == "Ingress":
        p = int(port) if port is not None else 80
        lines = [
            "apiVersion: networking.k8s.io/v1",
            "kind: Ingress",
            "metadata:",
            *meta,
            "spec:",
            "  rules:",
            "    - http:",
            "        paths:",
            "          - path: /",
            "            pathType: Prefix",
            "            backend:",
            "              service:",
            f"                name: {name}",
            "                port:",
            f"                  number: {p}",
        ]
    else:  # ConfigMap
        lines = ["apiVersion: v1", "kind: ConfigMap", "metadata:", *meta]
        if env:
            lines.append("data:")
            lines += _yaml_block(env, 2)
        else:
            lines.append("data: {}")

    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": f"{name}-{kind.lower()}.yaml",
        "kind": "k8s_manifest",
    }


# ── 4. Módulo Terraform ───────────────────────────────────────────────────────
def generate_terraform_module(spec: dict[str, Any]) -> dict[str, Any]:
    provider = str(spec.get("provider", "")).strip().lower()
    if provider not in SUPPORTED_TF_PROVIDERS:
        return {
            "error": "unsupported_provider",
            "provider": provider,
            "valid": sorted(SUPPORTED_TF_PROVIDERS),
        }
    resources = spec.get("resources")
    if not isinstance(resources, list) or not resources:
        return {"error": "missing_resources"}

    source = _TF_PROVIDER_SOURCE[provider]
    parts: list[str] = [
        "terraform {",
        "  required_providers {",
        f"    {provider} = {{",
        f'      source  = "{source}"',
        "    }",
        "  }",
        "}",
        "",
        f'provider "{provider}" {{}}',
        "",
    ]

    for res in resources:
        rtype = str(res.get("type", "")).strip()
        rname = str(res.get("name", "")).strip()
        if not rtype or not rname:
            return {"error": "resource_missing_type_or_name", "resource": res}
        parts.append(f'resource "{rtype}" "{rname}" {{')
        args = res.get("args") or {}
        for key in sorted(args):
            parts.append(f"  {key} = {_hcl_value(args[key], 2)}")
        parts.append("}")
        parts.append("")

    variables = spec.get("variables") or {}
    if variables:
        parts.append("# variables.tf")
        for key in sorted(variables):
            spec_v = variables[key]
            if isinstance(spec_v, dict):
                vtype = spec_v.get("type", "string")
                default = spec_v.get("default")
                desc = spec_v.get("description")
            else:
                vtype, default, desc = "string", spec_v, None
            parts.append(f'variable "{key}" {{')
            parts.append(f"  type = {vtype}")
            if desc is not None:
                parts.append(f"  description = {json.dumps(str(desc))}")
            if default is not None:
                parts.append(f"  default = {_hcl_value(default, 2)}")
            parts.append("}")
            parts.append("")

    outputs = spec.get("outputs") or {}
    if outputs:
        parts.append("# outputs.tf")
        for key in sorted(outputs):
            parts.append(f'output "{key}" {{')
            parts.append(f"  value = {outputs[key]}")
            parts.append("}")
            parts.append("")

    return {"artifact": "\n".join(parts).rstrip() + "\n", "filename": "main.tf", "kind": "terraform"}


# ── 5. Helm chart (multi-arquivo) ─────────────────────────────────────────────
def generate_helm_chart(spec: dict[str, Any]) -> dict[str, Any]:
    name = str(spec.get("name", "")).strip()
    image = str(spec.get("image", "")).strip()
    if not name:
        return {"error": "missing_name"}
    if not image:
        return {"error": "missing_image"}

    port = int(spec.get("port", 80))
    app_version = str(spec.get("app_version") or "1.0.0")
    values = spec.get("values") or {}

    chart_yaml = (
        "apiVersion: v2\n"
        f"name: {name}\n"
        f"description: Helm chart for {name}\n"
        "type: application\n"
        "version: 0.1.0\n"
        f'appVersion: "{app_version}"\n'
    )

    values_lines = [
        "replicaCount: 1",
        "image:",
        f"  repository: {image}",
        f'  tag: "{app_version}"',
        "  pullPolicy: IfNotPresent",
        "service:",
        "  type: ClusterIP",
        f"  port: {port}",
    ]
    if values:
        values_lines.append("extra:")
        values_lines.extend(_yaml_block(values, 2))
    values_yaml = "\n".join(values_lines) + "\n"

    deployment_yaml = (
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        f"  name: {name}\n"
        "spec:\n"
        "  replicas: {{ .Values.replicaCount }}\n"
        "  selector:\n"
        "    matchLabels:\n"
        f"      app: {name}\n"
        "  template:\n"
        "    metadata:\n"
        "      labels:\n"
        f"        app: {name}\n"
        "    spec:\n"
        "      containers:\n"
        f"        - name: {name}\n"
        '          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"\n'
        "          imagePullPolicy: {{ .Values.image.pullPolicy }}\n"
        "          ports:\n"
        "            - containerPort: {{ .Values.service.port }}\n"
    )

    service_yaml = (
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        f"  name: {name}\n"
        "spec:\n"
        "  type: {{ .Values.service.type }}\n"
        "  selector:\n"
        f"    app: {name}\n"
        "  ports:\n"
        "    - port: {{ .Values.service.port }}\n"
        "      targetPort: {{ .Values.service.port }}\n"
    )

    artifact = {
        "Chart.yaml": chart_yaml,
        "values.yaml": values_yaml,
        "templates/deployment.yaml": deployment_yaml,
        "templates/service.yaml": service_yaml,
    }
    return {"artifact": artifact, "filename": name, "kind": "helm_chart"}


# ── 6. Workflow do GitHub Actions ─────────────────────────────────────────────
def generate_github_actions_pipeline(spec: dict[str, Any]) -> dict[str, Any]:
    name = str(spec.get("name", "")).strip()
    if not name:
        return {"error": "missing_name"}
    jobs = spec.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        return {"error": "missing_jobs"}

    triggers = spec.get("on") or ["push", "pull_request"]
    lines: list[str] = [f"name: {name}", "on:"]
    lines.extend(f"  - {t}" for t in triggers)
    lines.append("jobs:")

    for idx, job in enumerate(jobs):
        job_name = str(job.get("name") or f"job-{idx + 1}").strip()
        runs_on = str(job.get("runs_on") or "ubuntu-latest")
        lines.append(f"  {job_name}:")
        lines.append(f"    runs-on: {runs_on}")
        steps = job.get("steps") or []
        if not steps:
            return {"error": "job_missing_steps", "job": job_name}
        lines.append("    steps:")
        for step in steps:
            step_name = step.get("name")
            uses = step.get("uses")
            run = step.get("run")
            first = True

            def _emit(text: str) -> None:
                nonlocal first
                prefix = "      - " if first else "        "
                lines.append(f"{prefix}{text}")
                first = False

            if step_name:
                _emit(f"name: {step_name}")
            if uses:
                _emit(f"uses: {uses}")
            if run:
                _emit(f"run: {run}")
            if not (step_name or uses or run):
                _emit("run: 'true'")
            with_args = step.get("with") or {}
            if with_args:
                lines.append("        with:")
                lines.extend(_yaml_block(with_args, 10))

    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": f".github/workflows/{name}.yml",
        "kind": "github_actions",
    }
