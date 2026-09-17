#!/bin/sh
# One Track A session on a rented machine, from the operator's Mac, in as few billed minutes as
# possible. The instance must already exist: this script never creates one, because a deploy needs
# the operator's consent click.
#
#   scripts/gpu-session.sh HOST IMAGE_TAG WORK_DIR BILLED_SECONDS_SO_FAR
#
#     HOST                   an ssh destination that works (user@ip, or a scratch ssh config alias)
#     IMAGE_TAG              the tag to build, normally the lane's head commit
#     WORK_DIR               a directory on the Mac for what comes back
#     BILLED_SECONDS_SO_FAR  seconds the instance has been billed when the smoke run ends, from the
#                            creation instant the orchestrator was told
#
# It builds the image on the machine, fetches the weights (each verified as it lands), runs the smoke
# job, applies the gate, and continues to session 1 ONLY if the gate exits 0. It never deletes the
# instance: deletion is a separate, deliberate step (scripts/delete-instance.sh), so a failure here
# cannot leave the operator wondering whether the machine is gone.
set -eu

host="${1:?an ssh destination}"
tag="${2:?the image tag, normally the head commit}"
work="${3:?a directory on this machine for the results}"
billed="${4:?seconds billed so far when the smoke run ends}"

case "${billed}" in
  ''|*[!0-9]*) echo "gpu-session: billed seconds is a whole number" >&2; exit 2 ;;
esac

here=$(cd "$(dirname "$0")/.." && pwd)
repository=$(cd "${here}/../.." && pwd)
python="${here}/.venv/bin/python"
head=$(git -C "${repository}" rev-parse HEAD)
remote="appearance"
# The smoke stage's budget and the machine's listed rate, as the design page states them.
budget_seconds=5400
rate_cents=263

mkdir -p "${work}"
echo "== staging both jobs on this machine"
rm -rf "${work}/staged-smoke" "${work}/staged-session-1"
"${python}" -m exulanica_appearance runner stage --spec "${here}/jobs/track-a-smoke.json" \
  --repository "${repository}" --weights "${here}/weights" --out "${work}/staged-smoke"
"${python}" -m exulanica_appearance runner stage --spec "${here}/jobs/track-a-session-1.json" \
  --repository "${repository}" --weights "${here}/weights" --out "${work}/staged-session-1"

echo "== pushing the lane's code and the staged inputs"
ssh "${host}" "mkdir -p ${remote}"
# Never the local virtual environment (gigabytes, and the wrong platform) or a cache: the container
# builds its own environment from pyproject.toml and uv.lock.
rsync -a --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' --exclude 'evidence' \
  "${here}/" "${host}:${remote}/ml-appearance/"
rsync -a --delete "${work}/staged-smoke" "${work}/staged-session-1" "${host}:${remote}/"

echo "== what the host has (installs the NVIDIA container toolkit only if Docker has no runtime)"
ssh "${host}" "bash ${remote}/ml-appearance/scripts/host-check.sh"

echo "== building the image (bases pinned by digest, VideoX-Fun pinned by commit and tree)"
ssh "${host}" "cd ${remote}/ml-appearance && docker build -f container/Dockerfile \
  --build-arg CODE_REVISION=${head} -t appearance:${tag} ."
# A locally built image has no registry digest, so docker runs it by its image id, which is the
# digest of that image's own configuration, and the records pin a stated name with that same id.
docker_ref=$(ssh "${host}" "docker image inspect appearance:${tag} --format '{{.Id}}'")
record_pin="appearance-local@${docker_ref}"
echo "   image ${record_pin}"

echo "== fetching the weights the staged manifests name, verified as they land"
ssh "${host}" "python3 ${remote}/ml-appearance/scripts/fetch-weights.py ${remote}/staged-smoke ${remote}/weights"

echo "== the smoke job"
ssh "${host}" "rm -rf ${remote}/out-smoke && ${remote}/ml-appearance/container/run.sh \
  '${docker_ref}' '${record_pin}' ${remote}/staged-smoke ${remote}/weights ${remote}/out-smoke 1440"
rsync -a "${host}:${remote}/out-smoke" "${work}/"

echo "== the gate"
if "${python}" -m exulanica_appearance runner gate --results "${work}/out-smoke" \
    --staged "${work}/staged-smoke" --billed-seconds "${billed}" --budget-seconds "${budget_seconds}" \
    --rate-cents "${rate_cents}" --out "${work}/gate-smoke.json"; then
  echo "== the gate passed: session 1"
else
  echo "== the gate did not pass: stopping here. Delete the machine and report." >&2
  exit 1
fi

ssh "${host}" "python3 ${remote}/ml-appearance/scripts/fetch-weights.py ${remote}/staged-session-1 ${remote}/weights"
ssh "${host}" "rm -rf ${remote}/out-session-1 && ${remote}/ml-appearance/container/run.sh \
  '${docker_ref}' '${record_pin}' ${remote}/staged-session-1 ${remote}/weights ${remote}/out-session-1 5670"
rsync -a "${host}:${remote}/out-session-1" "${work}/"
"${python}" -m exulanica_appearance runner check --out "${work}/out-session-1"
echo "== done. Delete the machine before writing the report."
