"""Local project folders as plain git repositories; synthetic checkpoints, no network or world."""

import json
import subprocess
from copy import deepcopy

import pytest
from exulanica.world_package.projects.checkpoint import Conflict, ProjectError, checkpoint_digest
from exulanica.world_package.projects.repository import (
    Author,
    Project,
    check_message,
    create,
    fork_project,
)
from exulanica.world_package.projects.summary import summarize

from test_world_project import sample

START = [
    "Started the project with 1 thing",
    "Changed the knight's model to synthetic-model",
    "Recorded 1 decision",
]
AUTHOR = Author("Synthetic Student", "student@example.invalid")


def git(folder, *arguments):
    return subprocess.run(
        ["git", f"--git-dir={folder / '.git'}", *arguments],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": str(folder)},
    ).stdout


def commits(folder):
    return int(git(folder, "rev-list", "--count", "HEAD").strip())


@pytest.fixture(autouse=True)
def foreign_git_environment(monkeypatch, tmp_path):
    """A caller inside another checkout's hook must not steer git at that checkout."""
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(decoy / "index"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    yield
    assert list(decoy.iterdir()) == []


def test_create_save_noop_and_plain_words(tmp_path):
    project, dependencies = sample()
    folder = tmp_path / "garden-project"
    first = create(folder, project, author=AUTHOR, dependencies=dependencies)
    assert first["committed"] and first["message"] == "Started the project"
    assert first["summary"] == START
    assert git(folder, "remote").strip() == ""
    assert [p.name for p in (folder / ".git" / "hooks").glob("*")] == []
    assert git(folder, "log", "-1", "--format=%B").strip() == "Started the project"

    local = Project(folder, author=AUTHOR)
    # Saving the same selection, however often the world runs, commits nothing.
    for _ in range(3):
        again = local.save(project, dependencies=dependencies)
        assert (again["committed"], again["reason"]) == (False, "unchanged")
    assert commits(folder) == 1

    moved = deepcopy(project)
    moved["things"][0]["transform"]["x_mm"] += 2000
    moved["things"][0]["transform"]["z_mm"] -= 500
    saved = local.save(moved)
    assert saved["committed"]
    assert saved["summary"] == ["Moved the knight 2 m east and 0.5 m north"]
    assert saved["message"] == "Moved the knight 2 m east and 0.5 m north"
    assert '"x_mm": 2000' in saved["diff"]
    assert commits(folder) == 2
    assert [entry["message"] for entry in local.history()] == [
        "Moved the knight 2 m east and 0.5 m north",
        "Started the project",
    ]
    assert local.compare("HEAD~1")["summary"] == saved["summary"]


def test_edits_in_the_folder_save_with_an_own_message(tmp_path):
    project, _ = sample()
    folder = tmp_path / "project"
    create(folder, project, author=AUTHOR)
    local = Project(folder, author=AUTHOR)
    edited = deepcopy(project)
    edited["decisions"] = []
    edited["models"] = []
    (folder / "world-project.json").write_text(json.dumps(edited, indent=2), encoding="utf-8")
    assert local.reopen()["uncommitted_edits"] == [
        "Changed the knight's model to Routine",
        "Dropped 1 decision",
    ]
    saved = local.save(message="Let the knight follow its routine")
    assert saved["committed"] and saved["message"] == "Let the knight follow its routine"
    assert local.reopen()["uncommitted_edits"] == []


def test_reopen_reports_a_missing_dependency_and_installs_nothing(tmp_path):
    project, dependencies = sample()
    folder = tmp_path / "project"
    create(folder, project, author=AUTHOR, dependencies=dependencies)
    ready = Project(folder).reopen()
    assert ready["dependencies_ready"] and ready["installed"] is False
    assert ready["runtime_loadable"] is False
    manifest = project["models"][0]["model_manifest_sha256"]
    (folder / "dependencies" / manifest).unlink()
    missing = Project(folder).reopen()
    assert missing["missing_dependencies"] == [manifest]
    assert not missing["dependencies_ready"]


def test_fork_gets_a_new_identity_folder_and_lineage(tmp_path):
    project, dependencies = sample()
    parent = tmp_path / "parent"
    create(parent, project, author=AUTHOR, dependencies=dependencies)
    child = tmp_path / "child"
    result = fork_project(parent, child, "project:my-fork", author=AUTHOR)
    assert result["message"] == "Started this project as a copy of another"
    forked = Project(child).at("HEAD")
    assert forked["project_id"] == "project:my-fork"
    assert forked["forked_from"] == {
        "project_id": "project:synthetic",
        "checkpoint_sha256": checkpoint_digest(project),
    }
    assert forked["source"] == project["source"]
    assert Project(child).reopen()["dependencies_ready"]
    assert commits(child) == 1 and commits(parent) == 1
    # The parent folder keeps its own project; a foreign project cannot be saved into it.
    with pytest.raises(Conflict, match="another project"):
        Project(parent, author=AUTHOR).save(forked)
    with pytest.raises(Conflict):
        fork_project(parent, child, "project:again", author=AUTHOR)


def test_assignment_and_record_words():
    project, _ = sample()
    bare = deepcopy(project)
    bare["models"], bare["decisions"] = [], []
    assert summarize(bare, project) == [
        "Changed the knight's model to synthetic-model",
        "Recorded 1 decision",
    ]
    more = deepcopy(project)
    for n in range(2, 5):
        record = deepcopy(project["decisions"][0])
        record.update(record_id=f"record:{n}", tick=n)
        more["decisions"].append(record)
    assert summarize(project, more) == ["Recorded 3 decisions"]
    assert summarize(project, project) == []


@pytest.mark.parametrize(
    "message",
    [
        "",
        "two\nlines",
        "Move the knight \u2014 east",
        "Move the knight Co-authored-by: someone",
        "x" * 121,
    ],
)
def test_commit_messages_are_one_plain_line(message):
    with pytest.raises(ProjectError):
        check_message(message)


def test_refuses_folders_that_are_not_their_own_project(tmp_path):
    project, _ = sample()
    with pytest.raises(ProjectError, match="no \\.git"):
        Project(tmp_path).save(project)
    folder = tmp_path / "project"
    create(folder, project, author=AUTHOR)
    with pytest.raises(Conflict, match="exists"):
        create(folder, project, author=AUTHOR)
    git(folder, "remote", "add", "origin", "https://example.invalid/never.git")
    with pytest.raises(ProjectError, match="remote"):
        Project(folder, author=AUTHOR).save(project)


def test_private_values_never_enter_a_project(tmp_path):
    project, _ = sample()
    # A home path, assembled so no home path is written into the repository itself.
    project["source"]["world_id"] = "/".join(("", "Users", "someone", "private", "world"))
    folder = tmp_path / "project"
    with pytest.raises(ProjectError):
        create(folder, project, author=AUTHOR)
    assert not folder.exists()
    project, _ = sample()
    project["dependencies"][0]["source_id"] = "token:ghp_" + "a" * 36
    with pytest.raises(ProjectError):
        create(folder, project, author=AUTHOR)
    assert not folder.exists()


def test_timeline_reads_pending_changes_and_checkpoints_newest_first(tmp_path):
    project, _ = sample()
    folder = tmp_path / "project"
    create(folder, project, author=AUTHOR)
    local = Project(folder, author=AUTHOR)
    moved = deepcopy(project)
    moved["things"][0]["transform"]["x_mm"] = 3000
    local.save(moved)
    turned = deepcopy(moved)
    turned["things"][0]["transform"]["yaw_microradians"] = 1570796
    (folder / "world-project.json").write_text(json.dumps(turned), encoding="utf-8")
    view = local.timeline()
    assert view["pending"] == ["Turned the knight 90°"]
    assert [c["summary"] for c in view["checkpoints"]] == [
        ["Moved the knight 3 m east"],
        START,
    ]
    assert view["more"] is False and view["head"] == view["checkpoints"][0]["commit"]
    assert local.timeline(limit=1)["more"] is True


def evidence_from(project, session_id="session:one", records=None):
    """Move a sample's decisions into a session evidence file; the checkpoint keeps none."""
    world = deepcopy(project)
    decisions = world.pop("decisions")
    world["decisions"] = []
    return world, {
        "profile": "exulanica.world-project-evidence/v1",
        "project_id": world["project_id"],
        "session_id": session_id,
        "source": world["source"],
        "models": world["models"],
        "decisions": decisions if records is None else records,
    }


def more_records(evidence, count):
    grown = deepcopy(evidence)
    for n in range(count):
        record = deepcopy(evidence["decisions"][0])
        record.update(record_id=f"record:more-{n}", tick=10 + n)
        grown["decisions"].append(record)
    return grown


def test_evidence_lives_beside_the_world_and_only_grows(tmp_path):
    project, _ = sample()
    world, evidence = evidence_from(project)
    folder = tmp_path / "project"
    first = create(folder, world, author=AUTHOR, evidence=[evidence])
    assert first["evidence"] == ["Recorded 1 decision"]
    assert (folder / "evidence" / "session-one.json").is_file()
    local = Project(folder, author=AUTHOR)
    grown = more_records(evidence, 3)
    saved = local.save(world, evidence=[grown])
    assert saved["summary"] == []  # The world did not change.
    assert saved["evidence"] == ["Recorded 3 more decisions"]
    assert saved["message"] == "Recorded 3 more decisions"
    assert local.save(world, evidence=[grown])["committed"] is False
    rewritten = deepcopy(grown)
    rewritten["decisions"][0]["reason_code"] = "edited_later"
    with pytest.raises(Conflict, match="append-only"):
        local.save(world, evidence=[rewritten])
    shrunk = deepcopy(grown)
    shrunk["decisions"].pop()
    with pytest.raises(Conflict, match="append-only"):
        local.save(world, evidence=[shrunk])
    view = local.timeline()
    assert view["checkpoints"][0]["evidence"] == saved["evidence"]
    assert view["checkpoints"][0]["summary"] == []
    assert [s["records"] for s in view["sessions"]] == [4]
    assert view["sessions"][0]["warning"] is None
    assert len(view["sessions"][0]["evidence_sha256"]) == 64


def test_an_assignment_no_saved_record_is_held_under_may_leave_a_session_file(tmp_path):
    # A thing given another model before it decided anything leaves its first assignment behind;
    # an assignment a saved record is held under never leaves.
    project, _ = sample()
    world, evidence = evidence_from(project)
    unused = {**evidence["models"][0], "thing_id": "knight:2", "revision": "unused-v1"}
    folder = tmp_path / "project"
    create(
        folder,
        world,
        author=AUTHOR,
        evidence=[{**evidence, "models": [*evidence["models"], unused]}],
    )
    local = Project(folder, author=AUTHOR)
    assert local.save(world, evidence=[more_records(evidence, 1)])["committed"]
    used = deepcopy(evidence)
    used["models"] = [unused]
    with pytest.raises(ProjectError):  # every saved record keeps its assignment in its file
        local.save(world, evidence=[used])


def test_reopen_labels_evidence_that_no_longer_fits(tmp_path):
    project, _ = sample()
    world, evidence = evidence_from(project)
    folder = tmp_path / "project"
    create(folder, world, author=AUTHOR, evidence=[evidence])
    local = Project(folder, author=AUTHOR)
    reassigned = deepcopy(world)
    reassigned["models"][0]["revision"] = "fixture-v2"
    reassigned["dependencies"] = [
        d for d in reassigned["dependencies"] if d["kind"] != "model-manifest"
    ] + [
        {
            "kind": "model-manifest",
            "sha256": "f" * 64,
            "licence": "synthetic-test-only",
            "source_id": "model-manifest",
        }
    ]
    reassigned["models"][0]["model_manifest_sha256"] = "f" * 64
    local.save(reassigned)
    sessions = local.reopen()["sessions"]
    assert [(s["session_id"], s["warning"]) for s in sessions] == [
        ("session:one", "made under model assignments no longer current")
    ]


def test_evidence_must_bind_inside_its_file_and_reads_honestly():
    from exulanica.world_package.projects.checkpoint import evidence_document

    project, _ = sample()
    _, evidence = evidence_from(project)
    unbound = deepcopy(evidence)
    unbound["decisions"][0]["binding_sha256"] = "d" * 64
    with pytest.raises(ProjectError):
        evidence_document(unbound)
    readable = deepcopy(evidence)
    readable["decisions"][0]["readable"] = {
        "situation": "You are a knight: a knight in plain armour.",
        "options": ["wait here a minute"],
        "choice": "rest by the well",
        "line": None,
        "status": "accepted",
        "reason": "validated_choice",
        "consumed_tick": 2,
        "disposition": "applied",
        "served_model_id": None,
        "cost_usd": None,
        "cost_known": False,
    }
    with pytest.raises(ProjectError):  # The choice was never offered.
        evidence_document(readable)
    readable["decisions"][0]["readable"]["choice"] = "wait here a minute"
    home_note = "see " + "/".join(("", "Users", "someone", "notes"))
    readable["decisions"][0]["readable"]["situation"] = home_note
    with pytest.raises(ProjectError):
        evidence_document(readable)


def test_project_commands_round_trip(tmp_path, capsys):
    from exulanica.world_package.projects.__main__ import main

    project, _ = sample()
    world, evidence = evidence_from(project)
    (tmp_path / "world.json").write_text(json.dumps(world), encoding="utf-8")
    (tmp_path / "evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
    folder = tmp_path / "project"
    who = ["--author-name", "Synthetic Student", "--author-email", "student@example.invalid"]
    assert main(["create", str(folder), "--from", str(tmp_path / "world.json"), *who]) == 0
    capsys.readouterr()
    moved = deepcopy(world)
    moved["things"][0]["transform"]["x_mm"] = 2000
    (tmp_path / "moved.json").write_text(json.dumps(moved), encoding="utf-8")
    arguments = [
        "--from",
        str(tmp_path / "moved.json"),
        "--evidence",
        str(tmp_path / "evidence.json"),
    ]
    assert main(["record", str(folder), *arguments, *who]) == 0
    recorded = json.loads(capsys.readouterr().out)
    assert recorded["summary"] == ["Moved the knight 2 m east"]
    assert recorded["evidence"] == ["Recorded 1 decision"]
    assert main(["changes", str(folder)]) == 0
    assert json.loads(capsys.readouterr().out)["summary"] == ["Moved the knight 2 m east"]
    assert main(["history", str(folder)]) == 0
    assert len(json.loads(capsys.readouterr().out)["checkpoints"]) == 2
    assert main(["reopen", str(folder)]) == 0
    assert json.loads(capsys.readouterr().out)["installed"] is False
    child = tmp_path / "fork"
    assert (
        main(["fork-project", str(folder), "--to", str(child), "--project-id", "project:f", *who])
        == 0
    )
    assert Project(child).at("HEAD")["forked_from"]["project_id"] == "project:synthetic"
    assert not (child / "evidence").exists()
    capsys.readouterr()
    assert main(["record", str(tmp_path / "nowhere")]) == 1
    assert "no .git" in capsys.readouterr().out


def test_a_session_keeps_its_first_capture_time():
    from exulanica.world_package.projects.repository import accumulate, session_file

    project, _ = sample()
    _, evidence = evidence_from(project)
    first = {**evidence, "captured_at": "2026-10-14T01:00:00Z"}
    [kept] = accumulate({}, first)
    later = {**more_records(evidence, 1), "captured_at": "2026-10-14T02:00:00Z"}
    [grown] = accumulate({session_file("session:one"): kept}, later)
    assert grown["captured_at"] == "2026-10-14T01:00:00Z"
    assert len(grown["decisions"]) == 2


def test_a_living_session_may_close_once_and_never_change_after():
    from exulanica.world_package.projects.repository import append_only, session_file

    from test_world_project_evidence_format import SESSION, living

    project, _ = sample()
    _, evidence = evidence_from(project)
    evidence["session_id"] = f"session:{SESSION}"
    name = session_file(evidence["session_id"])
    opened = {**evidence, "living_session": living(state="open")}
    grown = deepcopy(opened)
    grown["living_session"]["spending"]["used"]["calls"] = 500
    closed = {**evidence, "living_session": living(state="closed")}
    append_only({name: opened}, {name: grown})  # spending grows while open
    append_only({name: opened}, {name: closed})  # open becomes closed
    for later in (
        {**closed, "living_session": living(state="closed", reason="session_deadline")},
        {**evidence, "living_session": living(state="open")},
        evidence,
    ):
        with pytest.raises(Conflict, match="append-only"):
            append_only({name: closed}, {name: later})
    reopened = deepcopy(opened)
    reopened["living_session"]["opened"]["tick"] = 5
    with pytest.raises(Conflict, match="append-only"):
        append_only({name: opened}, {name: reopened})


@pytest.fixture
def no_git_identity(monkeypatch, tmp_path):
    """A machine with no git identity, as CI's is: git may not guess one either."""
    home = tmp_path / "empty-home"
    home.mkdir()
    (home / ".gitconfig").write_text("[user]\n\tuseConfigOnly = true\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    for name in ("EMAIL", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME"):
        monkeypatch.delenv(name, raising=False)
    return home


def test_every_project_commit_has_an_author_without_any_git_identity(no_git_identity, tmp_path):
    from exulanica.world_package.projects.history import record_application

    project, _ = sample()
    world, evidence = evidence_from(project)
    folder = tmp_path / "project"
    create(folder, world, evidence=[evidence])  # no author given anywhere below
    local = Project(folder)
    moved = deepcopy(world)
    moved["things"][0]["transform"]["x_mm"] = 1000
    assert local.save(moved)["committed"]
    assert local.link("learner/world", "main", "exulanica/world")["committed"]
    record = {
        "profile": "exulanica.world-project-application/v1",
        "repository": "learner/world",
        "pull_request": 1,
        "merge_commit": "a" * 40,
        "checkpoint_sha256": "b" * 64,
        "evidence_sha256": {},
        "version_id": "00000000-0000-0000-0000-00000000000a",
        "title": "From learner/world commit " + "a" * 40 + " (pull request #1)",
    }
    assert record_application(local, record)["committed"]
    fork_project(folder, tmp_path / "fork", "project:fork")
    from exulanica.world_package.projects.repository import DEFAULT_AUTHOR

    authors = git(folder, "log", "--format=%an <%ae>").split("\n")
    expected = f"{DEFAULT_AUTHOR.name} <{DEFAULT_AUTHOR.email}>"
    assert [a for a in authors if a] == [expected] * 4
    assert git(tmp_path / "fork", "log", "-1", "--format=%an <%ae>").strip() == expected


def test_a_stated_author_still_signs_and_the_person_s_git_config_is_never_read(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    home.mkdir()
    # A person's global configuration that would sign commits and name someone else.
    (home / ".gitconfig").write_text(
        "[user]\n\tname = Someone Else\n\temail = someone@example.invalid\n"
        "[commit]\n\tgpgsign = true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    project, _ = sample()
    folder = tmp_path / "project"
    create(folder, project, author=AUTHOR)
    assert git(folder, "log", "-1", "--format=%an").strip() == AUTHOR.name
    create(tmp_path / "default", project)
    assert git(tmp_path / "default", "log", "-1", "--format=%an").strip() != "Someone Else"


def test_a_kind_s_bytes_leave_the_folder_with_the_last_checkpoint_that_names_them(tmp_path):
    # A made creature whose kind was erased leaves the selection; its kind's bytes, its label
    # among them, leave the folder in the same commit. The project's history still holds them.
    from test_world_project_rights import made_kind, made_project

    local, project, sha = made_project(tmp_path / "project", made_kind("public"))
    kept = tmp_path / "project" / "dependencies" / sha
    assert kept.is_file()
    left = deepcopy(project)
    left["things"] = [t for t in left["things"] if t["thing_id"] != "creature:1"]
    left["dependencies"] = [d for d in left["dependencies"] if d["sha256"] != sha]
    saved = local.save(left)
    assert saved["committed"] and not kept.exists()
    assert local.git("ls-files", "--", f"dependencies/{sha}").strip() == ""
    assert local.git("status", "--porcelain").strip() == ""
    assert local.git("show", f"HEAD~1:dependencies/{sha}")
    # Bytes no checkpoint ever recorded are taken out without a record of them.
    stray = tmp_path / "project" / "dependencies" / ("b" * 64)
    stray.write_bytes(b"{}")
    moved = deepcopy(left)
    moved["things"][0]["transform"]["x_mm"] += 1_000
    assert local.save(moved)["committed"] and not stray.exists()
