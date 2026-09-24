"""Two worlds in one workspace holding every kind of state a World Memory Package projects.

The default world holds the environment-bearing lineage, both kinds of environment availability,
an undone environment addition and its schema version 1 branch, a version on a source a deletion
invalidated, and behaviour edits with and without a placed environment. The starter world holds a
placed photograph point map and a branch that copied it, beside authored objects, a behaviour edit
and an environment placement given motion. Around them the workspace holds what every 1.0
component reads: photographs with their derivatives and pipeline history, a deleted photograph and
its tombstone, a person who withdrew beside one who did not, a current structure, style and
interaction policy.

Every identifier the database mints is random, so nothing here is a golden by itself.
:func:`normalised_package` turns an exported package into a document that is the same on every
run: random tokens become labels numbered in a canonical order, and lists whose order the random
identifiers decide are sorted by what is left.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from exulanica.consent.regions import Silhouette, region_key
from exulanica.environment import (
    DerivedEnvironmentAsset,
    EnvironmentFeatureInput,
    EnvironmentRepository,
    FeatureIndexPublication,
    SourceAdmission,
)
from exulanica.evidence.region import DisplayGeometry, Rect
from exulanica.ingest import person_review
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.world import (
    AuthoredObject,
    ElementOverride,
    EnvironmentPlacement,
    EnvironmentSelection,
    ObjectBehaviour,
    ObjectOrigin,
    ProposalOrigin,
    ProposalProvenance,
    SourceAnchor,
    Transform,
    WorldInteractionPolicyRepository,
    WorldObjectRepository,
    WorldStructureRepository,
)
from exulanica.world.interaction import InteractionProposal
from exulanica.world_package.package import MANIFEST_PATH, REQUIRED_PAYLOAD_PATHS, SIGNATURE_PATH

from conftest import iso, write_photo
from test_world_environment_composition_postgres import _bounds, _frame, _rights
from test_world_package_extension_postgres import CUBE, MOTION
from test_world_package_withdrawal_postgres import EARLIER, KEPT, WITHDRAWN, _named
from world_structure_fixtures import structural_candidate
from world_support import registered_world

#: A second reviewed behaviour value, so a behaviour edit changes something a person can see.
SLOWER = ObjectBehaviour(
    "motion.bounded-path",
    1,
    {"axis": "z", "easing": "smooth", "period_milliseconds": 9_000, "travel_mm": 1_500},
)

#: The parent Merkle root every golden export names, so provenance/package.json carries one.
PARENT_ROOT = hashlib.sha256(b"rich fixture world parent root").hexdigest()

#: The explicit evaluation report every golden export includes.
EVALUATION_REPORT = {"metric": "fixture", "passed": True, "suite": "rich-world"}


@dataclass
class RichWorld:
    """The workspace, its two worlds, the store availability is read from, and what was made."""

    repository: Any
    store: Any
    default_world: str
    starter_world: str
    evaluation_report: Path
    versions: dict[str, uuid.UUID] = field(default_factory=dict)


def _transform(x_mm: int = 0, *, yaw: int = 0, scale: int = 1_000) -> Transform:
    return Transform(x_mm, 0, -450, yaw, scale)


def _object(object_id: str, region_id: str, *, behaviour=None, x_mm: int = 1_200):
    return AuthoredObject(
        object_id=object_id,
        asset_sha256=CUBE,
        region_id=region_id,
        transform=_transform(x_mm, yaw=785_398),
        origin=ObjectOrigin("authored", "fictional"),
        behaviour=behaviour,
    )


def _apply(structures: WorldStructureRepository, candidate):
    actor = uuid.uuid4()
    preview = structures.preview(candidate, proposed_by=actor)
    return structures.apply(
        preview.preview_id,
        base_snapshot_id=preview.base_snapshot_id,
        base_graph_sha256=preview.base_graph_sha256,
        base_reconstruction_sha256=preview.base_reconstruction_sha256,
        committed_by=actor,
    )


class _Versions:
    """Create and edit alternate versions by title, keeping each version's latest state."""

    def __init__(self, worlds: WorldObjectRepository, made: dict[str, uuid.UUID]) -> None:
        self.worlds = worlds
        self.made = made

    def create(self, title: str, *, source=None, parent: str | None = None):
        version = self.worlds.create_version(
            source_snapshot_id=source,
            parent_version_id=None if parent is None else self.made[parent],
            title=title,
            created_by=uuid.uuid4(),
        )
        self.made[title] = version.version_id
        return version

    def state(self, title: str) -> str:
        return self.worlds.version(self.made[title]).state_sha256

    def edit(self, title: str, method: str, *args: Any) -> Any:
        return getattr(self.worlds, method)(
            self.made[title], *args, base_state_sha256=self.state(title), actor=uuid.uuid4()
        )

    def undo(self, title: str) -> Any:
        return self.worlds.undo(
            self.made[title], base_state_sha256=self.state(title), actor=uuid.uuid4()
        )


