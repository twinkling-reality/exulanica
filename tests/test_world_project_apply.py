"""Apply-back offline: a strict fake GitHub for the merged pull request, a fake World API.

The fake World API holds each write to its route's body fields and to the state token, the way
`exulanica/api/routes/world_things.py` and `world_versions.py` do. Synthetic content only.
"""

import json
import re
from copy import deepcopy

import httpx
import pytest
from exulanica.canonical import canonical_json
from exulanica.world.objects import ObjectOrigin, Transform
from exulanica.world.placed_things import PlacedThing, named_kind, placed_thing_document
from exulanica.world_package.projects.apply import apply, review, title_for
from exulanica.world_package.projects.capture import WorldReader
from exulanica.world_package.projects.checkpoint import Conflict, ProjectError, digest, pretty
from exulanica.world_package.projects.github import read_merged

from test_world_project import sample

WORLD = "world:synthetic"
SOURCE = "00000000-0000-0000-0000-000000000001"

#: Query fields GitHub's schema declares, confirmed by introspection on 13 October 2026, for the
#: types the merged pull request read touches. The fake refuses a query naming any other field.
QUERY_FIELDS = {
    "repository",
    "nameWithOwner",
    "pullRequest",
    "number",
    "state",
    "merged",
    "mergedAt",
    "baseRefName",
    "headRefName",
    "mergeCommit",
    "oid",
    "file",
    "tree",
    "name",
    "path",
    "type",
    "object",
    "mode",
    "entries",
    "text",
    "byteSize",
    "isTruncated",
}


def fields_used(query):
    body = query[query.index("{") :]
    body = re.sub(r"\([^)]*\)", "", body)  # arguments
    body = re.sub(r"\b\w+\s*:", "", body)  # aliases
    body = re.sub(r"\.\.\.\s*on\s+\w+", "", body)  # inline fragments
    return set(re.findall(r"[A-Za-z_]\w*", body))


def thing(thing_id, kind, x_mm=0, region="region:one", removed=False):
    return placed_thing_document(
        PlacedThing(
            thing_id,
            named_kind(kind, 2),
            region,
            Transform(x_mm, 0, 0, 0, 1000),
            ObjectOrigin("authored", "fictional"),
            removed,
        )
    )


class World:
    """A fake World API: versions of placed things, written only through checked bodies."""

    def __init__(self):
        self.versions = {}
        self.writes = []
        self.refuse_next = None
        self.kinds = set()
        self.add(SOURCE, "Garden", [thing("knight:1", "knight"), thing("bench:1", "bench", 3000)])

    def add(self, version_id, title, things):
        self.versions[version_id] = {
            "version_id": version_id,
            "world_id": WORLD,
            "title": title,
            "source_snapshot_id": "snapshot",
            "source_invalidated": False,
            "things": things,
        }
        self.restate(version_id)

    def restate(self, version_id):
        version = self.versions[version_id]
        version["state_sha256"] = digest(canonical_json(version["things"]))

    def handle(self, request):
        path = request.url.path
        assert path.startswith("/things/") or request.url.params["world_id"] == WORLD
        if request.method == "GET":
            if path.startswith("/things/kinds/"):
                held = path.rsplit("/", 1)[1] in self.kinds
                return httpx.Response(200 if held else 404, json={"code": "unknown_reference"})
            if path == "/world/versions":
                return httpx.Response(200, json=list(self.versions.values()))
            return httpx.Response(200, json=self.versions[path.rsplit("/", 1)[1]])
        body = json.loads(request.content)
        self.writes.append((path, body))
        if self.refuse_next and self.refuse_next in path:
            self.refuse_next = None
            return httpx.Response(503, json={"code": "kind_work_pending"})
        if path == "/world/versions":
            assert set(body) == {"title", "parent_version_id"}
            new = f"00000000-0000-0000-0000-{len(self.versions) + 1:012d}"
            self.add(
                new, body["title"], deepcopy(self.versions[body["parent_version_id"]]["things"])
            )
            return httpx.Response(201, json=self.versions[new])
        match = re.fullmatch(r"/world/versions/([^/]+)/things(?:/([^/]+)/(move|remove))?", path)
        version = self.versions[match.group(1)]
        if body["base_state_sha256"] != version["state_sha256"]:
            return httpx.Response(409, json={"code": "stale_object_base"})
        held = {t["thing_id"]: t for t in version["things"]}
        if match.group(3) is None:
            assert set(body) == {
                "base_state_sha256",
                "thing_id",
                "kind",
                "region_id",
                "pose",
                "origin_role",
            }
            assert set(body["pose"]) == {"x_mm", "y_mm", "z_mm", "yaw_microradians"}
            if body["thing_id"] in held:
                return httpx.Response(409, json={"code": "thing_exists"})
            pose = body["pose"]
            version["things"].append(
                {
                    "thing_id": body["thing_id"],
                    "kind": body["kind"],
                    "region_id": body["region_id"],
                    "transform": {
                        "coordinate_space": "region_local",
                        "coordinate_unit": "millimetre",
                        **pose,
                        "scale_milli": 1000,
                    },
                    "origin": {"kind": "authored", "role": body["origin_role"]},
                    "removed": False,
                }
            )
        elif match.group(3) == "move":
            assert set(body) == {"base_state_sha256", "pose"}
            held[match.group(2)]["transform"].update(body["pose"])
        else:
            assert set(body) == {"base_state_sha256"}
            held[match.group(2)]["removed"] = True
        self.restate(version["version_id"])
        return httpx.Response(200, json=version)


