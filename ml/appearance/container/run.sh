#!/bin/sh
# Run one staged texture job in the appearance container, on the rented machine.
#
#   container/run.sh DOCKER_REF RECORD_PIN STAGED_DIR WEIGHTS_DIR OUT_DIR HARD_LIMIT_SECONDS
#
#     DOCKER_REF   what docker runs: a registry reference pinned by digest (repo@sha256:...) or, for
#                  an image built on this machine and never pushed, its image id (sha256:...), which
#                  is the digest of that image's own configuration.
#     RECORD_PIN   what every generation record names the image by: NAME@sha256:<64 hex>. For a local
#                  build that is a stated name and the image id, so the record still pins the bytes
#                  that ran even though no registry holds them.
#
# The container gets: no network, a read-only root, the staged inputs and the weights read-only, one
# writable output directory, no added capabilities, and a hard time limit that kills it whatever the
# runner is doing. The runner stops itself at the job's own stop (150 per cent of its estimate); this
# limit is the second line, for a run that hangs instead of running slowly. Deleting the instance is
# the third and is done from the operator's machine.
set -eu
docker_ref="${1:?what docker runs, pinned by digest or an image id}"
record_pin="${2:?what the records name the image by, NAME@sha256:<64 hex>}"
staged="${3:?the staged input directory}"
weights="${4:?the weights directory}"
out="${5:?the output directory, which must be empty}"
seconds="${6:?the hard limit in seconds}"

case "${docker_ref}" in
  *@sha256:*|sha256:*) ;;
  *) echo "run.sh: docker runs a digest or an image id, never a tag" >&2; exit 2 ;;
esac
case "${record_pin}" in
  *@sha256:*) ;;
  *) echo "run.sh: the records pin NAME@sha256:<64 hex>, never a tag" >&2; exit 2 ;;
esac
case "${seconds}" in
  ''|*[!0-9]*) echo "run.sh: the hard limit is a whole number of seconds" >&2; exit 2 ;;
esac
mkdir -p "${out}"
if [ -n "$(ls -A "${out}")" ]; then echo "run.sh: ${out} is not empty" >&2; exit 2; fi

# As the invoking host user, not the image's own user and never root: the output directory is a bind
# mount the host owns, and a container user of its own cannot create anything inside it. MEASURED on
# the first real run, which refused with "PermissionError: [Errno 13] Permission denied: /out/outputs".
exec timeout --signal=TERM --kill-after=120 "${seconds}" \
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    --gpus all \
    --network none \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --tmpfs /tmp:rw,exec,size=16g \
    --shm-size 16g \
    --env EXULANICA_CONTAINER_IMAGE="${record_pin}" \
    --mount "type=bind,src=${staged},dst=/staged,readonly" \
    --mount "type=bind,src=${weights},dst=/weights,readonly" \
    --mount "type=bind,src=${out},dst=/out" \
    "${docker_ref}" --staged /staged --weights /weights --out /out
