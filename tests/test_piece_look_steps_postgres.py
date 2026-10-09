"""A world's look takes its passed generated pieces in as they arrive, and gives them back.

The generation worker's look step (``exulanica.generation.apply``) against a migrated database, as
the deployed runtime role writes: a made request's passed pieces become the world's own look (a
workspace style pack version of origin generated, drawn on the library pack the request named),
worn only once its check passed; a take-back writes the world's next appearance without them; a
request drawn on another look, or with nothing passed, is not applied; and a world whose own look is
withdrawn reads as its library base, is never rolled back to it, and takes new pieces on that base.
A world wearing a library pack reads as it did before a world could wear its own.

A made request is written as the owner with triggers off, as the generation worker leaves one: the
request, the installation's index row and the passed output. Its piece is a committed cozy piece
standing in for a generated one, so its colours are the base's palette and its size within its
family's budget, and the style pack check (run here as the asset preparation process runs it)
passes it.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from exulanica.generation import store
from exulanica.generation.apply import REFERENCE_PREFIX, LookStepper
from exulanica.generation.looks import GeneratedVariant, build_derived_look
from exulanica.world import InvalidStyleData, ProposalOrigin, ProposalProvenance, StyleScope
from exulanica.world.errors import StyleWriteBusy
from exulanica.world.models import StylePackBinding
from exulanica.world.repository import WorldStyleRepository
from exulanica.world.style_pack_checks import StylePackCheckWorker, colour_table, library_palettes
from exulanica.world.style_pack_library import style_pack_library
from exulanica.world.style_packs import load_context, read_manifest
from exulanica.world.workspace_style_packs import (
    WorkspaceStylePackRepository,
)
from exulanica_pieces.canonical import canonical_bytes, sha256_hex
from exulanica_pieces.records import POSTPROCESS_VERSION, cache_key

from test_purge import purged as purged
from test_workspace_style_packs_postgres import Packs, admitted
from test_workspace_style_packs_postgres import packs as packs
from test_world_style_pack_binding_postgres import committed, naming
from test_world_style_postgres import proposal, topology
from world_support import registered_world

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[1]
COZY_PIECES = ROOT / "assets/style-packs/packs/exulanica.cozy-town/pieces"
COZY = committed("exulanica.cozy-town")
TOON = committed("exulanica.toon-town")
COMPONENTS = "c1" * 32
#: Each look role a test asks for, the cozy piece standing in for its generated one, and its size.
PIECES = {
    "plant.default": ("tree.glb", (3200, 3200, 6000)),
    "vehicle.sedan": ("sedan.glb", (1800, 4600, 1440)),
}


@dataclass
class World:
    packs: Packs
    world_id: str
    stepper: LookStepper

    @property
    def styles(self) -> WorldStyleRepository:
        return WorldStyleRepository(
            self.packs.connection, self.packs.workspace_id, world_id=self.world_id
        )

    def step(self, at: dt.datetime | None = None) -> list[str]:
        return self.stepper.run(
            self.packs.connection, self.packs.workspace_id, at or dt.datetime.now(dt.UTC)
        )

    def steps(self, piece_request_id: uuid.UUID) -> list[dict]:
        return self.packs.connection.execute(
            "select kind, reason, manifest_sha256, style_version_id from piece_look_step "
            "where workspace_id = %s and piece_request_id = %s order by recorded_at, kind",
            (self.packs.workspace_id, piece_request_id),
        ).fetchall()

    def own(self) -> WorkspaceStylePackRepository:
        return WorkspaceStylePackRepository(
            self.packs.connection,
            self.packs.workspace_id,
            self.packs.actor,
            stores=self.packs.stores,
            generated_pieces=self.packs.content.generated_pieces,
        )

    def check(self) -> None:
        """Every waiting check, as the asset preparation process runs it; each passes."""
        outcome = StylePackCheckWorker(
            self.packs.runtime,
            self.packs.stores,
            frozenset({self.packs.workspace_id}),
            table=colour_table(ROOT),
            library=library_palettes,
            generated_pieces=self.packs.content.generated_pieces,
        ).drain()
        assert outcome.ready >= 1 and outcome.errors == [], outcome

    def wear(self, pack: StylePackBinding) -> None:
        styles = self.styles
        current = styles.current()
        preview = styles.preview(naming(current, pack))
        styles.apply(
            preview.preview_id,
            base_style_version_id=current.version_id,
            base_topology_digest=current.topology_digest,
            applied_by=self.packs.actor,
        )

    def made(
        self,
        role: str,
        *,
        base: StylePackBinding = COZY,
        within: bool = True,
        stand_in: tuple[str, tuple[int, int, int]] | None = None,
    ) -> uuid.UUID:
        """A request for ``role`` on ``base`` that a session made, its one piece kept (``stand_in``,
        a cozy file and its size, in place of the role's own)."""
        name, size = stand_in or PIECES[role]
        piece = (COZY_PIECES / name).read_bytes()
        self.packs.content.generated_pieces.put_bytes(piece)
        request_id = uuid.uuid4()
        request = canonical_bytes({"look_role": role, "request": str(request_id)})
        request_sha256 = sha256_hex(request)
        verdict = {"over": [] if within else ["triangles"], "within": within}
        receipt = canonical_bytes(
            {
                "components_sha256": COMPONENTS,
                "measured": {
                    "size_mm": {"depth": size[1], "height": size[2], "width": size[0]},
                },
                "output": {"bytes": len(piece), "sha256": sha256_hex(piece)},
                "postprocess": {"version": POSTPROCESS_VERSION},
                "request_sha256": request_sha256,
                "variant": 0,
                "verdict": verdict,
            }
        )
        key = cache_key(request_sha256, COMPONENTS, POSTPROCESS_VERSION)
        now = dt.datetime.now(dt.UTC)
        with (
            self.packs.purged.database().session(self.packs.workspace_id) as owner,
            owner.transaction(),
        ):
            owner.execute("set local session_replication_role = replica")
            owner.execute(
                "insert into piece_request (workspace_id, piece_request_id, requested_by, "
                "  world_id, kind_key, kind_version, kind_sha256, pack_id, pack_version, "
                "  pack_manifest_sha256, look_role, variants, request_canonical, request_sha256, "
                "  cache_scope, worst_case_usd, state, requested_at, queued_at, finished_at) "
                "values (%s, %s, %s, %s, 'tree', 1, %s, %s, %s, %s, %s, 1, %s, %s, 'catalog', 0, "
                "  'made', %s, %s, %s)",
                (
                    self.packs.workspace_id,
                    request_id,
                    self.packs.actor,
                    self.world_id,
                    "a" * 64,
                    base.pack_id,
                    base.version,
                    base.manifest_sha256,
                    role,
                    request.decode("ascii"),
                    request_sha256,
                    now,
                    now,
                    now,
                ),
            )
            owner.execute(
                "insert into generated_piece (cache_key, variant, request_sha256, "
                "  components_sha256, postprocess_version, receipt_canonical, receipt_sha256, "
                "  piece_sha256, piece_bytes, within, over_checks) "
                "values (%s, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    key,
                    request_sha256,
                    COMPONENTS,
                    POSTPROCESS_VERSION,
                    receipt.decode("ascii"),
                    sha256_hex(receipt),
                    sha256_hex(piece),
                    len(piece),
                    within,
                    verdict["over"],
                ),
            )
            owner.execute(
                "insert into piece_output (workspace_id, piece_request_id, variant, cache_key, "
                "  receipt_canonical, receipt_sha256, piece_sha256, within, over_checks) "
                "values (%s, %s, 0, %s, %s, %s, %s, %s, %s)",
                (
                    self.packs.workspace_id,
                    request_id,
                    key,
                    receipt.decode("ascii"),
                    sha256_hex(receipt),
                    sha256_hex(piece),
                    within,
                    verdict["over"],
                ),
            )
        return request_id


