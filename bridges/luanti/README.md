# The Luanti gate

A Luanti server mod, `exulanica_gate`, that puts a gate in a Luanti world. A player who walks into
the gate's light plays a part in an Exulanica world through the [door](../../docs/door-contract.md):
the world's options for that part appear as the player's menu, and the player's choices are its
choices at the next world minute. The world keeps every choice as a receipt, so it replays with no
game running.

The mod uses the engine's own API and nothing of any game, so one mod serves every Luanti game.
What a game's characters and items become in Exulanica is that game's mapping file
(`mod/exulanica_gate/mapping/`, profile `exulanica.bridge-mapping/v1`), which is data.

## What works today, and what does not yet

| Part | State |
| --- | --- |
| The channel: hello with the adapter's version, mapping and the game fields it reads; one held poll per grant; answers; refusals read from bodies | Works against the door's channel routes |
| Taking the part of a thing a grant names: the menu of offered options, held choices answered at the next ask, stepping back | Works; a scripted check plays it on a headless server (below) |
| A traveller crossing in as a thing of its own: arriving, chat both ways, items both ways, leaving | Built against the door's agreed crossing frames and checked against a stand-in door (`tools/fake_door.py`); it needs the door's crossing routes |
| A traveller in the game's own picture arriving in their own look | The look is built by `tools/build_look.py`; a world draws it once its thing store holds it, and until then the traveller arrives in the CC0 look |
| Invites (`/cross`, a code pasted into a masked form) | Written to the door's invite route; not yet run against it |

## Layout

| Path | What it is |
| --- | --- |
| `mod/exulanica_gate/` | The mod: `init.lua` wires settings and callbacks; `channel.lua` speaks to the door; `journey.lua` is one player's time through the gate; `choices.lua` answers asks from a player's held choices; `menu.lua` and `panel.lua` are what the player sees; `lines.lua` screens chat; `gate.lua` draws and places the gate; `store.lua`, `record.lua`, `json.lua` and `engine.lua` are plumbing |
| `mod/exulanica_gate/adapter.json` | The adapter's version and the game fields it reads (with every item its mapping lists) |
| `mod/exulanica_gate/mapping/` | One mapping file per Luanti game |
| `check/exulanica_gate_check/` | A test mod that plays a player on a headless server, and the table of line cases |
| `run/` | `install.sh` unpacks the engine and the game; `check.py` runs the scripted check, or with `--play NAME` serves a world for a person; `serve.sh` and `play.sh` run the demo server and a window joined to it |
| `tools/` | `build_look.py` builds a player's own look; `fake_door.py` is a stand-in door for the crossing check; `fixtures.py` turns a recorded run into a fixture |
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
slot, makes a world with people in it, grants the `luanti` bridge one of its people, and starts a
headless Luanti server whose check mod walks a stand-in player into the gate and plays the part
through the same handlers a person's actions reach. It then reads the world's own receipts and
replay. Each run's folder (ignored) holds the server's log, the mod's recording of every exchange
and a summary with no credential in it.

## Security notes

- Only the operator's own server, bound to the address it is given; Luanti's sandbox stays on.
- Everything from the world is text: cleaned, bounded, and escaped before it enters a form; never
  run, never turned into a node, an item or a path. A departing item is delivered only if the
  mapping lists it as travelling out.
- A channel credential an invite opened is kept in the mod's own storage, a file in the world
  folder; whoever hosts a server for other people should treat that folder as secret.
