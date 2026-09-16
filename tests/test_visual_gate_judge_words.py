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


def test_no_tracked_file_carries_the_judges_words():
    companions = sorted((_ROOT / JUDGE_WORDS_DIRECTORY).glob("*.json"))
    if not companions:
        pytest.skip(_NOT_HERE.format(name="any record"))
    words: list[str] = []
    lines: list[str] = []
    for companion in companions:
        document = json.loads(companion.read_bytes())
        words += [reply["words"] for reply in document["replies"] if reply["words"] is not None]
        lines += [line["words"] for line in document.get("shownLines", [])]
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=_ROOT, capture_output=True, check=False)
    if listed.returncode != 0:
        pytest.skip("this checkout is not a git repository, so its tracked files cannot be listed")
    checked = 0
    for name in listed.stdout.decode("utf-8").split("\0"):
        path = _ROOT / name
        if not name or path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        refuse_private_words(
            data.decode("utf-8", errors="replace"),
            words,
            shown=_SHOWN,
            lines=lines,
            quoted=False,
            path=name,
        )
        checked += 1
    assert checked > 0
