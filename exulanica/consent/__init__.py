"""Whether a person in a photograph may be shown, and what they agreed to separately.

A package of its own rather than a corner of :mod:`exulanica.identity`, because the two answer
different questions. Identity asks who somebody is and requires a human to say so. Consent asks
what may be done with their appearance, and its answer is no until a receipt says otherwise. A
person can be perfectly identified and still never drawn, which is the case the old yes-or-no
screening gate could not express and the reason this package exists.

Two modules, and the split is the whole design:

*   :mod:`exulanica.consent.regions` is where somebody is, and never who they are. It borrows
    :func:`exulanica.identity.keys.occurrence_identity_key` so that a region and the ``person``
    occurrence the vision stage already wrote for the same body share one identity, which is what
    makes a reviewer's confirmation survive a detector re-run.
*   :mod:`exulanica.consent.states` is what they agreed to, resolved from receipts and from
    nothing else. It holds no default that grants anything.

Both are pure. Neither reaches a database, so the offline verifier the design note asks for can
resolve a person's current state from a World Memory Package without one.
"""

from __future__ import annotations

__all__: list[str] = []
