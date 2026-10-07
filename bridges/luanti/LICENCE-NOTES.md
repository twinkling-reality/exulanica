# Licence notes for the Luanti gate

The adapter in this folder (the mod, its mapping file, the check mod, the scripts and the
fixtures) is Exulanica's own work under the repository's Apache-2.0 licence. The gate's two
pictures are drawn by the mod's code at load (`core.encode_png`), so no image file is kept.

It runs on, and is never shipped with:

| Work | Licence | How the adapter uses it |
| --- | --- | --- |
| Luanti 5.17.0, the engine | Code LGPL-2.1-or-later; the engine's media CC BY-SA 3.0, with exceptions its `LICENSE.txt` lists | Run unmodified as the server and the player's client; the mod calls its documented Lua API |
| Minetest Game, ContentDB release 38214 | Code LGPL-2.1-or-later; media CC BY-SA 3.0 | Run unmodified as the game the demo server plays; the mapping file names its item identifiers (`default:sword_steel` and others) as data |

Nothing of either is committed: no code, texture, model, sound or archive. Both are unpacked from
the operator's allocated archives into an ignored folder by `run/install.sh`, which checks each
archive's SHA-256 first.

A Luanti player wearing Minetest Game's own picture (`mods/player_api/models/character.png`, by
Jordach, CC BY-SA 3.0) arrives in their own look. `tools/build_look.py` builds it at a deployment
from the operator's own copy, refusing any other picture or licence file by SHA-256; the look is an
adaptation under CC BY-SA 3.0, credited wherever it is shown, never committed, never part of a
shipped image and never mixed into an Apache-2.0 or CC0 file ([licence matrix](../../docs/license-matrix.md),
section 14). A player in any other picture arrives in a CC0 look, and the crossing's manifest says
why.
