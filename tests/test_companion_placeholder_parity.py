"""The browser reads the Companion's words with the server's own vocabulary.

The server replaces every saved name with a placeholder of its class before any hosted request
(``exulanica/epistemics/saved_names.py``), and the browser turns each one back into the account
holder's own name (``web/packages/app/src/companion-names.ts``). Neither language reads the other,
so two facts are written twice and held to one text here: the placeholder pattern, because a class
the server learns to write and the browser does not recognise would reach a person as brackets;
and the naming predicate, because the browser tells a withdrawn person's withheld name from one
never given by the naming claim the graph keeps (``exulanica/graph/entities.py``).

``typescript_constant`` is the parser ``tests/test_consent_wording_is_one_text.py`` controls with a
pair that agrees independently of these.
"""

from pathlib import Path

import pytest
from exulanica.epistemics.saved_names import PLACEHOLDER
from exulanica.graph.entities import NAME_PREDICATE

from test_consent_wording_is_one_text import typescript_constant

SOURCE = Path(__file__).resolve().parents[1] / "web/packages/app/src/companion-names.ts"


@pytest.mark.parametrize(
    ("name", "server"),
    [("PLACEHOLDER_SOURCE", PLACEHOLDER.pattern), ("NAME_PREDICATE", NAME_PREDICATE)],
)
def test_the_browser_reads_what_the_server_writes(name, server):
    assert typescript_constant(name, SOURCE.read_text(encoding="utf-8")) == server
