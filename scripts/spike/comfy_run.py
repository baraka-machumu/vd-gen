"""Run one ComfyUI workflow (API format) and measure it. Phase 0 spike, modules M17/M18, spec §80.

Submits the workflow, waits for completion, and records wall time, ComfyUI execution time,
peak unified-memory use (MemAvailable drop, same method as measure.py), the outputs, and the exact
workflow JSON (SHA256) for reproducibility (spec §8).

Export the workflow from the ComfyUI UI with "Export (API)" (not the normal Save/Export). Its node ids
are the keys; override inputs with --set NODE_ID.INPUT=VALUE (VALUE is parsed as JSON when possible).

Usage (on the GX10, standard library only):
    python3 comfy_run.py WORKFLOW_API.json --label ltx-i2v [--runs 2] [--cold] \
        [--set 3.seed=42 --set 12.text="a desk in an office"] [--url http://127.0.0.1:8188]

--cold asks ComfyUI to unload all models first (POST /free), so run 1 includes model load time.
   WARNING: this affects anyone else using the same ComfyUI; don't use it while others are generating.

Every run gets a fresh random seed (inputs named seed / noise_seed), recorded in the report. Without it,
ComfyUI returns its cached result for an identical request and the "run" measures nothing.
Use --fixed-seed to keep the workflow's seeds (a repeat will then be served from cache).
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import random
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure import Sampler, meminfo_kib, peak

ROOT = Path(__file__).resolve().parents[2]


def http(url: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 30) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"} if data else {}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body) if body else None


def apply_overrides(workflow: dict[str, Any], sets: list[str]) -> dict[str, Any]:
    wf = copy.deepcopy(workflow)
    for item in sets:
        key, _, raw = item.partition("=")
        node_id, _, input_name = key.partition(".")
        if node_id not in wf or not input_name:
            raise SystemExit(f"--set {item!r}: node {node_id!r} not in workflow (ids: {', '.join(sorted(wf))})")
        try:
            value: Any = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        wf[node_id].setdefault("inputs", {})[input_name] = value
    return wf


SEED_INPUTS = ("seed", "noise_seed")
# Inputs worth recording next to every timing (resolution, length, steps, models, ...).
SUMMARY_INPUTS = (
    "width",
    "height",
    "length",
    "num_frames",
    "frames",
    "frame_rate",
    "fps",
    "batch_size",
    "steps",
    "cfg",
    "sampler_name",
    "scheduler",
    "denoise",
    "strength",
    "ckpt_name",
    "unet_name",
    "model_name",
    "clip_name",
    "clip_name1",
    "clip_name2",
    "vae_name",
    "lora_name",
    "strength_model",
    "upscale_model",
    "weight_dtype",
    "text_encoder",
    "image",
    "text",
    "sigmas",
    *SEED_INPUTS,
)
# Primitive nodes hold UI-level settings (width, duration, prompt, feature switches) under "value";
# they are only meaningful together with the node title, so both are recorded.
PRIMITIVE_PREFIX = "Primitive"


def reseed(workflow: dict[str, Any], pinned: set[str]) -> dict[str, int]:
    """Give every literal seed input a fresh random value (in place); skip inputs pinned by --set."""
    used = {}
    for node_id, node in workflow.items():
        inputs = node.get("inputs", {})
        for name in SEED_INPUTS:
            key = f"{node_id}.{name}"
            if name in inputs and not isinstance(inputs[name], list) and key not in pinned:
                inputs[name] = random.randint(0, 2**48)  # noqa: S311 - diffusion seed, not a secret
                used[key] = inputs[name]
    return used


def summarize(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """Literal (non-linked) key settings per node, so timings can be interpreted later."""
    rows = []
    for node_id, node in sorted(workflow.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        wanted = SUMMARY_INPUTS + (("value",) if node["class_type"].startswith(PRIMITIVE_PREFIX) else ())
        params = {k: v for k, v in node.get("inputs", {}).items() if k in wanted and not isinstance(v, list)}
        if params:
            title = node.get("_meta", {}).get("title")
            rows.append(
                {
                    "node": node_id,
                    "class_type": node["class_type"],
                    **({"title": title} if title and title != node["class_type"] else {}),
                    **params,
                }
            )
    return rows


def text_outputs(entry: dict[str, Any]) -> dict[str, list[str]]:
    """Text shown by preview nodes (e.g. an LLM-enhanced prompt), keyed by node id."""
    found = {}
    for node_id, node_out in entry.get("outputs", {}).items():
        texts = node_out.get("text")
        if isinstance(texts, list) and all(isinstance(t, str) for t in texts):
            found[node_id] = texts
    return found


def cached_nodes(entry: dict[str, Any]) -> int:
    for msg in entry.get("status", {}).get("messages", []):
        if len(msg) == 2 and msg[0] == "execution_cached":
            return len(msg[1].get("nodes", []))
    return 0


def queue_state(url: str, prompt_id: str) -> str:
    q = http(url, "/queue")
    if any(item[1] == prompt_id for item in q.get("queue_running", [])):
        return "running"
    pending = [item[1] for item in q.get("queue_pending", [])]
    if prompt_id in pending:
        return f"pending ({pending.index(prompt_id) + 1} of {len(pending)}, {len(q.get('queue_running', []))} running)"
    return "finishing"


def wait_for(url: str, prompt_id: str, poll_s: float, timeout_s: float, report_every_s: float = 30) -> dict[str, Any]:
    start = time.monotonic()
    deadline = start + timeout_s
    next_report = start + report_every_s
    while time.monotonic() < deadline:
        hist = http(url, f"/history/{prompt_id}")
        if hist and prompt_id in hist:
            entry = hist[prompt_id]
            if entry.get("status", {}).get("completed") or entry.get("status", {}).get("status_str") == "error":
                return entry
        if time.monotonic() >= next_report:
            avail = meminfo_kib()["MemAvailable"] / 2**20
            print(
                f"  ... {time.monotonic() - start:6.0f}s  {queue_state(url, prompt_id)}  mem available {avail:.1f} GiB",
                flush=True,
            )
            next_report += report_every_s
        time.sleep(poll_s)
    raise TimeoutError(f"prompt {prompt_id} did not finish within {timeout_s}s")


def exec_time_s(entry: dict[str, Any]) -> float | None:
    """ComfyUI's own execution time from the status messages (ms timestamps), if present."""
    stamps = {m[0]: m[1].get("timestamp") for m in entry.get("status", {}).get("messages", []) if len(m) == 2}
    start, end = stamps.get("execution_start"), stamps.get("execution_success") or stamps.get("execution_error")
    return round((end - start) / 1000, 1) if start and end else None


