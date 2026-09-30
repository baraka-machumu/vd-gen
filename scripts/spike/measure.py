"""Run a command and record wall time + peak memory on unified-memory hardware (module M17, spec §80).

GB10 shares one memory pool between CPU and GPU, and nvidia-smi may report per-GPU memory as N/A.
So the primary measurement is the drop in system MemAvailable (/proc/meminfo) from a baseline taken
just before the command starts. nvidia-smi utilization/memory/power are sampled too when reported.

Standard library only; runs on the host or inside a container.

Usage:
    python measure.py --out report.json --label ltx-i2v-run1 [--log run.log] [--interval 1.0] -- CMD [ARGS...]
Exits with the command's exit code.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


def meminfo_kib() -> dict[str, int]:
    values: dict[str, int] = {}
    with open("/proc/meminfo", encoding="ascii") as fh:
        for line in fh:
            key, rest = line.split(":", 1)
            values[key] = int(rest.split()[0])
    return values


def nvidia_sample() -> dict[str, float | None] | None:
    if not shutil.which("nvidia-smi"):
        return None
    fields = "utilization.gpu,memory.used,power.draw,temperature.gpu"
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip().splitlines()[0]
    except (subprocess.SubprocessError, IndexError, OSError):
        return None

    def num(v: str) -> float | None:
        try:
            return float(v)
        except ValueError:  # "[N/A]" / "Not Supported"
            return None

    util, mem, power, temp = (num(v.strip()) for v in out.split(","))
    return {"util_pct": util, "mem_used_mib": mem, "power_w": power, "temp_c": temp}


class Sampler(threading.Thread):
    def __init__(self, interval: float) -> None:
        super().__init__(daemon=True)
        self.interval = interval
        self.stop_event = threading.Event()
        self.min_available_kib: int | None = None
        self.min_available_at_s: float | None = None
        self.gpu_samples: list[dict[str, float | None]] = []
        self.t0 = time.monotonic()

    def run(self) -> None:
        while not self.stop_event.is_set():
            avail = meminfo_kib()["MemAvailable"]
            if self.min_available_kib is None or avail < self.min_available_kib:
                self.min_available_kib = avail
                self.min_available_at_s = round(time.monotonic() - self.t0, 1)
            sample = nvidia_sample()
            if sample:
                self.gpu_samples.append(sample)
            self.stop_event.wait(self.interval)


def _peak(samples: list[dict[str, float | None]], key: str) -> float | None:
    vals = [s[key] for s in samples if s.get(key) is not None]
    return max(vals) if vals else None  # type: ignore[type-var]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not cmd:
        parser.error("no command given (put it after --)")

    before = meminfo_kib()
    sampler = Sampler(args.interval)
    started = dt.datetime.now(dt.timezone.utc)
    sampler.start()
    t0 = time.monotonic()

    log_fh = args.log.open("w", encoding="utf-8") if args.log else None
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert proc.stdout is not None
    for line in proc.stdout:  # tee to console + log
        sys.stdout.write(line)
        if log_fh:
            log_fh.write(line)
    rc = proc.wait()
    wall = time.monotonic() - t0
    sampler.stop_event.set()
    sampler.join()
    if log_fh:
        log_fh.close()

    base_avail = before["MemAvailable"]
    min_avail = sampler.min_available_kib if sampler.min_available_kib is not None else base_avail
    report: dict[str, Any] = {
        "label": args.label,
        "command": cmd,
        "exit_code": rc,
        "started_utc": started.isoformat(),
        "wall_time_s": round(wall, 1),
        "memory": {
            "total_gib": round(before["MemTotal"] / 2**20, 2),
            "available_before_gib": round(base_avail / 2**20, 2),
            "min_available_gib": round(min_avail / 2**20, 2),
            "peak_used_delta_gib": round((base_avail - min_avail) / 2**20, 2),
            "peak_at_s": sampler.min_available_at_s,
            "method": "MemAvailable drop vs. baseline (unified memory: includes GPU allocations)",
        },
        "gpu": {
            "samples": len(sampler.gpu_samples),
            "peak_util_pct": _peak(sampler.gpu_samples, "util_pct"),
            "peak_mem_used_mib": _peak(sampler.gpu_samples, "mem_used_mib"),
            "peak_power_w": _peak(sampler.gpu_samples, "power_w"),
            "peak_temp_c": _peak(sampler.gpu_samples, "temp_c"),
        },
        "host": {"machine": platform.machine(), "node": platform.node()},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    m = report["memory"]
    print(f"\n[measure] {args.label}: exit={rc} wall={report['wall_time_s']}s "
          f"peak_mem_delta={m['peak_used_delta_gib']} GiB (of {m['total_gib']} GiB) -> {args.out}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
