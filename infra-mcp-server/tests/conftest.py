"""Fixtures compartilhadas — Settings com binários falsos para teste isolado."""

from __future__ import annotations

import pytest

from src.config.settings import Settings


@pytest.fixture
def fake_settings(tmp_path) -> Settings:
    """Settings que aponta para binários inexistentes (para forçar BinaryNotFound)
    OU para um runner mockado via monkeypatch nos testes específicos."""
    return Settings(
        terraform_root=tmp_path,
        terraform_bin="fake-terraform-bin",
        checkov_bin="fake-checkov-bin",
        infracost_bin="fake-infracost-bin",
        plan_timeout=10,
        validate_timeout=10,
        scan_timeout=10,
        cost_timeout=10,
        output_max_chars=4000,
    )
