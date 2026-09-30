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
| LTX-2.3 | ComfyUI (existing install) | **Runs.** t2v and i2v verified (i2v: warm runs only; cold not yet measured) | t2v: `ltx-i2v-20260930T085253Z.json` (this run was t2v despite the label); i2v: `ltx-i2v-20260930T103322Z.json` |
| HunyuanVideo | ComfyUI (existing install) | Installed, not yet measured | — |
| Wan | ComfyUI (existing install) | Installed, not yet measured | — |

## Benchmarks

| Date | Model / mode | Resolution | Frames / duration | Wall time | Compute per video-second | Peak extra memory | Notes |
|---|---|---|---|---|---|---|---|
| 2026-09-30 | LTX-2.3 **t2v** (ComfyUI) | 1280×704 @ 30 fps | 1201 / 40.0 s | 986.9 s (incl. model load) | **≈ 24.7 s** | 34.5 GiB | Single 40 s generation containing ~6 implicit shots. Steps/checkpoint unknown: workflow summary pending. Run 2 was a cache hit (invalid); fixed in `comfy_run.py`. |
| 2026-09-30 | LTX-2.3 **i2v** (ComfyUI), dev fp8 + distilled LoRA 0.5, x2 spatial upscaler, audio on | 1280×704 @ 25 fps | 201 / 8.04 s | 102.1 s / 100.2 s (2 runs, **warm**) | **≈ 12.5 s** (ComfyUI exec 100.9 s / 99.0 s) | 8.8 GiB above ~55 GiB already resident; min available 57.8 GiB | 36/51 nodes cached (models loaded, enhanced prompt reused); fresh seeds, so not a cache hit. GPU peak 95 %, 83 W. Cold run not measured. `ltx-i2v-20260930T103322Z.json` |
| 2026-09-30 | LTX-2.3 **i2v**, same workflow, **prompt enhancer off** | 1280×704 @ 25 fps | 201 / 8.04 s | 98.2 s / 100.2 s (2 runs, warm) | **≈ 12.2 s** (ComfyUI exec 97.8 s / 98.2 s) | 8.3 GiB; min available 58.1 GiB | Run 1 re-encoded the new prompt (31/51 cached), run 2 36/51. Removing the enhancer saves no measurable time. GPU peak 96 %, 84 W. `ltx-i2v-noenh-20260930T110141Z.json` |

**Early extrapolation:** a 10-min episode is ~600 s of video. At the warm i2v rate (~12.5 s/s, 8 s shots) that is ≈ 2.1 h raw generation at 720p, before model loads, regenerations and keyframes. The t2v rate (~25 s/s) gave ≈ 4 h. Neither is an NFR yet: it needs a cold run, and i2v output quality (Q7) must pass first.

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

## Quality findings: first i2v run (2026-09-30)

Source: `storage/ltx-i2v-20260930T103322Z-run{1,2}/LTX_2.3_i2v_0000{7,8}_.mp4` (local, not committed), reviewed from frames at 0/2/4/6/8 s.
Keyframe: `ComfyUI_00107_.png` (two young men in jackets at a fruit market, looking at phones). Prompt (node `Prompt`):

> Two young men standing together at an outdoor fruit market, looking at a smartphone and having a natural conversation. The man on the left gestures naturally with his hand while speaking, and the man on the right looks at the phone and then looks toward him. Subtle realistic body movement, natural facial expressions, gentle handheld camera movement, slight movement of people and fruit in the background, realistic lighting, cinematic documentary style, smooth continuous motion, highly detailed, photorealistic.

| # | Finding | Severity | Suspected cause | Next step |
|---|---|---|---|---|
| Q7 (**resolved**, see Q10) | Frame 0 matches the keyframe, then identity and wardrobe drift: run 1 has different people in grey/white T-shirts by ~2 s, run 2 swaps one man into a white T-shirt by ~4 s | High | Not the user prompt (it asks for continuous motion and mentions no clothing). Prime suspect: the workflow's **prompt enhancer** (`TextGenerateLTX2Prompt`, "Enable Prompt Enhance" = true) rewrites the prompt with Gemma; the rewrite was cached and reused by both runs. Contributing: the prompt does not anchor appearance (jackets, backpack) | Rerun with enhancer off (same keyframe, 2 seeds) and record the enhanced prompt text (`comfy_run.py` now saves preview-node text) |
| Q8 (**resolved**, see Q10) | Implicit shot changes inside one 8 s clip (close two-shot → wide market shots; run 2 ends in a motion-blurred close-up) | High | Same as Q7; violates R-SHOT | Same rerun; if it persists with the enhancer off, test 5 s instead of 8 s and an appearance-anchored prompt |
| Q9 | Market environment, lighting and colour stay consistent with the keyframe | Positive | — | Keep |

### Rerun with the prompt enhancer off (2026-09-30)

Same workflow and keyframe, `--set 320:328.value=false`, 2 fresh seeds. The report's `text_outputs` confirms the video was conditioned on the user prompt verbatim. Clips: `storage/ltx-i2v-noenh-20260930T110141Z-run{1,2}/LTX_2.3_i2v_0000{9,10}_.mp4`.

| # | Finding | Severity | Response |
|---|---|---|---|
| Q10 | Both runs hold the keyframe for all 8 s: same two people, same jackets and backpack, one continuous shot with no cuts; the gesture and look-toward described in the prompt happen. Q7/Q8 were caused by the prompt enhancer | Positive | Enhancer off by default (review/02 i2v update); keyframe-first i2v confirmed as the way to keep identity within a shot |
| Q11 | Run 2 ends with both men looking into the camera | Low | Breaks documentary style; add "not looking at the camera" to M10 i2v prompt defaults; QC can flag it later |
| Q12 | Faces look consistent at contact-sheet scale, but only a face-similarity score can confirm identity across the shot | Info | M21 keyframe identity check (first/last frame vs keyframe) |
