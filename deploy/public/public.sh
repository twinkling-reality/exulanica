#!/usr/bin/env bash
# The public server: the installation composition behind its TLS edge, as one command per step.
# docs/deployment.md section 8.2 is the runbook that calls it.
#
#   EXULANICA_DEPLOY_DIR=<secrets directory> deploy/public/public.sh <command>
#
#   build             on the build host: the client bundle and the compiled tessellator, then the four
#                     built images, from a clean checkout, and the database and edge images pulled
#                     by digest, six in all
#   images            print each image's ID and platform
#   save <file>       write the six images to one gzip archive and print its sha256
#   init              write <dir>/public.env: generated passwords, the operator's token, the values below
#   mint <label>      a rehearsal visitor: a token for a workspace of its own
#   revoke <label>    delete that rehearsal token; `up` then serves without it
#   up                start the server; the first run installs, migrates and publishes the catalogs
#   prepare-towns     make the arrival worlds once in the operator's workspace, so their tiles bake,
#                     and dress each with the scene the arrival list names
#   issue-authority   issue the server's spending authority from the EXULANICA_AUTHORITY_* values
#   guest-policy      set what each guest is granted under it, from the EXULANICA_GUEST_* values
#   guest-policy-withdraw  end the guest policy: no guest is granted anything until another is set
#   grant <label>     grant a rehearsal visitor's workspace an allowance under the authority
#   spending          the authority's state, as the operator command prints it
#   backup-now        one maintenance pass now: export, backup set and verification when due
#   status            the containers, readiness from inside, and disk use
#   watch             one health check through the edge; recreates the API after three failures
#   preflight         check every model identifier against the provider's public catalog
#   logs [service]    follow the logs
#   down              stop the server and keep its volumes
#   destroy           stop the server and delete its volumes, database, store and witness included
#
# `init` reads EXULANICA_PUBLIC_HOST, EXULANICA_TLS (internal for a rehearsal, acme for a public
# certificate authority with no contact, or a contact email), EXULANICA_EDGE_ADDRESS, EXULANICA_BACKUP_PATH,
# EXULANICA_CUSTODY_PATH and EXULANICA_GUEST_ENTRY (off, open or code, with
# EXULANICA_GUEST_ENTRY_CODE, at least 20 characters, and EXULANICA_GUEST_ENTRIES_PER_DAY) from the
# environment, and optionally the port settings. The entry code itself is never written: only its
# sha256. It leaves
# EXULANICA_BUDGET_USD and EXULANICA_BUDGET_MAX_CALLS empty, and `up` refuses until both are filled.
#
# SECRETS. Database passwords and tokens live in files created mode 0600 inside a directory
# created mode 0700. The model credential is never written to a file: `up` passes NEBIUS_API_KEY
# through from the calling shell, and without it every route that asks a model says so.
#
# The server never builds or pulls: `up` runs images loaded by name and refuses when one is
# missing, so what serves is what was built, pulled and checked on the build host.

set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
project="${EXULANICA_PUBLIC_PROJECT:-exulanica-public}"
backend_image="exulanica-public-backend"
maintenance_image="exulanica-public-maintenance"
client_image="exulanica-public-client"
tiles_image="exulanica-public-tiles"
postgres_image="exulanica-public-postgres"
edge_image="exulanica-public-edge"
images="$backend_image $maintenance_image $client_image $tiles_image $postgres_image $edge_image"
# The two images the server runs as published: compose.yaml's PostgreSQL and the reviewer edge's
# Caddy, each its version's multi-platform index by digest. The build pulls the build platform's
# image from it and names it as above, so a host never resolves a tag and the local tags other
# stacks on the build host use are left as they are.
postgres_source="pgvector/pgvector:0.8.6-pg18"
postgres_digest="sha256:2ba9ca5f2e7daa0f0e7723cba1ee9167bab54efd3640516a44ac1a928dd67e7a"
edge_source="caddy:2.11.4-alpine"
edge_digest="sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b"
# Each index's linux/amd64 image, as the registries listed it when the index was pinned. An image
# already held under that digest is tagged without asking the registry, so a registry outage does
# not stop a build whose images are all here; another platform reads the index as before.
postgres_amd64_digest="sha256:1d50c689b0a6511b9ea0a15615281c81a59fd04a08eb35057ec8646fb3a2118a"
edge_amd64_digest="sha256:040e9f7480b80b6d4a7e5013a21159b950a63dcbdb956e38abe2387fb28d9ec0"

case "${1:-}" in
  "" | build | images | save) deploy_dir="" ;;
  *) deploy_dir="${EXULANICA_DEPLOY_DIR:?set EXULANICA_DEPLOY_DIR to the directory that holds the secrets of this server}" ;;
esac
env_file="$deploy_dir/public.env"
token_dir="$deploy_dir/tokens"
tokens_file="$deploy_dir/tokens.json"
authority_file="$deploy_dir/authority.json"
watch_state="$deploy_dir/watch-failures"
proxy_state="$deploy_dir/watch-proxy-failures"
edge_state="$deploy_dir/watch-edge-failures"