@pytest.fixture
def world(packs) -> World:
    """A world of the workspace with its appearance, wearing the cozy town."""
    world_id = registered_world(packs.connection, packs.workspace_id, actor=packs.actor)
    made = World(
        packs,
        world_id,
        LookStepper(
            library=style_pack_library(),
            context=load_context(ROOT),
            stores=packs.stores,
            generated_pieces=packs.content.generated_pieces,
        ),
    )
    made.styles.register_topology(topology(world_id=world_id))
    made.wear(COZY)
    return made


def _modules(world: World, binding: StylePackBinding) -> dict[str, list[str]]:
    record = world.own().version(binding.manifest_sha256)
    assert record.manifest_canonical is not None
    manifest = json.loads(record.manifest_canonical)
    files = {file["path"]: file["sha256"] for file in manifest["files"]}
    return {
        role: [files[variant["file"]] for variant in module["variants"]]
        for role, module in manifest["modules"].items()
    }


def _tree() -> bytes:
    return (COZY_PIECES / PIECES["plant.default"][0]).read_bytes()


def _digest(role: str) -> str:
    return hashlib.sha256((COZY_PIECES / PIECES[role][0]).read_bytes()).hexdigest()


def test_passed_pieces_enter_the_world_s_look_once_checked_and_leave_on_request(world) -> None:
    plant = world.made("plant.default")
    # The look is recorded and waits for its check; the world does not wear it yet.
    assert world.step() == []
    assert world.styles.current().style_pack == COZY
    assert world.steps(plant) == []
    world.check()
    assert world.step() == [world.world_id]
    current = world.styles.current()
    own = current.style_pack
    assert own is not None
    assert (own.pack_id, own.version, own.source) == ("generated.cozy-town", 1, "workspace")
    assert (own.base, own.wearable) == (COZY, True)
    assert current.provenance == ProposalProvenance(
        ProposalOrigin.USER, world.packs.actor, f"{REFERENCE_PREFIX}{plant}"
    )
    assert _modules(world, own) == {"plant.default": [_digest("plant.default")]}
    assert world.steps(plant) == [
        {
            "kind": "applied",
            "reason": None,
            "manifest_sha256": own.manifest_sha256,
            "style_version_id": current.version_id,
        }
    ]
    read = store.read_piece_request(world.packs.connection, world.packs.workspace_id, plant)
    assert read is not None and read.document()["look_step"]["kind"] == "applied"
    # Nothing waits, so a pass writes nothing.
    assert world.step() == []

    # A second kind joins the first in the world's next own look.
    sedan = world.made("vehicle.sedan")
    world.step()
    world.check()
    world.step()
    both = world.styles.current().style_pack
    assert both is not None and both.version == 2
    assert _modules(world, both) == {
        "plant.default": [_digest("plant.default")],
        "vehicle.sedan": [_digest("vehicle.sedan")],
    }

    # Taking the trees back leaves the cars; taking the cars back leaves the library pack itself.
    asked = store.ask_take_back(
        world.packs.connection, world.packs.workspace_id, plant, world.packs.actor
    )
    assert asked is not None and asked.document()["look_step"]["kind"] == "take_back_asked"
    world.step()
    world.check()
    world.step()
    cars = world.styles.current().style_pack
    assert cars is not None and _modules(world, cars) == {
        "vehicle.sedan": [_digest("vehicle.sedan")]
    }
    assert [step["kind"] for step in world.steps(plant)] == [
        "applied",
        "take_back_asked",
        "taken_back",
    ]
    store.ask_take_back(world.packs.connection, world.packs.workspace_id, sedan, world.packs.actor)
    assert world.step() == [world.world_id]
    assert world.styles.current().style_pack == COZY
    taken = world.steps(sedan)[-1]
    assert (taken["kind"], taken["manifest_sha256"]) == ("taken_back", None)
    # Asked again, the request answers as it stands; nothing is deleted.
    again = store.ask_take_back(
        world.packs.connection, world.packs.workspace_id, sedan, world.packs.actor
    )
    assert again is not None and again.document()["look_step"]["kind"] == "taken_back"
    assert len(world.packs.owner_rows("select 1 from piece_output")) == 2


