"""Who decides for a subject, and what a request and a receipt record about an outside program.

A **decider** is what chooses a subject's next action: the world's own routine, an open model the
world's owner chose, the owner themselves through a direct request, or an outside program, such as
a game's bridge, deciding under a grant the owner issued. Its descriptor, ``exulanica.decider/v1``,
is a small closed document every choice of the second shape records under ``decider``:

*   ``{"kind": "routine"}``: the world's own rules decide;
*   ``{"kind": "model", "provider": ..., "model_id": ...}``: a model the manifest declares;
*   ``{"kind": "person"}``: the world's owner, through direct requests, which supersede any bound
    decider's answer in their minute and are never a binding of their own;
*   ``{"kind": "external", "bridge": ..., "grant_id": ...}``: an outside program, by the key of the
    bridge it reaches the world through and the grant its owner issued it. Which game, which
    adapter version and which mapping are the grant's and each receipt's, never the descriptor's.

A request records whoever it asked in its ``provider_config`` and a receipt whoever answered in its
``provider``. A model's shapes are :data:`~exulanica.world.role_decisions.PROVIDER_CONFIG` and
:data:`~exulanica.world.role_decisions.PROVIDER_RECORD`, unchanged and with no ``kind``, so every
stored request and receipt reads as it was written. An outside program's are this module's
:data:`EXTERNAL_CONFIG` and :data:`EXTERNAL_RECORD`, each naming its kind. An outside answer spends
nothing, so its record carries no cost; and it carries no free text from the program: a
correlation the program needs rides as :data:`SHA256` hex or not at all, so no name can.

Nothing here reads a database or asks anybody.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any, Final

__all__ = [
    "ADAPTER_VERSION",
    "BRIDGE",
    "DECIDER_PROFILE",
    "EXTERNAL_CONFIG",
    "EXTERNAL_REASONS",
    "EXTERNAL_RECORD",
    "KINDS",
    "OWNER_CHOOSES",
    "DeciderRefused",
    "arrived_from_outside",
    "check_external_config",
    "check_external_record",
    "decider",
    "is_external",
    "model_of",
    "of_model",
    "receipt_from_outside",
]

#: The descriptor's contract: a sub-document of a choice, with no profile key of its own.
DECIDER_PROFILE: Final = "exulanica.decider/v1"
#: Every kind of decider, in the order precedence names them from the weakest.
KINDS: Final = ("routine", "model", "person", "external")
#: The deciders an owner's choice binds a subject to through the choices route: a person decides
#: through direct requests, and an outside program only under a grant its route records.
OWNER_CHOOSES: Final = ("routine", "model")
#: A bridge's key: the lowercase name of the program's door, as the deployment declares it.
BRIDGE: Final = re.compile(r"[a-z][a-z0-9_-]{0,31}")
#: An adapter's version as its program states it: one to four whole numbers joined by dots, such
#: as ``0.1.0``. Numbers alone, so no name or other text can ride in it.
ADAPTER_VERSION: Final = re.compile(r"[0-9]{1,6}(\.[0-9]{1,6}){0,3}")
SHA256: Final = re.compile(r"[0-9a-f]{64}")
#: What a request records about the outside program it asked: which door, under which revision
#: of which grant, which mapping file, which contract and by when.
EXTERNAL_CONFIG: Final = frozenset(
    {"kind", "bridge", "grant_id", "grant_seq", "mapping_sha256", "contract", "deadline_ms"}
)
#: What a receipt records about an outside answer: the same grant and mapping, the adapter's
#: version, the digest of the answer it sent, how long it took, and an optional fixed-format
#: correlation token. No cost: an outside answer spends nothing.
EXTERNAL_RECORD: Final = frozenset(
    {
        "kind",
        "bridge",
        "adapter_version",
        "grant_id",
        "grant_seq",
        "mapping_sha256",
        "answer_sha256",
        "latency_ms",
        "source_ref_sha256",
    }
)
#: Why an outside program gave no usable answer, beside the reasons every role records: its door
#: had no live connection for the grant, it did not answer in time, or its grant was revoked or
#: had expired when the minute asked.
EXTERNAL_REASONS: Final = frozenset(
    {"decider_disconnected", "no_answer_in_time", "grant_revoked", "grant_expired"}
)
#: The longest an outside program may be given to answer, in milliseconds: the playback lease's 30
#: seconds, which no role's contract deadline may outlast either.
_DEADLINE_CEILING_MS: Final = 30_000
_LATENCY_CEILING_MS: Final = 3_600_000
_GRANT_SEQ_CEILING: Final = 1_000_000_000


class DeciderRefused(ValueError):
    """A descriptor or an outside record this code will not read, by the field at fault."""


def _whole(value: object, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _grant(value: object) -> bool:
    """A grant id as every record spells one: a UUID in its canonical lowercase text."""
    if type(value) is not str:
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _matches(pattern: re.Pattern[str], value: object) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def decider(value: object) -> dict[str, Any]:
    """The descriptor ``value`` states, exactly, as a new dict; anything else is refused."""
    if not isinstance(value, Mapping) or value.get("kind") not in KINDS:
        raise DeciderRefused("a decider names its kind: routine, model, person or external")
    kind = value["kind"]
    fields = {
        "routine": {"kind"},
        "person": {"kind"},
        "model": {"kind", "provider", "model_id"},
        "external": {"kind", "bridge", "grant_id"},
    }[kind]
    if set(value) != fields:
        raise DeciderRefused(f"a {kind} decider states exactly {sorted(fields)}")
    if kind == "model" and not (
        isinstance(value["provider"], str)
        and value["provider"]
        and isinstance(value["model_id"], str)
        and value["model_id"]
    ):
        raise DeciderRefused("a model decider names its provider and model id")
    if kind == "external" and not (_matches(BRIDGE, value["bridge"]) and _grant(value["grant_id"])):
        raise DeciderRefused("an external decider names its bridge by key and its grant by id")
    return {key: value[key] for key in sorted(fields)}


def of_model(model: Mapping[str, Any] | None) -> dict[str, Any]:
    """The descriptor of a first choice's ``model``: a model, or the routine for none."""
    if model is None:
        return {"kind": "routine"}
    return decider({"kind": "model", "provider": model["provider"], "model_id": model["model_id"]})


