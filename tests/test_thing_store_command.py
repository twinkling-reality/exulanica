"""The operator's command admits a look into one workspace only as a bridge's mapping names it, and
lists and withdraws a workspace's looks.

The mapping is the door tests' invented one (``door_support``), its one visitor's looks naming the
look under test, pinned by digest through ``EXULANICA_DOOR_BRIDGES``. Shown here:

*   with no database: a mapping file is admitted only when it is a mapping and a bridge the
    deployment declares pins its digest; the intake's check admits only an imported look the
    mapping names, by digest or by its whole reference, with the entry's source among its
    ingredients and the entry's SPDX identifier and share-alike mark;
*   against PostgreSQL, through the environment the command reads itself (``cli_database``), with
    the container written to the workspace's ``looks`` namespace under a data directory of the
    test's own: a dry run checks and writes nothing; a copy relabelled CC0 and public and a mapping
    no bridge pins are refused with nothing written; the positive control; once only; a listing; a
    withdrawal, and a refused one;
*   with no database, the dry runs refuse a look document that is not JSON and a withdrawal reason
    that is not one plain line, by name.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from exulanica.api.thing_store_command import (
    MappingNotAdmitted,
    admitted_mapping,
    main,
    mapping_admits,
)
from exulanica.door.bridges import load_bridge_directory
from exulanica.door.mapping import MappingRefused, check_mapping
from exulanica.evidence.blob import BlobId
from exulanica.store.configured import content_stores
from exulanica.things.authored import container_of
from exulanica.things.looks import Look, read_look
from exulanica.world.thing_store import ThingStoreRefused

import door_support
from test_thing_store_admission import _imported, _sculpted

SOURCE = "c" * 64
ACTOR = "00000000-0000-4000-8000-00000000c5a2"


def _entry(look: Look) -> dict[str, Any]:
    """A mapping's look entry naming ``look`` by digest, with the look's source and licence."""
    stated = look.document["origin"]["licence"]
    licence: dict[str, Any] = {"spdx": stated["spdx"], "share_alike": stated["share_alike"]}
    for field in ("attribution", "licence_url"):
        if stated[field] is not None:
            licence[field] = stated[field]
    return {
        "look_key": "own-look",
        "look": f"sha256:{look.sha256}",
        "licence": licence,
        "source_sha256": SOURCE,
    }


def _mapping(*entries: dict[str, Any]) -> dict[str, Any]:
    document = copy.deepcopy(door_support.MAPPING)
    document["key"] = "test-own-looks"
    document["visitors"][0]["looks"] = list(entries)
    return document


def _pinning(*mappings: dict[str, Any]) -> str:
    """``EXULANICA_DOOR_BRIDGES`` with the test bridge pinning ``mappings`` as well."""
    declared = json.loads(door_support.bridges_setting())
    declared[0]["mapping_sha256"] += [door_support.mapping_sha256(m) for m in mappings]
    return json.dumps(declared)


def test_a_mapping_file_is_admitted_only_when_a_declared_bridge_pins_it():
    mapping = _mapping(_entry(read_look(_imported())))
    raw = json.dumps(mapping).encode()
    pinned = load_bridge_directory({"EXULANICA_DOOR_BRIDGES": _pinning(mapping)})
    assert admitted_mapping(raw, pinned) == mapping
    for directory in (
        load_bridge_directory({"EXULANICA_DOOR_BRIDGES": _pinning()}),
        load_bridge_directory({}),
    ):
        with pytest.raises(MappingNotAdmitted):
            admitted_mapping(raw, directory)
    # Pinned, but not a mapping the door's check reads.
    unread = {key: value for key, value in mapping.items() if key != "actions"}
    unread_pinned = load_bridge_directory({"EXULANICA_DOOR_BRIDGES": _pinning(unread)})
    with pytest.raises(MappingRefused):
        admitted_mapping(json.dumps(unread).encode(), unread_pinned)
    for broken in (b"not json", json.dumps([mapping]), json.dumps({**mapping, "version": 1.5})):
        with pytest.raises(MappingRefused):
            admitted_mapping(broken if isinstance(broken, bytes) else broken.encode(), pinned)


@pytest.mark.parametrize("case", ["unnamed", "source", "spdx", "share_alike", "class"])
def test_the_intake_admits_only_a_look_its_mapping_names_as_it_is(case):
    look = read_look(_imported())
    entry = _entry(look)
    # The positive control: the look its mapping names, as it is.
    mapping_admits(check_mapping(_mapping(entry)))(look)
    if case == "unnamed":
        entry["look"] = "sha256:" + "0" * 64
    elif case == "source":
        entry["source_sha256"] = "d" * 64
    elif case == "spdx":
        entry["licence"]["spdx"] = "CC-BY-4.0"
    elif case == "share_alike":
        entry["licence"]["share_alike"] = False
    else:
        # A generated look the mapping names with its own source and licence: not an import.
        document, _container = _sculpted()
        document["origin"]["lineage"]["ingredients"] = [SOURCE]
        look = read_look(document)
        entry = _entry(look)
    with pytest.raises(ThingStoreRefused) as refused:
        mapping_admits(check_mapping(_mapping(entry)))(look)
    assert refused.value.code == "look_not_admitted"


def test_a_mapping_naming_its_look_by_reference_admits_it_only_whole():
    # A bridge-mapping/v2 entry names its look by the library's reference. The door's reader of
    # that profile is not on this base, so the mapping is handed to the check as written.
    look = read_look(_imported())
    entry = {**_entry(look), "look": look.reference()}
    mapping_admits(_mapping(entry))(look)
    for changed in ({"version": 2}, {"look": "another-look"}):
        moved = {**entry, "look": {**look.reference(), **changed}}
        with pytest.raises(ThingStoreRefused) as refused:
            mapping_admits(_mapping(moved))(look)
        assert refused.value.code == "look_not_admitted"


def test_a_dry_run_refuses_what_it_can_read_without_a_database(built, tmp_path, capsys):
    workspace = uuid.uuid4()
    unreadable = tmp_path / "not-json.v1.json"
    unreadable.write_bytes(b"\x89PNG not a look document")
    assert _admit(workspace, built, tmp_path / "data", document=unreadable) == 1
    assert "refused: look_refused: the look document is not JSON" in capsys.readouterr().out
    withdraw = [
        "withdraw-look",
        "--workspace",
        str(workspace),
        "--actor",
        ACTOR,
        "--look",
        "fixture-traveller-own",
        "--version",
        "1",
        "--reason",
        "no longer\ngranted",
    ]
    assert main(withdraw) == 1
    assert "refused: withdrawal_reason_refused" in capsys.readouterr().out


@pytest.fixture
def built(tmp_path, monkeypatch) -> dict[str, Path]:
    """A built look, its container and the mapping naming it, which the deployment pins."""
    document = _imported()
    mapping = _mapping(_entry(read_look(document)))
    paths = {name: tmp_path / name for name in ("look.v1.json", "look.glb", "mapping.json")}
    paths["look.v1.json"].write_text(json.dumps(document), encoding="utf-8")
    paths["look.glb"].write_bytes(container_of("blocky-traveller"))
    paths["mapping.json"].write_text(json.dumps(mapping), encoding="utf-8")
    monkeypatch.setenv("EXULANICA_DOOR_BRIDGES", _pinning(mapping))
    monkeypatch.delenv("EXULANICA_STORE_KIND", raising=False)
    return paths


def _admit(
    workspace: uuid.UUID,
    paths: dict[str, Path],
    data_dir: Path,
    *extra: str,
    document: Path | None = None,
    mapping: Path | None = None,
) -> int:
    return main(
        [
            "admit-look",
            "--workspace",
            str(workspace),
            "--actor",
            ACTOR,
            "--document",
            str(document or paths["look.v1.json"]),
            "--container",
            str(paths["look.glb"]),
            "--mapping",
            str(mapping or paths["mapping.json"]),
            "--data-dir",
            str(data_dir),
            *extra,
        ]
    )


def _listed(workspace: uuid.UUID, capsys) -> str:
    assert main(["list", "--workspace", str(workspace)]) == 0
    return capsys.readouterr().out


def _container_held(paths: dict[str, Path], data: Path, workspace: uuid.UUID) -> bool:
    held = BlobId.from_hex(hashlib.sha256(paths["look.glb"].read_bytes()).hexdigest())
    return content_stores(data_dir=data).looks.for_workspace(workspace).exists(held)


@pytest.mark.postgres
def test_a_dry_run_checks_the_look_against_its_mapping_and_writes_nothing(
    built, tmp_path, capsys, cli_database
):
    workspace = uuid.uuid4()
    assert _admit(workspace, built, tmp_path / "data") == 0
    assert "would admit fixture-traveller-own v1" in capsys.readouterr().out
    assert _listed(workspace, capsys) == ""
    assert not _container_held(built, tmp_path / "data", workspace)


@pytest.mark.postgres
def test_a_relabelled_copy_and_an_unpinned_mapping_are_refused_with_nothing_written(
    built, tmp_path, capsys, cli_database
):
    workspace, data = uuid.uuid4(), tmp_path / "data"
    # The built look relabelled CC0 and public, still naming its source: its digest is not the
    # one the mapping names.
    relabelled = tmp_path / "relabelled.v1.json"
    relabelled.write_text(
        json.dumps(
            _imported(
                spdx="CC0-1.0",
                verdict="SHIP",
                attribution=None,
                share_alike=False,
                licence_url=None,
            )
        ),
        encoding="utf-8",
    )
    for extra in ((), ("--apply",)):
        assert _admit(workspace, built, data, *extra, document=relabelled) == 1
        assert "look_not_admitted" in capsys.readouterr().out
    # A mapping no bridge this deployment declares pins.
    unpinned = tmp_path / "unpinned.json"
    unpinned.write_text(
        json.dumps({**json.loads(built["mapping.json"].read_text(encoding="utf-8")), "version": 3}),
        encoding="utf-8",
    )
    assert _admit(workspace, built, data, "--apply", mapping=unpinned) == 1
    assert "mapping_not_admitted" in capsys.readouterr().out
    assert _listed(workspace, capsys) == ""
    assert not _container_held(built, data, workspace)


@pytest.mark.postgres
def test_the_operator_admits_lists_and_withdraws_a_built_look(
    built, tmp_path, capsys, cli_database
):
    workspace, data = uuid.uuid4(), tmp_path / "data"
    assert _admit(workspace, built, data, "--apply") == 0
    assert capsys.readouterr().out.startswith("admitted fixture-traveller-own v1")
    assert _container_held(built, data, workspace)
    assert not _container_held(built, data, uuid.uuid4())
    assert "imported CC-BY-SA-4.0 exulanica.static-glb/v1 held" in _listed(workspace, capsys)
    # Once only; then withdrawn for good.
    assert _admit(workspace, built, data, "--apply") == 1
    assert "thing_version_exists" in capsys.readouterr().out
    withdraw = [
        "withdraw-look",
        "--workspace",
        str(workspace),
        "--actor",
        ACTOR,
        "--look",
        "fixture-traveller-own",
        "--version",
        "1",
        "--reason",
        "the deployment no longer grants these travellers",
    ]
    assert main(withdraw) == 0
    assert capsys.readouterr().out.startswith("would withdraw")
    assert main([*withdraw, "--apply"]) == 0
    capsys.readouterr()
    assert "withdrawn (the deployment no longer grants these travellers)" in _listed(
        workspace, capsys
    )
    unknown = [*withdraw, "--apply"]
    unknown[unknown.index("fixture-traveller-own")] = "fixture-never-held"
    assert main(unknown) == 1
    assert "look_unknown" in capsys.readouterr().out
