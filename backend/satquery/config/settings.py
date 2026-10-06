"""Runtime configuration, loaded from environment variables (and an optional ``.env``).

Secrets are held as ``SecretStr`` so they never appear in ``repr()``, logs or
serialised settings. Nothing here has a hard-coded credential or model endpoint
that cannot be overridden from the environment.
"""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from satquery.core.languages import normalize_language_code


class SpeechProvider(StrEnum):
    """Which speech-to-text backend serves voice input."""

    SARVAM = "sarvam"  # real Sarvam AI API
    MOCK = "mock"  # local deterministic stand-in; never calls any external API


class SarvamSettings(BaseSettings):
    """Sarvam AI speech-to-text configuration (``SARVAM_*`` variables)."""

    model_config = SettingsConfigDict(env_prefix="SARVAM_", env_file=".env", extra="ignore")

    api_key: SecretStr | None = None
    base_url: str = "https://api.sarvam.ai"
    stt_path: str = "/speech-to-text"
    stt_model: str = "saaras:v3"
    # Optional Sarvam ``mode`` (e.g. "transcribe", "translate"); omitted from the request when unset.
    stt_mode: str | None = None
    timeout_seconds: float = Field(default=30.0, gt=0)
    # Retries apply only to connection failures and 5xx responses, never to 4xx.
    max_retries: int = Field(default=1, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=0.5, ge=0)

    @field_validator("api_key", mode="before")
    @classmethod
    def _blank_key_is_missing(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("stt_mode", mode="before")
    @classmethod
    def _blank_mode_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class AgentBackend(StrEnum):
    """Which agent implementation ``create_app`` wires in by default."""

    LANGGRAPH = "langgraph"  # the real SatQuery LangGraph orchestrator (EarthMind tool)
    PLACEHOLDER = "placeholder"  # acknowledges the query, runs no tools


class ModelApiProtocol(StrEnum):
    """Which wire protocol a model-service adapter speaks.

    ``WRAPPER`` is the deployed remote wrapper API (``POST /predict``,
    ``multipart/form-data``, ``GET /health``). ``NATIVE`` is this repository's
    own in-tree FastAPI service (``POST /v1/.../infer``, JSON + base64), used
    for local development against the stub backends.
    """

    WRAPPER = "wrapper"
    NATIVE = "native"


class RemoteModelSettings(BaseSettings):
    """Fields every remote model-service adapter needs.

    No URL or credential is ever hard-coded in the agent: the temporary
    Cloudflare tunnels and the eventual ``*.satquery.online`` subdomains are
    both just values of ``api_url``, so swapping them needs no code change.
    """

    # Base URL of the service. Overridden per-service in the subclasses so each
    # one carries a sane local-development default.
    api_url: str = ""
    # Credential, if the deployment requires one. Held as SecretStr so it never
    # appears in repr(), logs, or serialised settings.
    api_key: SecretStr | None = None
    # Header the credential is sent in, and the scheme prefixed to it.
    # For a bare key header set ``api_auth_scheme=""`` (e.g. ``X-API-Key: <key>``).
    api_key_header: str = "Authorization"
    api_auth_scheme: str = "Bearer"
    # Endpoint paths, so a deployment can relocate them without a code change.
    health_path: str = "/health"
    predict_path: str = "/predict"
    # Total per-request timeout; separate (shorter) connect timeout so an
    # unreachable host fails fast instead of hanging the whole query.
    timeout: float = Field(default=180.0, gt=0)
    connect_timeout: float = Field(default=10.0, gt=0)
    api_protocol: ModelApiProtocol = ModelApiProtocol.WRAPPER
    # Inline produced images as base64 in the response. Off by default: the
    # response carries the fetchable ``/outputs`` URL instead, keeping payloads
    # small and database rows sane.
    include_output_base64: bool = False

    @field_validator("api_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("api_key", mode="before")
    @classmethod
    def _blank_key_is_missing(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def key(self) -> str | None:
        """The raw credential, for building a request header. Never log this."""
        return self.api_key.get_secret_value() if self.api_key is not None else None

    @property
    def configured(self) -> bool:
        return bool(self.api_url)


class EarthMindClientSettings(RemoteModelSettings):
    """How the SatQuery agent reaches the EarthMind service (``EARTHMIND_*``).

    These live on the *agent* host. The in-tree inference service on a GPU host
    reads a different set of ``EARTHMIND_*`` variables (see
    ``earthmind_service.config``); the two never share a process, so the
    prefixes do not collide.
    """

    model_config = SettingsConfigDict(env_prefix="EARTHMIND_", env_file=".env", extra="ignore")

    api_url: str = "http://localhost:8001"
    timeout: float = Field(default=180.0, gt=0)
    # Informational: the model name the agent expects. Not used to pick weights.
    model: str = "EarthMind-4B"


class MCDMambaClientSettings(RemoteModelSettings):
    """How the SatQuery agent reaches the MCD-Mamba service (``MCD_MAMBA_*``)."""

    model_config = SettingsConfigDict(env_prefix="MCD_MAMBA_", env_file=".env", extra="ignore")

    api_url: str = "http://localhost:8002"
    # Change detection tiles a scene, so it is the slowest of the three.
    timeout: float = Field(default=300.0, gt=0)
    model: str = "MCD-Mamba"
    # Wrapper inference parameters (permitted values only; see tools/params.py).
    patch_size: int = Field(default=224, ge=32, le=2048)
    return_probabilities: bool = True


class GeoGroundClientSettings(RemoteModelSettings):
    """How the SatQuery agent reaches the GeoGround service (``GEOGROUND_*``).

    Grounding has no in-tree native service, so ``api_protocol`` is always
    ``wrapper``; the field is inherited but not honoured here.
    """

    model_config = SettingsConfigDict(env_prefix="GEOGROUND_", env_file=".env", extra="ignore")

    api_url: str = ""
    timeout: float = Field(default=300.0, gt=0)
    model: str = "GeoGround"
    # Wrapper inference parameters.
    max_points: int = Field(default=50, ge=3, le=1000)
    generate_caption: bool = False


class Settings(BaseSettings):
    """Application configuration (``SATQUERY_*`` variables)."""

    model_config = SettingsConfigDict(env_prefix="SATQUERY_", env_file=".env", extra="ignore")

    app_name: str = "SatQuery AI"
    environment: str = "development"
    log_level: str = "INFO"
    cors_allow_origins: list[str] = Field(default_factory=list)

    agent_backend: AgentBackend = AgentBackend.LANGGRAPH
    # Filesystem root that local attachment references (relative paths / satquery:// ids)
    # are resolved against. Absolute paths and file:// URIs are resolved directly.
    attachment_root: str | None = None
    # Whether the agent may fetch attachment images over http(s). s3/gs/az are never
    # fetched (no storage layer yet) regardless of this flag.
    attachment_allow_http: bool = True

    speech_provider: SpeechProvider = SpeechProvider.SARVAM

    default_language: str = "en"
    max_query_chars: int = Field(default=2000, gt=0)
    max_audio_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    # Sarvam's synchronous REST API accepts clips shorter than 30 s.
    max_audio_seconds: float = Field(default=30.0, gt=0)
    max_attachments: int = Field(default=16, ge=0)
    # Hard cap on the whole request body; defaults to the base64-inflated audio limit + 1 MiB.
    max_request_bytes: int | None = Field(default=None, gt=0)

    # Only used when speech_provider == "mock".
    mock_transcript: str = "What changed between these two satellite images?"
    mock_language: str = "en"

    sarvam: SarvamSettings = Field(default_factory=SarvamSettings)

    # --- Remote model services -------------------------------------------
    # Each is always constructed (so its own ``*_API_URL`` env var is read) and
    # gated by an explicit ``*_enabled`` flag. A service is only offered to the
    # planner when it is both enabled and has a URL configured, so the agent
    # degrades to an honest "not available" instead of a silent misroute.
    earthmind: EarthMindClientSettings = Field(default_factory=EarthMindClientSettings)
    mcd_mamba: MCDMambaClientSettings = Field(default_factory=MCDMambaClientSettings)
    geoground: GeoGroundClientSettings = Field(default_factory=GeoGroundClientSettings)

    earthmind_enabled: bool = True
    mcd_mamba_enabled: bool = True
    geoground_enabled: bool = True

    @field_validator("default_language", "mock_language")
    @classmethod
    def _supported_language(cls, value: str) -> str:
        return normalize_language_code(value)

    # --- derived model-service availability -------------------------------

    @property
    def earthmind_available(self) -> bool:
        return self.earthmind_enabled and self.earthmind.configured

    @property
    def mcd_mamba_available(self) -> bool:
        return self.mcd_mamba_enabled and self.mcd_mamba.configured

    @property
    def geoground_available(self) -> bool:
        return self.geoground_enabled and self.geoground.configured

    @property
    def effective_max_request_bytes(self) -> int:
        if self.max_request_bytes is not None:
            return self.max_request_bytes
        return (self.max_audio_bytes * 4) // 3 + 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
