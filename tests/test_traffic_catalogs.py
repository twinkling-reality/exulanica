"""The traffic catalogs: every number a vehicle, a rule or a signal uses comes from a cited file.

What is pinned here, and why.

*   The five catalogs **load**, and hold the classes, policies and plan the simulation names, and
    the vehicle classes each of the city's lane uses and parking kinds admits.
*   Every numeric field names **exactly one source**, either a citation of a reference the file
    lists or a declared reason, and the **declared values are the listed ones**: adding a declared
    number is a reviewed change, not a quiet one.
*   The loader **refuses** an unknown key, a missing or unparseable source, a citation of an
    unknown reference, an unused reference, a float, a stray or missing file, dimensions that do
    not add up, a policy whose headways do not match its rule, a signal group that never gets
    right of way, a mapping to an unknown class, and a parking kind that admits nothing.
*   The **digest** is the same in a new process under another hash seed, and changes when a
    citation changes, because a citation is part of what was decided.
*   The **file digest** is the SHA-256 of the file bytes, and the signal plan's bytes are the
    ones the city vocabulary fixture names.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from exulanica.traffic.catalogs import (
    CATALOG_DIRECTORY,
    catalogs_digest,
    declared_values,
    load_traffic_catalogs,
)
from exulanica.traffic.errors import TrafficCatalogError

ROOT = Path(__file__).resolve().parents[1]

#: The signal plan's file bytes as the city vocabulary lane's fixture pins them. If this test
#: fails because the plan changed on purpose, send the new SHA-256 to the orchestrator for lane 20.
SIGNAL_PLAN_SHA256 = "5a428368b682ddf4147bf84c48ec56e6979bc85fdc920b8eab08279739b1c8be"

#: ``(catalog, entry, field)`` for every value that is declared rather than cited.
DECLARED = (
    ("vehicle-class", "bicycle", "body_families"),
    ("vehicle-class", "bicycle", "colours"),
    ("vehicle-class", "bicycle", "front_overhang_mm"),
    ("vehicle-class", "bicycle", "height_mm"),
    ("vehicle-class", "bicycle", "minimum_gap_mm"),
    ("vehicle-class", "bicycle", "minimum_turning_radius_mm"),
    ("vehicle-class", "bicycle", "parking_entry_ms"),
    ("vehicle-class", "bicycle", "parking_exit_ms"),
    ("vehicle-class", "bicycle", "rear_overhang_mm"),
    ("vehicle-class", "bicycle", "turning_inward_extent_mm"),
    ("vehicle-class", "bicycle", "turning_outward_extent_mm"),
    ("vehicle-class", "bicycle", "turning_speed_mm_per_s"),
    ("vehicle-class", "bicycle", "wheelbase_mm"),
    ("vehicle-class", "city_bus", "body_families"),
    ("vehicle-class", "city_bus", "colours"),
    ("vehicle-class", "city_bus", "minimum_gap_mm"),
    ("vehicle-class", "city_bus", "parking_entry_ms"),
    ("vehicle-class", "city_bus", "parking_exit_ms"),
    ("vehicle-class", "city_bus", "speed_cap_mm_per_s"),
    ("vehicle-class", "passenger_car", "body_families"),
    ("vehicle-class", "passenger_car", "colours"),
    ("vehicle-class", "passenger_car", "parking_entry_ms"),
    ("vehicle-class", "passenger_car", "parking_exit_ms"),
    ("vehicle-class", "passenger_car", "speed_cap_mm_per_s"),
    ("vehicle-class", "van", "body_families"),
    ("vehicle-class", "van", "colours"),
    ("vehicle-class", "van", "parking_entry_ms"),
    ("vehicle-class", "van", "parking_exit_ms"),
    ("vehicle-class", "van", "speed_cap_mm_per_s"),
    ("right-of-way-policy", "all_way_stop", "arrival_order"),
    ("right-of-way-policy", "priority_two_way_stop", "arrival_order"),
    ("right-of-way-policy", "signalised", "arrival_order"),
    ("right-of-way-policy", "uncontrolled_continuation", "arrival_order"),
    ("right-of-way-policy", "uncontrolled_continuation", "rule"),
    ("right-of-way-policy", "uncontrolled_continuation", "turn_priority"),
    ("signal-plan", "fixed_two_phase_60s", "intervals[1].duration_ms"),
    ("signal-plan", "fixed_two_phase_60s", "intervals[5].duration_ms"),
    ("lane-use-access", "buffer", "classes"),
    ("lane-use-access", "bus", "classes"),
    ("lane-use-access", "cycle", "classes"),
    ("lane-use-access", "general", "classes"),
    ("lane-use-access", "parking", "classes"),
    ("parking-kind-access", "accessible", "classes"),
    ("parking-kind-access", "bus_layover", "classes"),
    ("parking-kind-access", "cycle_stand", "classes"),
    ("parking-kind-access", "general", "classes"),
    ("parking-kind-access", "loading", "classes"),
)

_VEHICLE_NUMBERS = (
    "length_mm",
    "width_mm",
    "height_mm",
    "wheelbase_mm",
    "front_overhang_mm",
    "rear_overhang_mm",
    "minimum_turning_radius_mm",
    "turning_inward_extent_mm",
    "turning_outward_extent_mm",
    "speed_cap_mm_per_s",
    "turning_speed_mm_per_s",
    "acceleration_mm_per_s2",
    "deceleration_mm_per_s2",
    "minimum_gap_mm",
    "parking_entry_ms",
    "parking_exit_ms",
)


@pytest.fixture
def copied(tmp_path: Path) -> Path:
    """A private copy of the catalog directory a test may break."""
    target = tmp_path / "traffic"
    shutil.copytree(CATALOG_DIRECTORY, target)
    return target


def _edit(directory: Path, name: str, change) -> None:
    path = directory / name
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _refused(directory: Path, fragment: str) -> None:
    with pytest.raises(TrafficCatalogError) as caught:
        load_traffic_catalogs(directory)
    assert fragment in str(caught.value), str(caught.value)


# ---------------------------------------------------------------------------------------------
# What the catalogs hold


def test_the_catalogs_live_in_their_own_directory_under_the_catalog_root():
    # The city catalog loader refuses unknown files in assets/catalogs, so traffic has its own.
    assert CATALOG_DIRECTORY == ROOT / "assets" / "catalogs" / "traffic"
    assert sorted(path.name for path in CATALOG_DIRECTORY.iterdir()) == [
        "lane-use-access.v1.json",
        "parking-kind-access.v1.json",
        "right-of-way-policy.v1.json",
        "signal-plan.v1.json",
        "vehicle-class.v1.json",
    ]
    assert not list(CATALOG_DIRECTORY.parent.glob("vehicle-class*.json"))


def test_the_catalogs_load_with_the_entries_the_simulation_names():
    catalogs = load_traffic_catalogs()
    assert [entry.key for entry in catalogs.vehicle_classes] == [
        "bicycle",
        "city_bus",
        "passenger_car",
        "van",
    ]
    assert [entry.key for entry in catalogs.policies] == [
        "all_way_stop",
        "priority_two_way_stop",
        "signalised",
        "uncontrolled_continuation",
    ]
    assert [entry.key for entry in catalogs.plans] == ["fixed_two_phase_60s"]
    assert [policy.rule for policy in catalogs.policies] == [
        "all_way_stop",
        "priority",
        "signal",
        "uncontrolled",
    ]
    plan = catalogs.plan("fixed_two_phase_60s")
    assert plan.cycle_ms == 60_000
    assert [group.key for group in plan.groups] == ["phase_a", "phase_b", "walk_a", "walk_b"]


def test_the_city_keys_map_to_the_classes_they_admit():
    """Keyed by the city's own lane-use and parking-kind keys, every key of each city catalog."""
    catalogs = load_traffic_catalogs()
    for city_catalog, mappings in (
        ("lane-use", catalogs.lane_uses),
        ("parking-kind", catalogs.parking_kinds),
    ):
        city = json.loads((ROOT / "assets" / "catalogs" / f"{city_catalog}.v1.json").read_text())
        assert [mapping.key for mapping in mappings] == sorted(
            entry["key"] for entry in city["entries"]
        )
    assert {mapping.key: mapping.classes for mapping in catalogs.lane_uses} == {
        "buffer": (),
        "bus": ("city_bus",),
        "cycle": ("bicycle",),
        "general": ("bicycle", "city_bus", "passenger_car", "van"),
        "parking": (),
    }
    assert {mapping.key: mapping.classes for mapping in catalogs.parking_kinds} == {
        "accessible": ("passenger_car", "van"),
        "bus_layover": ("city_bus",),
        "cycle_stand": ("bicycle",),
        "general": ("passenger_car", "van"),
        "loading": ("van",),
    }
    # Exactly the lane uses the city says carry no traffic map to no class.
    city = json.loads((ROOT / "assets" / "catalogs" / "lane-use.v1.json").read_text())
    assert {entry["key"] for entry in city["entries"] if entry["traffic"] == "none"} == {
        mapping.key for mapping in catalogs.lane_uses if not mapping.classes
    }


