"""Who decides for which subjects of a society, for each decision role: the owner's choices.

A choice names, for one subject or a group of a role's subjects, who decides for them: the world's
own rules (the routine), a model the manifest offers the role, by provider and identifier, or an
outside program deciding under a grant the world's owner issued (:mod:`exulanica.world.deciders`).
Choices are appended in order and never changed (migration 0110, ``world_society_model_choice``),
each naming who made it and when, and each recorded under its role's own choice profile, so a
subject's decider at any time is the latest choice of their role naming them, and a society with no
choice is run by its rules alone.

A choice of the role's first profile names ``model``, a model or none; one of the second names
``decider``, the descriptor (migration 0146). Both are read for as long as they are stored: every
read of a choice gives its ``decider`` and the ``model`` it names, which is none for the routine and
for an outside program, so every reader that asks which model runs somebody reads the answer it
always did, and an outside program spends nothing.

A person may play one being of a society of things ("Play this one"): a choice naming it with the
decider ``{"kind": "person", "account_id": ...}``, recorded only through the play route
(:meth:`SocietyModelChoiceRepository.record_play`), and refused by name while another account plays
it (``being_played``). Giving it back records a choice naming the same person with ``ended``
(``given_back``, or ``player_left`` when the host gives back a being its player stopped answering
for): the being is decided for again as it was before the play began, by its own earlier choice, or,
where it had none, by its gate's group or its routine, so no decider is copied and nothing outlives
a gate's release. While a being is played, no other choice may name it.

A choice of the second profile may name a group instead of subjects (``group``, with no subjects;
the migration "a choice may name a gate's visitors"): ``arrivals_under_grant``, every visitor that
arrives under one grant and whose arrival said the world decides for it, which is how the world's
owner names the mind a gate's travellers get. A choice naming a subject comes before a group's, and
a group's comes before the routine; the bound on the subjects models run is applied to a group's
when a minute asks (:meth:`SocietyModelChoiceRepository.deciding`).

What a choice may name is checked here, by name: the society's engine must host the role; every
subject must be one the role may decide for in its state, and never one that came in from outside
whose own program decides for it; the model must be declared, offered to the role (a chat model a
probe verified to answer a choice, with the use cases the role needs) and askable under the role's
contract by a mechanism it was verified for; and the subjects models run stay within the bound the
role's contract names. An outside program is chosen only by the route that records its grant
(:meth:`SocietyModelChoiceRepository.record_external_choice`), in the grant's own transaction.
Whether this process can reach the model's provider, or the program's door, is the host's to say,
not the world's: a choice outlives a deployment.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.models.errors import ManifestError
from exulanica.models.manifest import Manifest
from exulanica.world.deciders import (
    decided_by_world,
    decided_from_outside,
    decider,
    is_played,
    model_of,
    of_model,
)
from exulanica.world.decision_roles import DecisionContract, DecisionRole, decision_roles
from exulanica.world.society import UnknownSociety
from exulanica.world.society_engines import society_engine
from exulanica.world.society_planner import input_sha256
from exulanica.world.society_things import kind_allows

__all__ = [
    "CHOICE_REFUSALS",
    "ENDED",
    "GROUPS",
    "ModelChoiceRefused",
    "SocietyModelChoiceRepository",
    "decider_of",
    "decides_at",
    "latest_choices",
]

#: How a gate's choice states its end: an RFC 3339 instant in UTC, to the second.
_ENDS_AT: Final = "%Y-%m-%dT%H:%M:%SZ"
#: The groups a choice may name instead of subjects: every visitor that arrives under one grant and
#: whose arrival said the world decides for it.
GROUPS: Final = ("arrivals_under_grant",)
#: Why a person stopped playing a being: they gave it back, or they stopped answering for it and the
#: host gave it back for them.
ENDED: Final = ("given_back", "player_left")

#: Why a choice is refused, by the code the route answers with, and the detail.
CHOICE_REFUSALS: Final = {
    "engine_takes_no_model_choice": (
        "this society's engine hosts no role a chosen model decides for; the engine table says "
        "which do"
    ),
    "person_not_in_this_world": "a choice names somebody who is not one of this society's people",
    "person_named_twice": "a choice names one person more than once",
    "model_not_declared": "the model is not one the manifest declares",
    "model_not_offered": (
        "the model is not offered to a person's decisions: it is not a chat model a probe verified "
        "to answer a choice"
    ),
    "model_not_askable": (
        "the contract this society's engine asks by accepts no mechanism the model was verified "
        "for, or the model is not offered for a choice that takes a line"
    ),
    "too_many_model_people": "the choice would run more people by models than the contract allows",
    "choice_key_reused": "this idempotency key already names another choice",
    "subject_chosen_under_another_role": (
        "one subject cannot be run by chosen models under two decision roles"
    ),
    "decided_from_outside": (
        "a program from outside decides for somebody this choice names: the one they came into "
        "the world with, or one the world's owner granted them to; end its grant, or send them "
        "away, instead"
    ),
    "engine_takes_no_traveller_choice": (
        "only a society of things takes visitors, so only its engine takes the mind a gate's "
        "travellers get"
    ),
    "decider_not_allowed": (
        "somebody this choice names is a kind of thing that kind of decider may not decide for"
    ),
    "engine_takes_no_play": "only a society of things' beings may be played",
    "being_played": (
        "somebody else is playing this being now; it can be chosen for again once it is given back"
    ),
    "not_played": "nobody here is playing this being",
}


def decides_at(ends_at: str | None, now: datetime) -> bool:
    """Whether a gate's choice ending at ``ends_at`` (as the group states it, to the second in
    UTC, or None for a group stored with no end) decides at ``now``: strictly before its end."""
    return ends_at is None or now < datetime.strptime(ends_at, _ENDS_AT).replace(tzinfo=UTC)


class ModelChoiceRefused(ValueError):
    """A choice this world may not record, by a code a caller can act on."""

    def __init__(self, code: str) -> None:
        super().__init__(CHOICE_REFUSALS[code])
        self.code = code
        self.detail = CHOICE_REFUSALS[code]


def _came_from_outside(state: Mapping[str, Any], subject_id: str) -> bool:
    return any(
        person.get("id") == subject_id and person.get("came_by") == "crossed"
        for person in state.get("inhabitants", ())
    )


def _counted(
    society: Mapping[str, Any], role: DecisionRole, choices: Mapping[str, Any]
) -> list[str]:
    """The subjects whose choices count toward the bound on the subjects models run: in a society
    of things only those still in it, since a visitor that left never comes back by its id;
    in any other society every subject a choice names, a person sent away among them, who may
    be brought back."""
    if society_engine(str(society["engine_version"])).state_family != "things":
        return list(choices)
    present = set(role.adapter.subjects(society["state"]))
    return [subject for subject in choices if subject in present]


def decider_of(document: Mapping[str, Any]) -> dict[str, Any]:
    """Who a stored choice names to decide: its ``decider``, or for a choice of a role's first
    profile the routine or the model its ``model`` names."""
    if "decider" in document:
        return decider(document["decider"])
    return of_model(document["model"])


def _view(document: Mapping[str, Any], recorded_at: Any) -> dict[str, Any]:
    """A stored choice as every reader reads it: as stored, with its decider and the model it
    names, and when it was recorded."""
    described = decider_of(document)
    return {
        **document,
        "decider": described,
        "model": model_of(described),
        "recorded_at": recorded_at,
    }


def latest_choices(
    role: DecisionRole, choices: Sequence[Mapping[str, Any]]
) -> dict[str, Mapping[str, Any]]:
    """Each subject's latest choice of ``role`` among ``choices``, read as
    :meth:`SocietyModelChoiceRepository.history` reads them, in order. A choice ending a person's
    play (``ended``) restores what the subject had before the play began: its own earlier choice,
    or none. Every reader of who decides for a subject reads it here, the models read and a
    comparison's definition alike."""
    return _latest(role, choices)[0]


