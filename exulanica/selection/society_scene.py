"""One society read for one question about its people, under current authorization.

:func:`read_scene` reads the society the page shows as the inspector reads it: its state, its
latest events up to the presented minute, the events that explain people's states and the decision
events that say who chose a goal, each input behind them authorized once per question.
:func:`build_scene` reads what the question's words name in it and writes every inhabitant's name
as a placeholder (``[inhabitant A]``), so no form that names one inhabitant reaches a hosted
request. :mod:`exulanica.selection.society_question` answers from the scene.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

import psycopg

from exulanica.epistemics.saved_names import (
    MIN_PART_LETTERS,
    PLACEHOLDER,
    SavedName,
    recognised_spans,
)
from exulanica.models.manifest import Manifest, load_manifest
from exulanica.selection.inhabitant_words import PlaceWords
from exulanica.selection.packet import MAX_PACKET_ITEMS
from exulanica.selection.society_answer import SocietyContext, SocietyRefusal, UnknownSocietyContext
from exulanica.world.society import UnavailableSocietyInput, UnknownSociety
from exulanica.world.society_engines import INPUT_ENGINES, society_engine
from exulanica.world.society_model_decisions import DECISION_EVENT_KIND
from exulanica.world.society_person_label import person_label
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.world_clock import ClockRefused
from exulanica.world.world_clock_repository import WorldClockRepository

#: How many recorded events one answer reads: the packet's own cap, so the composer is sent at most
#: as many lines as any packet holds.
EVENT_LINES: Final = MAX_PACKET_ITEMS

#: Either label typed into a question, in any case: it names nobody in this request.
_TYPED_LABEL: Final = re.compile(r"\[\s*(?:inhabitant|spot)\s+[a-z]+\s*\]", re.IGNORECASE)

#: The reason the planner records on a goal a person's model chose for them
#: (``REASON_CODES`` in ``exulanica/world/society_planner.py``). The line of that minute names the
#: model when the minute's one applied decision event for that person names it
#: (``_deciding_models``).
_CHOSEN_BY_THEIR_MODEL: Final = "chosen_by_their_model"

#: What a decision event says a consumed receipt did when the minute acted on the model's choice
#: (``_DISPOSITIONS`` in ``exulanica/world/society_model_decisions.py``).
_APPLIED: Final = "applied"


class _Labels:
    """The request's placeholders for inhabitants and places, in the order they are first used."""

    def __init__(self) -> None:
        self.people: dict[str, str] = {}
        self.spots: dict[str, str] = {}

    def person(self, inhabitant_id: str) -> str:
        if inhabitant_id not in self.people:
            self.people[inhabitant_id] = f"[inhabitant {_letters(len(self.people))}]"
        return self.people[inhabitant_id]

    def spot(self, target_id: str) -> str:
        if target_id not in self.spots:
            self.spots[target_id] = f"[spot {_letters(len(self.spots))}]"
        return self.spots[target_id]


