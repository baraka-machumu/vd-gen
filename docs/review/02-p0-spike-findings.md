# Review addendum 02: P0 spike findings → requirement changes

| | |
|---|---|
| **Date** | 2026-09-30 |
| **Input** | First LTX-2.3 clip generated on gx10-67e1 via the existing ComfyUI; product-owner review + frame analysis. Details in [`../models.md`](../models.md). |
| **Effect** | Adds requirements R-TEXT, R-SHOT, R-ACTION and R-MOTION. These amend the spec in the same way as review 01. |

## Summary

The clip was made by the approach spec §3 forbids: one long text-to-video generation with no references.
Its failures (garbled text, wrong door physics, identity drift, dissolves, stiff people) are the failures
the planned pipeline is designed to prevent, with one exception: **text rendering**, which the spec
does not address at all.

## New requirements

### R-TEXT: No model-rendered text (new)
- The prompt engine (M10) must **never** ask a video or image model for legible text (signs, logos, captions, screens, number plates). Text-bearing surfaces are described as "blank sign", "plain storefront", and so on.
- Brand signage and logos are **props with a reference asset** (spec §16). They are applied in post (M26) by compositing:
  - Phase 1: static-camera shots and lower-thirds/titles via FFmpeg overlay/drawtext.
  - Later: planar tracking for moving cameras.
- An alternative for hero shots: use a **real photo** containing the correct signage as the keyframe/environment reference, with low camera motion. The text must still pass QC.
- **QC (M21)** adds an OCR check. Any detected text that isn't in the shot's allowed-text list gets `REVIEW`, so garbled pseudo-text is caught automatically.

### R-SHOT: One shot per generation (clarifies spec §20, §69)
- Each generation produces exactly one shot. The duration cap is configurable per model, with a default of 8 s for LTX.
- The AI Director (M12) and the API reject multi-shot descriptions in a single generation request.
- Cuts and transitions exist only in the timeline (M26).

### R-ACTION: Difficult actions use first/last frames (strengthens spec §21)
- The shot planner flags **interaction actions** as `DIFFICULT` (open/close door, enter/exit vehicle, hand objects over, sit/stand, embrace, and so on). These default to the first-frame + last-frame mode.
- Complex actions are decomposed into simpler shots, for example: approach car (wide) → hand on handle (insert) → seated, door closing (medium, interior).

### R-MOTION: Realistic human motion (new)
- Support **motion reference**: a short real video (for example, an employee filmed on a phone performing the action) drives pose/motion through a control model. LTX-2.3's official IC-LoRA control models are the first candidate (spec §7). Their availability in the GX10 ComfyUI setup must be verified.
- Motion reference footage of employees falls under the consent rules (ADR-012).
- QC motion score (M21) is calibrated using this clip as a known-bad example.
- Benchmark distilled vs. dev checkpoint quality for human motion before fixing the Production profile (spec §57).

## Plan impact

| Module | Change |
|---|---|
| M10 Prompt Engine | R-TEXT prompt rules + unit tests |
| M12 AI Director | R-SHOT enforcement; R-ACTION action decomposition |
| M18 Video Providers | First/last frame + IC-LoRA control (pose/depth) capability; per-model max duration |
| M21 QC | OCR text check; motion score calibration set includes this clip |
| M26 Timeline & Render | Signage/logo compositing, lower-thirds |
| M17 spike | Next measurement: LTX-2.3 **i2v**, 5–8 s, from a keyframe; then the same shot with first/last frame |

## Update 2026-09-30: first i2v run

Two warm LTX-2.3 i2v runs from a keyframe (8 s, 1280×704): ~12.5 s compute per video-second, half the t2v rate. Details and prompt in [`../models.md`](../models.md) (Q7–Q9).

Keyframe-first did **not** by itself keep identity: the characters change clothes and the clip cuts to new framings within 2–4 s. The user prompt did not ask for this. The workflow's built-in prompt enhancer (an LLM rewrite step) is the prime suspect.

### Requirement changes
- **R-SHOT, addition:** the final prompt sent to the video model is the prompt the platform wrote. Any LLM rewrite step inside a workflow (e.g. `TextGenerateLTX2Prompt`) is disabled in production workflows unless its output is captured, stored with the shot, and passes the same R-TEXT/R-SHOT rules. The stored prompt is the one that was actually encoded (spec §8 reproducibility).
- **M10 Prompt Engine:** i2v prompts describe the keyframe's fixed appearance (wardrobe, props) and state "same people, same clothing, single continuous shot" so that the prompt reinforces the keyframe rather than competing with it.
- **M21 QC:** identity check compares the first and last frames of each shot with the keyframe (face + wardrobe), not only against the character reference.

### Open decision
- The example workflow loads `gemma-3-12b-it-abliterated_lora` (Gemma with refusal behaviour removed). It feeds **only** the prompt enhancer (`LoraLoader` → `TextGenerateLTX2Prompt`); the video text encoding (`CLIPTextEncode`) uses the plain Gemma encoder. With the enhancer off, the LoRA is not used. Whether production workflows may keep it is a product-owner decision, to be recorded as an ADR before M18 fixes the golden workflow.

### Result of the enhancer-off rerun (2026-09-30)
Confirmed: with the enhancer off, both seeds keep identity, wardrobe and a single continuous shot for 8 s (models.md Q10). The R-SHOT addition above therefore means **prompt enhancer off by default** in production LTX workflows; the prompt engine (M10) owns prompt quality. With the enhancer off, the abliterated Gemma LoRA is not used either.