def test_a_take_back_of_replaced_pieces_leaves_the_newer_ones(world) -> None:
    older = world.made("plant.default")
    world.step()
    world.check()
    world.step()
    newer = world.made("plant.default", stand_in=PIECES["vehicle.sedan"])
    world.step()
    world.check()
    world.step()
    worn = world.styles.current().style_pack
    assert worn is not None and _modules(world, worn) == {
        "plant.default": [_digest("vehicle.sedan")]
    }
    store.ask_take_back(world.packs.connection, world.packs.workspace_id, older, world.packs.actor)
    assert world.step() == [world.world_id]
    taken = world.steps(older)[-1]
    assert (taken["kind"], taken["reason"], taken["style_version_id"]) == (
        "taken_back",
        "not_worn",
        None,
    )
    # The world still wears the newer request's pieces, in the same look.
    assert world.styles.current().style_pack == worn
    assert world.steps(newer)[0]["kind"] == "applied"


def test_a_request_on_another_look_or_with_nothing_passed_is_not_applied(world) -> None:
    world.wear(TOON)
    on_cozy = world.made("plant.default")
    failed = world.made("vehicle.sedan", base=TOON, within=False)
    assert world.step() == [world.world_id]
    assert [(s["kind"], s["reason"]) for s in world.steps(on_cozy)] == [
        ("not_applied", "look_changed")
    ]
    assert [(s["kind"], s["reason"]) for s in world.steps(failed)] == [
        ("not_applied", "no_piece_within")
    ]
    assert world.styles.current().style_pack == TOON
    with pytest.raises(store.PieceNotTakenIn) as refused:
        store.ask_take_back(
            world.packs.connection, world.packs.workspace_id, on_cozy, world.packs.actor
        )
    assert refused.value.step == "not_applied"
    assert (
        store.ask_take_back(
            world.packs.connection, world.packs.workspace_id, uuid.uuid4(), world.packs.actor
        )
        is None
    )


