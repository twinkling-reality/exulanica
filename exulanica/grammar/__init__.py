"""Grammar: a generated subject is a pure function of a seed, a version and a catalog.

**ADR-0008 is structural here.** This package sits below ``exulanica.evidence`` in the
exhaustive import-linter layer order and a forbidden contract names ``exulanica.evidence``,
``exulanica.store``, ``exulanica.db``, ``exulanica.ingest``, ``exulanica.identity`` and
``exulanica.selection``. It may import ``exulanica.canonical``, ``exulanica.errors`` and
``exulanica.env`` and nothing else in this repository. A generator that cannot construct a
citation cannot return one, however it is later changed by somebody who never read this
sentence.

That absence is what lets a generated world exist beside a remembered one without borrowing its
truth status. Seeded is not sampled: every value a grammar emits is recomputable, byte for byte,
from the seed, the grammar version and the catalog digest, so nothing here is a model output and
nothing here is an observation.
"""

from __future__ import annotations
