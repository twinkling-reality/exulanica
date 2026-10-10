"""One thing or being of a society of things as its card shows it: ``exulanica.thing-card/v1``.

The card is read, never stored: what the thing is (its kind, in the kind's own words), what it can
do here and what others can do with it (only what a module this society runs acts on), where it
is and what it holds, who decides for it, how it is drawn and what else it could be drawn as, the
lines it said lately, and the society's minute and state digest as the card was read. A look is
chosen beside a thing, never in it (ADR-0030), so changing one (:func:`choose_look`) writes only
the look table and answers the card again: the minute and digest it states are the proof that
nothing the thing does changed.
"""

from __future__ import annotations

import functools
import json
import uuid
from collections.abc import Container, Mapping, Sequence
from typing import Any, Final

import psycopg

from exulanica.abilities.registry import ability_module, recorded_modules, recorded_row
from exulanica.api.services import Services
from exulanica.models.manifest import load_manifest
from exulanica.things.catalogs import CATALOG_DIRECTORY, thing_catalogs
from exulanica.world.deciders import decided_from_outside, is_played
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.placed_things import ThingKindReference, shipped_kind
from exulanica.world.society_decision_contract import person_role
from exulanica.world.society_engines import society_engine
from exulanica.world.society_kinds import is_made, kind_here
from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository
from exulanica.world.society_planner import routine_withheld
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.society_things import kind_allows
from exulanica.world.thing_library import shipped_looks
from exulanica.world.thing_looks import (
    LookReference,
    ThingLookRefused,
    check_crossing_look,
    look_choices,
)
from exulanica.world.thing_store import ThingStore, admitted_look_by_digest

__all__ = ["LINES_SHOWN", "THING_CARD_PROFILE", "choose_look", "thing_card"]

THING_CARD_PROFILE: Final = "exulanica.thing-card/v1"
#: How many of the lines a being said lately its card shows, newest first.
LINES_SHOWN: Final = 8
#: The crossing module reads the offer a visitor arrives through as well as the one it leaves
#: through, though no ability targets it: arriving is the door's, not a decider's.
_ARRIVAL_OFFER: Final = ("arrive_through", "exulanica-ability/crossing/v1")


def thing_card(
    connection: psycopg.Connection,
    services: Services,
    society: SocietyRepository,
    *,
    workspace_id: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
    thing_id: uuid.UUID,
    reader: uuid.UUID | None = None,
) -> dict[str, Any]:
    """The card of the society thing or being ``thing_id`` of the version's society of things, or
    :class:`UnknownWorldResource` where the version's society is not one or holds no such thing.
    ``reader`` is who reads it, so a being a person plays says whether the reader is that person."""
    card, _held = _card(
        connection,
        services,
        society,
        workspace_id=workspace_id,
        world_id=world_id,
        version_id=version_id,
        thing_id=thing_id,
        reader=reader,
    )
    return card


