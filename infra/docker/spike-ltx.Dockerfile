# P0 spike image: NGC PyTorch (arm64) + official Lightricks LTX-2 repo (ADR-004, ADR-007).
# Built by scripts/spike/ltx_spike.sh build; the build context is $DATA_ROOT/spike/src (contains LTX-2/).
# The NGC torch/CUDA stack is pinned: the build FAILS if pip tries to replace torch, rather than silently
# installing a generic wheel that may lack GB10 kernels.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

COPY LTX-2/ /opt/ltx/
WORKDIR /opt/ltx

RUN python -c "import importlib.metadata as md; \
[print(f'{d}=={md.version(d)}') for d in ('torch','torchvision','torchaudio','triton','pytorch-triton','transformer-engine','flash-attn','apex') \
 if d in {x.metadata['Name'].lower() for x in md.distributions()}]" > /opt/ngc-constraints.txt
RUN set -eux; \
    cat /opt/ngc-constraints.txt; \
    python -c 'import torch; print(torch.__version__)' > /opt/torch-before.txt; \
    if ls packages/*/pyproject.toml >/dev/null 2>&1; then \
        targets="$(for d in packages/*/; do [ -f "$d/pyproject.toml" ] && printf -- '-e ./%s ' "$d"; done)"; \
    else \
        targets="-e ."; \
    fi; \
    echo "Installing: $targets"; \
    PIP_CONSTRAINT=/opt/ngc-constraints.txt pip install $targets "huggingface_hub>=0.26"; \
    python -c 'import torch; print(torch.__version__)' > /opt/torch-after.txt; \
    diff /opt/torch-before.txt /opt/torch-after.txt
