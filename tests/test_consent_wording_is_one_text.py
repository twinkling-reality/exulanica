"""The sentences a person reads come from the server that checks them; the browser keeps no copy.

``GET /personal-admission`` states the attestation a human review sends back (``attestation``) and
every model right's notice and stop sentence (``model_right_offers``). The browser shows those words
and sends back the attestation it displayed, and the server compares it for exact equality, so a
client that showed something else is refused instead of believed. Nothing is written twice, so a
reworded sentence on the server is the sentence every browser shows, with no second copy to fall
out of step and refuse every person on the other side.

The test below holds that no such sentence appears anywhere in the app's source.
"""

from pathlib import Path

from exulanica.ingest.personal_admission import HUMAN_ATTESTATION, model_right_offers

APP_SOURCE = Path(__file__).resolve().parents[1] / "web/packages/app/src"
ADMISSION_CLIENT = APP_SOURCE / "personal-admission-api.ts"
#: Where the client declares the served attestation it shows and sends back.
SERVED_ATTESTATION = "readonly attestation?: string;"


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
