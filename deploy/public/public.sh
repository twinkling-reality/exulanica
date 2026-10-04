#!/usr/bin/env bash
# The public server: the installation composition behind its TLS edge, as one command per step.
# docs/deployment.md section 8.2 is the runbook that calls it.
#
#   EXULANICA_DEPLOY_DIR=<secrets directory> deploy/public/public.sh <command>
#
#   build             on the build host: the client bundle, then the three images, from a clean checkout
#   images            print each image's ID and the commit it was built from
#   save <file>       write the three images to one gzip archive and print its sha256
#   init              write <dir>/public.env: generated passwords, the operator's token, the values below
#   mint <label>      a rehearsal visitor: a token for a workspace of its own
#   revoke <label>    delete that rehearsal token; `up` then serves without it
#   up                start the server; the first run installs, migrates and publishes the catalogs
#   issue-authority   issue the server's spending authority from the EXULANICA_AUTHORITY_* values
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
# `init` reads EXULANICA_PUBLIC_HOST, EXULANICA_TLS, EXULANICA_EDGE_ADDRESS, EXULANICA_BACKUP_PATH
# and EXULANICA_CUSTODY_PATH from the environment, and optionally the port settings. It leaves
# EXULANICA_BUDGET_USD and EXULANICA_BUDGET_MAX_CALLS empty, and `up` refuses until both are filled.
#
# SECRETS. Database passwords and tokens live in files created mode 0600 inside a directory
# created mode 0700. The model credential is never written to a file: `up` passes NEBIUS_API_KEY
# through from the calling shell, and without it every route that asks a model says so.
#
# The server never builds: `up` runs images loaded by name and refuses when one is missing, so what
# serves is what was built and checked on the build host.

set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
project="${EXULANICA_PUBLIC_PROJECT:-exulanica-public}"
backend_image="exulanica-public-backend"
maintenance_image="exulanica-public-maintenance"
client_image="exulanica-public-client"
images="$backend_image $maintenance_image $client_image"

case "${1:-}" in
  "" | build | images | save) deploy_dir="" ;;
  *) deploy_dir="${EXULANICA_DEPLOY_DIR:?set EXULANICA_DEPLOY_DIR to the directory that holds the secrets of this server}" ;;
esac
env_file="$deploy_dir/public.env"
token_dir="$deploy_dir/tokens"
tokens_file="$deploy_dir/tokens.json"
authority_file="$deploy_dir/authority.json"
watch_state="$deploy_dir/watch-failures"

refuse() {
  echo "public.sh: $*" >&2
  exit 2
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
  docker compose -p "$project" --project-directory "$root" --env-file "$env_file" \
    -f "$root/compose.yaml" -f "$here/public.yaml" "$@"
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
    docker run --rm -i --network "${project}_default" \
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
      EXULANICA_BUDGET_USD="$marker" EXULANICA_BUDGET_MAX_CALLS="$marker" \
      EXULANICA_CODE_REVISION="$revision" EXULANICA_CLIENT_TREE_SHA256="$tree_sha256" \
      EXULANICA_NODE_VERSION="$(node --version)" EXULANICA_PNPM_VERSION="$(cd web && pnpm --version)" \
      DOCKER_DEFAULT_PLATFORM="${EXULANICA_BUILD_PLATFORM:-linux/amd64}" \
      docker compose -p "$project" --project-directory "$root" \
      -f "$root/compose.yaml" -f "$here/public.yaml" build api maintenance client
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
    : "${EXULANICA_TLS:?set EXULANICA_TLS to an ACME contact email, or internal for a rehearsal}"
    : "${EXULANICA_EDGE_ADDRESS:?set EXULANICA_EDGE_ADDRESS; 0.0.0.0 on a public host, 127.0.0.1 in a rehearsal}"
    : "${EXULANICA_BACKUP_PATH:?set EXULANICA_BACKUP_PATH to a directory on storage apart from the database and media}"
    : "${EXULANICA_CUSTODY_PATH:?set EXULANICA_CUSTODY_PATH to a directory apart from the backup directory}"
    for path in "$EXULANICA_BACKUP_PATH" "$EXULANICA_CUSTODY_PATH"; do
      [ -d "$path" ] || refuse "$path is not a directory"
    done
    backup="$(cd "$EXULANICA_BACKUP_PATH" && pwd -P)"
    custody="$(cd "$EXULANICA_CUSTODY_PATH" && pwd -P)"
    case "$custody/" in "$backup/"*) refuse "custody must not be inside the backup directory" ;; esac
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
EXULANICA_PROFILE=${EXULANICA_PROFILE:-single-host-server-only}
EXULANICA_BACKUP_PATH=$backup
EXULANICA_CUSTODY_PATH=$custody
EXULANICA_PUBLIC_HOST=$EXULANICA_PUBLIC_HOST
EXULANICA_TLS=$EXULANICA_TLS
EXULANICA_EDGE_ADDRESS=$EXULANICA_EDGE_ADDRESS
EXULANICA_EDGE_HTTP_PORT=${EXULANICA_EDGE_HTTP_PORT:-80}
EXULANICA_EDGE_HTTPS_PORT=${EXULANICA_EDGE_HTTPS_PORT:-443}
EXULANICA_CLIENT_PORT=${EXULANICA_CLIENT_PORT:-8080}
# The process fuse in USD and in calls, for one API process life. Filled in by the operator; up
# refuses until both are. The durable authority (issue-authority) is the money.
EXULANICA_BUDGET_USD=
EXULANICA_BUDGET_MAX_CALLS=
# The origins the API may reach. The API checks at startup that the model endpoint is in it.
EXULANICA_EGRESS_ALLOWLIST='["https://api.tokenfactory.nebius.com"]'
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
    docker run --rm --user "$(id -u):$(id -g)" -v "$token_dir:/out" "$backend_image" \
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
    compose up -d --wait --no-build --pull missing
    compose ps
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
    # One check through the public edge, for a timer to run every minute. Docker never restarts a
    # container whose health check fails (deployment.md section 9), so three liveness failures in a
    # row recreate the API container. Readiness is logged, never acted on: a dependency that is
    # down is not fixed by restarting the API.
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
    failures=0
    [ -f "$watch_state" ] && failures="$(cat "$watch_state")"
    if [ "$live" = 200 ]; then failures=0; else failures=$((failures + 1)); fi
    echo "$failures" >"$watch_state"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) healthz=$live readyz=$ready failures=$failures"
    if [ "$failures" -ge 3 ]; then
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) recreating api after $failures liveness failures"
      compose up -d --no-build --no-deps --force-recreate api
      echo 0 >"$watch_state"
    fi
    ;;

  preflight)
    # One public catalog read from the image the server runs; no credential and no model call.
    # Its allowlist is the catalogs' origins as the image's own manifest declares them, given to
    # this one-shot alone: the API's allowlist stays the model endpoint.
    need_env_file
    docker run --rm "$backend_image" sh -c 'EXULANICA_EGRESS_ALLOWLIST="$(python -c "
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
    sed -n '2,25p' "$0" >&2
    exit 2
    ;;
esac
