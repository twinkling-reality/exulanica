"""The sentence a person reads and the sentence the server checks are the same sentence.

The browser sends back the wording it displayed and the server compares it for exact equality, so
a client that showed something else is refused instead of believed. The attestation is written
twice on purpose, once in each language, and the test below holds the two equal: nothing in either
language reads the other, so a reworded sentence on one side would refuse every person on the
other, a silent break with nothing pointing at the cause.

A model right's words are not written twice. The browser reads every one of them from
``GET /personal-admission`` (``model_right_offers``) and keeps no copy, and the second test holds
that: no notice or stop sentence the server states appears anywhere in the app's source.

The parser below reads the TypeScript source rather than a build output. ``HUMAN_ATTESTATION`` is
its positive control: a parser that returned the wrong text, or nothing at all, fails on it.
"""

import re
from pathlib import Path

import pytest
from exulanica.ingest.personal_admission import HUMAN_ATTESTATION, model_right_offers

SOURCE = Path(__file__).resolve().parents[1] / "web/packages/app/src/personal-admission-api.ts"

_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", "'": "'", '"': '"', "`": "`"}


def _literal(text: str, start: int) -> tuple[str, int]:
    """One JavaScript string literal beginning at ``start``, and the index just past it."""
    quote = text[start]
    out: list[str] = []
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            escape = text[index + 1]
            if escape == "u":
                out.append(chr(int(text[index + 2 : index + 6], 16)))
                index += 6
                continue
            out.append(_ESCAPES[escape])
            index += 2
            continue
        if char == quote:
            return "".join(out), index + 1
        out.append(char)
        index += 1
    raise AssertionError(f"unterminated string literal at {start}")


def typescript_constant(name: str, source: str) -> str:
    """The value of ``export const <name> = <literal> + <literal> ...;`` in ``source``."""
    match = re.search(rf"^export const {name} = ", source, re.MULTILINE)
    assert match is not None, f"{name} is not exported from {SOURCE.name}"
    index = match.end()
    parts: list[str] = []
    while True:
        while source[index] in " \n\r\t":
            index += 1
        assert source[index] in "\"'`", f"{name} is not a plain string concatenation"
        part, index = _literal(source, index)
        parts.append(part)
        while source[index] in " \n\r\t":
            index += 1
        if source[index] == ";":
            return "".join(parts)
        assert source[index] == "+", f"{name} is not a plain string concatenation"
        index += 1


@pytest.mark.parametrize(("name", "expected"), [("HUMAN_ATTESTATION", HUMAN_ATTESTATION)])
def test_the_browser_and_the_server_state_the_same_words(name, expected):
    assert typescript_constant(name, SOURCE.read_text(encoding="utf-8")) == expected


APP_SOURCE = SOURCE.parent


def test_the_browser_keeps_no_copy_of_a_model_right_s_words():
    """Every notice and stop sentence reaches the browser in the status read, never as source."""
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(APP_SOURCE.rglob("*.ts"))
    )
    # Positive control: the reader sees the sources, including a sentence they do still state.
    assert HUMAN_ATTESTATION.split(" ", 4)[-1][:40] in source
    for offer in model_right_offers():
        for words in (offer.notice, offer.stop):
            # A long enough stretch to be a copy, short enough to survive a line break in a
            # concatenated literal.
            for stretch in (words[:48], words[-48:]):
                assert stretch not in source, f"the app states the {offer.role} words itself"


def test_the_parser_reads_escapes_rather_than_reporting_agreement(tmp_path):
    """A parser that dropped escapes would make a mismatched apostrophe look like a match."""
    source = "export const X = 'it\\u2019s '\n  + \"a \\\"quoted\\\" word\";\n"
    assert typescript_constant("X", source) == "it\u2019s a \"quoted\" word"
    with pytest.raises(AssertionError):
        typescript_constant("MISSING", source)
