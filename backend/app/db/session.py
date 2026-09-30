"""Async engine and per-request transactional sessions (spec §71: use database transactions)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def transaction(sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """One session per unit of work: commits if the block succeeds, rolls back (and re-raises) if it fails."""
    async with sessionmaker() as session, session.begin():
        yield session


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: the request's unit of work."""
    async for session in transaction(request.app.state.sessionmaker):
        yield session
