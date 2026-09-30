#!/usr/bin/env bash
# The judge stack behind its public edge, as one command per step. docs/judge-access.md section 11
# is the runbook that calls it.
#
#   EXULANICA_DEPLOY_DIR=<secrets directory> deploy/judge/stack.sh <command>
#
#   build           on the build host: build both images for linux/amd64, as compose.yaml declares
#   init            write <dir>/judge.env: generated database passwords and the values below
#   mint <label>    mint one judge's bearer token into <dir>/judge-tokens/<label>.json
#   revoke <label>  delete that judge's token; `up` then serves without it
#   images          print the ID of each image the stack runs, to compare with the build host
#   up              start the stack; the first run migrates, seeds and verifies
#   reset           return the world to the seed archive (the store is never touched)
#   status          the containers, and the API's readiness through the edge network
#   logs [service]  follow the logs
#   down            stop the stack and keep its volumes
#   destroy         stop the stack and delete its volumes, database and store included
#
# `init` reads EXULANICA_PUBLIC_HOST, EXULANICA_TLS, EXULANICA_SEED_ARCHIVE and
# EXULANICA_EDGE_ADDRESS from the environment, and optionally the three port settings. It leaves
# EXULANICA_BUDGET_USD and EXULANICA_BUDGET_MAX_CALLS empty, and the stack refuses to start until
# the operator fills them in.
#
# SECRETS. The database passwords and the judges' tokens live in files created mode 0600 inside a
# directory created mode 0700. The model credential is never written to a file: `up` passes
# NEBIUS_API_KEY through from the calling shell's environment, and without it the stack serves
# every route except the ones that call a model, which answer that no credential is configured.
#
# The host never builds: `up` runs images loaded by name and refuses when one is missing, so what
# serves is the image that was verified where it was built.

set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
# Every command but `build` and `images` reads the secrets directory.
case "${1:-}" in
  build | images) deploy_dir="" ;;
  *) deploy_dir="${EXULANICA_DEPLOY_DIR:?set EXULANICA_DEPLOY_DIR to the directory that holds the secrets of this stack}" ;;
esac
env_file="$deploy_dir/judge.env"
token_dir="$deploy_dir/judge-tokens"
tokens_file="$deploy_dir/judge-tokens.json"
backend_image="exulanica-judge-backend"
web_image="exulanica-judge-web"
# The long-running services. `migrate` and `seed` run once, on the first `up`.
serving="postgres api web edge"

refuse() {
  echo "stack.sh: $*" >&2
  exit 2
}

compose() {
  # Compose interpolates every service before any command, so the API's required token setting
  # must hold something even for `status` or `reset`. The minted directory when there is one;
  # otherwise a marker, which no command but `up` could hand to an API, and `up` refuses first.
  if [ -s "$tokens_file" ]; then
    EXULANICA_API_TOKENS="$(cat "$tokens_file")"
  else
    EXULANICA_API_TOKENS="no-judge-token-minted"
  fi
  export EXULANICA_API_TOKENS
  docker compose --env-file "$env_file" -f "$here/compose.yaml" -f "$here/edge.yaml" "$@"
}

need_env_file() {
  [ -f "$env_file" ] || refuse "$env_file does not exist; run init first"
}

# Reads one value from the env file without sourcing it, so nothing in it is executed.
env_value() {
  sed -n "s/^$1=//p" "$env_file" | tail -n 1 | sed "s/^'\(.*\)'\$/\1/"
}

merge_tokens() {
  # Every judge's one-entry directory, merged into the one directory the API loads. Written
  # through a descriptor opened 0600, as `exulanica-seed token` writes each part.
  python3 - "$token_dir" "$tokens_file" <<'PY'
import json, os, pathlib, sys
parts = sorted(pathlib.Path(sys.argv[1]).glob("*.json"))
merged = {}
for part in parts:
    merged.update(json.loads(part.read_text(encoding="utf-8")))
target = sys.argv[2]
descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(merged, handle, sort_keys=True)
print(f"{len(merged)} judge token(s) in {target}", file=sys.stderr)
PY
}

command="${1:-}"
case "$command" in
  build)
    # The images and their build arguments are the ones compose.yaml declares, built from this
    # checkout. Compose interpolates every service's settings before it builds anything, so the
    # run-time secrets are given a marker here; none of them is a build argument, and none reaches
    # an image. linux/amd64 because that is what the host runs.
    marker="build-only-not-a-secret"
    POSTGRES_PASSWORD="$marker" EXULANICA_APP_ROLE_PASSWORD="$marker" \
      EXULANICA_EXECUTOR_ROLE_PASSWORD="$marker" EXULANICA_JUDGE_ROLE_PASSWORD="$marker" \
      EXULANICA_API_TOKENS="$marker" EXULANICA_SEED_ARCHIVE="$here" \
      EXULANICA_BUDGET_USD="$marker" EXULANICA_BUDGET_MAX_CALLS="$marker" \
      DOCKER_DEFAULT_PLATFORM=linux/amd64 \
      docker compose -f "$here/compose.yaml" build migrate web
    "$0" images
    ;;

  init)
    [ -e "$env_file" ] && refuse "$env_file exists; delete it deliberately to start again"
    : "${EXULANICA_PUBLIC_HOST:?set EXULANICA_PUBLIC_HOST to the host name judges open}"
    : "${EXULANICA_TLS:?set EXULANICA_TLS to an ACME contact email, or internal for a rehearsal}"
    : "${EXULANICA_SEED_ARCHIVE:?set EXULANICA_SEED_ARCHIVE to the seed archive directory}"
    : "${EXULANICA_EDGE_ADDRESS:?set EXULANICA_EDGE_ADDRESS; 0.0.0.0 on a public host, 127.0.0.1 in a rehearsal}"
    [ -f "$EXULANICA_SEED_ARCHIVE/manifest.json" ] \
      || refuse "$EXULANICA_SEED_ARCHIVE holds no manifest.json, so it is not a seed archive"
    umask 077
    mkdir -p "$deploy_dir" "$token_dir"
    chmod 700 "$deploy_dir" "$token_dir"
    secret() { openssl rand -hex 24; }
    cat >"$env_file" <<ENV
