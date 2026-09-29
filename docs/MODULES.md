# Module Catalog & Phase Plan

This document defines **what** each module is and **when it is done**. Live progress is tracked in
[`../status/status.toml`](../status/status.toml) and rendered to [`../status/STATUS.md`](../status/STATUS.md).
Spec references (§N) point at [`spec/00-original-specification.md`](spec/00-original-specification.md). Review references (C/D/S/M-numbers) point at
[`review/01-specification-review.md`](review/01-specification-review.md).

---

## 1. Phases

The phases follow spec §81 with the amendments from review §8: a Phase 0 spike, the image provider in P4, and minimal auth in P1.

| Phase | Name | Goal | Exit criteria |
|---|---|---|---|
| **P0** | Foundations & GX10 spike | Repo, ADRs, CI; prove the GPU stack on real hardware | `verify_gx10.sh` passes on device; one LTX-2.3 i2v clip generated natively; time + peak memory recorded in `docs/models.md` |
| **P1** | Infrastructure | Control plane runs end-to-end | `docker compose up` gives healthy postgres/redis/minio/api/frontend/nginx; `/health/*` green; JWT login works; arm64 buildx succeeds in CI |
| **P2** | Project system | Domain CRUD for the bibles | Projects, Story Bible, characters, costumes, environments, props, assets: CRUD + upload + approval + versioning, with API tests |
| **P3** | AI Director | Local LLM turns intent into a plan | "Create Episode 1" → outline → scenes → shots, schema-valid, each stage gated by approval |
| **P4** | Generation core | Keyframe + video actually render | Shot → keyframe (image provider) → LTX i2v via scheduler on GX10; full provenance recorded; license-gated model registry |
| **P5** | Reference system | Consistency inputs | Retrieval of approved character/env/costume/prop refs + previous-frame chaining (within a scene) feeding generation |
| **P6** | QC & regeneration | **MVP gate** | QC scores per attempt, auto-regeneration rules, preview playback. **Spec §69 acceptance test passes.** |
| **P7** | LoRA & continuity | Stronger identity + story state | Character/style LoRA training + selection; continuity engine; multi-episode state |
| **P8** | Audio | Voice, music, SFX | Local TTS per character voice, music/SFX providers, audio assets |
| **P9** | Timeline & render | Finished episodes | EDL, audio sync, subtitles, preview/1080p/4K-upscale render |
| **P10** | Production hardening | Operate safely | Full RBAC, audit, Prometheus/Grafana, backup/restore drill, multi-worker, security review. **Spec §70 acceptance test + §83 DoD.** |

MVP = P0–P6. Nothing from P7 onward starts until the MVP gate passes, except documentation and design.

---

## 2. Module catalog

Each entry lists: **Phase(s)** · **Code location** · **Spec** · **Depends on** · **Exit criteria**.

### Foundations

**M00: Repository, governance & CI**
P0 · repo root, `.github/` · §54, §71, §75 · none
Exit: repo + ADR log + module plan + status tracker; CI running lint (ruff, eslint), type-check (mypy, tsc), tests, arm64 buildx; pre-commit hooks.

**M01: Infrastructure & Compose**
P1 · `infra/`, `docker-compose*.yml` · §30, §36, §37, §55, §65, §66 · M00
Exit: compose with api, worker, scheduler, frontend, nginx, postgres(+pgvector), redis, minio, and profiles for `gpu` (ai-engine, llm) and `monitoring`. Everything is private-network only, and MinIO is not published (ADR-010).

**M02: Hardware detection & System API**
P0 (script), P1 (API) · `backend/app/services/system/`, `scripts/setup/verify_gx10.sh` · §2, §35, §53, §74 · M03
Exit: `/api/v1/system/capabilities`, `/api/v1/system/hardware`, `/health*`. The GX10 verify script produces the §74 output. It reports the facts it detects and never assumes them.

**M03: Backend core**
P1 · `backend/app/core/`, `backend/app/db/` · §5, §38, §55, §71 · M00
Exit: settings (pydantic-settings, no hard-coded secrets/paths), structured JSON logging with correlation IDs, SQLAlchemy 2 async + Alembic, error model, **egress guard** enforcing `NETWORK_MODE`/`ENABLE_EXTERNAL_APIS` for all outbound HTTP.

**M04: Authentication & RBAC**
P1 (auth), P10 (RBAC) · `backend/app/api/auth/`, `backend/app/services/auth/` · §39, §65 · M03
Exit: P1 has JWT access + rotating refresh, a local admin and password hashing. P10 adds roles and permissions per §39, project membership checks on every route, and permission tests.

### Domain (project data)

**M05: Projects & Story Bible**
P2 · `services/projects/` · §11, §42 · M03, M04
Exit: project CRUD with fps/aspect ratio/default profile (review M7); exactly one active Story Bible per project, versioned.

