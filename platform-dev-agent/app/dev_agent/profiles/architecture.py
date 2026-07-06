"""Architecture persona — metadata/prompt in knowledge/profiles/architecture.md.

Also the fallback profile when the leader classifier is uncertain.
"""

from __future__ import annotations

from app.dev_agent.profiles.base import ProfileBase


class ArchitectureProfile(ProfileBase):
    id = "architecture"
