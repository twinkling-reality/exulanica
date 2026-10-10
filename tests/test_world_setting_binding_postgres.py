"""A world's appearance states the world's own setting over the pack it names, through preview,
apply and rollback, and migration 0189 over rows written before it.

Each setting here is written out by hand or composed from the committed parts for the committed
pack, and the expected stored document is that same document's canonical JSON, never read back
through the repository under test. The packs are read from their committed files.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import psycopg
import pytest
from exulanica.migrations import migrations
from exulanica.world import (
    InvalidStyleData,
    ProposalOrigin,
    ProposalProvenance,
    StylePackBinding,
    WorldStyleRepository,
)
from exulanica.world import world_settings as ws
from exulanica.world.style_packs import canonical_json, load_context
from psycopg.rows import dict_row

import pg_harness
from test_world_style_postgres import fixture_styles, proposal, topology
from world_support import registered_world

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "assets" / "style-packs" / "packs"
CONTEXT = load_context(ROOT)


def manifest_of(pack_id: str, version: int | None = None) -> tuple[dict[str, Any], bytes]:
    folder = (
        PACKS / pack_id if version is None else PACKS.parent / "published" / pack_id / str(version)
    )
    text = (folder / "manifest.json").read_bytes()
    return json.loads(text), text[:-1]


def setting_for(pack_id: str, chosen: dict[str, str], version: int | None = None) -> str:
    """The committed parts ``chosen`` composed for a committed pack, as canonical JSON."""
    manifest, _ = manifest_of(pack_id, version)
    composed = ws.compose_setting(chosen, ws.resolve_chain([manifest]), CONTEXT, ws.setting_parts())
    return canonical_json(composed)


def committed(
    pack_id: str, setting: str | None = None, version: int | None = None
) -> StylePackBinding:
    manifest, canonical = manifest_of(pack_id, version)
    return StylePackBinding(
        pack_id, manifest["version"], hashlib.sha256(canonical).hexdigest(), setting=setting
    )


def naming(current, pack: StylePackBinding | None, **more):
    return replace(proposal(current, **more), style_pack_stated=True, style_pack=pack)


def apply(styles: WorldStyleRepository, preview, base):
    return styles.apply(
        preview.preview_id,
        base_style_version_id=base.version_id,
        base_topology_digest="topology-a",
        applied_by=uuid.uuid4(),
    )


def stored(connection, version_id) -> Any:
    return connection.execute(
        "select style_pack_setting from world_style_version where version_id=%s", (version_id,)
    ).fetchone()["style_pack_setting"]


def test_a_setting_is_previewed_applied_stored_and_kept_until_the_pack_is_named_again(repository):
    styles = fixture_styles(repository)
    initial = styles.register_topology(topology())
    dusk = setting_for("exulanica.cozy-town", {"sky": "dusk", "ground": "sea"})
    cozy = committed("exulanica.cozy-town", dusk)

    previewed = styles.preview(naming(initial, cozy))
    assert previewed.candidate.style_pack.setting == dusk
    assert styles.current().style_pack is None
    first = apply(styles, previewed, initial)
    assert first.style_pack == cozy and first.style_pack.setting == dusk
    assert styles.current().style_pack.setting == dusk
    assert stored(repository.connection, first.version_id) == json.loads(dusk)

    # A proposal that names no pack keeps its base's pack and the setting drawn over it.
    kept = apply(styles, styles.preview(proposal(first, parameters={"vitality": 0.6})), first)
    assert kept.style_pack.setting == dusk
    # Naming the pack with another setting changes the setting and nothing else of the pack.
    snow = setting_for("exulanica.cozy-town", {"sky": "night", "cover": "snow"})
    changed = apply(
        styles, styles.preview(naming(kept, committed("exulanica.cozy-town", snow))), kept
    )
    assert changed.style_pack == cozy and changed.style_pack.setting == snow
    # Naming it with none returns the world to the pack as it states.
    plain = apply(
        styles, styles.preview(naming(changed, committed("exulanica.cozy-town"))), changed
    )
    assert plain.style_pack == cozy and plain.style_pack.setting is None
    assert stored(repository.connection, plain.version_id) is None
    assert [
        None if version.style_pack is None else version.style_pack.setting
        for version in styles.versions()
    ] == [None, dusk, dusk, snow, None]

    # A rollback to an earlier version names its pack and its setting again.
    back = styles.rollback(
        first.version_id,
        base_style_version_id=plain.version_id,
        base_topology_digest="topology-a",
        provenance=ProposalProvenance(ProposalOrigin.USER, uuid.uuid4()),
    )
    assert back.style_pack == cozy and back.style_pack.setting == dusk
    assert stored(repository.connection, back.version_id) == json.loads(dusk)


def test_a_proposal_and_its_preview_record_the_setting_as_it_was_named(repository):
    styles = fixture_styles(repository)
    initial = styles.register_topology(topology())
    dusk = setting_for("exulanica.toon-town", {"sky": "dusk"})
    toon = committed("exulanica.toon-town", dusk)
    named = styles.preview(naming(initial, toon))
    row = repository.connection.execute(
        "select style_pack from world_style_proposal where proposal_id=%s",
        (named.proposal.proposal_id,),
    ).fetchone()
    assert row["style_pack"] == {
        "pack": {
            "pack_id": toon.pack_id,
            "version": toon.version,
            "manifest_sha256": toon.manifest_sha256,
            "setting": json.loads(dusk),
        }
    }
    read = styles.proposal(named.proposal.proposal_id).proposal
    assert read.style_pack == toon and read.style_pack.setting == dusk
    candidate = repository.connection.execute(
        "select candidate from world_style_preview where preview_id=%s", (named.preview_id,)
    ).fetchone()["candidate"]
    assert candidate["style_pack"]["setting"] == json.loads(dusk)


NIGHT_TOO_DARK = {
    "exposure_permille": 1150,
    "sun.elevation_mdeg": 42000,
    "sun.colour": [150, 176, 255],
    "sun.intensity_permille": 520,
    "sky.zenith": [8, 12, 34],
    "sky.horizon": [34, 42, 78],
    "sky.intensity_permille": 450,
    "environment.intensity_permille": 420,
}


def _setting(**over: Any) -> dict[str, Any]:
    return {
        "profile": ws.PROFILE,
        "origin": "authored",
        "provenance": {"kind": "authored"},
        "parts": [],
        "light": None,
        "surfaces": {},
        "up": {},
        "swatches": {},
        "edge": None,
        **over,
    }


@pytest.mark.parametrize(
    ("document", "said"),
    [
        (_setting(light={"from": "day", "changes": NIGHT_TOO_DARK}), "light: a person in the open"),
        (_setting(swatches={"neon": {"emission_permille": 900}}), "swatches.neon"),
        (_setting(light={"from": "noon", "changes": {}}), "light.from"),
        (_setting(weather="rain"), "has an unknown key"),
        # A setting that changes nothing is not stored: the world is drawn as its pack states.
        (_setting(), "changes nothing"),
    ],
)
def test_a_setting_the_pack_cannot_be_drawn_in_is_refused_and_nothing_is_written(
    repository, document, said
):
    styles = fixture_styles(repository)
    initial = styles.register_topology(topology())
    refused_pack = committed("exulanica.cozy-town", canonical_json(document))
    with pytest.raises(InvalidStyleData) as refused:
        styles.preview(naming(initial, refused_pack))
    assert said in str(refused.value)
    assert styles.current().version_id == initial.version_id
    assert (
        repository.connection.execute(
            "select count(*) as n from world_style_version where style_pack_setting is not null"
        ).fetchone()["n"]
        == 0
    )


def test_a_setting_not_stated_as_its_canonical_json_is_refused(repository):
    styles = fixture_styles(repository)
    initial = styles.register_topology(topology())
    dusk = setting_for("exulanica.cozy-town", {"sky": "dusk"})
    spaced = json.dumps(json.loads(dusk), indent=1)
    assert json.loads(spaced) == json.loads(dusk) and spaced != dusk
    with pytest.raises(InvalidStyleData):
        styles.preview(naming(initial, committed("exulanica.cozy-town", spaced)))


def test_a_setting_is_checked_against_the_exact_version_of_the_pack_the_world_names(repository):
    """An earlier version the library still serves takes a setting composed for it, and a setting
    composed for one look is held to the look it is stored over."""
    styles = fixture_styles(repository)
    initial = styles.register_topology(topology())
    earlier = sorted(
        int(folder.name)
        for folder in (PACKS.parent / "published" / "exulanica.cozy-town").iterdir()
    )[0]
    old = setting_for("exulanica.cozy-town", {"sky": "night", "cover": "snow"}, earlier)
    first = apply(
        styles,
        styles.preview(naming(initial, committed("exulanica.cozy-town", old, earlier))),
        initial,
    )
    assert first.style_pack.version == earlier and first.style_pack.setting == old
    # Cozy town's night restates lit glass; Finished town states no such swatch.
    night = setting_for("exulanica.cozy-town", {"sky": "night"})
    assert "glass_lit" in json.loads(night)["swatches"]
    with pytest.raises(InvalidStyleData) as refused:
        styles.preview(naming(first, committed("exulanica.finished-town", night)))
    assert "swatches.glass_lit" in str(refused.value)


def _copy_version(connection, source, **columns):
    names = ",".join(sorted(columns))
    values = ",".join(f"%({name})s" for name in sorted(columns))
    connection.execute(
        "insert into world_style_version (version_id,workspace_id,world_id,revision,"
        "parent_version_id,topology_digest,global_profile_id,global_profile_version,"
        "global_parameters,origin,actor,origin_reference,provenance_schema_version,"
        f"recipe_binding,capability_mapping,{names}) "
        "select %(id)s,workspace_id,world_id,(select max(revision)+1 from world_style_version),"
        "version_id,topology_digest,global_profile_id,global_profile_version,global_parameters,"
        "'user',%(actor)s,null,1,recipe_binding,capability_mapping,"
        f"{values} from world_style_version where version_id=%(source)s",
        {"id": uuid.uuid4(), "actor": uuid.uuid4(), "source": source, **columns},
    )


def test_earlier_style_rows_stand_and_the_new_check_refuses_what_is_no_setting(monkeypatch):
    every = list(migrations())
    [settings] = [item for item in every if item.version == "0189"]
    monkeypatch.setattr(
        pg_harness, "migrations", lambda: iter(m for m in every if m.version < "0189")
    )
    with pg_harness.migrated_schema() as (_, connection):
        connection.autocommit = True
        connection.row_factory = dict_row
        workspace = uuid.uuid4()
        connection.execute(
            "select set_config('exulanica.workspace_id', %s, false)", (str(workspace),)
        )
        world_id = registered_world(connection, workspace)
        styles = WorldStyleRepository(connection, workspace, world_id=world_id)
        initial = styles.register_topology(topology(world_id=world_id))
        cozy = committed("exulanica.cozy-town")
        named = styles.apply(
            styles.preview(
                replace(
                    proposal(initial, origin=ProposalOrigin.SETTINGS, origin_reference="s"),
                    style_pack_stated=True,
                    style_pack=cozy,
                )
            ).preview_id,
            base_style_version_id=initial.version_id,
            base_topology_digest="topology-a",
            applied_by=uuid.uuid4(),
        )

        def contents():
            return [
                {key: value for key, value in row["row"].items() if key != "style_pack_setting"}
                for row in connection.execute(
                    "select to_jsonb(t) as row from world_style_version t order by revision"
                ).fetchall()
            ]

        before = contents()
        connection.execute(settings.sql)
        assert contents() == before
        assert (
            connection.execute(
                "select count(*) as n from world_style_version where style_pack_setting is not null"
            ).fetchone()["n"]
            == 0
        )
        # Every earlier version reads as it did: its pack, and no setting.
        read = WorldStyleRepository(connection, workspace, world_id=world_id).current()
        assert read.style_pack == cozy and read.style_pack.setting is None

        dusk = json.loads(setting_for("exulanica.cozy-town", {"sky": "dusk"}))
        # A copy names its pack as the source version does, so only the setting differs.
        pack = {
            "style_pack_id": cozy.pack_id,
            "style_pack_version": cozy.version,
            "style_pack_manifest_sha256": cozy.manifest_sha256,
        }
        for wrong in (
            psycopg.types.json.Jsonb("dusk"),
            psycopg.types.json.Jsonb([dusk]),
            psycopg.types.json.Jsonb({}),
            psycopg.types.json.Jsonb({**dusk, "profile": "exulanica.world-setting/v2"}),
            psycopg.types.json.Jsonb({**dusk, "profile": None}),
            psycopg.types.json.Jsonb({**dusk, "padding": "x" * 33_000}),
        ):
            with pytest.raises(psycopg.errors.CheckViolation) as refused:
                _copy_version(connection, named.version_id, style_pack_setting=wrong, **pack)
            assert refused.value.diag.constraint_name == "world_style_version_setting_is_a_setting"
        # A setting is drawn over a pack: a version naming no pack states none.
        with pytest.raises(psycopg.errors.CheckViolation) as refused:
            _copy_version(
                connection, initial.version_id, style_pack_setting=psycopg.types.json.Jsonb(dusk)
            )
        assert refused.value.diag.constraint_name == "world_style_version_setting_is_a_setting"
        # The same row with a setting over its pack is taken: only the document was wrong.
        _copy_version(
            connection,
            named.version_id,
            style_pack_setting=psycopg.types.json.Jsonb(dusk),
            **pack,
        )
        latest = WorldStyleRepository(connection, workspace, world_id=world_id).versions()[-1]
        assert latest.style_pack.setting == canonical_json(dusk)
