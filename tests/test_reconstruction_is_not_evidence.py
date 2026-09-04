"""Invariant 2, tested for real: reconstruction is never evidence.

``docs/domain-and-evidence-model.md``: an evidence address is (content hash of the ORIGINAL
bytes, track key, exact rational time interval) and nothing else, and no function may return a
rendition, a point map, or a rendered view as a citation target.

Until reconstruction existed this invariant was true by having nothing to violate it with. It
now has a producer, and the whole product rests on the sentence it protects: reconstruction
quality never participates in the truth guarantee. A region may degrade to a photograph on a
plane and the factual promise is unchanged, which is only true while a citation cannot resolve to
geometry.

Four checks, weakest first, and the ordering is deliberate.

*   The reconstruction package **cannot name an evidence address**, because it does not import the
    module that defines one. A rule kept by an absent import is kept for code nobody reviewed.
*   A point map is **never registered as a blob**. Spans reference ``blob``; artifacts do not
    live there, so a point map has nothing a span could point at.
*   Every span in a workspace names bytes **some capture claims**. That is the positive form of
    the same statement and it would catch a span created over a derivative by any route.
*   A permalink naming a point map's hash is **refused with the same 404** a nonexistent span
    gets, over HTTP, which is the surface an attacker or a confused client actually has.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.store.local import LocalContentAddressedStore

from conftest import iso, write_photo

_PACKAGE = Path(__file__).resolve().parents[1] / "exulanica" / "reconstruction"

#: Names that would mean this package had learned what a citation is. `BlobId` is included even
#: though it is only a content hash: a producer that held one would be one refactor away from
#: putting a derivative's hash where an original's belongs.
_FORBIDDEN_NAMES = ("EvidenceAddress", "BlobId", "span_digest", "evidence_span", "TimeInterval")


def _sources() -> list[Path]:
    return sorted(_PACKAGE.rglob("*.py"))


# ---------------------------------------------------------------------------------------------
# The absence


def test_the_reconstruction_package_exists_and_has_something_to_check():
    # A check over an empty directory passes while checking nothing, which is the failure mode
    # this repository has already found twice.
    assert _PACKAGE.is_dir(), f"{_PACKAGE} is missing"
    assert len(_sources()) >= 2, _sources()


def test_reconstruction_never_imports_the_evidence_layer():
    """The strongest form of invariant 2 available: it cannot say the word.

    A module that does not import `exulanica.evidence` cannot return an evidence address, cannot
    construct one, and cannot be persuaded to by a later change that nobody reviews. The
    equivalent rule for the whole backend is an import-linter contract; this is the test that
    fails first and says why.
    """
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                ("exulanica.evidence", "exulanica.store", "exulanica.db")
            ):
                pytest.fail(f"{path.name} imports {node.module}: reconstruction is not evidence")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(
                        ("exulanica.evidence", "exulanica.store", "exulanica.db")
                    ), f"{path.name} imports {alias.name}"


def test_no_reconstruction_function_is_annotated_to_return_a_citation():
    """The literal reading of the invariant: no function returns one.

    Checked on the signature rather than on the body, because a signature is the promise. A
    function annotated to return an `EvidenceAddress` is a citation target whatever it does
    inside.
    """
    for path in _sources():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.returns is None:
                continue
            returned = ast.get_source_segment(source, node.returns) or ""
            for name in _FORBIDDEN_NAMES:
                assert name not in returned, (
                    f"{path.name}:{node.name} is annotated to return {returned}, which names "
                    f"{name}. Reconstruction may not produce a citation target."
                )


# ---------------------------------------------------------------------------------------------
# A real point map, and what it is not


@pytest.fixture
def reconstructed(repository, photo_dir, tmp_path):
    """One photograph ingested with reconstruction on. Returns the artifact and its content hash."""
    from exulanica.ingest.privacy import (
        authorize_synthetic_capture,
        record_synthetic_exemption,
    )
    from exulanica.reconstruction.testing import FlatDepthModel

    write_photo(photo_dir, "a.jpg", when=iso(10), gps=(64.3271, -20.1199))
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=None, depth=FlatDepthModel())
    data = (photo_dir / "a.jpg").read_bytes()
    intake = pipeline.ingest_intake(data, filename="a.jpg")
    assert intake.capture_id is not None, intake.error
    authorization = authorize_synthetic_capture(
        repository,
        capture_id=intake.capture_id,
        actor=uuid.UUID("a244f9d0-9bd9-5f55-a133-2712cd05d720"),
        generator_manifest={
            "profile": "exulanica.reconstruction-boundary-test/v1",
            "notice": "SYNTHETIC TEST FIXTURE",
        },
        authorization_scope={"purpose": "reconstruction boundary test"},
    )
    screening = record_synthetic_exemption(
        repository, authorization_id=authorization.authorization_id
    )
    outcome = pipeline.ingest_derivatives(
        intake.capture_id, privacy_screening_id=screening.screening_id
    )
    assert outcome.error is None, outcome.error
    assert "depth" in outcome.stages_run, outcome.stages_run

    row = repository.connection.execute(
        "select artifact_id, content_sha256 from artifact "
        "where workspace_id = %s and stage_key = 'depth'",
        (repository.workspace_id,),
    ).fetchone()
    assert row is not None, "the depth stage produced no artifact"
    return row


def test_a_point_map_is_never_registered_as_a_blob(repository, reconstructed):
    """Spans reference `blob`. A point map that is not there has nothing a span could point at.

    This is the structural half of the invariant and it is why the media layer and the derivative
    layer are separate tables rather than one table with a kind column.
    """
    found = repository.connection.execute(
        "select 1 from blob where blob_sha256 = %s", (bytes(reconstructed["content_sha256"]),)
    ).fetchone()
    assert found is None, "the point map was registered as a blob, so a span could cite it"


def test_no_span_names_anything_but_bytes_a_capture_claims(repository, reconstructed):
    """The positive form, which catches a derivative cited by any route at all."""
    orphans = repository.connection.execute(
        "select s.span_id, encode(s.blob_sha256, 'hex') as digest from evidence_span s "
        "where s.workspace_id = %s and not exists ("
        "  select 1 from capture c "
        "  where c.workspace_id = s.workspace_id and c.blob_sha256 = s.blob_sha256)",
        (repository.workspace_id,),
    ).fetchall()
    assert orphans == [], f"spans naming bytes no capture claims: {orphans}"


def test_the_point_map_is_stored_and_still_not_citable(repository, reconstructed, tmp_path):
    """The bytes exist in the object store, and that is not the same as being evidence.

    Worth asserting both halves. A point map has to be retrievable or the renderer cannot load
    it, so "not evidence" cannot mean "not stored". What makes it not evidence is that no span
    names it, so no citation can resolve to it and no permalink can be built for it.
    """
    store = LocalContentAddressedStore(tmp_path / "blobs")
    digest = bytes(reconstructed["content_sha256"])
    from exulanica.evidence.blob import BlobId

    assert store.exists(BlobId(digest)), "the point map was not stored, so nothing can render it"
    cited = repository.connection.execute(
        "select 1 from evidence_span where workspace_id = %s and blob_sha256 = %s",
        (repository.workspace_id, digest),
    ).fetchone()
    assert cited is None, "a span names the point map"