**M06: Characters & Costumes**
P2 · `services/characters/` · §12, §13, §17 · M05, M09
Exit: character CRUD, reference upload, approval (no in-place replacement, versions only), costume CRUD. Likeness/consent fields per review M1 are included.

**M07: Environments & Props**
P2 · `services/environments/` · §15, §16 · M05, M09
Exit: environment/prop CRUD, reference views (incl. `prop_references`, review C8), approval + versioning.

**M08: Episodes, Scenes, Shots & Approvals**
P2–P3 · `services/production/` · §18–§21, §43, §44, §48, §49 · M05–M07
Exit: join tables (review D2/D3), **explicit state machines** in `docs/architecture/state-machines.md` enforced in the service layer (D1), an `approvals` table + gate configuration (D6), and a `continuity_events` table (D4).

**M09: Assets & Storage**
P2 · `services/assets/` · §5, §30, §62, §65 · M01, M03
Exit: immutable assets with lineage (D7), MinIO buckets, checksums, thumbnails, authenticated `/media` delivery (ADR-010), `asset_embeddings` (ADR-009).

### Intelligence

**M10: Prompt Engine & Prompt Versioning**
P3 · `services/prompting/` · §22, §48 · M08
Exit: a deterministic builder: the same structured input always gives a byte-identical prompt (snapshot tests). Sections per §22. Prompt text is stored only in `prompt_versions` (C7), with version diffing.

**M11: LLM Provider Layer**
P3 · `backend/app/providers/llm/` · §5, §9, §38 · M03
Exit: an OpenAI-compatible local provider (Ollama/llama.cpp/vLLM), JSON-schema constrained output, retries with validator feedback, and an external provider that is disabled unless allowed by M03 egress policy.

**M12: AI Director**
P3 · `backend/app/services/ai_director/` · §3, §10, §43 · M08, M10, M11, M14
Exit: story/episode/scene/shot/continuity/prompt directors. Planning is hierarchical (review §5.5), outputs are typed only and never touch a shell or tools, and the LLM model, template and raw output are recorded per planning job.

### Execution

**M13: Realtime Events (WebSocket)**
P3–P4 · `backend/app/api/ws/` · §46 · M14
Exit: `/ws/projects/{id}` with the §46 events, fed from Redis pub/sub, with auth on connect.

**M14: Job System & Workers**
P1 (skeleton), P3 · `backend/app/workers/`, `contracts/` · §32, §71 · M03
Exit: a Postgres-backed queue per ADR-003 with leases, heartbeats, idempotency keys and retry/backoff; crash-recovery tests (kill a worker mid-job, and the job is re-leased).

**M15: GPU Scheduler & Worker Registry**
P4 · `backend/app/services/scheduler/` · §33, §56, §66, §67, §80 · M14, M16
Exit: a memory ledger from measured profiles (ADR-005), LLM tenancy, per-worker capabilities and heartbeat, and `MAX_CONCURRENT_VIDEO_JOBS` honored. It is multi-node-ready but runs a single node.

**M16: Model Registry & License Registry**
P4 · `services/models/`, `scripts/models/` · §34, §50, §51, §78 · M03
Exit: registry states (installed / not installed / downloading / unavailable / incompatible / not approved), pinned repo + revision + SHA256, and `model_licenses` with admin approval **required** before production use. Also an offline fetch/bundle tool (review M5).

**M17: AI Engine Runtime**
P0 (spike), P4 · `ai-engine/common/` · §36, §37, §75, §80 · M16
Exit: an NGC arm64 image (ADR-007), a job execution loop that claims GPU jobs, model load/unload with measured memory, cooperative cancel, and a GPU smoke test. `ai-engine` and `llm` are the only GPU tenants.

**M18: Video Providers**
P4 (LTX), post-MVP (Hunyuan/Wan) · `ai-engine/ltx/`, `ai-engine/hunyuan/`, `ai-engine/wan/`, `workflows/` · §6, §7, §8, §57, §58, §72, §79 · M17
Exit: LTX-2.3 i2v + t2v (+ first/last frame if supported) via the capability interface (ADR-006), Draft/Preview/Production profiles, and two-stage upscale. Unverified providers report `UNSUPPORTED_ON_CURRENT_HARDWARE`. The workflow recipe is stored per attempt (ADR-004).

**M19: Image / Keyframe Provider**
P4 · `ai-engine/image/` · §21, §79 · M17
Exit: keyframe generation with reference conditioning, and first/last frame generation. The model is chosen by the ADR-008 benchmark.

### Consistency & quality

**M20: Reference Retrieval & Embeddings**
P5 · `services/references/` · §23, §59, §60, §62 · M09, M17
Exit: an `EmbeddingProvider`, retrieval of approved refs ranked for a shot, and previous-frame chaining within a scene only (review §5.3). The selected refs are recorded in `generation_attempt_references`.

**M21: QC Engine**
P6 · `services/qc/` + `ai-engine/qc/` · §25, §63 · M20
Exit: deterministic technical checks first (ffprobe), then character/environment/adherence/motion scores per the review §5.4 definitions, configurable thresholds, and a calibration-set procedure documented.

