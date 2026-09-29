# Architecture Decision Records (ADR log)

Each decision includes its context, the decision itself and its consequences. Status values: **Proposed**, **Accepted**, **Superseded by ADR-x**, **Rejected**.
A Proposed ADR becomes Accepted when the product owner or tech lead signs it off. Record the date and name in the ADR.
When an ADR changes a module's scope, update [`MODULES.md`](MODULES.md) and [`../status/status.toml`](../status/status.toml) in the same commit.

| ADR | Title | Status | Blocks |
|---|---|---|---|
| 001 | Monorepo layout per spec §54 | Proposed | M00 |
| 002 | Control plane / GPU plane split | Proposed | M01, M17 |
| 003 | Job system: Postgres is the source of truth, Redis carries signals only | Proposed | M14 |
| 004 | MVP execution backend: native pipelines, ComfyUI after the MVP | Accepted (2026-09-29) | M17, M18 |
| 005 | Unified-memory GPU scheduler; the LLM is a GPU tenant | Proposed | M15 |
| 006 | One capability-based provider interface per modality | Proposed | M11, M18, M19, M25 |
| 007 | GPU images are based on NVIDIA NGC arm64 containers | Proposed | M17 |
| 008 | Keyframe/identity image model: selected by benchmark | **Open** | M19 |
| 009 | A single `asset_embeddings` table; visual memory is a view | Proposed | M09, M20 |
| 010 | Media delivery through nginx `auth_request`; MinIO never exposed | Proposed | M09, M01 |
| 011 | Status tracking lives in `status/status.toml` | Accepted (2026-09-29) | — |
| 012 | Deployment scope: private office network, employee likenesses | Accepted (2026-09-29) | M01, M06, M25, M33 |

---

## ADR-001: Monorepo layout per spec §54

**Context.** The spec defines a single-repo layout. Its placement of `ai_director/` and similar packages conflicts with §10 and §24 (review C10).
**Decision.** Use one repo with the top-level folders `backend/`, `frontend/`, `ai-engine/`, `contracts/`, `workflows/`, `infra/`, `scripts/`, `docs/` and `status/`. Domain services live under `backend/app/services/<domain>/`. The new `contracts/` package holds the Pydantic job payload/result schemas that the backend and the ai-engine share.
**Consequences.** One PR can change an API contract and both of its sides. The backend and ai-engine keep separate dependency lockfiles (see ADR-002).

## ADR-002: Control plane / GPU plane split

**Context.** Development machines are Windows/x86 without a GB10. §82 forbids fake generators outside tests.
**Decision.**
- **Control plane** (api, scheduler, workers for non-GPU jobs, postgres, redis, minio, frontend, nginx): multi-arch images (arm64 required, amd64 allowed for dev). It runs anywhere.
- **GPU plane** (`ai-engine`, `llm`): arm64 only, runs on the GX10. It registers with the scheduler through a heartbeat (§67).
- With no GPU plane registered, every GPU provider reports `UNAVAILABLE` and GPU jobs stay `QUEUED`. The UI says so explicitly.
**Consequences.** The whole control plane can be developed and tested off-device. It also prepares multi-GX10 support (§66) from day one.

## ADR-003: Job system: Postgres is the source of truth, Redis carries signals only

