# Private AI Video Production Platform — Original Specification (v0)

> **Status:** Frozen source input. Do not edit. Amendments live in
> [`../review/01-specification-review.md`](../review/01-specification-review.md) and
> [`../DECISIONS.md`](../DECISIONS.md). Section numbers (§N) are referenced throughout the repo.

---

# Private AI Video Production Platform

## Production Architecture & Implementation Specification

### Target Hardware: ASUS Ascent GX10 — NVIDIA GB10 — 128 GB Unified Memory

---

# 1. Executive Objective

Build a fully self-hosted AI video production platform capable of creating multi-scene and multi-episode videos while maintaining consistent:

* characters
* faces
* body characteristics
* clothing
* environments
* locations
* props
* visual style
* camera language
* story continuity
* voice identity
* audio style
* episode continuity

The system must operate primarily on-premises.

Company data, uploaded images, scripts, generated assets, character references, environments, prompts, videos, audio and project information must never be sent to external AI APIs unless an administrator explicitly enables an external provider.

The platform must be designed so that future video models can be added without rewriting the application.

The first production target is the ASUS Ascent GX10.

---

# 2. Hardware Assumptions

Target machine:

* ASUS Ascent GX10
* NVIDIA GB10 Blackwell GPU
* 128 GB unified LPDDR5x memory
* 20-core ARM CPU
* NVIDIA DGX OS
* 10 GbE
* NVMe storage

The application must be ARM64 compatible.

Do not assume x86_64 Docker images.

Every container image used for GPU workloads must be verified for ARM64 compatibility.

The system must detect:

* architecture
* NVIDIA driver
* CUDA version
* available unified memory
* GPU compute capability
* disk capacity
* disk utilization
* model availability

At application startup expose a:

GET /api/system/capabilities

endpoint returning:

```json
{
"architecture": "aarch64",
"gpu": "NVIDIA GB10",
"memory_gb": 128,
"cuda_available": true,
"models_available": [],
"storage_available_gb": 0
}
```

---

# 3. Important Architecture Principle

Do NOT implement the platform as:

User -> LLM -> Video

Implement:

User → AI Director → Story Bible → Character Bible → Environment Bible → Scene Planner → Shot Planner → Reference Manager → Keyframe Generation → Video Generation → Consistency Validation → Regeneration → Audio → Editing → Final Render

The LLM is the director/orchestrator.

The video models are rendering engines.

---

# 4. High-Level Architecture

```
                ┌───────────────────────────────┐
                │          Web Portal            │
                │ React + TypeScript             │
                └───────────────┬───────────────┘
                                │
                                ▼
                ┌───────────────────────────────┐
                │          API Gateway           │
                │ FastAPI                       │
                └───────────────┬───────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
              ▼                 ▼                 ▼
         Project API       AI Director       Asset API
              │                 │                 │
              └─────────────────┼─────────────────┘
                                │
                                ▼
                     ┌────────────────────┐
                     │ Workflow Engine    │
                     │ Python             │
                     └─────────┬──────────┘
                               │
                               ▼
                     ┌────────────────────┐
                     │ Job Queue          │
                     │ Redis              │
                     └─────────┬──────────┘
                               │
          ┌────────────────────┼─────────────────────┐
          │                    │                     │
          ▼                    ▼                     ▼
   Image Worker          Video Worker          Audio Worker
          │                    │                     │
          ▼                    ▼                     ▼
   Image Models             LTX/Wan             TTS/SFX
          │                    │
          └────────────────────┼─────────────────────┘
                               ▼
                       Consistency Engine
                               │
                               ▼
                         Render Pipeline
                               │
                               ▼
                            FFmpeg
                               │
                               ▼
                         Final Video
```

---

# 5. Recommended Technology Stack

## Backend

Python 3.12 or 3.13. FastAPI. Pydantic. SQLAlchemy. Alembic. Redis. Celery or custom asyncio worker orchestration. FFmpeg. OpenCV. PyTorch. CUDA.

## Frontend

React. TypeScript. Vite. TailwindCSS. React Query. WebSocket support. Timeline editor.

## Database

PostgreSQL. Use PostgreSQL as the authoritative metadata database. Do not store large video files inside PostgreSQL.

## Object Storage

MinIO. Use S3-compatible storage.

Store: images, videos, audio, models metadata, LoRAs, thumbnails, keyframes, final renders.

## Vector Search

Start with PostgreSQL + pgvector. Do not introduce a separate vector database unless scale requires it.

