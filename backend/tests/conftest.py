from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from app.core.config import Settings, get_settings

# Minimal valid environment. Values are placeholders for tests, not real credentials.
BASE_ENV = {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
    "S3_ACCESS_KEY": "test-access",
    "S3_SECRET_KEY": "test-secret",
    "LOG_JSON": "true",
}


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[None]:
    """Each test starts from BASE_ENV only: no developer .env, no leaked variables, no cached settings."""
    monkeypatch.chdir(tmp_path)  # Settings reads .env from the working directory
    for key in list(Settings.model_fields):
        monkeypatch.delenv(key.upper(), raising=False)
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def make_settings(**overrides: Any) -> Settings:
    return Settings(**overrides)
