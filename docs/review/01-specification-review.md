# Specification Review — Private AI Video Production Platform

| | |
|---|---|
| **Reviewed document** | [`docs/spec/00-original-specification.md`](../spec/00-original-specification.md) (v0, 83 sections) |
| **Review date** | 2026-09-29 |
| **Perspective** | AI engineering + software engineering |
| **Outcome** | **Approve with amendments.** The architecture is right. Before coding starts, the spec needs the consistency fixes in §3 and the decisions in [`DECISIONS.md`](../DECISIONS.md). |

Severity legend: **🔴 Blocker**: must be resolved before the affected module starts. **🟠 Major**: causes rework if ignored. **🟡 Minor**: clarify when convenient.

Claims about third-party models, licenses and hardware are flagged **[VERIFY]**. They follow the spec's own rule (§78): nothing counts as confirmed until someone checks the upstream source or tests it on the GX10.

---

## 1. Summary

This is a strong spec. It gets the hardest parts right:

1. **The director/renderer split (§3).** Treating the LLM as a planner that emits typed data, and video models as interchangeable renderers, is the only architecture that can keep characters consistent across 80+ shots.
2. **Keyframe-first plus approval gates (§21, §43, §44).** Video generation is the most expensive step, and these gates make sure humans reject bad shots before it runs.
3. **Immutable history (§48, §49, §40, §82).** Versioned prompts, append-only generation attempts and full provenance. The requirement "Why does this shot look the way it does?" is a good north-star test.
4. **Honest hardware handling (§37, §78, §80).** The `UNSUPPORTED_ON_CURRENT_HARDWARE` rule prevents the most common failure mode on new ARM64 hardware: pretending an unverified model works.
5. **MVP scoping (§68, §69).** The acceptance test is concrete and small.

The main weaknesses:

- **Internal inconsistencies:** duplicate or conflicting table names, endpoints, interface names and container topologies (§3 below).
- **Underspecified data model:** there are no state machines, relationships are stored as arrays, and several referenced entities have no table (§4).
- **Unvalidated feasibility assumptions:** GB10 throughput, memory co-residency, QC metrics and licenses (§5, §6).
- **Missing non-functional requirements:** throughput targets, likeness/consent governance, retention, CI strategy without GPUs (§7).
- **Scope:** 30 deliverables and 12 docs make a multi-quarter program. The phase plan needs explicit exit criteria so that phases 1 through 6 (the MVP) can ship alone (§8).

---

## 2. What to keep unchanged

| Area | Spec § | Why it is right |
|---|---|---|
| Provider abstraction for video/LLM/audio | §6, §9, §27, §72 | Model churn in this space is measured in months. |
| PostgreSQL as source of truth + MinIO for blobs + pgvector | §5, §30 | Minimal moving parts; one transactional store. |
| One GPU execution service rather than container-per-model | §36 | Avoids duplicated weights in unified memory. |
| Store workflow JSON per asset | §8 | Needed for reproducibility. |
| Deterministic prompt builder from structured metadata | §22 | Prompts become a derived artifact, not hand-maintained text. |
| Offline by default, explicit egress allow-list | §38, §73 | Correct default for private IP. |
| Model license registry + admin approval | §51 | Needed because several candidate models have restrictive licenses (see §6). |
| Never delete failed generations | §25, §49 | Needed for debugging, and later for QC calibration data. |

---

## 3. Internal inconsistencies (fix in spec)

