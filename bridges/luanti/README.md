# The Luanti gate

A Luanti server mod, `exulanica_gate`, that puts a gate in a Luanti world. A player who walks into
the gate's light sends their character through it into an Exulanica world, through the
[door](../../docs/door-contract.md): the character arrives there as a thing of its own, looking like
itself and carrying one thing from the player's hand, and lives there, with a mind of that world.
The player is never held and decides nothing for it: they play on, and one line above their hotbar
says where their character is. When it comes home (it chooses to leave, the world's owner sends it,
the player calls it home with `/comehome`, or the gate closes), what it carries lands in the
player's inventory, or waits for them if they are away. Nothing in the Luanti window is a menu of
the world's options; the world is seen in Exulanica.

The mod uses the engine's own API and nothing of any game, so one mod serves every Luanti game.
What a game's characters and items become in Exulanica is that game's mapping file
(`mod/exulanica_gate/mapping/`), which is data. Each published version of a mapping stays beside
the next, so a deployment that pinned one keeps working: version 1 (profile
`exulanica.bridge-mapping/v1`) names a look by its digest, and version 2 (profile
`exulanica.bridge-mapping/v2`, the mod's default) by the thing library's reference.

## What works today, and what does not yet

| Part | State |
| --- | --- |
| The channel: hello with the adapter's version, mapping and the game fields it reads; one held poll per grant; refusals read from bodies | Works against the door's channel routes |
| A character crossing into a world: through the world's gate with one thing from the hand, the player told once when it arrives, its things delivered once when it comes home (also to a player who left the game meanwhile) | Works against the door's crossing routes; a scripted check plays it on a headless server against the demo's scene (below) |
| The world deciding for the character | Works against the door: where a grant says the world decides for its visitors, no ask about the character reaches the gate, and the world's routine or the mind the world's owner names for travellers decides; the scripted check plays both (the mind with `--traveller-mind`, answered by a scripted model with `--scripted-model`, which calls no provider). Where a grant names the gate instead, its asks come and the gate leaves each to the world's routine |
| Lines the character says and hears in the world | The door tells the gate each one; the mod shows none of them in the game (the world is seen in Exulanica), and the scripted check holds every line against what the player was told |
| A character in the player's own look (the game's own player picture, built by `tools/build_look.py`) | The world shows it once its thing store holds the built look; until then the character arrives in the CC0 look |
| Calling a character home from the game (`/comehome`; not `/home`, which Minetest Game's own `sethome` mod names a player's home point) | Works against the door's home route (`POST /door/channel/home`) and the stand-in door; the scripted check plays it on both. On a door without the route the player is told the world cannot call characters home yet |
| A player's items crossing as themselves (a book, a diamond, a steel pickaxe: each its own look and kind, built by `tools/build_items.py` from the operator's copy) | Built and checked against the thing contract's readers; crossing waits for the door to read mapping profile v3, a workspace to admit item kinds, and the crossing's kind check to read them; until then items cross as mapping v2 says (a torch as a lantern, a sword) |
| Invites (`/cross`, a code pasted into a masked form, for a server whose gate opens only by codes) | Works against the door's invite routes; the scripted check plays it with `--invite`: a code that opens nothing refused in words, the world's code opening the gate for that player, the same code refused the second time, then the crossing |

## Layout

| Path | What it is |
| --- | --- |
| `mod/exulanica_gate/` | The mod: `init.lua` wires settings and callbacks; `channel.lua` speaks to the door; `journey.lua` is one player's character away; `crossing.lua` sends it and brings it home; `panel.lua` is the one line the player sees; `lines.lua` makes a world's words plain text; `gate.lua` draws and places the gate; `store.lua`, `record.lua`, `json.lua` and `engine.lua` are plumbing |
| `mod/exulanica_gate/adapter.json` | The adapter's version and the game fields it reads (with every item its mapping lists) |
| `mod/exulanica_gate/mapping/` | The mapping files for each Luanti game, every published version kept |
| `check/exulanica_gate_check/` | A test mod that plays a player on a headless server |
| `run/` | `install.sh` unpacks the engine and the game; `check.py` runs the scripted check on its own stack or one already running (`--api`), with a scripted model where asked (`--scripted-model`, plans in `run/plans/`), lists the game's items (`--census`), or with `--play NAME` serves a world for a person; `serve.sh` and `play.sh` run the demo server and a window joined to it |
| `tools/` | `build_look.py` builds a player's own look; `build_items.py` builds, from the hand-written `items.v1.json`, the look and thing kind each listed game item crosses as (see [the licence notes](LICENCE-NOTES.md)); `cross_once.py` makes one character cross into a running stack exactly as the mod would, with no game (for checking how a world shows it); `fake_door.py` is a stand-in door for checks; `fixtures.py` turns a recorded run into a fixture |
| `fixtures/` | Exchanges recorded from real runs, which the repository's tests read |
| `LICENCE-NOTES.md` | What the adapter uses of Luanti and Minetest Game, and their licences |

