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
