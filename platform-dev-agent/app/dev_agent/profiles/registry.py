"""Persona registry — populated by auto-discovery (not a hardcoded dict).

``PROFILES`` maps a persona id to its :class:`ProfileBase` subclass. It is built
once at import time by :func:`discover_profiles`, which cross-checks the classes
against ``knowledge/profiles/*.md`` and injects each file's front-matter.
"""

from __future__ import annotations

from app.dev_agent.profiles.base import ProfileBase
from app.dev_agent.profiles.loader import discover_profiles

PROFILES: dict[str, type[ProfileBase]] = discover_profiles()

__all__ = ["PROFILES"]
