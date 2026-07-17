from __future__ import annotations

from .artifact_tool import delete_artifact, get_artifact, list_artifacts, save_artifact
from .feature_spec_tool import (
    delete_feature_spec,
    get_feature_spec,
    list_feature_specs,
    save_feature_spec,
    update_feature_spec,
)
from .generator_tool import (
    calculate_rice_score,
    generate_acceptance_criteria,
    generate_handoff_to_architecture,
    generate_handoff_to_design,
    generate_handoff_to_engineering,
    generate_release_plan,
)
from .gtm_brief_tool import (
    delete_gtm_brief,
    get_gtm_brief,
    list_gtm_briefs,
    save_gtm_brief,
    update_gtm_brief,
)
from .product_vision_tool import (
    delete_product_vision,
    get_product_vision,
    list_product_visions,
    set_product_vision,
)
from .release_plan_tool import (
    delete_release_plan,
    get_release_plan,
    list_release_plans,
    save_release_plan,
    update_release_plan,
)

__all__ = [
    # Feature Specs
    "save_feature_spec",
    "list_feature_specs",
    "get_feature_spec",
    "update_feature_spec",
    "delete_feature_spec",
    # GTM Briefs
    "save_gtm_brief",
    "list_gtm_briefs",
    "get_gtm_brief",
    "update_gtm_brief",
    "delete_gtm_brief",
    # Release Plans
    "save_release_plan",
    "list_release_plans",
    "get_release_plan",
    "update_release_plan",
    "delete_release_plan",
    # Product Visions
    "set_product_vision",
    "list_product_visions",
    "get_product_vision",
    "delete_product_vision",
    # Artifacts
    "save_artifact",
    "list_artifacts",
    "get_artifact",
    "delete_artifact",
    # Geradores determinísticos (COMPUTE PURO — sem DB/LLM)
    "generate_release_plan",
    "generate_acceptance_criteria",
    "calculate_rice_score",
    "generate_handoff_to_architecture",
    "generate_handoff_to_design",
    "generate_handoff_to_engineering",
]
