# The 0 A.D. gate

A citizen soldier of a running 0 A.D. match walks to a standard on the map, leaves the match, and
walks into an Exulanica world through its gate as a traveller: the world's own mind decides what it
does there (or a person plays it in the app). When it leaves the world, it is back at the standard
in the match. The game shows nothing new but the standard; no menu, no text from the world.

The door it speaks: [door contract](../../docs/door-contract.md). Licences:
[LICENCE-NOTES.md](LICENCE-NOTES.md).

## What crosses

`mapping/zero-ad-empires-ascendant.v1.json` (profile `exulanica.bridge-mapping/v2`): an Athenian
hoplite (`units:athen:infantry_spearman_b`, the template `units/athen/infantry_spearman_b` with `:`
for `/`) crosses as THINGS's `traveller` kind, version 2. No item crosses (a 0 A.D. unit carries
none). What stays behind, each with its reason: the player's name, hitpoints, armour and attack,
rank, formation and stance, carried resources, garrison, position, and every unit the mapping does
not name. `mapping/reads.json` is what the adapter declares it reads; the door checks the two
against each other at hello.

## How it works

The game, started with `--rl-interface=127.0.0.1:<port>`, serves `/reset`, `/step`, `/evaluate` and
`/templates` (`exulanica_zero_ad/rl.py`). The adapter starts the match from its settings, stands the
standard on the gate (`/evaluate`), then steps the match one turn at a time (one every 200 ms):

1. a unit of the gate's player standing on the gate, of a template the mapping names, is sent through
   the door as an arrival (`POST /door/channel/arrivals`, in the mapping's look); once the door takes
   it, the unit is taken out of the match;
2. the door's frames are read by long poll on a thread of their own: when one of its soldiers
   departs, or its arrival is refused, a unit of the same template is put back on the gate for its
   owner; when the grant ends, every soldier still away comes back;
3. it decides nothing for a visitor; an ask, were a grant to send one, is answered with the option
   that changes nothing.

A journal file of the operator's keeps what is away and the door's cursor, so a restart brings back
whoever departed meanwhile. Credentials: the grant's channel credential is read from the environment
(`EXULANICA_DOOR_CREDENTIAL`) only.

## Running it

    EXULANICA_DOOR_CREDENTIAL=... python -m exulanica_zero_ad \
        --door <the door's address> --match <match settings.json> --gate <x>,<z>,<radius> \
        --journal <a file of the operator's> [--marker <template of the standard>]

run from `bridges/zero_ad`. The game is reached on this machine only, at a loopback address.

## Match settings

`--match` names the match the adapter starts with `/reset`: the game's own match attributes, its
`settings` (players and their civilisations, victory conditions, seeds), `mapType`, `map` and
`gameSpeed`. With a window, 0.28's loading page also reads `settings.mapName`; without it the page
fails and the window stays on the main menu while the match runs.
`matches/greek-acropolis-athenians.json` is the skirmish map Greek Acropolis (2) with player 1 as the
Athenians, whose starting units include the hoplite the mapping names.

## The end-to-end check

`run/check.py` runs one crossing against this checkout's own stack, with the game already running at
its loopback address: it starts the stack on a port slot with this bridge declared, builds the demo's
scene and grants one hoplite, stands the standard where a hoplite of the match stood and walks it back
onto it, runs the adapter's loop, sends the visitor home as the world's owner after `--lives-s`
seconds unless its mind leads it home first, and reads the world's records (the look worn, the
crossing's manifest of what came across and what stayed behind, who decided, the replay). It writes
the run's summary and every exchange, with no credential, into
`.exulanica/zero-ad-checks/` and brings the stack down. With `--scripted-model run/plans/<plan>.json
--traveller-mind` a scripted model is the soldier's mind, so no provider is called:
`soldier-leaves.json` leaves when it may, `soldier-waits.json` waits until it is sent home.

For a take in a stack started for it, as a film or a demo does:

1. `run/check.py --declare <file>` writes this bridge into the door bridge declarations the stack
   starts with (`scripts/acceptance/launch.py up --door-bridges <file>`): beside the bridges the
   file already declares, so one stack lets several games in (the Luanti tool's `declare` writes
   its file anew, so it goes first), and in place of an earlier entry of this bridge. A film or a
   demo names no game, so the bridge is declared as "another open-source game" unless `--label`
   and `--game-words` say otherwise (each one line of 1 to 80 characters).
2. `run/check.py --api <the stack's API> --token-file <the owner's token> --record <the scene
   builder's record>` joins that stack once its scene is built (`scripts/demo/build_scene.py
   --record`): it starts and stops no stack and builds nothing, crosses into the world the record
   names, keeps the owner's token in its own process, and closes the grant it issued when it ends.
   The summary keeps the words the stack shows for the bridge.

## Tests

`tests/test_bridge_zero_ad.py` holds the mapping to the door's checks and the adapter to fakes of the
game and the door: no test needs the game installed.