| # | Sev | Finding | Where | Recommended resolution |
|---|---|---|---|---|
| C1 | 🟠 | System endpoints appear in three forms: `/api/system/capabilities`, `/api/system/hardware`, `/api/v1/system` | §2, §35, §45 | Use `/api/v1/system/capabilities` and `/api/v1/system/hardware`. Keep `/health*` unversioned for probes. |
| C2 | 🟠 | Two names for the LoRA table: `loras` vs `character_loras`. §81 also requires **style** LoRAs, which have no character | §14, §31, §81 | Use a single `loras` table with `kind ∈ {CHARACTER, STYLE, ENVIRONMENT}` and a nullable `character_id`. |
| C3 | 🟠 | Two different video interfaces: `VideoGenerationProvider` (9 methods) vs `VideoProvider` (5 methods, different names) | §6, §72 | Use a single `VideoProvider` ABC. Add `capabilities()`, and make unsupported ops raise `CapabilityNotSupported` rather than requiring every provider to implement everything. See ADR-006. |
| C4 | 🟠 | Container topology is given two ways: a separate `comfyui` service vs ComfyUI hosted inside `ai-engine` (`COMFYUI_URL=http://ai-engine:8188`) | §36, §55 | ComfyUI runs **inside** `ai-engine` as one of its execution backends. |
| C5 | 🟠 | `LOCAL_LLM_BASE_URL=http://llm:11434` refers to an `llm` service that is not in the compose list. Prometheus/Grafana are also missing from the list | §36, §52, §55 | Add `llm`, `prometheus`, `grafana` (and optionally `node-exporter`/`dcgm-exporter`) to compose. |
| C6 | 🟠 | Three separate embedding stores: `*_references.embedding`, `asset_embeddings`, `project_visual_memory` | §12, §15, §31, §62 | Use one `asset_embeddings` table (asset_id, embedding_model, dim, vector). `project_visual_memory` becomes a **view** over approved assets + embeddings + tags. |
| C7 | 🟡 | `shots.prompt`/`negative_prompt` and `prompt_versions` both hold the prompt | §20, §48 | `shots.current_prompt_version_id` FK. The prompt text lives only in `prompt_versions`. |
| C8 | 🟡 | `props.embedding` and `props.reference_asset_id` limit a prop to one reference image | §16 | Add a `prop_references` table, matching characters and environments. |
| C9 | 🟡 | Audio has both `TTSProvider` and `VoiceProvider` with no clear boundary | §27 | `TTSProvider` = text→speech. `VoiceProvider` = voice-identity management (clone/register). Or merge them into a single `SpeechProvider`. |
| C10 | 🟡 | The directory tree puts `ai_director/`, `continuity/` etc. **beside** `services/`, but §10 and §24 say `/services/ai_director/` | §10, §24, §54 | Use `backend/app/services/<domain>/`. Scaffold follows this. |
| C11 | 🟡 | Repo name `ai-video-platform/` vs this workspace `yas-video-generator` | §54 | Keep the workspace name. Internal layout follows §54. |
| C12 | 🟡 | "Celery **or** custom asyncio" leaves the job system undecided | §5 | Decided in ADR-003. |

---

## 4. Data-model and domain gaps

