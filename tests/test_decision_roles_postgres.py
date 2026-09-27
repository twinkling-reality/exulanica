"""A decision role's documents in the deployed database: admitted by their shape, read by the
registry.

Migration 0117 admits every request, receipt and model choice whose profile has a decision role's
shape, so a role declared as data needs no migration of its own; which role a profile names, and
whether that role is registered, stays the application's to say. The application connects as a
provisioned runtime role over a saved world whose society's engine hosts roles. What is shown:

*   a request, a receipt and a model choice of a role no product registry holds, a junction signal,
    are admitted when their profiles have a role's shape;
*   a malformed profile, and one of no role's shape, are refused by the constraints 0117 names, and
    a choice names its subjects under one field, exactly;
*   the social society's own profile is refused in a society whose engine hosts roles;
*   the application stays the authority: a stored request of a profile no registered role writes
    is refused by name when it is read back, while the person's reads back as it was reserved.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
import pytest
from exulanica.selection.validation import Session
from exulanica.world.role_decisions import seal
from exulanica.world.society import society_state_sha256
from exulanica.world.society_decision_contract import person_role
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_repository import SocietyRepository
from psycopg.types.json import Jsonb

import test_society_stay_requests_api as stays

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres

#: The junction signal's profiles, as its test registry states them: a role's shape, and no
#: product role's.
REQUEST = "exulanica.junction-signal-decision-request/v1"
RECEIPT = "exulanica.junction-signal-decision/v1"
CHOICE = "exulanica.junction-signal-model-choice/v1"


def _held(connection, world) -> dict[str, Any]:
    society = connection.execute(
        "select society_id,version_id,current_tick,state,state_sha256 from world_society "
        "where workspace_id=%s and world_id=%s",
        (world["workspace"], world["binding"].world_id),
    ).fetchone()
    latest = connection.execute(
        "select input_seq,document_sha256 from world_society_input where workspace_id=%s "
        "and society_id=%s order by input_seq desc limit 1",
        (world["workspace"], society["society_id"]),
    ).fetchone()
    return {**society, "input_seq": latest["input_seq"], "input_sha256": latest["document_sha256"]}


def _request(held: dict[str, Any], profile: str, subject: str) -> dict[str, Any]:
    return seal(
        {
            "profile": profile,
            "request_id": str(uuid.uuid4()),
            "subject_id": subject,
            "branch_id": str(held["version_id"]),
            "base_tick": held["current_tick"],
            "base_state_sha256": held["state_sha256"],
            "input_seq": held["input_seq"],
            "input_sha256": held["input_sha256"],
            "context": {},
            "context_sha256": society_state_sha256({}),
            "provider_config": None,
        }
    )


def _reserve(connection, world, held, document) -> None:
    connection.execute(
        "insert into world_society_decision_request(workspace_id,society_id,request_id,"
        "subject_id,base_tick,input_seq,document,document_sha256) values(%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            world["workspace"],
            held["society_id"],
            document["request_id"],
            document["subject_id"],
            document["base_tick"],
            document["input_seq"],
            Jsonb(document),
            document["document_sha256"],
        ),
    )


def _receipt(request: dict[str, Any], profile: str) -> dict[str, Any]:
    return seal(
        {
            "profile": profile,
            "decision_seq": 1,
            "request_id": request["request_id"],
            "request_sha256": request["document_sha256"],
            **{
                key: request[key]
                for key in (
                    "subject_id",
                    "branch_id",
                    "base_tick",
                    "base_state_sha256",
                    "input_seq",
                    "input_sha256",
                    "context_sha256",
                )
            },
            "status": "unavailable",
            "reason": "model_timed_out",
            "proposal": None,
            "provider": None,
        }
    )


def _record(connection, world, held, document) -> None:
    connection.execute(
        "insert into world_society_decision(workspace_id,society_id,decision_seq,request_id,"
        "document,document_sha256) values(%s,%s,%s,%s,%s,%s)",
        (
            world["workspace"],
            held["society_id"],
            document["decision_seq"],
            document["request_id"],
            Jsonb(document),
            document["document_sha256"],
        ),
    )


def _choose(connection, world, held, profile: str, subjects: dict[str, Any]) -> None:
    request_id = uuid.uuid4()
    document: dict[str, Any] = {
        "profile": profile,
        "choice_seq": 1,
        "request_id": str(request_id),
        "society_id": str(held["society_id"]),
        **subjects,
        "model": None,
        "contract": {},
        "chosen_by": str(world["session"].actor),
    }
    document["document_sha256"] = society_state_sha256(document)
    connection.execute(
        "insert into world_society_model_choice(workspace_id,world_id,society_id,choice_seq,"
        "request_id,document,document_sha256,chosen_by) values(%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            world["workspace"],
            world["binding"].world_id,
            held["society_id"],
            1,
            request_id,
            Jsonb(document),
            document["document_sha256"],
            world["session"].actor,
        ),
    )


def _refused(connection, operation) -> psycopg.errors.CheckViolation:
    with pytest.raises(psycopg.errors.CheckViolation) as refused, connection.transaction():
        operation()
    return refused.value


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_role_s_documents_are_admitted_by_their_shape_and_nothing_else_is(app):
    world, client = app
    services = client.app.state.services
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    with services.database.session(world["workspace"]) as connection:
        role = connection.execute(
            "select rolsuper,rolbypassrls from pg_roles where rolname=current_user"
        ).fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": False}, role
        held = _held(connection, world)
        # A malformed profile and one of no role's shape are refused by 0117's own constraint.
        for profile in ("exulanica.junction signal/v1", "exulanica.junction-signal-plan/v1"):
            refused = _refused(
                connection,
                lambda profile=profile: _reserve(
                    connection, world, held, _request(held, profile, people[1])
                ),
            )
            assert refused.diag.constraint_name == "world_society_decision_request_profile_check"
        # The social society's profile belongs to its own engine, never to one that hosts roles.
        refused = _refused(
            connection,
            lambda: _reserve(
                connection,
                world,
                held,
                _request(held, "exulanica.society-decision-request/v1", people[1]),
            ),
        )
        assert "records the decision requests of its own engine" in str(refused)
        # The positive control: a junction signal's request and receipt are admitted by shape.
        request = _request(held, REQUEST, people[0])
        with connection.transaction():
            _reserve(connection, world, held, request)
        malformed = {**_receipt(request, "exulanica.junction signal/v1")}
        refused = _refused(connection, lambda: _record(connection, world, held, malformed))
        assert refused.diag.constraint_name == "world_society_decision_profile_check"
        with connection.transaction():
            _record(connection, world, held, _receipt(request, RECEIPT))
        # A choice's profile and its one field of subjects.
        for profile, subjects, constraint in (
            ("exulanica.junction signal/v1", {"subjects": [people[0]]}, "profile_check"),
            (CHOICE, {}, "names_its_subjects"),
            (CHOICE, {"subjects": [people[0]], "people": [people[0]]}, "names_its_subjects"),
        ):
            refused = _refused(
                connection,
                lambda profile=profile, subjects=subjects: _choose(
                    connection, world, held, profile, subjects
                ),
            )
            assert refused.diag.constraint_name == f"world_society_model_choice_{constraint}"
        with connection.transaction():
            _choose(connection, world, held, CHOICE, {"subjects": [people[0]]})


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_stored_request_of_no_registered_role_is_refused_when_read(app):
    world, client = app
    services = client.app.state.services
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    session = Session(workspace_id=world["workspace"], actor=world["session"].actor)
    with services.database.session(world["workspace"]) as connection:
        society = SocietyRepository(
            connection,
            world["workspace"],
            world_id=world["binding"].world_id,
            input_authorizer=lambda doc: services.society_runtime.authorize(
                connection, session, doc
            ),
        )
        decisions = SocietyDecisionRepository(society)
        held = _held(connection, world)
        role = person_role()
        contract = role.contract()
        # The positive control: the person's request, reserved by the registry's role, reads back.
        with connection.transaction():
            reserved, fresh = decisions.prepare_role(
                role,
                world["binding"].version_id,
                request_id=uuid.uuid4(),
                subject_id=uuid.UUID(people[0]),
                base_tick=held["current_tick"],
                base_state_sha256=held["state_sha256"],
                contract=contract,
                provider_config={
                    "provider": "example_provider",
                    "model_id": "example/model",
                    "mechanism": "tool_call",
                    "choice_seq": 1,
                    "manifest_sha256": "a" * 64,
                    "prompt_version": role.prompt_version,
                    "contract": contract.binding(),
                    "deadline_ms": contract.value("decision_deadline_ms"),
                },
            )
        assert fresh and reserved["request"] is not None
        person = uuid.UUID(reserved["request"]["request_id"])
        with connection.transaction():
            assert (
                decisions.read(world["binding"].version_id, person)["request"]
                == (reserved["request"])
            )
        # A junction signal's request is admitted by the database and refused by the registry.
        stranger = _request(held, REQUEST, people[1])
        with connection.transaction():
            _reserve(connection, world, held, stranger)
        with (
            pytest.raises(ValueError, match="invalid recorded decision request"),
            connection.transaction(),
        ):
            decisions.read(world["binding"].version_id, uuid.UUID(stranger["request_id"]))
