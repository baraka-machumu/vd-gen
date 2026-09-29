# Private AI Video Production Platform (`yas-video-generator`)

Self-hosted, offline-first platform for multi-scene, multi-episode AI video with consistent characters,
environments, costumes, props, voices and story. Target hardware: **ASUS Ascent GX10 (NVIDIA GB10, 128 GB unified memory, arm64)**.

> **Stage:** P0 (planning & foundations). No application code yet. Documentation comes first.

## Start here

| Document | Purpose |
|---|---|
| [docs/spec/00-original-specification.md](docs/spec/00-original-specification.md) | Original spec (frozen, cited as §N) |
| [docs/review/01-specification-review.md](docs/review/01-specification-review.md) | Engineering review: gaps, risks, amendments, open questions |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Architecture decision records (ADRs) |
| [docs/MODULES.md](docs/MODULES.md) | Module catalog, phases, exit criteria, dependencies |
| [status/STATUS.md](status/STATUS.md) | Live status (generated from `status/status.toml`) |

## Architecture in one line

User → **AI Director** (local LLM, typed plans) → bibles → scene/shot planner → reference retrieval →
**keyframe** → **video** (LTX-2.3 first, pluggable) → QC → regeneration → audio → edit → render.
It is split into a portable **control plane** and a GX10-only **GPU plane** (ADR-002).

## Repository layout

```
backend/     FastAPI control plane (API, services, workers, providers)
frontend/    React + TypeScript web portal
ai-engine/   GPU execution service (NGC arm64): video/image/QC/audio/training adapters
contracts/   Shared Pydantic job contracts
workflows/   Versioned generation recipes
infra/       Compose, nginx, postgres, redis, minio, monitoring
scripts/     setup, health, models, backup, status
docs/        spec, review, ADRs, modules, architecture
status/      status.toml (source of truth) + generated STATUS.md
```

## Updating status

```bash
# edit status/status.toml, then:
python scripts/status/render_status.py          # validates + regenerates status/STATUS.md
python scripts/status/render_status.py --check  # CI: fails if STATUS.md is stale
```
