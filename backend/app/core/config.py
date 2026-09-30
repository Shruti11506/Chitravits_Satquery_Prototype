"""Application configuration, loaded from environment variables."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/.env, resolved from this file rather than the working directory: a
# relative ".env" silently loaded nothing when uvicorn was started from any
# other folder (e.g. the repo root), leaving Supabase unconfigured. Real
# environment variables (e.g. Docker's env_file) still take precedence.
BACKEND_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "SatQuery Backend"
    APP_VERSION: str = "0.1.0"
    APP_ENV: str = "development"

    SUPABASE_URL: str = ""
    SUPABASE_PUBLISHABLE_KEY: str = ""
    SUPABASE_SECRET_KEY: str = ""

    # Plain comma-separated string (not list[str]) so pydantic-settings doesn't
    # attempt to JSON-decode it -- see `cors_origins` property below.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    SUPABASE_STORAGE_BUCKET: str = "Satquery"
    # Supabase's platform-wide default max upload size is 50MB unless a
    # project raises it (Dashboard -> Storage -> Settings) or the bucket sets
    # its own file_size_limit -- the `Satquery` bucket has none configured
    # (confirmed via get_bucket()), so 50 is the real effective limit, not
    # 500. Raise this only after confirming the project's actual configured
    # limit is higher.
    MAX_UPLOAD_SIZE_MB: int = 50

    # IANA timezone used to bucket query activity into calendar days (heatmap,
    # streaks) when the profile has no timezone of its own.
    APP_TIMEZONE: str = "Asia/Kolkata"

    # Input Validation resource limits (app/validation/limits.py). File size
    # reuses MAX_UPLOAD_SIZE_MB above rather than a second setting for the
    # same ceiling; these three are new and only meaningful to validation.
    VALIDATION_MAX_IMAGE_WIDTH: int = 20000
    VALIDATION_MAX_IMAGE_HEIGHT: int = 20000
    VALIDATION_MAX_BANDS: int = 50
    # width x height ceiling checked by file validation (decompression-bomb guard).
    VALIDATION_MAX_PIXELS: int = 400_000_000
    VALIDATION_MAX_INPUT_IMAGES: int = 2

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def cors_origin_regex(self) -> str | None:
        """Allow local frontends on any port and any Vercel deployment (*.vercel.app)."""
        patterns = [r"^https://.*\.vercel\.app$"]
        if self.APP_ENV == "development":
            patterns.append(r"^http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$")
        return "|".join(patterns)

    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