def model_of(described: Mapping[str, Any]) -> dict[str, str] | None:
    """The model a descriptor names, as a first choice's ``model`` states one; None for any other
    decider, which no model is asked for and which spends nothing."""
    if described["kind"] != "model":
        return None
    return {"provider": described["provider"], "model_id": described["model_id"]}


def is_external(record: object) -> bool:
    """Whether a request's ``provider_config`` or a receipt's ``provider`` names an outside
    program; a model's never names a kind."""
    return isinstance(record, Mapping) and record.get("kind") == "external"


def receipt_from_outside(receipt: Mapping[str, Any]) -> bool:
    """Whether a receipt answered a request of an outside program: its ``provider`` is an outside
    answer's record, or, with no answer recorded, it ended for a reason only an outside ask gives
    (:data:`EXTERNAL_REASONS`). What a minute's ``decision_applied`` event says decided."""
    provider = receipt.get("provider")
    if provider is not None:
        return is_external(provider)
    return receipt.get("reason") in EXTERNAL_REASONS


def _shared(record: Mapping[str, Any], where: str) -> None:
    """The fields an outside program's request and receipt both state, each in its one form."""
    if not (
        _matches(BRIDGE, record["bridge"])
        and _grant(record["grant_id"])
        and _whole(record["grant_seq"], 1, _GRANT_SEQ_CEILING)
        and _matches(SHA256, record["mapping_sha256"])
    ):
        raise DeciderRefused(f"{where} names its bridge, grant, grant revision and mapping file")


def check_external_config(config: object) -> None:
    """A request's record of the outside program it asked: exactly :data:`EXTERNAL_CONFIG`."""
    if not isinstance(config, Mapping) or set(config) != EXTERNAL_CONFIG:
        raise DeciderRefused(
            f"an outside program's request states exactly {sorted(EXTERNAL_CONFIG)}"
        )
    if config["kind"] != "external":
        raise DeciderRefused("an outside program's request names its kind, external")
    _shared(config, "an outside program's request")
    contract = config["contract"]
    if not isinstance(contract, Mapping) or set(contract) != {"catalog_versions", "sha256"}:
        raise DeciderRefused("an outside program's request names the contract it was asked under")
    if not _whole(config["deadline_ms"], 1, _DEADLINE_CEILING_MS):
        raise DeciderRefused(
            f"an outside program is given 1 to {_DEADLINE_CEILING_MS} ms to answer"
        )


def check_external_record(record: object) -> None:
    """A receipt's record of an outside answer: exactly :data:`EXTERNAL_RECORD`."""
    if not isinstance(record, Mapping) or set(record) != EXTERNAL_RECORD:
        raise DeciderRefused(f"an outside answer's record states exactly {sorted(EXTERNAL_RECORD)}")
    if record["kind"] != "external":
        raise DeciderRefused("an outside answer's record names its kind, external")
    _shared(record, "an outside answer's record")
    if not _matches(ADAPTER_VERSION, record["adapter_version"]):
        raise DeciderRefused(
            "an outside answer names its adapter's version, whole numbers joined by dots"
        )
    if not _matches(SHA256, record["answer_sha256"]):
        raise DeciderRefused("an outside answer's record names the digest of the answer sent")
    if not _whole(record["latency_ms"], 0, _LATENCY_CEILING_MS):
        raise DeciderRefused("an outside answer's record states how long it took, in milliseconds")
    token = record["source_ref_sha256"]
    if token is not None and not _matches(SHA256, token):
        raise DeciderRefused(
            "an outside answer carries no free data: its correlation token is a digest or none"
        )


def arrived_from_outside(state: Mapping[str, Any], subject_id: str) -> bool:
    """Whether ``subject_id`` came into this society from outside, as its state records: its own
    program decides for it, and no owner's choice or direct request may (``decided_from_outside``).
    An engine whose people carry no ``came_by`` holds nobody who did."""
    for person in state.get("inhabitants", ()):
        if person.get("id") == subject_id:
            return person.get("came_by") == "crossed"
    return False
