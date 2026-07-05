"""Auto-discovery of personas by crossing subclasses against prompt files.

Two sources are cross-checked and MUST agree (explicit failure otherwise):

1. subclasses of :class:`ProfileBase` declared in ``app.dev_agent.profiles.*``;
2. persona prompt files ``knowledge/profiles/<id>.md``.

Every class ``id`` must have a file; every file must have a class. On a match,
the front-matter of each file is injected into the class (``front_matter`` plus
``display_name`` / ``description`` / ``model`` / ``max_iterations``), so the
prompt file stays the single source of persona metadata.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

from app.dev_agent.profiles.base import (
    PROFILES_DIR,
    ProfileBase,
    ProfileParseError,
    _split_front_matter,
)

# Modules in the profiles package that are NOT personas.
_NON_PROFILE_MODULES = frozenset({"base", "loader", "registry", "__init__"})


def _discover_classes() -> dict[str, type[ProfileBase]]:
    """Return ``{id: ProfileBase subclass}`` found in ``app.dev_agent.profiles.*``."""
    import app.dev_agent.profiles as pkg

    classes: dict[str, type[ProfileBase]] = {}
    for _finder, modname, _ispkg in pkgutil.iter_modules(pkg.__path__):
        if modname in _NON_PROFILE_MODULES:
            continue
        module = importlib.import_module(f"{pkg.__name__}.{modname}")
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, ProfileBase)
                and obj is not ProfileBase
                and obj.id
                # Only classes actually defined in this module (avoid re-import
                # of a class imported from a sibling module).
                and obj.__module__ == module.__name__
            ):
                if obj.id in classes and classes[obj.id] is not obj:
                    raise ProfileParseError(
                        f"duplicate persona id {obj.id!r} "
                        f"({classes[obj.id].__name__} and {obj.__name__})"
                    )
                classes[obj.id] = obj
    return classes


def discover_profiles() -> dict[str, type[ProfileBase]]:
    """Discover personas, cross-checking classes against prompt files.

    Raises :class:`ProfileParseError` if the class set and the file set diverge,
    or if a file has invalid front-matter. Front-matter is injected into each
    class on success.
    """
    classes = _discover_classes()
    files = {path.stem for path in PROFILES_DIR.glob("*.md")}

    missing_file = set(classes) - files
    missing_class = files - set(classes)
    if missing_file or missing_class:
        raise ProfileParseError(
            "persona<->file divergence: "
            f"classes without file={sorted(missing_file)}, "
            f"files without class={sorted(missing_class)}"
        )

    for pid, cls in classes.items():
        raw = (PROFILES_DIR / f"{pid}.md").read_text(encoding="utf-8")
        meta, _body = _split_front_matter(raw)
        file_id = meta.get("id")
        if file_id is not None and file_id != pid:
            raise ProfileParseError(
                f"front-matter id {file_id!r} does not match file name {pid!r}"
            )
        cls.front_matter = meta
        cls.display_name = meta.get("display_name", cls.display_name or pid)
        cls.description = meta.get("description", cls.description)
        cls.model = meta.get("model", cls.model)
        if "max_iterations" in meta:
            cls.max_iterations = int(meta["max_iterations"])

    return classes


def capabilities_for(profile_id: str, front_matter: dict[str, Any]) -> set[str]:
    """Return the capability strings declared in a persona's front-matter.

    ``capabilities: [read]`` or ``capabilities: [read, write]``. Defaults to
    ``{"read"}`` (safe default) when absent.
    """
    caps = front_matter.get("capabilities")
    if not caps:
        return {"read"}
    return {str(c).strip().lower() for c in caps}


__all__ = ["discover_profiles", "capabilities_for"]