# Written by stack.sh init. Mode 0600: it holds database passwords. Never copy it off this host.
POSTGRES_PASSWORD=$(secret)
EXULANICA_APP_ROLE_PASSWORD=$(secret)
EXULANICA_EXECUTOR_ROLE_PASSWORD=$(secret)
EXULANICA_JUDGE_ROLE_PASSWORD=$(secret)
EXULANICA_SEED_ARCHIVE=$EXULANICA_SEED_ARCHIVE
EXULANICA_PUBLIC_HOST=$EXULANICA_PUBLIC_HOST
EXULANICA_TLS=$EXULANICA_TLS
EXULANICA_EDGE_ADDRESS=$EXULANICA_EDGE_ADDRESS
EXULANICA_EDGE_HTTP_PORT=${EXULANICA_EDGE_HTTP_PORT:-80}
EXULANICA_EDGE_HTTPS_PORT=${EXULANICA_EDGE_HTTPS_PORT:-443}
EXULANICA_JUDGE_PORT=${EXULANICA_JUDGE_PORT:-8080}
# The model spend ceiling in USD and the call ceiling for one API process life. The stack refuses
# to start until both are filled in.
EXULANICA_BUDGET_USD=
EXULANICA_BUDGET_MAX_CALLS=
# The origins the API may reach. The API checks at startup that the model endpoint is in it.
EXULANICA_EGRESS_ALLOWLIST='["https://api.tokenfactory.nebius.com"]'
ENV
    echo "wrote $env_file (mode 0600); fill in EXULANICA_BUDGET_USD and EXULANICA_BUDGET_MAX_CALLS"
    ;;

  mint)
    need_env_file
    label="${2:?give the judge a label, for example judge-1}"
    case "$label" in
      *[!A-Za-z0-9_-]*) refuse "a label is letters, digits, hyphens and underscores" ;;
    esac
    [ -e "$token_dir/$label.json" ] && refuse "$label already has a token; revoke it first"
    archive="$(env_value EXULANICA_SEED_ARCHIVE)"
    workspace="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["workspace_id"])' \
      "$archive/manifest.json")"
    umask 077
    # The image's own command mints the token, so the grant's permissions come from the one place
    # that declares them. It runs as the calling user so the file it writes is that user's.
    docker run --rm --user "$(id -u):$(id -g)" -v "$token_dir:/out" "$backend_image" \
      exulanica-seed token --workspace "$workspace" --out "/out/$label.json"
    merge_tokens
    echo "run up to serve it"
    ;;

  revoke)
    need_env_file
    label="${2:?name the judge label to revoke}"
    [ -f "$token_dir/$label.json" ] || refuse "$label has no token"
    rm -f "$token_dir/$label.json"
    merge_tokens
    echo "run up to stop serving it"
    ;;

  images)
    for image in "$backend_image" "$web_image"; do
      printf '%s %s\n' "$image" "$(docker image inspect --format '{{.Id}}' "$image")"
    done
    ;;

  up)
    need_env_file
    [ -s "$tokens_file" ] || refuse "no judge token has been minted; run mint <label> first"
    for image in "$backend_image" "$web_image"; do
      docker image inspect "$image" >/dev/null 2>&1 \
        || refuse "$image is not loaded on this host; load the image built and verified elsewhere"
    done
    if [ -z "${NEBIUS_API_KEY:-}" ]; then
      echo "NEBIUS_API_KEY is not set: the Companion and the model-run people will answer that no" \
        "credential is configured" >&2
    fi
    seeded="$(docker ps -a --filter "label=com.docker.compose.project=exulanica-judge" \
      --filter "label=com.docker.compose.service=seed" --format '{{.Status}}')"
    case "$seeded" in
      "Exited (0)"*)
        # The seed completed on an earlier run. Starting it again would restore over the world a
        # judge is using, and the restore refuses a database that already holds the seed.
        # shellcheck disable=SC2086
        compose up -d --wait --no-build --pull missing --no-deps $serving
        ;;
      "")
        compose up -d --wait --no-build --pull missing
        ;;
      *)
        refuse "the seed job exists and did not complete ($seeded); read its log, then destroy"
        ;;
    esac
    compose ps
    ;;

  reset)
    need_env_file
    compose run --rm --no-deps seed sh -c "exulanica-seed reset --archive /seed"
    ;;

  status)
    need_env_file
    compose ps
    # Readiness from inside the web container, which reaches the API over the compose network, so
    # this answers even while the edge or its certificate is the problem.
    compose exec -T web wget -q -O - http://api:8000/readyz || true
    echo
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
      || refuse "destroy deletes the database and the store; pass --yes-delete-volumes"
    compose down --volumes
    ;;

  *)
    sed -n '2,20p' "$0" >&2
    exit 2
    ;;
esac
