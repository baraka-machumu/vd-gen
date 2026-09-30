#!/usr/bin/env bash
# ltx_spike.sh: Phase 0 spike. Run the official LTX-2.3 image-to-video pipeline natively on the GX10
# and record wall time + peak unified memory (modules M17/M18, ADR-004, ADR-007, spec §78, §80).
#
# Steps, in order (see docs/runbooks/p0-gx10-spike.md):
#   build       clone the official LTX-2 repo at LTX_GIT_REF and build the spike image on NGC PyTorch
#   list-files  list files + sizes in LTX_HF_REPO (and TEXT_ENCODER_HF_REPO) to choose downloads
#   download    download the selected weights and write a SHA256 manifest (spec §50)
#   discover    list the runnable pipeline modules in the repo and their --help output
#   run         run LTX_RUN_CMD LTX_RUNS times with NO network, measuring each run
#
# Config: scripts/spike/ltx_spike.env (copy from ltx_spike.env.example).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${LTX_SPIKE_ENV:-$REPO_ROOT/scripts/spike/ltx_spike.env}"
IMAGE_TAG="yas/ltx-spike:p0"
REPORT_DIR="$REPO_ROOT/reports/p0"

die() { echo "ERROR: $*" >&2; exit 1; }
[[ -f "$ENV_FILE" ]] || die "missing $ENV_FILE (cp scripts/spike/ltx_spike.env.example scripts/spike/ltx_spike.env)"
# shellcheck source=/dev/null
source "$ENV_FILE"
: "${NGC_IMAGE:?}" "${DATA_ROOT:?}" "${LTX_GIT_URL:?}" "${LTX_GIT_REF:?}"
[[ "$(uname -m)" == "aarch64" ]] || die "must run on the GX10 (aarch64); found $(uname -m)"

SRC_DIR="$DATA_ROOT/spike/src"
MODELS_DIR_HOST="$DATA_ROOT/models"
SPIKE_DIR_HOST="$DATA_ROOT/spike"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$REPORT_DIR" "$SRC_DIR" "$MODELS_DIR_HOST" "$SPIKE_DIR_HOST/output" "$SPIKE_DIR_HOST/input"

# Common docker run arguments: GPU, NVIDIA-recommended IPC/ulimits, read-only repo scripts.
docker_run() {
  docker run --rm --gpus all --ipc=host --ulimit memlock=-1 --ulimit stack=67108864 \
    -v "$MODELS_DIR_HOST:/models" -v "$SPIKE_DIR_HOST:/spike" \
    -v "$REPO_ROOT/scripts/spike:/opt/spike:ro" -v "$REPORT_DIR:/reports" \
    "$@"
}

require_image() {
  docker image inspect "$IMAGE_TAG" >/dev/null 2>&1 || die "image $IMAGE_TAG not built; run: $0 build"
}

cmd_build() {
  if [[ -d "$SRC_DIR/LTX-2/.git" ]]; then
    git -C "$SRC_DIR/LTX-2" fetch --tags origin
  else
    git clone "$LTX_GIT_URL" "$SRC_DIR/LTX-2"
  fi
  git -C "$SRC_DIR/LTX-2" checkout --detach "$LTX_GIT_REF" 2>/dev/null \
    || git -C "$SRC_DIR/LTX-2" checkout --detach "origin/$LTX_GIT_REF"
  local commit; commit="$(git -C "$SRC_DIR/LTX-2" rev-parse HEAD)"
  echo "LTX-2 source: $LTX_GIT_URL @ $commit"

  docker build -f "$REPO_ROOT/infra/docker/spike-ltx.Dockerfile" \
    --build-arg BASE_IMAGE="$NGC_IMAGE" -t "$IMAGE_TAG" "$SRC_DIR" 2>&1 | tee "$REPORT_DIR/ltx-build-$TS.log"

  local arch; arch="$(docker image inspect --format '{{.Architecture}}' "$IMAGE_TAG")"
  [[ "$arch" == "arm64" ]] || die "built image is $arch, expected arm64"
  printf '{\n  "ltx_git_url": "%s",\n  "ltx_commit": "%s",\n  "ngc_image": "%s",\n  "built_utc": "%s"\n}\n' \
    "$LTX_GIT_URL" "$commit" "$NGC_IMAGE" "$TS" > "$REPORT_DIR/ltx-build-$TS.json"
  echo "Built $IMAGE_TAG -> $REPORT_DIR/ltx-build-$TS.json"
}

