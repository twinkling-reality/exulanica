"""A starter world's Companion appearance proposals cite the photographs attached to it.

A proposal must cite evidence, and a starter world is built from nothing, so its topology binds
none. The evidence it can hold is the reviewed photographs the person attaches to it as references.
``source_catalogue`` offers those, as the saved entry's current collection reports them at the
moment it is read: a photograph that is detached, or whose source is withdrawn, is no longer
citable. The drafter is handed each by its attachment id alone, never bytes or derived text.

The route half is the reason the catalogue exists: ``POST /selection/appearance`` on a saved
starter world reads that world's own appearance and, once a photograph is attached, returns a
proposal that cites it.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.selection.proposal import (
    AppearanceProposal,
    ProposalRefusal,
    RefusalCode,
    propose_appearance,
    source_catalogue,
)
from exulanica.selection.validation import Session
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import SavedWorldEntryRepository, SourceAttachmentSelection
from exulanica.world.repository import WorldStyleRepository
from fastapi.testclient import TestClient

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
from model_fakes import FakeTransport
from test_saved_world_entries_api import _reviewed_source
from test_selection_proposal import draft, reply, scripted
from tests_support_api import EVERY_PERMISSION, scratch_database

pytestmark = pytest.mark.postgres

TOKEN = "starter-appearance-token-long-enough-for-tests"
UTTERANCE = "make my world a little warmer"


@dataclass
class Starter:
    repository: object
    store: LocalContentAddressedStore
    actor: uuid.UUID
    entries: SavedWorldEntryRepository
    entry_id: uuid.UUID
    world_id: str

    def entry(self):
        return self.entries.entry(self.entry_id)

    def current_style(self):
        return (
            WorldStyleRepository(
                self.repository.connection, self.repository.workspace_id, world_id=self.world_id
            )
            .current()
            .global_style
        )

    def attach(self, *, minute: int, **review) -> uuid.UUID:
        """Attach one reviewed photograph through the repository the route uses; its id."""
        source = _reviewed_source(
            self.repository,
            SimpleNamespace(store=self.store, actor=self.actor),
            minute=minute,
            **review,
        )
        entry = self.entry()
        attached = self.entries.attach_sources(
            self.entry_id,
            operation_id=uuid.uuid4(),
            base_revision=entry.revision,
            authored_version_id=entry.authored_version_id,
            authored_state_sha256=entry.authored_state_sha256,
            authored_edit_seq=entry.authored_edit_seq,
            style_version_id=entry.style_version_id,
            sources=(
                SourceAttachmentSelection(
                    uuid.UUID(source["capture_id"]), uuid.UUID(source["evidence_span_id"])
                ),
            ),
            attached_by=self.actor,
        )
        [attachment] = [
            a for a in attached.source_attachments if str(a.capture_id) == source["capture_id"]
        ]
        return attachment.attachment_id

    def propose(self, *responses):
        client, transport = scripted(*responses)
        outcome = propose_appearance(
            self.repository.connection,
            client,
            UTTERANCE,
            Session(workspace_id=self.repository.workspace_id, actor=self.actor),
            current=self.current_style(),
            world_id=self.world_id,
            store=self.store,
        )
        return outcome, transport

    def cited(self) -> list[str]:
        return [
            str(choice.source_id)
            for choice in source_catalogue(
                self.repository.connection,
                self.repository.workspace_id,
                world_id=self.world_id,
                store=self.store,
            )
        ]


@pytest.fixture
def starter(repository, tmp_path) -> Starter:
    store = LocalContentAddressedStore(tmp_path / "blobs")
    actor = uuid.uuid4()
    entries = SavedWorldEntryRepository(repository.connection, repository.workspace_id, store)
    entry = entries.create_starter(title="My world", created_by=actor)
    return Starter(repository, store, actor, entries, entry.entry_id, entry.world_id)


def _refused_for_want_of_evidence(outcome) -> None:
    assert isinstance(outcome.refusal, ProposalRefusal)
    assert outcome.refusal.code is RefusalCode.NO_EVIDENCE
    assert "attach a reviewed photograph" in outcome.refusal.detail


def test_a_starter_with_no_photograph_refuses_by_name_and_says_what_would_change_that(starter):
    outcome, transport = starter.propose(reply({"kind": "appearance"}))
    _refused_for_want_of_evidence(outcome)
    assert transport.call_count == 1, "the drafter must not be asked with nothing to cite"


def test_a_starter_with_one_attached_reviewed_photograph_gets_a_proposal_citing_it(starter):
    attachment_id = starter.attach(minute=1)
    assert starter.cited() == [str(attachment_id)]
    outcome, transport = starter.propose(
        reply({"kind": "appearance"}), reply(draft(references=[str(attachment_id)]))
    )
    assert outcome.refusal is None, outcome.refusal
    assert isinstance(outcome.proposal, AppearanceProposal)
    assert outcome.proposal.reference_ids == (str(attachment_id),)
    # The drafter saw the attachment as an identifier and nothing else about the photograph.
    drafting = json.dumps(transport.requests[1]["payload"])
    assert str(attachment_id) in drafting
    assert "source-1.jpg" not in drafting


def test_a_detached_photograph_is_no_longer_citable(starter):
    attachment_id = starter.attach(minute=2)
    entry = starter.entry()
    starter.entries.detach_sources(
        starter.entry_id,
        operation_id=uuid.uuid4(),
        base_revision=entry.revision,
        authored_version_id=entry.authored_version_id,
        authored_state_sha256=entry.authored_state_sha256,
        authored_edit_seq=entry.authored_edit_seq,
        style_version_id=entry.style_version_id,
        attachment_ids=(attachment_id,),
        detached_by=starter.actor,
    )
    assert starter.cited() == []
    _refused_for_want_of_evidence(starter.propose(reply({"kind": "appearance"}))[0])


def test_a_photograph_whose_source_is_withdrawn_is_no_longer_citable(starter):
    attachment_id = starter.attach(minute=3)
    [attachment] = starter.entry().source_attachments
    assert attachment.attachment_id == attachment_id
    starter.repository.insert_tombstone(
        scope="capture",
        capture_id=attachment.capture_id,
        requested_by=starter.actor,
        reason="the person withdrew this photograph",
    )
    assert starter.cited() == []
    _refused_for_want_of_evidence(starter.propose(reply({"kind": "appearance"}))[0])


def test_the_route_gives_a_saved_starter_world_a_proposal_citing_its_photograph(
    starter, repository, spine_schema, monkeypatch
):
    """``POST /selection/appearance`` reads the named starter's own appearance and evidence."""
    _psycopg, scratch = spine_schema
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {
                    "workspace_id": str(repository.workspace_id),
                    "actor": str(starter.actor),
                    "permissions": EVERY_PERMISSION,
                }
            }
        ),
    )
    transport = FakeTransport()
    database = scratch_database(scratch)
    services = Services(
        database=database,
        readonly_database=database,
        store=starter.store,
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=ModelClient(
            api_key="test-key-not-real",
            transport=transport,
            budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        ),
    )
    with TestClient(create_app(services, verify=False)) as client:

        def ask():
            return client.post(
                f"/selection/appearance?world_id={starter.world_id}",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"utterance": UTTERANCE},
            ).json()

        transport.responses[:] = [reply({"kind": "appearance"})]
        refused = ask()
        assert refused["refusal"]["code"] == "no_evidence"
        assert "attach a reviewed photograph" in refused["refusal"]["detail"]

        attachment_id = str(starter.attach(minute=4))
        transport.responses[:] = [
            reply({"kind": "appearance"}),
            reply(draft(references=[attachment_id])),
        ]
        proposed = ask()
        assert proposed["refusal"] is None, proposed
        assert proposed["proposal"]["reference_ids"] == [attachment_id]
