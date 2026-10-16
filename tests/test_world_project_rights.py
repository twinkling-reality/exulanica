"""What reaches a repository: no written word unless it is private, things only where their origin
allows, in every file of every commit publication would send.

Strict fake GitHub servers and synthetic projects only; nothing is published anywhere.
"""

from copy import deepcopy

import pytest
from exulanica.canonical import canonical_json
from exulanica.world_package.projects.checkpoint import Conflict, digest
from exulanica.world_package.projects.github import (
    BranchTarget,
    GitHubProjects,
    RollingPullRequests,
    Target,
)
from exulanica.world_package.projects.repository import Author, Project, create

from test_world_project import sample
from test_world_project_github import Repository, Server, local_project, publish
from test_world_project_insight import session

TARGET = BranchTarget("learner/world", "main", "exulanica/world")
FILE_TARGET = Target("learner/world", "main")
AUTHOR = Author("Synthetic Student", "student@example.invalid")
#: Every written word the synthetic records below carry.
WORDS = ("You are a knight", "wait here a minute", "rest by the well", "Time to sit")
#: A written block for the sample checkpoint's own one-option record.
READABLE = {
    "situation": "You are a knight: a knight in plain armour.",
    "options": ["wait here a minute"],
    "choice": "wait here a minute",
    "line": "Time to sit.",
    "status": "accepted",
    "reason": "validated_choice",
    "consumed_tick": 2,
    "disposition": "applied",
    "served_model_id": "synthetic-model-rev-1",
    "cost_usd": "0.0001",
    "cost_known": True,
}


def received(remote):
    """Everything a fake repository holds: each file of each branch, each request's title and
    body."""
    texts = [
        data.decode() for branch in remote.branches.values() for data in branch["files"].values()
    ]
    texts += [f"{pr['title']}\n{pr['body']}" for pr in remote.pulls]
    return "\n".join(texts)


def labelled(folder, *, readable):
    """A project whose second session holds two decisions, with or without their words."""
    local, _, _ = local_project(folder)
    world, evidence = session(count=2, readable=readable)
    local.save(world, evidence=[{**evidence, "session_id": "session:labelled"}])
    return local


def remote(visibility):
    repository = Repository()
    repository.visibility = visibility
    return repository


@pytest.mark.parametrize("visibility", ["PUBLIC", "INTERNAL", None])
def test_a_repository_that_is_not_private_receives_no_written_word_in_any_file(
    tmp_path, visibility
):
    local = labelled(tmp_path, readable=True)
    repository = remote(visibility)  # None: GitHub stated no visibility, read as public
    client = RollingPullRequests(repository.request)
    with pytest.raises(Conflict, match="written words"):
        client.review(TARGET, local)
    with pytest.raises(Conflict, match="written words"):
        client.publish(TARGET, local, reviewed_sha256="0" * 64, allow_publication=True)
    assert repository.writes == []
    assert not any(word in received(repository) for word in WORDS)


def test_words_reach_a_private_repository_and_a_project_without_them_a_public_one(tmp_path):
    private = remote("PRIVATE")
    _, result = publish(
        RollingPullRequests(private.request), TARGET, labelled(tmp_path / "a", readable=True), None
    )
    assert result["published"] and "rest by the well" in received(private)
    public = remote("PUBLIC")
    review, result = publish(
        RollingPullRequests(public.request), TARGET, labelled(tmp_path / "b", readable=False), None
    )
    assert result["published"] and review["text"] == "codes"
    assert not any(word in received(public) for word in WORDS)
    assert "chose one of 2 choices" in public.pulls[0]["body"]


def test_an_earlier_checkpoint_s_words_are_refused_though_the_last_holds_none(tmp_path):
    project, _ = sample()
    worded = deepcopy(project)
    worded["decisions"][0]["readable"] = dict(READABLE)
    folder = tmp_path / "project"
    create(folder, worded, author=AUTHOR)
    local = Project(folder, author=AUTHOR)
    assert local.save(project)["committed"]  # the record keeps no words now
    repository = remote("PUBLIC")
    with pytest.raises(Conflict, match=r"world-project\.json carries written words"):
        RollingPullRequests(repository.request).review(TARGET, local)
    assert repository.writes == []


#: Words a world's owner wrote: the world's title, a character's name and its personality.
OWNER_WORDS = ("Terraces on the bay", "Puddle", "A worried yellow duck")


def written(project, *, words=True):
    """The sample checkpoint with its world's title and its knight's character: the words kept,
    or only the record's revision as a project without readable text keeps it."""
    character = {"thing_id": "knight:1", "revision": 2}
    if words:
        character["words"] = {"name": "Puddle", "about": "A worried yellow duck who loves water."}
        return {**project, "title": "Terraces on the bay", "characters": [character]}
    return {**project, "characters": [character]}


