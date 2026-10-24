"""Application settings.

Every value has a working default so the app runs with no configuration at all.
Override via environment variables prefixed ``CS2A_`` or a ``.env`` file; see
``.env.example`` at the repository root.
"""

from __future__ import annotations

import functools
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]

MIB = 1024 * 1024


class Settings(BaseSettings):
    """Runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="CS2A_",
        env_file=(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Storage -------------------------------------------------------------
    data_dir: Path = Field(default=_REPO_ROOT / "data")

    # --- Upload limits -------------------------------------------------------
    max_demo_bytes: int = Field(default=400 * MIB, gt=0)
    min_demo_bytes: int = Field(default=64 * 1024, ge=0)
    max_total_bytes: int = Field(default=20 * 1024 * MIB, gt=0)

    # --- Worker --------------------------------------------------------------
    parse_timeout_s: int = Field(default=900, gt=0)
    worker_mem_limit_mb: int = Field(default=3072, gt=0)
    max_attempts: int = Field(default=2, ge=1)
    keep_demo_files: bool = True
    queue_max_depth: int = Field(default=32, gt=0)

    # --- URL import ----------------------------------------------------------
    allow_url_import: bool = True
    allow_http_import: bool = False
    allow_private_import: bool = False
    import_connect_timeout_s: float = Field(default=5.0, gt=0)
    import_read_timeout_s: float = Field(default=30.0, gt=0)
    import_total_deadline_s: float = Field(default=300.0, gt=0)
    import_max_redirects: int = Field(default=5, ge=0)

    # --- Frontend ------------------------------------------------------------
    serve_frontend: bool = False

    # --- Testing hooks -------------------------------------------------------
    database_url: str | None = None
    """Override the SQLite URL. Used by tests; derived from ``data_dir`` otherwise."""

    @field_validator("data_dir", mode="after")
    @classmethod
    def _absolute(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    # --- Derived paths -------------------------------------------------------
    @property
    def demos_dir(self) -> Path:
        """Where validated demo files are stored under generated names."""
        return self.data_dir / "demos"

    @property
    def tmp_dir(self) -> Path:
        """Scratch space for in-flight uploads.

        Deliberately on the same filesystem as :attr:`demos_dir` so promoting a
        finished upload is an atomic ``os.replace`` rather than a copy.
        """
        return self.data_dir / "tmp"

    @property
    def awpy_dir(self) -> Path:
        """Cache root for awpy map assets (radar images, nav meshes)."""
        return self.data_dir / "awpy"

    @property
    def fixtures_dir(self) -> Path:
        """Downloaded test demos. Never committed."""
        return self.data_dir / "fixtures"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+pysqlite:///{self.db_path}"

    def ensure_dirs(self) -> None:
        """Create the data directories. Idempotent."""
        for path in (self.data_dir, self.demos_dir, self.tmp_dir, self.awpy_dir, self.fixtures_dir):
            path.mkdir(parents=True, exist_ok=True)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