Use vectors for: character reference retrieval, environment retrieval, visual asset retrieval, prompt retrieval, scene retrieval.

## AI Orchestration

Create an internal abstraction: AIProvider

Implement: LocalLLMProvider, OptionalExternalLLMProvider

The default provider must be LocalLLMProvider.

---

# 6. Model Abstraction

Never hard-code LTX throughout the application.

Create: class VideoGenerationProvider

with:

generate_text_to_video(), generate_image_to_video(), generate_video_to_video(), generate_first_last_frame(), extend_video(), retake_video(), upscale_video(), estimate_resources(), health_check()

Then implement: LTXProvider, WanProvider, HunyuanProvider, FutureProvider

The application should select a provider based on: requested operation, resolution, duration, available memory, quality profile, project configuration.

---

# 7. Primary Video Engine

Primary engine: LTX-2.x. Implement LTX-2.3 first. Keep the architecture ready for LTX-2.5.

LTX-2.3 official model assets include: 22B development checkpoint, 22B distilled checkpoint, spatial upscalers, temporal upscaler, distilled LoRA, IC-LoRA control models.

The official LTX repository also provides production-oriented DFR pipelines and LoRA training infrastructure.

Use the official Lightricks repositories.

Do not use unofficial model mirrors unless explicitly configured by the administrator.

---

# 8. ComfyUI Integration

Use ComfyUI as an optional execution backend rather than making it the business application.

Architecture: Application → Workflow Manager → ComfyUI API → ComfyUI Workflow → Model → Generated Asset

Store every workflow JSON used to produce an asset.

Database: generation_workflows — Fields: id, name, model_provider, model_version, workflow_json, created_at, updated_at

Every generated asset must reference the workflow used to create it. This provides reproducibility.

---

# 9. Local LLM

Implement LocalLLMProvider.

Recommended initial architecture: LLM Server → OpenAI-compatible API → AI Director

The exact local LLM must be configurable. Do not hard-code one LLM.

Support: Ollama, llama.cpp-compatible API, vLLM where supported by hardware, future local inference engines.

Configuration: LOCAL_LLM_BASE_URL, LOCAL_LLM_MODEL, LOCAL_LLM_TIMEOUT, LOCAL_LLM_MAX_TOKENS

The application must continue functioning if the external internet is unavailable.

---

# 10. AI Director

Create: /services/ai_director/

Modules: story_director.py, character_director.py, environment_director.py, scene_director.py, shot_director.py, continuity_director.py, prompt_director.py

Responsibilities: Convert user instructions into structured production data.

Example — User: "Create a 10-minute episode where Daniel discovers a hidden document in his office."

AI Director produces: Episode → Scenes → Shots → Character requirements → Environment requirements → Props → Camera instructions → Dialogue → Audio requirements

Never allow the LLM to directly execute arbitrary shell commands.

All generated actions must pass through typed application APIs.

---

# 11. Story Bible

Create: story_bibles — Fields: id, project_id, title, description, genre, visual_style, tone, world_rules, timeline_rules, continuity_rules, created_at, updated_at

A project must have one active Story Bible.

The Story Bible is injected into scene planning.

---

# 12. Character Bible

Create: characters — Fields: id, project_id, name, description, age, gender, appearance, body_description, face_description, hair_description, skin_description, personality, default_costume, visual_style, status, created_at, updated_at

Create: character_references — Fields: id, character_id, asset_id, reference_type, view, expression, quality_score, embedding, approved

Reference types: front, side, back, three_quarter, full_body, closeup, expression, action, costume

---

# 13. Character Identity Pipeline

The character pipeline must support:

1. Character creation.
2. Reference image generation/upload.
3. Human approval.
4. Reference embedding.
5. Optional LoRA training.
6. LoRA versioning.
7. Character consistency validation.

Directory: assets/characters/{character_id}/

Example:

```
characters/
  daniel/
    references/
    approved/
    rejected/
    lora/
    embeddings/
    metadata.json
```

Do not automatically replace an approved character reference. Create versions instead.

---

# 14. LoRA System

Implement: loras — Fields: id, project_id, character_id, name, version, base_model, model_path, training_dataset, training_config, status, quality_score, created_at

Training states: QUEUED, PREPARING, TRAINING, VALIDATING, APPROVED, FAILED, ARCHIVED

The user must be able to select — Character: Daniel; LoRA: Daniel_v3; Strength: 0.75

The strength must be configurable.

---

# 15. Environment Bible