def checkpoint(world, things):
    project, _ = sample()
    project["source"].update(
        world_id=WORLD, version_id=SOURCE, state_sha256=world.versions[SOURCE]["state_sha256"]
    )
    project["region_ids"] = sorted({t["region_id"] for t in things})
    project["things"] = things
    for kind in ("bench", "lamp_post"):
        sha = named_kind(kind, 2).sha256
        if all(d["sha256"] != sha for d in project["dependencies"]):
            project["dependencies"].append(
                {"kind": "thing-kind", "sha256": sha, "licence": "synthetic", "source_id": kind}
            )
    project["decisions"] = []
    return project


class GitHub:
    """A strict fake: the merged pull request read, held to GitHub's declared query fields."""

    def __init__(self, project, *, merged=True, base="main", number=7):
        self.project, self.merged, self.base, self.number = project, merged, base, number

    def request(self, query, variables, **_):
        unknown = fields_used(query) - QUERY_FIELDS
        assert not unknown, f"GitHub declares no field {sorted(unknown)}"
        data = pretty(self.project)
        return {
            "repository": {
                "nameWithOwner": "learner/world",
                "pullRequest": {
                    "number": variables["number"],
                    "state": "MERGED" if self.merged else "OPEN",
                    "merged": self.merged,
                    "mergedAt": "2026-10-13T20:00:00Z" if self.merged else None,
                    "baseRefName": self.base,
                    "headRefName": "exulanica/world",
                    "mergeCommit": {
                        "oid": "c" * 40,
                        "file": {
                            "mode": 0o100644,
                            "object": {
                                "text": data.decode(),
                                "byteSize": len(data),
                                "isTruncated": False,
                            },
                        },
                        "evidence": None,
                    }
                    if self.merged
                    else None,
                },
            }
        }


def reader(world):
    return WorldReader(
        "http://localhost:20070",
        "synthetic-bearer",
        WORLD,
        transport=httpx.MockTransport(world.handle),
    )


def edited(world):
    """The project after a merge: the knight moved 2 m east, the bench removed, a lamp added."""
    return checkpoint(
        world,
        [
            thing("knight:1", "knight", 2000),
            thing("bench:1", "bench", 3000, removed=True),
            thing("lamp:1", "lamp_post", -1000),
        ],
    )


