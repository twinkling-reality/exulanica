"""A stored point map stops being readable the moment the depth right that made it ends.

Migration 0073 rechecks a model right at the instant of every read, which is enough while the act
is transient: the bytes go, an answer comes back, nothing is kept. Depth keeps something. A point
map is a three-dimensional reading of the room the photograph was taken in, and before migration
0092 withdrawing the depth right stopped the next inference and left every existing map servable,
so a person could read "stopped" and their living room stayed in the world.

These tests hold the binding that closes that: written inside the publication transaction, refused
if the right went away while the model was running, and read by ``asset_point_allows``, which is
the one gate every point-map read passes. The control throughout is a point map with no binding:
it must be completely unaffected, or the clause is refusing maps for reasons of its own.
"""

import datetime as dt
import uuid

import pytest
from exulanica.ingest.model_rights import LOCAL_PROCESS, ModelHandoff, withdraw_model_right
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.privacy import authorize_synthetic_capture, record_synthetic_exemption
from exulanica.ingest.repository import IngestRepository

from conftest import photo_bytes
from test_personal_model_right import (
    ACCOUNT,
    DEPTH_DOUBLE,
    CountingDepth,
    Personal,
    admit_personal,
    grant,
)
from test_personal_model_right import (
    personal as personal,
)
from test_personal_model_right import (
    store as store,
)


def allows(repository: IngestRepository, artifact_id: uuid.UUID) -> bool:
    return repository.connection.execute(
        "select asset_point_allows(%s,%s,clock_timestamp()) as allowed",
        (repository.workspace_id, artifact_id),
    ).fetchone()["allowed"]


def point_maps(repository: IngestRepository) -> list[uuid.UUID]:
    return [
        row["artifact_id"]
        for row in repository.connection.execute(
            "select artifact_id from artifact where kind='point_map' order by artifact_id"
        ).fetchall()
    ]


def run_depth(subject: Personal, depth: CountingDepth | None = None) -> uuid.UUID:
    """One depth pass over an eligible personal photograph, returning the point map it published."""
    before = set(point_maps(subject.repository))
    model = depth if depth is not None else CountingDepth(ModelHandoff.local(DEPTH_DOUBLE))
    outcome = PhotoIngestPipeline(
        subject.repository, subject.store, depth=model
    ).ingest_derivatives(subject.capture_id, privacy_screening_id=subject.review_id)
    assert outcome.error is None, outcome.error
    (published,) = [item for item in point_maps(subject.repository) if item not in before]
    return published


def bindings(repository: IngestRepository, artifact_id: uuid.UUID) -> list[dict]:
    return repository.connection.execute(
        "select * from point_map_model_right_sources(%s,%s)",
        (repository.workspace_id, artifact_id),
    ).fetchall()


def unbound_point_map(repository: IngestRepository, store) -> uuid.UUID:
    """A readable point map that no right permitted: a photograph that needs none.

    This is the control every test below leans on. Withdrawing somebody's depth right must not
    reach it, and a clause that knocked it out would be refusing maps for reasons of its own.
    """
    intake = PhotoIngestPipeline(repository, store).ingest_intake(
        photo_bytes(when="2026:08:27 11:00:00"), filename="synthetic.jpg"
    )
    authorization = authorize_synthetic_capture(
        repository,
        capture_id=intake.capture_id,
        actor=ACCOUNT,
        generator_manifest={"profile": "exulanica.synthetic-test-corpus/v1"},
        authorization_scope={"purpose": "point map binding test"},
    )
    exemption = record_synthetic_exemption(
        repository, authorization_id=authorization.authorization_id
    )
    before = set(point_maps(repository))
    outcome = PhotoIngestPipeline(
        repository, store, depth=CountingDepth(ModelHandoff.local(DEPTH_DOUBLE))
    ).ingest_derivatives(intake.capture_id, privacy_screening_id=exemption.screening_id)
    assert outcome.error is None, outcome.error
    (published,) = [item for item in point_maps(repository) if item not in before]
    assert bindings(repository, published) == []
    assert allows(repository, published) is True
    return published