Create: environments — Fields: id, project_id, name, description, architecture, lighting, color_palette, permanent_objects, time_of_day, weather, visual_style, status

Create: environment_references — Fields: id, environment_id, asset_id, view, time_of_day, weather, embedding, quality_score, approved

Examples: office_front, office_wide, office_left, office_right, office_desk, office_night

---

# 16. Props

Create: props — Fields: id, project_id, name, description, appearance, dimensions, color, materials, reference_asset_id, embedding, status

Props must be reusable across scenes.

Examples: laptop, phone, vehicle, document, watch, coffee cup

---

# 17. Costume System

Create: costumes — Fields: id, character_id, name, description, shirt, trousers, shoes, accessories, reference_asset_id, created_at

A scene must explicitly reference the costume. This prevents clothing drift.

---

# 18. Episode Model

Create: episodes — Fields: id, project_id, episode_number, title, synopsis, script, status, duration_target, created_at, updated_at

Statuses: DRAFT, PLANNED, GENERATING, QC, RENDERING, COMPLETED, FAILED

---

# 19. Scene Model

Create: scenes — Fields: id, episode_id, scene_number, title, location_id, time_of_day, weather, characters, props, costumes, description, continuity_notes, duration_target, status

---

# 20. Shot Model

Create: shots — Fields: id, scene_id, shot_number, duration, shot_type, camera, lens, movement, composition, lighting, action, dialogue, sound, character_ids, environment_id, prop_ids, costume_ids, reference_asset_ids, prompt, negative_prompt, seed, generation_provider, generation_model, workflow_id, status

Shot types: EXTREME_WIDE, WIDE, MEDIUM, MEDIUM_CLOSEUP, CLOSEUP, EXTREME_CLOSEUP, OVER_SHOULDER, POV, INSERT

Camera movements: STATIC, PAN, TILT, DOLLY, TRACKING, CRANE, HANDHELD, ORBIT

---

# 21. Keyframe-First Workflow

Do not immediately generate final video.

Pipeline: Shot → Generate keyframe → Human/AI QC → Approved keyframe → Image-to-video → Video QC

For difficult scenes: Shot → Generate first frame → Generate last frame → Video generation → Validate transition

Store: first_frame_asset_id, last_frame_asset_id

---

# 22. Prompt Engine

Create a deterministic prompt builder.

Prompt sections: CHARACTER, COSTUME, ENVIRONMENT, ACTION, CAMERA, LIGHTING, COMPOSITION, MOTION, STYLE, CONTINUITY

Example generated prompt:

"Daniel, a 32-year-old African man with dark brown skin, short black hair, short trimmed beard and a small scar above his left eyebrow, wearing the approved dark-blue shirt and black trousers, walks slowly into the established modern office. The wooden desk, black office chair, bookshelf and desk lamp remain in their established positions. Medium tracking shot, camera moves backward smoothly as Daniel approaches the desk. Natural warm daylight enters through the large window. Cinematic realistic photography, physically plausible movement, natural facial motion."

The prompt engine must build this from structured metadata.

Do not allow users to manually maintain giant prompts for every shot.

---

# 23. Visual Reference Retrieval

Before generating every shot retrieve: character references, environment references, costume references, prop references, previous shot last frame.

Use embeddings to retrieve the most relevant approved assets.

Example — Shot: Daniel enters office. Retrieve: Daniel front reference, Daniel full-body reference, Daniel approved costume, Office wide reference, Office entrance reference, Previous shot final frame.

Pass these into the video workflow.

---

# 24. Continuity Engine

Create: /services/continuity/

Validate: character identity, costume continuity, location continuity, prop continuity, time-of-day continuity, weather continuity, story continuity

Example — Scene 1: Daniel wearing blue shirt. Scene 2: same day. If Scene 2 specifies red shirt, continuity engine returns:

CONTINUITY_ERROR — "Daniel's costume changed from blue shirt to red shirt without a wardrobe event."

The user must be able to override this explicitly.

---

# 25. Video Consistency QC

Every generated shot gets a QC record.

Create: quality_checks — Fields: id, asset_id, character_score, environment_score, prompt_adherence_score, motion_score, artifact_score, technical_score, overall_score, status, details, created_at

Statuses: PASS, REVIEW, FAIL

Do not automatically delete failed generations. Keep them for debugging and auditing.

---

# 26. Regeneration

Every shot must support: Regenerate; Regenerate with same seed; Regenerate with new seed; Regenerate with stronger character reference; Regenerate with different model; Regenerate with modified prompt; Regenerate only failed section

