#!/bin/zsh
# An outside agent's beat during a film take's hold: a grant through the world's own gate for one body of
# the agent's own, then NeMo Agent Toolkit runs of that agent (agent_toolkit_run.py, each capped by what is
# left of the beat's allocation) restarted ten seconds after each ends, until the allocation's calls or
# dollars are used, a third provider error in a row, the beat's minutes, or the stop rule's pause; then the
# grant is closed, and the body goes home. The world's clock plays at the beat's speed meanwhile and at the
# take's speed after, set through the owner's playback control and only while the world plays.
#
#   AGENT_NAT=<the toolkit's nat command> AGENT_FACADE_PYTHON=<a Python with the agent library's MCP extra>
#   [EXULANICA_DEMO_ENV_FILE=<a file with a NEBIUS_API_KEY= line>]
#   zsh scripts/demo/take_agent.sh <take document> <run folder> [stand-in]
#
# The take document's "hold.agent" is the beat as data: "name", "maker", "mind" (a model id the manifest
# prices), "task" (what the toolkit is asked; it should say to enter the world), "minutes", "speed",
# "max_calls", "max_usd". A task written to <run folder>/agent-task.txt replaces the document's for the runs
# that start after it. The model key is read from EXULANICA_DEMO_ENV_FILE into each run's own process and
# nowhere else; "stand-in" runs a stand-in mind instead (no provider, no key, no cost), for a rehearsal.
# take_hold.sh calls this after it wrote <run folder>/hold-record.json.
set -u
DOC=${1:?name the take document}
RUN=${2:?name the run folder of the take}
STAND_IN=${3:-}
ROOT=${0:A:h:h:h}
DOC=${DOC:A}
RUN=${RUN:A}
NAT=${AGENT_NAT:?name the nat command of the toolkit in AGENT_NAT}
FACADE=${AGENT_FACADE_PYTHON:?name a Python with the MCP extra of the agent library in AGENT_FACADE_PYTHON}
log() { print -r -- "$(date '+%H:%M:%S') $*" >> $RUN/agent.log.txt; }
field() {
  python3 -c 'import json, sys
text = open(sys.argv[1]).read()
value = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
for key in sys.argv[2].split("."):
    value = value.get(key) if isinstance(value, dict) else None
print("" if value is None else value)' $1 $2
}
STACK=$(field $RUN/stack-up.json run_dir)
API=http://127.0.0.1:$(field $RUN/stack-up.json ports.api)
MINUTES=$(field $DOC hold.agent.minutes)
MAX_CALLS=$(field $DOC hold.agent.max_calls)
MAX_USD=$(field $DOC hold.agent.max_usd)
MIND=$(field $DOC hold.agent.mind)
TASK=$(field $DOC hold.agent.task)
WORLD=$(field $RUN/hold-record.json world_id)
VERSION=$(field $RUN/hold-record.json version_id)
GATE=$(field $RUN/hold-record.json travellers.gate)
cd $ROOT
# The world's clock at a speed, through the owner's playback control, only while it plays.
set_speed() {
  python3 - $RUN/hold-record.json $STACK/token $API $1 >> $RUN/agent.log.txt 2>&1 <<'SPEED'
import json, sys, time, urllib.parse, urllib.request
record = json.load(open(sys.argv[1])); token = open(sys.argv[2]).read().strip(); speed = int(sys.argv[4])
url = (f"{sys.argv[3]}/world/versions/{record['version_id']}/society/control?"
       + urllib.parse.urlencode({"world_id": record["world_id"]}))
def call(method, body=None):
    request = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(request, timeout=30))
control = call("GET")
if control["mode"] == "playing" and control["speed"] != speed:
    control = call("PUT", {"base_revision": control["revision"], "mode": "playing", "speed": speed})
print(f"{time.strftime('%H:%M:%S')} the world's clock: {control['mode']} at speed {control['speed']}")
SPEED
}
set_speed $(field $DOC hold.agent.speed)
KEYS=$(mktemp -d)
(cd bridges/agents && env -i PATH="$PATH" HOME="$HOME" EXULANICA_TOKEN="$(cat $STACK/token)" EXULANICA_URL=$API \
  PYTHONPATH=$ROOT/bridges/agents $FACADE -m exulanica_agent grant --world $WORLD --version $VERSION --visitors 1 \
  --gate $GATE --minutes 60 --key-file $KEYS/agent.key) > $RUN/agent-grant.json.txt 2>&1
