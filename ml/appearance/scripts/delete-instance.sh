#!/bin/sh
# Delete a rented instance and prove it is gone, or watch until a deadline and then delete it.
#
#   scripts/delete-instance.sh now NAME
#   scripts/delete-instance.sh at  NAME DEADLINE_EPOCH_SECONDS
#
# `now` deletes and then lists, so the proof is in the output. `at` sleeps until the deadline and
# then does the same, and is meant to run in the background as this session's own watchdog. The
# orchestrator keeps an independent watchdog, because this one dies with the session; that is why the
# instance's name and its deadline go to the orchestrator the moment the machine exists.
#
# An idle machine of this class costs about $2.63 an hour, and a MassedCompute machine cannot be
# stopped, only deleted, so deletion is the only thing that ends the bill.
set -eu

mode="${1:?now or at}"
name="${2:?the instance name}"

delete() {
  printf '%s deleting %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${name}"
  brev delete "${name}" || printf 'brev delete refused; delete %s in the console NOW\n' "${name}" >&2
  sleep 10
  printf '%s what the account holds now:\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  brev ls || printf 'brev ls refused; check the console\n' >&2
  if brev ls 2>/dev/null | grep -q -- "${name}"; then
    printf '%s IS STILL LISTED: delete it in the console NOW\n' "${name}" >&2
    exit 1
  fi
  printf '%s is gone\n' "${name}"
}

case "${mode}" in
  now)
    delete
    ;;
  at)
    deadline="${3:?the deadline in epoch seconds}"
    case "${deadline}" in
      ''|*[!0-9]*) echo "delete-instance: the deadline is epoch seconds" >&2; exit 2 ;;
    esac
    printf 'watching %s until %s\n' "${name}" "$(date -u -r "${deadline}" +%Y-%m-%dT%H:%M:%SZ)"
    while [ "$(date +%s)" -lt "${deadline}" ]; do
      sleep 30
    done
    delete
    ;;
  *)
    echo "delete-instance: the mode is now or at" >&2
    exit 2
    ;;
esac