---

# 27. Audio Architecture

Separate audio generation from video generation.

Components: TTSProvider, VoiceProvider, MusicProvider, SFXProvider

All providers must have interfaces.

Example: VoiceProvider.generate(text, voice_id, emotion, speed)

Store audio assets independently.

---

# 28. Voice Identity

Create: voices — Fields: id, project_id, name, description, provider, model, voice_reference, status

Never send voice data to an external service unless explicitly enabled. The default must be local.

---

# 29. Final Editing

Use FFmpeg. The application must generate an edit decision list.

Example: episode_001_timeline.json contains: shot_id, start_time, end_time, transition, audio_tracks, music, dialogue, sfx, subtitles

Then render: preview, 1080p, 4K if supported

---

# 30. Storage Architecture

Use: /data, /data/projects, /data/assets, /data/models, /data/cache, /data/renders, /data/logs, /data/temp

But production application metadata must be in PostgreSQL. Use MinIO for persistent media.

Example buckets: ai-video-assets, ai-video-models, ai-video-renders, ai-video-projects, ai-video-backups

---

# 31. Database Architecture

PostgreSQL tables: users, projects, project_members, story_bibles, characters, character_references, character_loras, environments, environment_references, props, costumes, voices, episodes, scenes, shots, assets, asset_embeddings, generation_jobs, generation_attempts, quality_checks, generation_workflows, model_registry, render_jobs, audit_logs, system_settings

---

# 32. Job Architecture

Redis is the queue broker.

Jobs: PLAN_EPISODE, PLAN_SCENE, PLAN_SHOT, GENERATE_IMAGE, GENERATE_KEYFRAME, GENERATE_VIDEO, GENERATE_AUDIO, UPSCALE_VIDEO, QUALITY_CHECK, REGENERATE, RENDER_EPISODE, CREATE_THUMBNAIL, CREATE_EMBEDDING, TRAIN_LORA

Every job has: id, type, priority, status, progress, attempt, worker, started_at, completed_at, error

---

# 33. GPU Scheduler

Do not let arbitrary workers consume the GPU.

Create: GPUScheduler. States: IDLE, LOADING_MODEL, GENERATING, OFFLOADING, ERROR

Jobs request: estimated_memory, model, resolution, duration, priority

Scheduler decides when the job runs.

Because the GX10 has 128 GB unified memory, the system should dynamically choose model loading/offloading strategies instead of assuming fixed VRAM.

---

# 34. Model Registry

Create: model_registry

Example:

```json
{
"name": "LTX-2.3",
"provider": "ltx",
"version": "2.3",
"type": "video",
"capabilities": ["t2v", "i2v", "v2v", "first_last_frame"],
"memory_profile": {},
"installed": true
}
```

The UI should display: Installed, Not installed, Downloading, Unavailable, Incompatible

---

# 35. Hardware Capability Detection

At startup run nvidia-smi and relevant NVIDIA/CUDA/PyTorch capability checks.

Also detect uname -m. Expected: aarch64

Expose: /api/system/hardware

The UI should display: GX10, GB10, 128 GB Unified Memory, CUDA status, PyTorch status, Model availability, Storage, Queue status

---

# 36. Docker Architecture

Use Docker Compose initially.

Services: frontend, backend, worker, scheduler, postgres, redis, minio, comfyui, nginx

Do NOT force every AI model into a separate container if GPU memory duplication makes it inefficient.

Prefer: one GPU execution service with model adapters.

Example services: frontend, api, worker, scheduler, postgres, redis, minio, ai-engine, nginx

The ai-engine hosts the active model execution environment.

---

# 37. ARM64 Requirement

All Dockerfiles must explicitly support linux/arm64. Do not blindly use linux/amd64.

If an upstream AI image is x86-only: DO NOT silently emulate it. Report: "Model unavailable on native GX10 ARM64 environment." Then provide an alternative implementation.

---

# 38. External Network Policy

Create: NETWORK_MODE=offline. Default: offline

Allowed external network destinations should be configurable.

The application must not call OpenAI, Google, Anthropic, LTX API, fal.ai, Replicate, or any other cloud AI service unless explicitly configured.

---

# 39. Security

Implement: JWT authentication. RBAC.

Roles: ADMIN, PROJECT_ADMIN, CREATOR, REVIEWER, VIEWER

Permissions: project:create, project:edit, project:view, character:create, character:approve, generation:create, generation:cancel, asset:view, asset:delete, model:manage, system:admin

