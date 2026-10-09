# Licence notes for the 0 A.D. gate

The adapter in this folder (its Python package, its mapping file and its declared reads) is
Exulanica's own work under the repository's Apache-2.0 licence. It speaks the game's interface with
its own client: it imports no code of the game's, not even the game's own Python client.

It runs beside, and is never shipped with:

| Work | Licence | How the adapter uses it |
| --- | --- | --- |
| 0 A.D. 0.28.0 "Boiorix" for macOS, by Wildfire Games | Code GPL-2.0-or-later; art and audio CC BY-SA 3.0, with attribution to Wildfire Games (the game's `LICENSE.txt`) | Run unmodified on the operator's machine with its built-in `--rl-interface`; the adapter posts to that interface's routes and names the game's unit templates as data |

Nothing of the game is committed: no code, texture, model, sound, map or archive. The operator
downloads it into a folder of their own, outside every repository, after checking its SHA-256
against the one the release publishes.

A soldier arrives in `blocky-hoplite`, a CC0 look of this world's drawn after a hoplite (the
mapping's first look; `blocky-traveller`, its second, serves a library that does not ship the
hoplite); the game's own art, which asks for share-alike, stays in the game, and the crossing's
manifest says so. No picture is read from the game.