@pytest.mark.parametrize("visibility", ["PUBLIC", "INTERNAL", None])
def test_a_world_s_title_and_a_character_s_words_reach_only_a_private_repository(
    tmp_path, visibility
):
    project, _ = sample()
    create(tmp_path / "project", written(project), author=AUTHOR)
    local = Project(tmp_path / "project", author=AUTHOR)
    repository = remote(visibility)
    with pytest.raises(Conflict, match=r"world-project\.json carries written words"):
        RollingPullRequests(repository.request).review(TARGET, local)
    server = Server()
    server.visibility = visibility
    with pytest.raises(Conflict, match=r"world-project\.json carries written words"):
        GitHubProjects(server.request).review(FILE_TARGET, local.at("HEAD"), "Publish")
    assert repository.writes == [] and server.writes == []
    assert not any(word in received(repository) for word in OWNER_WORDS)


def test_a_character_kept_without_its_words_reaches_a_public_repository_unnamed(tmp_path):
    project, _ = sample()
    create(tmp_path / "a", written(project, words=False), author=AUTHOR)
    public = remote("PUBLIC")
    _, result = publish(
        RollingPullRequests(public.request), TARGET, Project(tmp_path / "a", author=AUTHOR), None
    )
    assert result["published"]
    assert "- Wrote the knight's personality\n" in public.pulls[0]["body"]
    assert public.pulls[0]["title"] == "Changes to this world"
    create(tmp_path / "b", written(project), author=AUTHOR)
    private = remote("PRIVATE")
    _, result = publish(
        RollingPullRequests(private.request), TARGET, Project(tmp_path / "b", author=AUTHOR), None
    )
    assert result["published"] and private.pulls[0]["title"] == "Changes to Terraces on the bay"
    assert all(word in received(private) for word in OWNER_WORDS)


# Things, by their origin record


def made_kind(distribution, *, klass="drafted"):
    """A made kind's bytes as a project keeps them, its origin saying where it may be shown."""
    by = (
        {"kind": "account", "account_id": "00000000-0000-4000-8000-000000000001"}
        if klass == "uploaded"
        else {
            "kind": "model",
            "provider": "synthetic",
            "model_id": "synthetic-drafter",
            "prompt_version": "synthetic-1",
            "prompt_sha256": None,
            "words_sha256": None,
            "execution_sha256": None,
        }
    )
    origin = {
        "profile": "exulanica.origin/v1",
        "class": klass,
        "by": by,
        "sources": [],
        "licence": {
            "spdx": "Apache-2.0",
            "verdict": "SHIP",
            "attribution": None,
            "share_alike": False,
            "licence_url": None,
            "licence_text_sha256": None,
        },
        "authors": [],
        "lineage": {"ingredients": [], "receipts": [], "translation_manifest_sha256": None},
        "distribution": distribution,
    }
    return canonical_json(
        {"profile": "exulanica.thing-kind/v1", "kind": "made_creature", "origin": origin}
    )


def made_project(folder, data):
    """The sample world with one more placed thing, of a kind made in its workspace."""
    project, _ = sample()
    sha = digest(data)
    creature = deepcopy(project["things"][0])
    creature.update(thing_id="creature:1", kind={"source": "workspace", "sha256": sha})
    project["things"].append(creature)
    project["dependencies"].append(
        {
            "kind": "thing-kind",
            "sha256": sha,
            "licence": "synthetic-test-only",
            "source_id": "workspace-kind:synthetic",
        }
    )
    create(folder, project, author=AUTHOR, dependencies={sha: data})
    return Project(folder, author=AUTHOR), project, sha


@pytest.mark.parametrize(
    ("distribution", "public"), [("public", True), ("private", False), ("restricted", False)]
)
def test_a_made_thing_reaches_a_repository_only_where_its_origin_allows(
    tmp_path, distribution, public
):
    local, _, _ = made_project(tmp_path / "project", made_kind(distribution))
    assert RollingPullRequests(remote("PRIVATE").request).review(TARGET, local)["actions"]
    client = RollingPullRequests(remote("PUBLIC").request)
    if public:
        assert client.review(TARGET, local)["actions"]
    else:
        with pytest.raises(Conflict, match=f"keeps it {distribution}"):
            client.review(TARGET, local)


def test_a_made_thing_whose_rights_cannot_be_read_is_refused_anywhere(tmp_path):
    # An upload that claims to be public is no origin record the reader accepts.
    forged, _, _ = made_project(tmp_path / "forged", made_kind("public", klass="uploaded"))
    missing, _, sha = made_project(tmp_path / "missing", made_kind("public"))
    (missing.folder / "dependencies" / sha).unlink()
    for local in (forged, missing):
        for visibility in ("PRIVATE", "PUBLIC"):
            repository = remote(visibility)
            with pytest.raises(Conflict, match="rights cannot be read"):
                RollingPullRequests(repository.request).review(TARGET, local)
            assert repository.writes == []