def test_the_design_vehicles_carry_the_cited_numbers():
    """Spot checks against the tables the citations name, so a transcription slip shows."""
    catalogs = load_traffic_catalogs()
    car = catalogs.vehicle_class("passenger_car")
    assert (car.length_mm, car.width_mm, car.wheelbase_mm) == (5_790, 2_130, 3_350)
    assert (car.minimum_turning_radius_mm, car.turning_inward_extent_mm) == (6_400, 6_400 - 4_390)
    assert car.turning_outward_extent_mm == 7_260 - 6_400
    assert (car.acceleration_mm_per_s2, car.deceleration_mm_per_s2) == (730, 1_670)
    bus = catalogs.vehicle_class("city_bus")
    assert (bus.length_mm, bus.width_mm, bus.wheelbase_mm) == (12_190, 2_590, 7_620)
    assert bus.turning_inward_extent_mm == 11_520 - 7_450
    assert bus.turning_outward_extent_mm == 12_800 - 11_520
    bicycle = catalogs.vehicle_class("bicycle")
    assert (bicycle.length_mm, bicycle.width_mm, bicycle.speed_cap_mm_per_s) == (1_780, 690, 6_111)
    # 15 km/h is 4166.67 mm/s, floored.
    assert {entry.turning_speed_mm_per_s for entry in catalogs.vehicle_classes} == {4_166}
    policy = catalogs.policy("priority_two_way_stop")
    assert dict(policy.critical_headway_ms) == {
        "major_left": 4_100,
        "minor_left": 7_100,
        "minor_right": 6_200,
        "minor_through": 6_500,
    }
    plan = catalogs.plan("fixed_two_phase_60s")
    assert plan.pedestrian_clearance_speed_mm_per_s == 1_066
    assert plan.pedestrian_total_speed_mm_per_s == 914
    assert plan.pedestrian_total_extra_mm == 1_829


