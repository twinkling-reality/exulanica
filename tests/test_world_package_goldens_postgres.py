"""Every file of a rich world's package, under every extension combination, against its golden.

The fixture (``world_package_rich_world``) holds each kind of state the projector reads, in two
worlds of one workspace, and :func:`normalised_package` removes only what differs between runs:
identifiers, times the database wrote, digests of those, and how long a pipeline stage took. What
is left is pinned file by file in ``tests/fixtures/wmp-goldens/<world>.json``: the 1.0 payloads
once, since no extension may change them; every other document once, by the first 16 hex digits of
the SHA-256 of its normalised text; and for each combination the document each of its extension
files and its crate is, or the refusal it ends in.

The combinations are every subset of the extension versions the projector accepts, so the
refusal of two versions of one extension is pinned too.

A golden is never rewritten by a test. On a mismatch the new document is written beside the
test's temporary files and the failure names it; a person reviews it and copies it over.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exulanica.world import WorldObjectRepository
from exulanica.world.authored_delta import DELTA_SECTIONS
from exulanica.world.edit_kinds import EditSubject
from exulanica.world_package import extension_projection, project_world_package, verify_package
from exulanica.world_package.extension_formats import FORMATS
from exulanica.world_package.package import PackageError
from psycopg.rows import dict_row

from test_photo_point_map_composition import placed as imported_placed  # noqa: F401
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401
from world_package_rich_world import (
    BASE_PAYLOADS,
    PARENT_ROOT,
    build_rich_world,
    canonical_text,
    normalised_package,
)

pytestmark = pytest.mark.postgres

GOLDENS = Path(__file__).resolve().parent / "fixtures" / "wmp-goldens"
#: Why the no-extension export of each world is the source of its 1.0 payloads.
NO_EXTENSION = "no extension"


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


@pytest.fixture(name="placed")
def _placed_alias(request):
    return request.getfixturevalue("imported_placed")


#: Every extension version the projector accepts, read from the one list that defines them, so
#: an extension version added there without a golden fails here rather than going unpinned.
SUPPORTED_EXTENSIONS = frozenset(format_.key for format_ in FORMATS)


def combinations() -> list[tuple[str, tuple[str, ...]]]:
    """Every subset of the supported extensions, named by its members in sorted order."""
    keys = sorted(SUPPORTED_EXTENSIONS)
    subsets = [
        tuple(chosen)
        for size in range(len(keys) + 1)
        for chosen in itertools.combinations(keys, size)
    ]
    return [(" + ".join(subset) if subset else NO_EXTENSION, subset) for subset in subsets]


def _export(world, world_id: str, output: Path, extensions: tuple[str, ...]):
    return project_world_package(
        world.repository.connection,
        workspace_id=world.repository.workspace_id,
        actor=uuid.uuid4(),
        output=output,
        private_key=Ed25519PrivateKey.generate(),
        world_id=world_id,
        parent_merkle_root_sha256=PARENT_ROOT,
        evaluation_reports=[world.evaluation_report],
        extensions=extensions,
        store=world.store,
    )


def _actual(world, world_id: str, tmp_path: Path) -> dict:
    """The golden document: the 1.0 payloads once, each other document once by its digest."""
    base: dict | None = None
    documents: dict[str, object] = {}
    exports: dict[str, dict] = {}
    for name, extensions in combinations():
        output = tmp_path / f"{world_id.replace(':', '-')}-{len(exports)}.wmp"
        try:
            result = _export(world, world_id, output, extensions)
        except PackageError as refusal:
            assert not output.exists(), f"{name}: a refused package was published"
            exports[name] = {"refused": str(refusal)}
            continue
        verify_package(result.output)
        files = normalised_package(result.output)
        payloads = {path: document for path, document in files.items() if path in BASE_PAYLOADS}
        if base is None:
            assert name == NO_EXTENSION, "the no-extension export is taken first"
            base = payloads
        # No extension may change a 1.0 payload; the crate is the one 1.0 file that lists them.
        for path, document in payloads.items():
            assert document == base[path], f"{name}: 1.0 payload {path} differs from {NO_EXTENSION}"
        named: dict[str, str] = {}
        for path, document in files.items():
            if path in BASE_PAYLOADS:
                continue
            digest = hashlib.sha256(canonical_text(document).encode()).hexdigest()[:16]
            documents[digest] = document
            named[path] = digest
        exports[name] = {"files": named}
    return {"base": base, "documents": documents, "exports": exports}


def _resolved(golden: dict) -> dict[str, dict]:
    """Each combination's files as documents, or its refusal."""
    return {
        name: (
            {"refused": export["refused"]}
            if "refused" in export
            else {path: golden["documents"][digest] for path, digest in export["files"].items()}
        )
        for name, export in golden["exports"].items()
    }


