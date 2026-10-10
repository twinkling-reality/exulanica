#!/bin/zsh
# What happens outside the page while a film take holds, one command beside
# `TAKE_HOLD=yes zsh scripts/demo/take_run.sh <take document> <run folder>`. It waits for the take's
# hold-start mark, writes the world's record (start_society.py reads the society back), then, as the take
# document's "hold" says:
#   - provider_failure_guard.py watches the stop rule (a third provider failure in a row for any mind pauses
#     the world) until take_run.sh has read the receipts (<run folder>/guard-stop);
#   - "crossing" {"lives_s", "call_home_limit_s", "runs", "home_item"}: the game's crossing check, with its
#     stand-in player (no game window), joins this stack: its first visitor is sent home after lives_s, its
#     second is called home once it holds a thing of the world or after call_home_limit_s. The check runs
#     again, up to "runs" times, while no run has delivered "home_item" to the game (a mind may hand the
#     second visitor another thing of the world first, which ends that run's protocol);
#   - "requests": hold_requests.py writes a person's requests for the take's driver to type, the give and the
#     receiver's own pick-up only past the departures before each run's first visitor has left;
#   - "agent": take_agent.sh, an outside agent's beat, once the crossing has ended;
# and creates <run folder>/crossed, so the take goes on to the card: at once when the guard pauses the world
# (a running check is ended, with its game server), else when the above has ended.
#
#   [TAKE_GAME_PORT=<the game server's UDP port; default the stack's spare port>]
#   zsh scripts/demo/take_hold.sh <take document> <run folder> [stand-in]
#
# "stand-in" gives the agent's beat a stand-in mind (no provider, no cost), for a rehearsal.
set -u
DOC=${1:?name the take document}
RUN=${2:?name the run folder of the take}
STAND_IN=${3:-}
ROOT=${0:A:h:h:h}
DOC=${DOC:A}
RUN=${RUN:A}
log() { print -r -- "$(date '+%H:%M:%S') $*" >> $RUN/hold.log.txt; }
field() {
  python3 -c 'import json, sys
text = open(sys.argv[1]).read()
value = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
for key in sys.argv[2].split("."):
    value = value.get(key) if isinstance(value, dict) else None
print("" if value is None else value)' $1 $2
}
until [ -e $RUN/run.log.txt ] && grep -q "mark hold-start" $RUN/run.log.txt; do
  if [ -e $RUN/run.log.txt ] && grep -qE "the take stopped|[0-9] end$" $RUN/run.log.txt; then
    log "the take ended before its hold"
    exit 1
  fi
  sleep 2
done
STACK=$(field $RUN/stack-up.json run_dir)
API=http://127.0.0.1:$(field $RUN/stack-up.json ports.api)
GAME_PORT=${TAKE_GAME_PORT:-$(field $RUN/stack-up.json ports.spare)}
SCENE=$(field $DOC scene)
log "hold-start seen; the stack's run directory $STACK"
cd $ROOT
# The take's own world among the workspace's saved worlds is the one it named (a take that made its town
# leaves the first world beside it); with no single world of that title, the workspace's only one.
ENTRY=$(python3 - $STACK/token $API "$(field $DOC title)" <<'ENTRY'
import json, sys, urllib.request
token = open(sys.argv[1]).read().strip()
request = urllib.request.Request(sys.argv[2] + "/world-entries", headers={"Authorization": "Bearer " + token})
body = json.load(urllib.request.urlopen(request, timeout=30))
entries = body if isinstance(body, list) else body.get("entries", [])
named = [entry["entry_id"] for entry in entries if entry.get("title") == sys.argv[3]]
print(named[0] if len(named) == 1 else "")
ENTRY
)
log "the take's world: ${ENTRY:-the workspace's only one}"
EXULANICA_TOKEN="$(cat $STACK/token)" python3 scripts/demo/start_society.py $SCENE --base-url $API \
  --record $RUN/hold-record.json ${ENTRY:+--entry} $ENTRY >> $RUN/hold.log.txt 2>&1
if [ ! -e $RUN/hold-record.json ]; then
  log "no record of the world: nothing runs in this hold"
  touch $RUN/crossed
  exit 1
fi
python3 -u scripts/demo/provider_failure_guard.py --api $API --record $RUN/hold-record.json --token-file $STACK/token \
  --stop $RUN/guard-stop --log $RUN/failure-guard.log.txt --tripped $RUN/stop-rule.json > /dev/null 2>&1 &
