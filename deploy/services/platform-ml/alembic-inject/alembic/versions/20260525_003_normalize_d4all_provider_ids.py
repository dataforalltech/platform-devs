"""Normalize d4all_* provider IDs across all config tables

Revision ID: 20260525_003
Revises: 20260525_002
Create Date: 2026-05-25

Renames legacy provider identifiers to the new d4all_* naming convention:
  d4all       → d4all_nlp      (ml_nlp_configs.operation_providers)
  local       → d4all_extract  (ml_file_extractor.provider)
  opensource  → d4all_audio    (ml_audio_configs.provider, ml_nlp_configs)
  whisper     → d4all_whisper  (ml_audio_configs.provider)
  coqui       → d4all_tts      (ml_audio_configs.provider)

JSON columns (operation_providers, connector_ids) need string replacement
because they store the provider IDs as JSON values.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers
revision = "20260525_003"
down_revision = "20260525_002"
branch_labels = None
depends_on = None


def _safe_update(conn, table: str, column: str, old: str, new: str) -> None:
    """Replace occurrences of old provider string in column, only if table exists."""
    try:
        # Check if table exists
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name = :t"
            ),
            {"t": table},
        )
        if result.scalar() == 0:
            return
        # Plain string column
        conn.execute(
            text(f"UPDATE `{table}` SET `{column}` = :new WHERE `{column}` = :old"),
            {"new": new, "old": old},
        )
    except Exception:
        pass  # non-fatal — table may not exist in all envs


def _safe_json_replace(conn, table: str, column: str, old: str, new: str) -> None:
    """Replace provider ID inside a JSON string column."""
    try:
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name = :t"
            ),
            {"t": table},
        )
        if result.scalar() == 0:
            return
        # Replace JSON string value occurrences — wrapped in quotes to avoid
        # partial matches (e.g. "d4all" vs "d4all_nlp").
        conn.execute(
            text(
                f"UPDATE `{table}` "
                f"SET `{column}` = REPLACE(`{column}`, '\"{ old }\"', '\"{ new }\"') "
                f"WHERE `{column}` LIKE '%\"{ old }\"%'"
            )
        )
    except Exception:
        pass


def upgrade() -> None:
    conn = op.get_bind()

    # ── ml_nlp_configs ────────────────────────────────────────────────────────
    # operation_providers: JSON like {"sentiment": ["d4all"], "entities": ["d4all"]}
    _safe_json_replace(conn, "ml_nlp_configs", "operation_providers", "d4all", "d4all_nlp")
    # connector_ids JSON — no provider values, skip

    # ── ml_audio_configs ──────────────────────────────────────────────────────
    _safe_update(conn, "ml_audio_configs", "provider", "opensource", "d4all_audio")
    _safe_update(conn, "ml_audio_configs", "provider", "whisper",    "d4all_whisper")
    _safe_update(conn, "ml_audio_configs", "provider", "coqui",      "d4all_tts")

    # ── ml_file_extractor ────────────────────────────────────────────────────
    _safe_update(conn, "ml_file_extractor", "provider", "local", "d4all_extract")
    # operations column is CSV — replace whole word occurrences
    # (operations don't contain provider names, so no change needed there)

    # ── ml_file_extractor_jobs ────────────────────────────────────────────────
    # provider_params JSON may contain provider field
    _safe_json_replace(conn, "ml_file_extractor_jobs", "provider_params", "local", "d4all_extract")


def downgrade() -> None:
    conn = op.get_bind()

    # Reverse: d4all_* → legacy names
    _safe_json_replace(conn, "ml_nlp_configs", "operation_providers", "d4all_nlp", "d4all")
    _safe_update(conn, "ml_audio_configs", "provider", "d4all_audio",   "opensource")
    _safe_update(conn, "ml_audio_configs", "provider", "d4all_whisper", "whisper")
    _safe_update(conn, "ml_audio_configs", "provider", "d4all_tts",     "coqui")
    _safe_update(conn, "ml_file_extractor", "provider", "d4all_extract", "local")
    _safe_json_replace(conn, "ml_file_extractor_jobs", "provider_params", "d4all_extract", "local")
