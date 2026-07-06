"""Discovery cross-check: classes <-> prompt files, and front-matter injection."""

from __future__ import annotations

import pytest

from app.dev_agent.profiles.base import PROFILES_DIR, ProfileParseError, _split_front_matter
from app.dev_agent.profiles.loader import capabilities_for, discover_profiles
from app.dev_agent.profiles.registry import PROFILES

_EXPECTED = {
    "security",
    "qa_engineer",
    "architecture",
    "backend",
    "frontend",
    "devops",
    "product_owner",
    "product_manager",
}


def test_registry_has_all_eight_personas() -> None:
    assert set(PROFILES) == _EXPECTED


def test_every_class_id_matches_its_file_name() -> None:
    files = {p.stem for p in PROFILES_DIR.glob("*.md")}
    assert set(PROFILES) == files


def test_discovery_injects_front_matter_metadata() -> None:
    classes = discover_profiles()
    backend = classes["backend"]
    assert backend.display_name == "Backend Engineer"
    assert backend.model == "claude-sonnet-4-6"
    assert backend.max_iterations == 15  # from front-matter, not the default 12
    assert capabilities_for("backend", backend.front_matter) == {"read", "write"}

    security = classes["security"]
    assert capabilities_for("security", security.front_matter) == {"read"}


def test_split_front_matter_returns_meta_and_body() -> None:
    raw = "---\nid: x\ndisplay_name: X\n---\nBody line one.\n"
    meta, body = _split_front_matter(raw)
    assert meta == {"id": "x", "display_name": "X"}
    assert body.strip() == "Body line one."


def test_split_front_matter_without_block_raises() -> None:
    with pytest.raises(ProfileParseError):
        _split_front_matter("no front matter here")


def test_divergence_between_class_and_file_raises(monkeypatch, tmp_path) -> None:
    """A class id with no matching prompt file must fail discovery explicitly."""
    import app.dev_agent.profiles.loader as loader
    from app.dev_agent.profiles.base import ProfileBase

    class GhostProfile(ProfileBase):  # id has no knowledge/profiles/ghost.md
        id = "ghost"

    def fake_discover_classes() -> dict[str, type[ProfileBase]]:
        classes = {pid: PROFILES[pid] for pid in PROFILES}
        classes["ghost"] = GhostProfile
        return classes

    monkeypatch.setattr(loader, "_discover_classes", fake_discover_classes)
    with pytest.raises(ProfileParseError) as exc:
        loader.discover_profiles()
    assert "ghost" in str(exc.value)
