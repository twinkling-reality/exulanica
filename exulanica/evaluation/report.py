"""Turning results into a report, with section 3's rules enforced by the code that writes it.

Nine rules, and the ones that can be mechanical are mechanical here rather than in a reviewer's
head. What is enforced: every number carries n and, where an interval is meaningful, an interval
(rule 1, in ``counts.render``); the corpus tag travels with every number (rule 2); what the corpus
does not cover is printed next to the results (rule 3 of 3.1 and section 1.7); failures are named
with evidence (rule 4, in ``NamedCase``); the two acceptance tables are two headings (rule 5);
modality is disclosed (rule 7); and the banned vocabulary is scanned (rule 9).

The banned-word scan runs over THIS REPORT and nowhere else, unconditionally. An earlier design
scanned the whole documentation set, found 85 hits it could not adjudicate, and put the scan
behind a flag. A check nobody turns on is not a check. Scoped to the generated report it is
decidable, because a report is the one artefact whose every word this code wrote.

WITH ONE EXEMPTION, found by the scan refusing its own first report. Section 6's "licenses" and
"does not license" cells are quoted verbatim, and two of them use words rule 9 bans: M9's cell
says "any private entity" and M10's says "anonymous asset URLs are protected. They are not."
Rule 9 bans those words as CAPABILITY CLAIMS, and the "does not license" column is the
anti-claim column: scanning it would forbid the report from saying that something is NOT
guaranteed, which inverts the rule it is enforcing. So the quoted cells are marked as quoted and
excluded, and the scan covers every word this harness composes. The exemption is auditable
because ``tests/test_evaluation.py`` pins the quoted text to section 6 verbatim, so nothing can
be smuggled through the exemption without failing that.
"""

from __future__ import annotations

import re
from typing import Final

from exulanica.evaluation.counts import Count, Sample, render
from exulanica.evaluation.metrics import METRICS, Component

__all__ = ["BANNED", "banned_words_in", "quoted_from_the_methodology", "render_report"]

#: Section 3.1 rule 9, verbatim, plus invariant 10's storage vocabulary, which rule 9 does not
#: contain and which is banned for a different reason: the platform supports no Object Lock, no
#: Legal Hold and no write-once retention, so those words are an overclaim about a property
#: rather than about a capability. Two lists, one scan.
BANNED: Final[tuple[str, ...]] = (
    "state of the art",
    "high accuracy",
    "reliable",
    "production ready",
    "solves",
    "understands",
    "private",
    "on-device",
    "end-to-end encrypted",
    "anonymous",
    "gdpr compliant",
    "fully deleted",
    "secure",
    "immutable",
    "worm",
    "tamper-proof",
    "regulatory-compliant",
)

_ALLOWED: Final = ("on OGC-1", "we measured", "we did not test", "we do not know")


def banned_words_in(text: str) -> list[str]:
    """Every banned term the report uses, as whole words."""
    lowered = text.lower()
    return [
        term
        for term in BANNED
        if re.search(rf"(?<![a-z0-9-]){re.escape(term)}(?![a-z0-9])", lowered)
    ]


def _section(
    components: list[tuple[Component, Count | Sample | None]],
    *,
    synthetic: bool,
    corpus_tag: str,
    blocked: dict[str, str],
) -> str:
    lines: list[str] = []
    for component, result in components:
        lines.append(f"\n  {component.metric} {component.key}: {component.name}")
        if component.bar is not None:
            lines.append(f"    target: {component.bar}")
        if result is None:
            # A reason discovered at run time beats the static one, because it describes this
            # corpus rather than the general case.
            reason = blocked.get(f"{component.metric}.{component.key}") or component.blocked_on
            lines.append(f"    NOT MEASURED: {reason}")
        else:
            lines.append(f"    {render(result, synthetic=synthetic, corpus_tag=corpus_tag)}")
        if component.licenses:
            # A row that did not run licenses NOTHING, and the tense has to say so. The cell is
            # section 6's statement of what a RESULT would license, and printed flat under a
            # "NOT MEASURED" line M9's reads "No external lookup occurred ... across the tested
            # negatives" beside a row where no negative was ever probed. That is the sentence
            # this harness exists to refuse, so an unmeasured row prints it in the conditional.
            if result is None:
                lines.append(
                    "    licenses NOTHING, because it did not run. What a result would have "
                    f"licensed, quoted from section 6: {component.licenses}"
                )
            else:
                lines.append(f"    licenses, quoted from section 6: {component.licenses}")
        if component.withholds:
            lines.append(f"    does NOT license, quoted from section 6: {component.withholds}")
    return "\n".join(lines)


