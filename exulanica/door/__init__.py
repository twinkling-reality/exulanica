"""The door: how an outside program decides for things in a world, under its owner's grant.

An outside program, such as a game's adapter, is a **bridge** the deployment admits
(:mod:`exulanica.door.bridges`). A world's owner issues a **grant** naming one bridge, one world,
how many visitors it may bring in and which of the world's own things it may decide for. The bridge
dials out to the server and, over a long-poll channel, receives the same options a model is shown
and answers with one of them; the decision host turns each answer into a receipt, so a world with a
visitor replays with no bridge running (``docs/door-contract.md``).

Nothing in this package knows any particular game. A game is an adapter outside the product plus a
mapping file, which is data (:mod:`exulanica.door.mapping`). The import contracts in
``pyproject.toml`` keep it that way in both directions: nothing in the product but the HTTP layer
imports this package, and ``tests/test_door_names_no_game.py`` refuses a game's name anywhere in the
product's source.
"""