def _latest(
    role: DecisionRole, choices: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Mapping[str, Any]], dict[str, int]]:
    """:func:`latest_choices`, and the ``choice_seq`` of the choice from which each subject's
    latest choice decides: its own, or, for one restored when a play ended, the choice that ended
    it."""
    current: dict[str, Mapping[str, Any]] = {}
    since: dict[str, int] = {}
    before: dict[str, Mapping[str, Any] | None] = {}
    for choice in choices:
        for subject in choice[role.choice_subjects]:
            if "ended" in choice:
                held = before.pop(subject, None)
                if held is None:
                    current.pop(subject, None)
                    since.pop(subject, None)
                else:
                    current[subject] = held
                    since[subject] = int(choice["choice_seq"])
                continue
            if is_played(choice["decider"]):
                before[subject] = current.get(subject)
            current[subject] = choice
            since[subject] = int(choice["choice_seq"])
    return current, since


def _asked_model(model: Any) -> dict[str, Any] | None:
    """The decider an owner's choice of ``model`` asks for, before anything checks the model: the
    routine for none, the model it names, or None for a body that names no model at all, which
    matches no recorded choice and is refused when it is checked."""
    if model is None:
        return {"kind": "routine"}
    if not isinstance(model, Mapping) or set(model) != {"provider", "model_id"}:
        return None
    try:
        return of_model(model)
    except ValueError:
        return None


def _model_record(
    role: DecisionRole, manifest: Manifest, contract: DecisionContract, model: Any
) -> dict | None:
    if model is None:
        return None
    if not isinstance(model, Mapping) or set(model) != {"provider", "model_id"}:
        raise ModelChoiceRefused("model_not_declared")
    model_id, provider = model["model_id"], model["provider"]
    if not isinstance(model_id, str) or model_id not in manifest.models:
        raise ModelChoiceRefused("model_not_declared")
    spec = manifest.spec(model_id)
    if spec.provider != provider:
        raise ModelChoiceRefused("model_not_declared")
    try:
        manifest.offered(role.chosen, model_id)
    except ManifestError as exc:
        raise ModelChoiceRefused("model_not_offered") from exc
    if contract.mechanism_for(spec) is None:
        raise ModelChoiceRefused("model_not_askable")
    return {"provider": provider, "model_id": model_id}


