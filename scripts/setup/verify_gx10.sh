#!/usr/bin/env bash
# verify_gx10.sh: Phase 0 hardware verification for the ASUS Ascent GX10 (spec §74, module M02).
#
# Reports what it DETECTS and never assumes (spec §78). Safe to re-run; it changes nothing on the host
# except pulling the NGC PyTorch image (skip with --no-pull) and writing a report under reports/p0/.
#
# Usage:
#   scripts/setup/verify_gx10.sh [--skip-container] [--no-pull] [--image IMAGE]
# Environment overrides:
#   NGC_IMAGE      NGC PyTorch image with arm64 + GB10 support (default below; check the NGC catalog)
#   DATA_ROOT      data volume to check for free space (default /data)
#   MIN_FREE_GB    minimum free space on DATA_ROOT (default 300)
#   MIN_MEMORY_GB  minimum visible unified memory (default 100; the OS reserves part of the 128 GB)
#
# Exit codes: 0 = PASS, 1 = FAIL or INCOMPLETE, 2 = usage error.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NGC_IMAGE="${NGC_IMAGE:-nvcr.io/nvidia/pytorch:25.11-py3}"
DATA_ROOT="${DATA_ROOT:-/data}"
MIN_FREE_GB="${MIN_FREE_GB:-300}"
MIN_MEMORY_GB="${MIN_MEMORY_GB:-100}"
REPORT_DIR="${REPORT_DIR:-$REPO_ROOT/reports/p0}"
SKIP_CONTAINER=0
PULL=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-container) SKIP_CONTAINER=1 ;;
    --no-pull) PULL=0 ;;
    --image) NGC_IMAGE="${2:?--image needs a value}"; shift ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

declare -A STATUS DETAIL
ORDER=()
# Checks that must PASS for overall PASS. Everything else is informational (WARN/INFO).
REQUIRED=(architecture nvidia gpu_model cuda unified_memory docker nvidia_container_runtime storage pytorch_cuda)

