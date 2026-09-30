"""Inventory an existing ComfyUI server (read-only). Phase 0 spike, modules M16/M17/M18.

Records what is ACTUALLY installed (spec §78): ComfyUI + PyTorch versions, devices, the models in each
model folder, the custom nodes that look video-related (LTX / Hunyuan / Wan), and the current queue.
Nothing is submitted, loaded or unloaded.

Usage (on the GX10, standard library only):
    python3 comfy_probe.py [--url http://127.0.0.1:8188] [--report-dir reports/p0]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

VIDEO_KEYWORDS = ("ltx", "hunyuan", "wan", "video", "vace", "i2v", "t2v")


def get(url: str, path: str, timeout: float = 30) -> Any:
    with urllib.request.urlopen(url.rstrip("/") + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def try_get(url: str, path: str) -> Any:
    try:
        return get(url, path)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"_error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8188")
    parser.add_argument("--report-dir", type=Path, default=Path(__file__).resolve().parents[2] / "reports" / "p0")
    args = parser.parse_args()

    try:
        stats = get(args.url, "/system_stats", timeout=10)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"Cannot reach ComfyUI at {args.url}: {exc}\n"
              "Check the port with: ss -ltnp | grep -i python   (or docker ps for a containerised ComfyUI)", file=sys.stderr)
        return 1

    # Model folders -> files. /models exists on current ComfyUI; older builds lack it.
    folders = try_get(args.url, "/models")
    models: dict[str, Any] = {}
    if isinstance(folders, list):
        for folder in folders:
            files = try_get(args.url, f"/models/{folder}")
            if isinstance(files, list) and files:
                models[folder] = sorted(files)
    else:
        models = {"_error": folders.get("_error", "unknown")}

    object_info = try_get(args.url, "/object_info")
    video_nodes: dict[str, list[str]] = {}
    if isinstance(object_info, dict) and "_error" not in object_info:
        for name, info in object_info.items():
            if any(k in name.lower() for k in VIDEO_KEYWORDS):
                video_nodes.setdefault(info.get("python_module", "?"), []).append(name)

    queue = try_get(args.url, "/queue")
    report = {
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "url": args.url,
        "system_stats": stats,
        "models": models,
        "node_count": len(object_info) if isinstance(object_info, dict) else None,
        "video_related_nodes_by_module": {k: sorted(v) for k, v in sorted(video_nodes.items())},
        "queue": {
            "running": len(queue.get("queue_running", [])) if isinstance(queue, dict) else None,
            "pending": len(queue.get("queue_pending", [])) if isinstance(queue, dict) else None,
        },
        "extensions": try_get(args.url, "/extensions"),
    }

    args.report_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = args.report_dir / f"comfy_probe-{ts}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if isinstance(object_info, dict) and "_error" not in object_info:
        (args.report_dir / f"comfy_object_info-{ts}.json").write_text(json.dumps(object_info), encoding="utf-8")

    # Console summary.
    system = stats.get("system", {})
    print(f"ComfyUI {system.get('comfyui_version', '?')} | Python {str(system.get('python_version', '?')).split()[0]} "
          f"| PyTorch {system.get('pytorch_version', '?')}")
    for d in stats.get("devices", []):
        print(f"Device: {d.get('name')}  vram_total={d.get('vram_total', 0) / 2**30:.1f} GiB  "
              f"vram_free={d.get('vram_free', 0) / 2**30:.1f} GiB")
    print(f"Queue: running={report['queue']['running']} pending={report['queue']['pending']}")
    print("\nModels:")
    for folder, files in models.items():
        if folder == "_error":
            print(f"  (model listing unavailable: {files})")
            continue
        print(f"  {folder}/")
        for f in files:
            print(f"    {f}")
    print("\nVideo-related custom nodes (by module):")
    for module, names in report["video_related_nodes_by_module"].items():
        print(f"  {module}: {len(names)} nodes")
    print(f"\nReport: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
