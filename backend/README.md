# backend/ — Control plane (FastAPI)

Runs on any architecture (arm64 required, amd64 allowed for dev) — see ADR-002.

| Path | Modules |
|---|---|
| `app/core/` | M03 settings, logging, errors, egress guard |
| `app/db/`, `app/models/` | M03 SQLAlchemy + Alembic; tables owned by domain modules |
| `app/api/` | REST `/api/v1/*`, `/health*`, `/ws/*` (M02, M04, M13) |
| `app/schemas/` | Pydantic API schemas |
| `app/services/<domain>/` | Domain logic (M05–M12, M15, M16, M20–M23, M26, M28) |
| `app/providers/` | Provider ABCs + clients (ADR-006): LLM (M11); GPU providers are *clients* of ai-engine |
| `app/workers/` | Postgres-backed job workers (M14, ADR-003) |
| `tests/{unit,integration,api}` | Run in CI with fakes |
| `tests/gx10` | `@pytest.mark.gx10` — run only on the device |

Not started — see [`../status/STATUS.md`](../status/STATUS.md).
