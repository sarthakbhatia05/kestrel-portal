from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
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

    # PRD C4.6: absent means the ask-anything surface reports itself
    # unavailable. Every dashboard figure is unaffected.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    cors_origins: list[str] = ["http://localhost:5173"]

    @field_validator("source_db_path", "curated_db_path")
    @classmethod
    def _resolve_against_repo_root(cls, value: Path) -> Path:
        """Interpret relative paths from the repository root, not the shell's cwd.

        Otherwise the same .env means different files depending on whether
        the reader is standing in backend/ or at the root, which is exactly
        the kind of cold-start trap NF1 exists to prevent.
        """
        return value if value.is_absolute() else (REPO_ROOT / value).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
