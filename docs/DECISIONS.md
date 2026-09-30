# Architecture Decision Records (ADR log)

Each decision includes its context, the decision itself and its consequences. Status values: **Proposed**, **Accepted**, **Superseded by ADR-x**, **Rejected**.
A Proposed ADR becomes Accepted when the product owner or tech lead signs it off. Record the date and name in the ADR.
When an ADR changes a module's scope, update [`MODULES.md`](MODULES.md) and [`../status/status.toml`](../status/status.toml) in the same commit.

| ADR | Title | Status | Blocks |
|---|---|---|---|
| 001 | Monorepo layout per spec §54 | Proposed | M00 |
| 002 | Control plane / GPU plane split | Proposed | M01, M17 |
| 003 | Job system: Postgres is the source of truth, Redis carries signals only | Proposed | M14 |
| 004 | MVP execution backend: native pipelines, ComfyUI after the MVP | **Superseded by ADR-013** (2026-09-30) | — |
| 005 | Unified-memory GPU scheduler; the LLM is a GPU tenant | Proposed | M15 |
| 006 | One capability-based provider interface per modality | Proposed | M11, M18, M19, M25 |
| 007 | GPU images are based on NVIDIA NGC arm64 containers | Proposed | M17 |
| 008 | Keyframe/identity image model: selected by benchmark | **Open** | M19 |
| 009 | A single `asset_embeddings` table; visual memory is a view | Proposed | M09, M20 |
| 010 | Media delivery through nginx `auth_request`; MinIO never exposed | Proposed | M09, M01 |
| 011 | Status tracking lives in `status/status.toml` | Accepted (2026-09-29) | — |
| 012 | Deployment scope: private office network, employee likenesses | Accepted (2026-09-29) | M01, M06, M25, M33 |
| 013 | ComfyUI is the primary video execution backend | Accepted (2026-09-30) | M15, M17, M18, M19, M28 |
| 014 | No in-workflow prompt enhancement; no abliterated models | Proposed | M10, M11, M16, M18 |
| 015 | SeaweedFS replaces MinIO as the S3-compatible object store | Accepted (2026-09-30) | M01, M09, M30 |

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
**Accepted** 2026-09-29 by the product owner. **Superseded by ADR-013 on 2026-09-30:** the premise changed when we learned that working ComfyUI graphs and weights for LTX, Hunyuan and Wan already exist on the GX10.

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
**Amended by ADR-013:** for the MVP, the GPU runtime is the existing ComfyUI install on the GX10. This ADR now applies when that install is containerized (M17), and to any native-pipeline fallback.

## ADR-008: Keyframe/identity image model: selected by benchmark (OPEN)

**Context.** Identity consistency depends mostly on keyframes (review §5.3), and the spec leaves the image model open.
**Decision process.** Shortlist 2–3 models with permissive commercial licenses that support reference/identity conditioning and run on GB10. Benchmark them on identity similarity, prompt adherence, time and memory using the MVP character. Record the results in `docs/models.md`.
**Owner:** M19. **Deadline:** before Phase 5 starts.

## ADR-009: A single `asset_embeddings` table; visual memory is a view

**Decision.** `asset_embeddings(asset_id, embedding_model, dim, vector, created_at)` has one partial HNSW index per `embedding_model`. `project_visual_memory` is a SQL view over approved assets joined with their embeddings and tags. The reference tables (`character_references`, etc.) don't store vectors themselves.

## ADR-010: Media delivery through nginx `auth_request`; MinIO never exposed

**Decision.** The browser requests `/media/{asset_id}?token=…`. nginx calls `auth_request` against the API, which checks the JWT or short-TTL token and the project membership, then proxies to MinIO over the internal network. MinIO's ports are not published.
**Amended by ADR-015:** the object store is SeaweedFS; "MinIO" here means the object store.

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

## ADR-013: ComfyUI is the primary video execution backend

