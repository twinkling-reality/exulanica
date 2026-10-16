"""The words a world's project says to a person, and nothing internal in what a pull request
shows: synthetic projects and a strict fake repository only; nothing is published anywhere."""

import re
from copy import deepcopy

import pytest
from exulanica.canonical import canonical_json
from exulanica.world.society_sessions import SESSION_CLOSED_WORDS, UNWORDED_CLOSE
from exulanica.world_package.projects.checkpoint import checkpoint_digest, digest, document
from exulanica.world_package.projects.github import BranchTarget, RollingPullRequests
from exulanica.world_package.projects.repository import Author, Project, create
from exulanica.world_package.projects.summary import run_numbers, subject, summarize
from exulanica.world_package.projects.words import model_name, money, names, seconds

from test_world_project import sample
from test_world_project_github import Repository
from test_world_project_insight import living_evidence

TARGET = BranchTarget("learner/world", "main", "exulanica/world")
AUTHOR = Author("Synthetic Student", "student@example.invalid")
#: A model this install's manifest names, and the provider that serves it.
MODEL = ("nebius_token_factory", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")


@pytest.mark.parametrize(
    ("usd", "said"),
    [
        ("0", "$0"),
        ("0.00000000", "$0"),
        ("0.000018", "less than $0.0001"),
        ("0.000375", "$0.0004"),
        ("0.0042", "$0.0042"),
        ("0.05000000", "$0.05"),
        ("0.31", "$0.31"),
        ("1.425", "$1.43"),
    ],
)
def test_money_is_said_as_the_workspace_says_it(usd, said):
    assert money(usd) == said


@pytest.mark.parametrize(
    ("milliseconds", "said"),
    [(4, "under 0.01 s"), (93, "0.09 s"), (136, "0.14 s"), (1360, "1.4 s")],
)
def test_a_time_to_answer_is_said_in_seconds(milliseconds, said):
    assert seconds(milliseconds) == said


def test_a_model_is_called_by_the_name_the_workspace_gives_it():
    assert model_name(MODEL[1]) == "Nemotron 3 Nano 30B"
    assert model_name("synthetic-model") == "synthetic-model"  # not in this manifest


def placed(project, thing_id, x_mm=0, kind=None):
    thing = deepcopy(project["things"][0])
    thing["thing_id"] = thing_id
    thing["transform"]["x_mm"] = x_mm
    if kind is not None:
        thing["kind"] = kind
    return thing


def test_things_are_called_by_their_written_name_or_their_kind_never_their_identity():
    project, _ = sample()
    things = [placed(project, f"knight:{n}", n * 1000) for n in range(1, 13)]
    things.append(placed(project, "made:1", kind={"source": "workspace", "sha256": "e" * 64}))
    world = {
        "things": things,
        "characters": [
            {"thing_id": "knight:5", "revision": 1, "words": {"name": "Sir Pip", "about": None}}
        ],
    }
    called = names([world])
    assert called["knight:1"] == "the knight"
    assert called["knight:10"] == "the second knight"  # by identity order, never shown
    assert called["knight:5"] == "Sir Pip"
    assert called["knight:9"] == "the 11th knight"
    assert called["made:1"] == "the creature made in this world"
    assert not any(":" in name for name in called.values())


def edited(project, **changes):
    changed = deepcopy(project)
    changed.update(changes)
    return changed


def test_moves_and_turns_read_as_build_mode_says_them():
    project, _ = sample()
    for yaw, x_mm, said in (
        (1_570_796, 0, "Turned the knight 90°"),
        (3_141_593, 0, "Turned the knight round"),
        (4_712_389, 0, "Turned the knight 90°"),  # three quarters one way: a quarter the other
        (261_799, 2000, "Moved the knight 2 m east, turned 15°"),
        (0, -3500, "Moved the knight 3.5 m west"),
    ):
        moved = deepcopy(project)
        moved["things"][0]["transform"].update(yaw_microradians=yaw, x_mm=x_mm)
        assert summarize(project, moved) == [said]


def test_a_model_given_changed_or_taken_away_is_one_sentence():
    project, _ = sample()
    words = {"name": "Sir Pip", "about": None}
    named = edited(
        project, decisions=[], characters=[{"thing_id": "knight:1", "revision": 1, "words": words}]
    )
    other = deepcopy(named)
    other["models"][0]["model_id"] = MODEL[1]
    assert summarize(named, other) == ["Changed Sir Pip's model to Nemotron 3 Nano 30B"]
    assert summarize(named, edited(named, models=[])) == ["Changed Sir Pip's model to Routine"]
    assert summarize(edited(named, models=[]), named) == [
        "Changed Sir Pip's model to synthetic-model"
    ]


def test_who_a_character_is_reads_as_its_owner_wrote_it_and_never_in_a_commit():
    project, _ = sample()

    def written(revision, name=None, about=None):
        return edited(
            project,
            characters=[
                {
                    "thing_id": "knight:1",
                    "revision": revision,
                    "words": {"name": name, "about": about},
                }
            ],
        )

    first = written(1, "Sir Pip", "Guards the well at night.")
    assert summarize(project, first) == ["Named the knight Sir Pip", "Wrote Sir Pip's personality"]
    assert summarize(project, first, quote=True)[1] == (
        "Wrote Sir Pip's personality: “Guards the well at night.”"
    )
    assert subject(project, first) == "Named the knight Sir Pip, wrote Sir Pip's personality"
    renamed = written(2, "Pip", "Guards the well at night.")
    assert summarize(first, renamed) == ["Renamed Sir Pip to Pip"]
    cleared = written(3, "Pip", None)
    assert summarize(renamed, cleared) == ["Cleared Pip's personality"]
    # Without its words a project keeps the record's revision: a change, no words.
    bare = edited(project, characters=[{"thing_id": "knight:1", "revision": 4}])
    assert summarize(project, bare) == ["Wrote the knight's personality"]
    again = edited(project, characters=[{"thing_id": "knight:1", "revision": 5}])
    assert summarize(bare, again, quote=True) == ["Changed the knight's personality"]


def test_a_written_name_cannot_break_a_commit_subject():
    project, _ = sample()
    dashed = edited(
        project,
        characters=[
            {
                "thing_id": "knight:1",
                "revision": 1,
                "words": {"name": "Pip\u2014the brave", "about": None},
            }
        ],
    )
    said = subject(project, dashed)
    assert "\u2014" not in said and said == "Named the knight Pip-the brave"


def test_optional_additions_left_out_keep_a_checkpoint_s_digest():
    project, _ = sample()
    assert checkpoint_digest(edited(project, title=None, characters=None)) == checkpoint_digest(
        project
    )
    assert "title" not in document(edited(project, title=None))


def test_runs_are_numbered_in_the_order_they_opened():
    _, later = living_evidence(session_id="0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a50")
    _, earlier = living_evidence(session_id="0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5f")
    [(name, run)] = earlier.items()
    run["living_session"]["opened"]["at"] = "2026-10-13T22:30:00Z"
    assert run_numbers({**later, name: run}) == {name: 1, **dict.fromkeys(later, 2)}


# Nothing internal in what a pull request shows


def with_model(world, evidence):
    """The synthetic project's knight asked of a model this install's manifest names."""
    for held in (world, evidence):
        old = digest(canonical_json(held["models"][0]))
        held["models"][0].update(provider=MODEL[0], model_id=MODEL[1])
        new = digest(canonical_json(held["models"][0]))
        for decision in held["decisions"]:
            if decision["binding_sha256"] == old:
                decision["binding_sha256"] = new
    return world, evidence


def shown(tmp_path, *, readable):
    """A pull request's title and text for a project with a run, a title and a character."""
    world, sessions = living_evidence()
    [evidence] = sessions.values()
    if not readable:
        for decision in evidence["decisions"]:
            decision.pop("readable")
    world, evidence = with_model(world, evidence)
    character = {"thing_id": "knight:1", "revision": 2}
    if readable:
        character["words"] = {"name": "Sir Pip", "about": "Guards the well at night."}
        world["title"] = "Terraces on the bay"
    world["characters"] = [character]
    folder = tmp_path / str(readable)
    create(folder, world, author=AUTHOR, evidence=[evidence])
    repository = Repository()
    repository.visibility = "PRIVATE" if readable else "PUBLIC"
    review = RollingPullRequests(repository.request).review(TARGET, Project(folder, author=AUTHOR))
    return review["title"], review["body"], review["commits"]


#: What a person never reads in a pull request: identities, digests and internal codes.
INTERNAL = (
    re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
    re.compile(r"[0-9a-f]{16,}"),
    re.compile(r"(?i)\b(session|provider|token|entity|payload|context)s?\b"),
    re.compile(r"\b(request|option|record|project|knight|world|snapshot|version|region):"),
    re.compile(r"nebius_token_factory|NVIDIA-Nemotron|synthetic-model|validated_choice"),
    re.compile(r"\((wait|go)\)|\boption \d"),
)


@pytest.mark.parametrize("readable", [True, False])
def test_a_pull_request_shows_no_identity_digest_or_code(tmp_path, readable):
    title, body, commits = shown(tmp_path, readable=readable)
    visible, _, comment = body.partition("<!--")
    assert comment.startswith(" exulanica files: ") and comment.rstrip().endswith("-->")
    # The society's own sentence for why a run ended is its words, read unchanged.
    for words in (*SESSION_CLOSED_WORDS.values(), UNWORDED_CLOSE):
        visible = visible.replace(words, "")
    for text in (title, visible, *(c["message"] for c in commits)):
        for pattern in INTERNAL:
            assert pattern.search(text) is None, (pattern.pattern, pattern.search(text))
    assert "Nemotron 3 Nano 30B" in visible
    if readable:
        assert title == "Changes to Terraces on the bay"
        assert "- Wrote Sir Pip's personality: “Guards the well at night.”" in visible
        assert "- Sir Pip, with Nemotron 3 Nano 30B: 6 decisions, 6 done" in visible
    else:
        assert title == "Changes to this world"
        assert "- Wrote the knight's personality" in visible
        assert "Sir Pip" not in body and "Guards the well" not in body


def parted(project, *parts):
    return edited(project, parts=[dict(part) for part in parts])


def part(ordinal, kind, centre=(4_000, 3_000), turns=0, label=None, removed=False):
    entry = {
        "part_id": f"0190a1b2-c3d4-4e5f-8a9b-00000000000{ordinal}",
        "kind": None if removed else kind,
        "centre_mm": None if removed else list(centre),
        "quarter_turns": turns,
        "removed": removed,
    }
    if label is not None and not removed:
        entry["label"] = label
    return entry


def test_a_made_world_s_parts_read_in_build_mode_s_words():
    project, _ = sample()
    bench, pool = part(1, "fixture", label="Bench"), part(2, "area", (9_000, 1_000), label="Pond")
    before = parted(project, bench, pool)
    assert summarize(project, before) == ["Kept the 2 parts this world was made with"]
    moved = parted(project, {**bench, "centre_mm": [6_000, 3_000], "quarter_turns": 1}, pool)
    assert summarize(before, moved) == ["Moved the bench 2 m east, turned 90°"]
    turned = parted(project, {**bench, "quarter_turns": 2}, pool)
    assert summarize(before, turned) == ["Turned the bench round"]
    gone = parted(project, bench, part(2, "area", removed=True))
    assert summarize(before, gone) == ["Removed the pond"]
    assert summarize(gone, before) == ["Brought back the pond"]


def test_a_public_repository_calls_a_made_part_by_its_kind():
    from exulanica.world_package.projects.words import without_words

    project, _ = sample()
    halls = [part(n, "building", (n * 10_000, 0), label="Tea house") for n in (1, 2)]
    before = parted(project, *halls)
    after = parted(project, halls[0], {**halls[1], "centre_mm": [20_000, -3_000]})
    assert summarize(before, after) == ["Moved the second tea house 3 m south"]
    assert summarize(without_words(before), without_words(after)) == [
        "Moved the second building 3 m south"
    ]


def test_an_edit_of_the_same_version_is_said_by_what_it_changed_alone():
    project, _ = sample()
    moved = deepcopy(project)
    moved["things"][0]["transform"]["x_mm"] = 2000
    moved["source"]["state_sha256"] = "c" * 64  # every edit changes the version's state
    assert summarize(project, moved) == ["Moved the knight 2 m east"]
    other = deepcopy(moved)
    other["source"]["version_id"] = "version:another"
    assert summarize(moved, other) == ["Followed another version of the world"]


def test_a_made_building_raised_or_lowered_says_its_storeys():
    project, _ = sample()
    hall = {**part(1, "building", label="Tea house"), "storeys": 2}
    before = parted(project, hall)
    assert summarize(before, parted(project, {**hall, "storeys": 4})) == [
        "Raised the tea house to 4 storeys"
    ]
    assert summarize(before, parted(project, {**hall, "storeys": 1})) == [
        "Lowered the tea house to 1 storey"
    ]


def test_a_removal_undone_reads_as_build_mode_s_note_says_it():
    # One sentence for one change, in the note, in History and in a pull request: build mode's
    # shipped words, as a row without the full stop.
    from pathlib import Path

    notes = (
        Path(__file__).resolve().parents[1] / "tools/previews/world-workspace/build-words.mjs"
    ).read_text(encoding="utf-8")
    assert "return `Brought back ${what}`;" in notes
    project, _ = sample()
    removed = deepcopy(project)
    removed["things"][0]["removed"] = True
    removed["models"], removed["decisions"] = [], []
    unmodelled = edited(project, models=[], decisions=[])
    assert summarize(removed, unmodelled) == ["Brought back the knight"]
    pond = part(2, "area", (9_000, 1_000), label="Pond")
    assert summarize(parted(project, part(2, "area", removed=True)), parted(project, pond)) == [
        "Brought back the pond"
    ]


def test_a_public_repository_calls_a_garden_fixture_a_part():
    from exulanica.world_package.projects.words import part_names

    fixtures = [part(n, "fixture", (n * 1_000, 0)) for n in (1, 2)]
    assert sorted(part_names([{"parts": fixtures}]).values()) == ["the part", "the second part"]


def with_creature(project, label=None, thing_id="creature:1", sha="e" * 64):
    """The sample world with a creature its workspace made, labelled where the project kept it."""
    world = deepcopy(project)
    creature = placed(world, thing_id, 3_000, kind={"source": "workspace", "sha256": sha})
    if label is not None:
        creature["label"] = label
    world["things"].append(creature)
    if all(d["sha256"] != sha for d in world["dependencies"]):
        world["dependencies"].append(
            {
                "kind": "thing-kind",
                "sha256": sha,
                "licence": "synthetic-test-only",
                "source_id": "workspace-kind:synthetic",
            }
        )
    return world


def test_a_made_creature_is_called_by_its_kind_s_label_where_the_project_keeps_it():
    # J20: its maker's words, as its tag and History say it; else the fixed words (P2, W3).
    project, _ = sample()
    heron = {"source": "workspace", "sha256": "e" * 64}
    moth = {"source": "workspace", "sha256": "f" * 64}
    world = {
        "things": [
            {**placed(project, "made:1", kind=heron), "label": "Long necked marsh heron"},
            {**placed(project, "made:2", kind=heron), "label": "Long necked marsh heron"},
            {**placed(project, "made:3", kind=moth), "label": "GLOW moth of the lower pools"},
            placed(project, "made:4", kind={"source": "workspace", "sha256": "d" * 64}),
        ]
    }
    called = names([world])
    assert called["made:1"] == "the long necked marsh heron"
    assert called["made:2"] == "the second long necked marsh heron"
    assert called["made:3"] == "the GLOW moth of the lower pools"
    assert called["made:4"] == "the creature made in this world"


def test_a_made_creature_s_label_is_never_said_again_once_its_thing_has_left():
    # Its kind erased (the version read marks it gone) or no longer selected: the label stays in
    # the earlier checkpoint alone and is not written into anything new.
    project, _ = sample()
    kept = with_creature(project, "Long necked marsh heron")
    moved = deepcopy(kept)
    moved["things"][-1]["transform"]["x_mm"] += 2_000
    assert summarize(kept, moved) == ["Moved the long necked marsh heron 2 m east"]
    left = deepcopy(kept)
    left["things"] = left["things"][:-1]
    lines = summarize(kept, left)
    assert lines == ["Stopped keeping the creature made in this world in the project"]
    assert "heron" not in " ".join(lines)


def test_a_made_creature_s_label_kept_for_the_first_time_is_one_sentence():
    # Readable text turned on: the commit says what changed, never "Add dependency files".
    project, _ = sample()
    bare, kept = with_creature(project), with_creature(project, "Long necked marsh heron")
    said = ["Called the creature made in this world the long necked marsh heron"]
    assert summarize(bare, kept) == said
    assert subject(bare, kept) == said[0]
    # Readable text turned off: the label goes unsaid, under the summary's own catch-all.
    assert summarize(kept, bare) == ["Changed some details; the files show them"]


def test_a_made_creature_s_label_is_written_words():
    from exulanica.world_package.projects.checkpoint import ProjectError
    from exulanica.world_package.projects.words import without_words

    project, _ = sample()
    bare, labelled = with_creature(project), with_creature(project, "Long necked marsh heron")

    # An optional addition: a checkpoint without it keeps its digest.
    def creature(world):
        return next(t for t in document(world)["things"] if t["thing_id"] == "creature:1")

    assert "label" not in creature(bare)
    assert creature(labelled)["label"] == "Long necked marsh heron"
    # Left out for a repository that is not private.
    assert all("label" not in thing for thing in without_words(document(labelled))["things"])
    # A shipped kind's words are the library's: no thing of one carries a label.
    shipped = deepcopy(project)
    shipped["things"][0]["label"] = "Long necked marsh heron"
    with pytest.raises(ProjectError):
        document(shipped)


# A town's residents, who are no placed things

BAKER = "0190a1b2-c3d4-7e5f-8a9b-00000000b001"
SECOND_BAKER = "0190a1b2-c3d4-7e5f-8a9b-00000000b002"
FERRY_KEEPER = "0190a1b2-c3d4-7e5f-8a9b-00000000f001"
NOBODY_SAID = "0190a1b2-c3d4-7e5f-8a9b-00000000a001"


def with_residents(project, *residents, model=None):
    """The sample checkpoint with these residents, each decided for by the knight's model (or
    `model`), its binding naming the resident as a thing's names its placed id."""
    world = deepcopy(project)
    world["residents"] = [dict(resident) for resident in residents]
    for resident in residents:
        binding = {**project["models"][0], "thing_id": resident["resident_id"]}
        if model is not None:
            binding.update(provider=MODEL[0], model_id=model)
        world["models"].append(binding)
    return world


def test_a_resident_is_called_by_its_kept_name_else_its_role_never_its_identity():
    project, _ = sample()
    world = with_residents(
        project,
        {"resident_id": BAKER, "role": "baker"},
        {"resident_id": SECOND_BAKER, "role": "baker"},
        {"resident_id": FERRY_KEEPER, "role": "ferry_keeper", "name": "Bram Tolley"},
        {"resident_id": NOBODY_SAID, "role": None},
    )
    called = names([document(world)])
    assert called[BAKER] == "the baker"
    assert called[SECOND_BAKER] == "the second baker"  # by identity order, never shown
    assert called[FERRY_KEEPER] == "Bram Tolley"
    assert called[NOBODY_SAID] == "the resident"
    assert called["knight:1"] == "the knight"
    unnamed = with_residents(project, {"resident_id": FERRY_KEEPER, "role": "ferry_keeper"})
    assert names([unnamed])[FERRY_KEEPER] == "the ferry keeper"


def test_a_resident_s_model_reads_as_a_thing_s_does():
    project, _ = sample()
    project = edited(project, decisions=[])
    before = with_residents(project, {"resident_id": BAKER, "role": "baker"})
    after = with_residents(project, {"resident_id": BAKER, "role": "baker"}, model=MODEL[1])
    assert summarize(before, after) == ["Changed the baker's model to Nemotron 3 Nano 30B"]
    assert summarize(before, project) == ["Changed the baker's model to Routine"]
    named = {"resident_id": BAKER, "role": "baker", "name": "Odile Fenn"}
    assert summarize(
        with_residents(project, named), with_residents(project, named, model=MODEL[1])
    ) == ["Changed Odile Fenn's model to Nemotron 3 Nano 30B"]


def test_residents_left_out_keep_an_old_checkpoint_s_digest_and_bindings():
    from exulanica.world_package.projects.schema import ModelBinding, binding_sha256

    project, _ = sample()
    old = checkpoint_digest(project)
    assert "residents" not in document(project)
    assert checkpoint_digest(edited(project, residents=None)) == old
    assert checkpoint_digest(edited(project, residents=[])) == old
    # A binding keeps its fields, so a decision's binding digest is the one it always had.
    binding = project["models"][0]
    assert binding_sha256(ModelBinding.model_validate(binding)) == digest(canonical_json(binding))
    # A resident's name is an optional addition too.
    bare = with_residents(project, {"resident_id": BAKER, "role": "baker"})
    assert checkpoint_digest(bare) == checkpoint_digest(
        with_residents(project, {"resident_id": BAKER, "role": "baker", "name": None})
    )


def test_a_binding_names_a_selected_thing_or_a_kept_resident():
    from exulanica.world_package.projects.checkpoint import ProjectError
    from exulanica.world_package.projects.words import without_words

    project, _ = sample()
    kept = with_residents(project, {"resident_id": BAKER, "role": "baker", "name": "Odile Fenn"})
    orphan = deepcopy(kept)
    orphan["residents"] = []
    with pytest.raises(ProjectError):
        document(orphan)
    # A resident's name is written words: left out for a repository that is not private.
    assert without_words(document(kept))["residents"] == [{"resident_id": BAKER, "role": "baker"}]