**M22: Regeneration Engine**
P6 · `services/regeneration/` · §26, §49, §64 · M21, M18
Exit: every §26 mode that the provider capabilities allow, auto-regeneration rules with a max of 3, then `REVIEW_REQUIRED`. Attempts are append-only.

**M23: Continuity Engine**
P7 · `services/continuity/` · §24, §61 · M08, M12
Exit: rule checks for costume, location, props, time of day, weather and story; explicit override with a reason; `episode_end_states` + `continuity_context.json` injected into planning.

**M24: LoRA Training & Management**
P7 · `ai-engine/training/`, `services/loras/` · §13, §14 · M17, M20, M21
Exit: dataset prep from approved refs, a training state machine per §14, validation via QC, versions, and strength selection. `kind` = character/style (review C2). GB10 training time is benchmarked.

### Output

**M25: Audio**
P8 · `ai-engine/audio/`, `services/audio/` · §27, §28 · M17, M16, M33
Exit: speech/music/SFX providers (local), voices linked to characters (D12), voice cloning blocked without consent.

**M26: Timeline & Render**
P6 (preview only), P9 · `services/rendering/` · §29, §57, §58 · M09, M25
Exit: a `timelines` table with the EDL (D10), FFmpeg render of preview/1080p/4K-via-upscaler, subtitles from dialogue (D11), and a render job with progress.

**M27: Web Portal (Frontend)**
P1–P9 · `frontend/` · §41, §42 · M13 + backing modules
Exit: per-phase pages: Dashboard, Project tabs, Character/Environment/Episode/Shot/Render studios. Each studio ships in the phase of its backend module.

### Operations & governance

**M28: Audit & Provenance**
P4 (provenance), P10 (audit log) · `services/audit/` · §40, §82 · M08, M14
Exit: every attempt links project → episode → scene → shot → model + version → workflow → prompt version → refs → seed → LoRA → hardware/software versions → QC. A "why does this shot look like this" API/UI view exists. `audit_logs` covers user actions.

**M29: Observability**
P1 (logs), P10 (metrics) · `infra/monitoring/` · §52 · M01
Exit: Prometheus + Grafana with the §52 metrics, GPU/unified-memory exporters validated on GB10, dashboards and alerts (disk pressure, queue stuck, worker lost).

**M30: Backup & Retention**
P10 · `scripts/backup/` · §50 · M01, M09
Exit: Postgres + MinIO backup, a **tested restore drill**, and a retention policy for failed-attempt media (review M4).

**M31: Install & Ops Scripts**
P1, P10 · `scripts/setup/`, `scripts/health/` · §74, §75 · M01, M02
Exit: `install.sh` performs the §74 steps idempotently; `verify_gx10.sh` exists; an offline install path is available.

**M32: Documentation**
All phases · `docs/` · §76 · none
Exit: the §76 doc set, each doc written in the phase of the module it describes, not all at the end.

**M33: Security, Privacy & Likeness Consent**
P2 (consent), P10 (review) · cross-cutting · §38, §39, §65, review M1/M2 · M04, M09
Exit: consent records required for real-person likeness/voice, egress tests (runtime makes **zero** external calls in offline mode), a threat model, and a security review (§83).

---

## 3. Dependency overview

```
M00 ─┬─ M03 ─┬─ M04 ── M05 ─┬─ M06 ─┐
     │       │              ├─ M07 ─┼─ M08 ─┬─ M10 ─┐
     ├─ M01 ─┴─ M09 ────────┘       │       │       ├─ M12 (AI Director)
     │                              │       └─ M23  │
     │       M03 ── M11 ────────────┼───────────────┘
     │       M03 ── M14 ─┬─ M13     │
     │                   └─ M15 ─┐  │
     └─ M16 ── M17 ─┬─ M18 ──────┼──┴─ M20 ── M21 ── M22   ◄── MVP gate (P6)
                    ├─ M19 ──────┘         └── M24 (LoRA)
                    └─ M25 (audio) ── M26 (render)
```

**MVP critical path:** M00 → M03 → M09 → M08 → M14 → M16 → M17 → M19 → M18 → M20 → M21 → M22 → M26(preview).
The **M17 GX10 spike (P0)** de-risks this path and runs in parallel with P1.

---

## 4. Status vocabulary

| Status | Meaning |
|---|---|
| `NOT_STARTED` | No work yet |
| `DESIGN` | Designing: ADR/interface/schema in progress |
| `IN_PROGRESS` | Implementation underway |
| `BLOCKED` | Cannot proceed; `blocked_by` must be set |
| `IN_REVIEW` | Code complete, under review/testing |
| `DONE` | Exit criteria met **and verified** (on GX10 where the criteria mention hardware) |

A module may be marked `DONE` only when its exit criteria above are met. Partial completion is expressed through its task list.