record() { ORDER+=("$1"); STATUS[$1]="$2"; DETAIL[$1]="$3"; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- Architecture -------------------------------------------------------------------------------
ARCH="$(uname -m)"
if [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then
  record architecture PASS "$ARCH"
else
  record architecture FAIL "$ARCH (expected aarch64)"
fi

# --- Platform / OS (informational) --------------------------------------------------------------
PRODUCT="$(cat /sys/devices/virtual/dmi/id/product_name 2>/dev/null || echo unknown)"
VENDOR="$(cat /sys/devices/virtual/dmi/id/sys_vendor 2>/dev/null || echo unknown)"
if [[ "${PRODUCT^^}" == *GX10* ]]; then
  record platform PASS "$VENDOR $PRODUCT"
else
  record platform WARN "$VENDOR $PRODUCT (GX10 not found in DMI product name)"
fi

OS_NAME="unknown"
[[ -r /etc/os-release ]] && OS_NAME="$(. /etc/os-release && echo "${PRETTY_NAME:-unknown}")"
DGX_RELEASE=""
[[ -r /etc/dgx-release ]] && DGX_RELEASE="$(grep -E '^DGX_(SWBUILD_VERSION|OTA_VERSION|PLATFORM)=' /etc/dgx-release | tr '\n' ' ')"
record os INFO "$OS_NAME${DGX_RELEASE:+ | $DGX_RELEASE}"

# --- NVIDIA driver / GPU ------------------------------------------------------------------------
GPU_NAME=""
if have nvidia-smi && GPU_CSV="$(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>&1)"; then
  GPU_NAME="$(echo "$GPU_CSV" | head -1 | cut -d, -f1 | xargs)"
  DRIVER="$(echo "$GPU_CSV" | head -1 | cut -d, -f2 | xargs)"
  CC="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 | xargs)"
  record nvidia PASS "driver $DRIVER, compute capability ${CC:-unknown}"
  if [[ "${GPU_NAME^^}" == *GB10* ]]; then
    record gpu_model PASS "$GPU_NAME"
  else
    record gpu_model FAIL "${GPU_NAME:-none} (expected NVIDIA GB10)"
  fi
else
  record nvidia FAIL "nvidia-smi missing or failing: ${GPU_CSV:-not installed}"
  record gpu_model FAIL "no GPU detected"
fi

# --- CUDA ---------------------------------------------------------------------------------------
CUDA_DRIVER="$(nvidia-smi 2>/dev/null | grep -oE 'CUDA Version: *[0-9.]+' | grep -oE '[0-9.]+$' | head -1)"
NVCC_VER="$(nvcc --version 2>/dev/null | grep -oE 'release [0-9.]+' | grep -oE '[0-9.]+$')"
if [[ -n "$CUDA_DRIVER" ]]; then
  record cuda PASS "driver supports CUDA $CUDA_DRIVER; host nvcc ${NVCC_VER:-not installed (not required: containers ship the toolkit)}"
else
  record cuda FAIL "CUDA version not reported by nvidia-smi"
fi

# --- Unified memory -----------------------------------------------------------------------------
if [[ -r /proc/meminfo ]]; then
  MEM_TOTAL_GB="$(awk '/^MemTotal:/ {printf "%.1f", $2/1048576}' /proc/meminfo)"
  MEM_AVAIL_GB="$(awk '/^MemAvailable:/ {printf "%.1f", $2/1048576}' /proc/meminfo)"
  GPU_MEM="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null | head -1 | xargs)"
  DETAIL_MEM="total ${MEM_TOTAL_GB} GiB, available ${MEM_AVAIL_GB} GiB, nvidia-smi memory.total: ${GPU_MEM:-n/a}"
  if awk -v t="$MEM_TOTAL_GB" -v m="$MIN_MEMORY_GB" 'BEGIN {exit !(t >= m)}'; then
    record unified_memory PASS "$DETAIL_MEM"
  else
    record unified_memory FAIL "$DETAIL_MEM (< ${MIN_MEMORY_GB} GiB)"
  fi
else
  MEM_TOTAL_GB="unknown"
  record unified_memory FAIL "/proc/meminfo not readable"
fi

# --- Docker -------------------------------------------------------------------------------------
DOCKER_OK=0
if have docker && DOCKER_VER="$(docker version --format '{{.Server.Version}}' 2>&1)"; then
  DOCKER_OK=1
  record docker PASS "server $DOCKER_VER"
  if BUILDX="$(docker buildx version 2>/dev/null)"; then
    record docker_buildx PASS "$(echo "$BUILDX" | awk '{print $2}')"
  else
    record docker_buildx WARN "docker buildx not available (needed later for image builds, spec §75)"
  fi
  RUNTIMES="$(docker info --format '{{json .Runtimes}}' 2>/dev/null)"
  CTK="$(nvidia-ctk --version 2>/dev/null | head -1)"
  if [[ "$RUNTIMES" == *nvidia* || -n "$CTK" ]]; then
    record nvidia_container_runtime PASS "${CTK:-nvidia runtime registered}"
  else
    record nvidia_container_runtime FAIL "NVIDIA Container Toolkit not found (nvidia-ctk / docker nvidia runtime)"
  fi
else
  record docker FAIL "docker unavailable: ${DOCKER_VER:-not installed} (if 'permission denied': add user to the docker group and re-login)"
  record docker_buildx WARN "skipped (docker unavailable)"
  record nvidia_container_runtime FAIL "skipped (docker unavailable)"
fi

# --- Storage ------------------------------------------------------------------------------------
STORAGE_PATH="$DATA_ROOT"
[[ -d "$STORAGE_PATH" ]] || STORAGE_PATH="/"
if DF_LINE="$(df -BG --output=avail,size,pcent "$STORAGE_PATH" 2>/dev/null | tail -1)"; then
  AVAIL_GB="$(echo "$DF_LINE" | awk '{gsub("G","",$1); print $1}')"
  SIZE_GB="$(echo "$DF_LINE" | awk '{gsub("G","",$2); print $2}')"
  USED_PCT="$(echo "$DF_LINE" | awk '{print $3}')"
  NOTE=""
  [[ "$STORAGE_PATH" != "$DATA_ROOT" ]] && NOTE=" ($DATA_ROOT does not exist yet; checked /)"
  D="${AVAIL_GB} GB free of ${SIZE_GB} GB on $STORAGE_PATH, ${USED_PCT} used$NOTE"
  if (( AVAIL_GB >= MIN_FREE_GB )); then record storage PASS "$D"; else record storage FAIL "$D (< ${MIN_FREE_GB} GB)"; fi
else
  AVAIL_GB="unknown"
  record storage FAIL "df failed on $STORAGE_PATH"
fi

# --- PyTorch CUDA inside the NGC container ------------------------------------------------------
mkdir -p "$REPORT_DIR"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
HOST="$(hostname -s 2>/dev/null || hostname)"
SMOKE_JSON="$REPORT_DIR/gpu_smoke-$HOST-$TS.json"
SMOKE_LOG="$REPORT_DIR/gpu_smoke-$HOST-$TS.log"

if (( SKIP_CONTAINER )); then
  record pytorch_cuda SKIP "container check skipped (--skip-container)"
elif (( ! DOCKER_OK )); then
  record pytorch_cuda FAIL "docker unavailable"
else
  if ! docker image inspect "$NGC_IMAGE" >/dev/null 2>&1; then
    if (( PULL )); then
      echo "Pulling $NGC_IMAGE (first run only, several GB)..." >&2
      docker pull "$NGC_IMAGE" >&2 || true
    fi
  fi
  if ! docker image inspect "$NGC_IMAGE" >/dev/null 2>&1; then
    record pytorch_cuda FAIL "image $NGC_IMAGE not available (pull failed or --no-pull; set NGC_IMAGE to a valid arm64 tag)"
  else
    IMG_ARCH="$(docker image inspect --format '{{.Architecture}}' "$NGC_IMAGE" 2>/dev/null)"
    if [[ "$IMG_ARCH" != "arm64" ]]; then
      record pytorch_cuda FAIL "image $NGC_IMAGE is $IMG_ARCH, not arm64: refusing to emulate (spec §37)"
    elif docker run --rm --gpus all --ipc=host --ulimit memlock=-1 --ulimit stack=67108864 \
          -v "$REPO_ROOT/scripts/health:/opt/health:ro" "$NGC_IMAGE" \
          python /opt/health/gpu_smoke.py --json >"$SMOKE_JSON" 2>"$SMOKE_LOG"; then
      SUMMARY="$(python3 - "$SMOKE_JSON" <<'PY' 2>/dev/null || echo "see $SMOKE_JSON"
import json, sys
path = sys.argv[1]
# The NGC entrypoint prints a banner to stdout before our JSON: keep only the JSON object, and rewrite the
# file so it is clean JSON for later readers.
lines = open(path, encoding="utf-8").read().splitlines()
r = json.loads("\n".join(lines[lines.index("{"):]))
json.dump(r, open(path, "w", encoding="utf-8"), indent=2)
print(f"torch {r['torch_version']} (CUDA {r['torch_cuda_version']}), {r['device_name']} sm_{r['capability']}, "
      f"bf16 matmul {r['matmul_bf16_tflops']} TFLOPS, SDPA backends ok: {','.join(r['sdpa_backends_ok']) or 'none'}")
PY
)"
      record pytorch_cuda PASS "$SUMMARY"
    else
      record pytorch_cuda FAIL "gpu_smoke.py failed in $NGC_IMAGE: see $SMOKE_LOG"
    fi
  fi
fi

# --- Verdict ------------------------------------------------------------------------------------
OVERALL=PASS
for k in "${REQUIRED[@]}"; do
  case "${STATUS[$k]}" in
    PASS) ;;
    SKIP) [[ "$OVERALL" == PASS ]] && OVERALL=INCOMPLETE ;;
    *) OVERALL=FAIL ;;
  esac
