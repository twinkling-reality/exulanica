"""The HTTP surface for a Companion appearance proposal, and where it goes next.

Two routes and one journey. `POST /selection/appearance` reads an utterance and returns either a
proposal with its provenance or a refusal; `POST /world/styles/previews` is where that proposal
becomes a reviewed preview, with `origin: companion`, exactly as a Settings change becomes one
with `origin: settings`.

**They are two requests on purpose and the gap between them is the guarantee.** What sits in it
is the person: the browser puts the proposal in front of them through the confirmation surface,
and posts the preview because they are looking at it. A single route that proposed and previewed
in one call would have moved that decision inside the server, where nobody can see it.

The model is scripted throughout. Nothing here spends credits.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from dataclasses import dataclass

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.transport import HttpResponse
from exulanica.selection.proposal import PROMPT_VERSION as PROPOSAL_PROMPT_VERSION
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import TopologyContract, TopologySourceSlot, WorldStyleRepository
from fastapi.testclient import TestClient

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS, write_photo
from model_fakes import FakeTransport, chat_body

pytestmark = pytest.mark.postgres

TOKEN = "proposal-owner-token-long-enough-for-tests"
STRANGER_TOKEN = "proposal-stranger-token-long-enough-for-tests"
DRAFTER = "Qwen/Qwen3-235B-A22B-Instruct-2507"
TOPOLOGY = "proposal-route-topology"


def reply(payload: dict, *, model: str = DRAFTER) -> HttpResponse:
    return HttpResponse(
        status_code=200, text=json.dumps(chat_body(json.dumps(payload), model=model))
    )


@dataclass
class ProposalApi:
    client: TestClient
    transport: FakeTransport
    actor: uuid.UUID
    source_ids: tuple[str, ...]

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {TOKEN}"}

    def get(self, path):
        return self.client.get(path, headers=self.headers)

    def post(self, path, body):
        return self.client.post(path, headers=self.headers, json=body)

    def current(self):
        return self.get("/world/styles/current").json()

    def script(self, *responses: HttpResponse) -> None:
        self.transport.responses[:] = list(responses)

    def utter(self, utterance: str):
        return self.post("/selection/appearance", {"utterance": utterance})

    def draft(self, **overrides) -> dict:
        body = {
            "profile": "origin-landscape@1",
            "modules": ["aeroheart-optics-v1"],
            "parameters": {
                "vitality": None,
                "glass": None,
                "relationship_energy": None,
                "garden_density": None,
                "horizon_softness": 0.8,
                "surface_finish": None,
                "world_tempo": None,
            },
            "references": [self.source_ids[0]],
            "spoken": "The horizon will sit softer, so the far edge reads as distance.",
            "impossible": None,
        }
        body.update(overrides)
        return body

    def preview_body(self, proposal: dict, **overrides) -> dict:
        """The proposal as the browser posts it, in the frontend's own camel-case spelling.

        Written the way `world-style-api.ts` writes it rather than in the snake-case the routes
        also accept, so this test exercises the casing the browser actually sends.
        """
        current = self.current()
        body = {
            "proposalId": str(uuid.uuid4()),
            "origin": "companion",
            "originReference": "companion-utterance:0f2c",
            "scope": {"kind": "global"},
            "baseStyleVersionId": current["current"]["version_id"],
            "baseTopologyDigest": current["current_topology_digest"],
            "profile": {
                "profileId": proposal["profile"]["profile_id"],
                "profileVersion": proposal["profile"]["profile_version"],
                "parameters": proposal["profile"]["parameters"],
            },
            "referenceIds": proposal["reference_ids"],
            "modelId": proposal["model_id"],
            "promptVersion": proposal["prompt_version"],
        }
        body.update(overrides)
        return body


@pytest.fixture
def proposal_api(repository, spine_schema, tmp_path, photo_dir, monkeypatch):
    _psycopg, scratch = spine_schema
    actor = uuid.uuid4()
    stranger = uuid.uuid4()
    store = LocalContentAddressedStore(tmp_path / "blobs")

    # A source slot is tied to a span in the same workspace by a composite foreign key, so the
    # evidence has to be real before the topology can name it.
    outcome = PhotoIngestPipeline(repository, store, vision=None).ingest_file(
        write_photo(photo_dir, "world-source.jpg")
    )
    assert outcome.error is None, outcome.error
    spans = [
        row["span_id"]
        for row in repository.connection.execute(
            "select span_id from evidence_span where workspace_id=%s order by span_id",
            (repository.workspace_id,),
        ).fetchall()
    ]
    assert spans
    source_ids = tuple(uuid.UUID(int=index + 1) for index in range(3))
    WorldStyleRepository(repository.connection, repository.workspace_id).register_topology(
        TopologyContract(
            TOPOLOGY,
            ("region-a",),
            tuple(
                TopologySourceSlot(
                    source_id=source_id,
                    slot_key=f"slot-{index:02d}",
                    region_id="region-a",
                    evidence_span_id=spans[index % len(spans)],
                    missing_reason=None,
                )
                for index, source_id in enumerate(source_ids)
            ),
        )
    )

    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {"workspace_id": str(repository.workspace_id), "actor": str(actor)},
                STRANGER_TOKEN: {"workspace_id": str(stranger), "actor": str(uuid.uuid4())},
            }
        ),
    )
    from tests_support_api import scratch_database

    database = scratch_database(scratch)
    transport = FakeTransport()
    services = Services(
        database=database,
        readonly_database=database,
        store=store,
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=ModelClient(
            api_key="test-key-not-real",
            transport=transport,
            budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        ),
    )
    with TestClient(create_app(services, verify=False)) as client:
        yield ProposalApi(client, transport, actor, tuple(str(value) for value in source_ids))


# -- the proposal route -----------------------------------------------------------------------


def test_an_appearance_request_comes_back_as_a_complete_reference_with_its_provenance(
    proposal_api,
):
    proposal_api.script(reply({"kind": "appearance"}), reply(proposal_api.draft()))

    response = proposal_api.utter("could the horizon be a bit softer in here")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["classification"] == "appearance"
    assert body["refusal"] is None
    proposal = body["proposal"]
    assert proposal["profile"]["profile_id"] == "origin-landscape"
    assert proposal["profile"]["changed"] == ["horizon-softness"]
    assert proposal["profile"]["parameters"]["horizon-softness"] == 0.8
    # Complete, so a preview posted from it does not reset the controls nobody mentioned.
    assert set(proposal["profile"]["parameters"]) == {
        "vitality",
        "glass",
        "relationship-energy",
        "garden-density",
        "horizon-softness",
        "surface-finish",
        "world-tempo",
    }
    assert proposal["model_id"] == DRAFTER
    assert proposal["prompt_version"] == PROPOSAL_PROMPT_VERSION
    assert proposal["reference_ids"] == [proposal_api.source_ids[0]]
    assert proposal["spoken"]


def test_the_execution_block_reports_this_paths_prompt_version_and_not_the_question_paths(
    proposal_api,
):
    """Both constants are inputs to the response cache key, so they are not interchangeable."""
    proposal_api.script(reply({"kind": "appearance"}), reply(proposal_api.draft()))

    execution = proposal_api.utter("softer horizon please").json()["execution"]

    assert execution["prompt_version"] == PROPOSAL_PROMPT_VERSION
    assert [call["role"] for call in execution["calls"]] == [
        "structured_extraction",
        "structured_extraction",
    ]
    assert all(call["served_model"] == DRAFTER for call in execution["calls"])


def test_a_question_is_classified_as_one_and_carries_no_refusal(proposal_api):
    """A question is not a failure of this route, and a client must not show one as a refusal."""
    proposal_api.script(reply({"kind": "question"}))

    body = proposal_api.utter("who is in these photographs?").json()

    assert (body["classification"], body["proposal"], body["refusal"]) == ("question", None, None)
    assert len(body["execution"]["calls"]) == 1


def test_a_request_the_catalogue_cannot_express_is_refused_with_a_code_a_surface_can_speak(
    proposal_api,
):
    proposal_api.script(
        reply({"kind": "appearance"}),
        reply(proposal_api.draft(impossible="a different typeface for the menus")),
    )

    body = proposal_api.utter("use a serif typeface everywhere").json()

    assert body["classification"] == "appearance"
    assert body["proposal"] is None
    assert body["refusal"]["code"] == "not_in_catalogue"
    assert body["refusal"]["detail"] == "a different typeface for the menus"


def test_a_value_outside_the_declared_range_never_comes_back_as_a_clamped_proposal(proposal_api):
    """The refusal that must not become a value. Scripted twice, because one repair is allowed."""
    over = proposal_api.draft()
    over["parameters"] = {**over["parameters"], "horizon_softness": 1.4}
    proposal_api.script(reply({"kind": "appearance"}), reply(over), reply(over))

    response = proposal_api.utter("make the horizon as soft as it can possibly go")
    body = response.json()

    assert body["proposal"] is None
    assert body["refusal"]["code"] == "not_drafted"
    # The refusal says which value broke which control, so the record can name it. What does
    # NOT come back is the bound: a clamp would have answered 1.0, which is a proposal nobody
    # made wearing the shape of one somebody did.
    assert "horizon_softness: 1.4" in body["refusal"]["detail"]
    assert "1.0" not in response.text


def test_an_unregistered_control_is_refused_rather_than_dropped_from_the_proposal(proposal_api):
    """`contour-density` belongs to the experimental profile. Naming it here is a refusal.

    Dropping it and proposing the rest would file a change under a request nobody made.
    """
    draft = proposal_api.draft()
    draft["parameters"] = {**draft["parameters"], "contour_density": 0.9}
    proposal_api.script(reply({"kind": "appearance"}), reply(draft), reply(draft))

    body = proposal_api.utter("add survey contours").json()

    assert body["proposal"] is None
    assert body["refusal"]["code"] == "not_drafted"


def test_evidence_from_another_workspace_is_not_in_the_catalogue_and_cannot_be_named(
    proposal_api,
):
    draft = proposal_api.draft(references=[str(uuid.uuid4())])
    proposal_api.script(reply({"kind": "appearance"}), reply(draft), reply(draft))

    body = proposal_api.utter("softer horizon").json()

    assert body["proposal"] is None
    assert body["refusal"]["code"] == "not_drafted"


def test_the_route_needs_a_bearer_token_like_every_other(proposal_api):
    response = proposal_api.client.post("/selection/appearance", json={"utterance": "softer"})

    assert (response.status_code, response.json()["code"]) == (401, "unauthenticated")


def test_an_instance_with_no_model_credential_says_so_rather_than_guessing(
    repository, spine_schema, tmp_path, monkeypatch
):
    _psycopg, scratch = spine_schema
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {TOKEN: {"workspace_id": str(repository.workspace_id), "actor": str(uuid.uuid4())}}
        ),
    )
    from tests_support_api import scratch_database

    database = scratch_database(scratch)
    services = Services(
        database=database,
        readonly_database=database,
        store=LocalContentAddressedStore(tmp_path / "blobs"),
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
    )
    with TestClient(create_app(services, verify=False)) as client:
        response = client.post(
            "/selection/appearance",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"utterance": "softer horizon"},
        )

    assert response.status_code == 503
    assert "model credential" in response.json()["detail"]


# -- and where the proposal goes next ---------------------------------------------------------


def test_the_proposal_becomes_a_companion_preview_through_the_world_style_lifecycle(proposal_api):
    """The acceptance path, end to end: `POST /world/styles/previews` with origin companion.

    The body is the frontend's own camel-case spelling, and the provenance is what the proposal
    route returned rather than what this test decided. Nothing about the current style moves.
    """
    proposal_api.script(reply({"kind": "appearance"}), reply(proposal_api.draft()))
    proposal = proposal_api.utter("softer horizon please").json()["proposal"]
    initial = proposal_api.current()

    preview = proposal_api.post("/world/styles/previews", proposal_api.preview_body(proposal))

    assert preview.status_code == 201, preview.text
    candidate = preview.json()["candidate"]
    assert candidate["global_style"]["parameters"]["horizon-softness"] == 0.8
    assert candidate["provenance"] == {
        "origin": "companion",
        # From the bearer token, never from the body. The proposal route has no actor field
        # either, and the browser cannot supply one.
        "actor": str(proposal_api.actor),
        "origin_reference": "companion-utterance:0f2c",
    }
    assert candidate["model_id"] == DRAFTER
    assert candidate["prompt_version"] == PROPOSAL_PROMPT_VERSION
    assert candidate["reference_ids"] == [proposal_api.source_ids[0]]
    # The binding is DERIVED by the backend from its own registry. Nothing executable crossed.
    assert candidate["recipe_binding"]["modules"] == [
        "aeroheart-optics-v1",
        "registered-surface-v1",
        "bounded-tempo-v1",
    ]
    assert proposal_api.current()["current"]["version_id"] == initial["current"]["version_id"]


def test_applying_a_companion_preview_records_the_model_that_drew_it_on_the_version(proposal_api):
    proposal_api.script(reply({"kind": "appearance"}), reply(proposal_api.draft()))
    proposal = proposal_api.utter("softer horizon please").json()["proposal"]
    initial = proposal_api.current()
    preview = proposal_api.post("/world/styles/previews", proposal_api.preview_body(proposal))

    applied = proposal_api.post(
        f"/world/styles/previews/{preview.json()['preview_id']}/apply",
        {
            "baseStyleVersionId": initial["current"]["version_id"],
            "baseTopologyDigest": TOPOLOGY,
        },
    )

    assert applied.status_code == 200, applied.text
    version = applied.json()
    assert version["revision"] == initial["current"]["revision"] + 1
    assert (version["model_id"], version["prompt_version"]) == (DRAFTER, PROPOSAL_PROMPT_VERSION)
    assert version["provenance"]["origin"] == "companion"
    assert version["global_style"]["parameters"]["horizon-softness"] == 0.8


def test_a_companion_preview_without_model_provenance_is_refused_by_the_world_authority(
    proposal_api,
):
    """The route-level half of the same rule the proposal path enforces before it gets here.

    Both are real. This one is what stops a client that skipped the proposal route from filing a
    companion-origin change with no model behind it.
    """
    proposal_api.script(reply({"kind": "appearance"}), reply(proposal_api.draft()))
    proposal = proposal_api.utter("softer horizon please").json()["proposal"]
    body = proposal_api.preview_body(proposal)
    del body["modelId"]
    del body["promptVersion"]

    response = proposal_api.post("/world/styles/previews", body)

    assert (response.status_code, response.json()["code"]) == (422, "invalid_style_data")
    assert "require model" in response.json()["detail"]


def test_a_companion_preview_naming_no_evidence_is_refused(proposal_api):
    proposal_api.script(reply({"kind": "appearance"}), reply(proposal_api.draft()))
    proposal = proposal_api.utter("softer horizon please").json()["proposal"]

    response = proposal_api.post(
        "/world/styles/previews", proposal_api.preview_body(proposal, referenceIds=[])
    )

    assert (response.status_code, response.json()["code"]) == (422, "invalid_style_data")


def test_a_companion_proposal_still_cannot_roll_the_world_back(proposal_api):
    """Unchanged by this path, and asserted here because this path is what made it reachable.

    A rollback restores values nobody is proposing and cites no model. The refusal stands, and
    the recovery is the same as it was: make a new proposal with its own provenance.
    """
    proposal_api.script(reply({"kind": "appearance"}), reply(proposal_api.draft()))
    proposal = proposal_api.utter("softer horizon please").json()["proposal"]
    initial = proposal_api.current()
    preview = proposal_api.post("/world/styles/previews", proposal_api.preview_body(proposal))
    applied = proposal_api.post(
        f"/world/styles/previews/{preview.json()['preview_id']}/apply",
        {"baseStyleVersionId": initial["current"]["version_id"], "baseTopologyDigest": TOPOLOGY},
    )

    refused = proposal_api.post(
        "/world/styles/rollback",
        {
            "targetVersionId": initial["current"]["version_id"],
            "baseStyleVersionId": applied.json()["version_id"],
            "baseTopologyDigest": TOPOLOGY,
            "origin": "companion",
            "originReference": "companion-utterance:0f2c",
        },
    )

    assert (refused.status_code, refused.json()["code"]) == (422, "invalid_style_data")
    assert "Companion rollback" in refused.json()["detail"]
    # And the same rollback from Settings still works, so what was refused is the origin.
    from_settings = proposal_api.post(
        "/world/styles/rollback",
        {
            "targetVersionId": initial["current"]["version_id"],
            "baseStyleVersionId": applied.json()["version_id"],
            "baseTopologyDigest": TOPOLOGY,
            "origin": "settings",
            "originReference": "appearance-history",
        },
    )
    assert from_settings.status_code == 200, from_settings.text


def test_the_proposal_route_writes_nothing_at_all(proposal_api):
    """It returns a proposal. Nothing is staged, nothing is previewed, nothing is current.

    The strongest available form of "shown to the user before it is applied": after the route
    has answered, the world has no preview and no new version to find.
    """
    before = proposal_api.current()
    proposal_api.script(reply({"kind": "appearance"}), reply(proposal_api.draft()))

    assert proposal_api.utter("softer horizon please").status_code == 200

    assert proposal_api.current() == before
    assert proposal_api.get("/world/styles/versions").json() == [before["current"]]


def test_the_services_object_is_replaceable_so_a_scripted_model_is_the_running_one(proposal_api):
    """Guards the fixture itself: a client that reached the network would fail differently."""
    proposal_api.script(reply({"kind": "question"}))
    proposal_api.utter("who is in these photographs?")

    assert proposal_api.transport.call_count == 1
    assert proposal_api.transport.models_called == [DRAFTER]
    assert dataclasses.is_dataclass(Services)
