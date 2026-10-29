import re
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # Comma-separated browser Origins. No trailing slash.
    cors_origins: str = "http://localhost:3000,https://ledger-nz.pages.dev"

    database_url: str = "sqlite:///./ledger.db"
    allow_dev_auth: bool = False
    transfer_regex: str = ""
    own_account_labels: str = "savings,transactions"
    transfer_window_days: int = 3

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    # Auth0 SPA login. Leave blank to keep Supabase email login.
    auth0_domain: str = ""
    auth0_audience: str = ""
    auth0_client_id: str = ""

    google_service_account_file: str = ""
    google_drive_root_folder_id: str = ""

    groq_api_key: str = ""
    groq_vision_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    ocr_tailscale_host: str = ""
    ocr_model: str = "qwen3.6:27b"
    ocr_confidence_threshold: float = 0.85
    ocr_timeout_seconds: float = 180

    wol_enabled: bool = True
    wol_mac_address: str = ""
    wol_broadcast: str = "255.255.255.255"
    wol_port: int = 9
    wol_wait_seconds: int = 90

    @property
    def cors_origin_list(self) -> List[str]:
        # Browsers send Origin with no path and no trailing slash. Keep both forms so a
        # dashboard value like https://ledger-nz.pages.dev/ still matches the live site.
        origins: list[str] = []
        for item in self.cors_origins.split(","):
            origin = item.strip().rstrip("/")
            if not origin:
                continue
            for candidate in (origin, f"{origin}/"):
                if candidate not in origins:
                    origins.append(candidate)
        return origins

    @property
    def cors_origin_regex(self) -> str | None:
        bases = [item.strip().rstrip("/") for item in self.cors_origins.split(",") if item.strip()]
        if not bases:
            return None
        return r"^(" + "|".join(re.escape(base) + r"/?" for base in dict.fromkeys(bases)) + r")$"

    @property
    def confidence_floor(self) -> float:
        value = float(self.ocr_confidence_threshold)
        return value / 100 if value > 1 else value

    @property
    def own_labels(self) -> list[str]:
        return [part.strip() for part in self.own_account_labels.split(",") if part.strip()]

    @property
    def auth0_host(self) -> str:
        value = self.auth0_domain.strip()
        for prefix in ("https://", "http://"):
            if value.lower().startswith(prefix):
                value = value[len(prefix) :]
        return value.strip("/")

    @property
    def auth0_issuer(self) -> str:
        if not self.auth0_host:
            return ""
        return f"https://{self.auth0_host}/"

    @property
    def ocr_provider(self) -> str:
        if self.groq_api_key.strip():
            return "groq"
        if self.ocr_tailscale_host.strip():
            return "ollama"
        return "off"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def assert_production(settings: Settings) -> None:
    if settings.app_env != "production":
        return
    if not settings.supabase_url.strip() or not settings.supabase_jwt_secret.strip():
        raise RuntimeError("Production requires SUPABASE_URL and SUPABASE_JWT_SECRET")
    if settings.allow_dev_auth:
        raise RuntimeError("ALLOW_DEV_AUTH must be false in production")
    if not settings.auth0_host:
        return
    missing = []
    if not settings.auth0_audience.strip():
        missing.append("AUTH0_AUDIENCE")
    if not settings.auth0_client_id.strip():
        missing.append("AUTH0_CLIENT_ID")
    if not settings.supabase_service_role_key.strip():
        missing.append("SUPABASE_SERVICE_ROLE_KEY")
    if missing:
        raise RuntimeError("Auth0 login requires " + ", ".join(missing))
