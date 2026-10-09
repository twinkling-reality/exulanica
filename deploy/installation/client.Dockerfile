# The complete installation's browser client: the app's production bundle, served by nginx, which
# proxies /api to the API as the reviewer stack's web image does (deploy/judge/web.Dockerfile).
#
# The bundle is built on the host, from the offline pnpm store, at the exact commit the backend
# image is built from, and copied in. No package is fetched inside this build. Host toolchains are
# not byte-deterministic across Node versions, so the Node and pnpm versions, the commit and the
# digest of the built tree are build arguments the build refuses without, and labels on the image:
#
#   pnpm --filter @exulanica/app build
#   docker build -f deploy/installation/client.Dockerfile \
#     --build-arg EXULANICA_CODE_REVISION=<40 hex> --build-arg EXULANICA_CLIENT_TREE_SHA256=<64 hex> \
#     --build-arg EXULANICA_NODE_VERSION=<node --version> --build-arg EXULANICA_PNPM_VERSION=<pnpm --version> .
#
# The nginx configuration is deploy/installation/client-nginx.conf, which
# tests/test_installation_deployment.py holds equal to the reviewer image's.

# Every base is its version's multi-platform index by digest, the tag kept in the name for the reader:
# a build never resolves a moving tag, and one whose base is already held needs no registry
# (tests/test_base_images_pinned.py).
FROM nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de

ARG EXULANICA_CODE_REVISION
ARG EXULANICA_CLIENT_TREE_SHA256
ARG EXULANICA_NODE_VERSION
ARG EXULANICA_PNPM_VERSION
RUN echo "$EXULANICA_CODE_REVISION" | grep -Eq '^[0-9a-f]{40}$' \
 && echo "$EXULANICA_CLIENT_TREE_SHA256" | grep -Eq '^[0-9a-f]{64}$' \
 && test -n "$EXULANICA_NODE_VERSION" && test -n "$EXULANICA_PNPM_VERSION" \
 || { echo "client image: state the commit, the tree digest and the Node and pnpm versions" >&2; exit 1; }

LABEL org.opencontainers.image.source="https://github.com/twinkling-reality/exulanica" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.revision="${EXULANICA_CODE_REVISION}" \
      exulanica.client.tree-sha256="${EXULANICA_CLIENT_TREE_SHA256}" \
      exulanica.client.node-version="${EXULANICA_NODE_VERSION}" \
      exulanica.client.pnpm-version="${EXULANICA_PNPM_VERSION}"

COPY web/packages/app/dist /usr/share/nginx/html
COPY deploy/installation/client-nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/installation/client-trusted-proxies.conf /etc/nginx/exulanica-trusted-proxies.conf

EXPOSE 8080