@dataclass(frozen=True)
class _Environment:
    source: SourceAdmission
    render: DerivedEnvironmentAsset
    publication: Any
    feature_id: str

    def placement(self, instance_id: str, region_id: str, *, feature: bool = False):
        return EnvironmentPlacement(
            instance_id=instance_id,
            admission_id=self.source.admission_id,
            render_asset_id=self.render.asset_id,
            publication_id=self.publication.publication_id if feature else None,
            selection=EnvironmentSelection(
                "feature" if feature else "whole_asset",
                self.feature_id if feature else None,
                7 if feature else None,
            ),
            source_anchor=SourceAnchor("nyc-grid", 1000, (10, 20, 0)),
            region_id=region_id,
            transform=Transform(0, 0, 0, 0, 1000),
            origin=ObjectOrigin("authored", "fictional"),
        )


def _admit_environment(repository, store, tmp_path: Path, label: str) -> _Environment:
    """One admitted source, its render and a published feature index, as the product admits them."""
    actor = uuid.uuid4()
    place_id = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place_id),
    )
    environments = EnvironmentRepository(repository.connection, repository.workspace_id, store)
    source_bytes = f"exact admitted source {label}".encode()
    source_path = tmp_path / f"{label}-source.bin"
    source_path.write_bytes(source_bytes)
    source = SourceAdmission(
        place_id=place_id,
        provider_key="nyc-open-data",
        provider_original_id=f"corridor-{label}",
        provider_revision="2026-09-12",
        expected_sha256=hashlib.sha256(source_bytes).hexdigest(),
        expected_byte_size=len(source_bytes),
        source_path=f"fixture/{label}-source.bin",
        media_type="application/octet-stream",
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
        operation_rights=_rights(),
        attribution="Synthetic fixture",
        modification_notice="Synthetic fixture is unchanged",
        local_path=source_path,
    )
    environments.admit_source(source, actor=actor)
    render_bytes = f"exact bounded render {label}".encode()
    render_path = tmp_path / f"{label}-render.glb"
    render_path.write_bytes(render_bytes)
    render = DerivedEnvironmentAsset(
        admission_id=source.admission_id,
        expected_sha256=hashlib.sha256(render_bytes).hexdigest(),
        expected_byte_size=len(render_bytes),
        media_type="model/gltf-binary",
        derivation_kind="fixture-render",
        derivation_lineage={"method": "fixture/v1", "input_sha256": [source.expected_sha256]},
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
        operation_rights=_rights(),
        attribution="Synthetic fixture",
        modification_notice="Synthetic render fixture",
        local_path=render_path,
    )
    environments.register_derived(render, actor=actor)
    publication = environments.publish_feature_index(
        source.admission_id,
        FeatureIndexPublication(
            render_asset_id=render.asset_id,
            features=(
                EnvironmentFeatureInput(
                    provider_feature_id=f"doitt_id:{label}",
                    kind="building",
                    bbox=(0, 0, 0, 100, 100, 100),
                    label="Fixture building",
                    render_batch_id=7,
                ),
            ),
        ),
        actor=actor,
    )
    return _Environment(source, render, publication, publication.features[0]["id"])


def _people(repository, store, photo_dir: Path) -> None:
    """Two named people and a person subject in one photograph; the first then withdraws."""
    actor = uuid.uuid4()
    write_photo(photo_dir, "people.jpg", when=iso(9))
    intake = PhotoIngestPipeline(repository, store, detector=None).ingest_intake(
        (photo_dir / "people.jpg").read_bytes(), filename="people.jpg"
    )
    assert intake.capture_id is not None, intake.error
    blob_id = repository.capture(intake.capture_id).blob_id
    withdrawing = _named(repository, WITHDRAWN, actor, earlier=EARLIER)
    _named(repository, KEPT, actor)
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
    person_review.record_consent(
        repository,
        subject_id=subject_id,
        actor=actor,
        consent_scope="likeness",
        decision="withdrawn",
    )