**Context.** The spec leaves Celery vs. custom asyncio open (§5) but requires idempotency, crash recovery and no state corruption (§71, §82). GPU jobs run for minutes.
**Decision.**
- `generation_jobs` in Postgres holds `status`, `priority`, `idempotency_key (unique)`, `lease_owner`, `lease_expires_at`, `heartbeat_at`, `attempt`, `payload`, `result` and `error`.
- Workers claim jobs with `SELECT … FOR UPDATE SKIP LOCKED` and renew the lease through heartbeats. When a lease expires, the job returns to `QUEUED` (up to `max_attempts`).
- Redis is used for wake-up notifications (so workers don't poll), for progress pub/sub, and for the WebSocket fan-out. Losing Redis loses no state.
- Domain results (`generation_attempts`, `assets`) are written in the same transaction that marks the job `SUCCEEDED`.
**Consequences.** The system stays correct across crashes and can be inspected with plain SQL. It needs a small amount of custom code (~500 LOC) instead of Celery. Arq or Dramatiq were considered, but their job state lives in Redis.

## ADR-004: MVP execution backend: native pipelines, ComfyUI after the MVP

**Context.** Spec §7 prefers official Lightricks pipelines. §8 wants ComfyUI as an optional backend. Doing both before the MVP doubles the integration work (review S2).
**Decision.** The `ai-engine` runs official LTX Python pipelines behind `VideoProvider`. A **workflow** is a versioned JSON recipe (`{backend: "native", pipeline, version, params}`) stored in `generation_workflows`, which satisfies §8 reproducibility. The ComfyUI backend (`{backend: "comfyui", graph}`) comes after the MVP.
**Alternative considered.** ComfyUI-first, rejected for the MVP because it would mean running two execution paths before the MVP.
**Accepted** 2026-09-29 by the product owner.

## ADR-005: Unified-memory GPU scheduler; the LLM is a GPU tenant

**Context.** The 128 GB of memory is shared by the CPU and GPU (§33, §80). The local LLM and the video stack are unlikely to fit together at useful sizes.
**Decision.**
- The scheduler keeps a memory ledger: `budget = measured_available − safety_margin`. Each model has a **measured** footprint profile from the registry (§34), which is updated after every load from observed peaks.
- The LLM server is a tenant. The scheduler can request an unload (for example, Ollama `keep_alive=0`) before large video jobs, and it batches planning jobs so the LLM is loaded less often.
- `MAX_CONCURRENT_VIDEO_JOBS=1` at first (§56).
**Consequences.** Planning and rendering are serialized under memory pressure, so the UI shows the scheduler state (§33 states).

## ADR-006: One capability-based provider interface per modality

**Context.** Two conflicting interfaces appear in §6 and §72 (review C3).
**Decision.** Each modality has one ABC (`LLMProvider`, `ImageProvider`, `VideoProvider`, `SpeechProvider`, `MusicProvider`, `SFXProvider`, `UpscaleProvider`, `EmbeddingProvider`). Every ABC exposes `capabilities() -> set[Capability]`, `health_check()`, `estimate_resources(request)` and one typed `run(request)` per operation. An operation outside a provider's capabilities raises `CapabilityNotSupported`. Provider status is one of `AVAILABLE | UNAVAILABLE | UNSUPPORTED_ON_CURRENT_HARDWARE | NOT_APPROVED`.
**Consequences.** The UI and the regeneration engine query capabilities instead of hard-coding them per model.

## ADR-007: GPU images are based on NVIDIA NGC arm64 containers

**Context.** GB10 is a new Blackwell variant, and generic aarch64 PyTorch wheels may lack its kernels (review §5.1).
**Decision.** `ai-engine` builds `FROM nvcr.io/nvidia/pytorch:<tag>` (an arm64 tag that has been validated on DGX OS). Each tag bump runs `scripts/health/gpu_smoke.py`: torch.cuda, device name, a bf16 matmul, attention kernels and a model load.
**Consequences.** The Python version inside ai-engine follows NGC and is decoupled from the backend.

## ADR-008: Keyframe/identity image model: selected by benchmark (OPEN)

**Context.** Identity consistency depends mostly on keyframes (review §5.3), and the spec leaves the image model open.
**Decision process.** Shortlist 2–3 models with permissive commercial licenses that support reference/identity conditioning and run on GB10. Benchmark them on identity similarity, prompt adherence, time and memory using the MVP character. Record the results in `docs/models.md`.
**Owner:** M19. **Deadline:** before Phase 5 starts.

## ADR-009: A single `asset_embeddings` table; visual memory is a view

**Decision.** `asset_embeddings(asset_id, embedding_model, dim, vector, created_at)` has one partial HNSW index per `embedding_model`. `project_visual_memory` is a SQL view over approved assets joined with their embeddings and tags. The reference tables (`character_references`, etc.) don't store vectors themselves.

## ADR-010: Media delivery through nginx `auth_request`; MinIO never exposed

**Decision.** The browser requests `/media/{asset_id}?token=…`. nginx calls `auth_request` against the API, which checks the JWT or short-TTL token and the project membership, then proxies to MinIO over the internal network. MinIO's ports are not published.

## ADR-011: Status tracking lives in `status/status.toml`

**Decision.** `status/status.toml` is the machine-readable source of truth for module and phase status. `status/STATUS.md` is generated from it with `python scripts/status/render_status.py`, and must never be edited by hand. The Definition-of-Done checklist (§83) is tracked in the same file.

## ADR-012: Deployment scope: private office network, employee likenesses

**Context.** Answers to the review's open questions (review §9), given by the product owner on 2026-09-29.
**Decision.**
- The platform is deployed on the **company's private office network only**. It gets no public ingress, and remote access, if needed later, goes through VPN. Spec §66 ("Private LAN/VPN") is the only deployment mode.
- The characters may be based on **employees'** faces and voices. This is real-person likeness, so the consent controls from review M1 are **mandatory**, not optional (see M33):
  - Each employee whose face or voice is used signs a consent record before any of their reference assets can be approved. The record states its scope: which projects, face and/or voice, and whether internal-only or external distribution is allowed.
  - Consent can be **withdrawn** (for example, when the employee leaves). Withdrawal blocks new generations that use that character or voice, and it flags the affected assets for review. It does not silently delete history.
  - Face embeddings and voice references are treated as **sensitive personal data**. Access is restricted to the project's members, every access is audited, and the data is included in the retention and deletion policy (M30).
  - HR/legal should review the consent form and confirm which local privacy or biometric-data rules apply.
- The product owner performs the GX10 deployment and the Phase 0 hardware spike.
**Consequences.**
- Internal-only use does **not** remove model-license obligations, because a company using a model internally is still commercial use. M16 license verification stays mandatory.
- The consent model (M33) moves forward to P2, so it lands together with character references (M06).