refuse() {
  echo "public.sh: $*" >&2
  exit 2
}

# Whether a host name is one a public certificate authority can certify: lower-case DNS labels
# ending in a letter top-level label (so no IP literal), with no scheme, port or whitespace, and
# not a name only a private network resolves.
public_dns_name() {
  printf '%s' "$1" | grep -Eq '^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?[.])+[a-z]{2,63}$' || return 1
  case "$1" in
    *.localhost | *.local | *.internal | *.test | *.invalid | *.example | *.home.arpa) return 1 ;;
  esac
}

# The edge's certificate line (deploy/public/Caddyfile) for EXULANICA_TLS, checked against the
# host it is for and the edge's address: `tls internal` only on a loopback edge, since no browser
# trusts Caddy's local authority; a public authority (acme, with no contact, or a contact email)
# only for a public DNS name, since Caddy would otherwise fall back to its local authority without
# saying so. Called by init and by every compose call, so a hand edit of public.env is checked too;
# a placeholder in the Caddyfile stands for a whole line, so nothing else gets through.
tls_directive() {
  local tls="$1" host="$2" address="$3"
  case "$tls" in
    "" | *[[:space:]]*) refuse "EXULANICA_TLS is internal, acme or a contact email" ;;
    internal)
      case "$address" in
        127.0.0.1 | ::1 | localhost) printf 'tls internal' ;;
        *) refuse "EXULANICA_TLS=internal is Caddy's local authority, which no browser trusts: only for an edge on a loopback address, not $address" ;;
      esac
      ;;
    *)
      if [ "$tls" != acme ]; then
        printf '%s' "$tls" | grep -Eq '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}$' \
          || refuse "EXULANICA_TLS is internal, acme or a contact email"
      fi
      public_dns_name "$host" \
        || refuse "EXULANICA_TLS=$tls asks a public certificate authority, which certifies only a public DNS name in lower case; $host is not one (use the server's sslip.io name, never its bare address)"
      [ "$tls" = acme ] || printf 'tls %s' "$tls"
      ;;
  esac
}

need_env_file() {
  [ -f "$env_file" ] || refuse "$env_file does not exist; run init first"
}

# Reads one value from the env file without sourcing it, so nothing in it is executed.
env_value() {
  sed -n "s/^$1=//p" "$env_file" | tail -n 1 | sed "s/^'\(.*\)'\$/\1/"
}

# The workspaces the tokens name, as the API and the workers read them: a JSON array of the
# rehearsal visitors' workspaces (whose societies this server plays and whose people it may ask
# models for), and a comma list of every token's workspace (which the workers may drain).
token_workspaces() {
  python3 - "$token_dir" "$1" <<'PY'
import json, pathlib, sys
directory, form = pathlib.Path(sys.argv[1]), sys.argv[2]
visitors, every = [], []
for part in sorted(directory.glob("*.json")):
    for grant in json.loads(part.read_text(encoding="utf-8")).values():
        every.append(grant["workspace_id"])
        if part.name != "operator.json":
            visitors.append(grant["workspace_id"])
print(json.dumps(sorted(set(visitors))) if form == "visitors" else ",".join(sorted(set(every))))
PY
}

compose() {
  # Compose interpolates every service before any command, so the settings no `up` would lack are
  # given here: the merged token directory and the workspaces it names. A marker stands in for the
  # tokens before any is minted; only `up` hands them to an API, and `up` refuses first.
  if [ -s "$tokens_file" ]; then
    EXULANICA_API_TOKENS="$(cat "$tokens_file")"
    EXULANICA_SOCIETY_CONTROL_WORKSPACES="$(token_workspaces visitors)"
    EXULANICA_WORKSPACE_IDS="$(token_workspaces every)"
  else
    EXULANICA_API_TOKENS="no-token-minted"
    EXULANICA_SOCIETY_CONTROL_WORKSPACES="[]"
    EXULANICA_WORKSPACE_IDS="00000000-0000-0000-0000-000000000000"
  fi
  export EXULANICA_API_TOKENS EXULANICA_SOCIETY_CONTROL_WORKSPACES EXULANICA_WORKSPACE_IDS
  # The certificate line is derived here on every call, never stored, so it always follows
  # EXULANICA_TLS as written now and passes init's checks.
  EXULANICA_TLS_DIRECTIVE="$(tls_directive "$(env_value EXULANICA_TLS)" \
    "$(env_value EXULANICA_PUBLIC_HOST)" "$(env_value EXULANICA_EDGE_ADDRESS)")" || exit 2
  export EXULANICA_TLS_DIRECTIVE
  # The tile worker's compose profile is always on here: the public profile installs it.
  docker compose -p "$project" --project-directory "$root" --env-file "$env_file" \
    -f "$root/compose.yaml" -f "$here/public.yaml" --profile tiles "$@"
}