GRANT=$(python3 -c 'import json, sys
print(json.loads(open(sys.argv[1]).read().strip().splitlines()[-1])["grant_id"])' $RUN/agent-grant.json.txt 2>/dev/null)
if [ -z "$GRANT" ]; then
  log "no grant: $(tail -1 $RUN/agent-grant.json.txt)"
  rm -rf $KEYS
  set_speed $(field $DOC speed)
  exit 1
fi
log "grant $GRANT through gate $GATE for one body; the beat's bound: $MAX_CALLS calls, USD $MAX_USD, $MINUTES minutes${STAND_IN:+ (stand-in mind, no provider)}"
END=$(( $(date +%s) + MINUTES * 60 ))
n=0
while :; do
  # What the runs so far used, and the provider errors at the end of their calls in a row.
  state=$(python3 scripts/demo/agent_toolkit_run.py --used $RUN)
  used_calls=${state%% *}
  rest=${state#* }
  used_usd=${rest%% *}
  row=${rest##* }
  left_calls=$(( MAX_CALLS - used_calls ))
  left_usd=$(python3 -c 'import sys
from decimal import Decimal
print(max(Decimal(sys.argv[1]) - Decimal(sys.argv[2]), Decimal(0)))' $MAX_USD $used_usd)
  if [ $row -ge 3 ]; then log "STOP RULE: three provider errors in a row for the agent's mind"; break; fi
  if [ $left_calls -lt 1 ] || python3 -c 'import sys
from decimal import Decimal
sys.exit(0 if Decimal(sys.argv[1]) <= 0 else 1)' $left_usd; then
    log "the beat's allocation is used: $used_calls calls, USD $used_usd"; break
  fi
  if [ $(date +%s) -ge $END ]; then log "the beat's $MINUTES minutes are over"; break; fi
  if [ -e $RUN/stop-rule.json ]; then log "the world is paused by the stop rule"; break; fi
  n=$((n + 1))
  [ -e $RUN/agent-task.txt ] && TASK=$(cat $RUN/agent-task.txt)
  RUN_ARGS=(--nat $NAT --facade-python $FACADE --world $API --key-file $KEYS/agent.key
    --record $RUN/agent-run-$n.json --mind $MIND --name "$(field $DOC hold.agent.name)"
    --maker "$(field $DOC hold.agent.maker)" --input "$TASK" --max-calls $left_calls --max-usd $left_usd
    --deadline-s $(( END - $(date +%s) )))
  if [ -n "$STAND_IN" ]; then
    env -u NEBIUS_API_KEY python3 scripts/demo/agent_toolkit_run.py "${RUN_ARGS[@]}" --stand-in \
      > $RUN/agent-run-$n.log.txt 2>&1
  else
    ENV_FILE=${EXULANICA_DEMO_ENV_FILE:?a live beat reads its model key from EXULANICA_DEMO_ENV_FILE}
    (
      export NEBIUS_API_KEY="$(sed -n 's/^NEBIUS_API_KEY=//p' $ENV_FILE)"
      python3 scripts/demo/agent_toolkit_run.py "${RUN_ARGS[@]}" > $RUN/agent-run-$n.log.txt 2>&1
    )
  fi
  log "run $n: $(tail -1 $RUN/agent-run-$n.log.txt | cut -c1-200)"
  sleep 10
done
python3 - $STACK/token $API $GRANT >> $RUN/agent.log.txt 2>&1 <<'CLOSE'
import sys, time, urllib.request
token = open(sys.argv[1]).read().strip()
request = urllib.request.Request(f"{sys.argv[2]}/door/grants/{sys.argv[3]}/revoke", data=b"", method="POST",
                                 headers={"Authorization": "Bearer " + token})
try:
    status = urllib.request.urlopen(request, timeout=30).status
except Exception as error:
    status = f"not closed: {type(error).__name__}"
print(f"{time.strftime('%H:%M:%S')} the grant is closed ({status})")
CLOSE
rm -rf $KEYS
set_speed $(field $DOC speed)
log "the agent's beat ends"
