from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Application settings.

    The three metric thresholds are deliberately root-level rather than
    per-domain: they are assumptions recorded in PRD section 9, and a
    reviewer must be able to find and change them in one place.
    """

    model_config = SettingsConfigDict(
        env_prefix="KESTREL_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    source_db_path: Path
    curated_db_path: Path = REPO_ROOT / "data" / "curated" / "kestrel_curated.db"

    # PRD A1. No documented SLA exists; exposed as configuration, not hard-coded.
    on_time_tolerance_minutes: int = 30
    # PRD A2. Applied uniformly across categories.
    near_expiry_days: int = 30
    # PRD 5.7. Financial year runs April to March.
    fiscal_year_start_month: int = 4

    anthropic_api_key: str | None = None
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
