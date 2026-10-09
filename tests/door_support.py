"""What the door's tests share: a declared bridge, its credential and a mapping it may present.

The bridge here is invented for the tests and names no game: the product's source holds no game's
name, and its tests keep the same rule. Its mapping is a small, complete document of the profile,
and the bridge directory pins exactly its digest.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.door.bridges import BridgeDirectory, load_bridge_directory
from exulanica.door.credentials import credential_sha256
from exulanica.door.grants import visitors_society

#: The test bridge's own deployment credential, as its server would hold it.
BRIDGE_CREDENTIAL: Final = "test-bridge-credential-that-is-long-enough-0001"
#: A second admitted bridge, for refusals that turn on which bridge asks.
OTHER_CREDENTIAL: Final = "other-bridge-credential-that-is-long-enough-002"
ADAPTER_VERSION: Final = "0.1.0"
#: A second admitted version, for a bridge that says hello again with a newer adapter.
NEWER_ADAPTER_VERSION: Final = "0.2.0"

#: The thing library's shipped CC0 look a visitor of the test game arrives in.
BLOCKY_TRAVELLER_SHA256: Final = "45d65686f899ae246d0c01e1a679213e67bb7935a157f26ec304c7dada339e3d"

MAPPING: Final[dict[str, Any]] = {
    "profile": "exulanica.bridge-mapping/v1",
    "key": "test-game-content",
    "version": 1,
    "game": {"label": "A test game"},
    "visitors": [
        {
            "game_type": "player",
            "kind": {"key": "visitor", "version": 1},
            "label": "traveller from the test game",
            "words": "You, as a traveller",
            "outcome": "approximated",
            "reason_words": "a player becomes a traveller of this world, in this world's own look",
            "looks": [
                {
                    "look_key": "otherwise",
                    "look": "sha256:" + BLOCKY_TRAVELLER_SHA256,
                    "licence": {"spdx": "CC0-1.0"},
                }
            ],
        }
    ],
    "items": [
        {
            "game_item": "test:sword",
            "kind": {"key": "sword", "version": 1},
            "ways": "both",
            "words": "A sword, which arrives as a sword",
            "outcome": "exact",
        },
        {
            "game_item": "test:torch",
            "kind": {"key": "lantern", "version": 1},
            "ways": "both",
            "words": "A torch, which arrives as a lantern",
            "outcome": "approximated",
            "reason_words": "this world has no torch; a lantern is the nearest thing giving light",
        },
    ],
    "actions": [
        {
            "game_action": "chat",
            "ability": "say",
            "words": "Chat, which is said",
            "outcome": "exact",
        },
        {
            "game_action": "menu choice",
            "ability": "any offered",
            "words": "A choice from the menu, which is the option chosen",
            "outcome": "exact",
        },
    ],
    "never_crosses": [
        {
            "field": "player name",
            "words": "Your player name",
            "reason_words": "a person's name never crosses",
        },
        {
            "field": "health",
            "words": "Your health",
            "reason_words": "this world has no health",
        },
    ],
}
#: The game fields the test adapter declares it reads, each accounted for by the mapping.
READS: Final = ["player", "test:sword", "test:torch", "chat", "player name", "health"]


def mapping_v2(version: int = 1) -> dict[str, Any]:
    """The test mapping as ``exulanica.bridge-mapping/v2``: each look by the thing library's key,
    version and digest instead of its digest alone."""
    document = mapping(version)
    document["profile"] = "exulanica.bridge-mapping/v2"
    for visitor in document["visitors"]:
        for look in visitor["looks"]:
            look["look"] = {
                "look": "blocky-traveller",
                "version": 1,
                "sha256": look["look"].removeprefix("sha256:"),
            }
    return document


def mapping(version: int = 1) -> dict[str, Any]:
    """The test mapping; ``version`` 2 is a second one the test bridge also pins, and any other
    version one it does not."""
    document = copy.deepcopy(MAPPING)
    document["version"] = version
    return document


def mapping_sha256(document: dict[str, Any] | None = None) -> str:
    return sha256_of_canonical(MAPPING if document is None else document).hex()


def bridges_setting(
    *,
    listed: bool = True,
    workspaces: list[str] | None = None,
    owner_workspaces: list[str] | None = None,
    **figures: int,
) -> str:
    """``EXULANICA_DOOR_BRIDGES`` for the test bridge (a server), another server bridge, and, when
    ``owner_workspaces`` is given, a bridge each owner runs (``owned-bridge``), offered to them.
    ``figures`` are the test bridge's own hold_seconds and deadline_ms."""
    entry: dict[str, Any] = {
        "bridge": "test-bridge",
        "label": "A test bridge",
        "game": "A test game",
        "run_by": "server",
        "ai": False,
        "credential_sha256": credential_sha256(BRIDGE_CREDENTIAL),
        "mapping_sha256": [mapping_sha256(), mapping_sha256(mapping(2))],
        "adapter_versions": [ADAPTER_VERSION, NEWER_ADAPTER_VERSION],
        "listed": listed,
        **figures,
    }
    if workspaces is not None:
        entry["workspaces"] = workspaces
    other = {
        "bridge": "other-bridge",
        "label": "Another bridge",
        "game": "Another test game",
        "run_by": "server",
        "ai": False,
        "credential_sha256": credential_sha256(OTHER_CREDENTIAL),
        "mapping_sha256": [mapping_sha256()],
        "adapter_versions": [ADAPTER_VERSION],
        "listed": True,
    }
    declared = [entry, other]
    if owner_workspaces is not None:
        declared.append(
            {
                "bridge": "owned-bridge",
                "label": "A program its owner runs",
                "game": "An agent",
                "run_by": "owner",
                "ai": True,
                "mapping_sha256": [mapping_sha256()],
                "adapter_versions": [ADAPTER_VERSION],
                "listed": False,
                "workspaces": owner_workspaces,
            }
        )
    return json.dumps(declared)


def bridges(**kwargs: Any) -> BridgeDirectory:
    return load_bridge_directory({"EXULANICA_DOOR_BRIDGES": bridges_setting(**kwargs)})


def open_to_visitors(client: Any, world: dict[str, Any]) -> None:
    """Make a saved world's version hold a society of things, where a grant's visitors arrive and
    which issuing a grant for them asks for (``world_not_open_to_visitors``), unless the version
    holds a society already: a well to go to (a society needs a reachable target), then the
    society."""
    # A PostgreSQL test's own helpers, imported here so the tests that need no database never load
    # them.
    from test_society_things_postgres import _make_society, _place

    binding = world["binding"]
    held = (
        world["connection"]
        .execute(
            "select 1 from world_society where workspace_id = %s and world_id = %s "
            "and version_id = %s",
            (world["workspace"], binding.world_id, binding.version_id),
        )
        .fetchone()
    )
    if held is None:
        _place(client, world, "well", "well", 2, -4_000, 2_000)
        _make_society(client, world)
    elif (
        visitors_society(
            world["connection"], world["workspace"], binding.world_id, str(binding.version_id)
        )
        is None
    ):
        raise AssertionError(
            "this version already holds a society that takes no visitors (one of people, "
            "exulanica-society/v2): open it to visitors before its people are made, or use "
            "another version"
        )
