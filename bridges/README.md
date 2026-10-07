# Bridges

Adapters that connect outside programs, such as games and AI agents, to Exulanica worlds through
the door ([door contract](../docs/door-contract.md)). Nothing here is part of the product: the
product never imports this folder, it is not packaged in the product's wheel, and the product's
source names no game (`tests/test_door_names_no_game.py`).

- `door_client/`: a reference client for the door's channel, standard library only. Adapters
  written in Python use it; adapters in other languages follow it. It speaks HTTPS, or plain HTTP to
  this machine for development, and follows no redirect, so a credential is sent nowhere else.
- One folder per program, added with its adapter: the adapter's code, its mapping file
  (`exulanica.bridge-mapping/v1`, every entry with its plain `words`, and `reason_words` where it is
  not exact) and its licence notes.

How an adapter is admitted is the deployment's: each bridge states who runs it (`run_by` `server`
for a game server other people join, `owner` for a program a world's owner runs), whether its
choices are an AI's (`ai`), and optionally its own poll hold and answer deadline. A server's
adapter redeems the invites its players type and names who typed each with `requester`, a digest it
derives and never a name. A slot's acceptance stack admits bridges with
`scripts/acceptance/launch.py up --door-bridges FILE`.

Rules for this folder:

- Our code is Apache-2.0, as the rest of the repository.
- No game's code or media is committed here: no textures, models, sounds or archives from a game.
  An adapter that needs a game's picture builds what it needs from the operator's own installation,
  and what it builds stays outside the repository.
- Tests here, and the product's tests of the door, use recorded or written fixtures only: no test
  needs a game installed.
- Credentials are kept by the host that runs an adapter (its environment, a keychain), never in a
  file here, a log line or a message. Where an adapter keeps a channel credential in its game's own
  storage, that storage is the server operator's to protect; say so in the adapter's README.