merge_tokens() {
  # Every token file, merged into the one directory the API loads, written through a descriptor
  # opened 0600.
  python3 - "$token_dir" "$tokens_file" <<'PY'
import json, os, pathlib, sys
merged = {}
for part in sorted(pathlib.Path(sys.argv[1]).glob("*.json")):
    merged.update(json.loads(part.read_text(encoding="utf-8")))
descriptor = os.open(sys.argv[2], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(merged, handle, sort_keys=True)
print(f"{len(merged)} token(s) in {sys.argv[2]}", file=sys.stderr)
PY
}

# An owner-connected one-shot in the backend image, on the server's network, for host
# administration that no runtime role may do. The owner URL reaches the container through the
# environment of this process, never its command line.
owner_run() {
  local password database user
  password="$(env_value POSTGRES_PASSWORD)"
  database="$(env_value POSTGRES_DB)"
  user="$(env_value POSTGRES_USER)"
  EXULANICA_DATABASE_URL="postgresql://${user:-exulanica}:${password}@postgres:5432/${database:-exulanica}" \
    docker run --rm -i --pull never --network "${project}_default" \
    -e EXULANICA_DATABASE_URL \
    -e EXULANICA_SPENDING_WITNESS_DIR=/var/lib/exulanica-spending-witness \
    -v "${project}_spending-witness:/var/lib/exulanica-spending-witness" \
    "$backend_image" "$@"
}

command="${1:-}"
case "$command" in
  build)
    # From a clean checkout, so an image holds exactly the commit it names. A rehearsal on a
    # working tree states EXULANICA_REHEARSAL_BUILD=1; its images still name HEAD, so they are
    # rehearsal images and never the ones a server loads.
    cd "$root"
    revision="$(git rev-parse HEAD)"
    if [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
      [ "${EXULANICA_REHEARSAL_BUILD:-}" = 1 ] \
        || refuse "the checkout has changes; build from a clean checkout of the commit to serve"
      echo "public.sh: building a rehearsal from a working tree with changes on $revision" >&2
    fi
    if env | grep -q '^VITE_'; then
      refuse "a VITE_ variable is set; the bundle would carry it (a token among them)"
    fi
    # The client bundle is built here from the offline store and copied into the client image, as
    # deploy/installation/client.Dockerfile requires, with its provenance as build arguments.
    (cd web && pnpm --filter @exulanica/app build)
    # The tessellator compiled to JavaScript for the tile worker's image, which carries no package
    # manager and no dependency (deploy/installation/tiles.Dockerfile).
    (cd web/packages/loom-tess && rm -rf dist && ../../node_modules/.bin/tsc --build tsconfig.node.json)
    tree_sha256="$(python3 - web/packages/app/dist <<'PY'
import hashlib, pathlib, sys
dist = pathlib.Path(sys.argv[1])
lines = sorted(
    f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(dist).as_posix()}\n"
    for p in dist.rglob("*") if p.is_file()
)
print(hashlib.sha256("".join(lines).encode()).hexdigest())
PY
)"
    # Compose interpolates every service's settings before it builds anything, so the run-time
    # values are given a marker; none of them is a build argument, and none reaches an image.
    marker="build-only-not-a-secret"
    POSTGRES_PASSWORD="$marker" EXULANICA_APP_ROLE_PASSWORD="$marker" \
      EXULANICA_EXECUTOR_ROLE_PASSWORD="$marker" EXULANICA_PURGE_ROLE_PASSWORD="$marker" \
      EXULANICA_BACKUP_ROLE_PASSWORD="$marker" EXULANICA_API_TOKENS="$marker" \
      EXULANICA_WORKSPACE_IDS="$marker" EXULANICA_BACKUP_PATH="$here" EXULANICA_CUSTODY_PATH="$here" \
      EXULANICA_EDGE_ADDRESS=127.0.0.1 EXULANICA_PUBLIC_HOST="$marker" EXULANICA_TLS=internal \
      EXULANICA_TLS_DIRECTIVE="tls internal" \
      EXULANICA_PUBLIC_ORIGIN="https://$marker" \
      EXULANICA_BUDGET_USD="$marker" EXULANICA_BUDGET_MAX_CALLS="$marker" \
      EXULANICA_CODE_REVISION="$revision" EXULANICA_CLIENT_TREE_SHA256="$tree_sha256" \
      EXULANICA_NODE_VERSION="$(node --version)" EXULANICA_PNPM_VERSION="$(cd web && pnpm --version)" \
      DOCKER_DEFAULT_PLATFORM="${EXULANICA_BUILD_PLATFORM:-linux/amd64}" \
      docker compose -p "$project" --project-directory "$root" \
      -f "$root/compose.yaml" -f "$here/public.yaml" --profile tiles build api maintenance client tile-worker
    platform="${EXULANICA_BUILD_PLATFORM:-linux/amd64}"
    for pinned in "$postgres_image ${postgres_source%%:*}@$postgres_digest $postgres_amd64_digest" \
      "$edge_image ${edge_source%%:*}@$edge_digest $edge_amd64_digest"; do
      name="${pinned%% *}" rest="${pinned#* }" source="${rest%% *}" amd64="${rest#* }"
      if [ "$platform" = linux/amd64 ] \
        && docker image inspect "${source%@*}@$amd64" >/dev/null 2>&1; then
        docker tag "${source%@*}@$amd64" "$name"
        continue
      fi
      # The build platform's own manifest, read from the pinned index (content-addressed, so the
      # digest inside it is the index's) and pulled by that digest: one store cannot hold two
      # platforms' images under one index digest.
      manifest="$(docker buildx imagetools inspect --raw "$source" | python3 -c '