def _interaction_policy(repository, snapshot, world_id: str) -> None:
    policies = WorldInteractionPolicyRepository(
        repository.connection, repository.workspace_id, world_id=world_id
    )
    proposal = InteractionProposal(
        uuid.uuid4(),
        ProposalProvenance(ProposalOrigin.USER, uuid.uuid4()),
        {"comfort.vignette": "strong"},
        None,
        snapshot.snapshot_id,
        snapshot.digests.topology_sha256,
        {"source": "settings"},
        "Apply one reviewed comfort capability.",
        ("settings",),
    )
    preview = policies.preview(proposal)
    policies.apply(
        preview.preview_id,
        base_policy_version_id=None,
        base_structure_snapshot_id=snapshot.snapshot_id,
        base_topology_sha256=snapshot.digests.topology_sha256,
        applied_by=uuid.uuid4(),
    )


def build_rich_world(repository, placed, photo_dir: Path, tmp_path: Path) -> RichWorld:
    """Build both worlds on top of the placed-point-map fixture, which made the starter world."""
    store = placed.api.store
    made: dict[str, uuid.UUID] = {}
    pipeline = PhotoIngestPipeline(repository, store, vision=None)

    # -- the workspace: photographs, people, a deletion -------------------------------------------
    kept = pipeline.ingest_file(write_photo(photo_dir, "kept.jpg", when=iso(10)))
    assert kept.error is None, kept.error
    doomed_photo = pipeline.ingest_file(write_photo(photo_dir, "doomed.jpg", when=iso(11)))
    assert doomed_photo.error is None, doomed_photo.error
    _people(repository, store, photo_dir)
    doomed_evidence = repository.connection.execute(
        "select s.span_id,c.capture_id from evidence_span s join capture c "
        "on c.workspace_id=s.workspace_id and c.blob_sha256=s.blob_sha256 "
        "where s.workspace_id=%s and c.capture_id=%s order by s.span_id limit 1",
        (repository.workspace_id, doomed_photo.capture_id),
    ).fetchone()

    # -- the default world: a source a deletion will invalidate, then the current one -----------
    default_world = registered_world(repository.connection, repository.workspace_id)
    structures = WorldStructureRepository(
        repository.connection, repository.workspace_id, world_id=default_world
    )
    dependent = _apply(
        structures,
        structural_candidate(
            graph="graph-with-source", evidence_span_id=doomed_evidence["span_id"]
        ),
    )
    worlds = WorldObjectRepository(
        repository.connection, repository.workspace_id, world_id=default_world, store=store
    )
    default = _Versions(worlds, made)
    default.create("Doomed", source=dependent.snapshot_id)
    current = _apply(structures, structural_candidate(graph="graph-final"))
    _interaction_policy(repository, current, default_world)
    source = current.snapshot_id

    default.create("Evening study", source=source)
    default.edit(
        "Evening study", "add_object", _object("object:lantern", "region-a", behaviour=MOTION)
    )
    default.edit("Evening study", "move_object", "object:lantern", _transform(2_400, scale=1_500))

    default.create("Variation", parent="Evening study")
    default.edit(
        "Variation",
        "set_element_override",
        ElementOverride("element:region-b:root", suppressed=True),
    )

    default.create("Shifted structure", source=source)
    default.edit(
        "Shifted structure",
        "set_element_override",
        ElementOverride(
            "element:region-a:root",
            suppressed=False,
            transform=Transform(500, 0, 0, 1_570_796, 1_000),
        ),
    )

    default.create("Empty again", source=source)
    default.edit("Empty again", "add_object", _object("object:bench", "region-b"))
    default.undo("Empty again")

    default.create("Put away", source=source)
    default.edit("Put away", "add_object", _object("object:chair", "region-b", behaviour=MOTION))
    default.edit("Put away", "remove_object", "object:chair")

    default.create("Moved on later", source=source)
    default.edit("Moved on later", "add_object", _object("object:kite", "region-a"))
    default.edit("Moved on later", "set_object_behaviour", "object:kite", SLOWER)
    default.create("Branch of it", parent="Moved on later")

    plaza = _admit_environment(repository, store, tmp_path, "plaza")
    closed = _admit_environment(repository, store, tmp_path, "closed")

    default.create("Plaza evening", parent="Evening study")
    default.edit(
        "Plaza evening", "add_environment", plaza.placement("environment:plaza", "region-a")
    )
    default.create("Plaza night", parent="Plaza evening")
    default.edit(
        "Plaza night",
        "move_environment",
        "environment:plaza",
        Transform(5_000, 0, 0, 0, 1_000),
    )

    default.create("Corridor", source=source)
    default.edit(
        "Corridor",
        "add_environment",
        plaza.placement("environment:corridor", "region-b", feature=True),
    )
    default.edit(
        "Corridor",
        "add_environment",
        closed.placement("environment:closed", "region-a"),
    )

    default.create("Undone plaza", source=source)
    default.edit("Undone plaza", "add_environment", plaza.placement("environment:gone", "region-a"))
    default.undo("Undone plaza")
    default.create("After the plaza", parent="Undone plaza")
    default.edit("After the plaza", "add_object", _object("object:sign", "region-b"))

    default.create("Plaza with motion", source=source)
    default.edit(
        "Plaza with motion", "add_environment", plaza.placement("environment:fair", "region-a")
    )
    default.edit("Plaza with motion", "add_object", _object("object:flag", "region-a"))
    default.edit("Plaza with motion", "set_object_behaviour", "object:flag", MOTION)

    EnvironmentRepository(repository.connection, repository.workspace_id, store).withdraw(
        "asset", closed.render.asset_id
    )
    repository.insert_tombstone(
        scope="capture",
        capture_id=doomed_evidence["capture_id"],
        requested_by=uuid.uuid4(),
        reason="the source photograph was deleted",
    )
    assert worlds.version(made["Doomed"]).source_invalidated is True

    # -- the starter world: a placed point map, its branch, objects and a behaviour edit --------
    applied = placed.apply()
    assert applied.status_code == 201, applied.text
    starter_worlds = placed.worlds()
    starter = _Versions(starter_worlds, made)
    made["Starter with a point map"] = uuid.UUID(placed.version_id)
    starter.create("Kitchen copy", parent="Starter with a point map")
    assert starter_worlds.version(made["Kitchen copy"]).point_map_instances
    starter_source = starter_worlds.version(made["Starter with a point map"]).source_snapshot_id
    starter.create("Starter lantern", source=starter_source)
    starter.edit(
        "Starter lantern",
        "add_object",
        _object("object:lantern", placed.region_id, behaviour=MOTION),
    )
    starter.create("Starter kite", source=starter_source)
    starter.edit("Starter kite", "add_object", _object("object:kite", placed.region_id))
    starter.edit("Starter kite", "set_object_behaviour", "object:kite", SLOWER)
    # Environment-bearing and withheld: authored-world 1.0 alone counts it in its one total
    # instead of refusing, since nothing environment-bearing is left to export.
    starter.create("Starter fair", source=starter_source)
    starter.edit(
        "Starter fair", "add_environment", plaza.placement("environment:fair", placed.region_id)
    )
    starter.edit("Starter fair", "add_object", _object("object:flag", placed.region_id))
    starter.edit("Starter fair", "set_object_behaviour", "object:flag", MOTION)

    report = tmp_path / "evaluation-report.json"
    report.write_text(json.dumps(EVALUATION_REPORT, sort_keys=True), encoding="utf-8")
    repository.connection.commit()
    return RichWorld(
        repository=repository,
        store=store,
        default_world=default_world,
        starter_world=placed.entry["world_id"],
        evaluation_report=report,
        versions=made,
    )