| # | Sev | Gap | Recommendation |
|---|---|---|---|
| D1 | 🔴 | **No state machines** for scene, shot, asset, generation_attempt, render_job, approval. Episode has statuses, but the spec never defines the transitions. | Define explicit transition tables in `docs/architecture/state-machines.md` (M08). Enforce them in one service layer. Reject illegal transitions with 409. |
| D2 | 🟠 | Many-to-many relationships are stored as arrays (`scenes.characters`, `shots.character_ids`, `prop_ids`, `costume_ids`, `reference_asset_ids`). You lose FK integrity, and deleting a character leaves orphaned IDs behind. | Use join tables: `scene_characters(scene_id, character_id, costume_id)`, `shot_characters`, `shot_props`, `generation_attempt_references(attempt_id, asset_id, role, weight)`. |
| D3 | 🟠 | Costume is per character, but a scene references `costumes` without saying who wears which. | Store `costume_id` on `scene_characters` (see D2). |
| D4 | 🟠 | §24 mentions a "wardrobe event" but no entity defines one, so the continuity engine cannot tell a legitimate change from drift. | Add `continuity_events(scene_id, shot_id?, type, subject, before, after, reason)`. |
| D5 | 🟠 | Multi-episode continuity (§61) produces `continuity_context.json` but nothing persists it. | Add an `episode_end_states` table (JSONB, versioned, approved at episode completion). |
| D6 | 🟠 | Approval gates (§44) have no storage: who approved what, when, and which version. | Add an `approvals(subject_type, subject_id, subject_version, gate, decision, user_id, comment, created_at)` table. |
| D7 | 🟠 | "Do not replace approved references; create versions" (§13) has no versioning model. | Use immutable `assets` rows with `parent_asset_id` / `supersedes_id`. The reference row points at a specific asset version. |
| D8 | 🟠 | `generation_jobs` (queue concern) vs `generation_attempts` (domain concern): the relationship and idempotency key are undefined. | One job produces one or more attempts. Jobs carry an `idempotency_key`. Attempts are append-only. See ADR-003. |
| D9 | 🟡 | `characters.gender` / `age` are free text with no validation or guidance. | Keep them free text, but document that they feed the prompt builder. Consider `apparent_age` wording. |
| D10 | 🟡 | Timeline/EDL (§29) exists only as a JSON file, with no table. | Add a `timelines` table (JSONB EDL, version, episode_id). Export to file on render. |
| D11 | 🟡 | Subtitles have no source of truth: are they generated from dialogue or from ASR of the rendered audio? | Generate from `shots.dialogue` + TTS timing, with optional local ASR alignment. |
| D12 | 🟡 | Voices (§28) are not linked to characters. | Add `characters.voice_id` FK. |

---

## 5. AI-engineering review

### 5.1 Hardware reality on GB10 🔴

- **Memory bandwidth, not capacity, is the bottleneck.** GB10 LPDDR5x is roughly 273 GB/s **[VERIFY]**, which is several times less than datacenter HBM. A 22B-parameter video DiT will fit, but it will be **slow** per step. Treat per-shot generation times as unknown until benchmarked (§80 already says this, and it matters more than the spec implies).
- **Throughput budget for the production acceptance test (§70):** 80+ shots × (keyframe + video + QC) × expected regenerations (say 1.5–2×) × two-stage upscale. If one 1080p production shot takes *T* minutes, one episode takes ≈ 80 × 2 × *T*. At *T* = 10 min that is ~27 GPU-hours per episode. **Add a benchmark task in Phase 4 and set a throughput NFR from the result** before committing to the §70 test as written.
- **Co-residency:** the 128 GB is shared by the OS, Postgres, MinIO, the LLM server, the video DiT, its text encoder, the VAE, upscalers and QC models. A large local LLM (e.g. a 70B at 4-bit ≈ 40 GB) **plus** the video stack will probably not fit together. The GPU scheduler must treat the **LLM as a GPU tenant**, unloading it before video jobs or pinning a small planner model. See ADR-005.
- **Software stack:** GB10 is a new Blackwell variant (compute capability reported as 12.1 / sm_121 **[VERIFY]**). Generic PyTorch aarch64 wheels may not include kernels for it. **Base GPU images on NVIDIA NGC containers (`nvcr.io/nvidia/pytorch`) built for arm64/DGX OS.** Validate FP8/NVFP4 paths, attention kernels (FlashAttention/SageAttention) and xformers individually. Any that fail must be marked unsupported, never emulated.
- **Determinism:** "Regenerate with same seed" (§26) will **not** be bit-reproducible on GPUs with non-deterministic kernels. Promise "same seed + same inputs = near-identical", and record the torch/CUDA/driver versions in the attempt so any drift can be explained.

### 5.2 Model and license review 🔴

The spec correctly requires a license registry (§51). The actual candidates show why:

