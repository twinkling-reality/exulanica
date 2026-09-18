#!/bin/sh
# Wait for a detached remote session to finish, then bring it home. Poll only: every failed poll is
# a dropped link and nothing more, so the operator can close the laptop whenever they like.
#
#   scripts/collect-session.sh HOST WORK_DIR JOB [JOB...]
set -eu
host="${1:?an ssh destination}"
work="${2:?a directory on this machine for the results}"
shift 2
jobs_to_collect="$*"
here=$(cd "$(dirname "$0")/.." && pwd)
python="${here}/.venv/bin/python"
remote="appearance"
ssh_opts="-o ConnectTimeout=20 -o BatchMode=yes"

printf '%s waiting for %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${jobs_to_collect}"
while true; do
  marker=$(ssh ${ssh_opts} "${host}" "cat ${remote}/remote-done 2>/dev/null" 2>/dev/null || true)
  case "${marker}" in
    *"ALL DONE"*) break ;;
  esac
  sleep 60
done
printf '%s the machine says it is done:\n%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${marker}"

for job in ${jobs_to_collect}; do
  # Retry the copy rather than give up on it: the results are the whole return on the spend.
  attempt=1
  while [ "${attempt}" -le 10 ]; do
    if rsync -a -e "ssh ${ssh_opts}" "${host}:${remote}/out-${job}" "${work}/" \
       && rsync -a -e "ssh ${ssh_opts}" "${host}:${remote}/run-${job}.log" "${work}/run-${job}.log.txt"; then
      break
    fi
    printf 'copy of %s failed, attempt %s; waiting\n' "${job}" "${attempt}"
    attempt=$((attempt + 1))
    sleep 30
  done
  "${python}" -m exulanica_appearance runner check --out "${work}/out-${job}" || true
done
rsync -a -e "ssh ${ssh_opts}" "${host}:${remote}/remote.log" "${work}/remote.log.txt" || true
printf '%s collected. The machine is still running: delete it.\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