def quoted_from_the_methodology() -> tuple[str, ...]:
    """Every verbatim cell the report reproduces, which is what the scan steps over.

    Returned rather than inlined so a test can assert it is exactly the section 6 cells and
    nothing else. An exemption nobody can enumerate is a hole.
    """
    return tuple(
        text
        for component in METRICS
        for text in (component.licenses, component.withholds, component.bar)
        if text
    )


def render_report(
    results: dict[str, Count | Sample | None],
    *,
    corpus_tag: str,
    corpus_version: str,
    manifest_sha256: str,
    synthetic: bool,
    disclosure: str,
    frames: int,
    git_commit: str,
    blocked: dict[str, str] | None = None,
    coverage: tuple[str, ...] = (),
) -> str:
    """The whole report. Every metric appears whether or not it was measured.

    Every metric is listed because a short report reads as a clean one. A metric that could not
    run says what stopped it, in the same table as the ones that did, so the reader counts what
    is missing rather than inferring it from a gap.

    ``coverage`` is the measured half of "what is not covered", from
    :func:`exulanica.evaluation.coverage.what_the_corpus_cannot_support`. The sentences below it in
    this function are true of any corpus this harness can read; the ones passed in are true of
    the workspace that was actually measured, and they are separated from the fixed text rather
    than blended into it so a reader can tell which is which. It defaults to empty so a caller
    testing the rendering rules does not have to fabricate a coverage claim.
    """
    blocked = blocked or {}
    by_key = {f"{c.metric}.{c.key}": c for c in METRICS}
    for key, result in results.items():
        if key not in by_key:
            raise ValueError(f"unknown evaluation component: {key}")
        if result is not None and (by_key[key].blocked_on or blocked.get(key)):
            raise ValueError(f"blocked component cannot publish a number: {key}")
    paired = [(by_key[key], results.get(key)) for key in by_key]
    enforced = [(c, r) for c, r in paired if c.kind == "enforced"]
    learned = [(c, r) for c, r in paired if c.kind == "learned"]
    other = [(c, r) for c, r in paired if c.kind == "unclassified"]

    measured = sum(1 for _c, r in paired if r is not None)
    head = f"""Exulanica evaluation report

corpus            {corpus_tag}, {corpus_version}
manifest sha256   {manifest_sha256}
frames            {frames}
commit            {git_commit}
components        {measured} measured of {len(paired)}; the rest say what stopped them

WHAT THIS CORPUS IS, and read it before any number below.

  {disclosure}
"""
    if synthetic:
        head += """
  THIS IS A SYNTHETIC CORPUS. Every frame is a render of a geometric arrangement. Nothing about
  identity, clustering or reconstruction is real on it, and no number computed here is evidence
  about photographs. No interval is printed against it, because an interval describes a sample
  drawn from a population and this is not one: it describes how faithfully a generator does what
  it was written to do.
"""
    head += """
  MODALITY. The corpus is still images with no audio and no video, so nothing here tests any
  speech-dependent or motion-dependent behaviour, and no result may be read as though it did.

  WHAT IS NOT COVERED. There are no people in this corpus. Synthetic manifest-derived gold
  questions exercise declared plans and the deterministic answer renderer. They do not measure
  live-model planning, factual support, abstention rates or latency. Object appearance queries
  depend on detector captions and an explicit manifest vocabulary; a miss is a pipeline result,
  not an isolated SQL defect. Place questions need human-confirmed entity IDs. No rendering
  number is measured by this harness.
"""
    if coverage:
        head += "\n  MEASURED AGAINST THIS WORKSPACE, rather than stated in general:\n\n"
        head += "".join(f"  {line}\n" for line in coverage)
    body = (
        head
        + "\n\nDETERMINISTIC INVARIANTS, enforced by code, expected exact"
        + _section(enforced, synthetic=synthetic, corpus_tag=corpus_tag, blocked=blocked)
        + "\n\n\nLEARNED MEASUREMENTS, never capability claims"
        + _section(learned, synthetic=synthetic, corpus_tag=corpus_tag, blocked=blocked)
        + "\n\n\nPLACED IN NEITHER ACCEPTANCE TABLE by the methodology"
        + _section(other, synthetic=synthetic, corpus_tag=corpus_tag, blocked=blocked)
        + "\n"
    )

    composed = body
    for quotation in quoted_from_the_methodology():
        composed = composed.replace(quotation, "")
    used = banned_words_in(composed)
    if used:
        raise ValueError(
            f"the report uses {used}, which section 3.1 rule 9 and invariant 10 forbid. "
            f"Allowed instead: {list(_ALLOWED)}."
        )
    return body
