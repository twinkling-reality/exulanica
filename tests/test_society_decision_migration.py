"""Database guards for reservations, immutable results and exact replay consumption."""

import uuid
from copy import deepcopy

import psycopg
import pytest
from exulanica.world.society import society_state_sha256
from exulanica.world.society_planner import initial_purposeful_society
from psycopg.types.json import Jsonb

import test_society_runtime as helpers

runtime_world = helpers.runtime_world

pytestmark = pytest.mark.postgres


def seal(document):
    document["document_sha256"] = society_state_sha256(
        {k: v for k, v in document.items() if k != "document_sha256"}
    )
    return document


@pytest.fixture
def social_db(runtime_world):
    w = runtime_world
    connection = w["connection"]
    source = helpers.initial(w)
    society_id = uuid.uuid4()
    state = initial_purposeful_society(society_id, "7a" * 32, source)
    state["profile"] = "exulanica-society/v3"
    scope = (w["workspace"], society_id)
    connection.execute(
        "insert into world_society(workspace_id,society_id,world_id,version_id,place_id,"
        "region_id,engine_version,seed,population_size,tick_seconds,state,state_sha256,created_by) "
        "values(%s,%s,%s,%s,%s,%s,%s,%s,128,60,%s,%s,%s)",
        (
            *scope,
            w["version"].world_id,
            w["version"].version_id,
            w["binding"].place_id,
            w["binding"].region_id,
            state["profile"],
            "7a" * 32,
            Jsonb(state),
            society_state_sha256(state),
            w["session"].actor,
        ),
    )
    connection.execute(
        "insert into world_society_input(workspace_id,society_id,input_seq,"
        "document,document_sha256) "
        "values(%s,%s,1,%s,%s)",
        (*scope, Jsonb(source), source["document_sha256"]),
    )
    request = seal(
        dict(
            profile="exulanica.society-decision-request/v1",
            request_id=str(uuid.uuid4()),
            subject_id=state["inhabitants"][0]["id"],
            branch_id=str(w["version"].version_id),
            base_tick=0,
            base_state_sha256=society_state_sha256(state),
            input_seq=1,
            input_sha256=source["document_sha256"],
            context={},
            context_sha256=society_state_sha256({}),
            provider_config=None,
        )
    )
    return connection, scope, request


def reserve(db, document):
    connection, scope, _ = db
    connection.execute(
        "insert into world_society_decision_request(workspace_id,society_id,request_id,"
        "subject_id,base_tick,input_seq,document,document_sha256) values(%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            *scope,
            document["request_id"],
            document["subject_id"],
            document["base_tick"],
            document["input_seq"],
            Jsonb(document),
            document["document_sha256"],
        ),
    )


def receipt(request, *, seq=1, status="unavailable"):
    return seal(
        {
            **{
                k: request[k]
                for k in (
                    "request_id",
                    "subject_id",
                    "branch_id",
                    "base_tick",
                    "base_state_sha256",
                    "input_seq",
                    "input_sha256",
                    "context_sha256",
                )
            },
            "profile": "exulanica.society-decision/v1",
            "decision_seq": seq,
            "request_sha256": request["document_sha256"],
            "status": status,
            "reason": "Offline migration test",
            "proposal": None,
            "provider": None,
        }
    )


def record(db, document):
    connection, scope, _ = db
    connection.execute(
        "insert into world_society_decision(workspace_id,society_id,decision_seq,request_id,"
        "document,document_sha256) values(%s,%s,%s,%s,%s,%s)",
        (
            *scope,
            document["decision_seq"],
            document["request_id"],
            Jsonb(document),
            document["document_sha256"],
        ),
    )


def transition(db, tick=1, previous=None):
    connection, scope, request = db
    connection.execute(
        "insert into world_society_transition(workspace_id,society_id,tick,from_input_seq,"
        "to_input_seq,previous_state_sha256,state_sha256,event_ids,events_sha256) "
        "values(%s,%s,%s,1,1,%s,%s,'[]',%s)",
        (*scope, tick, previous or request["base_state_sha256"], "f0" * 32, "a0" * 32),
    )


