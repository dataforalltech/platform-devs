"""Read-only, workspace-confined artifact provenance tools."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(os.environ.get("PLATFORM_REPO_ROOT", Path(__file__).resolve().parents[2])).resolve()
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from shared.secure_runtime import ToolDefinition, TrustedContext, create_mcp_app  # noqa: E402

_SENSITIVE_NAMES = {
    ".env", ".npmrc", ".pypirc", "credentials", "credentials.json", "id_rsa", "id_ed25519",
    "id_dsa", "id_ecdsa", ".netrc", "_netrc", ".pgpass", "secring.gpg", "authorized_keys",
}
_SENSITIVE_DIRS = {".git", ".ssh", ".gnupg"}
_SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".jks", ".keystore"}
_SENSITIVE_MARKERS = ("secret", "credential", "private_key", "private-key", "id_rsa", "id_ed25519")
_MAX_FILE_SIZE = int(os.environ.get("PROVENANCE_MAX_FILE_BYTES", str(100 * 1024 * 1024)))
_MAX_STATEMENT_BYTES = int(
    os.environ.get("PROVENANCE_MAX_STATEMENT_BYTES", str(512 * 1024 * 1024))
)


def _resolve_artifact(relative_path: str) -> tuple[Path, str]:
    candidate = (REPOSITORY_ROOT / relative_path).resolve(strict=True)
    try:
        normalized = candidate.relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("artifact path escapes the configured repository") from exc
    lowered_parts = {part.lower() for part in candidate.parts}
    lowered_name = candidate.name.lower()
    if (
        _SENSITIVE_DIRS & lowered_parts
        or lowered_name in _SENSITIVE_NAMES
        or lowered_name.startswith(".env.")
        or any(marker in lowered_name for marker in _SENSITIVE_MARKERS)
        or candidate.suffix.lower() in _SENSITIVE_SUFFIXES
    ):
        raise ValueError("sensitive artifact paths are not permitted")
    if not candidate.is_file():
        raise ValueError("artifact path must reference a regular file")
    if candidate.stat().st_size > _MAX_FILE_SIZE:
        raise ValueError("artifact exceeds the configured hashing limit")
    return candidate, normalized


def _git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    # ``safe.directory`` keeps git usable when the worktree is bind-mounted with a
    # different owner than the runtime user (the shipped container runs as ``mcp``
    # over a read-only mount owned by the host uid), which otherwise aborts with
    # "detected dubious ownership" and breaks every provenance call.
    return subprocess.run(
        ["git", "-c", f"safe.directory={REPOSITORY_ROOT}", *arguments],
        cwd=REPOSITORY_ROOT,
        check=check,
        capture_output=True,
        text=True,
        timeout=10,
        shell=False,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _describe(relative_path: str) -> dict[str, Any]:
    path, normalized = _resolve_artifact(relative_path)
    tracked_result = _git("ls-files", "--error-unmatch", "--", normalized, check=False)
    tracked = tracked_result.returncode == 0
    # ``status`` must not turn a git-level failure (e.g. an unrefreshable index on a
    # read-only mount) into a hard tool error; report it as unknown instead.
    status_result = _git("status", "--porcelain=v1", "--", normalized, check=False)
    status = status_result.stdout.strip() if status_result.returncode == 0 else "unknown"
    head = _git("rev-parse", "HEAD", check=False)
    head_sha = head.stdout.strip() if head.returncode == 0 else None
    return {
        "path": normalized,
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
        "git_tracked": tracked,
        "git_status": status or "clean",
        "repository_head": head_sha,
    }


def hash_artifact(arguments: dict[str, Any], _: TrustedContext) -> dict[str, Any]:
    return _describe(arguments["path"])


def verify_artifact(arguments: dict[str, Any], _: TrustedContext) -> dict[str, Any]:
    description = _describe(arguments["path"])
    expected = arguments["expected_sha256"].lower()
    return {
        "path": description["path"],
        "expected_sha256": expected,
        "actual_sha256": description["sha256"],
        "matches": hmac_compare(expected, description["sha256"]),
    }


def hmac_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)


def build_statement(arguments: dict[str, Any], context: TrustedContext) -> dict[str, Any]:
    # Bound total hashing work across the batch, not only per file (the per-file and
    # per-batch caps still apply), so one request cannot fan out into unbounded I/O.
    artifacts: list[dict[str, Any]] = []
    total_bytes = 0
    for path in arguments["paths"]:
        described = _describe(path)
        total_bytes += described["size_bytes"]
        if total_bytes > _MAX_STATEMENT_BYTES:
            raise ValueError("statement exceeds the configured aggregate hashing budget")
        artifacts.append(described)
    return {
        "schema_version": 1,
        "subject": artifacts,
        "repository": REPOSITORY_ROOT.name,
        "repository_head": artifacts[0]["repository_head"] if artifacts else None,
        "environment": context.environment,
        "correlation_id": context.correlation_id,
    }


DESCRIPTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "path": {"type": "string"},
        "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "size_bytes": {"type": "integer", "minimum": 0},
        "git_tracked": {"type": "boolean"},
        "git_status": {"type": "string"},
        "repository_head": {"anyOf": [{"type": "string", "pattern": "^[a-f0-9]{40,64}$"}, {"type": "null"}]},
    },
    "required": ["path", "sha256", "size_bytes", "git_tracked", "git_status", "repository_head"],
}

TOOLS = [
    ToolDefinition(
        name="provenance_hash_artifact",
        description="Compute SHA-256 and Git provenance for one non-sensitive repository artifact.",
        input_schema={
            "type": "object", "additionalProperties": False,
            "properties": {"path": {"type": "string", "minLength": 1, "maxLength": 4096}},
            "required": ["path"],
        },
        output_schema=DESCRIPTION_SCHEMA,
        required_scope="provenance:read", mutating=False, risk_level="low", handler=hash_artifact,
    ),
    ToolDefinition(
        name="provenance_verify_artifact",
        description="Verify an artifact against an expected SHA-256 digest without modifying it.",
        input_schema={
            "type": "object", "additionalProperties": False,
            "properties": {
                "path": {"type": "string", "minLength": 1, "maxLength": 4096},
                "expected_sha256": {"type": "string", "pattern": "^[A-Fa-f0-9]{64}$"},
            },
            "required": ["path", "expected_sha256"],
        },
        output_schema={
            "type": "object", "additionalProperties": False,
            "properties": {
                "path": {"type": "string"},
                "expected_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "actual_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "matches": {"type": "boolean"},
            },
            "required": ["path", "expected_sha256", "actual_sha256", "matches"],
        },
        required_scope="provenance:verify", mutating=False, risk_level="low", handler=verify_artifact,
    ),
    ToolDefinition(
        name="provenance_build_statement",
        description="Build an in-memory provenance statement for repository artifacts using observed hashes and Git state.",
        input_schema={
            "type": "object", "additionalProperties": False,
            "properties": {
                "paths": {"type": "array", "minItems": 1, "maxItems": 100, "uniqueItems": True, "items": {"type": "string", "minLength": 1, "maxLength": 4096}},
            },
            "required": ["paths"],
        },
        output_schema={
            "type": "object", "additionalProperties": False,
            "properties": {
                "schema_version": {"const": 1},
                "subject": {"type": "array", "items": DESCRIPTION_SCHEMA},
                "repository": {"type": "string"},
                "repository_head": {"anyOf": [{"type": "string", "pattern": "^[a-f0-9]{40,64}$"}, {"type": "null"}]},
                "environment": {"type": "string"},
                "correlation_id": {"type": "string"},
            },
            "required": ["schema_version", "subject", "repository", "repository_head", "environment", "correlation_id"],
        },
        required_scope="provenance:read", mutating=False, risk_level="low", handler=build_statement,
    ),
]

app = create_mcp_app("artifact-provenance-mcp", TOOLS)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("MCP_PORT", "7120")))


if __name__ == "__main__":
    main()