def test_a_published_point_map_names_the_right_that_permitted_it(personal):
    right = grant(personal, DEPTH_DOUBLE, LOCAL_PROCESS)
    artifact_id = run_depth(personal)
    (binding,) = bindings(personal.repository, artifact_id)
    assert binding["right_id"] == right.right_id
    assert binding["capture_id"] == personal.capture_id
    assert binding["model_id"] == DEPTH_DOUBLE.model_id
    assert binding["model_revision"] == DEPTH_DOUBLE.revision
    assert binding["destination"] == LOCAL_PROCESS
    assert binding["current"] is True
    assert allows(personal.repository, artifact_id) is True


def test_withdrawing_the_right_stops_the_estimate_being_readable_at_once(personal, store):
    grant(personal, DEPTH_DOUBLE, LOCAL_PROCESS)
    artifact_id = run_depth(personal)
    control = unbound_point_map(personal.repository, store)
    assert allows(personal.repository, artifact_id) is True

    (binding,) = bindings(personal.repository, artifact_id)
    withdraw_model_right(personal.repository, right_id=binding["right_id"], withdrawn_by=ACCOUNT)

    assert allows(personal.repository, artifact_id) is False
    assert bindings(personal.repository, artifact_id)[0]["current"] is False
    # The control: the clause reaches what the withdrawal named and nothing else.
    assert allows(personal.repository, control) is True


def test_an_expired_right_stops_the_estimate_as_a_withdrawn_one_does(personal, store):
    now = personal.repository.connection.execute(
        "select clock_timestamp() as at"
    ).fetchone()["at"]
    grant(
        personal,
        DEPTH_DOUBLE,
        LOCAL_PROCESS,
        granted_at=now - dt.timedelta(minutes=10),
        valid_until=now + dt.timedelta(seconds=2),
    )
    artifact_id = run_depth(personal)
    control = unbound_point_map(personal.repository, store)
    assert allows(personal.repository, artifact_id) is True

    # The clause reads the term rather than a stored flag, so moving the evaluation instant past
    # the expiry is the same fact the wall clock would produce two seconds later.
    expired = personal.repository.connection.execute(
        "select asset_point_allows(%s,%s,clock_timestamp()+interval '1 hour') as allowed",
        (personal.repository.workspace_id, artifact_id),
    ).fetchone()["allowed"]
    assert expired is False
    assert personal.repository.connection.execute(
        "select asset_point_allows(%s,%s,clock_timestamp()+interval '1 hour') as allowed",
        (personal.repository.workspace_id, control),
    ).fetchone()["allowed"] is True


def test_a_withdrawal_while_the_model_runs_refuses_the_publication(personal, ingest_spine):
    """The person stopped it inside the window the inference took, so nothing may land."""
    grant(personal, DEPTH_DOUBLE, LOCAL_PROCESS)
    _, open_another = ingest_spine
    elsewhere = open_another()

    class WithdrawsMidRun(CountingDepth):
        def predict(self, image):
            rows = elsewhere.connection.execute(
                "select right_id from personal_model_right where capture_id=%s",
                (personal.capture_id,),
            ).fetchall()
            for row in rows:
                withdraw_model_right(elsewhere, right_id=row["right_id"], withdrawn_by=ACCOUNT)
            return super().predict(image)

    depth = WithdrawsMidRun(ModelHandoff.local(DEPTH_DOUBLE))
    outcome = PhotoIngestPipeline(
        personal.repository, personal.store, depth=depth
    ).ingest_derivatives(personal.capture_id, privacy_screening_id=personal.review_id)

    assert depth.calls == 1, "the control: the model did run, so this is a publication refusal"
    assert outcome.error is not None
    assert "no longer current" in outcome.error
    assert point_maps(personal.repository) == []
    assert personal.repository.connection.execute(
        "select artifact_id from point_map_model_right"
    ).fetchall() == []


