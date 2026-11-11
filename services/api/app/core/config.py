import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def data_home() -> Path:
    """Folder for private runtime data: database, uploaded resumes, browser profile, logs, .env.

    It is outside the repository so personal data can never be committed by accident.
    APPLYPILOT_HOME overrides it (tests and Docker set their own paths).
    """
    override = os.environ.get("APPLYPILOT_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ApplyPilot"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applypilot"


class Settings(BaseSettings):
    # The private .env in the data folder wins over a .env in the working directory.
    # Real environment variables win over both.
    model_config = SettingsConfigDict(env_file=(".env", str(data_home() / ".env")), env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ApplyPilot"
    database_url: str = f"sqlite:///{data_home() / 'applypilot.db'}"
    demo_mode: bool = True
    access_token_hours: int = 12
    storage_dir: str = str(data_home() / "storage")
    cors_origins: str = "http://localhost:3000"
    # Host names the API answers to. Requests for any other Host header are refused, which
    # blocks DNS-rebinding attacks from web pages against this local server.
    allowed_hosts: str = "localhost,127.0.0.1"
    # ApplyPilot is single-user: new accounts can be created only while none exists.
    # Set ALLOW_REGISTRATION=true to open sign-up again (for example, for a second profile).
    allow_registration: bool = False
    ai_provider: str = "auto"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    # Cheaper model for simple, high-volume work (extraction checks, connection tests).
    anthropic_fast_model: str = "claude-haiku-5-5"
    # Used when the user picks the higher-quality option in Settings.
    anthropic_premium_model: str = "claude-opus-5-5"
    # Hard stop for estimated AI spend (US dollars, all time). The user can change it in Settings.
    ai_spend_limit_usd: float = 4.50
    # Hard ceiling for all AI use on this installation per calendar month, including background
    # work that is not tied to a user and every account on the server.
    ai_monthly_limit_usd: float = 25.00
    # Request rate limits per user (background work counts as one caller). They stop runaway
    # loops before they cost money; normal use stays far below them.
    ai_requests_per_minute: int = 30
    ai_requests_per_hour: int = 300
    # Reasoning effort for the main model. Lower is cheaper.
    ai_effort: str = "medium"
    # Browser-assisted applications: a visible Chrome window with its own ApplyPilot profile.
    autoapply_enabled: bool = True
    autoapply_headless: bool = False
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    adzuna_country: str = "ca"
    job_board_tokens: str = "greenhouse:gitlab"
    public_job_sources: bool = True
    redis_url: str = ""
    celery_enabled: bool = False
    cookie_secure: bool = False
    # "production" turns off every development convenience (for example, reset links in the server log).
    environment: str = "development"
    # Public address of the web app, used in emailed links.
    app_base_url: str = "http://localhost:3000"
    # Outgoing email (password reset). Any SMTP provider works.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_security: str = "starttls"  # starttls | ssl | none
    password_reset_minutes: int = 30
    # Runs saved searches that have automatic refresh turned on.
    scheduler_enabled: bool = True
    scheduler_interval_minutes: int = 15
    max_upload_bytes: int = 8 * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [item.strip() for item in self.allowed_hosts.split(",") if item.strip()]

    @property
    def storage_path(self) -> Path:
        path = Path(self.storage_dir).expanduser()
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(0o700)
        return path

    @property
    def ai_provider_name(self) -> str:
        provider = (self.ai_provider or "").lower()
        if provider in {"anthropic", "claude"}:
            return "anthropic" if self.anthropic_api_key else "none"
        if provider == "openai":
            return "openai" if self.openai_api_key else "none"
        if provider in {"", "auto"}:
            if self.anthropic_api_key:
                return "anthropic"
            if self.openai_api_key:
                return "openai"
        return "none"

    @property
    def ai_configured(self) -> bool:
        return self.ai_provider_name != "none"

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def adzuna_configured(self) -> bool:
        return bool(self.adzuna_app_id and self.adzuna_app_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
