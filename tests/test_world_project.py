"""Synthetic checkpoint round trips; no live store, provider or private world is read."""

from copy import deepcopy

import pytest
from exulanica.canonical import canonical_json
from exulanica.world.decision_roles import decision_roles
from exulanica.world.objects import ObjectOrigin, Transform
from exulanica.world.placed_things import (
    PlacedThing,
    named_kind,
    placed_thing_document,
    shipped_kind,
)
from exulanica.world_package.projects.__main__ import main
from exulanica.world_package.projects.checkpoint import (
    Conflict,
    ProjectError,
    changes,
    checkpoint_digest,
    decode,
    digest,
    document,
    fork,
    inspect,
    playback,
    pretty,
    read,
    save,
)
from exulanica.world_package.projects.schema import Source


def sample():
    reference = named_kind("knight", 2)
    kind = shipped_kind(reference)
    role = decision_roles().role("society_decision")
    contract = role.contract(role.contract_versions).binding()
    source_bytes = canonical_json({"synthetic_source": True})
    contract_bytes = canonical_json(contract)
    manifest = {"provider": "synthetic", "model_id": "synthetic-model", "revision": "fixture-v1"}
    manifest_bytes = canonical_json(manifest)
    dependencies = {
        digest(source_bytes): source_bytes,
        digest(contract_bytes): contract_bytes,
        digest(manifest_bytes): manifest_bytes,
    }
    binding = {
        "thing_id": "knight:1",
        "role": role.key,
        "contract_sha256": digest(contract_bytes),
        "model_manifest_sha256": digest(manifest_bytes),
        **manifest,
    }
    project = {
        "profile": "exulanica.world-project/v1",
        "project_id": "project:synthetic",
        "source": {
            "world_id": "world:synthetic",
            "version_id": "version:fixture",
            "snapshot_id": "snapshot:fixture",
            "state_sha256": "a" * 64,
            "snapshot_sha256": digest(source_bytes),
        },
        "forked_from": None,
        "region_ids": ["region:one"],
        "things": [
            placed_thing_document(
                PlacedThing(
                    "knight:1",
                    reference,
                    "region:one",
                    Transform(0, 0, 0, 0, 1000),
                    ObjectOrigin("authored", "fictional"),
                )
            )
        ],
        "dependencies": [
            {"kind": label, "sha256": sha, "licence": "synthetic-test-only", "source_id": label}
            for label, sha in (
                ("source-snapshot", digest(source_bytes)),
                ("thing-kind", kind.sha256),
                ("decision-contract", digest(contract_bytes)),
                ("model-manifest", digest(manifest_bytes)),
            )
        ],
        "models": [binding],
        "decisions": [
            {
                "record_id": "record:1",
                "thing_id": "knight:1",
                "tick": 1,
                "binding_sha256": digest(canonical_json(binding)),
                "source_record_sha256": "b" * 64,
                "observation_sha256": "c" * 64,
                "options": [{"option_id": "option:wait", "action": "wait", "target_id": None}],
                "chosen_option_id": "option:wait",
                "outcome": "applied",
                "reason_code": "applied",
                "elapsed_ms": 1,
                "input_tokens": 10,
                "output_tokens": 1,
            }
        ],
    }
    return project, dependencies


def test_edit_save_reopen_fork_and_selected_playback(tmp_path):
    project, dependencies = sample()
    path = tmp_path / "first.json"
    initial = save(path, project)
    reopened = read(path)
    assert initial == checkpoint_digest(reopened)
    report = inspect(
        reopened, dependencies=dependencies, expected_source=Source(**project["source"])
    )
    assert report["dependencies_ready"]
    assert report["runtime_loadable"] is False
    edited = deepcopy(reopened)
    edited["things"][0]["transform"]["x_mm"] = 1500
    assert '"x_mm": 1500' in changes(reopened, edited)
    assert checkpoint_digest(edited) != initial
    branch = fork(edited, "project:fork")
    assert branch["forked_from"]["checkpoint_sha256"] == checkpoint_digest(edited)
    assert branch["source"] == project["source"]
    evidence = playback(branch)
    assert evidence["records"][0]["options"][0]["action"] == "wait"
    assert evidence["provider_calls"] == 0
    assert not evidence["engine_replay_verified"]
    assert not evidence["source_records_verified"]
    with pytest.raises(Conflict):
        save(path, edited)
    assert read(path) == reopened


def test_missing_corrupt_dependencies_and_stale_base_are_distinct():
    project, dependencies = sample()
    missing = inspect(project, dependencies={})
    assert len(missing["missing_dependencies"]) == 3  # Shipped kind resolves without fetching.
    assert not missing["dependencies_ready"]
    sha = project["models"][0]["model_manifest_sha256"]
    dependencies[sha] = b"corrupt"
    invalid = inspect(project, dependencies=dependencies)
    assert invalid["invalid_dependencies"] == [sha]
    assert not invalid["dependencies_ready"]
    base = dict(project["source"], state_sha256="d" * 64)
    with pytest.raises(Conflict, match="expected base"):
        inspect(project, dependencies={}, expected_source=Source(**base))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(credentials={"secret": "never-export"}),
        lambda p: p["things"][0].update(support={"private": "unsupported"}),
        lambda p: p["things"][0]["transform"].update(x_mm=1.5),
        lambda p: p["things"][0]["transform"].update(x_mm=True),
        lambda p: p["things"][0]["transform"].update(scale_milli=2000),
        lambda p: p["things"].append(deepcopy(p["things"][0])),
        lambda p: p["decisions"][0].update(chosen_option_id="option:not-offered"),
        lambda p: p["decisions"][0].update(binding_sha256="d" * 64),
        lambda p: p["models"][0].update(thing_id="thing:absent"),
        lambda p: p["dependencies"].clear(),
    ],
)
def test_refuses_malformed_private_or_unbound_content(mutate):
    project, _ = sample()
    mutate(project)
    with pytest.raises(ProjectError):
        document(project)


