"""The browser recognises exactly the placeholders the server writes.

The server replaces every saved name with a placeholder of its class before any hosted request
(``exulanica/epistemics/saved_names.py``), and the browser turns each one back into the account
holder's own name (``web/packages/app/src/companion-names.ts``). Neither language reads the other,
so the pattern is written twice, and this holds the two to one text: a class the server learns to
write and the browser does not recognise would reach a person as brackets.

``typescript_constant`` is the parser ``tests/test_consent_wording_is_one_text.py`` controls with a
pair that agrees independently of this one.
"""

from pathlib import Path

from exulanica.epistemics.saved_names import PLACEHOLDER

from test_consent_wording_is_one_text import typescript_constant

SOURCE = Path(__file__).resolve().parents[1] / "web/packages/app/src/companion-names.ts"


def test_the_browser_recognises_the_placeholders_the_server_writes():
    browser = typescript_constant("PLACEHOLDER_SOURCE", SOURCE.read_text(encoding="utf-8"))
    assert browser == PLACEHOLDER.pattern
