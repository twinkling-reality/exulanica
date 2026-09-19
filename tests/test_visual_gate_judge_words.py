"""The visual gate judge's words stay on the machine they were given on.

Every visual gate record that reads a reply from the judge carries only the SHA-256 and byte count
of the judge's words, and binds a private companion under ``.exulanica/judge-words/``, which git
ignores. The public checks run everywhere. The checks against a companion, and the guard that no
tracked file carries the words, need the companion itself, so they run only on the machine the
judge answered on and skip anywhere else, saying so.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from exulanica.evaluation import visual_gate
from exulanica.evaluation.gate_keys import (
    ANSWER_OPTIONS,
    ANSWER_REQUIREMENT,
    CAPTURE_LABELS,
    CARRIED_WORDS_NOTICE,
    OPTION_ANSWERS,
    RUBRIC_GUIDANCE,
    RUBRIC_QUESTION,
    SUPERSEDED_VERSIONS,
    reason_follow_up,
)
from exulanica.evaluation.visual_gate import (
    JUDGE_WORDS_DIRECTORY,
    JUDGE_WORDS_PROFILE,
    JUDGEMENT_ANSWERS_PROFILE,
    refuse_private_words,
    typed_reply_answer,
    words_fingerprint,
    words_from_companion,
)

_ROOT = Path(__file__).resolve().parents[1]
_V3 = "docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v3.json"
_V4 = "docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v4.json"
_V5 = "docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v5.json"
_BASELINE = "docs/evaluation/2026-09-15-flatiron-owned-district-baseline.json"
#: Every record that reads a reply from the judge, and so binds a private companion.
_WITH_WORDS = (_V3, _V4, _V5, _BASELINE)
_NOT_HERE = (
    "the judge's words are kept only on the machine they were given on, and this checkout has no "
    "private companion for {name}"
)
#: Everything the judge has been shown, under any version. The judge may echo those words.
_SHOWN = (
    RUBRIC_QUESTION,
    RUBRIC_GUIDANCE,
    ANSWER_REQUIREMENT,
    CARRIED_WORDS_NOTICE,
    *ANSWER_OPTIONS,
    *(reason_follow_up(answer) for answer in OPTION_ANSWERS.values()),
    *(version.prompt(label) for version in SUPERSEDED_VERSIONS for label in CAPTURE_LABELS),
)


#: Keys that may hold a long string beside the judge's words without being them: metadata, a text
#: the judge was shown, or the asking session's own prose about the exchange. ALLOWED RATHER THAN
#: FORBIDDEN, and checked exhaustively: a key nobody listed stops the suite instead of being
#: skipped, which is what the `words` versus `text` spelling did on 2026-09-19. Scoped to the
#: objects that actually carry the judge's replies, so the list stays short enough to read.
_BESIDE_THE_WORDS = frozenset(
    {
        "asked",
        "captureSha256",
        "carried",
        "followUp",
        "givenAs",
        "givenAt",
        "givenBefore",
        "kind",
        "label",
        "notice",
        "picked",
        "picture",
        "prompt",
        "rubricSha256",
        "rubricVersion",
        "saidBy",
        "shown",
        "shownAbove",
        "state",
        "typedBy",
        "what",
        "words_bytes",
        "words_private",
        "words_sha256",
    }
)
#: The keys that DO hold the judge's own words, in the two shapes that directory holds.
_THE_WORDS = frozenset({"words", "text"})


def _folded(text: str) -> str:
    """Text as refuse_private_words compares it. Imported behaviour, restated nowhere else."""
    return visual_gate._folded(text)


def _attributed_to(holder: dict, judge: str) -> bool:
    """Whether this object says the judge wrote what it holds."""
    return any(holder.get(name) == judge for name in ("typedBy", "saidBy"))


def _words_the_judge_gave(document: dict) -> tuple[list[str], list[str], list[str]]:
    """The judge's own words in a companion of either shape, what was shown, and the lines.

    REFUSES AN UNKNOWN PROFILE rather than skipping it. A directory that holds words is guarded by
    a reader that knows every shape in it or by nothing at all: filtering out the stranger leaves
    the newest words unguarded and says so to nobody. That is not a hypothetical. This guard
    errored with KeyError('replies') from the moment an answers file in the second shape was
    written beside the companions, so it checked NOTHING across the arrival of new words.
    """
    profile = document.get("profile")
    judge = document.get("judge")
    assert profile in (JUDGE_WORDS_PROFILE, JUDGEMENT_ANSWERS_PROFILE), (
        f"{JUDGE_WORDS_DIRECTORY} holds a document of profile {profile!r}, which this guard does "
        "not know how to read. Teach it the shape; do not skip the file."
    )
    words: list[str] = []
    lines: list[str] = []
    shown: list[str] = []
    holders: list[dict] = []
    if profile == JUDGE_WORDS_PROFILE:
        holders = list(document["replies"])
        lines = [line["words"] for line in document.get("shownLines", [])]
    else:
        shown = list(document.get("options", []))
        for picture in document["pictures"]:
            holders.append(picture)
            shown += [picture[name] for name in ("prompt", "picture") if picture.get(name)]
            follow = picture.get("followUp")
            if isinstance(follow, dict):
                holders.append(follow)
                if follow.get("shown"):
                    shown.append(follow["shown"])
        holders += list(document.get("outsideTheJudgement", []))
    for holder in holders:
        if not _attributed_to(holder, judge):
            continue
        for name, value in holder.items():
            if not isinstance(value, str) or len(_folded(value).split()) < 3:
                continue
            if name in _THE_WORDS:
                words.append(value)
            elif name not in _BESIDE_THE_WORDS:
                raise AssertionError(
                    f"{document.get('publicRecord') or profile}: {name!r} holds a long string "
                    "beside the judge's words and this guard does not know whether it IS them. "
                    f"Add it to _THE_WORDS or to _BESIDE_THE_WORDS; leaving it unlisted is how a "
                    "reply goes unguarded."
                )
    return words, lines, shown


def _earliest_the_judge_typed(documents: list[dict]) -> str:
    """The first moment any companion records the judge typing anything."""
    moments: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            given = value.get("givenAt")
            if isinstance(given, str) and given:
                moments.append(given)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for document in documents:
        walk(document)
    assert moments, "no companion says when the judge typed anything"
    return min(moments)


def _record(path: str) -> dict:
    return json.loads((_ROOT / path).read_bytes())["record"]


def _fingerprints(value: object, found: list[tuple[object, object, object]]) -> list:
    """Every words fingerprint a public record carries, wherever it sits."""
    if isinstance(value, dict):
        if "words_sha256" in value:
            found.append((value["words_sha256"], value["words_bytes"], value["words_private"]))
        for item in value.values():
            _fingerprints(item, found)
    elif isinstance(value, list):
        for item in value:
            _fingerprints(item, found)
    return found


def _keys_named(name: str, value: object) -> bool:
    """Whether any object inside ``value`` has a key called ``name``."""
    if isinstance(value, dict):
        return name in value or any(_keys_named(name, item) for item in value.values())
    if isinstance(value, list):
        return any(_keys_named(name, item) for item in value)
    return False


def _companion(path: str) -> dict:
    """The private companion of ``path``, or a skip that names why it is not here."""
    companion = _ROOT / JUDGE_WORDS_DIRECTORY / Path(path).name
    if not companion.is_file():
        pytest.skip(_NOT_HERE.format(name=Path(path).name))
    data = companion.read_bytes()
    binding = _record(path)["judgeWords"]
    assert (len(data), hashlib.sha256(data).hexdigest()) == (
        binding["byte_size"],
        binding["sha256"],
    ), f"{companion.name} is not the companion {path} binds"
    return json.loads(data)


def _lines(document: dict) -> dict[str, str]:
    lines = {}
    for line in document.get("shownLines", []):
        fingerprint = words_fingerprint(line["words"])
        assert (line["words_sha256"], line["words_bytes"]) == (
            fingerprint["words_sha256"],
            fingerprint["words_bytes"],
        )
        lines[fingerprint["words_sha256"]] = line["words"]
    return lines


def test_every_record_that_reads_a_reply_binds_a_private_companion():
    discovered = sorted(
        path.relative_to(_ROOT).as_posix()
        for path in (_ROOT / "docs/evaluation").glob("*.json")
        if "judgeWords" in json.loads(path.read_bytes()).get("record", {})
    )
    assert discovered == sorted(_WITH_WORDS)
    for path in _WITH_WORDS:
        record = _record(path)
        binding = record["judgeWords"]
        assert binding["path"] == f"{JUDGE_WORDS_DIRECTORY}/{Path(path).name}"
        assert binding["tracked"] is False
        assert len(binding["sha256"]) == 64 and binding["byte_size"] > 0
        fingerprints = _fingerprints(record, [])
        assert any(private for _, _, private in fingerprints), path
        for digest, size, private in fingerprints:
            if private is True:
                assert isinstance(digest, str) and len(digest) == 64 and size > 0, path
            else:
                assert (digest, size, private) == (None, 0, False), path
        assert not _keys_named("verbatim", record), path
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", JUDGE_WORDS_DIRECTORY.split("/")[0]],
        cwd=_ROOT,
        check=False,
    )
    if ignored.returncode == 128:
        pytest.skip("this checkout is not a git repository, so what git ignores cannot be read")
    assert ignored.returncode == 0, "the judge-words directory must be ignored by git"


@pytest.mark.parametrize("path", _WITH_WORDS)
def test_every_fingerprint_matches_the_private_companion(path):
    document = _companion(path)
    record = _record(path)
    assert (document["profile"], document["publicRecord"]) == (JUDGE_WORDS_PROFILE, path)
    words = words_from_companion(document, path)
    lines = _lines(document)
    known = {**words, **lines}
    public = {digest: size for digest, size, private in _fingerprints(record, []) if private}
    for digest, size in public.items():
        assert digest in known, f"{path} carries a fingerprint its companion does not hold"
        assert len(known[digest].encode("utf-8")) == size
    assert set(known) <= set(public), f"{path} leaves out a reply its companion holds"
    for reply in document["replies"]:
        assert reply["typedBy"] == document["judge"]
        assert reply["givenAt"].startswith("2026-09-16T") and reply["givenAt"].endswith("Z")
    refuse_private_words(record, list(words.values()), shown=_SHOWN, lines=list(lines.values()))


def test_the_rule_reads_the_judges_own_replies_as_the_records_state():
    """What each record says the typed-reply rule does to a reply, checked against the reply."""
    for path in _WITH_WORDS:
        if not (_ROOT / JUDGE_WORDS_DIRECTORY / Path(path).name).is_file():
            pytest.skip(_NOT_HERE.format(name=Path(path).name))
    typed_v2 = [
        reply["words"]
        for reply in _companion(_V3)["replies"]
        if reply["picked"] is None and reply["words"] is not None
    ]
    # The version 5 record says one version 2 reply typed in place of a pick would read as a no.
    assert [typed_reply_answer(words) for words in typed_v2].count("no") == 1
    (message,) = [reply for reply in _companion(_V4)["replies"] if reply["kind"] == "message"]
    assert typed_reply_answer(message["words"]) is None
    typed_v4 = [reply for reply in _companion(_V5)["replies"] if reply["kind"] == "typed"]
    public = _record(_V5)["calibrationEvidence"]["pictures"]
    assert [typed_reply_answer(reply["words"]) for reply in typed_v4] == [
        entry["replies"][0]["readUnderVersion5"]["answer"] for entry in public
    ]
    answers = {
        entry["label"]: entry
        for entry in _record(_BASELINE)["gate"]["keys"]["readsAsInhabitedStreet"]["pictures"]
    }
    for reply in _companion(_BASELINE)["replies"]:
        if reply["kind"] == "reply" and reply["picked"] is None:
            assert typed_reply_answer(reply["words"]) == answers[reply["label"]]["answer"] == "no"


def _tracked_text_files() -> list[str] | None:
    """Every tracked file this check can read, or None where git cannot say."""
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=_ROOT, capture_output=True, check=False)
    if listed.returncode != 0:
        return None
    names = []
    for name in listed.stdout.decode("utf-8").split("\0"):
        path = _ROOT / name
        if not name or path.is_symlink() or not path.is_file():
            continue
        if b"\0" in path.read_bytes()[:8192]:
            continue
        names.append(name)
    return names


def _last_changed(name: str) -> str:
    return subprocess.run(
        ["git", "log", "-1", "--format=%cI", "--", name],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _runs_this_repository_already_had(
    words: list[str], names: list[str], earliest: str
) -> list[str]:
    """Five-word runs that were in a tracked file BEFORE the judge typed anything.

    A run that this repository already contained cannot have come from a reply given later, so no
    file carrying it is evidence of a leak, and eliminating the RUN clears every file carrying it
    at once instead of one file at a time. git decides: nobody picks a threshold and nobody keeps
    a list of forgiven files, which is the only way this stays honest as new words arrive.

    MEASURED 2026-09-19, when this was written. The judge's replies gave 138 distinct runs after
    excluding what they were shown; ONE hit anything; it hit five files of four different kinds;
    and it is 22 characters for five words, an average of 3.6 letters each, which is the shortest
    English there is. Two of those five files were last changed 2026-09-04, twelve days before the
    earliest moment any companion records the judge typing, so the run predates the words and all
    five are explained together. A control established the base rate this is read against: twenty
    invented sentences in the same register and at the same lengths gave 146 runs and ZERO hits,
    which bounds the per-run collision rate at about 2% and makes one hit unremarkable.
    """
    runs: set[str] = set()
    visible = [_folded(text) for text in _SHOWN]
    for text in words:
        parts = _folded(text).split()
        for index in range(max(0, len(parts) - 4)):
            run = " ".join(parts[index : index + 5])
            if not any(f" {run} " in f" {line} " for line in visible):
                runs.add(run)
    hits: dict[str, list[str]] = {}
    for name in names:
        body = f" {_folded((_ROOT / name).read_bytes().decode('utf-8', errors='replace'))} "
        for run in runs:
            if f" {run} " in body:
                hits.setdefault(run, []).append(name)
    return [
        run
        for run, carriers in hits.items()
        if any(_last_changed(name) < earliest for name in carriers)
    ]


def test_no_tracked_file_carries_the_judges_words():
    companions = sorted((_ROOT / JUDGE_WORDS_DIRECTORY).glob("*.json"))
    if not companions:
        pytest.skip(_NOT_HERE.format(name="any record"))
    documents = [json.loads(companion.read_bytes()) for companion in companions]
    words: list[str] = []
    lines: list[str] = []
    shown: list[str] = list(_SHOWN)
    for document in documents:
        gave, given_lines, given_shown = _words_the_judge_gave(document)
        words += gave
        lines += given_lines
        shown += given_shown
    assert words, "every companion in that directory held no words at all, which cannot be right"
    names = _tracked_text_files()
    if names is None:
        pytest.skip("this checkout is not a git repository, so its tracked files cannot be listed")
    earliest = _earliest_the_judge_typed(documents)
    # A run this repository already had is a run that may legitimately appear in public text,
    # which is what `shown` means to refuse_private_words, so it is carried in on that channel
    # rather than through a second mechanism beside it.
    shown += _runs_this_repository_already_had(words, names, earliest)
    for name in names:
        refuse_private_words(
            (_ROOT / name).read_bytes().decode("utf-8", errors="replace"),
            words,
            shown=shown,
            lines=lines,
            quoted=False,
            path=name,
        )
    assert names


# ---- the guard's own controls ------------------------------------------------------------------
#
# Every document below is invented here. None of it is any judge's words. A guard nobody has made
# fail is a guard nobody has tested, and this one passed for nothing at all between the moment an
# answers file arrived in a second shape and the moment somebody ran it and read the error.

_A_JUDGE = "Ada Example"
_INVENTED = "Some invented sentence that stands in for a reply nobody gave."


def _answers(**changes) -> dict:
    document = {
        "profile": JUDGEMENT_ANSWERS_PROFILE,
        "judge": _A_JUDGE,
        "judgedOn": "2026-09-19",
        "options": list(ANSWER_OPTIONS),
        "pictures": [
            {
                "label": "start",
                "picture": "Picture 1 of 3",
                "prompt": RUBRIC_QUESTION,
                "asked": True,
                "picked": ANSWER_OPTIONS[0],
                "words": _INVENTED,
                "typedBy": _A_JUDGE,
                "givenAt": "2026-09-19T09:00:00Z",
            }
        ],
    }
    document.update(changes)
    return document


def test_the_guard_refuses_a_shape_it_does_not_know_rather_than_skipping_it():
    with pytest.raises(AssertionError, match="does not know how to read"):
        _words_the_judge_gave({"profile": "exulanica.something-else/v1", "judge": _A_JUDGE})
    # And the two it does know are read rather than refused.
    words, _, _ = _words_the_judge_gave(_answers())
    assert words == [_INVENTED]
    words, lines, _ = _words_the_judge_gave(
        {
            "profile": JUDGE_WORDS_PROFILE,
            "judge": _A_JUDGE,
            "replies": [
                {"words": _INVENTED, "typedBy": _A_JUDGE, "givenAt": "2026-09-19T09:00:00Z"}
            ],
            "shownLines": [{"words": CARRIED_WORDS_NOTICE}],
        }
    )
    assert (words, lines) == ([_INVENTED], [CARRIED_WORDS_NOTICE])


def test_the_guard_reads_the_judges_words_under_whichever_key_holds_them():
    """`text` and `words` are the same thing said twice, and only one of them was ever read."""
    document = _answers(
        outsideTheJudgement=[
            {
                "saidBy": _A_JUDGE,
                "what": "a remark made before the judgement began",
                "text": "Another invented sentence, attributed to the judge and spelled text.",
                "givenAt": "2026-09-19T08:59:00Z",
            },
            {
                "saidBy": "the asking session",
                "what": "what the asker said, which is not the judge's words",
                "text": "Invented asker prose that a public record may carry without offence.",
                "givenAt": "2026-09-19T08:58:00Z",
            },
        ]
    )
    words, _, _ = _words_the_judge_gave(document)
    assert "Another invented sentence, attributed to the judge and spelled text." in words
    # What somebody else said is not the judge's words and must not be collected as them.
    assert not any("asker prose" in item for item in words)


def test_a_long_string_under_an_unlisted_key_stops_the_guard():
    """The fifth spelling problem, refused rather than skipped."""
    picture = {**_answers()["pictures"][0], "aKeyNobodyListed": "Yet another invented sentence."}
    with pytest.raises(AssertionError, match="aKeyNobodyListed"):
        _words_the_judge_gave(_answers(pictures=[picture]))


def test_a_run_this_repository_already_had_is_eliminated_and_an_invented_one_is_not():
    """The elimination, controlled in both directions against real tracked files."""
    names = _tracked_text_files()
    if names is None:
        pytest.skip("this checkout is not a git repository, so its tracked files cannot be listed")
    old = "exulanica/migrations/0002_naming_and_admission.sql"
    assert old in names
    changed = _last_changed(old)
    # A five-word run taken from that file, so it provably predates anything typed after it.
    parts = _folded((_ROOT / old).read_text(encoding="utf-8")).split()
    borrowed = " ".join(parts[40:45])
    after = "9999-01-01T00:00:00Z"
    assert changed < after
    assert _runs_this_repository_already_had([borrowed], names, after) == [borrowed]
    # And a run this repository does not have is not eliminated, so the rule is not a constant.
    # BUILT AT RUNTIME, never written out: the first attempt spelled a nonsense phrase as a
    # literal here, which put it in a tracked file and had the rule eliminate it correctly. A
    # control's own text is part of the corpus it controls.
    absent = " ".join([*borrowed.split()[:4], "qzvwxj"])
    assert _runs_this_repository_already_had([absent], names, after) == []
    # Nor is a real run eliminated when nothing carrying it predates the judge, which is the
    # direction that decides whether a hit stands.
    carried_since = min(
        _last_changed(name)
        for name in names
        if borrowed in _folded((_ROOT / name).read_bytes().decode("utf-8", errors="replace"))
    )
    assert _runs_this_repository_already_had([borrowed], names, carried_since) == []
