# The judge stack's browser client: build the bundle, then serve it beside a proxy to the API.
#
# The build context is `web/`, not the repository root. The root `.dockerignore` is an allowlist
# and `web/` is not on it, so a stage added to the root Dockerfile would receive an empty
# directory and produce an empty bundle without saying so. The server configuration is a heredoc
# rather than a file for the same reason from the other side: `web/` is not this change's to
# write into, and a config that lived in `deploy/judge/` would be outside the build context.
#
# TWO THINGS HERE ARE LOAD BEARING and both are about the single origin:
#
#   1. The proxy strips `/api`. `proxy_pass http://api:8000/` WITH the trailing slash does that.
#      Without the slash every call arrives at the API as `/api/graph` and 404s. The Vite dev
#      server does the same strip with an explicit rewrite, so this matches development rather
#      than inventing a convention.
#   2. The bundle is served at the origin ROOT. `vite.config.ts` sets no `base`, so index.html
#      references `/assets/...` absolutely and serving it under a path prefix breaks every asset.

FROM node:22-bookworm-slim AS build
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
# The version the workspace pins in `package.json`. Corepack rather than a global install, so the
# container resolves the same pnpm the lockfile was written by.
RUN corepack enable && corepack prepare pnpm@10.7.1 --activate
WORKDIR /src

# The lockfile and the workspace manifests first, so editing a source file does not re-resolve
# the dependency closure. `--frozen-lockfile` for the same reason the Python image uses
# `--locked`: a lockfile that no longer matches fails the build here rather than quietly
# resolving to something else.
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
# The shared TypeScript bases too. Every package's tsconfig.json extends `../../tsconfig.base.json`,
# and Vite reads that file during the build to learn the JSX and target settings, so a context
# without it fails with "failed to resolve extends" and zero modules transformed.
COPY tsconfig.json tsconfig.base.json ./
COPY packages ./packages
RUN --mount=type=cache,target=/pnpm/store pnpm install --frozen-lockfile

# Built LAST, and that ordering is not cosmetic. `pnpm check` runs `tsc --build` into the same
# `packages/app/dist` that Vite empties, so a build followed by a typecheck ships tsc artifacts
# beside the bundle. Only the bundle is wanted here.
#
# VITE_EXULANICA_TOKEN is deliberately NOT set. Baking it would publish the bearer token as a
# string literal inside the JavaScript, readable by anyone who can fetch the file. Left unset,
# the app renders its own token gate and the judge pastes the credential once.
RUN pnpm --filter @exulanica/app build

FROM nginx:1.29-alpine AS runtime
COPY --from=build /src/packages/app/dist /usr/share/nginx/html

COPY <<'CONF' /etc/nginx/conf.d/default.conf
server {
    listen 8080;
    server_name _;
    root /usr/share/nginx/html;

    # A generous ceiling rather than nginx's 1m default. Nothing a judge does uploads, but a
    # Selection plan with a long question is a POST body and a 413 from the proxy would look
    # like the Companion refusing to answer.
    client_max_body_size 8m;

    # The API, same origin, prefix stripped by the trailing slash on proxy_pass.
    location /api/ {
        proxy_pass http://api:8000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        # Answering a question runs a model call. The default 60s read timeout cuts that off and
        # the browser reports a network error rather than the answer that was on its way.
        proxy_read_timeout 300s;
        proxy_buffering off;
    }

    # Hashed bundle assets are immutable by name, so they may be cached hard. index.html must
    # not be, or a judge who reloads after a redeploy keeps the old bundle.
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # A single-page application: unknown paths are routes, not missing files.
    location / {
        try_files $uri $uri/ /index.html;
        add_header Cache-Control "no-cache";
    }
}
CONF

EXPOSE 8080