---

# 40. Audit Logging

Every generation must record: user, project, episode, scene, shot, model, model_version, LoRA, LoRA strength, prompt, negative prompt, seed, references, workflow, timestamp, hardware, result, QC result

This makes the system reproducible.

---

# 41. UI

## Dashboard
Display: Projects, Active generations, GPU utilization, Queue, Completed episodes

## Project
Tabs: Overview, Story Bible, Characters, Environments, Props, Costumes, Episodes, Assets, Models, Settings

## Character Studio
Display: Character reference sheet, Face, Full body, Expressions, Costumes, LoRAs
Actions: Generate references, Upload references, Approve, Train LoRA, Test character, Compare versions

## Environment Studio
Display: Environment references. Actions: Generate, Upload, Approve, Version

## Episode Studio
Timeline: Scene 1, Scene 2, Scene 3. Each scene contains: Shot 1, Shot 2, Shot 3

## Shot Studio
Show: Prompt, References, Keyframe, Video, QC, Generation history
Buttons: Generate keyframe, Generate video, Regenerate, Approve, Reject

## Render Studio
Show: timeline, video preview, audio, subtitles, export settings

---

# 42. Project Creation Workflow

Step 1: Project name. Step 2: Visual style. Step 3: Create Story Bible. Step 4: Create characters. Step 5: Create environments. Step 6: Create props. Step 7: Create costumes. Step 8: Create first episode.

---

# 43. Episode Creation Workflow

User enters: "Create Episode 1."

System:

1. Loads Story Bible.
2. Loads character definitions.
3. Loads environment definitions.
4. Loads continuity history.
5. Generates episode outline.
6. User approves outline.
7. Generates scenes.
8. User approves scenes.
9. Generates shots.
10. User approves shot plan.
11. Generates keyframes.
12. QC.
13. Generates video.
14. QC.
15. Regenerates failures.
16. Generates audio.
17. Creates edit.
18. Renders preview.
19. User approves.
20. Renders final.

Do not generate an entire episode without checkpoints.

---

# 44. Human Approval Gates

Required approval gates: STORY_APPROVAL, SCENE_APPROVAL, SHOT_APPROVAL, KEYFRAME_APPROVAL, FINAL_VIDEO_APPROVAL

Allow administrators to disable intermediate approvals for automated production.

---

# 45. API Structure

/api/v1/auth, /api/v1/projects, /api/v1/projects/{id}/story, /api/v1/projects/{id}/characters, /api/v1/projects/{id}/environments, /api/v1/projects/{id}/props, /api/v1/projects/{id}/costumes, /api/v1/projects/{id}/episodes, /api/v1/scenes, /api/v1/shots, /api/v1/assets, /api/v1/generation, /api/v1/models, /api/v1/workflows, /api/v1/qc, /api/v1/render, /api/v1/system

---

# 46. WebSocket Events

Implement: /ws/projects/{project_id}

Events: generation.started, generation.progress, generation.completed, generation.failed, qc.started, qc.completed, render.started, render.progress, render.completed, worker.connected, worker.disconnected

---

# 47. API Example

POST /api/v1/shots/{shot_id}/generate

Request:

```json
{
"provider": "ltx",
"model": "ltx-2.3",
"mode": "image_to_video",
"duration": 6,
"resolution": "1080p",
"seed": 12345,
"character_lora": "daniel-v3",
"character_lora_strength": 0.75,
"use_previous_frame": true
}
```

Response:

```json
{
"job_id": "job_123",
"status": "queued"
}
```

---

# 48. Prompt Versioning

Never overwrite prompts. Every prompt must be versioned.

prompt_versions: id, shot_id, version, prompt, negative_prompt, created_by, created_at

Allow comparison: v1, v2, v3

---

# 49. Generation Versioning

Every regeneration creates a new generation attempt.

Example — Shot 17: Generation 1 FAIL; Generation 2 FAIL; Generation 3 PASS

Never overwrite generation 1.

---

# 50. Backup

Backup: PostgreSQL, MinIO metadata, project configuration, character metadata, environment metadata, LoRA metadata, workflow JSON

Model weights should not necessarily be backed up if they can be reproducibly downloaded from approved repositories.

However, record exact: repository, revision, SHA256 for every model.

---

# 51. Model License Registry

Create: model_licenses

Every model must have: name, version, source, license, commercial_use_allowed, redistribution_allowed, requires_attribution, notes