import json, sys
os_name, arch = sys.argv[1].split("/")[:2]
found = [m["digest"] for m in json.load(sys.stdin)["manifests"]
         if m.get("platform", {}).get("os") == os_name
         and m.get("platform", {}).get("architecture") == arch]
print(found[0] if len(found) == 1 else "")
' "$platform")"
      [ -n "$manifest" ] || refuse "$source has no single $platform image"
      docker pull --quiet "${source%@*}@$manifest"
      docker tag "${source%@*}@$manifest" "$name"
    done
    "$0" images
    ;;

  images)
    for image in $images; do
      printf '%s %s %s\n' "$image" \
        "$(docker image inspect --format '{{.Id}}' "$image")" \
        "$(docker image inspect --format '{{.Architecture}}' "$image")"
    done
    ;;

  save)
    file="${2:?name the archive to write, for example public-images.tar.gz}"
    [ -e "$file" ] && refuse "$file exists"
    # shellcheck disable=SC2086
    docker save $images | gzip >"$file"
    shasum -a 256 "$file" 2>/dev/null || sha256sum "$file"
    ;;

  init)
    [ -e "$env_file" ] && refuse "$env_file exists; delete it deliberately to start again"
    : "${EXULANICA_PUBLIC_HOST:?set EXULANICA_PUBLIC_HOST to the host name visitors open}"
    : "${EXULANICA_TLS:?set EXULANICA_TLS to internal for a rehearsal, acme for a public authority with no contact, or a contact email}"
    : "${EXULANICA_EDGE_ADDRESS:?set EXULANICA_EDGE_ADDRESS; 0.0.0.0 on a public host, 127.0.0.1 in a rehearsal}"
    # Checked here and again by every compose call, which derives the line itself.
    tls_directive "$EXULANICA_TLS" "$EXULANICA_PUBLIC_HOST" "$EXULANICA_EDGE_ADDRESS" >/dev/null \
      || exit 2
    : "${EXULANICA_BACKUP_PATH:?set EXULANICA_BACKUP_PATH to a directory on storage apart from the database and media}"
    : "${EXULANICA_CUSTODY_PATH:?set EXULANICA_CUSTODY_PATH to a directory apart from the backup directory}"
    for path in "$EXULANICA_BACKUP_PATH" "$EXULANICA_CUSTODY_PATH"; do
      [ -d "$path" ] || refuse "$path is not a directory"
    done
    backup="$(cd "$EXULANICA_BACKUP_PATH" && pwd -P)"
    custody="$(cd "$EXULANICA_CUSTODY_PATH" && pwd -P)"
    case "$custody/" in "$backup/"*) refuse "custody must not be inside the backup directory" ;; esac
    : "${EXULANICA_GUEST_ENTRY:?set EXULANICA_GUEST_ENTRY to off, open or code}"
    guest_code_sha256=""
    case "$EXULANICA_GUEST_ENTRY" in
      off) ;;
      open | code)
        : "${EXULANICA_GUEST_ENTRIES_PER_DAY:?set EXULANICA_GUEST_ENTRIES_PER_DAY; the limit of each day is a figure the operator states}"
        if [ "$EXULANICA_GUEST_ENTRY" = code ]; then
          : "${EXULANICA_GUEST_ENTRY_CODE:?set EXULANICA_GUEST_ENTRY_CODE to the code visitors are given}"
          # Only the code's unsalted SHA-256 is kept, and a wrong code is answered at once, so a
          # short code falls to guessing: twenty characters or more.
          [ "${#EXULANICA_GUEST_ENTRY_CODE}" -ge 20 ] \
            || refuse "EXULANICA_GUEST_ENTRY_CODE is at least 20 characters"
          guest_code_sha256="$(printf '%s' "$EXULANICA_GUEST_ENTRY_CODE" | openssl dgst -sha256 -r | cut -d' ' -f1)"
        fi
        ;;
      *) refuse "EXULANICA_GUEST_ENTRY is off, open or code" ;;
    esac
    https_port="${EXULANICA_EDGE_HTTPS_PORT:-443}"
    public_origin="https://$EXULANICA_PUBLIC_HOST"
    [ "$https_port" = 443 ] || public_origin="$public_origin:$https_port"
    umask 077
    mkdir -p "$deploy_dir" "$token_dir"
    chmod 700 "$deploy_dir" "$token_dir"
    secret() { openssl rand -hex 24; }
    cat >"$env_file" <<ENV