done

ARCH_LABEL="$ARCH"; [[ "$ARCH" == "aarch64" ]] && ARCH_LABEL="arm64"
cat <<EOF

GX10 compatibility: $OVERALL

Architecture: $ARCH_LABEL
NVIDIA: ${STATUS[nvidia]}
CUDA: ${STATUS[cuda]}
PyTorch CUDA: ${STATUS[pytorch_cuda]}
Unified memory: ${MEM_TOTAL_GB}GB
Docker: ${STATUS[docker]}
Storage: ${STATUS[storage]}

Details:
EOF
for k in "${ORDER[@]}"; do
  printf '  %-26s %-5s %s\n' "$k" "${STATUS[$k]}" "${DETAIL[$k]}"
done

# --- JSON report --------------------------------------------------------------------------------
REPORT="$REPORT_DIR/verify_gx10-$HOST-$TS.json"
if have python3; then
  # Checks go through a temp file: the heredoc below is python's stdin, so a pipe would be discarded.
  CHECKS_TSV="$(mktemp)"
  for k in "${ORDER[@]}"; do printf '%s\t%s\t%s\n' "$k" "${STATUS[$k]}" "${DETAIL[$k]}"; done >"$CHECKS_TSV"
  python3 - "$REPORT" "$OVERALL" "$HOST" "$TS" "$NGC_IMAGE" "$SMOKE_JSON" "$CHECKS_TSV" <<'PY'
import json, os, sys
out, overall, host, ts, image, smoke, checks_tsv = sys.argv[1:8]
checks = {}
for line in open(checks_tsv, encoding="utf-8"):
    key, status, detail = line.rstrip("\n").split("\t", 2)
    checks[key] = {"status": status, "detail": detail}
report = {"overall": overall, "host": host, "timestamp_utc": ts, "ngc_image": image, "checks": checks}
if os.path.exists(smoke) and os.path.getsize(smoke) > 0:
    try:
        lines = open(smoke, encoding="utf-8").read().splitlines()
        report["gpu_smoke"] = json.loads("\n".join(lines[lines.index("{"):]))
    except (ValueError, json.JSONDecodeError):
        report["gpu_smoke"] = None
json.dump(report, open(out, "w"), indent=2)
PY
  rm -f "$CHECKS_TSV"
  echo; echo "Report: $REPORT"
else
  echo; echo "python3 not found on host: JSON report not written."
fi

[[ "$OVERALL" == PASS ]] && exit 0 || exit 1