The administrator must approve a model before it becomes available to production users.

Do not assume that "open source" automatically means unrestricted commercial use.

---

# 52. Observability

Use: Prometheus, Grafana, Structured JSON logging.

Metrics: generation_count, generation_failure_count, generation_duration, queue_depth, gpu_memory, gpu_utilization, system_memory, disk_usage, model_load_time, qc_failure_rate, regeneration_rate

---

# 53. Health Endpoints

GET /health, /health/database, /health/redis, /health/minio, /health/gpu, /health/models, /health/comfyui

---

# 54. Development Environment

Repository: ai-video-platform/

```
ai-video-platform/
  backend/
    app/
      api/ core/ db/ models/ schemas/ services/ workers/ providers/
      ai_director/ continuity/ generation/ qc/ rendering/
    tests/
  frontend/
    src/
      components/ pages/ features/ hooks/ api/ stores/
  ai-engine/
    ltx/ comfyui/ wan/ hunyuan/ common/
  workflows/
    ltx/ wan/ hunyuan/
  infra/
    docker/ nginx/ postgres/ redis/ minio/ monitoring/
  scripts/
    setup/ health/ models/
  docs/
```

---

# 55. Configuration

Create: .env.example

```
APP_ENV=production
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...
LOCAL_LLM_BASE_URL=http://llm:11434
LOCAL_LLM_MODEL=...
COMFYUI_URL=http://ai-engine:8188
DEFAULT_VIDEO_PROVIDER=ltx
DEFAULT_VIDEO_MODEL=ltx-2.3
NETWORK_MODE=offline
ENABLE_EXTERNAL_APIS=false
MAX_CONCURRENT_VIDEO_JOBS=1
DEFAULT_VIDEO_RESOLUTION=1080p
DEFAULT_VIDEO_DURATION=6
```

---

# 56. Do Not Assume Concurrent Video Generation

Initial GX10 configuration: MAX_CONCURRENT_VIDEO_JOBS=1

The GPU scheduler should be capable of increasing this later.

Do not sacrifice generation quality simply to maximize concurrency.

---

# 57. Performance Profiles

## Draft
Fast generation. Low resolution. Minimal steps. Used for storyboarding.

## Preview
Medium quality. 1080p target. Used for review.

## Production
Highest supported quality. Multi-stage generation. Upscaling. Maximum consistency controls.

## Final
Production profile plus: audio, subtitles, color processing, final rendering

---

# 58. Two-Stage Production

For production shots:

Stage 1: Generate low-resolution/initial result.
Stage 2: Spatial enhancement/upscaling.
Stage 3: Optional temporal enhancement.
Stage 4: Final encoding.

Never use the expensive final workflow while the user is still experimenting with the shot.

---

# 59. Character Consistency Strategy

Priority order:

1. Approved character reference.
2. Previous frame.
3. Character LoRA.
4. Costume reference.
5. Prompt description.
6. Seed.

The prompt alone is NOT considered sufficient for character consistency.

---

# 60. Environment Consistency Strategy

Priority:

1. Approved environment reference.
2. Previous frame.
3. Environment reference retrieval.
4. Scene metadata.
5. Prompt.

---

# 61. Multi-Episode Continuity

Before generating Episode N: retrieve Episode N-1 final state.

Generate: continuity_context.json

Example:

```json
{
"character_state": {
  "daniel": {
    "location": "office",
    "costume": "blue_shirt_v2",
    "props": ["phone_01"]
  }
},
"story_state": {
  "document_found": true,
  "relationship_with_sarah": "suspicious"
}
}
```

Inject this into Episode N planning. This is essential for serialized content.

---

# 62. Visual Memory

Maintain: project_visual_memory

Each approved asset gets: embedding, asset_type, character_id, environment_id, episode_id, scene_id, shot_id, tags

Before generation: retrieve relevant visual memory.

---

# 63. Quality Thresholds

Initial configurable defaults:

character_similarity >= 0.85
environment_similarity >= 0.85
prompt_adherence >= 0.80
motion_quality >= 0.80
technical_quality >= 0.95

Do not treat these values as scientifically universal. Make them configuration parameters.

---

# 64. Automated Regeneration Rules

if character_similarity < threshold: regenerate with stronger character reference.
if environment_similarity < threshold: regenerate with environment reference.
if motion_quality < threshold: regenerate with motion-focused workflow.
if prompt_adherence < threshold: rewrite prompt and regenerate.

