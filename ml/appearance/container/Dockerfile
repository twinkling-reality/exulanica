# The generated appearance runner, behind its own container boundary.
#
# NOTHING IN THE REPOSITORY BUILDS THIS ON THE OPERATOR'S MAC. It is built on the rented machine,
# where a build downloads the model libraries and VideoX-Fun. Both bases are pinned by digest and the
# build refuses a tag; VideoX-Fun is pinned by commit AND by tree, so a moved branch cannot change
# what is installed. The build context is `ml/appearance`.
#
#   docker build -f container/Dockerfile \
#     --build-arg CODE_REVISION=<40 hex> -t exulanica-appearance:<revision> ml/appearance
#
# Run it with container/run.sh, which gives it no network, a read-only root, the staged inputs and
# the weights read-only, one writable output directory, and a hard time limit.
ARG PYTHON_BASE=python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_BASE} AS videox
ARG PYTHON_BASE
ARG VIDEOX_FUN_COMMIT=968f0e2192ba4c7a12868bf36d73260d135424ca
ARG VIDEOX_FUN_TREE=dd5401675c10b374f36a9e719e9cb8c0b1010792
RUN case "${PYTHON_BASE}" in *@sha256:*) ;; *) exit 1 ;; esac
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# Apache-2.0. The Fun union controls' own model cards name this repository as how to run them.
RUN git init --quiet /opt/videox-fun \
 && cd /opt/videox-fun \
 && git fetch --quiet --depth 1 https://github.com/aigc-apps/VideoX-Fun.git "${VIDEOX_FUN_COMMIT}" \
 && git checkout --quiet FETCH_HEAD \
 && test "$(git rev-parse HEAD)" = "${VIDEOX_FUN_COMMIT}" \
 && test "$(git rev-parse HEAD^{tree})" = "${VIDEOX_FUN_TREE}" \
 && printf '%s\n' "${VIDEOX_FUN_COMMIT}" > COMMIT \
 && rm -rf .git

FROM ${PYTHON_BASE}
ARG PYTHON_BASE
ARG CODE_REVISION
RUN case "${PYTHON_BASE}" in *@sha256:*) ;; *) exit 1 ;; esac
RUN python -c 'import os, re; assert re.fullmatch("[0-9a-f]{40}", os.environ["CODE_REVISION"])'
ENV EXULANICA_BUILD_REVISION=${CODE_REVISION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/appearance/.venv \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HOME=/tmp/huggingface \
    TORCHINDUCTOR_CACHE_DIR=/tmp/inductor \
    TRITON_CACHE_DIR=/tmp/triton \
    MPLCONFIGDIR=/tmp/matplotlib \
    NUMBA_CACHE_DIR=/tmp/numba
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=videox /opt/videox-fun /opt/videox-fun
WORKDIR /opt/appearance
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --extra gpu --no-dev --no-install-project
COPY exulanica_appearance ./exulanica_appearance
RUN uv sync --locked --extra gpu --no-dev \
 && /opt/appearance/.venv/bin/python -c "\
from exulanica_appearance.runner.backends import videox; videox._import_videox();\
import torch, videox_fun.pipeline as p;\
assert p.QwenImageControlPipeline and p.ZImageControlPipeline;\
print('import smoke passed', torch.__version__)" \
 && useradd --system --uid 10001 --no-create-home appearance
USER appearance
LABEL org.opencontainers.image.source="https://github.com/twinkling-reality/exulanica" \
      org.opencontainers.image.licenses="Apache-2.0"
ENTRYPOINT ["/opt/appearance/.venv/bin/python", "-m", "exulanica_appearance", "runner", "run"]
