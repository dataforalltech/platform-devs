"""Security persona — metadata/prompt in knowledge/profiles/security.md."""

from __future__ import annotations

from app.dev_agent.profiles.base import ProfileBase


class SecurityProfile(ProfileBase):
    id = "security"