def consume(db, *, seq=1, tick=1, disposition="unavailable"):
    connection, scope, _ = db
    connection.execute(
        "insert into world_society_transition_decision(workspace_id,society_id,tick,"
        "decision_seq,disposition) values(%s,%s,%s,%s,%s)",
        (*scope, tick, seq, disposition),
    )


def rejected(connection, operation):
    with pytest.raises(psycopg.IntegrityError), connection.transaction():
        operation()


def test_request_identity_idempotency_and_current_state(social_db):
    connection, _, request = social_db
    wrong = seal({**request, "branch_id": str(uuid.uuid4())})
    rejected(connection, lambda: reserve(social_db, wrong))
    wrong = seal({**request, "base_state_sha256": "ff" * 32})
    rejected(connection, lambda: reserve(social_db, wrong))
    reserve(social_db, request)
    rejected(connection, lambda: reserve(social_db, request))
    retry = seal({**request, "request_id": str(uuid.uuid4())})
    rejected(connection, lambda: reserve(social_db, retry))


def test_receipt_scope_digest_binding_sequence_and_immutability(social_db):
    connection, scope, request = social_db
    reserve(social_db, request)
    result = receipt(request)
    rejected(connection, lambda: record(social_db, seal({**result, "context_sha256": "ab" * 32})))
    rejected(connection, lambda: record(social_db, receipt(request, seq=2)))
    foreign = (connection, (scope[0], uuid.uuid4()), request)
    rejected(connection, lambda: record(foreign, result))
    record(social_db, result)
    for table in ("world_society_decision_request", "world_society_decision"):
        rejected(connection, lambda table=table: connection.execute(f"delete from {table}"))


def test_stale_result_cannot_be_accepted(social_db):
    connection, scope, request = social_db
    reserve(social_db, request)
    connection.execute(
        "update world_society set current_tick=1,state_sha256=%s "
        "where workspace_id=%s and society_id=%s",
        ("fe" * 32, *scope),
    )
    rejected(connection, lambda: record(social_db, receipt(request, status="accepted")))
    record(social_db, receipt(request, status="stale"))


def test_transition_consumes_exact_receipt_once_with_truthful_disposition(social_db):
    connection, _, request = social_db
    reserve(social_db, request)
    record(social_db, receipt(request))
    rejected(connection, lambda: consume(social_db))  # no transition
    transition(social_db)
    rejected(connection, lambda: consume(social_db, disposition="applied"))
    rejected(connection, lambda: consume(social_db, disposition="rejected"))
    consume(social_db)
    rejected(connection, lambda: consume(social_db))
    rejected(
        connection, lambda: connection.execute("delete from world_society_transition_decision")
    )


def test_accepted_receipt_cannot_apply_to_wrong_transition(social_db):
    connection, _, request = social_db
    reserve(social_db, request)
    result = receipt(request, status="accepted")
    result["proposal"] = {"kind": "wait", "target_id": None}
    record(social_db, seal(result))
    transition(social_db, previous="ff" * 32)
    rejected(connection, lambda: consume(social_db, disposition="applied"))
    consume(social_db, disposition="stale")


def test_receipts_are_processed_as_a_contiguous_prefix(social_db):
    connection, _, request = social_db
    second = deepcopy(request)
    second.update(request_id=str(uuid.uuid4()), subject_id=str(uuid.uuid4()))
    seal(second)
    reserve(social_db, request)
    reserve(social_db, second)
    record(social_db, receipt(request))
    record(social_db, receipt(second, seq=2))
    transition(social_db)
    rejected(connection, lambda: consume(social_db, seq=2))
    consume(social_db)
    consume(social_db, seq=2)