Maximum automatic attempts: 3. After 3 failures: REVIEW_REQUIRED.

---

# 65. Security Requirement

No uploaded asset may be publicly accessible. MinIO must run private. Nginx must require authentication before asset access. Use signed URLs for asset delivery.

Never expose /models, /data, /storage, /minio directly to the internet.

---

# 66. Deployment

Initial: Single GX10. Docker Compose. Nginx. Private LAN/VPN. No public exposure.

Later: Multiple GX10 nodes.

```
                API
                 │
             Scheduler
                 │
      ┌──────────┼──────────┐
      ▼          ▼          ▼
    GX10-1     GX10-2     GX10-3
      │          │          │
     GPU        GPU        GPU
```

The scheduler assigns generation jobs to available nodes.

---

# 67. Multi-GX10 Preparation

Every worker must have: worker_id, gpu_capabilities, models_available, memory_available, status, heartbeat

The scheduler must not assume identical workers.

---

# 68. First MVP

Do NOT build everything simultaneously.

Implement this first: Project → Character → Environment → Episode → Scene → Shot → Character reference → Environment reference → LTX image-to-video → QC → Video preview

If this works reliably, add: LoRA → Continuity → Audio → Timeline → Final rendering

---

# 69. MVP Acceptance Test

The MVP is accepted only if it can produce: 1 character, 1 environment, 1 costume, 10 shots. Each shot 5–8 seconds.

The character must remain recognizably the same. The environment must remain recognizable. Shots must be editable individually. Failed shots must be regenerated without regenerating the whole episode.

---

# 70. Production Acceptance Test

The production system must successfully execute — Episode: 10 minutes. Characters: 5. Locations: 5. Scenes: 15+. Shots: 80+.

Requirements: character continuity, environment continuity, costume continuity, prop continuity, episode continuity, regeneration, QC, audio, final render

---

# 71. Coding Rules

The coding agent MUST:

* write production-quality code
* use type hints
* use Pydantic
* use SQLAlchemy
* use migrations
* write unit tests
* write integration tests
* write API tests
* write worker tests
* write provider tests
* write GPU health tests
* use structured logging
* handle retries
* handle failed jobs
* use idempotent jobs
* use database transactions
* never silently swallow exceptions
* never hard-code secrets
* never hard-code model paths
* never hard-code GPU assumptions

---

# 72. AI Provider Rule

Every AI provider must implement the same interface.

```python
class VideoProvider(ABC):
    async def generate(...): ...
    async def image_to_video(...): ...
    async def video_to_video(...): ...
    async def health_check(...): ...
    async def estimate_resources(...): ...
```

This allows LTX to be replaced or supplemented later.

---

# 73. Offline Mode

When ENABLE_EXTERNAL_APIS=false the following must work: LLM planning, image generation, video generation, voice generation, QC, rendering, asset storage, project management — without internet access.

Internet may only be needed initially to download approved model weights.

After models are installed, runtime must work offline.

---

# 74. Installation Script

Create: scripts/setup/install.sh

It must:

1. Validate ARM64.
2. Validate NVIDIA.
3. Validate CUDA.
4. Validate Docker.
5. Validate storage.
6. Create directories.
7. Create environment.
8. Start PostgreSQL.
9. Start Redis.
10. Start MinIO.
11. Start backend.
12. Start frontend.
13. Start AI engine.
14. Run health checks.

Also create: scripts/setup/verify_gx10.sh

Output:

```
GX10 compatibility: PASS
Architecture: arm64
NVIDIA: PASS
CUDA: PASS
PyTorch CUDA: PASS
Unified memory: 128GB
Docker: PASS
Storage: PASS
```

---

# 75. Docker Build Requirements

All images must declare architecture support. Preferred: linux/arm64. Build with docker buildx. Do not build x86-only images.

For GPU images, validate:

```
python -c "import torch; print(torch.cuda.is_available())"
python -c "import torch; print(torch.cuda.get_device_name(0))"
```

---

# 76. Documentation

Generate: docs/architecture.md, docs/deployment.md, docs/models.md, docs/lora-training.md, docs/character-consistency.md, docs/environment-consistency.md, docs/episode-generation.md, docs/troubleshooting.md, docs/security.md, docs/offline-operation.md, docs/api.md, docs/developer-guide.md

---

# 77. Required Deliverables