def test_every_numeric_field_names_exactly_one_source():
    catalogs = load_traffic_catalogs()
    references = {
        catalog_id: set(payload["references"]) for catalog_id, payload in catalogs.payloads
    }
    rows = []
    for vehicle in catalogs.vehicle_classes:
        assert {name for name, _ in vehicle.sources} == set(_VEHICLE_NUMBERS) | {
            "body_families",
            "colours",
        }
        rows += [("vehicle-class", text) for _, text in vehicle.sources]
    for policy in catalogs.policies:
        expected = {"rule", "turn_priority", "arrival_order"} | {
            f"critical_headway_ms.{name}" for name, _ in policy.critical_headway_ms
        }
        assert {name for name, _ in policy.sources} == expected
        rows += [("right-of-way-policy", text) for _, text in policy.sources]
    for plan in catalogs.plans:
        expected = {f"intervals[{index}].duration_ms" for index in range(len(plan.intervals))} | {
            "pedestrian_clearance_speed_mm_per_s",
            "pedestrian_total_speed_mm_per_s",
            "pedestrian_total_extra_mm",
        }
        assert {name for name, _ in plan.sources} == expected
        rows += [("signal-plan", text) for _, text in plan.sources]
    for catalog_id, mappings in (
        ("lane-use-access", catalogs.lane_uses),
        ("parking-kind-access", catalogs.parking_kinds),
    ):
        for mapping in mappings:
            assert {name for name, _ in mapping.sources} == {"classes"}
            rows += [(catalog_id, text) for _, text in mapping.sources]
    assert len(rows) == 4 * 18 + (3 + 4) + (3 + 1) + 3 + 3 + (8 + 3) + 5 + 5
    for catalog_id, text in rows:
        if text.startswith("declared: "):
            assert len(text) > len("declared: ") + 20, text
            continue
        assert text.startswith("cited "), text
        cited = text[len("cited ") :].split(":", 1)[0].split(" and ")
        assert set(cited) <= references[catalog_id], text


