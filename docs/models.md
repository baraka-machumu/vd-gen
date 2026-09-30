# Models: verified status, benchmarks & findings

Only **measured** facts go here (spec §78, §80). Every row cites its evidence in `reports/`.
License status is tracked separately in M16 and is **not** implied by "runs on GX10".

## Hardware baseline: gx10-67e1 (verified 2026-09-30)

| Item | Value | Evidence |
|---|---|---|
| Platform | ASUSTeK GX10, DGX OS 7.2.3 (OTA 7.5.0), Ubuntu 24.04.4 | `verify_gx10-gx10-67e1-20260930T080338Z.json` |
| GPU | NVIDIA GB10, compute capability 12.1, driver 580.159.03, CUDA 13.0 | same |
| Unified memory | 121.7 GiB visible to the OS. `nvidia-smi memory.total` = N/A, so memory must be measured via `/proc/meminfo` | same |
| Storage | 3.6 TB root, 1.5 TB free | same |
| NGC PyTorch in container | PASS (details in `gpu_smoke-*.json`, pending review) | same |
| Resident load | ComfyUI (LTX, Hunyuan, Wan installed) keeps ~58 GiB resident between jobs | owner report + verify run |

## Execution backend status

| Model | Backend | Status on GX10 | Evidence |
|---|---|---|---|
| LTX-2.3 | ComfyUI (existing install) | **Runs.** t2v verified; i2v not yet measured | `ltx-i2v-20260930T085253Z.json` (note: this run was t2v despite the label) |
| HunyuanVideo | ComfyUI (existing install) | Installed, not yet measured | — |
| Wan | ComfyUI (existing install) | Installed, not yet measured | — |

## Benchmarks

| Date | Model / mode | Resolution | Frames / duration | Wall time | Compute per video-second | Peak extra memory | Notes |
|---|---|---|---|---|---|---|---|
| 2026-09-30 | LTX-2.3 **t2v** (ComfyUI) | 1280×704 @ 30 fps | 1201 / 40.0 s | 986.9 s (incl. model load) | **≈ 24.7 s** | 34.5 GiB | Single 40 s generation containing ~6 implicit shots. Steps/checkpoint unknown: workflow summary pending. Run 2 was a cache hit (invalid); fixed in `comfy_run.py`. |

**Early extrapolation (to be replaced with i2v numbers):** a 10-min episode is ~600 s of video × ~25 s/s ≈ 4 h raw generation at 720p, before regenerations, keyframes and upscaling.

## Quality findings: P0 clip review (2026-09-30)

Source: `storage/LTX_2.3_t2v_00014_.mp4` (local, not committed). It was reviewed by the product owner and frame-by-frame.

| # | Finding | Severity | Root cause | Platform response |
|---|---|---|---|---|
| Q1 | Scene text is garbled ("YAS YOEO", "SILION VALLEY", "SILITOON VALLVY") | High (brand damage) | Video diffusion models cannot spell reliably | **Requirement R-TEXT:** the model never renders legible text; see [review/02](review/02-p0-spike-findings.md) |
| Q2 | Door opens the wrong way; the person is inside and outside the car at once | High | Physical human–object interaction without any control signal | First/last-frame generation (spec §21) + pose/motion control (LTX IC-LoRA, spec §7); split actions into simpler shots |
| Q3 | A character is duplicated and her identity drifts within 2 s (ponytail → bob) | High | t2v with no reference; many shots in one generation | Keyframe-first i2v from approved references (spec §21, §59); one shot per generation |
| Q4 | Ghosting dissolve between implied shots (38.2 s) | Medium | Model-invented transitions inside one generation | Cuts and transitions only in the edit (M26), never inside a generation |
| Q5 | People look stiff / robotic | High | No motion reference; long clip | Motion transfer from real reference footage (pose control); QC motion score (M21); compare the dev vs. distilled model |
| Q6 | Environment, lighting and vehicle stay consistent | Positive | — | Keep; confirms environment consistency is achievable |
