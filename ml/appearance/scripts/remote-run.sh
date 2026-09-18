#!/bin/sh
# Run the named jobs ON THE RENTED MACHINE, detached from any ssh connection.
#
#   nohup setsid sh remote-run.sh DOCKER_REF RECORD_PIN JOB [JOB...] > remote.log 2>&1 < /dev/null &
#
# The Mac only polls for the done marker afterwards, so a dropped link, a closed laptop or a
# reconnect costs nothing. MEASURED 2026-09-18: the driver held the container through a foreground
# ssh, so a 15 minute wifi gap would have killed a 64-generation job and the hard timeout with it,
# leaving the instance billing with no stop in front of it.
#
# Each job keeps its own stop: the limit is read from the staged job.json, and `timeout` inside
# container/run.sh still owns the hard kill, now under a process that no connection can hang up.
set -eu
docker_ref="${1:?the image to run}"
record_pin="${2:?what the records name the image by}"
shift 2
root="${HOME}/appearance"
: > "${root}/remote-done"
for job in "$@"; do
  limit=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['stop_at_seconds'])" \
    "${root}/staged-${job}/job.json")
  printf '%s starting %s, hard limit %s s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${job}" "${limit}"
  rm -rf "${root}/out-${job}"
  status=0
  "${root}/ml-appearance/container/run.sh" "${docker_ref}" "${record_pin}" \
    "${root}/staged-${job}" "${root}/weights" "${root}/out-${job}" "${limit}" \
    > "${root}/run-${job}.log" 2>&1 || status=$?
  printf '%s finished %s with status %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${job}" "${status}"
  printf '%s %s\n' "${job}" "${status}" >> "${root}/remote-done"
  [ "${status}" -eq 0 ] || { printf 'stopping: %s did not succeed\n' "${job}"; break; }
done
printf '%s all jobs attempted\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'ALL DONE\n' >> "${root}/remote-done"
