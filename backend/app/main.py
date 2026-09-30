"""FastAPI application factory. Run with: uvicorn app.main:create_app --factory"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import create_engine, create_sessionmaker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="YAS Video Platform API", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        """Liveness only. Dependency checks (/health/{database,redis,storage,gpu,...}) arrive with M02."""
        return {"status": "ok", "version": __version__}

    return app