cmd_list_files() {
  require_image
  : "${LTX_HF_REPO:?set LTX_HF_REPO}"
  docker_run -e HF_TOKEN="${HF_TOKEN:-}" "$IMAGE_TAG" python - "$LTX_HF_REPO" "${TEXT_ENCODER_HF_REPO:-}" <<'PY' \
    | tee "$REPORT_DIR/hf-files-$TS.txt"
import os, sys
from huggingface_hub import HfApi
api = HfApi(token=os.environ.get("HF_TOKEN") or None)
for repo in filter(None, sys.argv[1:]):
    info = api.model_info(repo, files_metadata=True)
    print(f"\n== {repo} @ {info.sha}")
    total = 0
    for s in sorted(info.siblings, key=lambda s: s.rfilename):
        size = s.size or 0
        total += size
        print(f"{size / 2**30:9.2f} GiB  {s.rfilename}")
    print(f"{total / 2**30:9.2f} GiB  TOTAL")
PY
}

cmd_download() {
  require_image
  : "${LTX_HF_REPO:?set LTX_HF_REPO}"
  [[ -n "${LTX_HF_INCLUDE:-}" ]] || die "set LTX_HF_INCLUDE (run '$0 list-files' to choose); refusing to download the whole repo"
  docker_run -e HF_TOKEN="${HF_TOKEN:-}" "$IMAGE_TAG" python - \
      "$LTX_HF_REPO" "${LTX_HF_INCLUDE}" "${TEXT_ENCODER_HF_REPO:-}" "${TEXT_ENCODER_HF_INCLUDE:-}" "/reports/models-manifest-$TS.json" <<'PY'
import hashlib, json, os, sys
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download

ltx_repo, ltx_inc, te_repo, te_inc, manifest_path = sys.argv[1:6]
token = os.environ.get("HF_TOKEN") or None
api = HfApi(token=token)
manifest = []
for repo, inc in ((ltx_repo, ltx_inc), (te_repo, te_inc)):
    if not repo:
        continue
    revision = api.model_info(repo).sha  # pin the exact commit we download
    local = Path("/models") / repo
    patterns = inc.split() or None
    print(f"Downloading {repo}@{revision} patterns={patterns} -> {local}", flush=True)
    snapshot_download(repo, revision=revision, allow_patterns=patterns, local_dir=local, token=token)
    for f in sorted(p for p in local.rglob("*") if p.is_file() and ".cache" not in p.parts):
        h = hashlib.sha256()
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 24), b""):
                h.update(chunk)
        manifest.append({"repository": repo, "revision": revision, "file": str(f.relative_to(local)),
                         "size_bytes": f.stat().st_size, "sha256": h.hexdigest()})
        print(f"  sha256 {h.hexdigest()}  {f.relative_to(local)}", flush=True)
json.dump(manifest, open(manifest_path, "w"), indent=2)
print(f"Manifest: {manifest_path}")
PY
}

