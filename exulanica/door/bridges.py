"""The bridges a deployment admits, declared once in its configuration.

A bridge is an outside program the deployment lets through the door: a game's adapter, run by
whoever runs that game's server. Bridges are declared, not registered through a route, the way a
deployment's models are declared in its manifest and the API's tokens in ``EXULANICA_API_TOKENS``:
admitting a program that will act in people's worlds is the deployment's decision, and a route that
registered one would be a surface for registering anything.

``EXULANICA_DOOR_BRIDGES`` holds a JSON array, one object per bridge:

``bridge``
    The bridge's key, as every grant, request and receipt names it: lowercase, one to 32 letters,
    digits, hyphens or underscores, beginning with a letter (the decider contract's rule,
    ``exulanica.world.deciders.BRIDGE``).
``label`` and ``game``
    What an owner reads when choosing it, and the game it connects, as words. They are data and
    never code: the product holds no game's name.
``run_by``
    Who runs the program. ``server``: a game server other people join, run by whoever runs that
    game's server; players open grants with invites the server redeems with its own credential. A
    world's owner is given a channel credential directly only for an unlisted server bridge that
    names the owner's workspace, since a listed server serves strangers. ``owner``: a program the
    world's owner runs on their own machine, such as an agent or a single-player game; it has no
    bridge credential and takes no invites, and any owner it is offered to may give it a channel
    credential for their own grant. Views say which, so a card can say a program is run by the
    world's owner rather than by a shared server.
``ai``
    Whether the program's choices are an artificial intelligence's, true or false and always
    stated, so a deployment cannot forget it: a card marks the things and lines of every grant of an
    AI bridge as AI's, and a game a person plays is not.
``credential_sha256``
    For a server bridge, the SHA-256 of the bridge's own credential, which it presents only to
    redeem an invite. The deployment holds the digest and never the secret. An owner bridge states
    none.
``hold_seconds`` and ``deadline_ms``
    Optional: how long its polls are held (1 to 25 seconds, 15 unless stated) and how long the
    decision host waits for its answer to one ask (1 ms to the role contract's
    ``decision_deadline_ms``, 3,000 unless stated). A game's scripts and an agent that takes a model
    call to choose need different figures, and the figures are data, not code.
``mapping_sha256``
    The digests of the mapping files the bridge may present, one to eight. A bridge whose adapter
    presents any other mapping is refused, so what crosses cannot change without a change here.
``adapter_versions``
    The adapter versions admitted, as the adapter states them.
``listed`` and ``workspaces``
    A listed bridge is offered to every workspace; an unlisted one only to the workspaces named.

A missing or empty setting admits no bridge, and the door then offers nothing: unlike the API's
tokens, a deployment with no bridges is an ordinary deployment. A malformed setting is refused at
load, by name, before the application serves anything.

A bridge credential is matched in constant time against every declared digest, as
:meth:`exulanica.api.authorisation.TokenDirectory.grant_for` matches a bearer token, so neither the
number of bridges nor which one matched is observable from how long the match took.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from exulanica.door.protocol import (
    DEADLINE_MS_DEFAULT,
    HOLD_SECONDS_DEFAULT,
    HOLD_SECONDS_MAXIMUM,
)
from exulanica.env import env_get, env_name
from exulanica.errors import ExulanicaError
from exulanica.world.deciders import ADAPTER_VERSION, BRIDGE
from exulanica.world.society_decision_contract import decision_contract

__all__ = [
    "DOOR_BRIDGES_ENV",
    "RUN_BY",
    "Bridge",
    "BridgeDirectory",
    "BridgeNotAccepted",
    "BridgeSettingRefused",
    "load_bridge_directory",
]

DOOR_BRIDGES_ENV: Final = env_name("DOOR_BRIDGES")

_DIGEST: Final = re.compile(r"^[0-9a-f]{64}$")
_WORDS: Final = re.compile(r"^[^\x00-\x1f\x7f]{1,80}$")
#: Who runs a bridge's program: a shared game server, or the world's owner on their own machine.
RUN_BY: Final = ("server", "owner")
_FIELDS: Final = frozenset(
    {
        "bridge",
        "label",
        "game",
        "run_by",
        "ai",
        "credential_sha256",
        "mapping_sha256",
        "adapter_versions",
        "listed",
        "workspaces",
        "hold_seconds",
        "deadline_ms",
    }
)
#: Every field but those only some bridges state: ``workspaces`` for an unlisted bridge,
#: ``credential_sha256`` for a server bridge, and the two optional figures.
_REQUIRED: Final = _FIELDS - {"workspaces", "credential_sha256", "hold_seconds", "deadline_ms"}
_MAPPINGS_MAXIMUM: Final = 8
_VERSIONS_MAXIMUM: Final = 16
_BRIDGES_MAXIMUM: Final = 64


class BridgeSettingRefused(ExulanicaError):
    """``EXULANICA_DOOR_BRIDGES`` is malformed; the message names what, and never a secret."""


class BridgeNotAccepted(ExulanicaError):
    """A presented bridge credential matches no declared bridge.

    One error for none, unknown and malformed, as for bearer tokens: telling them apart would tell
    a caller which of its guesses came closer.
    """


@dataclass(frozen=True, slots=True)
class Bridge:
    """One admitted bridge, as the deployment declares it."""

    key: str
    label: str
    game: str
    run_by: str
    ai: bool
    credential_sha256: str | None
    mapping_sha256: frozenset[str]
    adapter_versions: frozenset[str]
    listed: bool
    workspaces: frozenset[uuid.UUID]
    hold_seconds: int = HOLD_SECONDS_DEFAULT
    deadline_ms: int = DEADLINE_MS_DEFAULT

    def offered_to(self, workspace_id: uuid.UUID) -> bool:
        """Whether an owner of ``workspace_id`` may grant this bridge anything."""
        return self.listed or workspace_id in self.workspaces

    def takes_invites(self) -> bool:
        """Whether its grants open by invites its own credential redeems: a server's do."""
        return self.run_by == "server"

    def direct_credentials_for(self, workspace_id: uuid.UUID) -> bool:
        """Whether an owner of ``workspace_id`` may be given a channel credential directly: for a
        program the owner runs, wherever it is offered; for a server, only one that is unlisted and
        names the workspace, because a listed server serves people who are not that owner."""
        if self.run_by == "owner":
            return self.offered_to(workspace_id)
        return not self.listed and workspace_id in self.workspaces


