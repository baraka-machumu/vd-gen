"""Application settings (spec §55, amended by review 01 C4/C5). All values come from the environment or `.env`.

Credentials have no defaults and must always be provided. Model paths, GPU assumptions and service URLs are
configuration, never code (spec §71).
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class NetworkMode(StrEnum):
    OFFLINE = "offline"  # spec §38 default: no destination outside the configured internal services
    ONLINE = "online"  # external destinations possible, but only with ENABLE_EXTERNAL_APIS + allow-list


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", frozen=True)

    app_env: AppEnv = AppEnv.PRODUCTION
    log_level: str = "INFO"
    log_json: bool = True

    database_url: SecretStr
    redis_url: str = "redis://redis:6379/0"
    minio_endpoint: str = "minio:9000"
    minio_access_key: SecretStr
    minio_secret_key: SecretStr

    local_llm_base_url: AnyHttpUrl = AnyHttpUrl("http://llm:11434")
    local_llm_model: str = ""
    comfyui_url: AnyHttpUrl = AnyHttpUrl("http://ai-engine:8188")

    default_video_provider: str = "ltx"
    default_video_model: str = "ltx-2.3"
    max_concurrent_video_jobs: int = Field(default=1, ge=1)  # spec §56
    default_video_resolution: str = "1080p"
    default_video_duration: int = Field(default=6, ge=1)

    # Egress policy (spec §38, §73).
    network_mode: NetworkMode = NetworkMode.OFFLINE
    enable_external_apis: bool = False
    # Comma-separated host names. External hosts are reachable only when network_mode=online and
    # enable_external_apis=true. Internal hosts are always reachable (see internal_hosts()).
    allowed_external_hosts: Annotated[frozenset[str], NoDecode] = frozenset()
    extra_internal_hosts: Annotated[frozenset[str], NoDecode] = frozenset()

    @field_validator("allowed_external_hosts", "extra_internal_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return frozenset(h.strip().lower() for h in value.split(",") if h.strip())
        return value

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, value: SecretStr) -> SecretStr:
        """Accept the spec's `postgresql://` form and select the asyncpg driver."""
        raw = value.get_secret_value()
        for prefix in ("postgresql://", "postgres://"):
            if raw.startswith(prefix):
                return SecretStr("postgresql+asyncpg://" + raw[len(prefix) :])
        if not raw.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL (postgresql://...)")
        return value

    @model_validator(mode="after")
    def _consistent_egress(self) -> Settings:
        if self.network_mode is NetworkMode.OFFLINE and self.enable_external_apis:
            raise ValueError("ENABLE_EXTERNAL_APIS=true contradicts NETWORK_MODE=offline; set both explicitly")
        if self.enable_external_apis and not self.allowed_external_hosts:
            raise ValueError(
                "ENABLE_EXTERNAL_APIS=true requires ALLOWED_EXTERNAL_HOSTS (spec §38: explicit allow-list)"
            )
        return self

    @property
    def external_apis_enabled(self) -> bool:
        return self.network_mode is NetworkMode.ONLINE and self.enable_external_apis

    def internal_hosts(self) -> frozenset[str]:
        """Hosts of the platform's own services: always reachable, also offline (spec §73)."""
        hosts = {
            self.local_llm_base_url.host,
            self.comfyui_url.host,
            urlsplit(f"//{self.minio_endpoint}").hostname,
            urlsplit(self.redis_url).hostname,
        }
        return frozenset(h.lower() for h in hosts if h) | self.extra_internal_hosts


@lru_cache
def get_settings() -> Settings:
    return Settings()
