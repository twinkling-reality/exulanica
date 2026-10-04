#!/bin/sh
# The entry of a generated asset job on Nebius Serverless AI, run from the bucket mount by the image
# python:3.12-slim-bookworm pinned by digest (the submit command names it).
#
#   sh /mnt/data/runs/<job sha256>/job.sh
#
# Environment, set by the submit command: ROUTE (A or B), JOB (the job record's sha256), CODE_SHA256
# (the staged code archive's) and STOP_SECONDS (the job record's stop). Nothing here reads a credential: the bucket arrives as a mount.
set -eu
# The job record's stop (150 per cent of its estimate) bounds the whole job, setup included; the
# service's own timeout is at least an hour and is only the backstop.
if [ -z "${UNDER_STOP:-}" ]; then
  UNDER_STOP=1 exec timeout --signal=TERM --kill-after=60 "$STOP_SECONDS" sh "$0"
fi
data=/mnt/data
run="$data/runs/$JOB"
case "$ROUTE" in A|B) ;; *) echo "ROUTE is A or B" >&2; exit 2 ;; esac

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
  -r "$code/ml/appearance/container/assets/lock-route-$ROUTE.txt"

echo "phase prepare $(date -u +%Y-%m-%dT%H:%M:%SZ)"
export TORCH_HOME="$data/torch-home" HF_HOME="$data/hf-home"
PYTHONPATH="$code:$code/ml/appearance" python -m exulanica_appearance assets remote prepare \
  --code "$code" --route "$ROUTE" --upstream /opt/upstream --weights "$data/weights" \
  --torch-home "$TORCH_HOME" --hf-home "$HF_HOME" --report "$run/prepare-$(date -u +%Y%m%dT%H%M%SZ).json"

echo "phase run $(date -u +%Y-%m-%dT%H:%M:%SZ)"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1
standins="$code/ml/appearance/container/assets/standins"
case "$ROUTE" in
  A) upstream="/opt/upstream/trellis:/opt/upstream/utils3d" ;;
  B) upstream="/opt/upstream/step1x" ;;
esac
PYTHONPATH="$standins:$upstream:$code:$code/ml/appearance" python -m exulanica_appearance assets remote run \
  --code "$code" --route "$ROUTE" --job "$run/job.json" --requests "$run/requests" \
  --weights "$data/weights" --cutouts "$data/out/inputs" --out "$data/out"
echo "phase done $(date -u +%Y-%m-%dT%H:%M:%SZ)"
