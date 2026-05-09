from pathlib import Path

from pydantic_settings import BaseSettings


class AuditSettings(BaseSettings):
    db_path: str = ".audit.db"
    github_token: str = ""
    github_org: str = "dataforalltech"
    policies_path: str = str(Path(__file__).parent.parent / "policies")
    log_level: str = "INFO"

    class Config:
        env_prefix = "AUDIT_"
        env_file = ".env"


def get_settings() -> AuditSettings:
    return AuditSettings()