1. Complete source code. 2. Docker Compose. 3. Dockerfiles. 4. Database migrations. 5. PostgreSQL schema. 6. Redis configuration. 7. MinIO configuration. 8. FastAPI backend. 9. React frontend. 10. AI engine. 11. LTX integration. 12. ComfyUI integration. 13. Model registry. 14. Character system. 15. Environment system. 16. Story Bible. 17. Episode planner. 18. Scene planner. 19. Shot planner. 20. Prompt engine. 21. Continuity engine. 22. QC engine. 23. Render engine. 24. Authentication. 25. RBAC. 26. Audit logging. 27. Monitoring. 28. Tests. 29. Installation scripts. 30. Production documentation.

---

# 78. Critical Rule About Model Selection

Before implementing a model integration, verify: official repository, current model version, license, commercial usage rights, ARM64 compatibility, NVIDIA GB10 compatibility, CUDA compatibility, memory requirements, local inference availability.

Do not claim a model works on GX10 until it has actually been tested.

If a model cannot run natively mark it: UNSUPPORTED_ON_CURRENT_HARDWARE

Do not fake compatibility.

---

# 79. Initial Model Strategy

PRIMARY VIDEO: LTX-2.3
SECONDARY VIDEO: HunyuanVideo 1.5 where compatible.
IMAGE GENERATION: Use a pluggable image provider.
LLM: Local OpenAI-compatible LLM server.
TTS: Pluggable local TTS provider.
AUDIO: Pluggable local audio provider.
UPSCALE: Pluggable local upscaler.

Do not install every possible model in version 1.

---

# 80. Important GX10 Constraint

The GX10 has 128 GB unified memory, which is excellent for local AI workloads, but the application must NOT assume that "128 GB unified memory" means every model requiring 128 GB of dedicated GPU VRAM will behave identically to an H100/80GB GPU.

Benchmark each model on the actual machine.

The scheduler must observe real runtime memory.

---

# 81. Development Sequence

PHASE 1 — Infrastructure: PostgreSQL, Redis, MinIO, FastAPI, React, Docker
PHASE 2 — Project system: Projects, Characters, Environments, Assets
PHASE 3 — AI Director: Story, Episode, Scene, Shot
PHASE 4 — LTX integration: Text-to-video, Image-to-video
PHASE 5 — Reference system: Character references, Environment references, Previous-frame chaining
PHASE 6 — QC: Consistency, Motion, Prompt adherence
PHASE 7 — LoRA: Character LoRA, Style LoRA
PHASE 8 — Audio: Voice, Music, SFX
PHASE 9 — Timeline: Shot assembly, Audio synchronization, Subtitles
PHASE 10 — Production: Monitoring, RBAC, Audit, Backup, Multi-worker support

---

# 82. Final Instruction to the Coding Agent

Do not produce a toy/demo application.

Build this as a production-oriented private AI video platform.

Do not replace real AI integrations with fake/mock generators except inside automated tests.

When an AI model cannot yet be executed on the target GX10, implement the provider interface and clearly mark the provider as unavailable rather than pretending it works.

The application must remain functional if: the internet is disconnected, a model fails, a generation fails, a worker crashes, a video is rejected, a LoRA fails, a render fails.

The system must recover from failures without corrupting project state.

Every generated asset must be traceable to: project, episode, scene, shot, model, model version, workflow, prompt, references, seed, LoRA, generation attempt, QC result.

The final system must make it possible to answer: "Why does this shot look the way it does?" by examining the generation metadata.

---

# 83. Definition of Done

The platform is considered production-ready only when:

- [ ] GX10 detected
- [ ] ARM64 verified
- [ ] NVIDIA GPU verified
- [ ] CUDA verified
- [ ] PostgreSQL operational
- [ ] Redis operational
- [ ] MinIO operational
- [ ] FastAPI operational
- [ ] React UI operational
- [ ] Local LLM operational
- [ ] LTX operational
- [ ] Character references operational
- [ ] Environment references operational
- [ ] Character LoRA operational
- [ ] Shot planning operational
- [ ] Image-to-video operational
- [ ] Previous-frame chaining operational
- [ ] QC operational
- [ ] Regeneration operational
- [ ] Audio operational
- [ ] Timeline operational
- [ ] FFmpeg rendering operational
- [ ] Authentication operational
- [ ] RBAC operational
- [ ] Audit logging operational
- [ ] Monitoring operational
- [ ] Backup operational
- [ ] Offline mode tested
- [ ] 10-minute episode tested
- [ ] Multi-scene continuity tested
- [ ] Multi-episode continuity tested
- [ ] Failure recovery tested
- [ ] Security review completed