# Written by public.sh init. Mode 0600: it holds database passwords. Never copy it off this host.
POSTGRES_PASSWORD=$(secret)
EXULANICA_APP_ROLE_PASSWORD=$(secret)
EXULANICA_EXECUTOR_ROLE_PASSWORD=$(secret)
EXULANICA_PURGE_ROLE_PASSWORD=$(secret)
EXULANICA_BACKUP_ROLE_PASSWORD=$(secret)
EXULANICA_ACCOUNT_ROLE_PASSWORD=$(secret)
EXULANICA_TILES_ROLE_PASSWORD=$(secret)
EXULANICA_PROFILE=public
EXULANICA_BACKUP_PATH=$backup
EXULANICA_CUSTODY_PATH=$custody
EXULANICA_PUBLIC_HOST=$EXULANICA_PUBLIC_HOST
EXULANICA_PUBLIC_ORIGIN=$public_origin
EXULANICA_TLS=$EXULANICA_TLS
EXULANICA_EDGE_ADDRESS=$EXULANICA_EDGE_ADDRESS
EXULANICA_EDGE_HTTP_PORT=${EXULANICA_EDGE_HTTP_PORT:-80}
EXULANICA_EDGE_HTTPS_PORT=${EXULANICA_EDGE_HTTPS_PORT:-443}
# The process fuse in USD and in calls, for one API process life. Filled in by the operator; up
# refuses until both are. The durable authority (issue-authority) is the money.
EXULANICA_BUDGET_USD=
EXULANICA_BUDGET_MAX_CALLS=
# The origins the API may reach. The API checks at startup that the model endpoint is in it.
EXULANICA_EGRESS_ALLOWLIST='["https://api.tokenfactory.nebius.com"]'
# The guest entry: off, open, or code (only the code's sha256 is kept), and the day's limit.
EXULANICA_GUEST_ENTRY=$EXULANICA_GUEST_ENTRY
EXULANICA_GUEST_ENTRY_CODE_SHA256=$guest_code_sha256
EXULANICA_GUEST_ENTRIES_PER_DAY=${EXULANICA_GUEST_ENTRIES_PER_DAY:-}
EXULANICA_GUEST_SESSION_SECONDS=${EXULANICA_GUEST_SESSION_SECONDS:-}
# How long after a guest's last request their town plays, and how many guests' towns play at once;
# empty takes the defaults (fifteen minutes, 24).
EXULANICA_GUEST_PLAY_SECONDS=${EXULANICA_GUEST_PLAY_SECONDS:-}
EXULANICA_GUEST_PLAYING_MAXIMUM=${EXULANICA_GUEST_PLAYING_MAXIMUM:-}
# How many towns' claims one playback round runs at once. 4 by default here: measured with 12 and
# 24 model-run towns, four workers played about 4 minutes a minute per town against one worker's
# 1 to 2, every answer accepted (docs/deployment.md 5.1.5).
EXULANICA_PLAYBACK_WORKERS=${EXULANICA_PLAYBACK_WORKERS:-4}
ENV
    # The operator's own token: a workspace of its own and operations.read alone, for the
    # installation facts, capacity and spending reads. It makes no world and asks no model.
    python3 - "$token_dir/operator.json" <<'PY'
import json, os, secrets, sys, uuid
grant = {secrets.token_urlsafe(32): {
    "workspace_id": str(uuid.uuid4()), "actor": str(uuid.uuid4()), "permissions": ["operations.read"],
}}
descriptor = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(grant, handle)
PY
    merge_tokens
    echo "wrote $env_file (mode 0600); fill in EXULANICA_BUDGET_USD and EXULANICA_BUDGET_MAX_CALLS"
    ;;

  mint)
    need_env_file
    label="${2:?give the visitor a label, for example rehearsal-1}"
    case "$label" in
      operator | *[!A-Za-z0-9_-]*) refuse "a label is letters, digits, hyphens and underscores, and not operator" ;;
    esac
    [ -e "$token_dir/$label.json" ] && refuse "$label already has a token; revoke it first"
    workspace="$(python3 -c 'import uuid; print(uuid.uuid4())')"
    umask 077
    # The image's own command mints the token, so the grant's permissions come from the one place
    # that declares them. It runs as the calling user so the file it writes is that user's.
    docker run --rm --pull never --user "$(id -u):$(id -g)" -v "$token_dir:/out" "$backend_image" \
      exulanica-seed token --workspace "$workspace" --out "/out/$label.json" >/dev/null
    merge_tokens
    echo "minted $label for workspace $workspace; run up to serve it"
    ;;

  revoke)
    need_env_file
    label="${2:?name the label to revoke}"
    [ "$label" = operator ] && refuse "the operator's token is not revoked here"
    [ -f "$token_dir/$label.json" ] || refuse "$label has no token"
    rm -f "$token_dir/$label.json"
    merge_tokens
    echo "run up to stop serving it"
    ;;

  up)
    need_env_file
    [ -s "$tokens_file" ] || refuse "no token file; run init first"
    [ -n "$(env_value EXULANICA_BUDGET_USD)" ] && [ -n "$(env_value EXULANICA_BUDGET_MAX_CALLS)" ] \
      || refuse "fill in EXULANICA_BUDGET_USD and EXULANICA_BUDGET_MAX_CALLS in $env_file"
    for image in $images; do
      docker image inspect "$image" >/dev/null 2>&1 \
        || refuse "$image is not loaded on this host; load the images built and checked elsewhere"
    done
    # Only the edge publishes a port. The API trusts forwarded headers from anything that reaches
    # it (FORWARDED_ALLOW_IPS), and the client proxy trusts X-Forwarded-For from private ranges, so
    # a published port on either would let a local process choose its scheme or counted address.
    # Checked on the merged configuration, which is what Compose runs, not on the overlay's text.
    published="$(compose config --format json | python3 -c '
