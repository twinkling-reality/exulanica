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