| Candidate | Role | Concern **[VERIFY every row against upstream at integration time]** |
|---|---|---|
| LTX-2.x (Lightricks) | Primary video | Distributed under an LTX community/open-weights license. Commercial terms may depend on company revenue thresholds. Legal must read the exact current license. |
| HunyuanVideo 1.5 (Tencent) | Secondary video | Tencent Hunyuan community licenses have historically **excluded the EU, UK and South Korea** and capped MAU. This can block deployment depending on company location. |
| Wan 2.x (Alibaba) | Alternative video | Generally Apache-2.0. Probably the least restrictive fallback. |
| FLUX.1-dev | Keyframe/image | **Non-commercial** license. FLUX.1-schnell / Qwen-Image-class models are more permissive alternatives. |
| InsightFace / ArcFace pretrained models | Face-identity QC | Pretrained InsightFace model packs are **non-commercial research only**. Character-identity QC needs a commercially licensed face-embedding model or an internally trained one. |
| TTS (XTTS, F5, Kokoro, etc.) | Voice | Licenses vary widely (CPML, CC-BY-NC, Apache). Voice cloning adds consent obligations. |

**Action:** the model registry must block `approved_for_production=true` unless a `model_licenses` row exists with `commercial_use_allowed` explicitly set by an admin. This ships in M16, before any provider module.

### 5.3 Consistency strategy 🟠

- The priority order in §59 is sound. In practice, **identity preservation in LTX-class image-to-video depends mostly on the conditioning keyframe**. That makes the **keyframe image model** (with reference/identity conditioning, e.g. IP-Adapter/PuLID-class or an edit model) the real consistency lever, not the video model. The spec leaves the image provider as "pluggable" and never selects one. **Selecting and benchmarking the keyframe/identity model is on the MVP critical path** (ADR-008).
- **Previous-frame chaining** (§23) causes compounding drift and quality loss over long chains, because each generation inherits the previous one's artifacts. Use the previous frame for **continuity within a scene only**. Re-anchor every shot to the approved references, and never chain across scene boundaries.
- **LoRA training on GB10:** training a 22B video LoRA on this hardware is unverified and likely slow. Keep it in Phase 7 as planned and benchmark it before promising a turnaround time.

### 5.4 QC engine 🟠

- The thresholds in §63 (0.85 / 0.80 / 0.95) compare **incomparable metrics**. Cosine similarity from a face model, CLIP-score-style adherence and a motion-quality heuristic have different distributions. The spec already says "not scientifically universal". Go further and require a **calibration set**: 50–100 human-labelled shots from the MVP, with thresholds chosen per metric from the ROC curves. Keep failed generations (§25) partly for this.
- Define concretely what each score is. Proposal (subject to license check):
  - `character_score`: face-embedding similarity (per-frame, sampled; aggregate = p10 not mean, so a few bad frames fail the shot) + optional body/costume similarity via a general image embedding.
  - `environment_score`: image-embedding similarity to approved environment references on sampled frames.
  - `prompt_adherence_score`: local VLM judgement against the structured shot spec (not the flattened prompt), with a rubric.
  - `motion_score`: optical-flow statistics (jitter, warping, temporal flicker) + frame-difference anomalies.
  - `artifact_score` / `technical_score`: resolution, fps, duration, black/frozen frames, audio presence, codec validity via ffprobe. These are deterministic and cheap, so run them first.
- **"Rewrite prompt and regenerate" (§64)** conflicts with the "deterministic prompt builder" (§22). Resolution: the automatic rewrite modifies **structured shot fields** (or adds a bounded `prompt_overrides` section) through the LLM, producing a new prompt version. It never edits free text directly.

### 5.5 LLM / AI Director 🟠

- Local models are much less reliable than frontier APIs at emitting large, valid, nested JSON. Require **schema-constrained decoding** (JSON-schema / grammar mode, supported by Ollama, llama.cpp and vLLM), Pydantic validation, bounded retries with validator feedback, and **hierarchical generation** (outline → scenes → shots per scene) rather than one 80-shot response.
- **Prompt injection:** uploaded scripts are untrusted input to the LLM. The spec already forbids shell execution (§10). Also treat every LLM output as untrusted data, validate it against the schema, and never let it choose tool calls outside the allowed set.
- Record the LLM model, version, prompt template version and raw response on every planning job. This extends provenance to planning, not just rendering.

