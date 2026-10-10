"""What a society of things reads of a kind: the one place that answers it.

Everybody in a society of things names its kind by a reference its state records. A shipped kind is
named by key, version and digest and read from the shipped library, as it always was. A kind its
workspace keeps (a creature drafted from a person's words) is named by its document's digest alone,
``{source: "workspace", sha256}``, and read from the run forms the society's own records carry
(:mod:`exulanica.things.run_forms`): its input states them once a kind (``kinds``), and its state
keeps those of the made kinds present. So a society never reads a workspace's store, replays from
its inputs alone, and holds no word a person wrote.

:func:`kind_here` answers either reference with something that reads the same way: ``document``
with the kind's label, summary, class, abilities, offers, deciders and body. A made reference whose
run form the records at hand no longer state (a line heard from a creature since erased) answers a
kind that can do nothing and is named by the catalog's noun alone, so an old line still reads.

Pure: no connection.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from exulanica.things.catalogs import Socket, thing_catalogs
from exulanica.things.kinds import ThingKind
from exulanica.things.run_forms import (
    RUN_FORM_PROFILE,
    WORKSPACE_SOURCE,
    RunFormRefused,
    read_run_form,
)
from exulanica.world.placed_things import (
    PLACED_THING_ID_PATTERN,
    ThingKindReference,
    shipped_kind,
)

__all__ = [
    "KINDS_BOUND",
    "KINDS_FIELD",
    "THINGS_GONE_FIELD",
    "MadeKind",
    "is_made",
    "kind_here",
    "kinds_of",
    "made_reference",
    "reference_of",
    "reference_shape",
    "sockets_of",
    "validate_kinds",
    "validate_things_gone",
]

#: Where an input and a state keep the run forms of their made kinds, by the kind's digest.
KINDS_FIELD: Final = "kinds"
#: Where an input names the placed things it leaves out because the kind each is of, one its
#: workspace kept, is gone: a being that was one of them leaves because its kind was erased. By
#: placed id, since a thing placed before an erasure stays gone though the same creature is kept
#: again and another thing of that kind lives.
THINGS_GONE_FIELD: Final = "things_gone"
#: The most made kinds one input or state carries: the most things an input states.
KINDS_BOUND: Final = 4096
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_PLACED_ID: Final = re.compile(PLACED_THING_ID_PATTERN)
#: What a made kind no record at hand states is named: the body names catalogs' noun.
_GONE_LABEL: Final = "creature"
_MADE_FIELDS: Final = frozenset({"source", "sha256"})
_SHIPPED_FIELDS: Final = frozenset({"kind", "version", "sha256"})


@dataclass(frozen=True, slots=True)
class MadeKind:
    """A kind its workspace keeps, as a society reads it: its run form, or what stands for one
    the records at hand no longer state."""

    document: Mapping[str, Any]
    sha256: str
    #: Whether the records at hand still state its run form.
    stated: bool = True

    @property
    def klass(self) -> str:
        return str(self.document["class"])

    @property
    def label(self) -> str:
        return str(self.document["label"])


def made_reference(sha256: str) -> dict[str, str]:
    """A made kind's reference, by its document's digest alone."""
    return {"sha256": sha256, "source": WORKSPACE_SOURCE}


def is_made(reference: object) -> bool:
    """Whether ``reference`` names a kind its workspace keeps rather than a shipped one."""
    return isinstance(reference, Mapping) and reference.get("source") == WORKSPACE_SOURCE


def reference_shape(value: object) -> bool:
    """Whether ``value`` is a kind's reference of either shape: a shipped kind by key, version
    and digest, or a workspace's own by its digest alone."""
    if not isinstance(value, Mapping) or not isinstance(value.get("sha256"), str):
        return False
    if _HEX64.fullmatch(value["sha256"]) is None:
        return False
    if set(value) == _MADE_FIELDS:
        return value["source"] == WORKSPACE_SOURCE
    return (
        set(value) == _SHIPPED_FIELDS
        and isinstance(value["kind"], str)
        and type(value["version"]) is int
    )


