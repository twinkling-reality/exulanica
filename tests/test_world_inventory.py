"""Retained semantic identities are independent of rendering and model assignment."""

from copy import deepcopy

from exulanica.api.world_inventory import inventory_document
from exulanica.world.society_engines import ENGINES


def _documents():
    version = {
        "world_id": "world",
        "version_id": "version",
        "source_snapshot_id": "snapshot",
        "state_sha256": "a" * 64,
        "edit_seq": 8,
        "source_invalidated": False,
        "objects": [
            {
                "object_id": "shared",
                "removed": False,
                "asset": {"title": "A bench", "availability": "withdrawn"},
            }
        ],
        "things": [
            {"thing_id": name, "removed": name == "removed", "kind": {"kind": "knight"}}
            for name in ("shared", "uninstantiated", "removed")
        ],
        "environment_instances": [],
        "point_map_instances": [
            {"instance_id": "photo", "removed": False, "availability": "unavailable_bytes"}
        ],
    }
    models = {
        "clock_second": 100,
        "roles": [
            {
                "key": "people",
                "subject": "person",
                "view": {"choices": [], "decisions_read": {"maximum": 2000}},
            },
            {
                "key": "signals",
                "subject": "signal",
                "available": False,
                "reason": "traffic_controller_unavailable",
                "subjects": [],
            },
        ],
    }
    society = {
        "society_id": "society",
        "profile": next(e.engine for e in ENGINES if e.state_family == "things"),
        "current_tick": 9,
        "state_sha256": "b" * 64,
        "state": {
            "inhabitants": [
                {"id": "shared", "name": "Born here"},
                {"id": "being", "placed_id": "shared", "name": "Placed being"},
            ],
            "things": [{"id": "well", "placed_id": "uninstantiated"}],
        },
    }
    return version, models, society


def test_typed_identity_and_only_explicit_placement_aliases_merge():
    version, models, society = _documents()
    original = deepcopy((version, models, society))
    result = inventory_document(version, models, society)
    rows = result["entities"]
    assert len(rows) == 4
    shared = [row for row in rows if row["reference"]["id"] == "shared"]
    assert {row["reference"]["source"] for row in shared} == {
        "authored-object",
        "authored-thing",
        "society-being",
    }
    placed = next(row for row in shared if row["reference"]["source"] == "authored-thing")
    assert placed["aliases"] == [{"source": "society-being", "id": "being"}]
    assert placed["category"] == "being"
    assert placed["role_instances"] == [{"role_key": "people", "subject_id": "being"}]
    assert placed["detail"]["bind"]["ref"] == "being:being"
    well = next(row for row in rows if row["reference"]["id"] == "uninstantiated")
    assert well["aliases"] == [{"source": "society-thing", "id": "well"}]
    assert well["role_instances"] == []
    assert (version, models, society) == original
    assert result["roles"] == models["roles"]
    assert result["representations"][0]["availability"] == "unavailable_bytes"
    assert (
        next(row for row in rows if row["reference"]["source"] == "authored-object")["availability"]
        == "withdrawn"
    )


def test_no_drawing_or_browser_cap_and_no_invented_assignment():
    version, models, society = _documents()
    society["state"]["inhabitants"] = [{"id": str(i)} for i in range(180)]
    result = inventory_document(version, models, society)
    assert len([row for row in result["entities"] if row["category"] == "being"]) == 180
    coverage = {row["source"]: row for row in result["coverage"]}
    assert coverage["society.things"]["state"] == "complete"
    assert coverage["role.signals.instances"]["state"] == "unavailable"
    assert coverage["role.signals.instances"]["code"] == "traffic_controller_unavailable"
    for source in (
        "generated_semantics",
        "source_semantics",
        "reconstructed_scene_layers",
        "vehicles",
    ):
        assert coverage[source]["state"] == "not_enumerated"
    assert result["roles"][0]["view"] == models["roles"][0]["view"]
    assert result["consistency"] == "component-pinned"
    assert result["read"]["society"]["tick"] == 9


def test_absent_and_unavailable_are_distinct_and_keep_uninstantiated_authored_things():
    version, models, _ = _documents()
    for reason, state in ((None, "absent"), ("unavailable_society_input", "unavailable")):
        result = inventory_document(version, models, None, society_unavailable=reason)
        assert len(result["entities"]) == 3
        assert not any(row["role_instances"] for row in result["entities"])
        assert not any(row["detail"] for row in result["entities"])
        assert {
            row["state"] for row in result["coverage"] if row["source"].startswith("society.")
        } == {state}


def test_native_signal_subjects_and_pending_evidence_are_preserved():
    version, models, _ = _documents()
    signals = models["roles"][1]
    signals.update(
        available=True,
        reason=None,
        subjects=[{"signal_id": "shared", "label": "Crossing"}],
        choices=[{"subject_id": "shared", "status": "pending", "active_second": None}],
    )
    result = inventory_document(version, models, None)
    system = next(row for row in result["entities"] if row["category"] == "system")
    assert system["reference"] == {"source": "role-subject", "id": "shared", "role_key": "signals"}
    assert system["detail"] is None
    assert result["roles"][1] == signals


def test_cross_source_and_role_scoped_ids_never_collapse():
    version, models, society = _documents()
    version["environment_instances"] = [
        {"instance_id": "shared", "removed": False, "availability": "available"}
    ]
    for key in ("signals", "another_signal_role"):
        models["roles"].append(
            {
                "key": key,
                "subject": "signal",
                "available": True,
                "subjects": [{"signal_id": "shared"}],
            }
        )
    models["roles"] = [models["roles"][0], *models["roles"][2:]]
    result = inventory_document(version, models, society)
    refs = [row["reference"] for row in result["entities"] if row["reference"]["id"] == "shared"]
    assert len(refs) == 6
    assert len({(ref["source"], ref["id"], ref.get("role_key")) for ref in refs}) == 6
    assert {ref.get("role_key") for ref in refs if ref["source"] == "role-subject"} == {
        "signals",
        "another_signal_role",
    }


def test_missing_collections_do_not_become_complete_empty_collections_for_any_engine():
    for engine in ENGINES:
        version, models, society = _documents()
        society["profile"] = engine.engine
        society["state"] = {"unrecognized_entities": [{"id": "somebody"}]}
        result = inventory_document(version, models, society)
        coverage = {row["source"]: row for row in result["coverage"]}
        for source in ("society.inhabitants", "society.things", "role.people.instances"):
            assert coverage[source]["state"] == "not_enumerated"
        assert not any(row["detail"] for row in result["entities"])


def test_society_display_names_take_precedence_and_blank_names_keep_fallbacks():
    version, models, society = _documents()
    society["state"]["inhabitants"] = [
        {
            "id": "placed",
            "placed_id": "shared",
            "display_name": "A retained name",
            "name": "Old name",
        },
        {"id": "unplaced", "display_name": "Another retained name", "name": "Other name"},
        {"id": "named", "display_name": "  ", "name": "Existing name"},
        {"id": "anonymous", "display_name": "", "name": "  "},
    ]
    result = inventory_document(version, models, society)
    by_id = {
        row["reference"]["id"]: row for row in result["entities"] if row["category"] == "being"
    }
    assert by_id["shared"]["label"] == "A retained name"
    assert by_id["shared"]["aliases"] == [{"source": "society-being", "id": "placed"}]
    assert by_id["unplaced"]["label"] == "Another retained name"
    assert by_id["named"]["label"] == "Existing name"
    assert by_id["anonymous"]["label"] == "anonymous"
