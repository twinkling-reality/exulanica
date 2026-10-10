#!/bin/zsh
# One film take on a port slot, one command: a stack of this checkout (live minds on Nebius Token Factory
# inside a bound, or with TAKE_PLAN a scripted rehearsal that asks no provider), the doors the take document
# declares, then film_take.mjs records and drives the app, then the society's receipts are read while the
# stack still holds them, then the stack goes down.
#
#   [TAKE_PLAN=<a scripted model plan>] [TAKE_HOLD=yes] [TAKE_PORT_BASE=19200]
#   [EXULANICA_DEMO_ENV_FILE=<a file with a NEBIUS_API_KEY= line>] [TAKE_BUDGET_USD=0.50]
#   [TAKE_BUDGET_CALLS=300] [TAKE_OWN_LOOK=<a look document a game's visitors arrive in>]
#   [TAKE_TICK_INTERVAL_MS=<the base wait between world minutes; the stack's own default without it>]
#   zsh scripts/demo/take_run.sh <take document> <new run folder> [film_take.mjs options...]
#
# The take document (scripts/demo/takes/, profile exulanica.film-take/v1) is data; beside what
# film_take.mjs reads, this script reads its optional "scene" (the scene catalog file whose record
# start_society.py reads back: needed for the receipts) and "doors": {"game": {"label", "mapping"}} (a game's
# bridge, declared with those words and that mapping file of bridges/luanti) and "agents" (a bridge entry
# file for outside agents, added beside it), and whether it states "creatures" (the person makes a creature
# in the page: the stack then drafts creatures). With TAKE_HOLD=yes the take holds after its alive stretch until
# <run folder>/crossed exists; take_hold.sh is what runs meanwhile.
#
# A live take needs EXULANICA_DEMO_ENV_FILE: the key is read from it into the stack's own process
# environment and nowhere else. The stack's own bound stops model calls at TAKE_BUDGET_USD or
# TAKE_BUDGET_CALLS. Everything is written under the run folder: run.log.txt, stack-up.json, bridges.json,
# take/ (the video, its marks and stills), take-record.json, receipts/.
set -eu
DOC=${1:?name the take document}
RUN=${2:?name a new run folder}
shift 2
ROOT=${0:A:h:h:h}
DOC=${DOC:A}
RUN=${RUN:A}
BASE=${TAKE_PORT_BASE:-19200}
test ! -e $RUN
mkdir -p $RUN
log() { print -r -- "$(date '+%H:%M:%S') $*" >> $RUN/run.log.txt; }
# A field of a JSON document by its dotted path, or nothing where it is absent.
field() {
  python3 -c 'import json, sys
text = open(sys.argv[1]).read()
value = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
for key in sys.argv[2].split("."):
    value = value.get(key) if isinstance(value, dict) else None
print("" if value is None else value)' $1 $2
}
cd $ROOT
log "start $(date '+%Y-%m-%d %Z'), tree $(git rev-parse HEAD) plus $(git status --porcelain | wc -l | tr -d ' ') changed paths"
log "take document $DOC ($(shasum -a 256 < $DOC | cut -c1-16))"
DOORS=()
GAME_MAPPING=$(field $DOC doors.game.mapping)
if [ -n "$GAME_MAPPING" ]; then
  GAME_LABEL=$(field $DOC doors.game.label)
  .venv/bin/python bridges/luanti/tools/cross_once.py declare $RUN/bridges.json --label "$GAME_LABEL" \
    --game "$GAME_LABEL" --mapping $GAME_MAPPING >> $RUN/run.log.txt 2>&1
fi
AGENTS_ENTRY=$(field $DOC doors.agents)
if [ -n "$AGENTS_ENTRY" ]; then
  python3 -c 'import json, sys
from pathlib import Path
doors = Path(sys.argv[1])
bridges = json.loads(doors.read_text()) if doors.exists() else []
bridges.append(json.loads(Path(sys.argv[2]).read_text()))
doors.write_text(json.dumps(bridges, indent=1) + "\n")
print("bridges:", [bridge["bridge"] for bridge in bridges])' $RUN/bridges.json $AGENTS_ENTRY >> $RUN/run.log.txt 2>&1
fi
[ -e $RUN/bridges.json ] && DOORS=(--door-bridges $RUN/bridges.json)
# The world's clock: how long a world minute lasts at 1x (the launcher's own option; the API checks it).
CLOCK=()
if [ -n "${TAKE_TICK_INTERVAL_MS:-}" ]; then
  CLOCK=(--society-tick-interval-ms $TAKE_TICK_INTERVAL_MS)
  log "a world minute every $TAKE_TICK_INTERVAL_MS ms at 1x"
fi
# Creature drafting on, where the take has the person make a creature (its "creatures").
MAKES=()
if [ -n "$(field $DOC creatures)" ]; then
  MAKES=(--creatures)
  log "creature drafting is on: the take makes creatures"
fi
# A recording is never reloaded. The development server reloads the page whenever it is told a source
# file changed, and one reload during a take throws the page back to the list of worlds; this machine's
# file events can arrive an hour late, naming files nobody is writing. So the server watches no file for
# a take (the app's vite.config.ts reads this). A production build would do the same but carries no
# credential, and the take would record the access gate at every page load.
export TAKE_APP_WATCHES_NOTHING=yes
log "the app's development server watches no file: nothing reloads the page during the take"
if [ -n "${TAKE_PLAN:-}" ]; then
  log "scripted plan ${TAKE_PLAN:A} ($(shasum -a 256 < $TAKE_PLAN | cut -c1-16)); no key, no provider"
  env -u NEBIUS_API_KEY -u EXULANICA_EGRESS_ALLOWLIST .venv/bin/python scripts/acceptance/launch.py up \
    --worktree $ROOT --slot 0 --port-base $BASE --society-of-things --society-playback \
    --scripted-model ${TAKE_PLAN:A} "${DOORS[@]}" "${CLOCK[@]}" "${MAKES[@]}" > $RUN/stack-up.json 2>> $RUN/run.log.txt