class SocietyModelChoiceRepository:
    """The owner's choices for one world's societies, over a workspace-scoped connection."""

    def __init__(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, *, world_id: str
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.world_id = world_id

    def _society(self, version_id: uuid.UUID, *, lock: bool) -> dict[str, Any]:
        row = self.connection.execute(
            "select society_id,engine_version,state from world_society where workspace_id=%s "
            "and world_id=%s and version_id=%s" + (" for update" if lock else ""),
            (self.workspace_id, self.world_id, version_id),
        ).fetchone()
        if row is None:
            raise UnknownSociety("society is unavailable")
        return row

    def _rows(self, society_id: uuid.UUID) -> list[dict[str, Any]]:
        return self.connection.execute(
            "select choice_seq,request_id,document,document_sha256,chosen_by,recorded_at "
            "from world_society_model_choice where workspace_id=%s and world_id=%s "
            "and society_id=%s order by choice_seq",
            (self.workspace_id, self.world_id, society_id),
        ).fetchall()

    @staticmethod
    def _of(role: DecisionRole, rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        """The rows of ``role``'s choices, of its profile now or an earlier one; a choice of a
        profile no registered role writes is refused by name, never read as anybody's."""
        found = []
        for row in rows:
            profile = row["document"]["profile"]
            if decision_roles().for_choice(profile) is None:
                raise ValueError(f"a model choice of profile {profile!r} names no registered role")
            if role.reads_choice(profile):
                found.append(row)
        return found

    @staticmethod
    def _current(
        role: DecisionRole, rows: Sequence[Mapping[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Each subject's own latest choice of ``role``, by subject id, as
        :func:`latest_choices` reads it."""
        views = [
            _view(row["document"], row["recorded_at"])
            for row in SocietyModelChoiceRepository._of(role, rows)
        ]
        return {
            subject: {
                "decider": view["decider"],
                "model": view["model"],
                "choice_seq": view["choice_seq"],
                "chosen_by": view["chosen_by"],
                "recorded_at": view["recorded_at"],
                # The minute a person's play began, from which their quiet minutes count.
                **({"since_tick": view["since_tick"]} if "since_tick" in view else {}),
            }
            for subject, view in latest_choices(role, views).items()
        }

    @staticmethod
    def _groups(role: DecisionRole, rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        """Each grant's latest group choice of ``role``, by grant id."""
        found: dict[str, dict[str, Any]] = {}
        for row in SocietyModelChoiceRepository._of(role, rows):
            document = row["document"]
            group = document.get("group")
            if group is None:
                continue
            described = decider_of(document)
            found[group["grant_id"]] = {
                "ends_at": group.get("ends_at"),
                "decider": described,
                "model": model_of(described),
                "choice_seq": document["choice_seq"],
                "chosen_by": document["chosen_by"],
                "recorded_at": row["recorded_at"],
            }
        return found

    def traveller_choices(
        self, version_id: uuid.UUID, role: DecisionRole
    ) -> dict[str, dict[str, Any]]:
        """Each grant's latest group choice of ``role`` that still decides: the mind its arriving
        visitors get when their arrival says the world decides for them, by grant id; one past
        its end is left out, as :meth:`deciding` leaves it out."""
        rows = self._rows(self._society(version_id, lock=False)["society_id"])
        return self._deciding_groups(role, rows)

    def _deciding_groups(
        self, role: DecisionRole, rows: Sequence[Mapping[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Each grant's latest group choice that decides now: strictly before its end, as the
        database's clock reads it, or with no end; the clock is read only where a group is
        chosen."""
        groups = self._groups(role, rows)
        if not groups:
            return {}
        now = self.connection.execute("select statement_timestamp() as now").fetchone()["now"]
        return {
            grant_id: choice
            for grant_id, choice in groups.items()
            if decides_at(choice["ends_at"], now)
        }

    def _asked(self, version_id: uuid.UUID, role: DecisionRole) -> DecisionContract:
        """The contract the society's engine asks ``role`` under, which a chosen model is checked
        against whatever contract a caller records the choice under: a model it cannot ask, as
        one not offered for the lines a society of things' people say, is refused
        ``model_not_askable`` for every caller alike."""
        return role.contract(role.terms(self.engine(version_id)).versions)

    def engine(self, version_id: uuid.UUID) -> str:
        """The engine of the society ``version_id`` holds: its people are asked under its terms."""
        return str(self._society(version_id, lock=False)["engine_version"])

    def deciding(
        self, version_id: uuid.UUID, role: DecisionRole, contract: DecisionContract
    ) -> dict[str, dict[str, Any]]:
        """Who decides for each of ``role``'s subjects a choice decides for, by subject id: its own
        latest choice, else, for a visitor the world decides for, the latest choice naming the
        group of arrivals under its grant (``from``: ``choice`` or ``travellers``), where its kind
        allows that kind of decider. A group's model runs a visitor only while the subjects models
        run stay within the contract's bound, in the order the visitors came; past it the routine
        decides for the rest (``travellers_over_bound``). In a society of things the bound holds
        for own choices too: past it, the latest own choices of a model go to the routine
        (``choice_over_bound``). A subject no choice names is absent, as from :meth:`current`."""
        society = self._society(version_id, lock=False)
        rows = self._rows(society["society_id"])
        found = {
            subject: {**choice, "from": "choice"}
            for subject, choice in self._current(role, rows).items()
        }
        state = society["state"]
        bound = contract.value(role.subjects_bound)
        if society_engine(str(society["engine_version"])).state_family == "things":
            # Only beings still here count toward the bound, so one that leaves and comes back
            # by the same id (a placed being an edit removed and an undo restored) could take a
            # place chosen meanwhile: past the bound, the latest own choices of a model go to the
            # routine (``choice_over_bound``), the earliest keeping theirs. A being given back
            # after a person played it takes its model again from then, after any chosen while it
            # was played, which keep theirs.
            here = set(role.adapter.subjects(state))
            since = _latest(
                role, [_view(row["document"], row["recorded_at"]) for row in self._of(role, rows)]
            )[1]
            chosen = sorted(
                (
                    subject
                    for subject, choice in found.items()
                    if subject in here and choice["decider"]["kind"] == "model"
                ),
                key=lambda subject: (since[subject], subject),
            )
            for subject in chosen[bound:]:
                if not kind_allows(state, subject, "routine"):
                    del found[subject]
                    continue
                found[subject] = {
                    **found[subject],
                    "decider": {"kind": "routine"},
                    "model": None,
                    "from": "choice_over_bound",
                }
        # A gate's choice decides strictly before its end, as the database's clock reads it.
        groups = self._deciding_groups(role, rows)
        if not groups:
            return found
        room = bound - sum(
            1
            for subject in _counted(society, role, found)
            if found[subject]["decider"]["kind"] == "model"
        )
        present = set(role.adapter.subjects(state))
        visitors = sorted(
            (
                person
                for person in state.get("inhabitants", ())
                if person.get("id") in present
                and person["id"] not in found
                and decided_by_world(person)
                and person["crossing"]["grant_id"] in groups
            ),
            key=lambda person: person["ordinal"],
        )
        for person in visitors:
            choice = groups[person["crossing"]["grant_id"]]
            if not kind_allows(state, person["id"], choice["decider"]["kind"]):
                # A kind that takes no such decider is decided for as its kind says.
                continue
            if choice["decider"]["kind"] == "model":
                if room <= 0:
                    if not kind_allows(state, person["id"], "routine"):
                        # Past the bound, a kind the routine may not run is run by nobody here.
                        continue
                    found[person["id"]] = {
                        **choice,
                        "decider": {"kind": "routine"},
                        "model": None,
                        "from": "travellers_over_bound",
                    }
                    continue
                room -= 1
            found[person["id"]] = {**choice, "from": "travellers"}
        return found

    def current(self, version_id: uuid.UUID, role: DecisionRole) -> dict[str, dict[str, Any]]:
        """Each subject's latest choice of ``role``, by subject id, with who decides for them and
        the model that is, if any; one never chosen for is absent."""
        return self._current(role, self._rows(self._society(version_id, lock=False)["society_id"]))

    def history(self, version_id: uuid.UUID, role: DecisionRole) -> list[dict[str, Any]]:
        """Every choice made for ``role`` in this society, in order, as stored, each with its
        decider and the model it names."""
        return [
            _view(row["document"], row["recorded_at"])
            for row in self._of(
                role, self._rows(self._society(version_id, lock=False)["society_id"])
            )
        ]

    def record_choice(
        self,
        version_id: uuid.UUID,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        subjects: Sequence[str],
        model: Mapping[str, str] | None,
        chosen_by: uuid.UUID,
        manifest: Manifest,
        contract: DecisionContract,
    ) -> dict[str, Any]:
        """Record the owner's choice of a model, or of the routine with none, for ``subjects``, or
        return the one this idempotency key already recorded.

        An exact retry is answered with the recorded choice before anything else is checked, so
        it still returns after the model stops being offered.
        """

        def described() -> dict[str, Any]:
            return of_model(_model_record(role, manifest, self._asked(version_id, role), model))

        recorded = self._record(
            version_id,
            role,
            request_id=request_id,
            subjects=subjects,
            asked=_asked_model(model),
            described=described,
            chosen_by=chosen_by,
            contract=contract,
            granted_away=True,
        )
        assert recorded is not None
        return recorded

    def record_external_choice(
        self,
        version_id: uuid.UUID,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        subjects: Sequence[str],
        bridge: str,
        grant_id: uuid.UUID,
        chosen_by: uuid.UUID,
        contract: DecisionContract,
    ) -> dict[str, Any]:
        """Record that the outside program behind ``bridge`` decides for ``subjects`` under the
        grant ``grant_id``: called by the route that records the grant, in its transaction, never
        by the models route. Returns the choice, or the one this key already recorded."""
        external = decider({"kind": "external", "bridge": bridge, "grant_id": str(grant_id)})
        recorded = self._record(
            version_id,
            role,
            request_id=request_id,
            subjects=subjects,
            asked=external,
            described=lambda: external,
            chosen_by=chosen_by,
            contract=contract,
        )
        assert recorded is not None
        return recorded

    def record_play(
        self,
        version_id: uuid.UUID,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        subject: str,
        account_id: uuid.UUID,
        contract: DecisionContract,
    ) -> dict[str, Any]:
        """Record that the person ``account_id`` plays ``subject``: called by the play route alone.
        Refused by name where the engine is not a society of things' (``engine_takes_no_play``),
        where another account plays the being (``being_played``), where its own program decides for
        it (``decided_from_outside``) or where its kind lets no person decide for it
        (``decider_not_allowed``). A person already playing it is answered with that play."""
        played = decider({"kind": "person", "account_id": str(account_id)})
        with self.connection.transaction():
            society = self._society(version_id, lock=True)
            if society_engine(str(society["engine_version"])).state_family != "things":
                raise ModelChoiceRefused("engine_takes_no_play")
            held = self._current(role, self._rows(society["society_id"])).get(subject)
            if held is not None and held["decider"] == played:
                return {"subject_id": subject, **held}
            recorded = self._record(
                version_id,
                role,
                request_id=request_id,
                subjects=[subject],
                asked=played,
                described=lambda: played,
                chosen_by=account_id,
                contract=contract,
                granted_away=True,
                fields={"since_tick": int(society["state"]["tick"])},
            )
        assert recorded is not None
        return recorded

    def give_back(
        self,
        version_id: uuid.UUID,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        subject: str,
        account_id: uuid.UUID,
        chosen_by: uuid.UUID,
        contract: DecisionContract,
        ended: str,
    ) -> dict[str, Any]:
        """End the play of ``subject`` by ``account_id``, for ``ended`` (:data:`ENDED`): the being
        is decided for again as it was before the play began. ``chosen_by`` is the player giving
        it back, or the host's actor for ``player_left``. Refused ``not_played`` where that person
        does not play it; a retry of this key returns the choice it recorded."""
        if ended not in ENDED:
            raise ValueError(f"a play ends {ENDED}, not {ended!r}")
        played = decider({"kind": "person", "account_id": str(account_id)})
        with self.connection.transaction():
            society = self._society(version_id, lock=True)
            rows = self._rows(society["society_id"])
            existing = next((row for row in rows if row["request_id"] == request_id), None)
            if existing is not None:
                document = existing["document"]
                if (
                    document.get("ended") != ended
                    or decider_of(document) != played
                    or document[role.choice_subjects] != [subject]
                    or document["chosen_by"] != str(chosen_by)
                ):
                    raise ModelChoiceRefused("choice_key_reused")
                return _view(document, existing["recorded_at"])
            held = self._current(role, rows).get(subject)
            if held is None or held["decider"] != played:
                raise ModelChoiceRefused("not_played")
            sequence = (rows[-1]["choice_seq"] if rows else 0) + 1
            document: dict[str, Any] = {
                "profile": role.choice_profile,
                "choice_seq": sequence,
                "request_id": str(request_id),
                "society_id": str(society["society_id"]),
                role.choice_subjects: [subject],
                "decider": played,
                "ended": ended,
                "contract": contract.binding(),
                "chosen_by": str(chosen_by),
            }
            document["document_sha256"] = input_sha256(document)
            return self._insert(society["society_id"], sequence, request_id, document, chosen_by)

    def record_traveller_choice(
        self,
        version_id: uuid.UUID,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        grant_id: uuid.UUID,
        model: Mapping[str, str] | None,
        chosen_by: uuid.UUID,
        manifest: Manifest,
        contract: DecisionContract,
        ends_at: datetime,
    ) -> dict[str, Any]:
        """Record the mind every visitor arriving under ``grant_id`` gets when its arrival says the
        world decides for it: a model the manifest offers the role, or the routine for none.
        Called by the route that records the grant, in its transaction, which holds the grant to
        this world; refused as any owner's choice of a model is. Returns the choice, or the one
        this key already recorded. ``ends_at``, the grant's own end (aware, in UTC; every grant
        ends), ends the choice: it decides strictly before then, to the second, by the database's
        clock, so no host reserves an ask under it for the grant's visitors once the grant has
        ended, whenever their departures are written. An ask reserved before the end runs as
        reserved, and an owner's own choice naming a visitor is not ended by it."""

        def described() -> dict[str, Any]:
            return of_model(_model_record(role, manifest, self._asked(version_id, role), model))

        if ends_at.tzinfo is None or ends_at.utcoffset() != timedelta(0):
            raise ValueError("a gate's choice ends at an instant stated in UTC")
        group = {
            "kind": "arrivals_under_grant",
            "grant_id": str(grant_id),
            "ends_at": ends_at.strftime(_ENDS_AT),
        }
        return self._record_group(
            version_id,
            role,
            request_id=request_id,
            group=group,
            asked=_asked_model(model),
            described=described,
            chosen_by=chosen_by,
            contract=contract,
        )

    def release_traveller_choice(
        self,
        version_id: uuid.UUID,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        grant_id: uuid.UUID,
        chosen_by: uuid.UUID,
        contract: DecisionContract,
    ) -> dict[str, Any] | None:
        """Hand the visitors arriving under ``grant_id`` back to the routine, as one group choice:
        called by the route that revokes the grant, in its transaction, so no later grant of the
        same id inherits a mind. It ends with the grant, as the choice it releases does. None,
        recording nothing, when no group choice names the grant."""
        with self.connection.transaction():
            society = self._society(version_id, lock=True)
            rows = self._rows(society["society_id"])
            existing = next((row for row in rows if row["request_id"] == request_id), None)
            latest = self._groups(role, rows).get(str(grant_id))
            if existing is None and latest is None:
                return None
            ends_at = (
                existing["document"]["group"]["ends_at"]
                if existing is not None and "group" in existing["document"]
                else None
                if latest is None
                else latest["ends_at"]
            )
            group = {"kind": "arrivals_under_grant", "grant_id": str(grant_id)}
            if ends_at is not None:
                group["ends_at"] = ends_at
            return self._record_group(
                version_id,
                role,
                request_id=request_id,
                group=group,
                asked={"kind": "routine"},
                described=lambda: {"kind": "routine"},
                chosen_by=chosen_by,
                contract=contract,
            )

    def _record_group(
        self,
        version_id: uuid.UUID,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        group: Mapping[str, str],
        asked: Mapping[str, Any] | None,
        described: Any,
        chosen_by: uuid.UUID,
        contract: DecisionContract,
    ) -> dict[str, Any]:
        """Record one choice of ``role`` naming ``group`` rather than subjects, checked as
        ``described()`` checks it, or return the one this idempotency key already recorded."""
        with self.connection.transaction():
            society = self._society(version_id, lock=True)
            rows = self._rows(society["society_id"])
            existing = next((row for row in rows if row["request_id"] == request_id), None)
            if existing is not None:
                document = existing["document"]
                if (
                    not role.reads_choice(document["profile"])
                    or document.get("group") != dict(group)
                    or asked is None
                    or decider_of(document) != dict(asked)
                    or document["chosen_by"] != str(chosen_by)
                ):
                    raise ModelChoiceRefused("choice_key_reused")
                return _view(document, existing["recorded_at"])
            if not role.hosted_by(society["engine_version"]):
                raise ModelChoiceRefused("engine_takes_no_model_choice")
            if society_engine(str(society["engine_version"])).state_family != "things":
                raise ModelChoiceRefused("engine_takes_no_traveller_choice")
            record = described()
            sequence = (rows[-1]["choice_seq"] if rows else 0) + 1
            document: dict[str, Any] = {
                "profile": role.choice_profile,
                "choice_seq": sequence,
                "request_id": str(request_id),
                "society_id": str(society["society_id"]),
                role.choice_subjects: [],
                "group": dict(group),
                "decider": record,
                "contract": contract.binding(),
                "chosen_by": str(chosen_by),
            }
            document["document_sha256"] = input_sha256(document)
            return self._insert(society["society_id"], sequence, request_id, document, chosen_by)

    def _insert(
        self,
        society_id: uuid.UUID,
        sequence: int,
        request_id: uuid.UUID,
        document: dict[str, Any],
        chosen_by: uuid.UUID,
    ) -> dict[str, Any]:
        row = self.connection.execute(
            "insert into world_society_model_choice(workspace_id,world_id,society_id,"
            "choice_seq,request_id,document,document_sha256,chosen_by) "
            "values(%s,%s,%s,%s,%s,%s,%s,%s) returning recorded_at",
            (
                self.workspace_id,
                self.world_id,
                society_id,
                sequence,
                request_id,
                Jsonb(document),
                document["document_sha256"],
                chosen_by,
            ),
        ).fetchone()
        return _view(document, row["recorded_at"])

    def release_external_choice(
        self,
        version_id: uuid.UUID,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        grant_id: uuid.UUID,
        chosen_by: uuid.UUID,
        contract: DecisionContract,
    ) -> dict[str, Any] | None:
        """Hand every subject the grant ``grant_id`` still decides for back to their routine, as
        one choice: called by the route that revokes the grant, in its transaction, and by a grant
        that ran out. Who the grant decides for is read under the society's lock, so a choice
        committed meanwhile is never overwritten; a retry of this key returns the choice it
        recorded. None when the grant decides for nobody now, because a later choice already
        replaced it. A subject that is not here (everyone sent away, or a placed thing its author
        removed) is handed back all the same, so no grant that ended keeps anyone."""

        def held(rows: Sequence[Mapping[str, Any]]) -> list[str]:
            return [
                subject
                for subject, choice in sorted(self._current(role, rows).items())
                if choice["decider"]["kind"] == "external"
                and choice["decider"]["grant_id"] == str(grant_id)
            ]

        return self._record(
            version_id,
            role,
            request_id=request_id,
            subjects=held,
            asked={"kind": "routine"},
            described=lambda: {"kind": "routine"},
            chosen_by=chosen_by,
            contract=contract,
            handing_back=True,
        )

    def _checked(
        self,
        society: Mapping[str, Any],
        rows: Sequence[Mapping[str, Any]],
        role: DecisionRole,
        named: Sequence[str],
        described: Any,
        *,
        granted_away: bool,
        handing_back: bool,
    ) -> dict[str, Any]:
        """The decider a choice naming ``named`` records, as ``described()`` checks it, or the
        refusal: every check of a choice but the bound on the subjects models run
        (:meth:`_run_after`), in the order a choice is refused by. Reads only what it is handed, so
        recording a choice (:meth:`_record`, under the society's lock) and previewing one
        (:meth:`preview_choice`, with no lock) are refused by the same code for the same reason."""
        chosen = sorted(set(named))
        if not role.hosted_by(society["engine_version"]):
            raise ModelChoiceRefused("engine_takes_no_model_choice")
        if len(chosen) != len(named):
            raise ModelChoiceRefused("person_named_twice")
        record = described()
        present = set(role.adapter.subjects(society["state"]))
        # Who is here: everyone, but in a hand-back, whose subjects may have been sent away.
        here = [subject for subject in chosen if subject in present]
        if not chosen or (len(here) != len(chosen) and not handing_back):
            raise ModelChoiceRefused("person_not_in_this_world")
        if any(decided_from_outside(society["state"], subject) for subject in here):
            raise ModelChoiceRefused("decided_from_outside")
        if record["kind"] == "external" and any(
            _came_from_outside(society["state"], subject) for subject in chosen
        ):
            # A visitor is never handed to another outside program: its own program, or the
            # world, decides for it.
            raise ModelChoiceRefused("decided_from_outside")
        held = self._current(role, rows)
        if any(is_played(held.get(subject, {}).get("decider", {})) for subject in chosen):
            # While a person plays a being, only giving it back names it.
            raise ModelChoiceRefused("being_played")
        if granted_away and any(
            held.get(subject, {}).get("decider", {}).get("kind") == "external" for subject in chosen
        ):
            raise ModelChoiceRefused("decided_from_outside")
        state = society["state"]
        if not all(kind_allows(state, subject, record["kind"]) for subject in here):
            raise ModelChoiceRefused("decider_not_allowed")
        if record["kind"] == "external" and not all(
            kind_allows(state, subject, "routine") for subject in chosen
        ):
            # A grant ends, and whoever it decided for goes back to their routine then, so a
            # thing whose kind takes no routine is never handed to an outside program.
            raise ModelChoiceRefused("decider_not_allowed")
        if record["kind"] != "routine":
            occupied: dict[tuple[str, str], bool] = {}
            for row in rows:
                document = row["document"]
                other = decision_roles().for_choice(document["profile"])
                if other is None:
                    raise ValueError("a model choice names no registered role")
                if other.key == role.key:
                    continue
                for subject in document[other.choice_subjects]:
                    if subject in chosen:
                        occupied[(other.key, subject)] = decider_of(document)["kind"] != "routine"
            if any(occupied.values()):
                raise ModelChoiceRefused("subject_chosen_under_another_role")
        return record

    def _run_after(
        self,
        society: Mapping[str, Any],
        rows: Sequence[Mapping[str, Any]],
        role: DecisionRole,
        chosen: Sequence[str],
        record: Mapping[str, Any] | None,
        contract: DecisionContract,
    ) -> tuple[int, int]:
        """How many subjects models would run once ``chosen`` are decided for by ``record`` (as
        they are now with none), and the contract's bound on them."""
        after = self._current(role, rows)
        if record is not None:
            for subject in chosen:
                after[subject] = {"decider": record}
        counted = _counted(society, role, after)
        run = sum(1 for subject in counted if after[subject]["decider"]["kind"] == "model")
        return run, contract.value(role.subjects_bound)

    def preview_choice(
        self,
        version_id: uuid.UUID,
        role: DecisionRole,
        *,
        subjects: Sequence[str],
        model: Mapping[str, str] | None,
        manifest: Manifest,
        contract: DecisionContract,
    ) -> dict[str, Any]:
        """What :meth:`record_choice` would meet for ``subjects`` and ``model`` now, read with no
        lock and recording nothing, so a plan offers a choice only where the route would take it.

        ``code`` is why the whole choice is refused (the engine takes none, the model is not
        offered, or it would run more subjects by models than the contract allows), else None.
        ``subjects`` are those a choice may name; ``left_out`` holds every other one under the
        code a choice naming it alone is refused by. ``run_now`` and ``run_after`` count the
        subjects models run now and once ``subjects`` are chosen for, against ``bound``;
        ``choice_seq`` is the society's newest choice, so a caller's key can follow it. The world
        may move before the choice is sent: the route stays the authority."""
        society = self._society(version_id, lock=False)
        rows = self._rows(society["society_id"])
        newest = rows[-1]["choice_seq"] if rows else 0
        run_now, bound = self._run_after(society, rows, role, (), None, contract)
        read: dict[str, Any] = {
            "code": None,
            "subjects": [],
            "left_out": {},
            "run_now": run_now,
            "run_after": run_now,
            "bound": bound,
            "choice_seq": newest,
        }
        named = list(dict.fromkeys(subjects))
        if not role.hosted_by(society["engine_version"]):
            return {**read, "code": "engine_takes_no_model_choice"}
        try:
            record = of_model(_model_record(role, manifest, self._asked(version_id, role), model))
        except ModelChoiceRefused as refused:
            return {**read, "code": refused.code}
        taken: list[str] = []
        left: dict[str, list[str]] = {}
        for subject in named:
            try:
                self._checked(
                    society,
                    rows,
                    role,
                    [subject],
                    lambda: record,
                    granted_away=True,
                    handing_back=False,
                )
            except ModelChoiceRefused as refused:
                left.setdefault(refused.code, []).append(subject)
            else:
                taken.append(subject)
        run_after, _bound = self._run_after(society, rows, role, taken, record, contract)
        return {
            **read,
            "code": "too_many_model_people" if run_after > bound else None,
            "subjects": taken,
            "left_out": left,
            "run_after": run_after,
        }

    def _record(
        self,
        version_id: uuid.UUID,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        subjects: Sequence[str] | Callable[[Sequence[Mapping[str, Any]]], Sequence[str]],
        asked: Mapping[str, Any] | None,
        described: Any,
        chosen_by: uuid.UUID,
        contract: DecisionContract,
        granted_away: bool = False,
        handing_back: bool = False,
        fields: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Record one choice of ``role`` naming ``asked``, checked as ``described()`` checks it,
        or return the one this idempotency key already recorded. ``subjects`` may be read from
        the society's choices under its lock instead: then a key already recorded is answered
        whoever it named, and None is returned, recording nothing, when they name nobody. With
        ``granted_away``, the owner's own choice, a subject a grant decides for now is refused
        (``decided_from_outside``): only ending the grant hands it back. With ``handing_back``,
        an ended grant's hand-back to the routine, a subject that is not here is accepted and
        skips the checks that read it from the state; one that is here keeps every check."""
        if handing_back and dict(asked or {}) != {"kind": "routine"}:
            raise ValueError("only a hand-back to the routine names somebody who is not here")
        with self.connection.transaction():
            society = self._society(version_id, lock=True)
            rows = self._rows(society["society_id"])
            derived = callable(subjects)
            existing = next((row for row in rows if row["request_id"] == request_id), None)
            if existing is not None:
                document = existing["document"]
                if (
                    not role.reads_choice(document["profile"])
                    or (
                        not derived
                        and (
                            document[role.choice_subjects] != sorted(set(subjects))
                            or len(set(subjects)) != len(subjects)
                        )
                    )
                    or asked is None
                    or decider_of(document) != dict(asked)
                    or document["chosen_by"] != str(chosen_by)
                ):
                    raise ModelChoiceRefused("choice_key_reused")
                return _view(document, existing["recorded_at"])
            named = list(subjects(rows) if callable(subjects) else subjects)
            if derived and not named:
                return None
            chosen = sorted(set(named))
            record = self._checked(
                society,
                rows,
                role,
                named,
                described,
                granted_away=granted_away,
                handing_back=handing_back,
            )
            run, bound = self._run_after(society, rows, role, chosen, record, contract)
            if run > bound:
                raise ModelChoiceRefused("too_many_model_people")
            sequence = (rows[-1]["choice_seq"] if rows else 0) + 1
            document: dict[str, Any] = {
                "profile": role.choice_profile,
                "choice_seq": sequence,
                "request_id": str(request_id),
                "society_id": str(society["society_id"]),
                role.choice_subjects: chosen,
                "decider": record,
                "contract": contract.binding(),
                "chosen_by": str(chosen_by),
                **(fields or {}),
            }
            document["document_sha256"] = input_sha256(document)
            return self._insert(society["society_id"], sequence, request_id, document, chosen_by)