cmd_discover() {
  require_image
  docker_run --network none "$IMAGE_TAG" python - <<'PY' 2>&1 | tee "$REPORT_DIR/ltx-discover-$TS.txt"
import importlib.metadata as md, importlib.util, pkgutil, subprocess, sys

dists = [d for d in md.distributions() if (d.metadata["Name"] or "").lower().startswith("ltx")]
print("LTX distributions:", ", ".join(f"{d.metadata['Name']}=={d.version}" for d in dists) or "NONE")
top = set()
for d in dists:
    top.update((d.read_text("top_level.txt") or "").split())
    for f in d.files or []:
        if f.suffix == ".py" and len(f.parts) > 1 and not f.parts[0].endswith((".dist-info", ".pth")):
            top.add(f.parts[0])
for name in list(top):
    if importlib.util.find_spec(name) is None:
        top.discard(name)
print("Top-level packages:", ", ".join(sorted(top)) or "NONE (editable installs: see /opt/ltx/packages)")

mains = []
for pkg in sorted(top):
    mod = importlib.import_module(pkg)
    for info in pkgutil.walk_packages(getattr(mod, "__path__", []), prefix=pkg + "."):
        spec = importlib.util.find_spec(info.name)
        origin = getattr(spec, "origin", None)
        if origin and origin.endswith(".py"):
            try:
                if '__name__ == "__main__"' in open(origin, encoding="utf-8").read():
                    mains.append(info.name)
            except OSError:
                pass
print("\nRunnable modules (have __main__):", *mains, sep="\n  ")
for m in mains:
    print(f"\n{'=' * 100}\n$ python -m {m} --help\n{'=' * 100}", flush=True)
    try:
        out = subprocess.run([sys.executable, "-m", m, "--help"], capture_output=True, text=True, timeout=120)
        print(out.stdout or out.stderr)
    except subprocess.TimeoutExpired:
        print("(timed out)")
PY
  echo "Also read the pipeline section of: $SRC_DIR/LTX-2/README.md"
}

cmd_run() {
  require_image
  [[ -n "${LTX_RUN_CMD:-}" ]] || die "set LTX_RUN_CMD in $ENV_FILE (use '$0 discover' to find the pipeline and flags)"
  local input_rel=""
  if [[ -n "${SPIKE_INPUT_IMAGE:-}" ]]; then
    [[ -f "$SPIKE_INPUT_IMAGE" ]] || die "SPIKE_INPUT_IMAGE not found: $SPIKE_INPUT_IMAGE"
    [[ "$SPIKE_INPUT_IMAGE" == "$SPIKE_DIR_HOST"/* ]] || die "put SPIKE_INPUT_IMAGE under $SPIKE_DIR_HOST so the container can see it"
    input_rel="/spike/${SPIKE_INPUT_IMAGE#"$SPIKE_DIR_HOST"/}"
  fi
  local runs="${LTX_RUNS:-2}" i label
  for ((i = 1; i <= runs; i++)); do
    label="ltx-i2v-run$i-$TS"
    mkdir -p "$SPIKE_DIR_HOST/output/$label"
    echo ">>> $label (network disabled: proves offline runtime, spec §73)"
    # --network none + HF offline flags: any attempt to download at runtime fails loudly.
    docker_run --network none \
      -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
      -e MODELS_DIR=/models -e INPUT_IMAGE="$input_rel" -e OUTPUT_DIR="/spike/output/$label" \
      -e PROMPT="${SPIKE_PROMPT:-}" -e LTX_RUN_CMD="$LTX_RUN_CMD" \
      "$IMAGE_TAG" \
      python /opt/spike/measure.py --out "/reports/$label.json" --log "/reports/$label.log" \
        --label "$label" -- bash -c "$LTX_RUN_CMD" \
      || echo "!!! $label failed; see $REPORT_DIR/$label.log"
  done
  echo; echo "Outputs: $SPIKE_DIR_HOST/output/   Reports: $REPORT_DIR/ltx-i2v-run*-$TS.json"
}

case "${1:-}" in
  build) cmd_build ;;
  list-files) cmd_list_files ;;
  download) cmd_download ;;
  discover) cmd_discover ;;
  run) cmd_run ;;
  *) sed -n '2,13p' "$0"; exit 2 ;;
esac