def reference_of(reference: Mapping[str, Any]) -> dict[str, Any]:
    """``reference`` as a record keeps it: its own fields, of whichever shape it is."""
    if is_made(reference):
        return made_reference(str(reference["sha256"]))
    return {
        "kind": reference["kind"],
        "version": reference["version"],
        "sha256": reference["sha256"],
    }


def kinds_of(record: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """The run forms a state or an input carries, by digest: none where it states none."""
    if record is None:
        return MappingProxyType({})
    found = record.get(KINDS_FIELD)
    return found if isinstance(found, Mapping) else MappingProxyType({})


def _gone(sha256: str) -> MadeKind:
    return MadeKind(
        MappingProxyType(
            {
                "profile": RUN_FORM_PROFILE,
                "reference": made_reference(sha256),
                "class": "being",
                "label": _GONE_LABEL,
                "summary": "",
                "body": MappingProxyType({"sockets": ()}),
                "moves": (),
                "abilities": (),
                "offers": (),
                "routine": MappingProxyType({"weights": {}, "follow_holders_of": ()}),
                "deciders": MappingProxyType({"default": "routine", "allowed": ("routine",)}),
            }
        ),
        sha256,
        stated=False,
    )


def kind_here(record: Mapping[str, Any] | None, reference: Mapping[str, Any]) -> Any:
    """The kind ``reference`` names, as the society whose ``record`` (a state or an input) is at
    hand reads it: a shipped kind from the shipped library, at exactly its digest
    (:class:`~exulanica.world.errors.InvalidThingPlacement` otherwise, as before); a made kind
    from the run forms the record carries, or what stands for one it no longer states."""
    if is_made(reference):
        sha256 = str(reference["sha256"])
        form = kinds_of(record).get(sha256)
        return _gone(sha256) if form is None else MadeKind(form, sha256)
    return shipped_kind(ThingKindReference(**reference))


def sockets_of(kind: Any) -> tuple[Socket, ...]:
    """The sockets a being of ``kind`` holds things in, in its body plan's order: a shipped
    kind's from the plan catalog, a made kind's from its run form."""
    if isinstance(kind, MadeKind):
        return tuple(
            Socket(
                key=str(socket["key"]),
                bone=None,
                holds=int(socket["holds"]),
                length_mm_maximum=int(socket["length_mm_maximum"]),
                grip_section_mm_maximum=socket["grip_section_mm_maximum"],
            )
            for socket in kind.document["body"]["sockets"]
        )
    assert isinstance(kind, ThingKind)
    plan = thing_catalogs().plans.get(str(kind.document["body"]["plan"]))
    return () if plan is None else plan.sockets


def validate_kinds(record: Mapping[str, Any], named: set[str]) -> None:
    """The run forms a state or an input carries, held to their shape: stated only where a made
    kind is named, exactly the kinds ``named`` (digests), in digest order, each a run form that
    reads and names itself by the digest it is kept under."""
    if KINDS_FIELD not in record:
        if named:
            raise ValueError("a made kind is named whose run form is not stated")
        return
    kinds = record[KINDS_FIELD]
    if not isinstance(kinds, dict) or not kinds or len(kinds) > KINDS_BOUND:
        raise ValueError("made kinds are stated only where one is named, within the bound")
    if list(kinds) != sorted(kinds) or set(kinds) != named:
        raise ValueError("the run forms stated are exactly the made kinds named, in digest order")
    for sha256, form in kinds.items():
        try:
            read_run_form(form)
        except RunFormRefused as exc:
            raise ValueError(f"a made kind's run form does not read: {exc}") from exc
        if form["reference"]["sha256"] != sha256:
            raise ValueError("a run form is kept under the digest it names")


def validate_things_gone(record: Mapping[str, Any], listed: set[str]) -> None:
    """The placed things an input says are gone, held to their shape: stated only where there is
    one, placed ids in order, each once, none of them a thing the input lists (``listed``)."""
    if THINGS_GONE_FIELD not in record:
        return
    gone = record[THINGS_GONE_FIELD]
    if (
        not isinstance(gone, list)
        or not gone
        or len(gone) > KINDS_BOUND
        or not all(isinstance(one, str) and _PLACED_ID.fullmatch(one) for one in gone)
        or gone != sorted(set(gone))
        or set(gone) & listed
    ):
        raise ValueError("the things gone are placed ids in order, each once, none of them listed")