# ------------------------------------------------------------------------------------------------
# Normalisation
# ------------------------------------------------------------------------------------------------

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_URN = re.compile(r"urn:exulanica:wmp:(?P<kind>[a-z-]+):(?P<digest>[0-9a-f]{64})")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
_WILD = "*"
CRATE_PATH: Final = "ro-crate-metadata.json"
#: The 1.0 payloads an extension leaves byte-identical. The crate lists every file, so it is
#: not one of them.
BASE_PAYLOADS: Final = REQUIRED_PAYLOAD_PATHS - {CRATE_PATH}


#: Fields whose value is a measurement of this run rather than of the world: how long a pipeline
#: stage took. They are replaced outright, since no other value can equal them.
_MEASURED_FIELDS: Final = frozenset({"duration_ms"})


def _wild(value: Any, *, digests: bool) -> Any:
    """The value with every identifier replaced by one wildcard, for ordering only.

    With ``digests`` true, SHA-256 values and times are wildcarded too, which is the first sort
    key: an edit's digests can be random while its sequence number is not. The second key keeps
    them, because most digests are of fixed content (a photograph's bytes, a reviewed asset) and
    a photograph's capture time is in its bytes, so they are the only thing telling apart two
    items that differ in nothing else, such as the evidence spans of two photographs. A time the
    database wrote differs between runs but keeps its order, because the fixture makes everything
    in one fixed sequence.
    """
    if isinstance(value, dict):
        return {
            key: _WILD if key in _MEASURED_FIELDS else _wild(child, digests=digests)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_wild(child, digests=digests) for child in value]
    if isinstance(value, str):
        if digests and (_HEX64.fullmatch(value) or _TIME.fullmatch(value)):
            return _WILD
        return _UUID.sub(_WILD, _URN.sub(lambda m: f"urn:exulanica:wmp:{m['kind']}:*", value))
    return value


