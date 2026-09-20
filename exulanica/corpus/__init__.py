"""A synthetic photograph corpus, generated deterministically, labelled synthetic in its bytes.

**What this is for.** Nothing about scene grouping, continuity, reconstruction or evaluation is
real until a corpus exists. This package produces one: eighty-odd JPEGs with genuine EXIF,
arranged so that the properties the pipeline claims are actually exercised rather than assumed.
It runs the real ingest path, not a fixture loader, so what it verifies is the code that runs
on a photograph library.

**What it is not.** It is not a stand-in for photographs of somebody's life, and it does not
claim to be. The frames are projections of geometric arrangements. The coordinates are
fabricated. The device names are this generator's. Everything it produces says so in its own
EXIF, because a synthetic file that only looks synthetic while it sits in a directory called
`synthetic` is one move away from being mistaken for evidence.

**No people.** `docs/privacy-consent-threat-model.md` section 10 leaves the biometric question to
a human and says explicitly that the choice must be made before identity work begins. A synthetic
corpus containing synthetic faces would supply the input for the decision that has not been
taken, so the recurring subjects here are objects: a satchel, a flask, a lantern. They carry the
whole cross-capture continuity signal without carrying a face.

**Determinism is the point.** The same seed produces byte-identical files, so ingesting the
corpus twice is a genuine no-op and the idempotency guarantee is exercised rather than described.
That property is why the grain is drawn from a seeded stream rather than from Pillow's own noise
generator, which is unseeded.

Run it with `uv run exulanica-corpus`.
"""

from __future__ import annotations

from exulanica.corpus.plan import DEVICES, TRIPS, Device, FramePlan, Trip, build_plan
from exulanica.corpus.render import Camera, Face, Light, render
from exulanica.corpus.world import PLACES, SUBJECTS, Place

__all__ = [
    "DEVICES",
    "PLACES",
    "SUBJECTS",
    "TRIPS",
    "Camera",
    "Device",
    "Face",
    "FramePlan",
    "Light",
    "Place",
    "Trip",
    "build_plan",
    "render",
]