GUARD=$!
# The world's departures so far, from its events (all pages).
departures() {
  python3 - $RUN/hold-record.json $STACK/token $API <<'DEPARTURES'
import json, sys, urllib.parse, urllib.request
record = json.load(open(sys.argv[1])); token = open(sys.argv[2]).read().strip()
base = f"{sys.argv[3]}/world/versions/{record['version_id']}/society/events"
count, before = 0, None
while True:
    query = urllib.parse.urlencode({"world_id": record["world_id"], **({"before": before} if before else {})})
    request = urllib.request.Request(f"{base}?{query}", headers={"Authorization": "Bearer " + token})
    page = json.load(urllib.request.urlopen(request, timeout=30))
    count += sum(1 for event in page["events"] if event["event_kind"] == "thing_departed")
    if not page.get("next"):
        break
    before = str(page["next"])
print(count)
DEPARTURES
}
RUNS=$(field $DOC hold.crossing.runs)
if [ -n "$(field $DOC hold.crossing)" ]; then
  LIVES=$(field $DOC hold.crossing.lives_s)
  LIMIT=$(field $DOC hold.crossing.call_home_limit_s)
  HOME_ITEM=$(field $DOC hold.crossing.home_item)
  MAPPING=$(field $DOC doors.game.mapping)
  run=0
  while [ $run -lt ${RUNS:-1} ] && [ ! -e $RUN/stop-rule.json ]; do
    run=$((run + 1))
    gone=$(departures 2>/dev/null)
    after=$(( ${gone:-0} + 1 ))
    ASKS=
    if [ -n "$(field $DOC hold.requests)" ]; then
      python3 -u scripts/demo/hold_requests.py --api $API --record $RUN/hold-record.json --token-file $STACK/token \
        --take $DOC --say $RUN/crossed.say --stop $RUN/requests-stop-$run --after-departures $after \
        --log $RUN/hold-requests-$run.log.txt > /dev/null 2>&1 &
      ASKS=$!
    fi
    .venv/bin/python bridges/luanti/run/check.py --api $API --token-file $STACK/token --record $RUN/hold-record.json \
      --luanti-port $GAME_PORT --mapping $MAPPING --traveller-mind --lives-s ${LIVES:-30} --call-home-when-holding \
      --call-home-limit-s ${LIMIT:-360} > $RUN/crossing-check-$run.log.txt 2>&1 &
    CHECK=$!
    log "crossing check run $run (lives ${LIVES:-30} s, called home by ${LIMIT:-360} s; requests past $after departures)"
    while kill -0 $CHECK 2>/dev/null; do
      if [ -e $RUN/stop-rule.json ]; then
        # A command started in the background by a script ignores an interrupt, so the check is ended
        # outright, and the game server it started with it (the check would have stopped it itself).
        log "STOP RULE: the guard paused the world; the check is ended"
        game=($(pgrep -P $CHECK 2>/dev/null))
        kill $CHECK 2>/dev/null
        for tries in {1..10}; do kill -0 $CHECK 2>/dev/null || break; sleep 1; done
        kill -0 $CHECK 2>/dev/null && kill -KILL $CHECK 2>/dev/null
        for child in $game; do kill $child 2>/dev/null; done
        break
      fi
      sleep 3
    done
    wait $CHECK
    log "crossing check run $run ended (exit $?)"
    touch $RUN/requests-stop-$run
    [ -n "$ASKS" ] && wait $ASKS
    home=$(python3 -c 'import json, sys
text = open(sys.argv[1]).read()
try:
    summary = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
    print(sys.argv[2] in (summary.get("called_home") or {}).get("delivered", []))
except Exception:
    print(False)' $RUN/crossing-check-$run.log.txt "$HOME_ITEM")
    log "crossing check run $run: $HOME_ITEM went home: $home"
    [ "$home" = True ] && break
  done
fi
if [ -n "$(field $DOC hold.agent)" ] && [ ! -e $RUN/stop-rule.json ]; then
  log "the outside agent's beat: take_agent.sh${STAND_IN:+ ($STAND_IN)}"
  zsh scripts/demo/take_agent.sh $DOC $RUN $STAND_IN
  log "the outside agent's beat ended (exit $?)"
fi
touch $RUN/crossed
log "the hold ends; the guard watches until the receipts are read"
wait $GUARD
log "hold done (guard exit $?)"
