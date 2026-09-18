#!/bin/sh
# One Track A session on a rented machine, from the operator's Mac, in as few billed minutes as
# possible. The instance must already exist: this script never creates one, because a deploy needs
# the operator's consent click.
#
#   scripts/gpu-session.sh HOST IMAGE_TAG WORK_DIR CREATED_EPOCH JOB [JOB...]
#
#     HOST                   an ssh destination that works (user@ip, or a scratch ssh config alias)
#     IMAGE_TAG              the tag to build, normally the lane's head commit
#     WORK_DIR               a directory on the Mac for what comes back
#     CREATED_EPOCH          the instant the instance was created, in epoch seconds, as the
#                            provider's console states it. The script works out the billed seconds
#                            itself at the moment the gate runs, because a number typed at the start
#                            is already half an hour stale by then and the gate's spend check is one
#                            of the three things standing between this and an open-ended bill.
#     JOB...                 one or more job names in jobs/, run in the order given after the gate
#                            passes. Each job's hard limit is its own stop_at_seconds, read from what
#                            staging wrote, so no limit is typed here and none can drift from a spec.
#
# It builds the image on the machine, fetches the weights (each verified as it lands), runs the smoke
# job, applies the gate, and continues to session 1 ONLY if the gate exits 0. It never deletes the
# instance: deletion is a separate, deliberate step (scripts/delete-instance.sh), so a failure here
# cannot leave the operator wondering whether the machine is gone.
set -eu

host="${1:?an ssh destination}"
tag="${2:?the image tag, normally the head commit}"
work="${3:?a directory on this machine for the results}"
created="${4:?the creation instant in epoch seconds, as the console states it}"
shift 4
[ "$#" -ge 1 ] || { echo "gpu-session: name at least one job to run after the gate" >&2; exit 2; }
jobs_to_run="$*"

case "${created}" in
  ''|*[!0-9]*) echo "gpu-session: the creation instant is epoch seconds" >&2; exit 2 ;;
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
echo "== staging the smoke job and ${jobs_to_run} on this machine"
rm -rf "${work}/staged-smoke"
"${python}" -m exulanica_appearance runner stage --spec "${here}/jobs/track-a-smoke.json" \
  --repository "${repository}" --weights "${here}/weights" --out "${work}/staged-smoke"
for job in ${jobs_to_run}; do
  rm -rf "${work}/staged-${job}"
  "${python}" -m exulanica_appearance runner stage --spec "${here}/jobs/${job}.json" \
    --repository "${repository}" --weights "${here}/weights" --out "${work}/staged-${job}"
done

echo "== pushing the lane's code and the staged inputs"
ssh "${host}" "mkdir -p ${remote}"
# Never the local virtual environment (gigabytes, and the wrong platform) or a cache: the container
# builds its own environment from pyproject.toml and uv.lock.
rsync -a --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' --exclude 'evidence' \
  "${here}/" "${host}:${remote}/ml-appearance/"
staged_dirs="${work}/staged-smoke"
for job in ${jobs_to_run}; do staged_dirs="${staged_dirs} ${work}/staged-${job}"; done
# shellcheck disable=SC2086
rsync -a --delete ${staged_dirs} "${host}:${remote}/"

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
billed=$(( $(date +%s) - created ))
echo "   billed so far: ${billed} s"
if "${python}" -m exulanica_appearance runner gate --results "${work}/out-smoke" \
    --staged "${work}/staged-smoke" --billed-seconds "${billed}" --budget-seconds "${budget_seconds}" \
    --rate-cents "${rate_cents}" --out "${work}/gate-smoke.json"; then
  echo "== the gate passed: session 1"
else
  echo "== the gate did not pass: stopping here. Delete the machine and report." >&2
  exit 1
fi

for job in ${jobs_to_run}; do
  # The hard limit is the job's own stop, read from what staging wrote rather than typed here.
  limit=$("${python}" -c "import json,sys;print(json.load(open(sys.argv[1]))['stop_at_seconds'])" \
    "${work}/staged-${job}/job.json")
  echo "== ${job}, hard limit ${limit} s"
  ssh "${host}" "python3 ${remote}/ml-appearance/scripts/fetch-weights.py ${remote}/staged-${job} ${remote}/weights"
  ssh "${host}" "rm -rf ${remote}/out-${job} && ${remote}/ml-appearance/container/run.sh \
    '${docker_ref}' '${record_pin}' ${remote}/staged-${job} ${remote}/weights ${remote}/out-${job} ${limit}"
  rsync -a "${host}:${remote}/out-${job}" "${work}/"
  "${python}" -m exulanica_appearance runner check --out "${work}/out-${job}"
  # Each step's logs come back as that step ends: session 1 lost its build and fetch logs to a
  # deletion that happened before anyone pulled them.
  ssh "${host}" "cat ${remote}/build.log 2>/dev/null || true" > "${work}/build-${job}.log.txt" || true
done
echo "== done. Pull anything else you want off the machine NOW, then delete it before the report."
