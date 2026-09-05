#!/usr/bin/env bash
# Run the Exulanica scene worker on a CUDA host inside its own digest-pinned image.
#
# The worker image is the repository's root Dockerfile built at CODE_REVISION and pushed to the
# host's local registry, so the pose receipts record the runtime they actually ran in. The
# container shares the host network (the permitted database arrives over a reverse SSH tunnel on
# localhost:5433), talks to the host Docker daemon to launch the trainer image, and sees the
# content store at the same absolute path as the host so the trainer's bind mounts resolve.
#
# Required environment: CODE_REVISION (40 hex), EXULANICA_WORKSPACE_IDS (comma separated),
# EXULANICA_DATABASE_URL (for example postgresql://<os-user>@127.0.0.1:5433/exulanica_spine_test).
# Optional: EXULANICA_DATA_DIR (default ~/exulanica-data), PGOPTIONS (default -c role=exulanica_app),
# REPO_DIR (default ~/orimera, must hold deploy/gsplat/compressor/node_modules), NODE_DIR (~/node),
# EXULANICA_SCENE_JOB_IDS (comma separated; the worker then claims only those jobs instead of
# draining the workspaces oldest first, which on a rented GPU can spend the pass on a stale job).
# Usage: deploy/gsplat/run-scene-worker.sh exulanica-scene-worker --once --name <worker-name> [--job <id>]
set -euo pipefail
: "${CODE_REVISION:?set CODE_REVISION to the exact 40-character Git revision the images were built at}"
: "${EXULANICA_WORKSPACE_IDS:?set EXULANICA_WORKSPACE_IDS}"
: "${EXULANICA_DATABASE_URL:?set EXULANICA_DATABASE_URL}"
DATA_DIR="${EXULANICA_DATA_DIR:-$HOME/exulanica-data}"
REPO_DIR="${REPO_DIR:-$HOME/orimera}"
NODE_DIR="${NODE_DIR:-$HOME/node}"
WORKER_IMAGE="$(docker inspect --format '{{index .RepoDigests 0}}' "localhost:5000/exulanica-scene-worker:${CODE_REVISION:0:7}")"
case "$WORKER_IMAGE" in *@sha256:*) ;; *) echo "worker image has no registry digest; push it first" >&2; exit 1 ;; esac
mkdir -p "$DATA_DIR" "$HOME/worker-home"
# The image's liveness probe is the API's /healthz; a worker has no HTTP port, so it is disabled
# here exactly as compose does for the non-HTTP services.
exec docker run --rm --network host --no-healthcheck \
  --user "$(id -u):$(id -g)" --group-add "$(stat -c %g /var/run/docker.sock)" \
  -e HOME=/tmp/worker-home -v "$HOME/worker-home:/tmp/worker-home" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /usr/bin/docker:/usr/local/bin/docker:ro \
  -v "$NODE_DIR:/opt/node:ro" \
  -v "$REPO_DIR/deploy/gsplat/compressor:/opt/compressor:ro" \
  -v "$DATA_DIR:$DATA_DIR" \
  -e PATH="/app/.venv/bin:/opt/compressor/node_modules/.bin:/opt/node/bin:/usr/local/bin:/usr/bin:/bin" \
  -e EXULANICA_DATABASE_URL="$EXULANICA_DATABASE_URL" \
  -e PGOPTIONS="${PGOPTIONS:--c role=exulanica_app}" \
  -e EXULANICA_DATA_DIR="$DATA_DIR" \
  -e EXULANICA_WORKSPACE_IDS="$EXULANICA_WORKSPACE_IDS" \
  -e EXULANICA_SCENE_JOB_IDS="${EXULANICA_SCENE_JOB_IDS:-}" \
  -e EXULANICA_CODE_REVISION="$CODE_REVISION" \
  -e EXULANICA_POSE_RUNTIME_IMAGE="$WORKER_IMAGE" \
  -w "$DATA_DIR" \
  "$WORKER_IMAGE" "$@"