def test_a_withdrawn_own_look_reads_as_its_base_and_is_never_named_again(world) -> None:
    plant = world.made("plant.default")
    world.step()
    world.check()
    world.step()
    worn = world.styles.current()
    own = worn.style_pack
    assert own is not None and own.source == "workspace"
    assert world.own().withdraw(own.manifest_sha256)

    # The world still opens: its version names the own look, which may no longer be worn, and its
    # library base is what a page draws.
    read = world.styles.current()
    assert read.style_pack is not None
    assert (read.style_pack.wearable, read.style_pack.base) == (False, COZY)
    assert any("may no longer be worn" in warning for warning in read.warnings)
    # Rolling back to a version naming it, or writing one directly, is refused.
    world.wear(TOON)
    styles = world.styles
    current = styles.current()
    with pytest.raises(InvalidStyleData):
        styles.rollback(
            worn.version_id,
            base_style_version_id=current.version_id,
            base_topology_digest=current.topology_digest,
            provenance=ProposalProvenance(ProposalOrigin.USER, world.packs.actor),
        )
    with pytest.raises(psycopg.errors.CheckViolation, match="own_pack_not_wearable"):
        world.packs.connection.execute(
            "insert into world_style_version (version_id, workspace_id, world_id, revision, "
            "  parent_version_id, topology_digest, global_profile_id, global_profile_version, "
            "  global_parameters, origin, actor, provenance_schema_version, recipe_binding, "
            "  capability_mapping, style_pack_id, style_pack_version, "
            "  style_pack_manifest_sha256, style_pack_source) "
            "select gen_random_uuid(), workspace_id, world_id, revision + 100, version_id, "
            "  topology_digest, global_profile_id, global_profile_version, global_parameters, "
            "  origin, actor, provenance_schema_version, recipe_binding, capability_mapping, "
            "  %s, %s, %s, 'workspace' from world_style_version where version_id = %s",
            (own.pack_id, own.version, own.manifest_sha256, current.version_id),
        )
    assert world.steps(plant)[0]["kind"] == "applied"


def test_a_world_wearing_a_withdrawn_own_look_takes_new_pieces_on_its_base(world) -> None:
    world.made("plant.default")
    world.step()
    world.check()
    world.step()
    own = world.styles.current().style_pack
    assert own is not None
    world.own().withdraw(own.manifest_sha256)
    sedan = world.made("vehicle.sedan")
    world.step()
    world.check()
    assert world.step() == [world.world_id]
    now = world.styles.current().style_pack
    assert now is not None and now.wearable
    # The withdrawn look's trees are not carried over: the world wore its base.
    assert _modules(world, now) == {"vehicle.sedan": [_digest("vehicle.sedan")]}
    assert world.steps(sedan)[0]["kind"] == "applied"


