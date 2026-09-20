"""The epistemic layer: what is claimed, by whom, and on what evidence.

Four modules share those rules so a second writer cannot drift:

*   :mod:`exulanica.epistemics.assertions` is the one writer of claims, under the four
    provenance classes.
*   :mod:`exulanica.epistemics.vocabulary` records the reviewed decision for every
    predicate, including whether it writes a name.
*   :mod:`exulanica.epistemics.source_images` is persisted image selection and
    normalized lineage.
*   :mod:`exulanica.epistemics.caption_embeddings` is caption vector identity and
    persistence for ingest and retrieval.
"""

from exulanica.epistemics.assertions import AssertionWriter

__all__ = ["AssertionWriter"]
