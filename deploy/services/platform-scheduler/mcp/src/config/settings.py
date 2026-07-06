from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    base_url: str = "http://localhost:8004"
    internal_token: str
    timeout: float = 30.0
    log_level: str = "INFO"
    
    class Config:
        env_prefix = "MCP_SCHEDULER_"
        case_sensitive = False

settings = Settings()
