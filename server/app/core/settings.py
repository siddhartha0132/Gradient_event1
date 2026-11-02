"""Process settings, read from environment variables (prefix IC_) and validated at startup."""

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IC_", env_file=SERVER_DIR / ".env", extra="ignore")

    database_path: Path = SERVER_DIR / "data" / "iron_curtain.db"
    jwt_secret: str | None = None  # if unset, generated once and kept next to the database
    access_token_minutes: int = 15
    refresh_token_hours: int = 12

    # Job queue
    job_lease_seconds: float = 10.0  # a running job whose lease expires is reclaimed
    max_job_attempts: int = 3
    verify_exclusive_seconds: float = 20.0  # after this, any worker may take a verify job

    # Fair play: the internet probe is off by default so a dev machine is not flagged
    fairplay_internet_probe: bool = False
    fairplay_probe_url: str = "https://www.google.com/favicon.ico"

    # Built client to serve at /, if present
    client_dist: Path = SERVER_DIR.parent / "client" / "dist"

    def token_secret(self) -> str:
        if self.jwt_secret:
            return self.jwt_secret
        path = self.database_path.parent / ".jwt_secret"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(secrets.token_urlsafe(48))
            path.chmod(0o600)
        return path.read_text().strip()

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path}"

    @property
    def sync_database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
