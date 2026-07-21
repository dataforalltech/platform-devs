"""Strict models for MCP provider manifests and governed tool contracts."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ManifestStatus = Literal["active", "experimental", "planned", "deprecated", "disabled"]
ExecutableStatus = {"active", "experimental"}
RiskLevel = Literal["low", "medium", "high", "critical"]
ApprovalLevel = Literal["none", "N1", "N2"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Classification(StrictModel):
    type: Literal["system", "persona", "domain", "control-plane"]
    capability_domain: str = Field(min_length=1)


class Ownership(StrictModel):
    team: str = Field(min_length=1)
    source_repo: str = Field(min_length=1)
    source_path: str | None = None
    legacy_source_paths: list[str] = Field(default_factory=list)


class CompanionRuntime(StrictModel):
    service_name: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    command: list[str] = Field(min_length=1)
    environment: dict[str, str] = Field(default_factory=dict)
    ports: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class Runtime(StrictModel):
    mode: Literal["local", "external", "none"]
    language: str | None = None
    version: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    service_name: str | None = None
    base_url_env: str | None = None
    build_context: str | None = None
    dockerfile: str | None = None
    build_ssh: bool = False
    build_secrets: list[str] = Field(
        default_factory=list,
        description="BuildKit secret ids supplied through Compose build.secrets.",
    )
    environment: dict[str, str] = Field(default_factory=dict)
    volumes: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    exposes_tools: bool = True

    @model_validator(mode="after")
    def validate_build_secrets(self) -> Runtime:
        secret_pattern = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
        if any(not secret_pattern.fullmatch(secret) for secret in self.build_secrets):
            raise ValueError("build_secrets contains an invalid BuildKit secret id")
        if len(set(self.build_secrets)) != len(self.build_secrets):
            raise ValueError("build_secrets must not contain duplicates")
        if self.build_ssh and self.build_secrets:
            raise ValueError("build_ssh and build_secrets are mutually exclusive")
        return self


class CanonicalHTTP(StrictModel):
    health_live: str = "/v1/health/live"
    health_ready: str = "/v1/health/ready"
    tools_list: str = "/mcp/tools/list"
    tools_call: str = "/mcp/tools/call"


class Transport(StrictModel):
    stdio: bool = False
    http: bool = True
    canonical_http: CanonicalHTTP = Field(default_factory=CanonicalHTTP)


class Network(StrictModel):
    internal_port: int | None = Field(default=None, ge=1, le=65535)
    host_port: int | None = Field(default=None, ge=1, le=65535)


class Security(StrictModel):
    auth_required: bool
    tenant_required: bool
    policy_mode: Literal["fail_closed", "not_applicable"]
    audit_required: bool
    secret_redaction_required: bool
    context_signing_required: bool = True


class CI(StrictModel):
    enabled: bool = True
    coverage_threshold: int = Field(default=80, ge=0, le=100)
    lint: bool = True
    type_check: bool = True
    docker_build: bool = True
    smoke_test: bool = True


class Surface(StrictModel):
    enabled: bool = True


class MCPManifest(StrictModel):
    schema_version: Literal[1] = 1
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    status: ManifestStatus
    classification: Classification
    ownership: Ownership
    runtime: Runtime
    transport: Transport
    network: Network = Field(default_factory=Network)
    security: Security
    ci: CI = Field(default_factory=CI)
    gateway: Surface = Field(default_factory=Surface)
    registry: Surface = Field(default_factory=Surface)
    dependencies: list[str] = Field(default_factory=list)
    companions: list[CompanionRuntime] = Field(default_factory=list)
    tool_catalog: str | None = None
    tool_contracts: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "MCPManifest":
        executable = self.status in ExecutableStatus
        if self.status == "planned":
            enabled = [
                self.gateway.enabled,
                self.registry.enabled,
                self.ci.enabled,
                self.runtime.mode != "none",
                self.runtime.exposes_tools,
            ]
            if any(enabled):
                raise ValueError(
                    "planned manifests cannot be enabled on runtime surfaces"
                )
            if self.tool_catalog or self.tool_contracts:
                raise ValueError(
                    "planned manifests cannot publish tools or tool contracts"
                )
        if not executable and (self.gateway.enabled or self.registry.enabled):
            raise ValueError(
                "only active/experimental manifests may enter gateway or registry"
            )
        if executable and self.runtime.mode == "local":
            if not (
                self.runtime.command and self.runtime.cwd and self.runtime.service_name
            ):
                raise ValueError(
                    "local executable runtime requires command, cwd and service_name"
                )
        if (
            executable
            and self.runtime.mode == "external"
            and not self.runtime.base_url_env
        ):
            raise ValueError("external executable runtime requires base_url_env")
        if executable and self.runtime.exposes_tools:
            if not all(
                (
                    self.security.auth_required,
                    self.security.tenant_required,
                    self.security.audit_required,
                    self.security.secret_redaction_required,
                    self.security.context_signing_required,
                )
            ):
                raise ValueError(
                    "executable tool providers require auth, tenant, audit, redaction and signing"
                )
            if self.security.policy_mode != "fail_closed":
                raise ValueError(
                    "executable tool providers must use fail_closed policy"
                )
        return self


class ToolRisk(StrictModel):
    level: RiskLevel
    effects: list[str] = Field(default_factory=list)
    blast_radius: Literal[
        "none", "workspace", "service", "environment", "tenant", "global"
    ]
    approval_required: ApprovalLevel = "none"


class ToolContract(StrictModel):
    schema_version: Literal[1] = 1
    provider_id: str
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    description: str
    status: Literal["active", "disabled"] = "active"
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_scope: str
    mutating: bool
    risk: ToolRisk
    secret_reference_only: bool = True

    @model_validator(mode="after")
    def validate_governance(self) -> "ToolContract":
        if self.mutating and self.risk.level == "low":
            raise ValueError("mutating tools cannot be low risk")
        if (
            self.risk.level in {"high", "critical"}
            and self.risk.approval_required == "none"
        ):
            raise ValueError("high/critical tools require approval")
        if self.secret_reference_only:
            forbidden = re.compile(
                r"(^|_)("
                r"passwords?|passphrases?|secrets?|credentials?|tokens?|"
                r"private_keys?|secret_keys?|api_keys?|ssh_keys?|access_keys?|access_tokens?|"
                r"value"
                r")($|_)"
            )
            allowed_suffixes = ("_ref", "_lease_id", "_id")
            for schema in (self.input_schema, self.output_schema):
                for key in _schema_property_names(schema):
                    if key.lower() == "secret_reference_only":
                        continue
                    if forbidden.search(key.lower()) and not key.lower().endswith(
                        allowed_suffixes
                    ):
                        raise ValueError(
                            f"secret-bearing field is forbidden; use an opaque reference: {key}"
                        )
        return self


def _schema_property_names(schema: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for key, value in properties.items():
            names.add(str(key))
            if isinstance(value, dict):
                names.update(_schema_property_names(value))
    items = schema.get("items")
    if isinstance(items, dict):
        names.update(_schema_property_names(items))
    return names
