"""The history read offline: a local project folder, and a strict fake GitHub when publication is
read. Synthetic content only."""

import json
from copy import deepcopy

import pytest
from exulanica.world_package.projects.checkpoint import (
    ProjectError,
    checkpoint_digest,
    evidence_digest,
)
from exulanica.world_package.projects.github import BranchTarget, read_publication
from exulanica.world_package.projects.history import (
    PROFILE,
    application_document,
    history_read,
    record_application,
)
from exulanica.world_package.projects.repository import Author, Project, create

from test_world_project_apply import fields_used
from test_world_project_repository import evidence_from, more_records

AUTHOR = Author("Synthetic Student", "student@example.invalid")
TARGET = BranchTarget("learner/world", "main", "exulanica/world")

#: Fields the publication read names, each confirmed against GitHub's schema by introspection on
#: 13 October 2026 (Repository.ref(qualifiedName:), Ref target/name, Repository.pullRequests with
#: headRefName and last, PullRequest number/url/state/merged/baseRefName/mergeCommit).
PUBLICATION_FIELDS = {
    "repository",
    "nameWithOwner",
    "ref",
    "name",
    "target",
    "oid",
    "file",
    "mode",
    "object",
    "text",
    "byteSize",
    "isTruncated",
    "entries",
    "pullRequests",
    "nodes",
    "number",
    "url",
    "state",
    "merged",
    "baseRefName",
    "mergeCommit",
}


def project_with_history(tmp_path):
    """Start, a move with a session's evidence, more evidence, then a link: four commits."""
    from test_world_project import sample

    project, _ = sample()
    world, evidence = evidence_from(project)
    folder = tmp_path / "project"
    create(folder, world, author=AUTHOR, evidence=[evidence])
    local = Project(folder, author=AUTHOR)
    moved = deepcopy(world)
    moved["things"][0]["transform"]["x_mm"] = 2000
    local.save(moved)
    local.save(moved, evidence=[more_records(evidence, 2)])
    local.link("learner/world", "main", "exulanica/world")
    return local, world, moved


def application(local, revision, number=1, version="00000000-0000-0000-0000-00000000000a"):
    return {
        "profile": "exulanica.world-project-application/v1",
        "repository": "learner/world",
        "pull_request": number,
        "merge_commit": f"{number:040x}",
        "checkpoint_sha256": checkpoint_digest(local.at(revision)),
        "evidence_sha256": {
            name: evidence_digest(s) for name, s in sorted(local.sessions_at(revision).items())
        },
        "version_id": version,
        "title": f"From learner/world commit {number:040x} (pull request #{number})",
    }


def test_local_history_is_exact_and_names_what_each_checkpoint_changed(tmp_path):
    local, _, _ = project_with_history(tmp_path)
    record = application(local, "HEAD~1")
    assert record_application(local, record)["committed"]
    assert record_application(local, record) == {"committed": False, "reason": "unchanged"}
    view = history_read(local)
    assert view["profile"] == PROFILE and view["link"]["branch"] == "exulanica/world"
    assert [c["kind"] for c in view["checkpoints"]] == [
        "application",
        "link",
        "checkpoint",
        "checkpoint",
        "checkpoint",
    ]
    by_message = {c["message"]: c for c in view["checkpoints"]}
    moved = by_message["Moved the knight 2 m east"]
    assert moved["world_changes"] == ["Moved the knight 2 m east"]
    assert moved["evidence_changes"] == []
    grown = by_message["Recorded 2 more decisions"]
    assert grown["world_changes"] == []
    assert [(s["records"], s["records_added"]) for s in grown["sessions"]] == [(3, 2)]
    # The application belongs to the newest content checkpoint holding exactly its content.
    assert [c["message"] for c in view["checkpoints"] if c["applied_as"]] == [grown["message"]]
    assert grown["applied_as"][0]["version_id"] == record["version_id"]
    assert view["applications"]["source"] == "this folder's records"
    assert view["applications"]["not_listed"] == []
    assert view["publication"] == {"state": "not read"}
    assert all(c["published"] is None for c in view["checkpoints"])
    assert view["pending"] == {"world": [], "evidence": []}
    short = history_read(local, limit=2)
    assert short["more"] is True and len(short["checkpoints"]) == 2
    assert short["applications"]["not_listed"] == [record["merge_commit"]]


class Branch:
    """A strict fake GitHub answering the publication read from given branch files."""

    def __init__(self, files, requests=()):
        self.files, self.requests = files, list(requests)

    def request(self, query, variables, **_):
        unknown = fields_used(query) - PUBLICATION_FIELDS
        assert not unknown, f"GitHub declares no field {sorted(unknown)}"
        assert variables["ref"] == "refs/heads/exulanica/world"

        def blob(data):
            text = data.decode()
            return {
                "mode": 0o100644,
                "object": {"text": text, "byteSize": len(data), "isTruncated": False},
            }

        evidence = sorted(p for p in self.files if p.startswith("evidence/"))
        return {
            "repository": {
                "nameWithOwner": "learner/world",
                "ref": {
                    "name": "exulanica/world",
                    "target": {
                        "oid": "b" * 40,
                        "file": blob(self.files["world-project.json"]),
                        "evidence": {
                            "mode": 0o040000,
                            "object": {
                                "entries": [
                                    {"name": p.removeprefix("evidence/"), **blob(self.files[p])}
                                    for p in evidence
                                ]
                            },
                        },
                    },
                }
                if self.files
                else None,
                "pullRequests": {"nodes": self.requests},
            }
        }