import json, sys
services = json.load(sys.stdin)["services"]
print(" ".join(name for name in ("api", "client") if services.get(name, {}).get("ports")))
')"
    [ -z "$published" ] || refuse "these services publish a port, which only the edge may: $published"
    if [ -z "${NEBIUS_API_KEY:-}" ]; then
      echo "NEBIUS_API_KEY is not set: every route that asks a model will say no credential is configured" >&2
    fi
    # What the installation facts name as its identity: the images this server runs.
    EXULANICA_IMAGE_BACKEND="$(docker image inspect --format '{{.Id}}' "$backend_image")"
    EXULANICA_IMAGE_CLIENT="$(docker image inspect --format '{{.Id}}' "$client_image")"
    EXULANICA_CODE_REVISION="$(docker image inspect \
      --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$client_image")"
    export EXULANICA_IMAGE_BACKEND EXULANICA_IMAGE_CLIENT EXULANICA_CODE_REVISION
    # restore-marker, migrate and catalogs run to completion on every up, before the API: the
    # first writes the restore marker only on an empty database, the second applies what is new,
    # the third publishes the catalogs the image carries.
    compose up -d --wait --no-build --pull never
    # A service that exits at once can read healthy for a moment before its first restart (an
    # nginx configuration it refuses, for one), so `up` looks again a few seconds later.
    sleep 5
    restarting="$(compose ps --status restarting --services)"
    [ -z "$restarting" ] || refuse "these services keep restarting; read their logs: $restarting"
    compose ps
    ;;

  prepare-towns)
    # The arrival worlds (exulanica/world/arrival-worlds.v1.json in the image) made once in the
    # operator's own workspace, as the runtime role, inside the API's container, and each dressed
    # with the scene the list names for it, as every guest's copy is. The tile worker drains that
    # workspace and bakes them; run again to read each tile's state. Exits 1 when a dressing is
    # incomplete, naming the step's code.
    need_env_file
    workspace="$(python3 -c 'import json,sys; print(next(iter(json.load(open(sys.argv[1])).values()))["workspace_id"])' "$token_dir/operator.json")"
    compose exec -T api python -m exulanica.api.arrival_dressing prepare --workspace "$workspace"
    ;;

  issue-authority)
    need_env_file
    [ -e "$authority_file" ] && refuse "$authority_file exists: this server has its authority; adjust it with the spending command"
    : "${EXULANICA_AUTHORITY_USD:?set EXULANICA_AUTHORITY_USD to the model allowance of this server in USD}"
    : "${EXULANICA_AUTHORITY_CALLS:?set EXULANICA_AUTHORITY_CALLS to its call limit}"
    : "${EXULANICA_AUTHORITY_VALID_UNTIL:?set EXULANICA_AUTHORITY_VALID_UNTIL, for example 2026-11-15T00:00:00Z}"
    umask 077
    owner_run python -m exulanica.spending issue --provider nebius_token_factory \
      --ceiling-usd "$EXULANICA_AUTHORITY_USD" --max-calls "$EXULANICA_AUTHORITY_CALLS" \
      --valid-until "$EXULANICA_AUTHORITY_VALID_UNTIL" --operator public-server \
      --reason "the public server's allowance" >"$authority_file.answer"
    # The authority's identifier as the command answered it, with the validity it was issued for,
    # which every grant under it repeats.
    python3 - "$authority_file.answer" "$EXULANICA_AUTHORITY_VALID_UNTIL" "$authority_file" <<'PY'
