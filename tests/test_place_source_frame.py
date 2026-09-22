"""A place whose frame a provider documented, and the bytes a refused admission must not leave.

Two things are established here. The first is that a canonical place can exist for geography
that no reconstruction produced, and that the way it exists says so: ``frame_authority`` records
that the frame was declared, never measured, and 0091 refuses a place that would carry both
authorities at once, because relating a recovered COLMAP frame to a geographic CRS is
georeferencing and nothing in this repository measures it.

The second is an ordering. Admission verifies bytes, then writes a row, then stores the bytes.
A refused admission therefore leaves nothing behind. The test named for it fails against the
order this module used before: the store was written first, so a request naming a place that did
not exist answered 404 and left an unreferenced blob on disk.
"""

from __future__ import annotations

import ast
import hashlib
import uuid
from pathlib import Path

import psycopg
import pytest
from exulanica.environment import (
    DeclaredPlaceFrame,
    EnvironmentAdmissionRefused,
    EnvironmentRepository,
    GeographicBounds,
    GeographicFrame,
    OperationRights,
    PlaceFrameConflict,
    SourceAdmission,
    UnknownEnvironmentResource,
    place_frame_receipt,
)
from exulanica.errors import BlobNotFoundError
from exulanica.evidence.blob import BlobId
from exulanica.ingest.place_alignment import establish_place
from exulanica.ingest.spine import places
from exulanica.ingest.spine.scope import WorkspaceScope
from exulanica.store.local import LocalContentAddressedStore

pytestmark = pytest.mark.postgres

SOURCE = Path(__file__).resolve().parent.parent / "exulanica"


def _frame(name: str = "synthetic-district-crs84") -> GeographicFrame:
    return GeographicFrame(
        name=name,
        crs="OGC:CRS84",
        axis_order=("longitude", "latitude"),
        horizontal_unit="degree",
        vertical_unit="not_applicable",
        orientation="east-north",
        altitude_reference="not_applicable_2d",
    )


def _bounds(
    *coordinates: int, kind: str = "bbox", name: str = "synthetic-district-crs84"
) -> GeographicBounds:
    return GeographicBounds(
        kind=kind,
        frame_name=name,
        coordinate_scale=1000,
        coordinates=coordinates or (0, 0, 1000, 1000),
    )


def _rights(**changes: bool) -> OperationRights:
    values = {
        "display": True,
        "extract": True,
        "index": True,
        "persist": True,
        "modify": True,
        "compose": True,
        "export": False,
        "model_processing": False,
    }
    values.update(changes)
    return OperationRights.model_validate(values)


def _declaration(**changes) -> DeclaredPlaceFrame:
    values = {
        "provider_key": "synthetic-open-data",
        "provider_frame_statement": (
            "The provider publishes this extract in OGC:CRS84, longitude then latitude, "
            "in degrees, with no vertical component."
        ),
        "geographic_frame": _frame(),
        "geographic_bounds": _bounds(),
    }
    values.update(changes)
    return DeclaredPlaceFrame.model_validate(values)


def _admission(path: Path, place_id: uuid.UUID, data: bytes, **changes) -> SourceAdmission:
    values = {
        "place_id": place_id,
        "provider_key": "synthetic-open-data",
        "provider_original_id": "district-extract",
        "provider_revision": "2026-09-01",
        "expected_sha256": hashlib.sha256(data).hexdigest(),
        "expected_byte_size": len(data),
        "source_path": "https://example.invalid/district-extract.geojson",
        "media_type": "application/geo+json",
        "geographic_frame": _frame(),
        "geographic_bounds": _bounds(100, 100, 900, 900),
        "operation_rights": _rights(),
        "attribution": "Synthetic open data; attribution required.",
        "modification_notice": "Modified outputs must be marked.",
        "local_path": path,
    }
    values.update(changes)
    return SourceAdmission.model_validate(values)


@pytest.fixture
def environment(repository, tmp_path):
    store = LocalContentAddressedStore(tmp_path / "environment-blobs")
    return EnvironmentRepository(repository.connection, repository.workspace_id, store), store