def test_canonical_order_duplicate_json_and_symlinks(tmp_path):
    project, _ = sample()
    initial = checkpoint_digest(project)
    project["dependencies"].reverse()
    assert checkpoint_digest(project) == initial
    with pytest.raises(ProjectError):
        decode(b'{"a":1,"a":2}')
    with pytest.raises(ProjectError):
        decode(b'{"a":NaN}')
    target = tmp_path / "target.json"
    save(target, project)
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ProjectError):
        read(link)
    with pytest.raises(Conflict):
        save(link, project)


def test_cli_roundtrip_and_dependency_exit_status(tmp_path, capsys):
    project, _ = sample()
    path = tmp_path / "input.json"
    save(path, project)
    assert main(["inspect", str(path)]) == 2
    assert "missing_dependencies" in capsys.readouterr().out
    output = tmp_path / "fork.json"
    assert main(["fork", str(path), "--output", str(output), "--project-id", "project:new"]) == 0
    assert read(output)["project_id"] == "project:new"
    assert main(["playback", str(output)]) == 0


def test_native_selection_preserves_base_and_excludes_other_things_and_actor(tmp_path):
    import uuid
    from dataclasses import replace

    from exulanica.world.authored_delta import AlternateVersion, version_delta_sha256
    from exulanica.world_package.projects.projection import select_checkpoint
    from exulanica.world_package.projects.schema import Checkpoint

    project, _ = sample()
    typed = Checkpoint.model_validate(project)
    knight = typed.things[0].native()
    other = replace(knight, thing_id="knight:private", region_id="region:private")
    version = AlternateVersion(
        version_id=uuid.UUID(int=1),
        world_id="world:synthetic",
        source_snapshot_id=uuid.UUID(int=2),
        parent_version_id=None,
        title="PRIVATE WORLD TITLE",
        style_version_id=None,
        state_sha256="a" * 64,
        edit_seq=4,
        source_invalidated=False,
        created_by=uuid.UUID(int=999),
        created_at="PRIVATE ACTOR TIME",
        things=(knight, other),
    )
    version = replace(version, state_sha256=version_delta_sha256(version))
    selected = select_checkpoint(
        version,
        project_id="project:native",
        selected_thing_ids=frozenset({knight.thing_id}),
        snapshot_sha256=typed.source.snapshot_sha256,
        dependencies=typed.dependencies,
    )
    assert selected["source"]["state_sha256"] == version.state_sha256
    assert selected["source"]["snapshot_id"] == str(version.source_snapshot_id)
    assert selected["source"]["version_id"] == str(version.version_id)
    assert len(selected["things"]) == 1
    assert selected["models"] == []
    assert selected["decisions"] == []
    assert "PRIVATE" not in pretty(selected).decode()
    assert "knight:private" not in pretty(selected).decode()
    save(tmp_path / "selected.json", selected)
    assert read(tmp_path / "selected.json") == selected
    with pytest.raises(ProjectError, match="invalidated"):
        select_checkpoint(
            replace(version, source_invalidated=True),
            project_id="project:native",
            selected_thing_ids=frozenset({knight.thing_id}),
            snapshot_sha256=typed.source.snapshot_sha256,
            dependencies=typed.dependencies,
        )
    with pytest.raises(ProjectError, match="bound digest"):
        select_checkpoint(
            replace(version, state_sha256="e" * 64),
            project_id="project:native",
            selected_thing_ids=frozenset({knight.thing_id}),
            snapshot_sha256=typed.source.snapshot_sha256,
            dependencies=typed.dependencies,
        )


def test_scenery_does_not_become_a_model_agent_and_unknown_contract_is_reported():
    project, dependencies = sample()
    reference = named_kind("bench", 2)
    project["things"][0]["kind"] = reference.document()
    for dependency in project["dependencies"]:
        if dependency["kind"] == "thing-kind":
            dependency["sha256"] = reference.sha256
    report = inspect(project, dependencies=dependencies)
    assert report["unsupported"] == ["model-role:knight:1"]
    assert not report["dependencies_ready"]

    project, dependencies = sample()
    payload = canonical_json({"catalog_versions": {}, "sha256": "f" * 64})
    original = project["models"][0]["contract_sha256"]
    replacement = digest(payload)
    dependencies[replacement] = payload
    project["models"][0]["contract_sha256"] = replacement
    project["decisions"] = []
    for dependency in project["dependencies"]:
        if dependency["sha256"] == original:
            dependency["sha256"] = replacement
    report = inspect(project, dependencies=dependencies)
    assert report["unsupported"] == ["decision-contract:knight:1"]


def test_digest_matched_null_dependency_is_invalid():
    project, dependencies = sample()
    old = project["models"][0]["model_manifest_sha256"]
    new = digest(b"null")
    project["models"][0]["model_manifest_sha256"] = new
    project["decisions"] = []
    for dependency in project["dependencies"]:
        if dependency["sha256"] == old:
            dependency["sha256"] = new
    dependencies[new] = b"null"
    report = inspect(project, dependencies=dependencies)
    assert report["invalid_dependencies"] == [new]
    assert not report["dependencies_ready"]
