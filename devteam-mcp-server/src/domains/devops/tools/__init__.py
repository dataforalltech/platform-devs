from __future__ import annotations

from .artifact_tool import delete_artifact, get_artifact, list_artifacts, save_artifact
from .deployment_tool import (
    delete_deployment,
    get_deployment,
    list_deployments,
    recommend_strategy,
    save_deployment,
    update_deployment_status,
)
from .environment_tool import (
    delete_environment,
    get_environment,
    list_environments,
    set_environment,
)
from .generator_tool import (
    generate_docker_compose,
    generate_dockerfile,
    generate_github_actions_pipeline,
    generate_helm_chart,
    generate_kubernetes_manifest,
    generate_terraform_module,
)
from .pipeline_tool import (
    delete_pipeline,
    get_pipeline,
    list_pipelines,
    save_pipeline,
    update_pipeline,
)
from .service_config_tool import (
    delete_service_config,
    get_service_config,
    list_service_configs,
    set_service_config,
)

__all__ = [
    # Artifacts
    "save_artifact",
    "list_artifacts",
    "get_artifact",
    "delete_artifact",
    # Pipelines
    "save_pipeline",
    "list_pipelines",
    "get_pipeline",
    "update_pipeline",
    "delete_pipeline",
    # Deployments
    "save_deployment",
    "list_deployments",
    "get_deployment",
    "update_deployment_status",
    "delete_deployment",
    "recommend_strategy",
    # Environments
    "set_environment",
    "list_environments",
    "get_environment",
    "delete_environment",
    # Service Configs
    "set_service_config",
    "list_service_configs",
    "get_service_config",
    "delete_service_config",
    # Generators (COMPUTE PURO — sem store)
    "generate_dockerfile",
    "generate_docker_compose",
    "generate_kubernetes_manifest",
    "generate_terraform_module",
    "generate_helm_chart",
    "generate_github_actions_pipeline",
]