---

## 6. Software-engineering review

| # | Sev | Finding | Recommendation |
|---|---|---|---|
| S1 | 🔴 | **Job system undecided** (§5), and "Redis as broker" (§32) conflicts with "idempotent jobs + never corrupt state" (§71, §82). Celery's model (prefork, ack semantics, visibility timeouts) is a poor fit for 10-minute GPU jobs and asyncio code. | ADR-003: **Postgres is the job source of truth** (`generation_jobs` with status, lease, heartbeat, idempotency key). Redis is used only for wake-up signalling and pub/sub → WebSocket. A worker crash lets the lease expire, and the job is re-queued safely. |
| S2 | 🔴 | **Two GPU execution paths** (native LTX pipelines and ComfyUI) double the MVP integration work. | ADR-004: pick **one** path for the MVP. Recommendation: native Python pipelines in `ai-engine` behind the provider interface, with workflow = a versioned JSON "recipe" of pipeline + params. Add ComfyUI after the MVP as an alternative backend. The team may choose the reverse; either works, but only one before the MVP. |
| S3 | 🟠 | **Development machine ≠ target.** Development happens on Windows/x86, but the target is ARM64 + GB10. §82 forbids fake generators outside tests. | Split the system into a **control plane** (API, DB, UI, scheduler), which runs anywhere, and a **GPU plane** (`ai-engine`), which runs only on the GX10. On dev machines the providers report `UNAVAILABLE`. That is honest and satisfies §82. Contract tests use fakes. Hardware tests carry the `@pytest.mark.gx10` marker and run on the device. |
| S4 | 🟠 | **CI has no GB10.** | CI runs lint, type-check, unit/API/worker tests with fakes, and an arm64 buildx image build. A self-hosted runner on the GX10 (or a manual `make gx10-test`) runs the `gx10` marker suite. |
| S5 | 🟠 | Python version: the backend targets 3.12/3.13, but the `ai-engine` Python is **dictated by the NGC PyTorch image**. | Keep the backend and ai-engine as separate packages with separate lockfiles. They share only a small `contracts` package (Pydantic models for job payloads/results). |
| S6 | 🟠 | Asset delivery: "signed URLs" (§65) + private MinIO + nginx auth. If URLs are presigned MinIO URLs, clients need a route to MinIO. | Route through nginx `/media/` with `auth_request` to the API, or API-issued short-TTL HMAC tokens that nginx validates. MinIO is never reachable directly. |
| S7 | 🟠 | "Regenerate only failed section" (§26) depends on the provider (retake/extend/v2v). | Expose it through `capabilities()`. Hide the UI button when the provider does not support it. |
| S8 | 🟡 | The spec asks for a timeline editor UI (§5, §41) without defining its scope. A full NLE is a product by itself. | MVP: an ordered shot list with trim in/out and a preview. Phase 9: a multi-track timeline (evaluate an existing React timeline lib). |
| S9 | 🟡 | 4K rendering "if supported" (§29) is unclear: native 4K generation, or an upscale? | Treat 4K as an upscaler output only. Native generation stays at the model's supported resolutions. |
| S10 | 🟡 | pgvector: embedding dimensions differ per model (e.g. 512 vs 768 vs 1024). | Store `embedding_model` + `dim`. Use a separate HNSW index per (model) via partial indexes, or one table per embedding family. |

---

## 7. Missing requirements (add to spec)