def test_publication_marks_what_the_branch_holds_and_the_pull_request(tmp_path):
    local, _, _ = project_with_history(tmp_path)
    first_two = local.history()[-2]["commit"]  # "Moved the knight", the second commit.
    pull = {
        "number": 3,
        "url": "https://example.invalid/pull/3",
        "state": "OPEN",
        "merged": False,
        "baseRefName": "main",
        "mergeCommit": None,
    }
    other_base = {**pull, "number": 9, "baseRefName": "develop"}
    remote = Branch(local.published_files(first_two), [pull, other_base])
    view = history_read(local, publication=read_publication(TARGET, remote.request))
    assert view["publication"]["published_through"] == first_two
    assert view["publication"]["matches_local_history"] is True
    assert view["publication"]["pull_request"]["number"] == 3
    assert [c["published"] for c in view["checkpoints"]] == [False, False, True, True]

    # A branch someone else changed matches nothing local: nothing is marked published.
    changed = local.published_files(first_two)
    changed["world-project.json"] = changed["world-project.json"].replace(b"2000", b"2500")
    view = history_read(local, publication=read_publication(TARGET, Branch(changed).request))
    assert view["publication"]["matches_local_history"] is False
    assert view["publication"]["published_through"] is None
    assert not any(c["published"] for c in view["checkpoints"])

    # No branch yet: nothing published, and the read says so exactly.
    view = history_read(local, publication=read_publication(TARGET, Branch({}).request))
    assert view["publication"]["branch_head"] is None
    assert view["publication"]["published_through"] is None
    assert view["publication"]["matches_local_history"] is True


def test_pending_changes_and_closed_application_records(tmp_path):
    local, _, moved = project_with_history(tmp_path)
    turned = deepcopy(moved)
    turned["things"][0]["transform"]["yaw_microradians"] = 1570796
    (local.folder / "world-project.json").write_text(json.dumps(turned), encoding="utf-8")
    assert history_read(local)["pending"]["world"] == ["Turned the knight 90°"]
    record = application(local, "HEAD")
    for broken in (
        {**record, "token": "x"},
        {**record, "merge_commit": "c" * 39},
        {**record, "version_id": "/Users/someone/version"},
    ):
        with pytest.raises(ProjectError):
            application_document(broken)


def test_the_history_command_reads_locally_unless_publication_is_asked(tmp_path, capsys):
    from exulanica.world_package.projects.__main__ import main

    local, _, _ = project_with_history(tmp_path)
    assert main(["history", str(local.folder), "--limit", "3"]) == 0
    view = json.loads(capsys.readouterr().out)
    assert view["profile"] == PROFILE and view["more"] is True
    assert view["publication"] == {"state": "not read"}


def test_the_apply_command_records_which_version_a_merge_became(tmp_path, monkeypatch, capsys):
    import httpx
    from exulanica.world_package.projects import __main__ as cli
    from exulanica.world_package.projects import github
    from exulanica.world_package.projects.capture import WorldReader

    from test_world_project_apply import GitHub, World, edited

    world = World()
    project = edited(world)
    folder = tmp_path / "project"
    create(folder, project, author=AUTHOR)
    local = Project(folder, author=AUTHOR)
    local.link("learner/world", "main", "exulanica/world")
    monkeypatch.setattr(github, "gh_graphql", GitHub(project).request)
    monkeypatch.setattr(
        cli,
        "WorldReader",
        lambda api, token, world_id: WorldReader(
            api, token, world_id, transport=httpx.MockTransport(world.handle)
        ),
    )
    token = tmp_path / "token"
    token.write_text("synthetic-bearer")
    common = [str(folder), "--pull-request", "7", "--api", "http://localhost:20070"]
    common += ["--token-file", str(token)]
    assert cli.main(["review-apply", *common]) == 0
    digest = json.loads(capsys.readouterr().out)["review_sha256"]
    assert cli.main(["apply", *common, "--review-sha256", digest, "--allow-world-write"]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["applied"] and applied["recorded"]["committed"]
    view = history_read(local)
    assert view["checkpoints"][0]["kind"] == "application"
    [start] = [c for c in view["checkpoints"] if c["applied_as"]]
    assert start["message"] == "Started the project"
    assert start["applied_as"][0]["version_id"] == applied["version_id"]
    # Applying again finds the version already applied and records nothing new.
    assert cli.main(["review-apply", *common]) == 0
    digest = json.loads(capsys.readouterr().out)["review_sha256"]
    assert cli.main(["apply", *common, "--review-sha256", digest, "--allow-world-write"]) == 0
    assert json.loads(capsys.readouterr().out)["recorded"] == {
        "committed": False,
        "reason": "unchanged",
    }
