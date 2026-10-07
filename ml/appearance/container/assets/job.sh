#!/bin/sh
# The entry of a generated asset job on Nebius Serverless AI, run from the bucket mount by the image
# python:3.12-slim-bookworm pinned by digest (the submit command names it).
#
#   sh /mnt/data/runs/<job or session sha256>/job.sh
#
# Environment, set by the submit command: ROUTE (A or B), JOB (the job record's sha256, or in a
# session the session record's), CODE_SHA256 (the staged code archive's), STOP_SECONDS (the job
# record's stop, or the session's hard stop) and MODE: "job" runs one staged job; "session" loads
# the route once and serves the bucket's queue until its idle stop, a stop marker or its hard stop
# (exulanica_appearance/assets/session.py). Nothing here reads a credential: the bucket arrives as
# a mount.
set -eu
# The job record's stop (150 per cent of its estimate) bounds the whole job, setup included; the
# service's own timeout is at least an hour and is only the backstop.
if [ -z "${UNDER_STOP:-}" ]; then
  UNDER_STOP=1 exec timeout --signal=TERM --kill-after=60 "$STOP_SECONDS" sh "$0"
fi
data=/mnt/data
run="$data/runs/$JOB"
# The bucket mount takes plain writes but not a file's mode or times, so every piece of work (pip,
# upstream code, weights, caches, outputs) stays on the machine's own disk, and outputs reach the
# bucket only through "publish": each finished file written once, every minute and at exit.
work=/opt/work
mkdir -p "$work/out"
case "$ROUTE" in A|B) ;; *) echo "ROUTE is A or B" >&2; exit 2 ;; esac
mode=${MODE:-job}
case "$mode" in job|session) ;; *) echo "MODE is job or session" >&2; exit 2 ;; esac
# File names are lower case, and the job's file system tells the cases apart.
route=$(printf '%s' "$ROUTE" | tr AB ab)

echo "phase code $(date -u +%Y-%m-%dT%H:%M:%SZ)"
test "$(sha256sum "$run/code.tar" | cut -d' ' -f1)" = "$CODE_SHA256"
mkdir -p /opt/gen
tar -xf "$run/code.tar" -C /opt/gen
code=/opt/gen

echo "phase system $(date -u +%Y-%m-%dT%H:%M:%SZ)"
# Triton compiles some of torch's kernels when they first run and needs a C compiler for it
# (measured in the appearance session of 2026-09-17).
apt-get update -qq
apt-get install -y -qq --no-install-recommends gcc libc6-dev > /dev/null

echo "phase install $(date -u +%Y-%m-%dT%H:%M:%SZ)"
python -m pip install --quiet --no-deps --require-hashes --only-binary :all: \
  --extra-index-url https://download.pytorch.org/whl/cu128 \
  -r "$code/ml/appearance/container/assets/lock-route-$route.txt"

publish() {
  PYTHONPATH="$code:$code/ml/appearance" python -m exulanica_appearance assets remote publish \
    --source "$work/out" --target "$data/out" --ledger "$work/published.txt"
}
# A session publishes each batch itself before marking it done, so only a single job needs the
# minute loop.
publisher=""
if [ "$mode" = job ]; then
  ( while sleep 60; do publish > /dev/null || echo "publish failed" >&2; done ) &
  publisher=$!
fi
trap '[ -n "$publisher" ] && kill "$publisher" 2>/dev/null; echo "phase publish $(date -u +%Y-%m-%dT%H:%M:%SZ)"; publish || true' EXIT
trap 'exit 143' TERM

echo "phase prepare $(date -u +%Y-%m-%dT%H:%M:%SZ)"
export TORCH_HOME="$work/torch-home" HF_HOME="$work/hf-home"
PYTHONPATH="$code:$code/ml/appearance" python -m exulanica_appearance assets remote prepare \
  --code "$code" --route "$ROUTE" --upstream /opt/upstream --weights "$work/weights" \
  --torch-home "$TORCH_HOME" --hf-home "$HF_HOME" \
  --report "$work/out/prepare-$ROUTE-$(date -u +%Y%m%dT%H%M%SZ).json"

echo "phase run $(date -u +%Y-%m-%dT%H:%M:%SZ)"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1
standins="$code/ml/appearance/container/assets/standins"
case "$ROUTE" in
  A) upstream="/opt/upstream/trellis:/opt/upstream/utils3d" ;;
  B) upstream="/opt/upstream/step1x" ;;
esac
if [ "$mode" = session ]; then
  PYTHONPATH="$standins:$upstream:$code:$code/ml/appearance" python -m exulanica_appearance assets session serve \
    --code "$code" --route "$ROUTE" --session "$run/session.json" --code-sha256 "$CODE_SHA256" \
    --root "$data" --weights "$work/weights" --work "$work/out" --ledger "$work/published.txt"
else
  PYTHONPATH="$standins:$upstream:$code:$code/ml/appearance" python -m exulanica_appearance assets remote run \
    --code "$code" --route "$ROUTE" --job "$run/job.json" --requests "$run/requests" \
    --weights "$work/weights" --cutouts "$data/out/inputs" --out "$work/out"
fi
echo "phase done $(date -u +%Y-%m-%dT%H:%M:%SZ)"