def test_the_single_file_transport_holds_the_same_rules(tmp_path):
    project, _ = sample()
    worded = deepcopy(project)
    worded["decisions"][0]["readable"] = dict(READABLE)
    _, made, _ = made_project(tmp_path / "made", made_kind("public"))
    server = Server()
    server.visibility = "PUBLIC"
    client = GitHubProjects(server.request)
    with pytest.raises(Conflict, match="written words"):
        client.review(FILE_TARGET, worded, "Add the world")
    # A single file carries no made kind's bytes, so its rights cannot be read there.
    with pytest.raises(Conflict, match="rights cannot be read"):
        client.review(FILE_TARGET, made, "Add the world")
    assert client.review(FILE_TARGET, project, "Add the world")["checkpoint_sha256"]
    server.visibility = "PRIVATE"
    assert client.review(FILE_TARGET, worded, "Add the world")["checkpoint_sha256"]
    assert server.writes == []


def test_a_made_part_s_label_reaches_only_a_private_repository(tmp_path):
    project, _ = sample()
    labelled = {
        "part_id": "0190a1b2-c3d4-4e5f-8a9b-000000000001",
        "kind": "fixture",
        "centre_mm": [3_000, 4_000],
        "quarter_turns": 0,
        "removed": False,
        "label": "Puddle's pond",
    }
    create(tmp_path / "labelled", {**project, "parts": [labelled]}, author=AUTHOR)
    repository = remote("PUBLIC")
    with pytest.raises(Conflict, match="made part's label"):
        RollingPullRequests(repository.request).review(
            TARGET, Project(tmp_path / "labelled", author=AUTHOR)
        )
    bare = {key: value for key, value in labelled.items() if key != "label"}
    create(tmp_path / "bare", {**project, "parts": [bare]}, author=AUTHOR)
    _, result = publish(
        RollingPullRequests(repository.request),
        TARGET,
        Project(tmp_path / "bare", author=AUTHOR),
        None,
    )
    assert result["published"] and "Puddle" not in received(repository)


def test_a_made_creature_s_label_reaches_only_a_private_repository(tmp_path):
    # A made creature is called by its kind's label, its maker's words (J20): written words.
    local, project, _ = made_project(tmp_path / "made", made_kind("public"))
    labelled = deepcopy(project)
    creature = next(t for t in labelled["things"] if t["thing_id"] == "creature:1")
    creature["label"] = "Long necked marsh heron"
    creature["transform"]["x_mm"] += 2_000
    local.save(labelled)
    public = remote("PUBLIC")
    with pytest.raises(Conflict, match="made creature's kind's label"):
        RollingPullRequests(public.request).review(TARGET, local)
    assert public.writes == []
    private = remote("PRIVATE")
    _, result = publish(RollingPullRequests(private.request), TARGET, local, None)
    assert result["published"] and "Long necked marsh heron" in received(private)


#: A town's baker, who is no placed thing, decided for by the sample's model.
BAKER = "0190a1b2-c3d4-7e5f-8a9b-00000000b001"


def with_baker(project, *, name=None):
    resident = {"resident_id": BAKER, "role": "baker"}
    if name is not None:
        resident["name"] = name
    models = [*project["models"], {**project["models"][0], "thing_id": BAKER}]
    return {**project, "models": models, "residents": [resident]}


@pytest.mark.parametrize("visibility", ["PUBLIC", "INTERNAL", None])
def test_a_resident_s_name_reaches_only_a_private_repository(tmp_path, visibility):
    project, _ = sample()
    create(tmp_path / "named", with_baker(project, name="Odile Fenn"), author=AUTHOR)
    named = Project(tmp_path / "named", author=AUTHOR)
    repository = remote(visibility)
    with pytest.raises(Conflict, match="a resident's name"):
        RollingPullRequests(repository.request).review(TARGET, named)
    assert repository.writes == [] and "Odile" not in received(repository)
    private = remote("PRIVATE")
    _, result = publish(RollingPullRequests(private.request), TARGET, named, None)
    assert result["published"] and "Odile Fenn" in received(private)
    # Kept without its name, the resident reaches any repository, called by its role.
    create(tmp_path / "bare", with_baker(project), author=AUTHOR)
    public = remote("PUBLIC")
    _, result = publish(
        RollingPullRequests(public.request), TARGET, Project(tmp_path / "bare", author=AUTHOR), None
    )
    assert result["published"] and "Odile" not in received(public)
    assert "the baker's model" in public.pulls[0]["body"]
