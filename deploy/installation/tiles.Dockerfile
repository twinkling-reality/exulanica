# The generated-tile worker: the backend image with Node and the tessellator, compiled.
#
# It runs `exulanica-generated-tile-worker`, which bakes each tile of a generated world twice in a
# Node child process and publishes the bake as `exulanica_tiles` (migration 0138). Compose builds
# it from the API's image (`additional_contexts: backend: service:api`), as maintenance does.
#
# THE TESSELLATOR ARRIVES COMPILED. `web/packages/loom-tess` imports nothing but Node's own
# modules, so `tsc --build tsconfig.node.json` turns it into plain JavaScript with no dependency to
# install: no `node_modules`, no `tsx`, and no esbuild binary, whose install step segfaults when a
# linux/amd64 image is built under emulation on an arm64 host (deploy/judge/web.Dockerfile). The
# build host compiles it into `web/packages/loom-tess/dist` before this build
# (`deploy/public/public.sh build`), and the build refuses to start without it. Compiled and `tsx`
# bakes give the same container bytes (`tests/test_generated_tile_runner.py`).
#
# Node itself is copied from the pinned official image, binary only.

FROM node:22-bookworm-slim AS node

FROM backend

COPY --from=node /usr/local/bin/node /usr/local/bin/node
# `type: module` is what makes Node read the compiled `.js` files as ES modules.
COPY web/packages/loom-tess/package.json /app/tess/package.json
COPY web/packages/loom-tess/dist/src /app/tess/src

ENV EXULANICA_NODE=/usr/local/bin/node \
    EXULANICA_TESS_CLI=/app/tess/src/node/cli.js

# Refuse an image whose tessellator was not compiled or does not run here.
RUN test -f "$EXULANICA_TESS_CLI" && "$EXULANICA_NODE" "$EXULANICA_TESS_CLI" params >/dev/null

CMD ["exulanica-generated-tile-worker"]