## Running it

1. Unpack the engine and the game from the two allocated archives into the ignored
   `.exulanica/luanti/` (the script checks each archive's SHA-256 and never downloads):
   `bridges/luanti/run/install.sh <folder holding the archives>`.
2. The server's settings name the door (`exulanica_gate.door_url`), and `secure.http_mods` lists
   `exulanica_gate` (never `secure.trusted_mods`, which would lift Luanti's sandbox). Every setting
   is documented in `mod/exulanica_gate/settingtypes.txt`.
3. The server's channel credential reaches the mod only through the server process's environment,
   `EXULANICA_GATE_CHANNEL_CREDENTIAL`, read once at load. It is never a setting, never logged and
   never written by the mod.

## The scripted check

`<checkout>/.venv/bin/python bridges/luanti/run/check.py` starts this checkout's stack on one port
slot with a society of things, builds a scene (by default the demo's, at the newest version the
scene catalog's lock names, `assets/catalogs/scenes`; built by `scripts/demo/build_scene.py`, every
being on its routine, no model called) and grants the `luanti` bridge one traveller through the
scene's gate, carrying things both ways. For a scene that names its travellers (the gate they come
through and the mind the world gives them), the grant opens that gate and, where the door's grants
can say so, says the world decides for them; their paid mind is named only with `--traveller-mind`,
under an allocation, or with a scripted model answering for it (`--scripted-model PLAN`, plans in
`run/plans/`: the travellers wait, say a line to everyone near, or leave where their kind can
leave), which calls no provider and costs nothing. The check then expects no ask about the character
to reach the gate. With
`--invite` the Luanti server has no channel credential of its own: the check gives the world an
invite and the stand-in player types it into `/cross` (the bridge's own credential and the code
reach the server's environment alone, and nothing records either). A headless Luanti server's check
mod then walks a stand-in player into the gate with torches through the same handlers a person's
actions reach, while the check acts as the world's owner from the mod's recording: it sends the
character home after it has lived in the world for `--lives-s` seconds (20 by default) unless the
world's minds lead it home first, and closes the gate once its player has left the game with the
character away again. Where the door publishes its home route (`POST /door/channel/home`, read from
its `/openapi.json`), the stand-in player also sends its character once more and calls it home with
`/comehome`. Whatever the world gave the character must come home into the player's inventory with
the torch, and the character arrives in the player's own look where the world can show it, else in
the free look with the player told why. It then reads the world's own records: the gate posted no
answer, each ask about the character was settled by the world, no line said where the character was
reached the player's chat, a mind the grant named decided for the character at least once (counted
from the world's events: asking it is not enough, since a minute may refuse its answer), and the
society replays with no game running. Each run's folder (ignored) holds the server's log, the mod's recording of every exchange
and a summary with no credential in it. `--mapping NAME` crosses with another published mapping
version than the newest, to show a deployment pinned to it still works. With `--against fake` the same crossing runs against the
stand-in door instead, with no stack, where the character is given a sword (with a line said to it,
and one it says back) and leaves on its own, and is called home with `/comehome` on a later visit.

`--api URL --token-file FILE --record FILE` joins a stack the check did not start, where a scene
was built for a take: it starts and stops no stack and builds nothing. That stack is started with
the bridge declared (`launch.py up ... --society-of-things --door-bridges OUT`, where `OUT` is
written by `tools/cross_once.py declare OUT`), and the scene is built there by
`scripts/demo/build_scene.py --record FILE` (with `--minds` where its beings get their models). The
check crosses into the world that record names: the scene is read from the catalog at the record's
digest (or from `--scene` for a scene the catalog does not ship), the society the builder started is
read back (or one is started where the record names none), a paused society is played at
`--minutes-speed` and a playing one keeps its speed. The world owner's token is read once from the
file and stays in the check's process; the grant the check issued is closed when it ends. With
`--play NAME` a person plays the crossing instead of the check mod.

## Security notes

- Only the operator's own server, bound to the address it is given; Luanti's sandbox stays on.
- Everything from the world is text: cleaned and bounded before it is shown; never run, never
  turned into a node, an item or a path. A departing item is delivered only if the mapping lists it
  as travelling out.
- A channel credential an invite opened is kept in the mod's own storage, a file in the world
  folder; whoever hosts a server for other people should treat that folder as secret.
