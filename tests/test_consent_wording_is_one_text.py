"""The sentences a person reads come from the server that checks them; the browser keeps no copy.

``GET /personal-admission`` states the attestation a human review sends back (``attestation``) and
every model right's notice and stop sentence (``model_right_offers``). The browser shows those words
and sends back the attestation it displayed, and the server compares it for exact equality, so a
client that showed something else is refused instead of believed. Nothing is written twice, so a
reworded sentence on the server is the sentence every browser shows, with no second copy to fall
out of step and refuse every person on the other side.

The first test holds that no such sentence appears anywhere in the app's source.

``typescript_constant`` below reads a constant from TypeScript source rather than a build output.
The tests that hold other browser constants to the server's import it from here, and the last
test is its control: a parser that dropped escapes, or found a constant that is not there, fails
it.
"""

import re
from pathlib import Path

import pytest
from exulanica.ingest.personal_admission import HUMAN_ATTESTATION, model_right_offers

APP_SOURCE = Path(__file__).resolve().parents[1] / "web/packages/app/src"
ADMISSION_CLIENT = APP_SOURCE / "personal-admission-api.ts"
#: Where the client declares the served attestation it shows and sends back.
SERVED_ATTESTATION = "readonly attestation?: string;"

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
    assert match is not None, f"{name} is not exported from the source read"
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


def _stretches(words: str) -> tuple[str, str]:
    """A long enough stretch to be a copy, short enough to survive a line break in a concatenated
    literal: the start and the end of the sentence."""
    return words[:48], words[-48:]


def test_the_browser_keeps_no_copy_of_the_words_a_person_is_shown():
    """The attestation and every notice and stop sentence reach the browser in the status read."""
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(APP_SOURCE.rglob("*.ts"))
    )
    # Positive control: the reader sees the sources, including the client that reads the words.
    assert SERVED_ATTESTATION in ADMISSION_CLIENT.read_text(encoding="utf-8")
    assert SERVED_ATTESTATION in source
    for stretch in _stretches(HUMAN_ATTESTATION):
        assert stretch not in source, "the app states the attestation itself"
    for offer in model_right_offers():
        for words in (offer.notice, offer.stop):
            for stretch in _stretches(words):
                assert stretch not in source, f"the app states the {offer.role} words itself"


def test_the_parser_reads_escapes_rather_than_reporting_agreement():
    """A parser that dropped escapes would make a mismatched apostrophe look like a match."""
    source = "export const X = 'it\\u2019s '\n  + \"a \\\"quoted\\\" word\";\n"
    assert typescript_constant("X", source) == "it\u2019s a \"quoted\" word"
    with pytest.raises(AssertionError):
        typescript_constant("MISSING", source)