**Context.** The GX10 already runs ComfyUI with LTX-2.3, HunyuanVideo and Wan installed and working (P0 spike, [`models.md`](models.md)). That removes the main argument for native pipelines (ADR-004): there is nothing left to prove about running the models, and the weights are already downloaded. Spec §8 already allows ComfyUI as an execution backend.
**Decision.**
- All GPU generation (keyframes, video, upscaling, and later control/LoRA inference) runs through ComfyUI's HTTP API behind the `VideoProvider`/`ImageProvider` interfaces (ADR-006). No application code outside the ComfyUI adapter knows ComfyUI exists.
- **Workflow templates** are API-format ComfyUI graphs, versioned in `workflows/<provider>/`. Each template has a small manifest that maps our typed request fields (prompt, image, seed, width, height, length, LoRA, strength, and so on) to `node_id.input` paths. The adapter fills in a copy of the template. Users never edit graphs in production.
- **Reproducibility (spec §8, §40, §82):** each generation attempt stores the exact submitted graph (+ SHA256), the template version, the ComfyUI version, the custom-node versions (git commits), the model file names + SHA256, and the seed. Outputs are fetched through the API and stored as immutable assets in MinIO. ComfyUI's own output folder is not the system of record.
- **The scheduler (ADR-005) is the only submitter** in production. It submits one job at a time (`MAX_CONCURRENT_VIDEO_JOBS=1`), tracks progress via ComfyUI's queue and history APIs, and calls `POST /free` to release memory before switching model families (for example LTX → Wan) or before an LLM planning batch.
- **ComfyUI's result cache:** generation requests always carry an explicit seed. "Regenerate with the same seed" (spec §26) is sent with a cache-busting marker so it re-executes instead of returning the cached output (lesson from the P0 spike).
- **Pinning:** ComfyUI core and each custom node are pinned to recorded commits. Updates go through a staging check: re-run the golden workflows and compare against the reference outputs before adopting.
- **MVP:** we use the **existing** ComfyUI install on the GX10 as an external service (URL from `COMFYUI_URL`). M17 containerizes it (NGC base, ADR-007) after the MVP, or earlier if pinning the existing install proves unreliable.
- The native LTX pipeline scripts (`scripts/spike/ltx_spike.sh`) stay as a **fallback** and a diagnostic tool, not a second production path.
**Consequences.**
- Hunyuan and Wan become reachable through the same adapter. They are still gated by M16 license approval and per-model benchmarks.
- The ComfyUI on the GX10 is now production infrastructure. Ad-hoc use of it (manual experiments in the web UI) competes with platform jobs and can evict loaded models. Once the platform is live, manual use must be scheduled or moved to a separate instance.
- We inherit ComfyUI's release cadence and custom-node quality, which is why the pinning and golden-workflow checks above are mandatory.

## ADR-014: No in-workflow prompt enhancement; no abliterated models

**Context.** The ComfyUI LTX-2.3 i2v template contains a prompt enhancer (`TextGenerateLTX2Prompt`) that rewrites the user prompt with Gemma 3 12B, and loads `gemma-3-12b-it-abliterated_lora` for it. "Abliterated" means the model's refusal behaviour was deliberately removed. It is a community derivative, not an official Gemma release. In the P0 spike ([`models.md`](models.md) Q7, Q8, Q10) the enhancer caused identity and wardrobe drift and implicit cuts; with it off, 3/3 seeds kept the keyframe for 8 s at no speed cost. The LoRA feeds only the enhancer, so with the enhancer off it is unused.
**Decision.**
- Production ComfyUI workflow templates (`workflows/<provider>/`) **do not contain** LLM prompt-rewrite nodes. The prompt the platform stores for a generation attempt is exactly the prompt that was encoded (spec §8).
- Prompt enhancement, where wanted, is done by the **Prompt Engine (M10)** through the platform's own LLM provider (M11): versioned, stored per attempt, and subject to the R-TEXT/R-SHOT prompt rules (review 02).
- **Abliterated or otherwise safety-stripped models** (LLMs, text encoders, LoRAs) are not approved in the model registry (M16). The platform handles employee likenesses (ADR-012), so the safe-by-default behaviour of the base models is kept.
- The template adapter (M18) rejects a workflow that contains a node class on a deny-list (initially `TextGenerateLTX2Prompt`) or references a model file not approved in M16.
**Consequences.**
- The enhancer's possible benefit (richer prompts) must come from M10 prompt templates; P0 results suggest the plain prompt with explicit appearance anchors is better for i2v anyway.
- Manual experiments in the ComfyUI UI may still use the template as shipped; the rule applies to what the platform submits.

## ADR-015: SeaweedFS replaces MinIO as the S3-compatible object store

**Context.** Spec §5, §30 and §65 name MinIO. When M01 was built (2026-09-30), the official `minio/minio` and `minio/mc` images no longer existed on Docker Hub; the community edition is no longer distributed as images, so we would have to build and patch it ourselves. The platform needs only S3 semantics: buckets, object read/write, presigned URLs (ADR-010), per-key permissions.
**Decision.** (Product owner, 2026-09-30.)
- The object store is **SeaweedFS** (Apache-2.0), image `chrislusf/seaweedfs:<version>_large_disk` (official, linux/arm64 + amd64), pinned by version. One container runs master, volume, filer and the S3 gateway.
- The application talks to it **only through the S3 API**, so the store can be replaced by any S3-compatible service without code changes. Settings are vendor-neutral: `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` (replacing spec §55's `MINIO_*`).
- The application key is limited to the platform buckets (spec §30: `ai-video-assets`, `-models`, `-renders`, `-projects`, `-backups`): Read/Write/List/Tagging on those, nothing else. The identity file is generated at container start from the environment; no key is stored in the repo.
- The store is never published outside the compose `data` network (ADR-010, spec §65 unchanged).
**Consequences.**
- Backups (M30) use SeaweedFS's filer/volume backup or an S3-level copy; to be designed there.
- Bucket creation runs as a one-shot `storage-init` job on every `compose up` (idempotent).
- Verified by `scripts/ci/compose_smoke.sh`: the app key can write/read/delete in platform buckets, cannot create other buckets; wrong-key and anonymous access get 403.