else
  ENV_FILE=${EXULANICA_DEMO_ENV_FILE:?a live take reads its model key from EXULANICA_DEMO_ENV_FILE}
  log "live minds on Nebius Token Factory, at most USD ${TAKE_BUDGET_USD:-0.50} and ${TAKE_BUDGET_CALLS:-300} calls"
  (
    export NEBIUS_API_KEY="$(sed -n 's/^NEBIUS_API_KEY=//p' $ENV_FILE)"
    export EXULANICA_EGRESS_ALLOWLIST='["https://api.tokenfactory.nebius.com"]'
    export EXULANICA_BUDGET_USD=${TAKE_BUDGET_USD:-0.50} EXULANICA_BUDGET_MAX_CALLS=${TAKE_BUDGET_CALLS:-300}
    export EXULANICA_SPENDING=process
    .venv/bin/python scripts/acceptance/launch.py up --worktree $ROOT --slot 0 --port-base $BASE \
      --society-of-things --society-playback --model "${DOORS[@]}" "${CLOCK[@]}" "${MAKES[@]}" > $RUN/stack-up.json 2>> $RUN/run.log.txt
  )
fi
STACK=$(field $RUN/stack-up.json run_dir)
API=http://127.0.0.1:$(field $RUN/stack-up.json ports.api)
log "stack up, run directory $STACK"
if [ -n "${TAKE_OWN_LOOK:-}" ] && [ -n "$GAME_MAPPING" ]; then
  # The look a game's visitors arrive in, admitted to this stack's workspace as its owner would.
  .venv/bin/python - ${STACK:h}/state.json ${TAKE_OWN_LOOK:A} bridges/luanti/mod/exulanica_gate/mapping/$GAME_MAPPING \
    >> $RUN/run.log.txt 2>&1 <<'ADMIT' || log "the own look was not admitted (exit $?)"
import json, os, re, subprocess, sys
from pathlib import Path
state = json.loads(Path(sys.argv[1]).read_text())
document = Path(sys.argv[2])
container = document.with_name(re.sub(r"\.v\d+\.json$", ".glb", document.name))
environment = {"PATH": os.environ["PATH"], "EXULANICA_DATABASE_URL": state["database"]["runtime_url"],
               "EXULANICA_DATA_DIR": state["data_dir"], "EXULANICA_DOOR_BRIDGES": state["door_bridges"]}
done = subprocess.run(
    [sys.executable, "-m", "exulanica.api.thing_store_command", "admit-look", "--workspace", state["workspace_id"],
     "--actor", state["actor"], "--document", str(document), "--container", str(container), "--mapping", sys.argv[3],
     "--apply"], env=environment, capture_output=True, text=True)
said = [line for line in (done.stdout + done.stderr).splitlines() if "postgresql://" not in line]
print(f"own look {document.name}: exit {done.returncode} | " + " / ".join(said[-2:])[:400])
ADMIT
fi
HOLD=()
if [ "${TAKE_HOLD:-}" = yes ]; then
  HOLD=(--hold $RUN/crossed --hold-minutes 30)
  log "the take will hold after its alive stretch until $RUN/crossed exists (take_hold.sh)"
fi
node scripts/demo/film_take.mjs $DOC --out $RUN/take --url http://localhost:$(field $RUN/stack-up.json ports.vite)/ \
  --port $(field $RUN/stack-up.json ports.browser) "${HOLD[@]}" "$@" >> $RUN/run.log.txt 2>&1 \
  || log "the take stopped (exit $?)"
# The receipts live in this stack's database: read them before it goes down.
SCENE=$(field $DOC scene)
if [ -n "$SCENE" ]; then
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
  EXULANICA_TOKEN="$(cat $STACK/token)" python3 scripts/demo/start_society.py $SCENE --base-url $API \
    --record $RUN/take-record.json ${ENTRY:+--entry} $ENTRY >> $RUN/run.log.txt 2>&1 \
    || log "no record of the world (exit $?)"
  # A world a stop rule paused (provider_failure_guard.py's stop-rule.json) is read as it stands.
  MINUTES=1
  if [ -e $RUN/stop-rule.json ]; then MINUTES=0; log "the stop rule paused the world: read without playing"; fi
  EXULANICA_TOKEN="$(cat $STACK/token)" python3 -u scripts/demo/read_society_receipts.py --base-url $API \
    --record $RUN/take-record.json --minutes $MINUTES --speed 4 --wait-seconds 300 --out $RUN/receipts \
    >> $RUN/run.log.txt 2>&1 || log "the receipts were not read (exit $?)"
else
  log "the take document names no scene: no record and no receipts"
fi
python3 - $RUN/take/companion-traffic.json >> $RUN/run.log.txt 2>&1 <<'COMPANION' || true
import json, sys
from decimal import Decimal
calls = [call for entry in json.load(open(sys.argv[1])) if isinstance(entry.get("response_body"), dict)
         for call in ((entry["response_body"].get("execution") or {}).get("calls") or [])]
print("Companion calls on the page:", len(calls), "USD", sum(Decimal(c["usd"]) for c in calls if c.get("usd")),
      "every cost known:", all(c.get("cost_basis") == "known" for c in calls))
COMPANION
touch $RUN/guard-stop
.venv/bin/python scripts/acceptance/launch.py down --worktree $ROOT | tail -1 >> $RUN/run.log.txt
log "end"
cat $RUN/run.log.txt