| # | Sev | Missing | Proposed requirement |
|---|---|---|---|
| M1 | 🔴 | **Likeness & consent.** Uploaded reference photos and voice samples may depict real people. | `characters.is_real_person_likeness`, a consent record (`consent_asset_id`, signer, scope, expiry) required before approval. Block voice cloning without consent. Document this in `docs/security.md`. |
| M2 | 🟠 | **AI-content provenance.** | Optional C2PA manifest / visible or invisible watermark on final renders. Configurable per project. |
| M3 | 🟠 | **NFRs.** No targets for latency, throughput, concurrent users, uptime, or RPO/RTO. | Set them after the Phase 4 benchmark. Placeholder: ≤ 10 users, RPO 24h, RTO 4h, MAX_CONCURRENT_VIDEO_JOBS = 1. |
| M4 | 🟠 | **Retention & storage growth.** Keeping every failed attempt (§25) plus multi-stage intermediates grows storage without bound. | Retention policy: keep the metadata of failed attempts forever, and keep their media for N days (configurable). Add a storage dashboard and disk-pressure alerts. |
| M5 | 🟠 | **Offline model provisioning.** §73 assumes that weights, pip packages and container images are pre-fetched. | A `scripts/models/fetch.py` that pins repo + revision + SHA256 (§50) and supports an offline bundle (tarball) for air-gapped installs. Set `HF_HUB_OFFLINE=1` at runtime. |
| M6 | 🟡 | **Session auth details.** JWT access/refresh lifetimes, revocation and password policy are not defined. | Short-lived access token + rotating refresh token in an httpOnly cookie. Local accounts first. OIDC is optional later. |
| M7 | 🟡 | **Frame rate / aspect ratio** per project are never defined. | Add `projects.fps`, `projects.aspect_ratio`, `projects.default_profile`. The prompt/workflow builders read these. |
| M8 | 🟡 | **Cancellation semantics** for in-flight GPU jobs. | Cooperative cancellation between diffusion steps. Mark the attempt `CANCELLED` and keep the partial logs. |

---

## 8. Scope and phasing

The spec's phase order (§81) is good. Three adjustments:

1. **Phase 0 (new): Foundations & de-risking.** Repo, ADRs, CI, and **GX10 bring-up spike**: verify NGC PyTorch on GB10, run LTX-2.3 image-to-video once, and record time and peak memory. This spike decides the viability of everything else and should happen **in parallel with Phase 1**, not in Phase 4.
2. **Move the keyframe/image provider into Phase 4** (it is on the MVP path, §68), plus the model license registry (§51).
3. **Pull minimal auth into Phase 1.** A single admin user with JWT is enough. RBAC can wait until Phase 10, but an unauthenticated API holding company assets should not exist even on a LAN.

The MVP = Phases 0–6, gated by the §69 acceptance test. See [`../MODULES.md`](../MODULES.md) for the module-to-phase map and [`../../status/status.toml`](../../status/status.toml) for tracking.

---

## 9. Open questions for the product owner

| # | Question | Answer (2026-09-29) |
|---|---|---|
| 1 | **Deployment/legal:** where will the platform be used, and what is the company's revenue band (this decides LTX/Hunyuan eligibility)? | Private office network. **Revenue band still open**: internal use is still commercial use, so the model licenses must be checked (M16). See ADR-012. |
| 2 | **Content:** will real people's likenesses or voices be used? Who consents? | Yes, **employees**. Consent records are mandatory, consent can be withdrawn, and the data is sensitive. See ADR-012. |
| 3 | **Team / GX10 access:** who does bring-up? | The product owner deploys to the GX10 and runs the P0 spike. **Team size still open.** |
| 4 | **Throughput expectation:** finished minutes per week? | **Open.** Set it after the P0 benchmark. |
| 5 | **Local LLM preference / license?** | **Open.** |
| 6 | **Execution backend for the MVP?** | Native pipelines at first (ADR-004). **Changed 2026-09-30 to ComfyUI-first (ADR-013)** after we learned that working ComfyUI graphs already exist on the GX10. |
