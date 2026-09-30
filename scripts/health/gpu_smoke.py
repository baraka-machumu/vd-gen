"""GPU smoke test for the ai-engine base image (ADR-007, spec §75, module M17).

Runs INSIDE the NGC PyTorch container:
    python gpu_smoke.py [--json] [--alloc-gb 16]

It checks the following and reports measured values, never assumed ones:
  * torch import, CUDA availability, device name, compute capability
  * whether this torch build ships kernels for the device (arch list)
  * bf16 matmul correctness + throughput
  * scaled_dot_product_attention per backend (flash / efficient / cudnn / math)
  * a unified-memory allocation of --alloc-gb GiB

Exit code 0 if CUDA works and the bf16 matmul is correct, else 1.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
import traceback
from typing import Any


def _gib(n_bytes: int) -> float:
    return round(n_bytes / 2**30, 2)


def run(alloc_gb: int) -> dict[str, Any]:
    r: dict[str, Any] = {"ok": False, "machine": platform.machine(), "python": platform.python_version(), "errors": []}
    try:
        import torch
        import torch.nn.functional as F
    except Exception as exc:
        r["errors"].append(f"import torch failed: {exc!r}")
        return r

    r["torch_version"] = torch.__version__
    r["torch_cuda_version"] = torch.version.cuda
    r["cudnn_version"] = torch.backends.cudnn.version() if torch.backends.cudnn.is_available() else None
    r["cuda_available"] = torch.cuda.is_available()
    if not r["cuda_available"]:
        r["errors"].append("torch.cuda.is_available() is False")
        return r

    dev = torch.device("cuda:0")
    major, minor = torch.cuda.get_device_capability(0)
    r["device_name"] = torch.cuda.get_device_name(0)
    r["capability"] = f"{major}{minor}"
    r["arch_list"] = torch.cuda.get_arch_list()
    # A build supports the device if it has SASS for sm_XY, or PTX (compute_XY) at or below it for JIT.
    sass = f"sm_{major}{minor}"
    ptx_ok = any(
        a.startswith("compute_") and int(a.split("_")[1].rstrip("af")) <= major * 10 + minor for a in r["arch_list"]
    )
    r["native_kernels_for_device"] = sass in r["arch_list"] or f"{sass}a" in r["arch_list"]
    r["ptx_fallback_available"] = ptx_ok
    free, total = torch.cuda.mem_get_info(0)
    r["mem_get_info_gib"] = {"free": _gib(free), "total": _gib(total)}

    # bf16 matmul: correctness vs fp32 + throughput.
    try:
        n = 8192
        a = torch.randn(n, n, device=dev, dtype=torch.bfloat16)
        b = torch.randn(n, n, device=dev, dtype=torch.bfloat16)
        ref = a[:256].float() @ b.float()
        got = (a @ b)[:256].float()
        rel_err = ((got - ref).abs().max() / ref.abs().max()).item()
        for _ in range(3):
            a @ b
        torch.cuda.synchronize()
        iters = 20
        t0 = time.perf_counter()
        for _ in range(iters):
            a @ b
        torch.cuda.synchronize()
        dt = time.perf_counter() - t0
        r["matmul_bf16_tflops"] = round(2 * n**3 * iters / dt / 1e12, 1)
        r["matmul_bf16_rel_err"] = round(rel_err, 5)
        r["matmul_ok"] = rel_err < 0.05
        del a, b, ref, got
    except Exception:
        r["matmul_ok"] = False
        r["errors"].append("bf16 matmul failed:\n" + traceback.format_exc())

    # SDPA per backend.
    r["sdpa_backends_ok"] = []
    r["sdpa_backends_failed"] = {}
    try:
        from torch.nn.attention import SDPBackend, sdpa_kernel

        q = torch.randn(1, 24, 4096, 128, device=dev, dtype=torch.bfloat16)
        backends = {
            "flash": SDPBackend.FLASH_ATTENTION,
            "efficient": SDPBackend.EFFICIENT_ATTENTION,
            "math": SDPBackend.MATH,
        }
        if hasattr(SDPBackend, "CUDNN_ATTENTION"):
            backends["cudnn"] = SDPBackend.CUDNN_ATTENTION
        for name, backend in backends.items():
            try:
                with sdpa_kernel(backend):
                    F.scaled_dot_product_attention(q, q, q)
                torch.cuda.synchronize()
                r["sdpa_backends_ok"].append(name)
            except Exception as exc:
                r["sdpa_backends_failed"][name] = str(exc).splitlines()[0][:200]
        del q
    except Exception:
        r["errors"].append("SDPA check failed:\n" + traceback.format_exc())

    # Unified-memory allocation in 1 GiB chunks.
    chunks = []
    try:
        for _ in range(alloc_gb):
            chunks.append(torch.empty(2**30, dtype=torch.uint8, device=dev).fill_(1))
        torch.cuda.synchronize()
        r["alloc_gib_ok"] = alloc_gb
    except Exception as exc:
        r["alloc_gib_ok"] = len(chunks)
        r["errors"].append(f"allocation stopped at {len(chunks)} GiB: {exc!r}")
    finally:
        r["max_memory_allocated_gib"] = _gib(torch.cuda.max_memory_allocated(0))
        chunks.clear()
        torch.cuda.empty_cache()

    r["ok"] = bool(r.get("matmul_ok")) and r["alloc_gib_ok"] == alloc_gb
    return r


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="print JSON only")
    parser.add_argument("--alloc-gb", type=int, default=16, help="GiB to allocate in the memory test (default 16)")
    args = parser.parse_args()

    result = run(args.alloc_gb)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for key, value in result.items():
            print(f"{key:28} {value}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