def _letters(index: int) -> str:
    """``A`` for 0, ``Z`` for 25, ``AA`` for 26, as saved names' placeholders count."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


@dataclass(slots=True)
class SocietyScene:
    """One society read for one question: its state, its latest events, and what the question
    named in it. Built by :func:`read_scene`; the words sent onwards use its placeholders."""

    society_id: uuid.UUID
    version_id: uuid.UUID
    profile: str
    tick: int
    people: Mapping[str, Mapping[str, Any]]
    #: The targets people can use now, as the consumed input states them.
    usable_targets: frozenset[str]
    #: Newest first, at most :data:`EVENT_LINES`.
    events: tuple[Mapping[str, Any], ...]
    #: The event each person's state names as its explanation, by id, however long ago it was.
    explaining: Mapping[str, Mapping[str, Any]]
    selected: str | None
    selected_events: tuple[Mapping[str, Any], ...] = ()
    labels: _Labels = field(default_factory=_Labels)
    #: Where its people are and walk in their ground's own words (a site world's), served with
    #: the places its input states; None for a town's, whose words are the catalog's own.
    place_words: PlaceWords | None = None
    #: Inhabitants the question names by a name only they carry, by id.
    named: tuple[str, ...] = ()
    #: The question names a part several inhabitants share.
    named_ambiguously: bool = False
    #: A word of the question is a saved name and the selected inhabitant's name alike.
    collision: bool = False
    #: A word of the question is a saved name and, with nobody selected who has it, also an
    #: inhabitant's; it is read as the saved one's. The saved entity's class (``person``, ``place``
    #: and so on), or ``mixed`` for several of different classes; None for no such word.
    shared_name: str | None = None
    #: The question carries an ``[inhabitant A]`` or ``[spot A]`` label typed from elsewhere.
    typed_label: bool = False
    #: The question with every inhabitant's name written as a placeholder or taken out.
    question: str = ""
    #: The name of the model a person's owner chose, by the minute and the person whose goal it
    #: picked, for each such goal whose model one decision event of that minute names.
    deciding_models: Mapping[tuple[int, str], str] = field(default_factory=dict)
    #: Who decided, by the minute and the person whose goal it picked, where one applied decision
    #: event of that minute names its origin: a model, an outside program or a person playing.
    deciding_origins: Mapping[tuple[int, str], str] = field(default_factory=dict)
    #: For each placed object an event targets and the authored ``edit_seq`` its input followed,
    #: the version edit that last set that object at or before it, as ``(edit_seq, edit_id)``.
    object_edits: Mapping[tuple[str, int], tuple[int, uuid.UUID]] = field(default_factory=dict)
    #: The label the door lists for each bridge it offers this workspace, by key: where a person
    #: who came in from outside came from, in the words the page uses.
    bridges: Mapping[str, str] = field(default_factory=dict)


#: The key an event read here carries its input's authored ``edit_seq`` under, or None: read from
#: the input the event's authorization already loads, and never served.
_AUTHORED_EDIT_SEQ: Final = "input_authored_edit_seq"


def event_object_id(event: Mapping[str, Any]) -> str | None:
    """The placed authored object an event's target names, or None.

    A saved world's planner records the target a person heads for (``society_planner``); only an
    ``authored`` target names an object of the version.
    """
    target = (event.get("document") or {}).get("target")
    if not isinstance(target, Mapping) or target.get("origin") != "authored":
        return None
    object_id = target.get("object_id")
    return object_id if isinstance(object_id, str) and object_id else None


def _object_edits(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
    events: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, int], tuple[int, uuid.UUID]]:
    """The edit that last set each targeted object at or before its event's authored state.

    One read of the version's edit log for every object the events target. An undo that restored
    an object sets it as much as the edit it reversed did, so every kind counts.
    """
    wanted = {
        (object_id, int(seq))
        for event in events
        if (object_id := event_object_id(event)) is not None
        and isinstance(seq := event.get(_AUTHORED_EDIT_SEQ), int)
    }
    if not wanted:
        return {}
    rows = connection.execute(
        "select edit_id,edit_seq,object_id from world_alternate_version_edit "
        "where workspace_id=%s and world_id=%s and version_id=%s and object_id=any(%s) "
        "order by edit_seq",
        (workspace_id, world_id, version_id, sorted({object_id for object_id, _ in wanted})),
    ).fetchall()
    found: dict[tuple[str, int], tuple[int, uuid.UUID]] = {}
    for object_id, seq in wanted:
        setting = [row for row in rows if row["object_id"] == object_id and row["edit_seq"] <= seq]
        if setting:
            last = setting[-1]
            found[(object_id, seq)] = (int(last["edit_seq"]), last["edit_id"])
    return found


class _AuthorizedOnce:
    """One question's authorizer: each input authorized once, its verdict shared by every read.

    An authorization reads and hashes every reviewed asset the input names, so the scene, its
    latest events and the events that explain people's states ask it once per input between
    them, not once per read. A withdrawal is remembered as the refusal it was.
    """

    def __init__(self, authorize: Any) -> None:
        self._authorize = authorize
        self._verdicts: dict[tuple[int, str], UnavailableSocietyInput | None] = {}

    def __call__(self, document: Mapping[str, Any]) -> None:
        if self._authorize is None:
            raise UnavailableSocietyInput("current society input authorization is not configured")
        key = (int(document["input_seq"]), str(document["document_sha256"]))
        if key not in self._verdicts:
            try:
                self._authorize(document)
                self._verdicts[key] = None
            except UnavailableSocietyInput as refused:
                self._verdicts[key] = refused
        refusal = self._verdicts[key]
        if refusal is not None:
            raise refusal


def read_scene(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    context: SocietyContext,
    *,
    authorize: Any,
    question: str,
    saved: Sequence[SavedName],
    bridges: Mapping[str, str] | None = None,
) -> SocietyScene | SocietyRefusal:
    """Read the society the page shows, and what the question's words name in it.

    Raises :class:`UnknownSocietyContext` for a version with no society in this world, in another
    workspace, or an inhabitant not in it, all alike. The state is read as the inspector reads it,
    under current authorization of the input it consumed; a society whose current input cannot be
    authorized is the named refusal :data:`SocietyRefusal.UNAVAILABLE`. The latest events and the
    events that explain people's states are read here, each input behind them authorized once,
    and an event recorded under an input a withdrawal no longer authorizes is left out alone.
    Only events up to the version's presented minute are read (``exulanica.world-clock/v1``): a
    coupled world with roads runs its people ahead of what the page shows, by up to the clock's
    lead. A person's state line still describes the society's head minute: only the current
    state is stored. ``bridges`` is the label the door lists for each bridge it offers this
    workspace, by key, for the words of a person who came in from outside.
    """
    once = _AuthorizedOnce(authorize)
    repository = SocietyRepository(
        connection, workspace_id, world_id=world_id, input_authorizer=once
    )
    try:
        snapshot = repository.snapshot(context.version_id, places=True)
    except UnknownSociety:
        raise UnknownSocietyContext() from None
    except (UnavailableSocietyInput, ValueError):
        return SocietyRefusal.UNAVAILABLE
    # What the page shows: a coupled world with roads presents its people's minutes once traffic
    # has sealed them, so its society runs ahead of the page and no event past the presented
    # minute is cited. A legacy world presents its people's head (null here: nothing is left out).
    try:
        presented = WorldClockRepository(connection, workspace_id, world_id).read(
            context.version_id
        )["presented_through_tick"]
    except ClockRefused:
        raise UnknownSocietyContext() from None
    try:
        living = society_engine(snapshot["profile"]).state_family == "living"
        events = _authorized_events(
            connection,
            workspace_id,
            world_id,
            snapshot,
            repository,
            once,
            latest=EVENT_LINES,
            include_decisions=living,
            through_tick=presented,
        )
        selected_events = (
            _authorized_events(
                connection,
                workspace_id,
                world_id,
                snapshot,
                repository,
                once,
                latest=EVENT_LINES,
                include_decisions=True,
                subject_id=str(context.inhabitant_id),
                through_tick=presented,
            )
            if living and context.inhabitant_id is not None
            else []
        )
        shown = {str(event["event_id"]) for event in events}
        wanted = sorted(
            {
                str(event_id)
                for person in snapshot["state"].get("inhabitants", [])
                for event_id in (person.get("explanation") or {}).get("event_ids", [])
            }
            - shown
        )
        older = _authorized_events(
            connection,
            workspace_id,
            world_id,
            snapshot,
            repository,
            once,
            event_ids=wanted,
            through_tick=presented,
        )
        chosen_at = sorted(
            {
                (int(event["tick"]), str(event["subject_id"]))
                for event in (*events, *older)
                if (event.get("document") or {}).get("reason") == _CHOSEN_BY_THEIR_MODEL
            }
        )
        decisions = (
            list(
                {
                    str(event["event_id"]): event
                    for event in (*events, *selected_events)
                    if event["event_kind"] == DECISION_EVENT_KIND
                }.values()
            )
            if living
            else _authorized_events(
                connection,
                workspace_id,
                world_id,
                snapshot,
                repository,
                once,
                decisions_at=chosen_at,
                through_tick=presented,
            )
        )
    except (UnavailableSocietyInput, ValueError):
        # Authorization not configured, or a stored input that does not verify: the society
        # cannot be read. A withdrawn input only leaves out its own events.
        return SocietyRefusal.UNAVAILABLE
    places = snapshot.get("places") or {}
    scene = build_scene(
        snapshot,
        targets=[
            *places.get("targets", []),
            *(
                {"target_id": destination["destination_id"]}
                for destination in places.get("living_destinations", [])
            ),
        ],
        events=events,
        selected_events=selected_events,
        explaining=[*events, *older],
        selected=context.inhabitant_id,
        question=question,
        saved=saved,
        bridges=bridges,
    )
    words = places.get("place_words")
    if isinstance(words, Mapping):
        scene.place_words = PlaceWords(
            str(words["ground"]), str(words["here"]), str(words["around"])
        )
    if decisions:
        scene.deciding_models = _deciding_models(decisions, load_manifest())
        scene.deciding_origins = _deciding_origins(decisions)
    scene.object_edits = _object_edits(
        connection,
        workspace_id,
        world_id,
        scene.version_id,
        [*events, *older, *selected_events],
    )
    return scene


def _deciding_models(
    decisions: Iterable[Mapping[str, Any]], manifest: Manifest
) -> dict[tuple[int, str], str]:
    """The model to name for each minute and person, from that minute's decision events for them.

    A goal a person's model chose is recorded in the minute whose one applied receipt set it: the
    planner reads a model's goal policy only in the minute it is given
    (``advance_purposeful_society``), and one person takes at most one applied receipt a minute
    (``subject_already_decided``). So the model is named only when exactly one decision event of
    that minute and person applied a choice, and that event names the model; none, or several,
    leave the name out rather than guess. The name is :meth:`Manifest.model_name`'s, as the People
    panel shows it.
    """
    applied: dict[tuple[int, str], list[Mapping[str, Any]]] = {}
    for event in decisions:
        document = event["document"]
        if document.get("disposition") == _APPLIED:
            key = (int(event["tick"]), str(event["subject_id"]))
            applied.setdefault(key, []).append(document)
    named: dict[tuple[int, str], str] = {}
    for key, documents in applied.items():
        model = documents[0].get("model") if len(documents) == 1 else None
        if isinstance(model, Mapping) and isinstance(model.get("model_id"), str):
            named[key] = manifest.model_name(model["model_id"])
    return named


def _deciding_origins(decisions: Iterable[Mapping[str, Any]]) -> dict[tuple[int, str], str]:
    """Who decided for each minute and person, by the ``origin`` of that minute's one applied
    decision event for them, as :func:`_deciding_models` reads the model: none, or several, leave
    it out."""
    applied: dict[tuple[int, str], list[Mapping[str, Any]]] = {}
    for event in decisions:
        document = event["document"]
        if document.get("disposition") == _APPLIED:
            key = (int(event["tick"]), str(event["subject_id"]))
            applied.setdefault(key, []).append(document)
    return {
        key: documents[0]["origin"]
        for key, documents in applied.items()
        if len(documents) == 1 and isinstance(documents[0].get("origin"), str)
    }


def _authorized_events(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    snapshot: Mapping[str, Any],
    repository: SocietyRepository,
    authorize: _AuthorizedOnce,
    *,
    latest: int | None = None,
    event_ids: Sequence[str] = (),
    decisions_at: Sequence[tuple[int, str]] = (),
    include_decisions: bool = False,
    subject_id: str | None = None,
    through_tick: int | None = None,
) -> list[Mapping[str, Any]]:
    """This world's society's ``latest`` events, newest first, or the named ones however long ago,
    or the decision events recorded at ``decisions_at``'s minutes for its people, each only while
    the input it was recorded under is still authorized.

    The inputs are read, held to their rows and to this society's version, by the repository's own
    reader (``SocietyRepository._inputs``, whose ``_validate_scope`` binds them), and the latest
    events are ordered as ``SocietyRepository.events`` orders them. An event whose input a
    withdrawal no longer authorizes is left out, and only it; a stored input that does not verify
    raises, as the repository does.

    An event recording what a decision receipt did (:data:`DECISION_EVENT_KIND`) is never read
    with the latest events or by id, so none takes a line: the words catalog has none for it, and
    the person's own events say what they did, a goal their model chose by the reason
    ``chosen_by_their_model``. ``decisions_at`` reads those events alone, for the model that line
    names, under the same withdrawal rule. ``through_tick`` leaves out every event recorded after
    that minute, whichever way they are asked for.
    """
    chosen: str
    values: tuple[Any, ...]
    if latest is not None:
        chosen = (
            ("and e.subject_id=%s " if subject_id is not None else "")
            + ("" if include_decisions else "and e.event_kind<>%s ")
            + "order by e.tick desc,(e.document->>'order')::integer nulls last,e.event_id limit %s"
        )
        values = (
            *((subject_id,) if subject_id is not None else ()),
            *((DECISION_EVENT_KIND,) if not include_decisions else ()),
            latest,
        )
    elif event_ids:
        chosen = "and e.event_kind<>%s and e.event_id=any(%s::uuid[])"
        values = (DECISION_EVENT_KIND, list(event_ids))
    elif decisions_at:
        chosen = (
            "and e.event_kind=%s and (e.tick,e.subject_id) in "
            "(select * from unnest(%s::bigint[],%s::uuid[])) order by e.tick,e.event_id"
        )
        values = (
            DECISION_EVENT_KIND,
            [tick for tick, _ in decisions_at],
            [subject for _, subject in decisions_at],
        )
    else:
        return []
    bounded = "" if through_tick is None else "and e.tick<=%s "
    rows = connection.execute(
        "select e.event_id,e.tick,e.event_kind,e.subject_id,e.document "
        "from world_society_event e join world_society s "
        "on s.workspace_id=e.workspace_id and s.society_id=e.society_id "
        "where e.workspace_id=%s and s.world_id=%s and e.society_id=%s " + bounded + chosen,
        (
            workspace_id,
            world_id,
            snapshot["society_id"],
            *(() if through_tick is None else (through_tick,)),
            *values,
        ),
    ).fetchall()
    if snapshot["profile"] not in INPUT_ENGINES:
        return [dict(row) for row in rows]
    society = repository._row(uuid.UUID(str(snapshot["version_id"])))
    if society is None:
        raise ValueError("the society is no longer there")
    documents = repository._inputs(society, {row["document"]["input_seq"] for row in rows})
    authorized = set()
    for sequence, document in documents.items():
        try:
            authorize(document)
        except UnavailableSocietyInput:
            continue
        authorized.add(sequence)
    return [
        {**row, _AUTHORED_EDIT_SEQ: _authored_edit_seq(documents[row["document"]["input_seq"]])}
        for row in rows
        if row["document"]["input_seq"] in authorized
    ]


def _authored_edit_seq(document: Mapping[str, Any]) -> int | None:
    """The version ``edit_seq`` an input records it followed, or None for one that records none."""
    authored = document.get("authored_state")
    if not isinstance(authored, Mapping):
        return None
    seq = authored.get("edit_seq")
    return seq if isinstance(seq, int) and not isinstance(seq, bool) else None


def build_scene(
    snapshot: Mapping[str, Any],
    *,
    targets: Iterable[Mapping[str, Any]],
    events: Iterable[Mapping[str, Any]],
    explaining: Iterable[Mapping[str, Any]] = (),
    selected_events: Iterable[Mapping[str, Any]] = (),
    selected: uuid.UUID | None,
    question: str,
    saved: Sequence[SavedName],
    bridges: Mapping[str, str] | None = None,
) -> SocietyScene:
    """A society snapshot, its targets and its latest events, read for one question.

    ``snapshot`` is :meth:`SocietyRepository.snapshot`'s shape and ``events`` its ``events``';
    ``explaining`` holds the events people's states name as their explanation, however old;
    ``bridges`` the label the door lists for each bridge it offers, by key.
    Raises :class:`UnknownSocietyContext` when the selected inhabitant is not in it.
    """
    state = snapshot["state"]
    people = {str(person["id"]): person for person in state.get("inhabitants", [])}
    chosen = None if selected is None else str(selected)
    if chosen is not None and chosen not in people:
        raise UnknownSocietyContext()
    scene = SocietyScene(
        society_id=uuid.UUID(str(snapshot["society_id"])),
        version_id=uuid.UUID(str(snapshot["version_id"])),
        profile=str(snapshot["profile"]),
        tick=int(snapshot["current_tick"]),
        people=people,
        usable_targets=frozenset(
            str(target["target_id"]) for target in targets if target.get("enabled", True)
        ),
        events=tuple(events)[:EVENT_LINES],
        selected_events=tuple(selected_events)[:EVENT_LINES],
        explaining={str(event["event_id"]): event for event in explaining},
        selected=chosen,
        bridges=dict(bridges or {}),
    )
    if chosen is not None:
        scene.labels.person(chosen)
    _read_names(scene, question, saved)
    return scene


def _name_forms(name: str) -> list[str]:
    """A synthetic name whole, without its number ("Ari Ash" of "Ari Ash 1"), and each part of it
    long enough to be a name on its own."""
    whole = " ".join(name.split())
    if not whole:
        return []
    words = whole.split(" ")
    named = list(words)
    while len(named) > 1 and named[-1].isdigit():
        named.pop()
    forms = [whole, " ".join(named)]
    forms += [part for part in words if len(re.sub(r"[^\w]", "", part)) >= MIN_PART_LETTERS]
    return list(dict.fromkeys(forms))


def _form_pattern(form: str) -> re.Pattern[str]:
    return re.compile(
        r"(?<!\w)" + r"\s+".join(re.escape(word) for word in form.split(" ")) + r"(?!\w)",
        re.IGNORECASE,
    )


def _read_names(scene: SocietyScene, question: str, saved: Sequence[SavedName]) -> None:
    """Which inhabitants the question names, whether a name could be a saved person's, and the
    question with every inhabitant's name written as its placeholder.

    One reading, longest first, the way :func:`~exulanica.epistemics.saved_names.redact_names`
    reads saved names, over saved names and inhabitants' names together. The longer words win:
    "Emi Tanaka", a saved person, is that person however an inhabitant called Emi is named, and
    "Ari Ash", an inhabitant, is that inhabitant however a saved "Ash Ketchum" is named. The same
    words read as a saved name and as the selected inhabitant's name are a collision: the
    selection makes the ambiguity deliberate, and ``answer_question`` refuses the question by name
    before it is planned. With nobody selected who has them, they are the saved person's, and the
    answer says someone in the world shares the name.

    Of an inhabitant's forms, one that names one inhabitant, or the selected one among several,
    is written as that inhabitant's placeholder. One several share, none of them selected, names no
    one person and stays the person's own word, so "the ash cloud" is untouched; a question about
    one person named that way is refused as :data:`SocietyRefusal.SELECT_A_PERSON`. So no form
    that names one inhabitant reaches a hosted request.
    """
    # A label an earlier answer used names somebody only in that answer, and these letters are
    # this request's: typed back, it names nobody here, and the question is refused by name.
    scene.typed_label = _TYPED_LABEL.search(question) is not None
    owners: dict[str, set[str]] = {}
    for inhabitant_id, person in scene.people.items():
        for form in _name_forms(person_label(person)):
            owners.setdefault(form.casefold(), set()).add(inhabitant_id)
    everyone = set(scene.people)
    #: (start, end, kind, owners): kind 0 is a typed placeholder, 1 a saved name, 2 an
    #: inhabitant's name; at equal length a saved name is read before an inhabitant's.
    candidates: list[tuple[int, int, int, frozenset[str]]] = [
        (match.start(), match.end(), 0, frozenset()) for match in PLACEHOLDER.finditer(question)
    ]
    recognised = recognised_spans(question, saved)
    #: What kind of thing each saved name read is, by its span, for the note a tie adds.
    saved_class = {(start, end): name.entity_class for start, end, name in recognised}
    candidates += [(start, end, 1, frozenset()) for start, end, _ in recognised]
    for form, who in owners.items():
        if len(who) > 1 and who == everyone:
            continue
        candidates += [
            (match.start(), match.end(), 2, frozenset(who))
            for match in _form_pattern(form).finditer(question)
        ]
    accepted: list[tuple[int, int, int, frozenset[str]]] = []
    for candidate in sorted(candidates, key=lambda c: (c[0] - c[1], c[2], c[0])):
        start, end, kind, _ = candidate
        overlapping = [held for held in accepted if held[0] < end and start < held[1]]
        if not overlapping:
            accepted.append(candidate)
            continue
        tie = [
            held
            for held in overlapping
            if {held[2], kind} == {1, 2} and held[1] - held[0] == end - start
        ]
        if tie:
            # The same words are a saved name and an inhabitant's. With the one selected who has
            # it, the ambiguity is deliberate and refused by name; otherwise the words are the
            # saved person's, the library's by default, and the answer says someone in the world
            # shares the name.
            owners_here = next(c[3] for c in (candidate, *tie) if c[2] == 2)
            if scene.selected is not None and scene.selected in owners_here:
                scene.collision = True
            else:
                start_end = next((c[0], c[1]) for c in (candidate, *tie) if c[2] == 1)
                kind = saved_class[start_end]
                scene.shared_name = kind if scene.shared_name in (None, kind) else "mixed"
    named: dict[str, None] = {}
    written: list[str] = []
    at = 0
    for start, end, kind, who in sorted(accepted):
        written.append(question[at:start])
        if kind != 2:
            written.append(question[start:end])
        elif len(who) == 1:
            (inhabitant_id,) = who
            named[inhabitant_id] = None
            written.append(scene.labels.person(inhabitant_id))
        elif scene.selected is not None and scene.selected in who:
            named[scene.selected] = None
            written.append(scene.labels.person(scene.selected))
        else:
            # Several people's, none of them selected: no one person's name, so it stays the
            # person's own word, and a question about one person is refused select_a_person.
            scene.named_ambiguously = True
            written.append(question[start:end])
        at = end
    written.append(question[at:])
    scene.named = tuple(named)
    scene.question = "".join(written)
