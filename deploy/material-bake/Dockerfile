# The workspace material bake worker: the Exulanica package and the loom-texture baker, and nothing
# else. It has an image of its own because the baker is TypeScript run by Node, and the API image
# carries no Node.
#
# NOTHING IN THE REPOSITORY BUILDS THIS. Building it downloads Node, pnpm packages and Python
# wheels, so an operator builds it, with both bases pinned by digest (the build refuses a tag):
#
#   docker build -f deploy/material-bake/Dockerfile \
#     --build-arg NODE_BASE=node:22-bookworm-slim@sha256:<digest> \
#     --build-arg PYTHON_BASE=python:3.11-slim-bookworm@sha256:<digest> \
#     --build-arg CODE_REVISION=<40 hex> .
#
# And runs it with the database as its only network peer, a read-only root, the data directory as
# its only writable mount, and a container memory limit above the worker's own per-bake ceiling,
# which the worker enforces itself on every bake:
#
#   --read-only --tmpfs /tmp:rw,nosuid,size=256m --cap-drop ALL \
#   --security-opt no-new-privileges --memory 2g --pids-limit 64
#
# The baker runs from source under tsx, so the package source digest a receipt records names the
# files in this image, and the worker compares that digest with its own before it stores a byte.
ARG NODE_BASE
ARG PYTHON_BASE

FROM ${NODE_BASE} AS web
ARG NODE_BASE
RUN case "${NODE_BASE}" in *@sha256:*) ;; *) exit 1 ;; esac
RUN corepack enable
WORKDIR /opt/exulanica/web
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml web/tsconfig.base.json ./
COPY web/packages/loom-texture ./packages/loom-texture
# The root's development dependencies hold tsx; the lock file decides every version.
RUN pnpm install --frozen-lockfile --filter . --filter @exulanica/loom-texture \
 && node --import tsx -e "import('./packages/loom-texture/src/workspace/licence.ts')"

FROM ghcr.io/astral-sh/uv:0.9.5 AS uv

FROM ${PYTHON_BASE} AS runtime
ARG PYTHON_BASE
ARG CODE_REVISION
ENV EXULANICA_BUILD_REVISION=${CODE_REVISION}
RUN case "${PYTHON_BASE}" in *@sha256:*) ;; *) exit 1 ;; esac
# Refuse an unbound build, as the gsplat recipe does.
RUN python -c 'import os,re; assert re.fullmatch("[0-9a-f]{40}", os.environ["EXULANICA_BUILD_REVISION"])'
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=web /usr/local/bin/node /usr/local/bin/node
COPY --from=web /opt/exulanica/web /opt/exulanica/web
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/exulanica/.venv
WORKDIR /opt/exulanica/src
COPY pyproject.toml uv.lock LICENSE THIRD_PARTY_NOTICES.md ./
COPY exulanica ./exulanica
RUN uv sync --locked --no-dev --no-editable \
 && rm /usr/local/bin/uv
COPY assets/textures/manifest.json assets/textures/catalog.json /opt/exulanica/assets/textures/
COPY assets/textures/objects /opt/exulanica/assets/textures/objects
RUN groupadd --system --gid 10001 exulanica \
 && useradd --system --uid 10001 --gid 10001 --home-dir /opt/exulanica --no-create-home exulanica \
 && mkdir -p /var/lib/exulanica && chown exulanica:exulanica /var/lib/exulanica
ENV PATH=/opt/exulanica/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    EXULANICA_DATA_DIR=/var/lib/exulanica \
    EXULANICA_NODE=/usr/local/bin/node \
    EXULANICA_WEB_DIRECTORY=/opt/exulanica/web \
    EXULANICA_TEXTURE_DIRECTORY=/opt/exulanica/assets/textures
WORKDIR /opt/exulanica
USER exulanica
LABEL org.opencontainers.image.source="https://github.com/twinkling-reality/exulanica" \
      org.opencontainers.image.licenses="Apache-2.0"
CMD ["exulanica-material-bake"]