def test_a_world_wearing_a_library_pack_reads_as_before(world) -> None:
    current = world.styles.current()
    assert current.style_pack == COZY
    assert (current.style_pack.base, current.style_pack.wearable) == (None, None)
    row = world.packs.connection.execute(
        "select style_pack_source from world_style_version where version_id = %s",
        (current.version_id,),
    ).fetchone()
    assert row["style_pack_source"] == "library"
    from exulanica.api.routes.world import _style_pack_view

    assert json.loads(_style_pack_view(current.style_pack).model_dump_json()) == {
        "pack_id": COZY.pack_id,
        "version": COZY.version,
        "manifest_sha256": COZY.manifest_sha256,
    }


def test_a_look_step_is_appended_once_in_order_and_never_changed(world) -> None:
    plant = world.made("plant.default")
    connection = world.packs.connection
    workspace = world.packs.workspace_id

    def insert(kind: str, **more) -> None:
        connection.execute(
            "insert into piece_look_step (workspace_id, piece_request_id, world_id, kind, reason, "
            "  asked_by) values (%s, %s, %s, %s, %s, %s)",
            (workspace, plant, world.world_id, kind, more.get("reason"), more.get("asked_by")),
        )

    with pytest.raises(psycopg.errors.CheckViolation, match="only pieces a world took in"):
        insert("take_back_asked", asked_by=world.packs.actor)
    insert("not_applied", reason="look_changed")
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert("not_applied", reason="look_changed")
    # The runtime holds neither update nor delete, and the trigger refuses an update by anyone.
    for statement in ("update piece_look_step set reason = 'other'", "delete from piece_look_step"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(statement)
    with (
        world.packs.purged.database().session(workspace) as owner,
        pytest.raises(psycopg.errors.CheckViolation, match="recorded once"),
    ):
        owner.execute("update piece_look_step set reason = 'other'")


def _applied(world: World, role: str = "plant.default") -> uuid.UUID:
    made = world.made(role)
    world.step()
    world.check()
    world.step()
    return made


def test_at_its_limit_of_generated_looks_a_world_s_step_ends_by_name(world) -> None:
    # 64 live generated looks, each recorded as the worker records one and its check ended
    # interrupted (a check that may be asked again counts as live): the piece store says the
    # workspace is full, so an ask is refused by name before anything is spent, and a request made
    # before ends not applied, look_limit, rather than failing on every pass.
    plant = world.made("plant.default")
    own = world.own()
    context = load_context(ROOT)
    cozy_path = ROOT / "assets/style-packs/packs/exulanica.cozy-town/manifest.json"
    cozy = read_manifest(json.loads(cozy_path.read_text()), context)
    variant = GeneratedVariant(_digest("plant.default"), len(_tree()), (3200, 3200, 6000), "1" * 64)
    for version in range(1, 65):
        assert not store.generated_looks_full(world.packs.connection, world.packs.workspace_id)
        built = build_derived_look(
            chain=[cozy],
            version=version,
            roles={"plant.default": [variant]},
            authors=["a"],
            context=context,
        )
        assert built is not None
        own.record_generated(
            built.canonical,
            content_sha256=f"{version:064x}",
            asked_by=world.packs.actor,
            context=context,
        )
        manifest, token = own.claim("test-worker", 60)
        own.finish_failed(manifest, token, "interrupted", "a test interruption", {})
    assert store.generated_looks_full(world.packs.connection, world.packs.workspace_id)
    assert world.step() == [world.world_id]
    assert [(s["kind"], s["reason"]) for s in world.steps(plant)] == [("not_applied", "look_limit")]
    assert world.styles.current().style_pack == COZY


def test_over_its_retained_bytes_a_world_s_step_ends_by_name(world) -> None:
    # The stepper holds the limit the deployment configures, not the default; a look the
    # workspace has no bytes left for ends not applied, look_bytes_limit, on its first pass,
    # rather than waiting a day as a check that waits would, and the world keeps its look.
    plant = world.made("plant.default")
    world.stepper.retained_bytes_limit = 1
    assert world.step() == [world.world_id]
    assert [(s["kind"], s["reason"]) for s in world.steps(plant)] == [
        ("not_applied", "look_bytes_limit")
    ]
    assert world.styles.current().style_pack == COZY


def test_a_take_back_after_the_library_lets_go_of_the_look_s_base_is_refused_by_name(world) -> None:
    # The world wears its own look of the pieces, but the library no longer holds the look they
    # were taken into: no look without them can be made, so the take-back ends not taken back,
    # base_not_library, never taken back as not worn while the world still wears them.
    plant = _applied(world)
    worn = world.styles.current().style_pack
    library = world.stepper.library
    others = tuple(pack for pack in library.packs if pack.pack_id != COZY.pack_id)
    world.stepper.library = dataclasses.replace(library, packs=others, default=others[0].pack_id)
    store.ask_take_back(world.packs.connection, world.packs.workspace_id, plant, world.packs.actor)
    assert world.step() == [world.world_id]
    last = world.steps(plant)[-1]
    assert (last["kind"], last["reason"]) == ("not_taken_back", "base_not_library")
    assert world.styles.current().style_pack == worn


def test_nothing_is_written_in_a_deleted_workspace(world, caplog) -> None:
    # A worker still serving a workspace after its tombstone (one named in a static list) steps
    # nothing there: no look is taken in, and no world falls back into the erased workspace,
    # though its own look now reads as not wearable. Nothing is even tried, so nothing is refused
    # and logged on every pass.
    _applied(world)
    with world.packs.purged.database().session(world.packs.workspace_id) as owner:
        owner.execute(
            "insert into tombstone (workspace_id, scope, requested_by, reason) "
            "values (%s, 'workspace', %s, 'an operator deleted the workspace')",
            (world.packs.workspace_id, uuid.uuid4()),
        )

    def versions() -> int:
        return world.packs.connection.execute(
            "select count(*) as n from world_style_version where workspace_id = %s",
            (world.packs.workspace_id,),
        ).fetchone()["n"]

    before = versions()
    world.made("vehicle.sedan")
    with caplog.at_level(logging.WARNING, logger="exulanica.generation.apply"):
        assert world.step() == []
    assert versions() == before
    assert not caplog.records


def test_pieces_whose_look_s_check_was_interrupted_take_the_next_version(world) -> None:
    # An interrupted check may be asked again: the same pieces are not left on the failed version
    # (which would end them look_check_failed) but take the next one, which is checked and worn.
    plant = world.made("plant.default")
    assert world.step() == []
    own = world.own()
    manifest, token = own.claim("test-worker", 60)
    own.finish_failed(manifest, token, "interrupted", "a test interruption", {})
    assert world.step() == []
    world.check()
    assert world.step() == [world.world_id]
    assert [step["kind"] for step in world.steps(plant)] == ["applied"]
    worn = world.styles.current().style_pack
    assert worn is not None and worn.version == 2 and worn.manifest_sha256 != manifest


def test_a_take_back_waits_while_its_look_is_checked_and_ends_by_name_when_it_is_refused(
    world,
) -> None:
    plant = _applied(world)
    sedan = _applied(world, "vehicle.sedan")
    worn = world.styles.current().style_pack
    store.ask_take_back(world.packs.connection, world.packs.workspace_id, plant, world.packs.actor)
    # The look without the trees is recorded and its check waits: the take-back stays asked.
    assert world.step() == []
    assert world.steps(plant)[-1]["kind"] == "take_back_asked"
    # Its check ends refused: the take-back ends by that reason, never as not worn, and the world
    # keeps both kinds' pieces.
    own = world.own()
    manifest, token = own.claim("test-worker", 60)
    own.finish_failed(manifest, token, "refused", "a test refusal", {})
    assert world.step() == [world.world_id]
    last = world.steps(plant)[-1]
    assert (last["kind"], last["reason"]) == ("not_taken_back", "look_refused")
    assert world.styles.current().style_pack == worn
    assert world.steps(sedan)[0]["kind"] == "applied"
    asked = store.read_piece_request(world.packs.connection, world.packs.workspace_id, plant)
    assert asked is not None and asked.document()["look_step"]["kind"] == "not_taken_back"
    # Ended, it is no longer waiting: the next pass finds nothing to do in this world and records
    # nothing more, and a later request there gets its own step.
    assert world.step() == []
    assert [step["kind"] for step in world.steps(plant)][-1] == "not_taken_back"
    later = world.made("plant.default", stand_in=PIECES["vehicle.sedan"])
    world.step()
    world.check()
    assert world.step() == [world.world_id]
    assert world.steps(later)[0]["kind"] == "applied"


def test_an_apply_refused_as_busy_leaves_no_preview_open(world, monkeypatch) -> None:
    world.made("plant.default")
    world.step()
    world.check()

    def busy(*_args, **_kwargs):
        raise StyleWriteBusy("another change held a lock this write needs")

    monkeypatch.setattr(WorldStyleRepository, "apply", busy)
    assert world.step() == []
    opened = world.packs.connection.execute(
        "select count(*) as n from world_style_preview where workspace_id = %s and world_id = %s "
        "and status = 'open'",
        (world.packs.workspace_id, world.world_id),
    ).fetchone()
    assert opened["n"] == 0


def test_after_its_own_look_is_withdrawn_a_world_takes_regional_changes_and_falls_back(
    world,
) -> None:
    plant = _applied(world)
    own = world.styles.current().style_pack
    assert own is not None
    world.own().withdraw(own.manifest_sha256)
    # A regional change names no pack: it keeps what the world is drawn in, its library base.
    styles = world.styles
    current = styles.current()
    regional = dataclasses.replace(
        proposal(current, topology_digest=current.topology_digest, parameters={"vitality": 0.4}),
        scope=StyleScope("region", "region-a"),
    )
    preview = styles.preview(regional)
    applied = styles.apply(
        preview.preview_id,
        base_style_version_id=current.version_id,
        base_topology_digest=current.topology_digest,
        applied_by=world.packs.actor,
    )
    assert applied.style_pack == COZY
    # And with nothing else waiting, the look step records the fallback itself.
    plant_again = _applied(world)
    assert world.styles.current().style_pack.source == "workspace"
    world.own().withdraw(world.styles.current().style_pack.manifest_sha256)
    assert world.step() == [world.world_id]
    assert world.styles.current().style_pack == COZY
    fell = world.steps(plant_again)[-1]
    assert (fell["kind"], fell["reason"]) == ("fell_back", "look_withdrawn")
    assert fell["style_version_id"] == world.styles.current().version_id
    assert world.steps(plant)[0]["kind"] == "applied"


def test_a_world_wears_no_creator_s_own_pack_yet(world) -> None:
    # A creator's ready pack may be worn as far as its own check says, but a world's appearance is
    # history no erasure rewrites, so for now it names only looks of generated pieces.
    pack = admitted()
    world.packs.ready(pack)
    assert world.own().wearable(pack.manifest_sha256)
    current = world.styles.current()
    with pytest.raises(psycopg.errors.CheckViolation, match="own_pack_not_wearable"):
        world.packs.connection.execute(
            "insert into world_style_version (version_id, workspace_id, world_id, revision, "
            "  parent_version_id, topology_digest, global_profile_id, global_profile_version, "
            "  global_parameters, origin, actor, provenance_schema_version, recipe_binding, "
            "  capability_mapping, style_pack_id, style_pack_version, "
            "  style_pack_manifest_sha256, style_pack_source) "
            "select gen_random_uuid(), workspace_id, world_id, revision + 100, version_id, "
            "  topology_digest, global_profile_id, global_profile_version, global_parameters, "
            "  origin, actor, provenance_schema_version, recipe_binding, capability_mapping, "
            "  %s, %s, %s, 'workspace' from world_style_version where version_id = %s",
            (pack.pack_id, pack.version, pack.manifest_sha256, current.version_id),
        )
