"""A person who withdrew is in the World Memory Package without their name, and it says why.

The read path already applies this (``exulanica.graph.entities``, held by
``test_person_presentation_consent``): a withdrawn person's entity keeps its row and loses its
display name, and their naming assertions keep their rows and lose their values. The package is
the same person's data leaving the product for good, signed, so it applies the same rule to the
same two fields, names the reason on each row it withholds, and reads its own bytes back before it
signs them: a package in which any value is a withdrawn person's saved name is refused.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exulanica.consent.regions import Silhouette, region_key
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.evidence.region import DisplayGeometry, Rect
from exulanica.graph.entities import NAME_PREDICATE
from exulanica.identity import IdentityRepository, rename_entity
from exulanica.ingest import person_review
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world_package import projector
from exulanica.world_package.package import PackageError, verify_package
from exulanica.world_package.projector import (
    PERSON_WITHDRAWN_REASON,
    _urn,
    project_world_package,
)

from conftest import iso, write_photo

pytestmark = pytest.mark.postgres

WITHDRAWN = "Julie Marchetti"
EARLIER = "Jules"
KEPT = "Rosa Lindqvist"


def _named(repository, name: str, actor: uuid.UUID, *, earlier: str | None = None) -> uuid.UUID:
    """A person entity named through the naming assertion, as the product names one."""
    identity = IdentityRepository(repository.connection, repository.workspace_id)
    writer = AssertionWriter(repository.connection, repository.workspace_id)
    entity_id = identity.entities.create(entity_class="person")
    for display_name in (earlier, name):
        if display_name is not None:
            rename_entity(
                identity, writer, entity_id=entity_id, display_name=display_name, actor=actor
            )
    return entity_id


@pytest.fixture
def people(repository, photo_dir, tmp_path):
    """Two named people in one photograph's workspace; the first is a person subject."""
    actor = uuid.uuid4()
    write_photo(photo_dir, "a.jpg", when=iso(10))
    pipeline = PhotoIngestPipeline(
        repository, LocalContentAddressedStore(tmp_path / "blobs"), detector=None
    )
    intake = pipeline.ingest_intake((photo_dir / "a.jpg").read_bytes(), filename="a.jpg")
    assert intake.capture_id is not None, intake.error
    blob_id = repository.capture(intake.capture_id).blob_id

    withdrawing = _named(repository, WITHDRAWN, actor, earlier=EARLIER)
    staying = _named(repository, KEPT, actor)
    subject_id = person_review.create_subject(repository, actor=actor, entity_id=withdrawing)
    outline = Silhouette.from_rect(Rect.from_normalised(0.2, 0.2, 0.3, 0.5))
    person_review.record_region_edits(
        repository,
        capture_id=intake.capture_id,
        actor=actor,
        edits=[
            {
                "region_key": region_key(blob_id, outline, DisplayGeometry(w=160, h=100)).hex(),
                "action": "add",
                "silhouette": outline.as_digest_input(),
                "subject_id": str(subject_id),
            }
        ],
    )
    person_review.record_consent(
        repository, subject_id=subject_id, actor=actor, consent_scope="naming", decision="granted"
    )

    def withdraw() -> None:
        person_review.record_consent(
            repository,
            subject_id=subject_id,
            actor=actor,
            consent_scope="likeness",
            decision="withdrawn",
        )

    return repository, withdrawing, staying, withdraw


def _export(repository, output: Path):
    return project_world_package(
        repository.connection,
        workspace_id=repository.workspace_id,
        actor=uuid.uuid4(),
        output=output,
        private_key=Ed25519PrivateKey.generate(),
    )


def _package_text(output: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(output.rglob("*.json")))


def _entity(graph, entity_id: uuid.UUID) -> dict:
    (row,) = [row for row in graph["entities"] if row["entity_id"] == _urn("entity", entity_id)]
    return row


def _naming(graph, entity_id: uuid.UUID) -> list[dict]:
    return [
        row
        for row in graph["assertions"]
        if row["predicate"] == NAME_PREDICATE
        and row["subject_ref"].get("id") == _urn("entity", entity_id)
    ]


def test_a_withdrawn_person_keeps_their_rows_and_loses_every_saved_name(people, tmp_path):
    repository, withdrawing, staying, withdraw = people

    # The control: before the withdrawal the package carries the name, so its absence afterwards
    # is the rule working and not the name never having been exported.
    before = _export(repository, tmp_path / "before.wmp")
    assert WITHDRAWN in _package_text(before.output)

    withdraw()
    after = _export(repository, tmp_path / "after.wmp")
    verify_package(after.output)
    text = _package_text(after.output)
    assert WITHDRAWN not in text and EARLIER not in text, "a withdrawn person's name was exported"

    graph = json.loads((after.output / "memory/graph.json").read_text(encoding="utf-8"))
    entity = _entity(graph, withdrawing)
    assert entity["display_name"] is None
    assert entity["withheld"] == {"display_name": PERSON_WITHDRAWN_REASON}
    naming = _naming(graph, withdrawing)
    assert naming, "the naming assertion keeps its row; a withdrawal does not erase the event"
    assert all(row["object_value"] is None for row in naming)
    assert all(row["withheld"] == {"object_value": PERSON_WITHDRAWN_REASON} for row in naming)

    # The person who did not withdraw is exported exactly as before, with no withholding on them.
    kept = _entity(graph, staying)
    assert kept["display_name"] == KEPT and "withheld" not in kept
    assert all(
        row["object_value"] == KEPT and "withheld" not in row for row in _naming(graph, staying)
    )


def test_the_package_refuses_to_sign_a_withdrawn_name(people, tmp_path, monkeypatch):
    """The check reads the bytes about to be signed, so a field that forgets the rule is caught."""
    repository, _, _, withdraw = people
    withdraw()
    original = projector._crate_files

    def leaking(components):
        # A later field that carries a name the rule never reached.
        components = dict(components)
        graph = dict(components["memory/graph.json"])
        graph["labels"] = [WITHDRAWN.upper()]
        components["memory/graph.json"] = graph
        return original(components)

    monkeypatch.setattr(projector, "_crate_files", leaking)
    output = tmp_path / "refused.wmp"
    refusal = re.escape("memory/graph.json/labels/0: a withdrawn person's saved name")
    with pytest.raises(PackageError, match=refusal):
        _export(repository, output)
    assert not output.exists(), "a refused package was published"
    receipts = repository.connection.execute(
        "select count(*) as n from world_package_export where workspace_id=%s",
        (repository.workspace_id,),
    ).fetchone()["n"]
    assert receipts == 0, "a refused package was receipted"


def test_somebody_else_saved_under_the_same_name_keeps_it(people, tmp_path):
    """Two people can share a name. The one who did not withdraw is exported with theirs."""
    repository, withdrawing, _, withdraw = people
    namesake = _named(repository, WITHDRAWN, uuid.uuid4())
    withdraw()

    exported = _export(repository, tmp_path / "namesake.wmp")

    graph = json.loads((exported.output / "memory/graph.json").read_text(encoding="utf-8"))
    assert _entity(graph, namesake)["display_name"] == WITHDRAWN
    assert _entity(graph, withdrawing)["display_name"] is None
    assert all(row["object_value"] is None for row in _naming(graph, withdrawing))
    assert EARLIER not in _package_text(exported.output)
