# The judge stack's browser client: build the bundle, then serve it beside a proxy to the API.
#
# The build context is the repository root, filtered by `web.Dockerfile.dockerignore` beside this
# file, an allowlist like the root `.dockerignore`. Not `web/` alone: the application bundles
# catalogs, character sources, the owned district and the texture set from `assets/`, and the
# interaction policy registry from `exulanica/world/`, by relative imports that leave `web/`
# (MEASURED 2026-09-29: a `web/` context fails `vite build` with "Could not resolve
# ../../../../assets/owned-world/..."). The repository layout is kept under /src, so those
# imports resolve unchanged. The server configuration is a heredoc so the image needs no file
# of its own.
#
# TWO THINGS HERE ARE LOAD BEARING and both are about the single origin:
#
#   1. The proxy strips `/api`. `proxy_pass http://api:8000/` WITH the trailing slash does that.
#      Without the slash every call arrives at the API as `/api/graph` and 404s. The Vite dev
#      server does the same strip with an explicit rewrite, so this matches development rather
#      than inventing a convention.
#   2. The bundle is served at the origin ROOT. `vite.config.ts` sets no `base`, so index.html
#      references `/assets/...` absolutely and serving it under a path prefix breaks every asset.

# The bundle is the same bytes on every architecture, so this stage runs on the build host's own
# platform and only the nginx stage below is built for the target. Building it under emulation
# fails outright: esbuild's install step segfaults under qemu (MEASURED 2026-09-29, a linux/amd64
# build on an arm64 host, exit 139 in `pnpm install`).
FROM --platform=$BUILDPLATFORM node:22-bookworm-slim AS build
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
# The version the workspace pins in `package.json`. Corepack rather than a global install, so the
# container resolves the same pnpm the lockfile was written by.
RUN corepack enable && corepack prepare pnpm@10.7.1 --activate
WORKDIR /src/web

# The lockfile and the workspace manifests first, so editing a source file does not re-resolve
# the dependency closure. `--frozen-lockfile` for the same reason the Python image uses
# `--locked`: a lockfile that no longer matches fails the build here rather than quietly
# resolving to something else.
COPY web/pnpm-lock.yaml web/pnpm-workspace.yaml web/package.json ./
# The shared TypeScript bases too. Every package's tsconfig.json extends `../../tsconfig.base.json`,
# and Vite reads that file during the build to learn the JSX and target settings, so a context
# without it fails with "failed to resolve extends" and zero modules transformed.
COPY web/tsconfig.json web/tsconfig.base.json ./
COPY web/packages ./packages
RUN --mount=type=cache,target=/pnpm/store pnpm install --frozen-lockfile

# Built LAST, and that ordering is not cosmetic. `pnpm check` runs `tsc --build` into the same
# `packages/app/dist` that Vite empties, so a build followed by a typecheck ships tsc artifacts
# beside the bundle. Only the bundle is wanted here.
#
# VITE_EXULANICA_TOKEN is deliberately NOT set. Baking it would publish the bearer token as a
# string literal inside the JavaScript, readable by anyone who can fetch the file. Left unset,
# the app renders its own token gate and the judge pastes the credential once.
# What the bundle imports from outside `web/`, at the paths its relative imports name.
COPY assets /src/assets
COPY exulanica/world/interaction-policy-registry.v1.json /src/exulanica/world/
RUN pnpm --filter @exulanica/app build

FROM nginx:1.29-alpine AS runtime
COPY --from=build /src/web/packages/app/dist /usr/share/nginx/html

COPY <<'CONF' /etc/nginx/conf.d/default.conf
# The client address a write is counted against. Behind the public edge every connection comes
# from the edge's container, so the address is taken from X-Forwarded-For, trusted only from the
# private ranges a container network is drawn from. The edge replaces that header with the address
# it accepted the connection from, so a visitor cannot choose it; with no edge in front, the
# address is whatever reached the loopback port.
set_real_ip_from 10.0.0.0/8;
set_real_ip_from 172.16.0.0/12;
set_real_ip_from 192.168.0.0/16;
real_ip_header X-Forwarded-For;

# Writes are counted; reads are not. An empty key is not limited, so GET, HEAD and OPTIONS pass
# freely and every other method is counted per client address.
map $request_method $exulanica_write_client {
    default $binary_remote_addr;
    GET "";
    HEAD "";
    OPTIONS "";
}

# At most one write every two seconds per address, with a burst of twenty served at once. Every
# route that can call a hosted model is a write, so this paces a script against the model budget
# while leaving a person's clicks alone. The figures are a stated bound, not a measurement of
# a person's pace; the process's model budget remains the ceiling on spend.
limit_req_zone $exulanica_write_client zone=exulanica_writes:10m rate=30r/m;
limit_req_status 429;

server {
    listen 8080;
    server_name _;
    root /usr/share/nginx/html;

    # BODY CAP. A reviewer's token cannot upload, but a Selection plan with a long question is a
    # POST body and a 413 from the proxy would look like the Companion refusing to answer, so the
    # cap is a generous 8 MiB rather than nginx's 1m default (deployment.md 8).
    client_max_body_size 8m;

    # This proxy's own refusals, in the problem shape the API answers with ({"code", "detail"}),
    # because the browser reads a failure's code and detail and nothing else. Answers from the API
    # pass through unchanged: proxy_intercept_errors is off, so these apply only to responses this
    # proxy makes itself.
    error_page 413 = @body_too_large;
    error_page 429 = @rate_limited;
    error_page 502 = @upstream_unavailable;
    error_page 504 = @upstream_timeout;

    # BODY CAP REFUSAL. Sending the same body again is refused again, so no Retry-After.
    location @body_too_large {
        default_type application/json;
        add_header Cache-Control "no-store" always;
        return 413 '{"code":"body_too_large","detail":"the request body is larger than the 8388608 bytes this installation accepts","limit_bytes":8388608}';
    }

    # The write limit below admits one write every two seconds per address after its burst.
    location @rate_limited {
        default_type application/json;
        add_header Retry-After "2" always;
        add_header Cache-Control "no-store" always;
        return 429 '{"code":"rate_limited","detail":"this address has sent more writes than this installation accepts at once; nothing was passed on, so the same request can be sent again after 2 seconds","retry_after_seconds":2}';
    }

    # The API closed the connection or could not be reached: restarting, stopped, or ended the
    # request early. Whether a request it had begun ran is not known, so the detail says so.
    location @upstream_unavailable {
        default_type application/json;
        add_header Retry-After "5" always;
        add_header Cache-Control "no-store" always;
        return 502 '{"code":"upstream_unavailable","detail":"the API closed the connection or could not be reached; whether the request ran is not known, so send it again after 5 seconds only if repeating it is safe","retry_after_seconds":5}';
    }

    # The API did not answer within proxy_read_timeout. The work may still finish, so no
    # Retry-After invites sending it a second time.
    location @upstream_timeout {
        default_type application/json;
        add_header Cache-Control "no-store" always;
        return 504 '{"code":"upstream_timeout","detail":"the API did not answer within 300 seconds; whether the request ran is not known"}';
    }

    # The API, same origin, prefix stripped by the trailing slash on proxy_pass.
    location /api/ {
        limit_req zone=exulanica_writes burst=20 nodelay;
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
