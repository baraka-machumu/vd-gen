# backend/ — Control plane (FastAPI)

Runs on any architecture (arm64 required, amd64 allowed for dev) — see ADR-002.

| Path | Modules |
|---|---|
| `app/core/` | M03 settings, logging, errors, request middleware, egress guard |
| `app/db/`, `app/models/`, `alembic/` | M03 SQLAlchemy 2 async + Alembic; tables owned by domain modules |
| `app/api/` | REST `/api/v1/*`, `/health*`, `/ws/*` (M02, M04, M13) |
| `app/schemas/` | Pydantic API schemas |
| `app/services/<domain>/` | Domain logic (M05–M12, M15, M16, M20–M23, M26, M28) |
| `app/providers/` | Provider ABCs + clients (ADR-006): LLM (M11); GPU providers are *clients* of ai-engine |
| `app/workers/` | Postgres-backed job workers (M14, ADR-003) |
| `tests/{unit,api}` | Run everywhere, no services needed |
| `tests/integration` | Need PostgreSQL + pgvector (`TEST_DATABASE_URL`); skipped otherwise |
| `tests/gx10` | `@pytest.mark.gx10` — run only on the device |

## Develop

Python 3.12, managed with [uv](https://docs.astral.sh/uv/) (`uv.lock` is committed).

```bash
cd backend
uv sync --python 3.12
uv run pytest                        # unit + API tests
uv run mypy app tests alembic        # strict
uv run ruff check . && uv run ruff format --check .

# Integration tests (real PostgreSQL + pgvector):
docker run --rm -d --name yas-test-pg -p 55432:5432 -e POSTGRES_PASSWORD=test pgvector/pgvector:pg17
TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/postgres uv run pytest

# Run the API (settings from the environment or backend/.env, see ../.env.example):
uv run alembic upgrade head
uv run uvicorn app.main:create_app --factory --reload
```

## Rules that the code enforces

- **Configuration** comes from the environment only (`app/core/config.py`); credentials have no defaults.
- **Outbound HTTP** goes through `app.core.egress.create_http_client()`. It blocks every host that is not one of
  the platform's own services unless `NETWORK_MODE=online`, `ENABLE_EXTERNAL_APIS=true` and the host is in
  `ALLOWED_EXTERNAL_HOSTS` (spec §38). Importing `httpx.AsyncClient`, `requests`, `urllib.request` or `aiohttp`
  directly is a lint error.
- **Errors** return `{"error": {"code", "message", "details", "correlation_id"}}`. Raise an `AppError`
  subclass for client-visible errors; anything else is logged with its traceback and returned as a 500.
- **Every request** carries an `X-Request-ID` (accepted from the caller or generated). It appears in every log line
  and is forwarded on outbound calls.
- **Database work** runs in one transaction per unit of work (`get_session` / `transaction`).
