from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import NetworkMode, Settings
from tests.conftest import make_settings


def test_defaults_are_offline_and_single_video_job() -> None:
    s = make_settings()
    assert s.network_mode is NetworkMode.OFFLINE
    assert s.enable_external_apis is False
    assert s.external_apis_enabled is False
    assert s.max_concurrent_video_jobs == 1


def test_spec_style_database_url_gets_async_driver() -> None:
    s = make_settings(database_url="postgresql://u:p@db:5432/app")
    assert s.database_url.get_secret_value() == "postgresql+asyncpg://u:p@db:5432/app"


def test_non_postgres_database_url_is_rejected() -> None:
    with pytest.raises(ValidationError, match="PostgreSQL"):
        make_settings(database_url="sqlite:///x.db")


def test_secrets_are_not_printed() -> None:
    text = repr(make_settings()) + str(make_settings().model_dump())
    assert "test-secret" not in text
    assert "test:test" not in text


def test_credentials_are_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MINIO_SECRET_KEY")
    with pytest.raises(ValidationError, match="minio_secret_key"):
        Settings()


def test_offline_with_external_apis_is_a_configuration_error() -> None:
    with pytest.raises(ValidationError, match="contradicts NETWORK_MODE=offline"):
        make_settings(enable_external_apis=True, allowed_external_hosts="api.example.com")


def test_external_apis_need_an_allow_list() -> None:
    with pytest.raises(ValidationError, match="ALLOWED_EXTERNAL_HOSTS"):
        make_settings(network_mode="online", enable_external_apis=True)


def test_host_lists_parse_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETWORK_MODE", "online")
    monkeypatch.setenv("ENABLE_EXTERNAL_APIS", "true")
    monkeypatch.setenv("ALLOWED_EXTERNAL_HOSTS", " API.Example.com, other.example.org ,")
    s = Settings()
    assert s.allowed_external_hosts == {"api.example.com", "other.example.org"}
    assert s.external_apis_enabled


def test_internal_hosts_come_from_service_urls() -> None:
    s = make_settings(
        comfyui_url="http://gx10.local:8188",
        local_llm_base_url="http://llm:11434",
        minio_endpoint="minio:9000",
        extra_internal_hosts="nas.office.lan",
    )
    assert s.internal_hosts() >= {"gx10.local", "llm", "minio", "redis", "nas.office.lan"}


def test_env_example_is_a_valid_configuration() -> None:
    """../.env.example must stay loadable: every key known, inline comments stripped, offline by default."""
    example = Path(__file__).resolve().parents[3] / ".env.example"
    s = Settings(_env_file=example)
    documented = {
        line.split("=", 1)[0].strip().lower()
        for line in example.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    assert documented == set(Settings.model_fields)
    assert s.network_mode is NetworkMode.OFFLINE
    assert s.allowed_external_hosts == frozenset()
    assert s.comfyui_url.host == "ai-engine"
