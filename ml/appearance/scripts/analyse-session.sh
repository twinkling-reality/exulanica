#!/bin/sh
# Everything measured about a finished session, in one pass, so the numbers in a report come from a
# committed command rather than from whatever was typed that night.
#
#   scripts/analyse-session.sh WORK_DIR REPOSITORY [PREVIOUS_RESULTS_DIR]
#
#     WORK_DIR              what came back from the machine: out-<job>/ and staged-<job>/ inside it
#     REPOSITORY            the repository root, for the published sets each generation dresses
#     PREVIOUS_RESULTS_DIR  optional: a previous run of track-a-session-1, to compare against this
#                           one by digest. That comparison is the only thing that says whether this
#                           pipeline is deterministic across machines.
#
# It writes one measurement document per job, the comparison when a previous run is given, and the
# before-and-after pair sheets. It measures and never generates, so it costs nothing but disk.
set -eu
work="${1:?what came back from the machine}"
repository="${2:?the repository root}"
previous="${3:-}"
here=$(cd "$(dirname "$0")/.." && pwd)
python="${here}/.venv/bin/python"

for out in "${work}"/out-*; do
  job=$(basename "${out}" | sed 's/^out-//')
  [ -f "${out}/results.json" ] || { echo "skipping ${job}: no results.json"; continue; }
  echo "== ${job}"
  "${python}" -m exulanica_appearance runner check --out "${out}"
  "${python}" -m exulanica_appearance measure session --repository "${repository}" \
    --results "${out}" --staged "${work}/staged-${job}" --out "${work}/${job}-measurements.json"
  "${python}" -m exulanica_appearance sheet pairs --repository "${repository}" \
    --results "${out}" --out "${work}/pairs-${job}"
done

if [ -n "${previous}" ]; then
  echo "== determinism: this run of track-a-session-1 against ${previous}"
  "${python}" -m exulanica_appearance measure compare --first "${previous}" \
    --second "${work}/out-track-a-session-1" --out "${work}/determinism.json"
fi
echo "== measured. The look at every texel of anything picked is a separate, deliberate step."