def _staged(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


# -- what a declared frame is, and is not ---------------------------------------------------


def test_a_declared_place_frame_records_a_declaration_and_never_a_measurement(environment):
    repo, _store = environment
    declared = repo.declare_place_frame(_declaration(), actor=uuid.uuid4())

    assert declared.frame_authority == "declared_provider_frame"
    document = declared.document()
    assert document["frame_authority"] == "declared_provider_frame"
    assert document["receipt"]["profile"] == "exulanica.place-source-frame/v1"
    assert document["receipt"]["frame_authority"] == "declared_provider_frame"
    # The digest is reproducible from the declaration alone, so a stored row that drifted from
    # what was declared is visible rather than trusted.
    _record, _encoded, digest = place_frame_receipt(_declaration(place_id=declared.place_id))
    assert document["receipt_sha256"] == digest.hex()


def test_a_source_anchored_place_has_no_scene_history_and_says_so(environment, repository):
    """It is not served as a place with versions, because it has none.

    ``tombstone_blocks_place`` fails closed on a place with no anchor SCENE, and a declared frame
    is not one. A source-anchored place is therefore absent from the scene-addressed place read
    rather than served with an empty or invented history, which is the honest answer: no
    photographs stand behind it and no recovered frame exists to express versions in.
    """
    repo, _store = environment
    declared = repo.declare_place_frame(_declaration(), actor=uuid.uuid4())
    blocked = repository.connection.execute(
        "select tombstone_blocks_place(%s, %s) as blocked",
        (repository.workspace_id, declared.place_id),
    ).fetchone()
    assert blocked["blocked"] is True


def test_a_repeated_declaration_is_the_same_place_and_a_different_one_is_refused(environment):
    repo, _store = environment
    actor = uuid.uuid4()
    first = repo.declare_place_frame(_declaration(), actor=actor)
    again = repo.declare_place_frame(_declaration(place_id=first.place_id), actor=actor)
    assert again.receipt_sha256 == first.receipt_sha256

    with pytest.raises(PlaceFrameConflict):
        repo.declare_place_frame(
            _declaration(place_id=first.place_id, provider_key="another-provider"),
            actor=actor,
        )


def test_a_place_cannot_carry_both_a_measured_and_a_declared_frame(environment, repository):
    """Forged at the database, not only refused by the service.

    A place carrying an anchor scene and a declared frame would assert a correspondence between
    a recovered COLMAP frame and a geographic CRS that nothing here measured, and every read of
    it would have to pick one silently. Both directions are checked, because a guard that only
    holds in the order the service happens to write is a guard against the service.
    """
    repo, _store = environment
    scope = WorkspaceScope(repository.connection, repository.workspace_id)
    declared = repo.declare_place_frame(_declaration(), actor=uuid.uuid4())
    scene_id = _scene(repository)

    with (
        pytest.raises(psycopg.errors.CheckViolation, match="cannot also anchor a scene"),
        repository.connection.transaction(),
    ):
        places.insert_version(
            scope,
            place_id=declared.place_id,
            scene_id=scene_id,
            ordinal=0,
            ordered_by_utc=None,
            ordered_by_basis="unavailable",
            frame_hops=0,
            admitted_by_alignment_id=None,
        )

    measured = uuid.uuid4()
    with repository.connection.transaction():
        places.insert_place(scope, place_id=measured)
        places.insert_version(
            scope,
            place_id=measured,
            scene_id=scene_id,
            ordinal=0,
            ordered_by_utc=None,
            ordered_by_basis="unavailable",
            frame_hops=0,
            admitted_by_alignment_id=None,
        )
    with pytest.raises(EnvironmentAdmissionRefused, match="cannot also declare one"):
        repo.declare_place_frame(_declaration(place_id=measured), actor=uuid.uuid4())


# -- what an admission into a declared place must agree with --------------------------------


def test_an_admitted_source_must_carry_the_frame_its_place_declared(environment, tmp_path):
    repo, _store = environment
    declared = repo.declare_place_frame(_declaration(), actor=uuid.uuid4())
    data = b'{"type":"FeatureCollection","features":[]}'
    path = _staged(tmp_path, "wrong-frame.geojson", data)
    other = _frame("some-other-grid")

    with pytest.raises(EnvironmentAdmissionRefused, match="frame disagrees"):
        repo.admit_source(
            _admission(
                path,
                declared.place_id,
                data,
                geographic_frame=other,
                geographic_bounds=_bounds(100, 100, 900, 900, name="some-other-grid"),
            ),
            actor=uuid.uuid4(),
        )


@pytest.mark.parametrize(
    ("label", "bounds"),
    [
        ("a box reaching outside the declared extent", _bounds(100, 100, 1100, 900)),
        ("a box starting outside the declared extent", _bounds(-10, 100, 900, 900)),
        (
            "a polygon with one vertex outside",
            _bounds(100, 100, 900, 100, 900, 1200, kind="polygon"),
        ),
        (
            "a provider feature identifier, which is not geometry at all",
            _bounds(41297, kind="feature"),
        ),
    ],
)
def test_an_admitted_source_outside_the_declared_bounds_is_refused(
    environment, tmp_path, label, bounds
):
    repo, _store = environment
    declared = repo.declare_place_frame(_declaration(), actor=uuid.uuid4())
    data = label.encode("utf-8")
    path = _staged(tmp_path, "outside.geojson", data)
    with pytest.raises(EnvironmentAdmissionRefused, match="not inside the bounds"):
        repo.admit_source(
            _admission(path, declared.place_id, data, geographic_bounds=bounds),
            actor=uuid.uuid4(),
        )


def test_a_polygon_inside_the_declared_bounds_is_admitted(environment, tmp_path):
    repo, _store = environment
    declared = repo.declare_place_frame(_declaration(), actor=uuid.uuid4())
    data = b"a polygon wholly inside the declared extent"
    path = _staged(tmp_path, "inside.geojson", data)
    admitted = repo.admit_source(
        _admission(
            path,
            declared.place_id,
            data,
            geographic_bounds=_bounds(100, 100, 900, 100, 900, 900, kind="polygon"),
        ),
        actor=uuid.uuid4(),
    )
    assert admitted.receipt["place_id"] == str(declared.place_id)


def test_malformed_bounds_answer_no_rather_than_raising(repository):
    """A containment predicate that errors on bad input refuses nothing; it crashes the write.

    Every case below is something a direct insert could carry that a validated request cannot,
    and each one has to be an answer. The declared side is asked too, because a declaration whose
    own box is malformed must never become the box everything else is measured against.
    """
    row = repository.connection.execute(
        """
        select place_bounds_integers('{"kind":"bbox"}'::jsonb) as no_coordinates,
               place_bounds_integers('{"coordinates":[1.5,2,3,4]}'::jsonb) as fractional,
               place_bounds_integers('{"coordinates":"4"}'::jsonb) as not_an_array,
               place_bounds_integers('{"coordinates":[1,"2",3,4]}'::jsonb) as text_coordinate,
               place_declared_bounds_contain(
                 '{"kind":"polygon","frame_name":"f","coordinate_scale":1,
                   "coordinates":[0,0,1,0,1,1]}'::jsonb,
                 '{"kind":"bbox","frame_name":"f","coordinate_scale":1,
                   "coordinates":[0,0,1,1]}'::jsonb) as declared_is_not_a_box,
               place_declared_bounds_contain(
                 '{"kind":"bbox","frame_name":"f","coordinate_scale":1,
                   "coordinates":[0,0,10,10]}'::jsonb,
                 '{"kind":"bbox","frame_name":"f","coordinate_scale":2,
                   "coordinates":[1,1,9,9]}'::jsonb) as different_scale,
               place_declared_bounds_contain(
                 '{"kind":"bbox","frame_name":"f","coordinate_scale":1,
                   "coordinates":[0,0,10,10]}'::jsonb,
                 '{"kind":"bbox","frame_name":"other","coordinate_scale":1,
                   "coordinates":[1,1,9,9]}'::jsonb) as different_frame,
               place_declared_bounds_contain(
                 '{"kind":"bbox","frame_name":"f","coordinate_scale":1,
                   "coordinates":[0,0,10,10]}'::jsonb,
                 '{"kind":"bbox","frame_name":"f","coordinate_scale":1,
                   "coordinates":[1,1,0,0,9,9,10,10]}'::jsonb) as wrong_dimensions,
               place_declared_bounds_contain(
                 '{"kind":"bbox","frame_name":"f","coordinate_scale":1,
                   "coordinates":[0,0,10,10]}'::jsonb,
                 '{"kind":"bbox","frame_name":"f","coordinate_scale":1,
                   "coordinates":[9,9,1,1]}'::jsonb) as inverted_candidate,
               place_declared_bounds_contain(
                 '{"kind":"bbox","frame_name":"f","coordinate_scale":1,
                   "coordinates":[0,0,10,10]}'::jsonb,
                 '{"kind":"bbox","frame_name":"f","coordinate_scale":1,
                   "coordinates":[0,0,10,10]}'::jsonb) as exactly_the_declared_box
        """
    ).fetchone()
    assert row["no_coordinates"] is None
    assert row["fractional"] is None
    assert row["not_an_array"] is None
    assert row["text_coordinate"] is None
    assert row["declared_is_not_a_box"] is False
    assert row["different_scale"] is False
    assert row["different_frame"] is False
    assert row["wrong_dimensions"] is False
    assert row["inverted_candidate"] is False
    # The one positive control: a candidate equal to the declared box is inside it.
    assert row["exactly_the_declared_box"] is True


# -- the ordering a refusal depends on -------------------------------------------------------


def test_a_refused_admission_leaves_no_bytes_in_the_store(environment, tmp_path):
    """The measured defect, both halves of it.

    The first arm is the reproduction recorded on 2026-09-22: an admission naming a place that
    does not exist answered 404 and had already written the request's bytes, because the store
    was called before the place was looked up. The second arm is the reason the fix is an
    ordering rather than one moved statement: a refusal 0091 raises inside the write is past
    every Python check there is, and only putting the bytes after the row keeps it clean.
    """
    repo, store = environment
    absent = b'{"type":"FeatureCollection","features":[]}'
    absent_path = _staged(tmp_path, "absent-place.geojson", absent)
    absent_id = BlobId(hashlib.sha256(absent).digest())

    with pytest.raises(UnknownEnvironmentResource):
        repo.admit_source(_admission(absent_path, uuid.uuid4(), absent), actor=uuid.uuid4())
    with pytest.raises(BlobNotFoundError):
        store.get(absent_id)

    declared = repo.declare_place_frame(_declaration(), actor=uuid.uuid4())
    refused = b"bytes whose bounds fall outside the declared extent"
    refused_path = _staged(tmp_path, "outside-place.geojson", refused)
    refused_id = BlobId(hashlib.sha256(refused).digest())

    with pytest.raises(EnvironmentAdmissionRefused):
        repo.admit_source(
            _admission(
                refused_path,
                declared.place_id,
                refused,
                geographic_bounds=_bounds(100, 100, 1100, 900),
            ),
            actor=uuid.uuid4(),
        )
    with pytest.raises(BlobNotFoundError):
        store.get(refused_id)


# -- every production path that creates a place ----------------------------------------------


def _insert_place_callers() -> dict[str, set[str]]:
    """Every production function that calls ``places.insert_place``, found by reading the tree.

    Searched rather than listed, so a third creator appears here as a name this test does not
    know instead of passing silently. ``exulanica/ingest/spine/places.py`` itself is where the
    function is defined, which is not a call.
    """
    callers: dict[str, set[str]] = {}
    for path in sorted(SOURCE.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "insert_place(" not in source:
            continue
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call):
                    continue
                target = inner.func
                name = (
                    target.attr
                    if isinstance(target, ast.Attribute)
                    else target.id
                    if isinstance(target, ast.Name)
                    else None
                )
                if name == "insert_place":
                    callers.setdefault(node.name, set()).add(path.relative_to(SOURCE).as_posix())
    return callers


def _scene(repository) -> uuid.UUID:
    """One scene with one member, which is all an anchor needs to be bindable."""
    scene_id, capture_id = uuid.uuid4(), uuid.uuid4()
    digest = uuid.uuid4().bytes * 2
    repository.connection.execute(
        "insert into blob (blob_sha256, byte_size, media_type) values (%s, 1, 'image/jpeg') "
        "on conflict do nothing",
        (digest,),
    )
    repository.connection.execute(
        "insert into reconstruction_scene (scene_id, workspace_id, member_digest) "
        "values (%s, %s, %s)",
        (scene_id, repository.workspace_id, digest),
    )
    repository.connection.execute(
        "insert into capture (capture_id, workspace_id, blob_sha256) values (%s, %s, %s)",
        (capture_id, repository.workspace_id, digest),
    )
    repository.connection.execute(
        "insert into reconstruction_scene_member (workspace_id, scene_id, capture_id, ordinal) "
        "values (%s, %s, %s, 0)",
        (repository.workspace_id, scene_id, capture_id),
    )
    return scene_id


def test_every_production_path_that_creates_a_place_also_anchors_it(environment, repository):
    """A place the product creates always has one of the two frame authorities.

    A bare ``insert into place`` stays legal, because fixtures use it and because an unanchored
    place claims nothing, which is honest. What this holds is narrower and is the part a person
    depends on: nothing the product itself does leaves a place with no frame at all.
    """
    repo, _store = environment
    assert set(_insert_place_callers()) == {"declare_place_frame", "establish_place"}

    scope = WorkspaceScope(repository.connection, repository.workspace_id)
    declared = repo.declare_place_frame(_declaration(), actor=uuid.uuid4())
    assert places.source_frame(scope, place_id=declared.place_id) is not None
    assert places.version(scope, place_id=declared.place_id, scene_id=uuid.uuid4()) is None

    measured = uuid.uuid4()
    scene_id = _scene(repository)
    assert establish_place(repository, place_id=measured, anchor_scene_id=scene_id) is True
    anchor = places.version(scope, place_id=measured, scene_id=scene_id)
    assert anchor is not None and anchor.frame_hops == 0
    assert places.source_frame(scope, place_id=measured) is None
