#!/bin/sh
# Fetch a Hugging Face model repository's METADATA at one revision: the card data, the recursive file
# tree (sizes, git blob ids, LFS sha256) and the model card itself. No weights file is fetched.
#
#   ml/appearance/scripts/fetch-hf-metadata.sh <repo id> <40-hex revision> <output directory>
#
# The weights manifest builder (python -m exulanica_appearance weights) reads these three files.
set -eu
repo="$1"
revision="$2"
out="$3"
case "$revision" in
  *[!0-9a-f]*) echo "revision must be 40 lowercase hex" >&2; exit 2 ;;
esac
[ "${#revision}" -eq 40 ] || { echo "revision must be 40 lowercase hex" >&2; exit 2; }
mkdir -p "$out"
base="https://huggingface.co"
curl -fsS -m 60 "$base/api/models/$repo/revision/$revision" -o "$out/revision.json"
curl -fsS -m 60 "$base/api/models/$repo/tree/$revision?recursive=true" -o "$out/tree.json"
curl -fsS -m 60 "$base/$repo/raw/$revision/README.md" -o "$out/README.md"
printf '%s\n%s\n' "$repo" "$revision" > "$out/source.txt"