import json, os, sys
answer = json.loads(open(sys.argv[1], encoding="utf-8").read())
record = {"authority_id": answer["authority_id"], "valid_until": sys.argv[2], "answer": answer}
descriptor = os.open(sys.argv[3], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(record, handle, sort_keys=True)
PY
    rm -f "$authority_file.answer"
    cat "$authority_file"
    ;;

  grant)
    need_env_file
    label="${2:?name the rehearsal visitor to grant}"
    [ -f "$token_dir/$label.json" ] || refuse "$label has no token"
    [ -f "$authority_file" ] || refuse "no authority yet; run issue-authority first"
    : "${EXULANICA_GRANT_USD:?set EXULANICA_GRANT_USD to the allowance of this visitor in USD}"
    : "${EXULANICA_GRANT_CALLS:?set EXULANICA_GRANT_CALLS to its call limit}"
    authority="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["authority_id"])' "$authority_file")"
    workspace="$(python3 -c 'import json,sys; print(next(iter(json.load(open(sys.argv[1])).values()))["workspace_id"])' "$token_dir/$label.json")"
    valid_until="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["valid_until"])' "$authority_file")"
    owner_run python -m exulanica.spending grant --authority "$authority" --workspace "$workspace" \
      --ceiling-usd "$EXULANICA_GRANT_USD" --max-calls "$EXULANICA_GRANT_CALLS" \
      --valid-until "$valid_until" --operator public-server --reason "rehearsal visitor $label"
    ;;

  guest-policy)
    # What each guest workspace is granted under the server's authority, once, by the runtime's
    # guest step (migration 0139). Replaces the policy it had; grants already made stay.
    need_env_file
    [ -f "$authority_file" ] || refuse "no authority yet; run issue-authority first"
    : "${EXULANICA_GUEST_USD:?set EXULANICA_GUEST_USD to what each guest may spend, in USD}"
    : "${EXULANICA_GUEST_CALLS:?set EXULANICA_GUEST_CALLS to the call limit of each guest}"
    : "${EXULANICA_GUEST_DAYS:?set EXULANICA_GUEST_DAYS to how long the allowance of a guest lasts, 1 to 31}"
    # How many guests the policy grants in a UTC day, counted by the database whatever asks: the
    # day's entries unless stated.
    grants_per_day="${EXULANICA_GUEST_GRANTS_PER_DAY:-$(env_value EXULANICA_GUEST_ENTRIES_PER_DAY)}"
    [ -n "$grants_per_day" ] \
      || refuse "set EXULANICA_GUEST_GRANTS_PER_DAY, or EXULANICA_GUEST_ENTRIES_PER_DAY in $env_file"
    authority="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["authority_id"])' "$authority_file")"
    owner_run python -m exulanica.spending guest-policy --authority "$authority" \
      --ceiling-usd "$EXULANICA_GUEST_USD" --max-calls "$EXULANICA_GUEST_CALLS" \
      --valid-for-days "$EXULANICA_GUEST_DAYS" --grants-per-day "$grants_per_day" \
      --operator public-server --reason "each visitor's allowance on the public server"
    ;;

  guest-policy-withdraw)
    need_env_file
    [ -f "$authority_file" ] || refuse "no authority yet; run issue-authority first"
    authority="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["authority_id"])' "$authority_file")"
    owner_run python -m exulanica.spending guest-policy-withdraw --authority "$authority" \
      --operator public-server --reason "${EXULANICA_GUEST_WITHDRAW_REASON:-withdrawn by the operator}"
    ;;

  spending)
    need_env_file
    [ -f "$authority_file" ] || refuse "no authority yet; run issue-authority first"
    owner_run python -m exulanica.spending status --authorities
    ;;

  backup-now)
    need_env_file
    compose exec -T maintenance exulanica-installation maintenance --once
    ;;

  status)
    need_env_file
    compose ps
    # Readiness from inside the client container, which reaches the API over the compose network,
    # so this answers even while the edge or its certificate is the problem.
    compose exec -T client wget -q -O - http://api:8000/readyz || true
    echo
    docker system df
    df -h "$(env_value EXULANICA_BACKUP_PATH)" "$(env_value EXULANICA_CUSTODY_PATH)"
    ;;

  watch)
    # One check, for a timer to run every minute, of three paths, each with its own count of
    # failures in a row:
    # - the API's own liveness, read from inside the client container over the compose network.
    #   Docker never restarts a container whose health check fails (deployment.md section 9), so
    #   three failures recreate the API container, which keeps the model credential of the one it
    #   replaces;
    # - the path the edge takes, read from inside the edge container: the client proxy, then the
    #   API. While the API is well, three failures here mean the proxy cannot reach it (nginx finds
    #   `api` by name once, at its start), so they restart the client proxy, never the API;
    # - the public edge itself, over TLS. It is reported, never repaired: an edge or a certificate
    #   that fails (a failed issuance, a rate limit) is fixed by neither restart. From the third
    #   failure in a row every check that repaired nothing logs `edge failing`, for the journal.
    # Readiness is logged too, never acted on: a dependency that is down is not fixed that way.
    need_env_file
    host="$(env_value EXULANICA_PUBLIC_HOST)"
    port="$(env_value EXULANICA_EDGE_HTTPS_PORT)"
    address="$(env_value EXULANICA_EDGE_ADDRESS)"
    [ "$address" = 0.0.0.0 ] && address=127.0.0.1
    origin="https://$host:${port:-443}"
    # Resolve the host name to this machine, so the check reads this server's edge and its
    # certificate rather than whatever DNS answers. A rehearsal's internal authority is not
    # trusted by the system, so its certificate is not verified there.
    insecure=""
    [ "$(env_value EXULANICA_TLS)" = internal ] && insecure="--insecure"
    live="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 $insecure \
      --resolve "$host:${port:-443}:$address" "$origin/api/healthz" || true)"
    ready="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 $insecure \
      --resolve "$host:${port:-443}:$address" "$origin/api/readyz" || true)"
    inside="$(compose exec -T client sh -c \
      'wget -q -T 10 -O /dev/null http://api:8000/healthz && echo 200 || echo 000' 2>/dev/null \
      || echo 000)"
    proxied="$(compose exec -T edge sh -c \
      'wget -q -T 10 -O /dev/null http://client:8080/api/healthz && echo 200 || echo 000' \
      2>/dev/null || echo 000)"
    count() { # <state file> <passed: yes or no>: the failures in a row, written back
      local n=0
      [ -f "$1" ] && n="$(cat "$1")"
      if [ "$2" = yes ]; then n=0; else n=$((n + 1)); fi
      echo "$n" >"$1"
      echo "$n"
    }
    failures="$(count "$watch_state" "$([ "$inside" = 200 ] && echo yes || echo no)")"
    # The proxy's path counts only while the API is well; otherwise the API's own count acts.
    proxy_failures="$(count "$proxy_state" \
      "$([ "$inside" != 200 ] || [ "$proxied" = 200 ] && echo yes || echo no)")"
    edge_failures="$(count "$edge_state" "$([ "$live" = 200 ] && echo yes || echo no)")"
    now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "$now api_healthz=$inside edge_healthz=$live readyz=$ready failures=$failures proxy_healthz=$proxied proxy_failures=$proxy_failures edge_failures=$edge_failures"
    repaired=""
    if [ "$failures" -ge 3 ]; then
      echo "$now recreating api after $failures failures of its own liveness"
      # The model credential lives only in the environment `up` gave the API's container, and this
      # check runs from a timer that holds none: a recreation would start the API without it, and
      # every model mind would stop until somebody ran `up` again. So the container being replaced
      # hands its own on: read here into this process's environment alone, for the one command
      # below. It is never printed, logged, put on a command line or written to a file.
      if [ -z "${NEBIUS_API_KEY:-}" ]; then
        replaced="$(compose ps -a -q api 2>/dev/null | head -n 1 || true)"
        if [ -n "$replaced" ]; then
          NEBIUS_API_KEY="$(
            docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$replaced" 2>/dev/null \
              | sed -n 's/^NEBIUS_API_KEY=//p' | head -n 1 || true
          )"
          export NEBIUS_API_KEY
        fi
      fi
      [ -n "${NEBIUS_API_KEY:-}" ] \
        || echo "$now the replaced api held no NEBIUS_API_KEY: the recreated api asks no model until up is run with it"
      compose up -d --no-build --pull never --no-deps --force-recreate api
      echo 0 >"$watch_state"
      repaired=api
    elif [ "$proxy_failures" -ge 3 ]; then
      echo "$now restarting the client proxy after $proxy_failures failures to reach a live api"
      compose restart client
      echo 0 >"$proxy_state"
      repaired=client
    fi
    # Reported only by a check that repaired nothing: after a repair the next check says whether
    # the edge answers again.
    if [ "$edge_failures" -ge 3 ] && [ -z "$repaired" ]; then
      echo "$now edge failing: $edge_failures checks in a row answered $live through $origin; not repaired here"
    fi
    ;;

  preflight)
    # One public catalog read from the image the server runs; no credential and no model call.
    # Its allowlist is the catalogs' origins as the image's own manifest declares them, given to
    # this one-shot alone: the API's allowlist stays the model endpoint.
    need_env_file
    docker run --rm --pull never "$backend_image" sh -c 'EXULANICA_EGRESS_ALLOWLIST="$(python -c "
import json
from exulanica.models.manifest import load_manifest
print(json.dumps(sorted({p.catalog_origin for p in load_manifest().providers.values()})))
")" exec exulanica-preflight --json'
    ;;

  logs)
    need_env_file
    shift
    compose logs --follow --tail 200 "$@"
    ;;

  down)
    need_env_file
    compose down
    ;;

  destroy)
    need_env_file
    [ "${2:-}" = "--yes-delete-volumes" ] \
      || refuse "destroy deletes the database, the store and the spending witness; pass --yes-delete-volumes"
    compose --profile recovery down --volumes
    ;;

  *)
    sed -n '2,30p' "$0" >&2
    exit 2
    ;;
esac