def test_the_declared_values_are_exactly_the_reviewed_list():
    rows = declared_values(load_traffic_catalogs())
    assert tuple((catalog, entry, field) for catalog, entry, field, _ in rows) == DECLARED
    assert all(reason.strip() == reason and reason for _, _, _, reason in rows)


def test_every_reference_is_cited_and_every_licence_names_files_that_exist():
    catalogs = load_traffic_catalogs()
    for catalog_id, payload in catalogs.payloads:
        cited = set()
        for entry in payload["entries"]:
            for text in entry["sources"].values():
                if text.startswith("cited "):
                    cited |= set(text[len("cited ") :].split(":", 1)[0].split(" and "))
            licence = entry["licence"]
            assert (licence["spdx"], licence["origin"]) == ("Apache-2.0", "original")
            for name in ("licence_source", "content_source"):
                assert (ROOT / licence[name]).is_file(), (catalog_id, entry["key"], licence[name])
        assert cited == set(payload["references"]), catalog_id


# ---------------------------------------------------------------------------------------------
# What the loader refuses


def test_the_committed_directory_copied_elsewhere_still_loads(copied):
    assert load_traffic_catalogs(copied).digest == load_traffic_catalogs().digest


def test_an_unknown_key_is_refused(copied):
    _edit(
        copied,
        "vehicle-class.v1.json",
        lambda document: document["entries"][0].update({"top_speed_mm_per_s": 9_000}),
    )
    _refused(copied, "unknown keys ['top_speed_mm_per_s']")


def test_a_value_without_a_source_is_refused(copied):
    _edit(
        copied,
        "vehicle-class.v1.json",
        lambda document: document["entries"][2]["sources"].pop("width_mm"),
    )
    _refused(copied, "misses ['width_mm']")


def test_a_source_for_a_value_that_does_not_exist_is_refused(copied):
    _edit(
        copied,
        "right-of-way-policy.v1.json",
        lambda document: document["entries"][2]["sources"].update(
            {"critical_headway_ms.major_left": "declared: a headway the rule does not read"}
        ),
    )
    _refused(copied, "names unknown values ['critical_headway_ms.major_left']")


def test_a_source_that_neither_cites_nor_declares_is_refused(copied):
    _edit(
        copied,
        "signal-plan.v1.json",
        lambda document: document["entries"][0]["sources"].update(
            {"intervals[0].duration_ms": "MUTCD says so"}
        ),
    )
    _refused(copied, "starts 'cited <ref>: ' or 'declared: '")


def test_a_citation_of_an_unknown_reference_is_refused(copied):
    _edit(
        copied,
        "vehicle-class.v1.json",
        lambda document: document["entries"][1]["sources"].update(
            {"length_mm": "cited aashto_2018: Table 2-1a"}
        ),
    )
    _refused(copied, "cites 'aashto_2018', which is not a reference")


def test_a_reference_no_entry_cites_is_refused(copied):
    _edit(
        copied,
        "right-of-way-policy.v1.json",
        lambda document: document["references"].update({"unread_manual": "A manual never read"}),
    )
    _refused(copied, "references ['unread_manual'] are cited by no entry")


def test_a_float_is_refused(copied):
    path = copied / "vehicle-class.v1.json"
    text = path.read_text(encoding="utf-8")
    assert text.count('"length_mm": 5790,') == 2
    path.write_text(text.replace('"length_mm": 5790,', '"length_mm": 5790.5,', 1), encoding="utf-8")
    _refused(copied, "non-integer number 5790.5")


def test_a_stray_or_missing_file_is_refused(copied):
    (copied / "tram-class.v1.json").write_text("{}\n", encoding="utf-8")
    _refused(copied, "expected")
    (copied / "tram-class.v1.json").unlink()
    (copied / "signal-plan.v1.json").unlink()
    _refused(copied, "expected")


def test_dimensions_that_do_not_add_up_are_refused(copied):
    _edit(
        copied,
        "vehicle-class.v1.json",
        lambda document: document["entries"][2].update({"wheelbase_mm": 3_500}),
    )
    _refused(copied, "overhangs and wheelbase sum to 5930, not 5790")


