"""Testes para tools de pipeline: scaffold_pipeline, get_pipeline_templates."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.tools.pipeline_tool import get_pipeline_templates, scaffold_pipeline

from .conftest import make_mock_repo


class TestGetPipelineTemplates:
    def test_returns_all_six_templates(self):
        result = get_pipeline_templates()

        assert "templates" in result
        assert result["count"] == 6
        names = {t["name"] for t in result["templates"]}
        assert names == {"ci", "deploy", "cd-dev", "cd-hml", "cd-prod", "pr-validate"}

    def test_each_template_has_required_fields(self):
        result = get_pipeline_templates()

        for tpl in result["templates"]:
            assert "name" in tpl
            assert "file" in tpl
            assert "description" in tpl
            assert "required_secrets" in tpl
            assert "required_vars" in tpl

    def test_cd_prod_has_approval_note(self):
        result = get_pipeline_templates()
        prod = next(t for t in result["templates"] if t["name"] == "cd-prod")
        assert "APROVAÇÃO MANUAL" in prod.get("note", "")


class TestScaffoldPipeline:
    def test_installs_all_templates_by_default(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo

        # Mock Git Data API para commit múltiplo
        mock_ref = MagicMock()
        mock_ref.object.sha = "base_sha"
        mock_repo.get_git_ref.return_value = mock_ref

        mock_parent = MagicMock()
        mock_parent.tree = MagicMock()
        mock_repo.get_git_commit.return_value = mock_parent

        mock_blob = MagicMock()
        mock_blob.sha = "blob_sha"
        mock_repo.create_git_blob.return_value = mock_blob
        mock_tree = MagicMock()
        mock_repo.create_git_tree.return_value = mock_tree

        mock_commit = MagicMock()
        mock_commit.sha = "scaffold_sha"
        mock_commit.html_url = "https://github.com/test-org/my-repo/commit/scaffold_sha"
        mock_repo.create_git_commit.return_value = mock_commit

        result = scaffold_pipeline(client, repo="my-repo")

        assert result["committed"] is True
        assert result["count"] == 6
        files = result["files_installed"]
        assert ".github/workflows/ci.yml" in files
        assert ".github/workflows/cd-prod.yml" in files
        assert len(result["next_steps"]) > 0

    def test_installs_subset_of_templates(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo

        mock_ref = MagicMock()
        mock_ref.object.sha = "base_sha"
        mock_repo.get_git_ref.return_value = mock_ref
        mock_parent = MagicMock()
        mock_parent.tree = MagicMock()
        mock_repo.get_git_commit.return_value = mock_parent
        mock_blob = MagicMock()
        mock_blob.sha = "blob"
        mock_repo.create_git_blob.return_value = mock_blob
        mock_repo.create_git_tree.return_value = MagicMock()
        mock_commit = MagicMock()
        mock_commit.sha = "sha"
        mock_commit.html_url = "https://github.com/x/y/commit/sha"
        mock_repo.create_git_commit.return_value = mock_commit

        result = scaffold_pipeline(client, repo="my-repo", templates=["ci", "cd-dev"])

        assert result["count"] == 2
        files = result["files_installed"]
        assert ".github/workflows/ci.yml" in files
        assert ".github/workflows/cd-dev.yml" in files
        assert ".github/workflows/deploy.yml" not in files

    def test_invalid_template_name_returns_error(self, client):
        result = scaffold_pipeline(client, repo="my-repo", templates=["ci", "nonexistent"])
        assert result["error"] == "ValidationError"
        assert "nonexistent" in result["details"]

    def test_missing_repo_returns_validation_error(self, client):
        result = scaffold_pipeline(client, repo="")
        assert result["error"] == "ValidationError"

    def test_custom_commit_message(self, client, mock_github):
        mock_repo = make_mock_repo()
        mock_github.get_repo.return_value = mock_repo

        # 2 templates → _commit_multi → create_git_commit
        mock_ref = MagicMock()
        mock_ref.object.sha = "base"
        mock_repo.get_git_ref.return_value = mock_ref
        mock_parent = MagicMock()
        mock_parent.tree = MagicMock()
        mock_repo.get_git_commit.return_value = mock_parent
        mock_blob = MagicMock()
        mock_blob.sha = "blob"
        mock_repo.create_git_blob.return_value = mock_blob
        mock_repo.create_git_tree.return_value = MagicMock()
        mock_commit = MagicMock()
        mock_commit.sha = "sha"
        mock_commit.html_url = "https://x/commit/sha"
        mock_repo.create_git_commit.return_value = mock_commit

        scaffold_pipeline(
            client,
            repo="my-repo",
            templates=["ci", "cd-dev"],  # 2 arquivos → usa _commit_multi
            commit_message="chore: add ci pipeline",
        )

        call_kwargs = mock_repo.create_git_commit.call_args.kwargs
        assert call_kwargs["message"] == "chore: add ci pipeline"

    def test_template_files_are_valid_yaml(self):
        """Templates embedded devem ser YAML válido."""
        from pathlib import Path

        import yaml

        tpl_dir = (
            Path(__file__).parent.parent
            / "src"
            / "knowledge"
            / "pipeline_templates"
        )
        for yml_file in tpl_dir.glob("*.yml"):
            content = yml_file.read_text(encoding="utf-8")
            parsed = yaml.safe_load(content)
            assert parsed is not None, f"{yml_file.name} não é YAML válido"
            assert "name" in parsed or "on" in parsed, (
                f"{yml_file.name} não parece um GitHub Actions workflow"
            )
