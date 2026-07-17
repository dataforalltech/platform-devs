from __future__ import annotations

from .artifact_tool import delete_artifact, get_artifact, list_artifacts, save_artifact
from .component_tool import (
    delete_component,
    get_component,
    list_components,
    save_component,
    update_component,
)
from .form_tool import (
    delete_form,
    get_form,
    list_forms,
    save_form,
    update_form,
)
from .generator_tool import (
    create_design_tokens,
    generate_api_service,
    generate_component_variants,
    generate_custom_hook,
    generate_form_with_validation,
    generate_nextjs_page,
    generate_react_component,
    generate_storybook_story,
    generate_typescript_types,
    generate_wireframe,
)
from .page_tool import (
    delete_page,
    get_page,
    list_pages,
    set_page,
)
from .story_tool import (
    delete_story,
    get_story,
    list_stories,
    save_story,
    update_story,
)

__all__ = [
    # Components
    "save_component",
    "list_components",
    "get_component",
    "update_component",
    "delete_component",
    # Pages (upsert por route)
    "set_page",
    "list_pages",
    "get_page",
    "delete_page",
    # Forms
    "save_form",
    "list_forms",
    "get_form",
    "update_form",
    "delete_form",
    # Stories
    "save_story",
    "list_stories",
    "get_story",
    "update_story",
    "delete_story",
    # Artifacts
    "save_artifact",
    "list_artifacts",
    "get_artifact",
    "delete_artifact",
    # Geradores determinísticos (COMPUTE PURO — não persistem)
    "generate_react_component",
    "generate_nextjs_page",
    "generate_custom_hook",
    "generate_form_with_validation",
    "generate_typescript_types",
    "generate_storybook_story",
    "generate_api_service",
    "generate_component_variants",
    "generate_wireframe",
    "create_design_tokens",
]