@dataclass(frozen=True, slots=True)
class BridgeDirectory:
    """Every bridge the deployment admits, by key."""

    bridges: Mapping[str, Bridge] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.bridges)

    def get(self, key: str) -> Bridge | None:
        return self.bridges.get(key)

    def offered_to(self, workspace_id: uuid.UUID) -> tuple[Bridge, ...]:
        """The bridges an owner of ``workspace_id`` may grant, in key order."""
        return tuple(
            bridge
            for _key, bridge in sorted(self.bridges.items())
            if bridge.offered_to(workspace_id)
        )

    def for_credential(self, presented: str | None) -> Bridge:
        """The bridge whose credential was presented, matched in constant time, or refuse."""
        if not presented:
            raise BridgeNotAccepted("no bridge credential was presented")
        digest = hashlib.sha256(presented.encode("utf-8")).hexdigest()
        found: Bridge | None = None
        for bridge in self.bridges.values():
            if bridge.credential_sha256 is not None and secrets.compare_digest(
                bridge.credential_sha256, digest
            ):
                found = bridge
        if found is None:
            raise BridgeNotAccepted("the presented bridge credential is not declared")
        return found


def _strings(value: Any, *, where: str, pattern: re.Pattern[str], maximum: int) -> frozenset[str]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= maximum
        or not all(isinstance(item, str) and pattern.fullmatch(item) for item in value)
        or len(set(value)) != len(value)
    ):
        raise BridgeSettingRefused(
            f"{DOOR_BRIDGES_ENV}: {where} must list 1 to {maximum} distinct values of the "
            "stated form"
        )
    return frozenset(value)