def _card(
    connection: psycopg.Connection,
    services: Services,
    society: SocietyRepository,
    *,
    workspace_id: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
    thing_id: uuid.UUID,
    reader: uuid.UUID | None = None,
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    """The card, and the thing or being it was read from in the same snapshot."""
    snapshot, said, left_out = society.snapshot_and_lines(version_id, thing_id, limit=LINES_SHOWN)
    state = snapshot["state"]
    if society_engine(snapshot["profile"]).state_family != "things":
        raise UnknownWorldResource("this version's society holds no things")
    wanted = str(thing_id)
    person = next((p for p in state["inhabitants"] if p["id"] == wanted), None)
    thing = next((t for t in state["things"] if t["id"] == wanted), None)
    if person is None and thing is None:
        raise UnknownWorldResource("no such thing in this version's society")
    held = person if person is not None else thing
    assert held is not None
    if person is not None and is_made(person["kind"]):
        # A being of a kind its workspace keeps: what it does is the society's, as for anybody,
        # and what it is called is the workspace's store's.
        decider = _decider(
            connection, services, workspace_id, world_id, version_id, state, person, reader
        )
        made = _made_card(
            connection, workspace_id, snapshot, person, decider, said=said, left_out=left_out
        )
        return made, held
    kind = shipped_kind(ThingKindReference(**held["kind"]))
    runs = list(recorded_modules(state))
    hands = recorded_row(runs, "hands") is not None
    worn = _worn(connection, workspace_id, world_id, version_id, wanted, kind)
    card = {
        "profile": THING_CARD_PROFILE,
        "thing_id": wanted,
        "subject_id": None if person is None else wanted,
        "label": person["display_name"] if person is not None else kind.document["label"],
        "came_by": person["came_by"]
        if person is not None
        else ("placed" if thing is not None and thing["placed_id"] is not None else "crossed"),
        "kind": {
            "kind": kind.kind,
            "version": kind.version,
            "sha256": held["kind"]["sha256"],
            "label": kind.document["label"],
            "summary": kind.document["summary"],
            "class": kind.document["class"],
            "body": {"plan": kind.plan},
        },
        "runs": runs,
        "abilities": _abilities(kind, runs),
        "offers": _offers(kind, runs, routine_withheld(state, person) if person else frozenset()),
        "where": _where(held, person is not None),
        "holding": _holding(state, wanted) if person is not None and hands else None,
        "decider": None
        if person is None
        else _decider(
            connection, services, workspace_id, world_id, version_id, state, person, reader
        ),
        "look": worn,
        "looks": _looks(connection, workspace_id, kind),
        "kind_origin": kind.document["origin"],
        "crossing": None,
        "lines": None if person is None else _lines(said),
        # Lines said under an input that no longer authorizes are left out, and say so.
        **(
            {"lines_left_out": {"count": left_out, "reason": "unavailable_society_input"}}
            if person is not None and left_out
            else {}
        ),
        "society": {"tick": int(state["tick"]), "state_sha256": snapshot["state_sha256"]},
    }
    return card, held


def _made_card(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    snapshot: Mapping[str, Any],
    person: Mapping[str, Any],
    decider: Mapping[str, Any],
    *,
    said: Sequence[Mapping[str, Any]],
    left_out: int,
) -> dict[str, Any]:
    """The card of a being of a kind its workspace keeps (a creature drafted from words).

    What it can do, where it is, what it holds, who decides for it and what it said are the
    society's, read from the run form its state carries, as for any being. What it is called is
    the workspace's: the label and summary its maker's words gave it, the open model that drafted
    it and the sketch it wears are read here from the workspace's store by the digest the state
    names, on the caller's connection, and never from the society. Where the workspace no longer
    holds the kind (the creature was erased; the being leaves with the society's next minute) the
    card says so and names it only by its body, as the society does."""
    state = snapshot["state"]
    sha256 = str(person["kind"]["sha256"])
    run = kind_here(state, person["kind"])
    runs = list(recorded_modules(state))
    hands = recorded_row(runs, "hands") is not None
    kept = ThingStore(connection, workspace_id, None).kind_by_digest(sha256)
    drafted_by = None
    sketch = None
    if kept is not None:
        by = (kept.document["origin"] or {}).get("by") or {}
        if by.get("kind") == "model":
            drafted_by = {
                "provider": by["provider"],
                "model_id": by["model_id"],
                "name": load_manifest().model_name(str(by["model_id"])),
            }
        first = next(iter(kept.document["looks"]), None)
        if first is not None:
            sketch = admitted_look_by_digest(connection, workspace_id, first["sha256"])
    look: dict[str, Any] | None = None
    looks: list[dict[str, Any]] = []
    if sketch is not None:
        look = {
            "source": "workspace",
            "sha256": sketch.sha256,
            "label": sketch.label,
            "look_kind_words": _look_kind_words().get(sketch.look_kind),
            "chosen_by_owner": False,
            "origin": sketch.document.get("origin"),
        }
        looks = [
            {
                "source": "workspace",
                "sha256": sketch.sha256,
                "label": sketch.label,
                "licence": _licence(sketch),
                "authors": list((sketch.document.get("origin") or {}).get("authors", ())),
                "preview": None,
            }
        ]
    return {
        "profile": THING_CARD_PROFILE,
        "thing_id": person["id"],
        "subject_id": person["id"],
        # The society's own name for it: its body's, numbered.
        "label": person["display_name"],
        "came_by": person["came_by"],
        "kind": {
            "source": "workspace",
            "sha256": sha256,
            "held": kept is not None,
            "label": run.document["label"] if kept is None else kept.document["label"],
            "summary": run.document["summary"] if kept is None else kept.document["summary"],
            "class": "being",
            "body": {
                "plan": None,
                "name": run.document["label"],
                "summary": run.document["summary"],
            },
            "drafted_by": drafted_by,
        },
        "runs": runs,
        "abilities": _abilities(run, runs),
        "offers": _offers(run, runs, routine_withheld(state, person)),
        "where": _where(person, True),
        "holding": _holding(state, str(person["id"])) if hands else None,
        "decider": dict(decider),
        "look": look,
        "looks": looks,
        # Who made the kind, and nothing of the words it was made from.
        "kind_origin": None
        if kept is None
        else {"class": (kept.document["origin"] or {}).get("class"), "by": drafted_by},
        "crossing": None,
        "lines": _lines(said),
        **(
            {"lines_left_out": {"count": left_out, "reason": "unavailable_society_input"}}
            if left_out
            else {}
        ),
        "society": {"tick": int(state["tick"]), "state_sha256": snapshot["state_sha256"]},
    }


def choose_look(
    connection: psycopg.Connection,
    services: Services,
    society: SocietyRepository,
    *,
    workspace_id: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
    thing_id: uuid.UUID,
    look: Mapping[str, Any],
    actor: uuid.UUID,
) -> dict[str, Any]:
    """Record the world's owner's choice of a shipped ``look`` for ``thing_id``, one whose body plan
    is its kind's (:class:`~exulanica.world.thing_looks.ThingLookRefused` otherwise), appended to
    the look table and nothing else; answer the card as read before it with only the look it wears
    replaced. The caller's transaction holds the workspace's lock from the card's first read, so
    nothing else on the card can change before the answer."""
    card, held = _card(
        connection,
        services,
        society,
        workspace_id=workspace_id,
        world_id=world_id,
        version_id=version_id,
        thing_id=thing_id,
        reader=actor,
    )
    if card["kind"].get("source") == "workspace":
        # A creature its workspace keeps wears its sketch, its only look, until another is made.
        raise ThingLookRefused(
            "look_unfit", "a creature made from words wears only its sketch: no other look is made"
        )
    chosen = check_crossing_look(
        {key: card["kind"][key] for key in ("kind", "version", "sha256")},
        look,
        connection=connection,
        workspace_id=workspace_id,
    )
    kind = shipped_kind(
        ThingKindReference(**{k: card["kind"][k] for k in ("kind", "version", "sha256")})
    )
    if chosen.source == "workspace":
        plan = thing_catalogs().plan(kind.plan)
        if plan is None or not plan.bones:
            raise ThingLookRefused(
                "look_unfit", f"a {kind.kind} wears only its own looks: it has no bones to dress"
            )
    elif not _fits(kind, shipped_looks()[(chosen.look, chosen.version)]):
        raise ThingLookRefused(
            "look_unfit", f"a {kind.kind} wears only its own looks: it has no bones to dress"
        )
    placed = held.get("placed_id")
    connection.execute(
        "insert into world_thing_look(workspace_id,world_id,version_id,thing_id,placed_id,look,"
        "look_version,look_sha256,chosen_by,actor,source) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,'owner',%s,%s)",
        (
            workspace_id,
            world_id,
            version_id,
            thing_id,
            placed,
            chosen.look,
            chosen.version,
            bytes.fromhex(chosen.sha256),
            actor,
            chosen.source,
        ),
    )
    # The choice just appended is the newest one the thing may wear, so it is the one worn.
    return {**card, "look": _look_entry(connection, workspace_id, chosen, kind, owner=True)}


def _running(module: str, runs: Sequence[str]) -> str | None:
    """The version of ``module``'s module this society runs, or None where it runs none. The
    abilities catalog names each ability's module at one version; a society runs the version its
    first input recorded, and every version of a module serves the same abilities."""
    row = recorded_row(runs, ability_module(module).name)
    return None if row is None else row.module


def _abilities(kind: Any, runs: Sequence[str]) -> list[dict[str, str]]:
    """The kind's abilities a module this society runs serves, in the kind's order."""
    catalog = thing_catalogs().abilities
    found = []
    for ability in kind.document["abilities"]:
        entry = catalog.get(ability["key"])
        module = None if entry is None else _running(entry.module, runs)
        if entry is not None and module is not None:
            found.append({"key": entry.key, "words": entry.words, "module": module})
    return found


def _offers(
    kind: Any, runs: Sequence[str], withheld: Container[str] = frozenset()
) -> list[dict[str, str]]:
    """The kind's offers a module this society runs reads: the target of one of its abilities, or
    the offer a visitor arrives through, in the kind's order. Where the being's own kind withholds
    the activity that reads an offer (:func:`~exulanica.world.society_planner.routine_withheld`),
    as a talk takes two beings whose kinds both list it, nobody takes it up, so it is left out."""
    catalogs = thing_catalogs()
    reads: dict[str, str] = {}
    read_for: dict[str, str] = {}
    for ability in catalogs.abilities.values():
        if ability.target_offer is not None:
            reads.setdefault(ability.target_offer, ability.module)
            read_for.setdefault(ability.target_offer, ability.key)
    reads.setdefault(*_ARRIVAL_OFFER)
    words = {key: offer.words for key, offer in catalogs.offers.items()}
    found = []
    for offer in kind.document.get("offers", ()):
        if read_for.get(offer["key"]) in withheld:
            continue
        read_by = reads.get(offer["key"])
        module = None if read_by is None else _running(read_by, runs)
        if module is not None:
            found.append({"key": offer["key"], "words": words[offer["key"]], "module": module})
    return found


def _where(held: Mapping[str, Any], is_person: bool) -> dict[str, Any]:
    if is_person:
        return {"on_ground": "height_mm" not in held, "held_by": None, "socket": None, "on": None}
    return {
        "on_ground": held["held_by"] is None and "height_mm" not in held,
        "held_by": held["held_by"],
        "socket": held.get("socket"),
        "on": None,
    }


def _holding(state: Mapping[str, Any], holder: str) -> list[dict[str, Any]]:
    return [
        {
            "thing_id": thing["id"],
            "label": kind_here(state, thing["kind"]).document["label"],
            "socket": thing.get("socket"),
        }
        for thing in state["things"]
        if thing["held_by"] == holder
    ]


def _decider(
    connection: psycopg.Connection,
    services: Services,
    workspace_id: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
    state: Mapping[str, Any],
    person: Mapping[str, Any],
    reader: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Who decides for ``person``: its program where it came from outside and its program decides,
    else a person playing it (by whether that is the ``reader``, never by account), else the choice
    that decides for it (its own or its gate's), else the routine; with whether the world's owner
    may change it and why a chosen model is not asked here."""
    subject = person["id"]
    if decided_from_outside(state, subject):
        crossing = person["crossing"]
        return {
            "kind": "external",
            "bridge": crossing["bridge"],
            "label": crossing["bridge"],
            "until": None,
            "may_change": False,
            "refusal": "decided_from_outside",
        }
    role = person_role()
    contract = role.contract(role.terms(state["profile"]).versions)
    repository = SocietyModelChoiceRepository(connection, workspace_id, world_id=world_id)
    choice = repository.deciding(version_id, role, contract).get(subject)
    if choice is not None and is_played(choice["decider"]):
        # While a person plays it, only giving it back changes who decides.
        return {
            "kind": "person",
            "played_by_you": reader is not None and choice["decider"]["account_id"] == str(reader),
            "from": choice["from"],
            "may_change": False,
            "refusal": "being_played",
        }
    may_change = kind_allows(state, subject, "model")
    if choice is None or choice["model"] is None:
        return {
            "kind": "routine",
            "from": None if choice is None else choice["from"],
            "may_change": may_change,
            "refusal": None,
        }
    model = choice["model"]
    return {
        "kind": "model",
        "provider": model["provider"],
        "model_id": model["model_id"],
        "name": load_manifest().model_name(model["model_id"]),
        "from": choice["from"],
        "may_change": may_change,
        "refusal": services.choice_refusal(
            role, model, connection, workspace_id, str(state["profile"])
        ),
    }


def _worn(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
    thing_id: str,
    kind: Any,
) -> dict[str, Any]:
    """The look the thing wears: the latest chosen for it that it may still wear (a shipped look,
    or one the workspace keeps, by its digest), else its kind's first."""
    choices = look_choices(connection, workspace_id, world_id, version_id, thing_id=thing_id)
    chosen = next(
        (
            row
            for row in (*choices["looks"], *choices.get("workspace_looks", ()))
            if row["thing_id"] == thing_id
        ),
        None,
    )
    if chosen is None:
        return _look_entry(connection, workspace_id, None, kind, owner=False)
    if chosen["look"].get("source") == "workspace":
        reference = LookReference(None, None, chosen["look"]["sha256"], "workspace")
    else:
        reference = LookReference(
            chosen["look"]["look"], chosen["look"]["version"], chosen["look"]["sha256"]
        )
    return _look_entry(
        connection, workspace_id, reference, kind, owner=chosen["chosen_by"] == "owner"
    )


def _look_entry(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    reference: LookReference | None,
    kind: Any,
    *,
    owner: bool,
) -> dict[str, Any]:
    """The card's entry for a look the thing wears: ``reference``, or, where it is None or names a
    look no longer served (a shipped look a release dropped, or one the workspace withdrew since
    it was chosen), the kind's first look, not chosen by the owner."""
    look = None
    if reference is not None:
        look = (
            admitted_look_by_digest(connection, workspace_id, reference.sha256)
            if reference.source == "workspace"
            else shipped_looks().get((reference.look, reference.version))
        )
        if look is not None and look.sha256 != reference.sha256:
            look = None
    if look is None:
        first = kind.document["looks"][0]
        reference = LookReference(first["look"], first["version"], first["sha256"])
        look = shipped_looks()[(reference.look, reference.version)]
        owner = False
    assert reference is not None
    return {
        **reference.document(),
        "label": look.label,
        "look_kind_words": _look_kind_words().get(look.look_kind),
        "chosen_by_owner": owner,
        "origin": look.document.get("origin"),
    }


def _licence(look: Any) -> Any:
    """A look's licence, which its origin states."""
    return (look.document.get("origin") or {}).get("licence")


@functools.cache
def _look_kind_words() -> Mapping[str, str]:
    """Each look kind's own words, from the newest look-kinds catalog."""
    newest = max(
        CATALOG_DIRECTORY.glob("look-kinds.v*.json"),
        key=lambda path: int(path.name.split(".v")[1].split(".")[0]),
    )
    entries = json.loads(newest.read_text(encoding="utf-8"))["entries"]
    return {entry["key"]: entry["words"] for entry in entries}


def _fits(kind: Any, look: Any) -> bool:
    """Whether a shipped look may be worn by a thing of ``kind``: one made for its body plan, and,
    for a body with no bones (an object drawn at its kind's own size), one of the kind's own looks,
    so a sword is never drawn as a bench."""
    if look.body_plan != kind.plan:
        return False
    plan = thing_catalogs().plan(kind.plan)
    if plan is not None and plan.bones:
        return True
    return any(
        (own["look"], own["version"]) == (look.look, look.version) for own in kind.document["looks"]
    )


def _looks(
    connection: psycopg.Connection, workspace_id: uuid.UUID, kind: Any
) -> list[dict[str, Any]]:
    """Every look the kind may wear: each shipped one (:func:`_fits`), by key and version; then,
    for a body with bones, each the workspace keeps and has not withdrawn made for its body plan,
    by its digest alone."""
    plan = thing_catalogs().plan(kind.plan)
    own = (
        [
            {
                "source": "workspace",
                "sha256": look.sha256,
                "label": look.label,
                "licence": _licence(look),
                "authors": list((look.document.get("origin") or {}).get("authors", ())),
                "preview": None,
            }
            for look in ThingStore(connection, workspace_id, None).looks_held()
            if look.body_plan == kind.plan
        ]
        if plan is not None and plan.bones
        else []
    )
    return [*_shipped_looks(kind), *own]


def _shipped_looks(kind: Any) -> list[dict[str, Any]]:
    return [
        {
            **look.reference(),
            "label": look.label,
            "licence": _licence(look),
            "authors": list((look.document.get("origin") or {}).get("authors", ())),
            "preview": None,
        }
        for _key, look in sorted(shipped_looks().items())
        if _fits(kind, look)
    ]


def _lines(lines: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The lines the being said lately, newest first, each with who decided it."""
    found = []
    for said in lines:
        details = said["document"]["thing"]
        decider: dict[str, Any] = {"kind": details["decider"]}
        if "model" in details:
            decider["model_id"] = details["model"]["model_id"]
            decider["name"] = load_manifest().model_name(details["model"]["model_id"])
        found.append({"tick": said["tick"], "line": details["line"], "decider": decider})
    return found
