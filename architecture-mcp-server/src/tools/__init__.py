from __future__ import annotations

from .architecture_blueprint_tool import (
    build_architecture_proposal,
    delete_architecture_blueprint,
    get_architecture_blueprint,
    list_architecture_blueprints,
    save_architecture_blueprint,
    update_architecture_blueprint,
)
from .artifact_tool import delete_artifact, get_artifact, list_artifacts, save_artifact
from .c4_diagram_tool import (
    build_c4_model,
    delete_c4_diagram,
    get_c4_diagram,
    list_c4_diagrams,
    set_c4_diagram,
)
from .solution_blueprint_tool import (
    build_solution_blueprint,
    delete_solution_blueprint,
    get_solution_blueprint,
    list_solution_blueprints,
    save_solution_blueprint,
    update_solution_blueprint,
)

__all__ = [
    # Architecture Blueprints
    "save_architecture_blueprint",
    "list_architecture_blueprints",
    "get_architecture_blueprint",
    "update_architecture_blueprint",
    "delete_architecture_blueprint",
    "build_architecture_proposal",
    # C4 Diagrams
    "set_c4_diagram",
    "list_c4_diagrams",
    "get_c4_diagram",
    "delete_c4_diagram",
    "build_c4_model",
    # Solution Blueprints
    "save_solution_blueprint",
    "list_solution_blueprints",
    "get_solution_blueprint",
    "update_solution_blueprint",
    "delete_solution_blueprint",
    "build_solution_blueprint",
    # Artifacts
    "save_artifact",
    "list_artifacts",
    "get_artifact",
    "delete_artifact",
]