def test_a_merge_becomes_a_new_version_and_the_source_is_untouched():
    world = World()
    merged = read_merged("learner/world", 7, GitHub(edited(world)).request)
    before = deepcopy(world.versions[SOURCE])
    with reader(world) as client:
        planned = review(client, merged, "main")
        assert planned["mode"] == "branch"
        assert planned["changes"] == [
            "remove the bench",
            "move the knight 2 m east",
            "add the lamp post",
        ]
        assert planned["not_applied"]["model_assignments"] == [
            "change the knight's model to synthetic-model after the world is started"
        ]
        assert world.writes == []
        with pytest.raises(ProjectError, match="authorization"):
            apply(client, merged, "main", reviewed_sha256=planned["review_sha256"])
        assert world.writes == []
        result = apply(
            client,
            merged,
            "main",
            reviewed_sha256=planned["review_sha256"],
            allow_world_write=True,
        )
        assert result["applied"] and result["title"] == title_for(merged)
        new = world.versions[result["version_id"]]
        assert new["title"] == f"From learner/world commit {'c' * 40} (pull request #7)"
        held = {t["thing_id"]: t for t in new["things"]}
        assert held["knight:1"]["transform"]["x_mm"] == 2000
        assert held["bench:1"]["removed"] is True
        assert held["lamp:1"]["kind"]["kind"] == "lamp_post"
        assert world.versions[SOURCE] == before
        again = review(client, merged, "main")
        assert again["mode"] == "already applied" and again["changes"] == []
        writes = len(world.writes)
        assert apply(
            client, merged, "main", reviewed_sha256=again["review_sha256"], allow_world_write=True
        ) == {"applied": False, "mode": "already applied", "refused": []}
        assert len(world.writes) == writes


def test_a_merged_personality_and_model_are_reported_and_never_applied():
    # Who a character is reaches its model's input: a merge never writes it, or a model.
    world = World()
    project = edited(world)
    project["characters"] = [
        {
            "thing_id": "knight:1",
            "revision": 3,
            "words": {"name": "Sir Pip", "about": "Guards the well at night."},
        }
    ]
    merged = read_merged("learner/world", 7, GitHub(project).request)
    with reader(world) as client:
        planned = review(client, merged, "main")
        assert planned["not_applied"]["personalities"] == [
            "write Sir Pip's personality in the world"
        ]
        assert planned["not_applied"]["model_assignments"] == [
            "change Sir Pip's model to synthetic-model after the world is started"
        ]
        assert planned["changes"] == [
            "remove the bench",
            "move Sir Pip 2 m east",
            "add the lamp post",
        ]
        apply(
            client,
            merged,
            "main",
            reviewed_sha256=planned["review_sha256"],
            allow_world_write=True,
        )
    # Only the version and its placed things are written: no character and no model route.
    version = world.writes[1][0].split("/")[3]
    assert [path for path, _ in world.writes] == [
        "/world/versions",
        f"/world/versions/{version}/things/bench:1/remove",
        f"/world/versions/{version}/things/knight:1/move",
        f"/world/versions/{version}/things",
    ]
    assert "Guards the well" not in repr(world.writes)


def test_an_interrupted_apply_resumes_on_the_version_its_title_names():
    world = World()
    merged = read_merged("learner/world", 7, GitHub(edited(world)).request)
    with reader(world) as client:
        planned = review(client, merged, "main")
        world.refuse_next = "/move"
        with pytest.raises(ProjectError, match="apply stopped after"):
            apply(
                client,
                merged,
                "main",
                reviewed_sha256=planned["review_sha256"],
                allow_world_write=True,
            )
        resumed = review(client, merged, "main")
        assert resumed["mode"] == "resume"
        assert resumed["changes"] == ["move the knight 2 m east", "add the lamp post"]
        result = apply(
            client, merged, "main", reviewed_sha256=resumed["review_sha256"], allow_world_write=True
        )
        assert result["steps"] == ["move knight:1", "add lamp:1"]
        assert sum(1 for path, _ in world.writes if path == "/world/versions") == 1


