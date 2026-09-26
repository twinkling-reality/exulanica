"""The page reads an answer's simulated people and places with the server's own pattern.

The server writes an inhabitant as ``[inhabitant A]`` and a place they use as ``[spot A]``
(``exulanica/selection/society_question.py``), and the page draws each from the society it shows
(``web/packages/app/src/companion-simulated.ts``). A class one side writes and the other does not
read would reach a person as brackets, so the pattern is held to one text here.
"""

from pathlib import Path

from exulanica.selection.society_question import SIMULATED_PLACEHOLDER

from test_consent_wording_is_one_text import typescript_constant

SOURCE = Path(__file__).resolve().parents[1] / "web/packages/app/src/companion-simulated.ts"


def test_the_page_reads_the_simulated_placeholders_the_server_writes():
    source = SOURCE.read_text(encoding="utf-8")
    written = typescript_constant("SIMULATED_PLACEHOLDER_SOURCE", source)
    assert written == SIMULATED_PLACEHOLDER.pattern
    # A positive control: the pattern finds both classes the server writes, and no saved name's.
    assert SIMULATED_PLACEHOLDER.findall("[inhabitant A] at [spot B] with [person A]") == [
        "[inhabitant A]",
        "[spot B]",
    ]
