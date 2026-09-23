"""Whether a person in a photograph may be shown, what they agreed to, and where a place name goes.

A package of its own rather than a corner of :mod:`exulanica.identity`, because the two answer
different questions. Identity asks who somebody is and requires a human to say so. Consent asks
what may be done with their appearance, and its answer is no until a receipt says otherwise. A
person can be perfectly identified and still never drawn. Screening that asked only whether
a photograph contained nobody cannot express that split, which is why this package exists.

The person modules are two, and the split is the whole design:

*   :mod:`exulanica.consent.regions` is where somebody is, and never who they are. It borrows
    :func:`exulanica.identity.keys.occurrence_identity_key` so that a region and the ``person``
    occurrence the vision stage already wrote for the same body share one identity, which is what
    makes a reviewer's confirmation survive a detector re-run.
*   :mod:`exulanica.consent.states` is what they agreed to, resolved from receipts and from
    nothing else. It holds no default that grants anything.

Both are pure. Neither reaches a database, so the offline verifier the design note asks for can
resolve a person's current state from a World Memory Package without one. So are
:mod:`exulanica.consent.training`, a licensee's exact-term training permission, and
:mod:`exulanica.consent.place_names`, the rule deciding whether a place's saved name may go to a
model.

:mod:`exulanica.consent.place_name_rights` is the one module here that reads and writes a
database: the account holder's decisions about a place's name, which migration 0097 stores, and
the resolver that asks the rule about them at the moment a name would be sent.
"""

from __future__ import annotations

__all__: list[str] = []