def _compare(actual: dict, golden_name: str, tmp_path: Path) -> None:
    path = GOLDENS / f"{golden_name}.json"
    written = tmp_path / f"{golden_name}.actual.json"
    written.write_text(canonical_text(actual), encoding="utf-8")
    assert path.is_file(), f"no golden {path}; review {written} and copy it there"
    golden = json.loads(path.read_text(encoding="utf-8"))
    expected, found = _resolved(golden), _resolved(actual)
    differing = sorted(
        {
            f"base {key}"
            for key in golden["base"].keys() | actual["base"].keys()
            if golden["base"].get(key) != actual["base"].get(key)
        }
        | {
            f"{name}: {key}"
            for name in expected.keys() | found.keys()
            for key in expected.get(name, {"(absent)": None}).keys()
            | found.get(name, {"(absent)": None}).keys()
            if expected.get(name, {}).get(key) != found.get(name, {}).get(key)
        }
    )
    assert not differing, (
        f"{golden_name} differs from its golden in {differing}; the new document is {written}"
    )
    assert golden == actual, f"{golden_name} holds a document no combination uses; see {written}"


def test_the_default_world_matches_its_golden_under_every_combination(
    repository, placed, photo_dir, tmp_path
):
    world = build_rich_world(repository, placed, photo_dir, tmp_path)
    _compare(_actual(world, world.default_world, tmp_path), "default-world", tmp_path)


def test_the_starter_world_matches_its_golden_under_every_combination(
    repository, placed, photo_dir, tmp_path
):
    world = build_rich_world(repository, placed, photo_dir, tmp_path)
    _compare(_actual(world, world.starter_world, tmp_path), "starter-world", tmp_path)


def test_the_plane_reader_states_what_the_repository_reads(repository, placed, photo_dir, tmp_path):
    """The export plan's inputs, read with the projector's own queries, against the product's.

    The projector reads the plane directly so that it names no edit kind; the repository reads the
    same versions for every route. For every version of both worlds the two must agree on the
    chain's kinds and subjects, the sections the state holds, the parent and the invalidation.
    """
    world = build_rich_world(repository, placed, photo_dir, tmp_path)
    compared = 0
    for world_id in (world.default_world, world.starter_world):
        worlds = WorldObjectRepository(
            repository.connection, repository.workspace_id, world_id=world_id, store=world.store
        )
        with repository.connection.cursor(row_factory=dict_row) as cursor:
            plane = extension_projection._plane_versions(
                cursor, world_id, workspace_id=repository.workspace_id
            )
        for version in plane:
            stored = worlds.version(version.version_id)
            assert version.parent_version_id == stored.parent_version_id
            assert version.source_invalidated == stored.source_invalidated
            assert version.chain_kinds == {edit.kind for edit in stored.edits}
            assert version.chain_subjects == {
                subject
                for edit in stored.edits
                for subject in EditSubject
                if getattr(edit, subject.column) is not None
            }
            assert version.state_sections == {
                section.key for section in DELTA_SECTIONS if getattr(stored, section.key)
            }
            compared += 1
    assert compared == len(world.versions), "every version the fixture made was compared"