def download_outputs(url: str, entry: dict[str, Any], dest: Path) -> list[str]:
    saved = []
    for node_out in entry.get("outputs", {}).values():
        for items in node_out.values():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict) or "filename" not in item:
                    continue
                q = urllib.parse.urlencode({k: item.get(k, "") for k in ("filename", "subfolder", "type")})
                target = dest / item["filename"]
                dest.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(f"{url.rstrip('/')}/view?{q}", timeout=300) as resp:
                    target.write_bytes(resp.read())
                saved.append(str(target))
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("workflow", type=Path, help="workflow exported with 'Export (API)'")
    parser.add_argument("--label", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8188")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--cold", action="store_true", help="unload all ComfyUI models before run 1")
    parser.add_argument("--set", dest="sets", action="append", default=[], metavar="NODE.INPUT=VALUE")
    parser.add_argument("--fixed-seed", action="store_true", help="keep the workflow's seeds (repeats hit the cache)")
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports" / "p0")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
    args = parser.parse_args()

    workflow = json.loads(args.workflow.read_text(encoding="utf-8"))
    if not all(isinstance(v, dict) and "class_type" in v for v in workflow.values()):
        raise SystemExit("This is not an API-format workflow. In ComfyUI use Workflow -> Export (API).")
    workflow = apply_overrides(workflow, args.sets)
    pinned = {item.partition("=")[0] for item in args.sets}
    wf_bytes = json.dumps(workflow, sort_keys=True).encode("utf-8")
    wf_sha = hashlib.sha256(wf_bytes).hexdigest()
    summary = summarize(workflow)
    print("Workflow settings:" + ("" if args.fixed_seed else " (seeds are replaced per run; see the report)"))
    for row in summary:
        shown = {k: v for k, v in row.items() if args.fixed_seed or k not in SEED_INPUTS}
        if len(shown) > 2 + ("title" in shown):
            print("  " + ", ".join(f"{k}={v}" for k, v in shown.items()))

    stats_before = http(args.url, "/system_stats")
    queue = http(args.url, "/queue")
    busy = len(queue.get("queue_running", [])) + len(queue.get("queue_pending", []))
    if busy:
        print(f"WARNING: ComfyUI already has {busy} job(s) queued/running; timings will include waiting.")
    if args.cold:
        print("Unloading ComfyUI models (POST /free)...")
        http(args.url, "/free", {"unload_models": True, "free_memory": True})
        time.sleep(5)

    ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / f"{args.label}-{ts}.workflow.json").write_bytes(wf_bytes)

    runs = []
    rc = 0
    for i in range(1, args.runs + 1):
        seeds = {} if args.fixed_seed else reseed(workflow, pinned)
        before = meminfo_kib()["MemAvailable"]
        sampler = Sampler(interval=1.0)
        sampler.start()
        t0 = time.monotonic()
        resp = http(args.url, "/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())})
        prompt_id = resp["prompt_id"]
        print(f"[run {i}] submitted prompt {prompt_id}; waiting...", flush=True)
        try:
            entry = wait_for(args.url, prompt_id, poll_s=2.0, timeout_s=args.timeout)
            error = None if entry.get("status", {}).get("status_str") == "success" else entry.get("status")
        except TimeoutError as exc:
            entry, error = {}, str(exc)
        wall = time.monotonic() - t0
        sampler.stop_event.set()
        sampler.join()
        min_avail = sampler.min_available_kib or before
        outputs = download_outputs(args.url, entry, args.output_dir / f"{args.label}-{ts}-run{i}") if entry else []
        run = {
            "run": i,
            "prompt_id": prompt_id,
            "cold": args.cold and i == 1,
            "wall_time_s": round(wall, 1),
            "comfy_exec_time_s": exec_time_s(entry),
            "seeds": seeds,
            "cached_nodes": cached_nodes(entry),
            "served_from_cache": bool(entry) and cached_nodes(entry) >= len(workflow),
            "available_before_gib": round(before / 2**20, 2),
            "peak_used_delta_gib": round((before - min_avail) / 2**20, 2),
            "min_available_gib": round(min_avail / 2**20, 2),
            "gpu_peak_util_pct": peak(sampler.gpu_samples, "util_pct"),
            "gpu_peak_power_w": peak(sampler.gpu_samples, "power_w"),
            "outputs": outputs,
            "text_outputs": text_outputs(entry) if entry else {},
            "error": error,
        }
        runs.append(run)
        rc = rc or (1 if error else 0)
        print(
            f"[run {i}] {'OK' if not error else 'ERROR'} wall={run['wall_time_s']}s exec={run['comfy_exec_time_s']}s "
            f"peak_mem_delta={run['peak_used_delta_gib']} GiB outputs={len(outputs)} "
            f"cached_nodes={run['cached_nodes']}/{len(workflow)}",
            flush=True,
        )
        if run["served_from_cache"]:
            print(f"[run {i}] WARNING: every node was served from ComfyUI's cache; this timing is NOT a generation.")

    report = {
        "label": args.label,
        "timestamp_utc": ts,
        "url": args.url,
        "workflow_file": str(args.workflow),
        "workflow_sha256": wf_sha,
        "overrides": args.sets,
        "workflow_summary": summary,
        "comfy_system_before": stats_before,
        "comfy_system_after": http(args.url, "/system_stats"),
        "memory_total_gib": round(meminfo_kib()["MemTotal"] / 2**20, 2),
        "runs": runs,
    }
    out = args.report_dir / f"{args.label}-{ts}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport: {out}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