def test_an_evidence_only_merge_makes_no_version():
    world = World()
    unchanged = checkpoint(world, deepcopy(world.versions[SOURCE]["things"]))
    merged = read_merged("learner/world", 7, GitHub(unchanged).request)
    with reader(world) as client:
        planned = review(client, merged, "main")
        assert planned["mode"] == "nothing to apply"
        assert (
            apply(
                client,
                merged,
                "main",
                reviewed_sha256=planned["review_sha256"],
                allow_world_write=True,
            )["applied"]
            is False
        )
    assert world.writes == []


def test_drift_unsupported_changes_and_unmerged_requests_are_refused():
    world = World()
    project = edited(world)
    merged = read_merged("learner/world", 7, GitHub(project).request)
    with reader(world) as client:
        world.versions[SOURCE]["things"][0]["transform"]["x_mm"] = 50
        world.restate(SOURCE)
        with pytest.raises(Conflict, match="changed since this project was captured"):
            review(client, merged, "main")
        with pytest.raises(Conflict, match="another branch"):
            review(client, merged, "develop")
    world = World()
    for change in (
        lambda t: t[0].update(region_id="region:two"),
        lambda t: t[0].update(kind=named_kind("traveller", 2).document()),
    ):
        things = deepcopy(world.versions[SOURCE]["things"])
        change(things)
        project = checkpoint(world, things)
        if things[0]["kind"]["kind"] == "traveller":
            project["models"] = []
            project["dependencies"].append(
                {
                    "kind": "thing-kind",
                    "sha256": named_kind("traveller", 2).sha256,
                    "licence": "synthetic",
                    "source_id": "traveller",
                }
            )
        merged = read_merged("learner/world", 7, GitHub(project).request)
        with reader(world) as client:
            planned = review(client, merged, "main")
            assert planned["mode"] == "refused" and planned["refused"]
            apply(
                client,
                merged,
                "main",
                reviewed_sha256=planned["review_sha256"],
                allow_world_write=True,
            )
    assert world.writes == []
    with pytest.raises(ProjectError, match="not merged"):
        read_merged("learner/world", 7, GitHub(project, merged=False).request)


def test_the_strict_fake_refuses_a_field_github_does_not_declare():
    with pytest.raises(AssertionError, match="declares no field"):
        GitHub(sample()[0]).request("query { repository { pullRequest { isMerged } } }", {})


def test_the_apply_command_refuses_before_any_request(tmp_path, monkeypatch, capsys):
    import subprocess

    from exulanica.world_package.projects.__main__ import main

    def no_network(*args, **kwargs):
        raise AssertionError("nothing may be contacted")

    monkeypatch.setattr(subprocess, "run", no_network)
    token = tmp_path / "token"
    token.write_text("synthetic-bearer")
    arguments = ["apply", str(tmp_path), "--pull-request", "7", "--api", "http://localhost:20070"]
    arguments += ["--token-file", str(token), "--review-sha256", "0" * 64]
    assert main(arguments) == 1
    assert "authorization" in capsys.readouterr().out


def test_a_kind_this_workspace_does_not_hold_is_refused_before_any_write():
    world = World()
    things = deepcopy(world.versions[SOURCE]["things"])
    things.append({**thing("made:1", "bench"), "kind": {"source": "workspace", "sha256": "e" * 64}})
    project = checkpoint(world, things)
    project["dependencies"].append(
        {"kind": "thing-kind", "sha256": "e" * 64, "licence": "synthetic", "source_id": "made"}
    )
    merged = read_merged("learner/world", 7, GitHub(project).request)
    with reader(world) as client:
        planned = review(client, merged, "main")
        assert planned["mode"] == "refused"
        assert planned["refused"] == [
            "the creature made in this world: this workspace holds no such kind"
        ]
        world.kinds.add("e" * 64)
        assert review(client, merged, "main")["changes"] == ["add the creature made in this world"]
    assert world.writes == []
