"""Turn the LTX-2.3 i2v API workflow into a first/last-frame workflow. Phase 0 spike, M17/M18, spec §21.

Adds a second image (the last frame) through the same preprocessing as the first frame and pins it to the
final frame of pass 1 with LTXVAddGuide (frame_idx=-1). LTXVCropGuides then removes the guide frames before
the x2 latent upscale, so pass 2 refines the cropped latent. The prompt enhancer is switched off (review/02).

Node ids below are those of the ComfyUI "Image to Video (LTX-2.3)" template export (ltx_i2v_api.json);
the script refuses to run if they don't match.

Usage:
    python make_flf_workflow.py ltx_i2v_api.json ltx_flf_api.json --last-image flf_last.png [--prompt-file p.txt]
The last image must already be in ComfyUI's input folder on the GX10 (e.g. ~/ComfyUI/input/).
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

EXPECTED = {
    "269": "LoadImage",
    "320:290": "ResizeImageMaskNode",
    "320:286": "ResizeImagesByLongerEdge",
    "320:289": "LTXVPreprocess",
    "320:296": "LTXVImgToVideoInplace",
    "320:304": "LTXVConditioning",
    "320:316": "CheckpointLoaderSimple",
    "320:318": "LTXVConcatAVLatent",
    "320:314": "CFGGuider",
    "320:284": "LTXVCropGuides",
    "320:287": "LTXVLatentUpsampler",
    "320:319": "PrimitiveStringMultiline",
    "320:328": "PrimitiveBoolean",
}


def build(wf: dict, last_image: str, prompt: str | None) -> dict:
    for node_id, cls in EXPECTED.items():
        if wf.get(node_id, {}).get("class_type") != cls:
            raise SystemExit(f"node {node_id} is not {cls}; this is not the expected LTX-2.3 i2v template export")
    wf = copy.deepcopy(wf)

    wf["900"] = {"class_type": "LoadImage", "inputs": {"image": last_image}, "_meta": {"title": "Load Last Frame"}}
    for new, src, link_input, upstream in (
        ("320:901", "320:290", "input", "900"),
        ("320:902", "320:286", "images", "320:901"),
        ("320:903", "320:289", "image", "320:902"),
    ):
        wf[new] = copy.deepcopy(wf[src])
        wf[new]["inputs"][link_input] = [upstream, 0]
        wf[new]["_meta"] = {"title": wf[src].get("_meta", {}).get("title", wf[src]["class_type"]) + " (last frame)"}

    wf["320:904"] = {
        "class_type": "LTXVAddGuide",
        "inputs": {
            "positive": ["320:304", 0],
            "negative": ["320:304", 1],
            "vae": ["320:316", 2],
            "latent": ["320:296", 0],
            "image": ["320:903", 0],
            "frame_idx": -1,
            "strength": 1.0,
        },
        "_meta": {"title": "Last Frame Guide"},
    }
    # Pass 1 samples the guided latent with the guided conditioning.
    wf["320:318"]["inputs"]["video_latent"] = ["320:904", 2]
    wf["320:314"]["inputs"]["positive"] = ["320:904", 0]
    wf["320:314"]["inputs"]["negative"] = ["320:904", 1]
    # Crop the guide frames out before upscaling; pass 2 uses the cropped conditioning (already wired).
    wf["320:284"]["inputs"]["positive"] = ["320:904", 0]
    wf["320:284"]["inputs"]["negative"] = ["320:904", 1]
    wf["320:287"]["inputs"]["samples"] = ["320:284", 2]

    wf["320:328"]["inputs"]["value"] = False  # prompt enhancer off
    if prompt:
        wf["320:319"]["inputs"]["value"] = prompt
    return wf


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--last-image", required=True, help="filename in ComfyUI's input folder")
    parser.add_argument("--prompt-file", type=Path)
    args = parser.parse_args()
    wf = json.loads(args.source.read_text(encoding="utf-8"))
    prompt = args.prompt_file.read_text(encoding="utf-8").strip() if args.prompt_file else None
    args.output.write_text(json.dumps(build(wf, args.last_image, prompt), indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
