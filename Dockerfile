# The default image serves the API, migrates, and runs the pose worker. Compose builds the
# derivative worker from the same source with the depth extra instead, keeping torch and pycolmap
# out of one process while retaining one reviewed recipe.
#
# There is no ENTRYPOINT, only a CMD. An entrypoint would make the migration one-shot and make
# the ingest job reach for `--entrypoint`, and the whole point of one image is that they do not.
#
# WHAT THE DEFAULT CONTAINS is the small CPU pose extra. The derivative-worker build argument
# selects the torch depth extra. Every citation still resolves to original bytes because
# reconstruction is never evidence.

FROM ghcr.io/astral-sh/uv:0.9.5 AS uv

FROM python:3.11-slim-trixie AS builder
COPY --from=uv /uv /usr/local/bin/uv
# The locked depth extra names source repositories at exact commits. Git exists only in this
# discarded builder stage; no package manager or Git binary reaches the runtime image.
RUN apt-get update \
 && apt-get install --yes --no-install-recommends g++ git libx11-dev \
 && rm -rf /var/lib/apt/lists/*
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
ARG EXULANICA_SYNC_EXTRAS="--extra server --extra pose"

# Dependencies first and the project second, so editing a source file does not re-resolve the
# closure. `--locked` rather than `--frozen`: a uv.lock that no longer matches pyproject.toml
# fails the build here, which makes the image a third place the lock is checked rather than the
# first place it is quietly ignored.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project ${EXULANICA_SYNC_EXTRAS}

# The package directory is copied, and it is not optional: without it hatchling builds an empty
# wheel, uv installs that over the working one, and the image's own entry points raise
# ModuleNotFoundError at start. `tests/test_deployment.py` asserts this COPY exists.
COPY pyproject.toml uv.lock LICENSE THIRD_PARTY_NOTICES.md ./
COPY exulanica ./exulanica
# The project wheel is rebuilt unconditionally: a cache mount that outlives the previous build must
# never let an older wheel of this package shadow the sources COPYed just above.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --reinstall-package exulanica ${EXULANICA_SYNC_EXTRAS}

FROM python:3.11-slim-trixie AS runtime
LABEL org.opencontainers.image.source="https://github.com/twinkling-reality/exulanica"
LABEL org.opencontainers.image.licenses="Apache-2.0"

# The only apt packages, and each one is here for the SOG compressor's GPU path: psycopg[binary]
# ships its own libpq and Pillow its own image libraries, so nothing else is needed from Debian.
# libvulkan1 is the Vulkan loader the compressor's WebGPU backend opens when the scene worker runs
# on a GPU host with the NVIDIA runtime's graphics capability. The NVIDIA Vulkan ICD it loads is
# libGLX_nvidia.so.0, which links libX11 and libXext even with no display, and its glcore library
# resolves the ErrorF symbol from libglvnd's GLX dispatch (MEASURED 2026-09-06: without them the
# loader reported "libX11.so.6: cannot open shared object file", then "undefined symbol: ErrorF",
# and found no driver). Without a GPU every one of these is inert. Every package added here is a
# package somebody has to patch.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libvulkan1 libx11-6 libxext6 libglvnd0 libglx0 libgl1 libegl1 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 exulanica \
 && useradd --system --uid 10001 --gid 10001 --home-dir /app --no-create-home exulanica \
 && mkdir -p /app /var/lib/exulanica \
 && chown exulanica:exulanica /app /var/lib/exulanica

COPY --from=builder --chown=exulanica:exulanica /app/.venv /app/.venv

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    EXULANICA_DATA_DIR=/var/lib/exulanica

WORKDIR /app
USER exulanica
EXPOSE 8000

# LIVENESS, never readiness. `/healthz` touches no dependency; `/readyz` opens a connection and
# an object store call, and a container restarted because its database blinked is a container
# that makes an incident worse. Written in Python because this image has no curl and does not
# need one.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"]

CMD ["uvicorn", "--factory", "exulanica.api.app:create_app", "--host", "0.0.0.0", "--port", "8000"]