def test_a_policy_whose_headways_do_not_match_its_rule_is_refused(copied):
    _edit(
        copied,
        "right-of-way-policy.v1.json",
        lambda document: document["entries"][1]["critical_headway_ms"].pop("minor_left"),
    )
    _refused(copied, "the priority rule reads exactly")


def test_only_an_all_way_stop_may_order_by_arrival(copied):
    _edit(
        copied,
        "right-of-way-policy.v1.json",
        lambda document: document["entries"][2].update(
            {"arrival_order": "first_stopped_first_served"}
        ),
    )
    _refused(copied, "only the all_way_stop rule orders by arrival")


def test_a_signal_group_that_never_gets_right_of_way_is_refused(copied):
    def never_walk_b(document):
        for interval in document["entries"][0]["intervals"]:
            for field in ("pedestrian_walk", "pedestrian_clearance"):
                interval[field] = [group for group in interval[field] if group != "walk_b"]

    _edit(copied, "signal-plan.v1.json", never_walk_b)
    _refused(copied, "group 'walk_b' is never given right of way")


def test_a_group_green_and_amber_at_once_is_refused(copied):
    _edit(
        copied,
        "signal-plan.v1.json",
        lambda document: document["entries"][0]["intervals"][0]["vehicle_amber"].append("phase_a"),
    )
    _refused(copied, "a group is green and amber at once")


def test_a_mapping_to_an_unknown_class_is_refused(copied):
    _edit(
        copied,
        "lane-use-access.v1.json",
        lambda document: document["entries"][2].update({"classes": ["bicycle", "tram"]}),
    )
    _refused(copied, "cycle admits unknown classes ['tram']")


def test_a_parking_kind_that_admits_nothing_is_refused(copied):
    _edit(
        copied,
        "parking-kind-access.v1.json",
        lambda document: document["entries"][4].update({"classes": []}),
    )
    _refused(copied, "is a non-empty list of keys")


def test_entries_out_of_key_order_are_refused(copied):
    _edit(
        copied,
        "vehicle-class.v1.json",
        lambda document: document["entries"].reverse(),
    )
    _refused(copied, "entries are sorted by key")


# ---------------------------------------------------------------------------------------------
# Digests

_DIGEST = r"""
import sys
import exulanica.traffic.catalogs as module
catalogs = module.load_traffic_catalogs()
print(module.__file__)
print(catalogs.digest)
print(catalogs.file_digest("signal-plan"))
"""


def _digest_in_a_new_process(hash_seed: str) -> tuple[str, str]:
    result = subprocess.run(
        [sys.executable, "-c", _DIGEST],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONHASHSEED": hash_seed},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    module_path, digest, plan_digest = result.stdout.split()
    # A child that imported another checkout's package would measure the wrong code.
    assert Path(module_path).resolve().is_relative_to(ROOT), module_path
    return digest, plan_digest


def test_the_digest_is_the_same_in_new_processes_under_other_hash_seeds():
    catalogs = load_traffic_catalogs()
    expected = (catalogs.digest, catalogs.file_digest("signal-plan"))
    assert _digest_in_a_new_process("0") == expected
    assert _digest_in_a_new_process("4294967295") == expected
    assert catalogs_digest(catalogs) == catalogs.digest
    assert len(catalogs.digest) == 64


def test_changing_only_a_citation_changes_the_digest(copied):
    before = load_traffic_catalogs(copied).digest
    _edit(
        copied,
        "vehicle-class.v1.json",
        lambda document: document["entries"][2]["sources"].update(
            {"length_mm": "cited aashto_2011: Table 2-1a, P, overall length 5.79 m, re-read"}
        ),
    )
    assert load_traffic_catalogs(copied).digest != before


def test_the_file_digests_are_the_sha256_of_the_file_bytes():
    catalogs = load_traffic_catalogs()
    assert dict(catalogs.file_sha256) == {
        path.name.split(".v1.json")[0]: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in CATALOG_DIRECTORY.glob("*.json")
    }


def test_the_signal_plan_bytes_are_the_ones_the_city_fixture_names():
    """Lane 20's signal records carry this digest. A deliberate change goes to the orchestrator."""
    assert load_traffic_catalogs().file_digest("signal-plan") == SIGNAL_PLAN_SHA256
