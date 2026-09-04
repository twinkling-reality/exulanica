"""The HTTP surface, including the authorisation sweep that is generated from the router.

``evaluation-methodology.md`` M10 specifies how the authorisation half is tested, and the shape
of the requirement is unusual enough to quote:

    "**DECISION: table-driven, generated from the router, so a new route without a test fails
    CI.** User U1 owns the corpus; U2 owns nothing. For every read path, assert U2 receives a
    not-found response: API routes, citation deep links, share links, graph API, query API, and
    direct object storage URLs. **404, never 403**, so the surface is not an existence oracle.
    Nonexistent and foreign IDs return the identical code."

So the sweep below does not enumerate routes by hand. It walks ``app.routes``, and a route that
is neither exercised nor explicitly listed as public fails the test. Adding an endpoint without
thinking about who may call it is not possible here; the suite goes red.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.routes import routable_paths
from exulanica.api.services import Services
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.evidence.blob import BlobId
from exulanica.identity import IdentityRepository, name_occurrence
from exulanica.ingest.batch import IntakeBatch
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.store.local import LocalContentAddressedStore
from fastapi.testclient import TestClient

from conftest import DEFAULT_PAYLOAD, CountingVisionModel, write_photo, write_point_map

#: Routes that are deliberately unauthenticated, with the reason each one is.
PUBLIC_ROUTES: dict[str, str] = {
    "/healthz": "a liveness probe that needed a credential would go red when it rotated",
    "/readyz": "the same, and it reports no workspace content",
    "/openapi.json": "the schema of the API, which is not data",
    "/docs": "the schema of the API, which is not data",
    "/docs/oauth2-redirect": "part of the docs page",
    "/redoc": "the schema of the API, which is not data",
}

#: A request body for every authenticated route, so the sweep can actually call it. A route
#: missing from here and from PUBLIC_ROUTES fails `test_every_route_is_covered_by_this_file`.
ROUTE_PROBES: dict[tuple[str, str], dict] = {
    ("GET", "/graph"): {},
    ("GET", "/geometry"): {},
    ("GET", "/geometry/{artifact_id}"): {},
    ("GET", "/selection/catalogue"): {},
    ("POST", "/selection"): {"json": {"intent": "captures"}},
    ("POST", "/selection/packet"): {"json": {"intent": "captures"}},
    ("POST", "/selection/plan"): {"json": {"question": "where was I?"}},
    ("POST", "/selection/ask"): {"json": {"question": "where was I?"}},
    ("GET", "/evidence"): {"params": {"uri": "exulanica://blob/x/img#t=0,1"}},
    ("GET", "/evidence/{span_id}"): {},
    ("GET", "/evidence/{span_id}/region"): {},
    ("GET", "/identity/events"): {},
    ("GET", "/operations/derivative-jobs"): {},
    ("GET", "/operations/derivative-jobs/{job_id}/events"): {},
    ("GET", "/operations/reconstruction-scenes"): {},
    ("GET", "/operations/reconstruction-scenes/{job_id}"): {},
    ("POST", "/operations/reconstruction-scenes/{job_id}/retry"): {},
    ("GET", "/world/styles/catalog"): {},
    ("GET", "/world/styles/current"): {},
    ("GET", "/world/styles/versions"): {},
    ("GET", "/world/styles/proposals/{proposal_id}"): {},
    ("GET", "/world/interactions/catalog"): {},
    ("GET", "/world/interactions/current"): {},
    ("GET", "/world/interactions/versions"): {},
    ("GET", "/world/interactions/proposals/{proposal_id}"): {},
    ("GET", "/world/interactions/recommendations"): {},
    ("GET", "/world/source-media"): {},
    ("GET", "/world/source-media/{source_id}"): {},
    ("DELETE", "/world/styles/previews/{preview_id}"): {},
    ("POST", "/world/styles/previews"): {
        "json": {
            "proposal_id": str(uuid.uuid4()),
            "origin": "user",
            "scope": {"kind": "global"},
            "base_style_version_id": str(uuid.uuid4()),
            "base_topology_digest": "probe-topology",
            "profile": {"profile_id": "origin-landscape", "profile_version": 1},
        }
    },
    ("POST", "/world/styles/previews/{preview_id}/apply"): {
        "json": {
            "base_style_version_id": str(uuid.uuid4()),
            "base_topology_digest": "probe-topology",
        }
    },
    ("POST", "/world/styles/rollback"): {
        "json": {
            "target_version_id": str(uuid.uuid4()),
            "base_style_version_id": str(uuid.uuid4()),
            "base_topology_digest": "probe-topology",
            "origin": "user",
        }
    },
    ("DELETE", "/world/interactions/previews/{preview_id}"): {},
    ("POST", "/world/interactions/previews"): {
        "json": {
            "proposal_id": str(uuid.uuid4()),
            "origin": "settings",
            "origin_reference": "probe-panel",
            "base_policy_version_id": None,
            "base_structure_snapshot_id": None,
            "base_topology_sha256": None,
            "capability_patch": {"initiative.mode": "minimal"},
            "proposal_input": {"control": "initiative"},
            "explanation": "The user selected less initiative.",
        }
    },
    ("POST", "/world/interactions/previews/{preview_id}/apply"): {
        "json": {
            "base_policy_version_id": None,
            "base_structure_snapshot_id": None,
            "base_topology_sha256": None,
        }
    },
    ("POST", "/world/interactions/rollback"): {
        "json": {
            "target_version_id": str(uuid.uuid4()),
            "origin": "settings",
            "base_policy_version_id": str(uuid.uuid4()),
            "base_structure_snapshot_id": None,
            "base_topology_sha256": None,
        }
    },
    # The stream is opened but never read here: an anonymous or foreign caller is refused
    # before the generator starts, which is the only thing this sweep asks about. Reading it
    # as the owner is `test_formation_stream.py`, which has a batch to read.
    ("GET", "/formation"): {},
    ("GET", "/formation/{batch_id}"): {},
    # Multipart, because that is what the route takes, and a part the route refuses on its
    # name, because the sweep asks only who may reach the endpoint. What it does with a
    # photograph is `test_intake_upload.py`, which has a store and a schema to check against.
    ("POST", "/intake"): {"files": {"files": ("probe.txt", b"probe", "text/plain")}},
    ("POST", "/identity/rename"): {"json": {"entity_id": str(uuid.uuid4()), "display_name": "X"}},
    ("POST", "/identity/name"): {"json": {"occurrence_id": str(uuid.uuid4()), "display_name": "X"}},
    ("POST", "/identity/confirm"): {
        "json": {"occurrence_id": str(uuid.uuid4()), "entity_id": str(uuid.uuid4())}
    },
    ("POST", "/identity/reject"): {
        "json": {"occurrence_id": str(uuid.uuid4()), "entity_id": str(uuid.uuid4())}
    },
    ("POST", "/identity/revoke"): {"json": {"occurrence_id": str(uuid.uuid4())}},
    ("POST", "/identity/merge"): {
        "json": {"sources": [str(uuid.uuid4())], "target": str(uuid.uuid4())}
    },
    ("POST", "/identity/split"): {
        "json": {"entity_id": str(uuid.uuid4()), "occurrence_ids": [str(uuid.uuid4())]}
    },
    ("POST", "/identity/undo"): {"json": {"event_id": str(uuid.uuid4())}},
}

_OWNER_TOKEN = "owner-token-that-is-long-enough-to-be-accepted"
_STRANGER_TOKEN = "stranger-token-that-is-long-enough-to-pass"


class Deployment:
    """An application over the test schema, with two tokens: one owner and one stranger."""

    def __init__(
        self,
        client,
        store,
        owner,
        stranger,
        span_id,
        occurrence_id,
        entity_id,
        batch_id,
        artifact_id,
    ) -> None:
        self.client = client
        self.store = store
        self.owner = owner
        self.stranger = stranger
        self.span_id = span_id
        self.occurrence_id = occurrence_id
        self.entity_id = entity_id
        self.batch_id = batch_id
        self.artifact_id = artifact_id

    def _request(self, token: str, method: str, path: str, **kwargs):
        headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
        return self.client.request(method, path, headers=headers, **kwargs)

    def as_owner(self, method: str, path: str, **kwargs):
        return self._request(_OWNER_TOKEN, method, path, **kwargs)

    def as_stranger(self, method: str, path: str, **kwargs):
        return self._request(_STRANGER_TOKEN, method, path, **kwargs)

    def fill(self, path: str) -> str:
        return (
            path.replace("{span_id}", str(self.span_id))
            .replace("{batch_id}", str(self.batch_id))
            .replace("{proposal_id}", str(uuid.uuid4()))
            .replace("{preview_id}", str(uuid.uuid4()))
            .replace("{source_id}", str(uuid.uuid4()))
            .replace("{job_id}", str(uuid.uuid4()))
            .replace("{artifact_id}", str(self.artifact_id))
        )


@pytest.fixture
def deployment(tmp_path, photo_dir, repository, spine_schema, monkeypatch):
    """One ingested photograph, one named person, and an app wired to that schema.

    The stranger's token names a workspace that exists as a uuid and owns nothing, which is the
    U2 of M10. It is a real session rather than an invalid credential, because the question
    being asked is what an authenticated caller sees of somebody else's library.
    """
    _psycopg, scratch = spine_schema
    store = LocalContentAddressedStore(tmp_path / "blobs")
    payload = copy.deepcopy(DEFAULT_PAYLOAD)
    payload["objects"] = [
        {
            "label": "person",
            "salience": "primary",
            "confidence": "high",
            "box": {"x": 0.5, "y": 0.1, "w": 0.2, "h": 0.6},
        }
    ]
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel(payload=payload))
    outcome = pipeline.ingest_file(write_photo(photo_dir, "a.jpg"))
    assert outcome.error is None, outcome.error

    owner = repository.workspace_id
    actor = uuid.uuid4()
    occurrence = repository.connection.execute(
        "select occurrence_id from occurrence where class = 'person' limit 1"
    ).fetchone()
    named = name_occurrence(
        IdentityRepository(repository.connection, owner),
        AssertionWriter(repository.connection, owner),
        occurrence_id=occurrence["occurrence_id"],
        display_name="Julie",
        actor=actor,
    )
    span = repository.connection.execute(
        "select span_id from evidence_span where modality = 'still_image' limit 1"
    ).fetchone()

    # A point map of the same photograph, written by hand because this deployment runs with no
    # depth model. It exists so the sweep below asks the geometry route a question it can answer
    # with a 200 for the owner, rather than a 404 that would make every authorisation assertion
    # about it pass for the wrong reason.
    blob = repository.connection.execute("select blob_sha256 from capture limit 1").fetchone()
    artifact_id, _ = write_point_map(repository, store, BlobId(bytes(blob["blob_sha256"])))

    # A real batch, so the formation route has something to be asked about. Opened and closed
    # immediately: an open batch would make the stream wait for events that are never coming.
    batch = IntakeBatch.open(repository, label="test")
    batch.declare_size(1)
    batch.close("succeeded")

    stranger = uuid.uuid4()
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                _OWNER_TOKEN: {"workspace_id": str(owner), "actor": str(actor)},
                _STRANGER_TOKEN: {"workspace_id": str(stranger), "actor": str(uuid.uuid4())},
            }
        ),
    )
    from tests_support_api import scratch_database

    database = scratch_database(scratch)
    services = Services(
        database=database,
        readonly_database=database,
        store=store,
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
    )
    app = create_app(services, verify=False)
    with TestClient(app) as client:
        yield Deployment(
            client,
            store,
            owner,
            stranger,
            span["span_id"],
            occurrence["occurrence_id"],
            named.entity_id,
            batch.batch_id,
            artifact_id,
        )


# -- the sweep ----------------------------------------------------------------------------


def test_the_route_sweep_can_actually_see_the_application(deployment):
    """The guard on the guard, and it is not decoration.

    A coverage check over an empty set of routes passes. So before asking whether every route is
    covered, this asks whether the walk found any routes at all, and whether it found ones this
    file knows exist by name. Both halves matter: a walk that returned nothing and a walk that
    returned only the documentation pages are both green under the check below, and both mean the
    authorisation sweep is testing nothing.
    """
    found = routable_paths(deployment.client.app)
    assert ("GET", "/graph") in found, found
    assert ("POST", "/identity/name") in found, found
    assert ("GET", "/evidence/{span_id}") in found, found
    # Every probed route must be reachable. A probe for a route that no longer exists is a test
    # asserting things about nothing, which is the same defect pointing the other way.
    missing = sorted(set(ROUTE_PROBES) - set(found))
    assert not missing, f"probed routes that the application does not serve: {missing}"


def test_every_route_is_covered_by_this_file(deployment):
    """The generated half. A new endpoint with no entry here fails, which is the point."""
    uncovered = [
        (method, path)
        for method, path in routable_paths(deployment.client.app)
        if path not in PUBLIC_ROUTES and (method, path) not in ROUTE_PROBES
    ]
    assert not uncovered, (
        f"these routes are neither public nor probed: {uncovered}. Add them to ROUTE_PROBES "
        "with a body, or to PUBLIC_ROUTES with the reason they need no credential."
    )


@pytest.mark.parametrize(("method", "path"), sorted(ROUTE_PROBES))
def test_every_authenticated_route_refuses_an_anonymous_caller(deployment, method, path):
    response = deployment.client.request(
        method, deployment.fill(path), **ROUTE_PROBES[(method, path)]
    )
    assert response.status_code == 401, response.text
    assert response.json()["code"] == "unauthenticated"


@pytest.mark.parametrize(("method", "path"), sorted(ROUTE_PROBES))
def test_every_authenticated_route_refuses_a_bad_token(deployment, method, path):
    response = deployment.client.request(
        method,
        deployment.fill(path),
        headers={"Authorization": "Bearer not-a-configured-token-but-long-enough"},
        **ROUTE_PROBES[(method, path)],
    )
    assert response.status_code == 401, response.text


@pytest.mark.parametrize(("method", "path"), sorted(ROUTE_PROBES))
def test_a_stranger_never_gets_a_403(deployment, method, path):
    """M10: "404, never 403, so the surface is not an existence oracle."

    A 403 on somebody else's id confirms that the id exists and belongs to someone. Every route
    that can be reached with another workspace's id must answer as though it were not there.
    """
    response = deployment.as_stranger(method, deployment.fill(path), **ROUTE_PROBES[(method, path)])
    assert response.status_code != 403, (
        f"{method} {path} returned 403 to a stranger, which confirms the resource exists"
    )


@pytest.mark.parametrize("path", ["/evidence/{span_id}", "/evidence/{span_id}/region"])
def test_a_stranger_gets_the_same_answer_for_a_real_id_and_an_invented_one(deployment, path):
    """The IDOR case, explicitly: U1's span id substituted into U2's session."""
    real = deployment.as_stranger("GET", deployment.fill(path))
    invented = deployment.as_stranger("GET", path.replace("{span_id}", str(uuid.uuid4())))
    assert real.status_code == 404
    assert real.status_code == invented.status_code
    assert real.json() == invented.json()


def test_the_owner_can_read_what_the_stranger_cannot(deployment):
    """Otherwise every test above would pass on an application that refused everybody."""
    for path in (
        "/evidence/{span_id}",
        "/evidence/{span_id}/region",
        "/geometry/{artifact_id}",
    ):
        assert deployment.as_owner("GET", deployment.fill(path)).status_code == 200


def test_a_stranger_probing_a_real_artifact_id_learns_nothing_from_it(deployment):
    """The IDOR case for geometry, and it is sharper here than for evidence.

    ``artifact_id`` is ``uuid5`` over an idempotency key that contains no workspace, so a
    stranger who ingested the same photograph holds a row under the identical id. Guessing is
    therefore free, and what stops it is the workspace scoping rather than the id being secret.
    """
    real = deployment.as_stranger("GET", deployment.fill("/geometry/{artifact_id}"))
    invented = deployment.as_stranger("GET", f"/geometry/{uuid.uuid4()}")
    assert real.status_code == 404
    assert (
        real.json()
        == invented.json()
        == {
            "code": "unknown_reference",
            "detail": "no such geometry",
        }
    )


# -- health -------------------------------------------------------------------------------


def test_liveness_touches_nothing_and_needs_no_credential(deployment):
    response = deployment.client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_reports_each_check_separately(deployment):
    response = deployment.client.get("/readyz")
    body = response.json()
    assert set(body["checks"]) == {
        "database",
        "schema",
        "object_store",
        "model_manifest",
        "derivative_worker",
    }
    # Not asked for, so not running, and READY: draining the queue in another process is a real
    # deployment. What is never ready is a worker that WAS asked for and is not there, which is
    # `test_readiness_fails_when_a_worker_was_asked_for_and_is_not_running`.
    assert body["checks"]["derivative_worker"] == {
        "ok": True,
        "running": False,
        "proves": (
            "this process was not asked to drain the derivative queue. Something else must, "
            "or POST /intake accepts uploads whose model stages never run"
        ),
    }
    # The schema check compares the recorded migrations against the files, and this application
    # runs against a harness-applied schema that records nothing, so it is expected to fail here.
    assert body["checks"]["database"]["ok"]
    assert body["checks"]["object_store"]["ok"]
    assert body["checks"]["model_manifest"]["ok"]
    # And it says what it does not prove, rather than letting a green tick imply it.
    assert "still exists in the live catalog" in body["checks"]["model_manifest"]["does_not_prove"]


def test_the_readiness_database_check_claims_only_what_a_fresh_connect_proves(deployment):
    """This string leaves the process. It used to name a component the deployment does not have.

    ``/readyz`` served "the database is reachable and the connection pool is not full" to an
    operator over HTTP, and the docstring above it said the same. There is no connection pool:
    ``orimera/db/session.py`` calls ``psycopg.connect`` per session and ``psycopg_pool`` is in
    neither ``pyproject.toml`` nor ``uv.lock``. An operator reading that acted on a check of
    something that does not exist, and missed the thing it does check, which is that the server
    had a free connection SLOT. Slots are what this deployment can run out of: one API process
    can demand one backend per in-flight request against 97 usable on a default cluster.

    The assertion is tied to the dependency rather than to a form of words on purpose. If a pool
    is ever added, this fails and asks for the sentence to be revisited, which is the right
    moment: a pool that hands back a connection without ``reset all`` carries the previous
    borrower's workspace, measured, and that is a cross-tenant read rather than a wording bug.
    """
    assert importlib.util.find_spec("psycopg_pool") is None, (
        "psycopg_pool is installed. /readyz reports a free connection slot because every "
        "connection is opened fresh; revisit that sentence, orimera/db/session.py and "
        "docs/deployment.md section 5.4 before relaxing this"
    )
    proves = deployment.client.get("/readyz").json()["checks"]["database"]["proves"]
    assert "pool" not in proves.lower(), proves
    assert "free connection slot" in proves, proves


def test_readiness_says_what_this_instance_is_running_without(deployment):
    body = deployment.client.get("/readyz").json()
    assert any("read-only" in warning for warning in body["warnings"])
    assert any("model credential" in warning for warning in body["warnings"])


# -- evidence -----------------------------------------------------------------------------


def test_a_citation_resolves_to_the_original_bytes(deployment):
    response = deployment.as_owner("GET", deployment.fill("/evidence/{span_id}"))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")
    assert response.content[:2] == b"\xff\xd8"
    assert response.headers["accept-ranges"] == "bytes"
    # Somebody's photograph must not land in a shared cache the deletion path cannot reach.
    assert "private" in response.headers["cache-control"]


def test_a_range_request_returns_that_range(deployment):
    whole = deployment.as_owner("GET", deployment.fill("/evidence/{span_id}"))
    part = deployment.as_owner(
        "GET", deployment.fill("/evidence/{span_id}"), headers={"Range": "bytes=0-9"}
    )
    assert part.status_code == 206
    assert part.content == whole.content[:10]
    assert part.headers["content-range"] == f"bytes 0-9/{len(whole.content)}"


def test_a_suffix_range_returns_the_tail(deployment):
    whole = deployment.as_owner("GET", deployment.fill("/evidence/{span_id}"))
    part = deployment.as_owner(
        "GET", deployment.fill("/evidence/{span_id}"), headers={"Range": "bytes=-5"}
    )
    assert part.status_code == 206
    assert part.content == whole.content[-5:]


@pytest.mark.parametrize("header", ["bytes=99999999-", "bytes=-", "items=0-1", "bytes=5-1"])
def test_an_unsatisfiable_range_is_refused_with_the_total(deployment, header):
    response = deployment.as_owner(
        "GET", deployment.fill("/evidence/{span_id}"), headers={"Range": header}
    )
    assert response.status_code == 416
    assert response.headers["content-range"].startswith("bytes */")


def test_a_permalink_from_another_workspace_is_not_readable(deployment):
    """A permalink names a blob by hash, so the workspace check cannot come from a row id."""
    listed = deployment.as_owner("POST", "/selection/packet", json={"intent": "captures"}).json()
    uri = listed["items"][0]["uri"]
    assert deployment.as_owner("GET", "/evidence", params={"uri": uri}).status_code == 200
    assert deployment.as_stranger("GET", "/evidence", params={"uri": uri}).status_code == 404


# -- selection ----------------------------------------------------------------------------


def test_a_selection_resolves_over_http(deployment):
    response = deployment.as_owner("POST", "/selection", json={"intent": "captures"})
    assert response.status_code == 200
    body = response.json()
    assert body["total_matched"] == 1
    assert body["captures"][0]["blob"].startswith("ni:///sha-256;")
    assert body["truncated"] is False


def test_a_malformed_plan_is_a_400_and_an_unknown_id_is_a_404(deployment):
    malformed = deployment.as_owner("POST", "/selection", json={"intent": "nonsense"})
    assert malformed.status_code == 422, "FastAPI rejects the body before the route runs"

    unknown = deployment.as_owner(
        "POST",
        "/selection",
        json={"intent": "captures", "entities": {"ids": [str(uuid.uuid4())], "mode": "any"}},
    )
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "unknown_reference"


def test_the_endpoints_that_need_a_model_say_so_rather_than_guessing(deployment):
    for path in ("/selection/plan", "/selection/ask"):
        response = deployment.as_owner("POST", path, json={"question": "where was I?"})
        assert response.status_code == 503
        assert "model credential" in response.json()["detail"]


# -- identity -----------------------------------------------------------------------------


def test_a_mutation_cannot_say_who_decided(deployment):
    """decided_by comes from the token. The request model has no field for it, so a caller that
    tried would be refused by the schema rather than ignored."""
    response = deployment.as_owner(
        "POST",
        "/identity/name",
        json={
            "occurrence_id": str(deployment.occurrence_id),
            "display_name": "Someone",
            "actor": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 422, response.text


def test_naming_an_already_identified_occurrence_is_a_conflict(deployment):
    response = deployment.as_owner(
        "POST",
        "/identity/name",
        json={"occurrence_id": str(deployment.occurrence_id), "display_name": "Someone else"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "already_identified"


def test_agreeing_with_a_proposal_that_is_not_pending_is_refused(deployment):
    """The server half of "graph-client rejects any mutation whose proposal id is not pending"."""
    response = deployment.as_owner(
        "POST",
        "/identity/confirm",
        json={
            "occurrence_id": str(deployment.occurrence_id),
            "entity_id": str(deployment.entity_id),
            "proposal_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 409
    assert "still be pending" in response.json()["detail"]


def test_the_identity_ledger_is_readable(deployment):
    events = deployment.as_owner("GET", "/identity/events").json()
    assert [event["type"] for event in events][-2:] == ["entity_created", "link_confirmed"] or [
        event["type"] for event in events
    ][:2] == ["link_confirmed", "entity_created"]


# -- the scene grouping the client turns into islands ---------------------------------------


def _group_two_photographs(repository, photo_dir, store):
    """Ingest a second photograph an hour after the first, then cluster.

    Two photographs at one position an hour apart, which is inside the grouping window, so a
    correct clusterer returns one group of two and an incorrect one returns two groups of one.
    """
    from exulanica.ingest.scenes import run_scene_grouping

    pipeline = PhotoIngestPipeline(repository, store, vision=None)
    outcome = pipeline.ingest_file(
        write_photo(photo_dir, "b.jpg", when="2026:08:27 11:00:00", gps=(64.3271, -20.1199))
    )
    assert outcome.error is None, outcome.error
    return run_scene_grouping(repository)


def test_the_graph_carries_the_grouping_the_client_turns_into_islands(
    deployment, repository, photo_dir
):
    """The server ships a grouping. It does not ship an island, and the difference is the point.

    ADR-0005 leaves what an island IS to the client, so what crosses the wire is named after the
    ingest artifact it is: a run of captures close in time and, where they had a fix, close in
    space. The client decides whether that is one region or several.
    """
    report = _group_two_photographs(repository, photo_dir, deployment.store)
    assert len(report.groups) == 1

    payload = deployment.as_owner("GET", "/graph").json()
    assert len(payload["scene_groups"]) == 1
    group = payload["scene_groups"][0]
    assert group["member_count"] == 2
    assert len(group["capture_ids"]) == 2
    assert group["first_utc"] < group["last_utc"]
    # No field on this payload is called an island, at any depth. The check is on the serialised
    # document rather than on the model, because a field added later to a nested row would be
    # just as much of a decision taken by accident.
    assert "island" not in json.dumps(payload).lower()


def test_a_deleted_capture_leaves_the_group_smaller_rather_than_dangling(
    deployment, repository, photo_dir
):
    """A group member the client cannot resolve is worse than a group with one fewer member.

    The client places anchors inside the islands it builds from these ids. An id naming a
    capture that no longer exists would be an island the interface knows the size of and can
    show nothing in.
    """
    _group_two_photographs(repository, photo_dir, deployment.store)
    before = deployment.as_owner("GET", "/graph").json()["scene_groups"][0]
    assert before["member_count"] == 2

    repository.connection.execute(
        "update capture set deleted_at = now() where capture_id = %s",
        (uuid.UUID(before["capture_ids"][0]),),
    )

    after = deployment.as_owner("GET", "/graph").json()["scene_groups"][0]
    assert after["member_count"] == 1
    assert after["capture_ids"] == before["capture_ids"][1:]


def test_a_stale_grouping_is_not_offered_at_all(deployment, repository, photo_dir):
    """Arranging a world out of a grouping known to be out of date is worse than arranging none.

    An empty list is a state the client already handles: with no grouping, every capture stands
    alone. A stale one is a state it cannot detect.
    """
    _group_two_photographs(repository, photo_dir, deployment.store)
    assert deployment.as_owner("GET", "/graph").json()["scene_groups"]

    repository.connection.execute(
        "update derived_artifact set stale = true where kind = 'scene_group'"
    )
    assert deployment.as_owner("GET", "/graph").json()["scene_groups"] == []


# -- the rung a region earned, which is displayed rather than hidden ---------------------------


def _reconstruct(repository, photo_dir, store, *, valid_fraction=1.0, when="2026:08:27 13:00:00"):
    """Ingest one photograph with reconstruction on, then group it.

    ``when`` differs per call because it goes into the EXIF and therefore into the bytes, and the
    bytes are the identity. Two calls with the same timestamp produce the same blob, the same
    idempotency key and the same artifact, which is the cost control working exactly as designed
    and not what a test of two regions wants.
    """
    from exulanica.ingest.privacy import (
        authorize_synthetic_capture,
        record_synthetic_exemption,
    )
    from exulanica.ingest.scenes import run_scene_grouping
    from exulanica.reconstruction.testing import FlatDepthModel

    pipeline = PhotoIngestPipeline(
        repository, store, vision=None, depth=FlatDepthModel(valid_fraction=valid_fraction)
    )
    path = write_photo(photo_dir, f"r{when[-8:].replace(':', '')}.jpg", when=when)
    intake = pipeline.ingest_intake(path.read_bytes(), filename=path.name)
    assert intake.capture_id is not None, intake.error
    authorization = authorize_synthetic_capture(
        repository,
        capture_id=intake.capture_id,
        actor=uuid.UUID("25f22ef6-997b-5274-ac66-b96af1420410"),
        generator_manifest={
            "profile": "exulanica.api-reconstruction-test/v1",
            "notice": "SYNTHETIC TEST FIXTURE",
        },
        authorization_scope={"purpose": "API reconstruction test"},
    )
    screening = record_synthetic_exemption(
        repository, authorization_id=authorization.authorization_id
    )
    outcome = pipeline.ingest_derivatives(
        intake.capture_id, privacy_screening_id=screening.screening_id
    )
    assert outcome.error is None, outcome.error
    run_scene_grouping(repository)
    return outcome


def test_the_graph_reports_the_rung_a_region_earned(deployment, repository, photo_dir):
    """product-specification.md 5.1: the rung is displayed, not hidden and not smoothed over.

    An interface cannot display a rung the API does not carry, so this is the half of that
    decision that lives on the wire.
    """
    _reconstruct(repository, photo_dir, deployment.store)
    groups = deployment.as_owner("GET", "/graph").json()["scene_groups"]
    assert groups, "no scene group to carry a rung"
    earned = [g for g in groups if g["rung"] is not None]
    assert earned, groups
    assert earned[0]["rung"] == 3
    assert earned[0]["rung_capture_count"] >= 1


def test_a_group_reports_its_worst_rung_rather_than_its_best(deployment, repository, photo_dir):
    """A region is navigable at the level of its weakest part.

    A group where one photograph has no geometry has a hole in it, and reporting the best or the
    mean would describe a region nobody can walk through as though they could.
    """
    _reconstruct(repository, photo_dir, deployment.store, valid_fraction=1.0)
    # Twenty minutes later, so it lands in the same scene group and the two rungs have to be
    # reduced to one number for the region they share.
    _reconstruct(
        repository, photo_dir, deployment.store, valid_fraction=0.01, when="2026:08:27 13:20:00"
    )
    groups = deployment.as_owner("GET", "/graph").json()["scene_groups"]
    worst = [g for g in groups if g["rung_capture_count"] >= 2]
    assert worst, [g["rung_capture_count"] for g in groups]
    assert worst[0]["rung"] == 4


def test_a_group_nothing_has_reconstructed_says_so_rather_than_claiming_rung_four(
    deployment, repository, photo_dir
):
    """Null and rung 4 are different facts.

    Rung 4 means reconstruction ran and there was nothing to place. Null means it never ran. An
    interface that showed them identically would be reporting a decision nobody made.
    """
    from exulanica.ingest.scenes import run_scene_grouping

    pipeline = PhotoIngestPipeline(repository, deployment.store, vision=None, depth=None)
    outcome = pipeline.ingest_file(write_photo(photo_dir, "none.jpg", when="2026:08:27 14:00:00"))
    assert outcome.error is None
    assert "depth" in outcome.stages_skipped
    run_scene_grouping(repository)

    groups = deployment.as_owner("GET", "/graph").json()["scene_groups"]
    assert any(g["rung"] is None for g in groups), groups


def test_the_newest_rung_is_the_one_reported(deployment, repository, photo_dir):
    """Reconstruction run twice reports what the latest run found, not what the first one did.

    This test found defect R16. ``predicate.functional`` is documented in migration 0001 as "at
    most one active object per subject" and is enforced by nothing: no constraint, no index and no
    trigger reads the column. So the second claim below does NOT supersede the first, both stay
    active, and an unordered read would report whichever row the query planner returned.

    The behaviour asserted here is therefore what the reader guarantees rather than what the
    vocabulary was believed to: newest active wins, deterministically. Both halves are checked,
    because a later fix that makes ``functional`` real must not change what is displayed.
    """
    _reconstruct(repository, photo_dir, deployment.store, valid_fraction=1.0)
    capture = repository.connection.execute(
        "select capture_id from capture where workspace_id = %s order by created_at desc limit 1",
        (repository.workspace_id,),
    ).fetchone()
    span = repository.connection.execute(
        "select span_id from evidence_span where workspace_id = %s limit 1",
        (repository.workspace_id,),
    ).fetchone()

    before = deployment.as_owner("GET", "/graph").json()["scene_groups"]
    assert any(g["rung"] == 3 for g in before), before

    # A second run of a later version of the stage, reporting a worse outcome over the same
    # photograph. `reconstruction_rung_is` is functional, so this supersedes rather than adding.
    # A real run row, because `assertion.produced_by_run` has a foreign key: an inference that
    # named a run nobody could look up would be an inference with no provenance.
    from exulanica.ingest.ledger import Ledger

    rerun = Ledger.start_run(repository, trigger="reprocess")
    repository.insert_assertion(
        kind="inference",
        predicate_key="reconstruction_rung_is",
        subject_ref={"type": "capture", "id": str(capture["capture_id"])},
        object_value={"rung": 4, "valid_fraction": 0.01, "reason": "a later run placed less"},
        emit_key="test:rerun",
        support_span_ids=[span["span_id"]],
        produced_by_run=rerun.run_id,
    )

    after = deployment.as_owner("GET", "/graph").json()["scene_groups"]
    reported = {g["rung"] for g in after if g["rung"] is not None}
    assert reported == {4}, after
    # R16 is closed by migration 0006 and the reported rung above is unchanged, which was the
    # point of asserting both halves: making `functional` real had to be invisible on screen.
    # What changed is underneath. The first claim is retired rather than left current beside the
    # second, so the display no longer depends on `_rung_by_capture` ordering to be correct, and
    # the retired claim is still readable, which is what a superseded row is for.
    statuses = [
        row["status"]
        for row in repository.connection.execute(
            "select a.status from assertion a join predicate p on p.predicate_id = a.predicate_id "
            "where a.workspace_id = %s and p.key = 'reconstruction_rung_is' order by a.asserted_at",
            (repository.workspace_id,),
        ).fetchall()
    ]
    assert statuses == ["superseded", "active"], (
        "a functional predicate is carrying two claims that are not one current and one retired"
    )
