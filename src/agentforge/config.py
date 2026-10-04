from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTFORGE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://agentforge:agentforge@localhost:5432/agentforge"
    worker_id: str = "worker-local"
    worker_lease_seconds: int = 30
    worker_idle_sleep_seconds: float = 1.0
