# ai-engine/ — GPU plane (M17)

The single GPU execution service (spec §36). arm64 only, based on NVIDIA NGC PyTorch (ADR-007).
Claims GPU jobs from the scheduler (M15) and runs them through provider adapters.

| Path | Module |
|---|---|
| `common/` | M17 runtime, job loop, model load/unload, memory measurement |
| `ltx/`, `hunyuan/`, `wan/` | M18 video providers |
| `comfyui/` | M18 optional ComfyUI backend (post-MVP, ADR-004) |
| `image/` | M19 keyframe provider |
| `qc/` | M21 GPU-side scorers |
| `audio/` | M25 |
| `training/` | M24 LoRA training |

Rule (spec §78): a provider is `UNSUPPORTED_ON_CURRENT_HARDWARE` until verified on a GX10.