def _sort_key(value: Any) -> tuple[str, str]:
    return (
        json.dumps(_wild(value, digests=True), sort_keys=True),
        json.dumps(_wild(value, digests=False), sort_keys=True),
    )


def _names_an_identifier(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_names_an_identifier(child) for child in value.values())
    if isinstance(value, list):
        return any(_names_an_identifier(child) for child in value)
    return isinstance(value, str) and bool(_UUID.search(value) or _URN.search(value))


def _ordered(value: Any) -> Any:
    """Sort each list of records that names identifiers, refusing a tie only an id would break.

    A list of records that names identifiers may be ordered by one, so its order can differ
    between runs, and it is sorted by what is left. Every other list keeps the order it was
    exported in, so the golden pins that order too: plain values are stored arrays (the spans an
    assertion cites, the artifacts a pipeline event wrote) or sorted by a fixed name, and records
    that name no identifier, such as the crate's graph, cannot be ordered by one.
    """
    if isinstance(value, dict):
        return {key: _ordered(child) for key, child in value.items()}
    if isinstance(value, list):
        children = [_ordered(child) for child in value]
        if not all(isinstance(child, dict) for child in children) or not any(
            _names_an_identifier(child) for child in children
        ):
            return children
        keyed = sorted(((_sort_key(child), child) for child in children), key=lambda p: p[0])
        for (first, a), (second, b) in itertools.pairwise(keyed):
            if first == second and json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True):
                raise AssertionError(
                    "two items differ only in identifiers, so no stable order exists: "
                    f"{first[1][:200]}"
                )
        return [child for _, child in keyed]
    return value


class _Labels:
    def __init__(self) -> None:
        self.labels: dict[tuple[str, str], str] = {}
        self.counts: dict[str, int] = {}

    def label(self, family: str, token: str) -> str:
        key = (family, token)
        if key not in self.labels:
            self.counts[family] = self.counts.get(family, 0) + 1
            self.labels[key] = f"<{family}:{self.counts[family]}>"
        return self.labels[key]

    def value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: f"<{key}>" if key in _MEASURED_FIELDS else self.value(value[key])
                for key in sorted(value)
            }
        if isinstance(value, list):
            return [self.value(child) for child in value]
        if isinstance(value, str):
            if _HEX64.fullmatch(value):
                return self.label("sha256", value)
            if _TIME.fullmatch(value):
                return self.label("time", value)
            value = _URN.sub(
                lambda m: (
                    f"urn:exulanica:wmp:{m['kind']}:"
                    + self.label("urn", f"{m['kind']}:{m['digest']}")
                ),
                value,
            )
            return _UUID.sub(lambda m: self.label("uuid", m.group(0)), value)
        return value


def normalised_package(output: Path) -> dict[str, Any]:
    """Every file of a package as a document that is the same on every run of the fixture.

    Random tokens (UUIDs, WMP URNs, SHA-256 hex values and times) become labels numbered in the
    order a canonical walk meets them, so equal tokens keep equal labels across the whole package
    and the golden still pins which values are the same. The walk takes the 1.0 payloads first,
    then any extension, then ``ro-crate-metadata.json``, so a 1.0 payload gets the same labels
    whichever extensions ride beside it. The manifest and signature are left out: they are
    functions of the bytes pinned here.
    """
    documents = {
        str(path.relative_to(output)): json.loads(path.read_bytes())
        for path in output.rglob("*.json")
        if str(path.relative_to(output)) not in {MANIFEST_PATH, SIGNATURE_PATH}
    }
    labels = _Labels()
    return {path: labels.value(_ordered(documents[path])) for path in walk_order(documents)}


def walk_order(paths) -> list[str]:
    """The 1.0 payloads but the crate, then every other payload, then the crate, each sorted."""
    base = sorted(path for path in paths if path in BASE_PAYLOADS)
    rest = sorted(path for path in paths if path not in BASE_PAYLOADS and path != CRATE_PATH)
    return base + rest + ([CRATE_PATH] if CRATE_PATH in paths else [])


def canonical_text(value: Any) -> str:
    return json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
