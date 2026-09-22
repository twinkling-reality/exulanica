"""The sentence a person reads and the sentence the server checks are the same sentence.

The browser sends back the wording it displayed and the server compares it for exact equality, so
the two constants are written twice on purpose: a client that showed something else is then
refused instead of believed. Written twice is not the same as free to drift. Nothing in either
language reads the other, so a reworded notice in the browser would be refused by the server for
every person, and a reworded notice in the server would refuse every browser: a silent break that
shows up as "3D estimate could not be recorded" and nothing pointing at the cause.

The parser below reads the TypeScript source rather than a build output. ``HUMAN_ATTESTATION`` is
its positive control: it is an older pair that agrees today, so a parser that returned the wrong
text, or nothing at all, fails on that arm as well as on the one under test.
"""

import re
from pathlib import Path

import pytest
from exulanica.ingest.personal_admission import DEPTH_MODEL_NOTICE, HUMAN_ATTESTATION

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


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # The control: an older pair, agreeing before this lane and not changed by it.
        ("HUMAN_ATTESTATION", HUMAN_ATTESTATION),
        ("DEPTH_MODEL_NOTICE", DEPTH_MODEL_NOTICE),
    ],
)
def test_the_browser_and_the_server_state_the_same_words(name, expected):
    assert typescript_constant(name, SOURCE.read_text(encoding="utf-8")) == expected


def test_the_parser_reads_escapes_rather_than_reporting_agreement(tmp_path):
    """A parser that dropped escapes would make a mismatched apostrophe look like a match."""
    source = "export const X = 'it\\u2019s '\n  + \"a \\\"quoted\\\" word\";\n"
    assert typescript_constant("X", source) == "it\u2019s a \"quoted\" word"
    with pytest.raises(AssertionError):
        typescript_constant("MISSING", source)