def _bridge(entry: Any, position: int) -> Bridge:
    where = f"bridge {position}"
    if not isinstance(entry, dict) or not _REQUIRED <= set(entry) <= _FIELDS:
        raise BridgeSettingRefused(
            f"{DOOR_BRIDGES_ENV}: {where} must state exactly the bridge fields "
            f"({', '.join(sorted(_FIELDS))}; workspaces only when needed)"
        )
    key = entry["bridge"]
    if not isinstance(key, str) or not BRIDGE.fullmatch(key):
        raise BridgeSettingRefused(f"{DOOR_BRIDGES_ENV}: {where} has no valid bridge key")
    where = f"bridge {key}"
    for name in ("label", "game"):
        if not isinstance(entry[name], str) or not _WORDS.match(entry[name].strip() or "\x00"):
            raise BridgeSettingRefused(
                f"{DOOR_BRIDGES_ENV}: {where} needs a {name} of 1 to 80 characters"
            )
    run_by = entry["run_by"]
    if run_by not in RUN_BY:
        raise BridgeSettingRefused(
            f"{DOOR_BRIDGES_ENV}: {where} says who runs it, run_by {' or '.join(RUN_BY)}"
        )
    credential = entry.get("credential_sha256")
    if run_by == "owner" and credential is not None:
        raise BridgeSettingRefused(
            f"{DOOR_BRIDGES_ENV}: {where} is run by each world's owner and has no bridge credential"
        )
    if run_by == "server" and (not isinstance(credential, str) or not _DIGEST.match(credential)):
        raise BridgeSettingRefused(
            f"{DOOR_BRIDGES_ENV}: {where} states its credential as a SHA-256 hex digest, never the "
            "credential itself"
        )
    hold_seconds = entry.get("hold_seconds", HOLD_SECONDS_DEFAULT)
    if type(hold_seconds) is not int or not 1 <= hold_seconds <= HOLD_SECONDS_MAXIMUM:
        raise BridgeSettingRefused(
            f"{DOOR_BRIDGES_ENV}: {where} holds a poll 1 to {HOLD_SECONDS_MAXIMUM} whole seconds"
        )
    ceiling = decision_contract().value("decision_deadline_ms")
    deadline_ms = entry.get("deadline_ms", DEADLINE_MS_DEFAULT)
    if type(deadline_ms) is not int or not 1 <= deadline_ms <= ceiling:
        raise BridgeSettingRefused(
            f"{DOOR_BRIDGES_ENV}: {where} is given 1 to {ceiling} ms to answer, the decision "
            "contract's own bound"
        )
    if not isinstance(entry["ai"], bool):
        raise BridgeSettingRefused(
            f"{DOOR_BRIDGES_ENV}: {where} says whether its program is an AI, ai true or false"
        )
    if not isinstance(entry["listed"], bool):
        raise BridgeSettingRefused(f"{DOOR_BRIDGES_ENV}: {where} says listed true or false")
    try:
        workspaces = frozenset(uuid.UUID(value) for value in entry.get("workspaces", []))
    except (TypeError, ValueError, AttributeError) as exc:
        raise BridgeSettingRefused(
            f"{DOOR_BRIDGES_ENV}: {where} names workspaces as uuids"
        ) from exc
    if not entry["listed"] and not workspaces:
        raise BridgeSettingRefused(
            f"{DOOR_BRIDGES_ENV}: {where} is unlisted and names no workspace, so nobody could "
            "grant it"
        )
    return Bridge(
        key=key,
        label=entry["label"].strip(),
        game=entry["game"].strip(),
        run_by=run_by,
        ai=entry["ai"],
        credential_sha256=credential,
        mapping_sha256=_strings(
            entry["mapping_sha256"],
            where=f"{where}'s mapping_sha256",
            pattern=_DIGEST,
            maximum=_MAPPINGS_MAXIMUM,
        ),
        adapter_versions=_strings(
            entry["adapter_versions"],
            where=f"{where}'s adapter_versions",
            pattern=ADAPTER_VERSION,
            maximum=_VERSIONS_MAXIMUM,
        ),
        listed=entry["listed"],
        workspaces=workspaces,
        hold_seconds=hold_seconds,
        deadline_ms=deadline_ms,
    )


def load_bridge_directory(environ: Mapping[str, str] | None = None) -> BridgeDirectory:
    """The bridges ``EXULANICA_DOOR_BRIDGES`` declares: none when it is unset, or refuse."""
    raw = env_get("DOOR_BRIDGES", environ)
    if raw is None:
        return BridgeDirectory()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BridgeSettingRefused(f"{DOOR_BRIDGES_ENV} is not valid JSON: {exc.msg}") from exc
    if not isinstance(parsed, list) or len(parsed) > _BRIDGES_MAXIMUM:
        raise BridgeSettingRefused(
            f"{DOOR_BRIDGES_ENV} must be a JSON array of at most {_BRIDGES_MAXIMUM} bridges"
        )
    bridges: dict[str, Bridge] = {}
    credentials: set[str] = set()
    for position, entry in enumerate(parsed, start=1):
        bridge = _bridge(entry, position)
        if bridge.key in bridges:
            raise BridgeSettingRefused(f"{DOOR_BRIDGES_ENV}: bridge {bridge.key} is declared twice")
        if bridge.credential_sha256 is not None:
            if bridge.credential_sha256 in credentials:
                raise BridgeSettingRefused(
                    f"{DOOR_BRIDGES_ENV}: bridge {bridge.key} shares a credential with another "
                    "bridge"
                )
            credentials.add(bridge.credential_sha256)
        bridges[bridge.key] = bridge
    return BridgeDirectory(bridges=bridges)
