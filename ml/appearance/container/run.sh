#!/bin/sh
# Run one staged texture job in the appearance container, on the rented machine.
#
#   container/run.sh IMAGE@sha256:... STAGED_DIR WEIGHTS_DIR OUT_DIR HARD_LIMIT_SECONDS
#
# The container gets: no network, a read-only root, the staged inputs and the weights read-only, one
# writable output directory, no added capabilities, and a hard time limit that kills it whatever the
# runner is doing. The runner stops itself at the job's own stop (150 per cent of its estimate); this
# limit is the second line, for a run that hangs instead of running slowly. Deleting the instance is
# the third and is done from the operator's machine.
set -eu
image="${1:?the image, pinned by digest}"
staged="${2:?the staged input directory}"
weights="${3:?the weights directory}"
out="${4:?the output directory, which must be empty}"
seconds="${5:?the hard limit in seconds}"

case "${image}" in
  *@sha256:*) ;;
  *) echo "run.sh: the image must be pinned by digest, not a tag" >&2; exit 2 ;;
esac
case "${seconds}" in
  ''|*[!0-9]*) echo "run.sh: the hard limit is a whole number of seconds" >&2; exit 2 ;;
esac
mkdir -p "${out}"
if [ -n "$(ls -A "${out}")" ]; then echo "run.sh: ${out} is not empty" >&2; exit 2; fi

exec timeout --signal=TERM --kill-after=120 "${seconds}" \
  docker run --rm \
    --gpus all \
    --network none \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --tmpfs /tmp:rw,exec,size=16g \
    --shm-size 16g \
    --env EXULANICA_CONTAINER_IMAGE="${image}" \
    --mount "type=bind,src=${staged},dst=/staged,readonly" \
    --mount "type=bind,src=${weights},dst=/weights,readonly" \
    --mount "type=bind,src=${out},dst=/out" \
    "${image}" --staged /staged --weights /weights --out /out
