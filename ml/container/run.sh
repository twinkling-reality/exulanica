#!/bin/sh
# Train the texture inverse model once, inside its container boundary.
#
#   ml/container/run.sh IMAGE EXPORT_DIR OUT_DIR APPROVAL_REFERENCE [train options]
#
# IMAGE must be pinned by digest. EXPORT_DIR is a texture-inverse export, OUT_DIR an empty
# directory for the weights and the receipt, and APPROVAL_REFERENCE names the operator's yes to
# this run; the trainer refuses without one. The container gets no network, a read-only root, the
# export, the committed manifest and the published maker objects read-only, and nothing else.
set -eu
if [ "$#" -lt 4 ]; then
  echo "usage: $0 IMAGE EXPORT_DIR OUT_DIR APPROVAL_REFERENCE [train options]" >&2
  exit 2
fi
image=$1 export_dir=$2 out_dir=$3 approval=$4
shift 4
case "$image" in *@sha256:*) ;; *) echo "the image must be pinned by digest" >&2; exit 2 ;; esac
[ -n "$approval" ] || { echo "an approval reference is required" >&2; exit 2; }
root=$(cd "$(dirname "$0")/../.." && pwd)
manifest="$root/web/packages/loom-texture/dataset/manifests/texture-inverse-v1.json"
exec docker run --rm \
  --gpus device=0 \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,nosuid,size=2g \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --env EXULANICA_TRAINING_APPROVAL="$approval" \
  --mount "type=bind,source=$export_dir,target=/data,readonly" \
  --mount "type=bind,source=$manifest,target=/manifest.json,readonly" \
  --mount "type=bind,source=$root/assets/textures/objects,target=/objects,readonly" \
  --mount "type=bind,source=$out_dir,target=/out" \
  "$image" train --dataset /data --manifest /manifest.json --objects /objects --out /out "$@"
