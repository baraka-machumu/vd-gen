# Runbook: P0 GX10 bring-up & LTX-2.3 spike

**Goal (Phase 0 exit criteria, [MODULES.md](../MODULES.md)):**
1. `verify_gx10.sh` passes on the device.
2. One LTX-2.3 image-to-video clip is generated **natively** on the GB10, with no network at runtime.
3. Wall time and peak unified memory are recorded.

**Who:** the product owner (ADR-012). **Time:** about 1–3 hours, mostly downloads.
Every step writes its results to `reports/p0/`. Send that folder back so the results can go into `docs/models.md` and the plan.

---

## 0. Prerequisites on the GX10

- DGX OS installed and updated, logged in as a user in the `docker` group (`groups | grep docker`).
- Internet access **for setup only** (NGC image, GitHub, Hugging Face).
- A Hugging Face account. If the text encoder is gated, accept its license on huggingface.co and create a read token.
- About 300 GB free on the data disk.

```bash
# Create the data root once (uses sudo only here):
sudo mkdir -p /data && sudo chown "$USER":"$USER" /data

# Get the repo onto the GX10 (git clone from your remote, or copy the folder):
cd ~ && git clone <your-remote>/yas-video-generator.git && cd yas-video-generator
chmod +x scripts/setup/verify_gx10.sh scripts/spike/ltx_spike.sh
```

## 1. Hardware verification

```bash
scripts/setup/verify_gx10.sh
```

- The first run pulls the NGC PyTorch image (~20 GB).
- If the default tag doesn't exist or isn't arm64, pick a current one from the NGC catalog (`nvcr.io/nvidia/pytorch`, tags `YY.MM-py3`) and re-run with it:
  `NGC_IMAGE=nvcr.io/nvidia/pytorch:<tag> scripts/setup/verify_gx10.sh`
- **Expected result:** `GX10 compatibility: PASS`. In the details, look at the `pytorch_cuda` line:
  - `native_kernels_for_device`: `true` in the JSON is what we want. If it is `false`, the image is falling back to JIT, and we need a newer image.
  - `matmul_bf16_tflops` and the SDPA backends that worked.

**Stop here if the result is FAIL** and send `reports/p0/`.

## 2. Configure the spike

```bash
cp scripts/spike/ltx_spike.env.example scripts/spike/ltx_spike.env
nano scripts/spike/ltx_spike.env   # set NGC_IMAGE to the tag that PASSED in step 1; set HF_TOKEN
```

Put an input image at `/data/spike/input/keyframe.png`. **Don't use an employee photo yet** (no consent records exist; ADR-012). An office/object photo or a picture of yourself is fine.

## 3. Build the spike image

```bash
scripts/spike/ltx_spike.sh build
```

This clones the official `Lightricks/LTX-2` repo and installs it on top of NGC PyTorch.
**If the build fails with a `diff` error at the end,** the LTX dependencies tried to replace NGC's torch. Send `reports/p0/ltx-build-*.log`; don't work around it.

## 4. Choose and download weights

```bash
scripts/spike/ltx_spike.sh list-files    # shows every file + size in the HF repo(s)
```

1. Check `LTX_HF_REPO` in the env file. Open the official Lightricks Hugging Face page and the LTX-2 README (`/data/spike/src/LTX-2/README.md`) and confirm the LTX-2.3 repo id and which text encoder is required.
2. Set `LTX_HF_INCLUDE` to the **minimum** needed: the distilled checkpoint (faster, which is right for a spike) plus whatever the README says the pipeline requires (e.g. spatial upscaler). Set `TEXT_ENCODER_HF_REPO`/`_INCLUDE` if the encoder is separate.
3. Then run:

```bash
scripts/spike/ltx_spike.sh download      # writes reports/p0/models-manifest-*.json (repo, revision, SHA256)
```

## 5. Discover the pipeline command

```bash
scripts/spike/ltx_spike.sh discover      # lists runnable pipeline modules + their --help
```

Pick the image-to-video pipeline (the distilled one is fine), then set `LTX_RUN_CMD` in the env file using `$MODELS_DIR`, `$INPUT_IMAGE`, `$OUTPUT_DIR` and `$PROMPT`. Use a modest first target of 5–6 s at the pipeline's default resolution; don't start at 1080p or with long clips.
**If you're unsure of the flags, stop and send `reports/p0/ltx-discover-*.txt`.** The command can be filled in from it.

## 6. Run and measure

```bash
scripts/spike/ltx_spike.sh run
```

- It runs `LTX_RUNS` times (default 2), each with the **network disabled**. That also proves spec §73: the runtime works offline.
- Watch in a second terminal if you like: `watch -n2 'free -g; nvidia-smi --query-gpu=utilization.gpu,power.draw,temperature.gpu --format=csv'`.
- The output video is in `/data/spike/output/<run>/`. Play it and note whether it looks right.

## 7. What to send back

The whole `reports/p0/` folder (the JSON, log and txt files are small), plus one line saying whether the clip looked correct.
From those results the spike is recorded in `docs/models.md` (time/clip, peak memory, working kernels), the throughput NFR is set (review M3), and the scheduler memory profile (ADR-005) is updated.

## Troubleshooting

| Symptom | Likely cause / action |
|---|---|
| `permission denied ... docker.sock` | `sudo usermod -aG docker $USER`, then log out and back in |
| `could not select device driver "" with capabilities: [[gpu]]` | NVIDIA Container Toolkit missing or not configured: `sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker` |
| `native_kernels_for_device: false` | Use a newer NGC tag |
| Run fails with a network/download error | A file is missing from the download (the runtime is offline by design): add it to `*_INCLUDE` and re-run `download` |
| Out-of-memory / system freeze | Lower resolution/duration first, then report the numbers; don't enable swap-heavy workarounds |
