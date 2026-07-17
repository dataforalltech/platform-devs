"""Testes das operações ACR que permanecem após a retirada de GitHub Actions."""

from __future__ import annotations

import subprocess

from src.tools import acr_tool
from src.tools.acr_tool import acr_build, list_acr_images


def test_acr_build_rejects_missing_dockerfile(settings, tmp_path):
    acr_settings = settings.model_copy(
        update={"acr_username": "user", "acr_password": "password"}
    )
    result = acr_build(
        acr_settings,
        repo_path=str(tmp_path),
        image_name="platform-example",
        push=False,
    )
    assert result["error"] == "ValidationError"


def test_acr_build_rejects_path_outside_repository(settings, tmp_path):
    result = acr_build(
        settings,
        repo_path=str(tmp_path / "missing"),
        image_name="platform-example",
        dockerfile="../Dockerfile",
        push=False,
    )
    assert result["error"] == "ValidationError"


def test_acr_build_requires_credentials_when_push_is_enabled(settings, tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    no_acr_settings = settings.model_copy(
        update={"acr_username": None, "acr_password": None}
    )
    result = acr_build(
        no_acr_settings,
        repo_path=str(tmp_path),
        image_name="platform-example",
        push=True,
    )
    assert result["error"] == "ConfigError"


def test_acr_build_rejects_latest(settings, tmp_path):
    acr_settings = settings.model_copy(
        update={"acr_username": "user", "acr_password": "password"}
    )
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    result = acr_build(
        acr_settings,
        repo_path=str(tmp_path),
        image_name="platform-example",
        tag="latest",
        push=False,
    )
    assert result["error"] == "ValidationError"
    assert "latest" in result["details"]


def test_list_acr_images_requires_credentials(client, settings):
    no_acr_settings = settings.model_copy(
        update={"acr_username": None, "acr_password": None}
    )
    result = list_acr_images(client, no_acr_settings, "platform-example")
    assert result["error"] == "ConfigError"


def _completed(command, *, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def test_acr_build_without_push_returns_evidence_gaps(settings, tmp_path, monkeypatch):
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        if command[:2] == ["git", "rev-parse"]:
            return _completed(command, stdout="abc123def456\n")
        if command[:2] == ["docker", "build"]:
            return _completed(command)
        if command[:3] == ["docker", "image", "inspect"]:
            return _completed(command, stdout="[]\n")
        raise AssertionError(command)

    monkeypatch.setattr(acr_tool, "_run", fake_run)
    result = acr_build(
        settings,
        repo_path=str(tmp_path),
        image_name="platform-example",
        tag="v1.2.3",
        push=False,
    )
    assert result["success"] is True
    assert result["pushed"] is False
    assert result["source_revision"] == "abc123def456"
    assert len(result["evidence_gaps"]) == 3
    assert result["image"].endswith(":v1.2.3")


def test_acr_build_default_tag_marks_unversioned_source(settings, tmp_path, monkeypatch):
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        if command[:2] == ["git", "rev-parse"]:
            return _completed(command, returncode=1)
        if command[:3] == ["docker", "image", "inspect"]:
            return _completed(command, stdout="[]\n")
        return _completed(command)

    monkeypatch.setattr(acr_tool, "_run", fake_run)
    result = acr_build(
        settings,
        repo_path=str(tmp_path),
        image_name="platform-example",
        push=False,
    )
    assert result["success"] is True
    assert result["source_revision"] == "unversioned"
    assert result["tag"].endswith("-unversioned")


def test_acr_build_pushes_only_immutable_tag(settings, tmp_path, monkeypatch):
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    configured = settings.model_copy(
        update={"acr_username": "user", "acr_password": "password"}
    )
    monkeypatch.setattr(
        acr_tool.subprocess,
        "run",
        lambda *args, **kwargs: _completed(args[0]),
    )
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["git", "rev-parse"]:
            return _completed(command, stdout="abcdef123456\n")
        if command[:3] == ["docker", "image", "inspect"]:
            return _completed(command, stdout='["image@sha256:abc"]\n')
        return _completed(command)

    monkeypatch.setattr(acr_tool, "_run", fake_run)
    result = acr_build(
        configured,
        repo_path=str(tmp_path),
        image_name="platform-example",
        tag="v2.0.0",
        push=True,
    )
    assert result["success"] is True
    pushed = [command for command in commands if command[:2] == ["docker", "push"]]
    assert len(pushed) == 1
    assert all("latest" not in part for part in pushed[0])


def test_list_acr_images_success(client, settings, monkeypatch):
    configured = settings.model_copy(
        update={"acr_username": "user", "acr_password": "password"}
    )
    monkeypatch.setattr(
        client,
        "list_acr_tags",
        lambda **kwargs: [{"name": "v1.0.0", "digest": "sha256:abc"}],
    )
    result = list_acr_images(client, configured, "platform-example")
    assert result["count"] == 1
    assert result["tags"][0]["digest"] == "sha256:abc"


def test_list_acr_images_wraps_client_error(client, settings, monkeypatch):
    configured = settings.model_copy(
        update={"acr_username": "user", "acr_password": "password"}
    )

    def fail(**kwargs):
        from src.knowledge.github_client import GitHubClientError

        raise GitHubClientError("registry unavailable")

    monkeypatch.setattr(client, "list_acr_tags", fail)
    result = list_acr_images(client, configured, "platform-example")
    assert result["error"] == "GitHubClientError"
