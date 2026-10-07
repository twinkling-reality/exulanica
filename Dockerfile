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
COPY exulanica_pieces ./exulanica_pieces
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
 && mkdir -p /app /var/lib/exulanica /var/lib/exulanica-restore /var/lib/exulanica-status \
    /var/lib/exulanica-spending-witness /var/lib/exulanica-backup /var/lib/exulanica-custody \
 && chown exulanica:exulanica /app /var/lib/exulanica /var/lib/exulanica-restore \
    /var/lib/exulanica-status /var/lib/exulanica-spending-witness /var/lib/exulanica-backup \
    /var/lib/exulanica-custody

# A named volume first mounted over one of these directories takes the directory's owner from
# the image, so the restore marker, the maintenance status and the spending witness are writable by
# the process that writes them and by no other user.
COPY --from=builder --chown=exulanica:exulanica /app/.venv /app/.venv
# The published material catalog, read-only: the makers a person's recipe is checked against,
# and the baked texture sets the reviewed furniture embeds. The API verifies every set the
# manifest names when it builds the object catalog at startup, so an image without the blobs
# serves nothing (MEASURED 2026-09-29: the API exited with TextureCatalogError on the first
# set). The bake worker has an image of its own (deploy/material-bake/Dockerfile) because it
# runs Node. `tests/test_image_ships_startup_reads.py` holds the blobs to this image.
COPY assets/textures/manifest.json /app/assets/textures/manifest.json
COPY assets/textures/catalog.json /app/assets/textures/catalog.json
COPY assets/textures/objects /app/assets/textures/objects
COPY assets/textures/blobs /app/assets/textures/blobs
# The versioned catalogs, and a link that puts them where the installed package reads them: a
# module finds a catalog two directories above its own file, which for this non-editable install
# is site-packages. Several are read when the package is imported, so an image without them
# cannot start any process. `tests/test_image_ships_import_reads.py` holds both lines.
COPY assets/catalogs /app/assets/catalogs
# The committed style pack library, which the API reads and holds to its digests when it starts and
# serves at /world/style-packs (exulanica/world/style_pack_library.py). About 1.1 MiB.
# `tests/test_image_ships_startup_reads.py` holds this line to what loading the library reads.
COPY assets/style-packs /app/assets/style-packs
# The character catalogs the image publishes (`exulanica-character-catalog publish --apply`, which
# every serving database runs after `exulanica-db`, as the `catalogs` jobs do): the people and the
# parametric family, with every container and licence they name. About 22 MB. The development
# preview's stylized examples stay out. `tests/test_image_ships_character_catalogs.py` holds these
# lines to what publishing reads.
COPY assets/characters/catalog.json assets/characters/looks.json /app/assets/characters/
COPY assets/characters/parametric-catalog.json /app/assets/characters/
COPY assets/characters/makehuman-people-v1 /app/assets/characters/makehuman-people-v1
COPY assets/characters/makehuman-parametric-v1 /app/assets/characters/makehuman-parametric-v1
# The looks imported from packs other makers published, each with its container, import receipt,
# licence and source reading (assets/catalogs/things/looks names each container by digest). About
# 0.6 MB. `tests/test_thing_imports.py` holds this line to the files the imported looks name.
COPY assets/things /app/assets/things
# The installation profiles an installation names by EXULANICA_INSTALLATION_PROFILE
# (docs/deployment.md 9.1).
COPY deploy/profiles /app/deploy/profiles
RUN ln -s /app/assets "$(/app/.venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/assets"

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    EXULANICA_DATA_DIR=/var/lib/exulanica \
    EXULANICA_TEXTURE_DIRECTORY=/app/assets/textures

WORKDIR /app
USER exulanica
EXPOSE 8000

# LIVENESS, never readiness. `/healthz` touches no dependency; `/readyz` opens a connection and
# an object store call. Docker and Compose only record a failing health check, they do not restart
# on it; an orchestrator that does would otherwise restart a container because its database
# blinked, which makes an incident worse. Written in Python because this image has no curl and
# does not need one.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"]

CMD ["uvicorn", "--factory", "exulanica.api.app:create_app", "--host", "0.0.0.0", "--port", "8000"]