def test_a_binding_never_names_another_photograph_or_another_artifact(personal, store):
    right = grant(personal, DEPTH_DOUBLE, LOCAL_PROCESS)
    artifact_id = run_depth(personal)
    other = admit_personal(
        personal.repository, store, photo_bytes(when="2026:08:27 12:00:00"), "other.jpg"
    )
    connection = personal.repository.connection
    for capture_id, artifact, message in [
        (other.capture_id, artifact_id, "same photograph"),
        # The trigger runs before the foreign key, so an id naming nothing is refused as not
        # being a point map rather than as a missing row. Either is a refusal; this is which.
        (personal.capture_id, uuid.uuid4(), "only a point map"),
    ]:
        with pytest.raises(Exception) as refused, connection.transaction():
            connection.execute(
                "insert into point_map_model_right (workspace_id,artifact_id,capture_id,"
                "right_id,bound_at) values (%s,%s,%s,%s,clock_timestamp())",
                (personal.repository.workspace_id, artifact, capture_id, right.right_id),
            )
        assert message in str(refused.value)


def test_a_binding_is_never_rewritten_or_removed(personal):
    grant(personal, DEPTH_DOUBLE, LOCAL_PROCESS)
    artifact_id = run_depth(personal)
    connection = personal.repository.connection
    for statement in (
        "update point_map_model_right set bound_at=clock_timestamp()",
        "delete from point_map_model_right",
    ):
        with pytest.raises(Exception) as refused, connection.transaction():
            connection.execute(statement)
        assert "append" in str(refused.value).lower() or "immutable" in str(refused.value).lower()
    assert len(bindings(personal.repository, artifact_id)) == 1


# -- the route that serves the bytes ---------------------------------------------------------------


def _app(repository, store, spine_schema, monkeypatch):
    """The real application in front of this workspace, built as test_geometry_delivery.py does."""
    import json

    from exulanica.api.app import create_app
    from exulanica.api.authorisation import load_token_directory
    from exulanica.api.services import Services
    from fastapi.testclient import TestClient

    from tests_support_api import EVERY_PERMISSION, scratch_database

    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                _TOKEN: {
                    "workspace_id": str(repository.workspace_id),
                    "actor": str(ACCOUNT),
                    "permissions": EVERY_PERMISSION,
                }
            }
        ),
    )
    _psycopg, scratch = spine_schema
    database = scratch_database(scratch)
    return TestClient(
        create_app(
            Services(
                database=database,
                readonly_database=database,
                store=store,
                tokens=load_token_directory(),
                executor_shares_the_write_role=True,
                model_client=None,
            ),
            verify=False,
        )
    )


_TOKEN = "point-map-binding-owner-token-that-is-long-enough"


def test_the_geometry_route_stops_serving_a_stopped_estimate(personal, spine_schema, monkeypatch):
    grant(personal, DEPTH_DOUBLE, LOCAL_PROCESS)
    artifact_id = run_depth(personal)
    control = unbound_point_map(personal.repository, personal.store)

    with _app(personal.repository, personal.store, spine_schema, monkeypatch) as client:
        headers = {"Authorization": f"Bearer {_TOKEN}"}
        served = client.get(f"/geometry/{artifact_id}", headers=headers)
        assert served.status_code == 200, served.text
        listed = client.get("/geometry", headers=headers)
        assert listed.status_code == 200, listed.text
        assert artifact_id in {uuid.UUID(row["artifact_id"]) for row in listed.json()}

        (binding,) = bindings(personal.repository, artifact_id)
        withdraw_model_right(
            personal.repository, right_id=binding["right_id"], withdrawn_by=ACCOUNT
        )

        stopped = client.get(f"/geometry/{artifact_id}", headers=headers)
        assert stopped.status_code == 404, stopped.text
        assert stopped.json()["code"] == "unknown_reference"
        remaining = client.get("/geometry", headers=headers).json()
        assert artifact_id not in {uuid.UUID(row["artifact_id"]) for row in remaining}
        # The control: the same route, the same reader, the unbound map still served.
        assert control in {uuid.UUID(row["artifact_id"]) for row in remaining}
        assert client.get(f"/geometry/{control}", headers=headers).status_code == 200
