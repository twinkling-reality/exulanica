"""Proposing that an unnamed occurrence is somebody the account holder has already named.

This is the second rung of identity. The first is the account holder saying who somebody is, and
that stays the only thing that creates an entity. What this adds is a question: given a person
already named in one photograph, is this detection in another photograph the same person?

**It proposes; a unique best contextual match may also organize as a guess.** At the recorded
threshold it writes ``auto_provisional``, never ``confirmed``. The Selection's explicit
``INCLUDE_PROPOSALS`` scope may include that link, but its packet remains non-citable. These
unvalidated weights are a layout/filtering policy, not a calibrated probability or a factual
claim. Human confirmation is the only route to a confirmed link (ADR-0018).

**It is not biometric and cannot become so from here.** Face, voice and gait have no producer.
The decision that would permit a face embedding belongs to a human, is recorded as open in
``privacy-consent-threat-model.md`` section 10, and nothing here settles it. The three signals
used are context: where, alongside what, and what a person wrote. See ``signals.py``.

**A detector label is a hard constraint, not a signal.** Twenty-seven captures containing a red
cube do not contain the same red cube. Label equality decides which pairs are worth comparing;
what corroborates them is context, and a pair with no corroborating modality is not proposed at
all rather than proposed weakly.

Home. Not ``exulanica.ingest``, whose own package docstring says "Nothing here can create an entity
or a link", and whose derivatives are keyed per photograph while a proposal is a function of the
whole corpus and of user decisions. Not ``exulanica.api``, where routes decide nothing. Here, where
the occurrence key, the basis digest and rejection memory already live.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.identity.keys import PRODUCIBLE_MODALITIES, basis_digest, normalise_modalities
from exulanica.identity.match_context import refresh_match_context
from exulanica.identity.repository import IdentityRepository
from exulanica.identity.signals import CaptureContext, ContextSignals, corroborating_modalities

__all__ = ["PROPOSER_PARAMS", "ProposalReport", "propose_matches"]

OCCURRENCE_ENTITY: Final = "occurrence_entity"

#: UNVALIDATED DEFAULTS, in parameters rather than in constants precisely because the corpus that
#: would validate them does not exist: there is no labelled cross-capture pair set and no
#: evaluation has run. An edit moves ``params_digest``, which lands in every basis and therefore
#: in every ``basis_digest``, so a later tuning pass is recorded on the rows it produced rather
#: than applied retroactively to rows produced under different arithmetic. The depth stage's
#: parameters carry the same warning for the same reason.
PROPOSER_PARAMS: Final[dict[str, Any]] = {
    "version": 2,
    # The same figure scene grouping uses for its own clustering, so the two agree about what
    # "the same place" means rather than disagreeing by a number nobody chose.
    "max_place_distance_m": 250,
    "min_shared_labels": 2,
    # Milli-units throughout: `canonical_json` refuses a float, and a digest input has to
    # serialise identically in every implementation forever.
    "weight_context_place": 400,
    "weight_context_cooccurrence": 400,
    "weight_user_text": 800,
    # Above the weight of ONE context signal and below the weight of two, so a single GPS
    # coincidence or a single shared trip is recorded and not asked about, and two independent
    # signals agreeing is what earns a question. At 300 this sat below the smallest score any
    # corroborated pair can have, so `dropped` was unreachable and the threshold decided nothing.
    "surface_threshold_milli": 500,
    # An explicit organizational guess. It is never a factual-confidence threshold.
    "auto_provisional_threshold_milli": 800,
    "algorithm": "corroborating_modalities_weighted_sum",
}

_WEIGHTS: Final = {
    "context_place": "weight_context_place",
    "context_cooccurrence": "weight_context_cooccurrence",
    "user_text": "weight_user_text",
}


def params_digest() -> str:
    """The arithmetic a proposal was produced under, as a short hex digest.

    Recorded on the row rather than left in git, so a proposal states which weights produced it.
    """
    return sha256_of_canonical(PROPOSER_PARAMS).hex()[:16]


@dataclass(frozen=True, slots=True)
class Anchor:
    """A named entity, and one capture it is confirmed to appear in."""

    entity_id: uuid.UUID
    display_name: str | None
    occurrence_class: str
    label: str | None
    context: CaptureContext


@dataclass(frozen=True, slots=True)
class Candidate:
    """An occurrence linked to nobody, which is what a question can be asked about."""

    occurrence_id: uuid.UUID
    identity_key: bytes
    occurrence_class: str
    label: str | None
    context: CaptureContext


@dataclass
class ProposalReport:
    """What one pass decided, in the three states a pass can leave a pair in."""

    anchors: int = 0
    candidates: int = 0
    surfaced: list[uuid.UUID] = field(default_factory=list)
    dropped: list[uuid.UUID] = field(default_factory=list)
    suppressed: list[uuid.UUID] = field(default_factory=list)
    auto_provisional: list[uuid.UUID] = field(default_factory=list)
    #: Pairs that produced no corroborating modality at all and were therefore never written.
    #: Counted rather than stored: a row asserting "nothing suggested this" would be a row per
    #: pair of everything in the library.
    uncorroborated: int = 0

    @property
    def written(self) -> int:
        return len(self.surfaced) + len(self.dropped) + len(self.suppressed)


def _label_of(quality: dict[str, Any] | None) -> str | None:
    return (quality or {}).get("label")


def _score_milli(modalities: Sequence[str]) -> int:
    return sum(int(PROPOSER_PARAMS[_WEIGHTS[name]]) for name in modalities if name in _WEIGHTS)


def propose_matches(
    repository: IdentityRepository,
    signals: ContextSignals,
    *,
    run_id: uuid.UUID,
) -> ProposalReport:
    """One whole-corpus pass. Safe to run repeatedly: a re-run asks no question twice.

    ``run_id`` is a parameter rather than something opened here. ``match_proposal.produced_by_run``
    references ``pipeline_run``, and ``Ledger`` lives in ``exulanica.ingest``, which this layer may
    not import. The caller decides what a run is, which keeps the layer direction honest and lets
    the ingest command hand down the run it already has.
    """
    report = ProposalReport()
    anchors = _read_anchors(repository, signals)
    candidates = _read_candidates(repository, signals)
    report.anchors = len(anchors)
    report.candidates = len(candidates)
    if not anchors or not candidates:
        return report

    for candidate in candidates:
        best_by_entity: dict[uuid.UUID, tuple[int, tuple[str, ...], Anchor]] = {}
        already_present = {a.entity_id for a in anchors
                           if a.context.capture_id == candidate.context.capture_id}
        for anchor in anchors:
            # Hard constraints, before anything is scored. Same class, same detector label, and
            # never a candidate in a capture the anchor is already confirmed in: two person
            # occurrences in one photograph are two people.
            if anchor.occurrence_class != candidate.occurrence_class:
                continue
            if anchor.label != candidate.label:
                continue
            if anchor.entity_id in already_present:
                continue
            # `never_same` is deliberately not consulted. It constrains an entity against an
            # entity, and a candidate here is by construction linked to no entity at all, so
            # there is no pair for it to speak about. It becomes relevant to a merge, not to
            # this.

            modalities = corroborating_modalities(
                anchor.context,
                candidate.context,
                join_label=candidate.label,
                max_place_distance_m=float(PROPOSER_PARAMS["max_place_distance_m"]),
                min_shared_labels=int(PROPOSER_PARAMS["min_shared_labels"]),
                display_name=anchor.display_name,
            )
            producible = tuple(m for m in modalities if m in PRODUCIBLE_MODALITIES)
            if not producible:
                # No signal corroborates this pair, so there is no question to ask. Counted
                # rather than written: a row per uncorroborated pair is a row per pair of
                # everything in the library, and it would assert nothing.
                report.uncorroborated += 1
                continue
            scored_anchor = (_score_milli(producible), producible, anchor)
            previous = best_by_entity.get(anchor.entity_id)
            if previous is None or scored_anchor[0] > previous[0]:
                best_by_entity[anchor.entity_id] = scored_anchor

        # Best first, and the entity id breaks a tie so two runs over unchanged data produce the
        # same ranks. Ranking is within one occurrence's candidate set and means nothing across
        # occurrences; the index on (workspace, occurrence, rank) says the same thing.
        scored = list(best_by_entity.values())
        scored.sort(key=lambda item: (-item[0], str(item[2].entity_id)))
        for rank, (score_milli, modalities, anchor) in enumerate(scored):
            _write_proposal(
                repository,
                report,
                candidate=candidate,
                anchor=anchor,
                modalities=modalities,
                score_milli=score_milli,
                rank=rank,
                run_id=run_id,
                unique_best=rank == 0 and (len(scored) == 1 or score_milli > scored[1][0]),
            )
    return report


def _write_proposal(
    repository: IdentityRepository,
    report: ProposalReport,
    *,
    candidate: Candidate,
    anchor: Anchor,
    modalities: tuple[str, ...],
    score_milli: int,
    rank: int,
    run_id: uuid.UUID,
    unique_best: bool,
) -> None:
    normalised = normalise_modalities(modalities)
    basis = {
        "modalities": list(normalised),
        "weights_milli": {name: PROPOSER_PARAMS[_WEIGHTS[name]] for name in normalised},
        "thresholds_milli": {
            "surface": PROPOSER_PARAMS["surface_threshold_milli"],
            "auto_provisional": PROPOSER_PARAMS["auto_provisional_threshold_milli"],
        },
        "calibration": "unavailable_no_observed_user_calibration",
        "extractor_versions": {
            "context_signals": str(PROPOSER_PARAMS["version"]),
            "params": params_digest(),
        },
    }
    digest = basis_digest(normalised, basis["extractor_versions"])

    suppressed, new_modality = repository.rejections.covering(
        scope=OCCURRENCE_ENTITY,
        key_a=candidate.identity_key,
        key_b=anchor.entity_id.bytes,
        modalities=normalised,
    )
    if suppressed:
        outcome = "suppressed_by_rejection"
    elif score_milli >= int(PROPOSER_PARAMS["surface_threshold_milli"]):
        outcome = "surfaced"
    else:
        outcome = "dropped"

    # Keyed on the QUESTION, not on the answer. The identity key rather than the occurrence id,
    # for the same reason rejection memory is: a detector re-run mints a new occurrence id for
    # the same thing in the same photograph and would otherwise mint a duplicate question. The
    # modality set rather than the basis digest, because a re-weighting or a version bump moves
    # the digest and not the set, and a re-weighting is not a new question. Score and rank are
    # absent for the same reason.
    emit_key = (
        f"match:{candidate.identity_key.hex()}:{anchor.entity_id}:{'+'.join(normalised)}"
    )
    with repository.transaction():
        proposal_id = repository.proposals.record(
            occurrence_id=candidate.occurrence_id,
            entity_id=anchor.entity_id,
            score=score_milli / 1000,
            rank=rank,
            basis_digest=digest,
            basis=basis,
            outcome=outcome,
            produced_by_run=run_id,
            emit_key=emit_key,
            new_modality=new_modality,
        )
        if proposal_id is None:
            return
        {"surfaced": report.surfaced, "dropped": report.dropped}.get(
            outcome, report.suppressed
        ).append(proposal_id)
        if (outcome == "surfaced" and unique_best
                and score_milli >= int(PROPOSER_PARAMS["auto_provisional_threshold_milli"])):
            # The proposal stays surfaced: an organizational guess still awaits a human answer.
            report.auto_provisional.append(repository.links.insert(
                occurrence_id=candidate.occurrence_id, entity_id=anchor.entity_id,
                state="auto_provisional", method="context_weighted_sum", basis_digest=digest,
                score=score_milli / 1000,
            ))


def _read_anchors(
    repository: IdentityRepository, signals: ContextSignals
) -> list[Anchor]:
    """Every named entity, once per capture it is CONFIRMED in.

    A confirmed link and not merely a display name: an entity nobody has confirmed anywhere has
    no capture to compare against, so it can corroborate nothing.
    """
    rows = refresh_match_context(repository)["anchors"]
    anchors: list[Anchor] = []
    for row in rows:
        context = signals.of(uuid.UUID(row["capture_id"]))
        if context is None:
            continue
        anchors.append(
            Anchor(
                entity_id=uuid.UUID(row["entity_id"]),
                display_name=row["display_name"],
                occurrence_class=row["class"],
                label=row["label"],
                context=context,
            )
        )
    return anchors


def _read_candidates(
    repository: IdentityRepository, signals: ContextSignals
) -> list[Candidate]:
    """Every occurrence linked to nobody at all, in any state.

    ``proposed`` and ``auto_provisional`` count as linked here. An occurrence already carrying an
    open link is already the subject of a question, and asking a second one about it would be two
    questions about one detection.
    """
    rows = repository.connection.execute(
        "select o.occurrence_id, o.identity_key, o.class, o.quality, o.capture_id "
        "from occurrence o "
        "where o.workspace_id = %s "
        "  and not tombstone_blocks_any_span(o.workspace_id, o.span_ids) "
        "  and not exists (select 1 from entity_link l "
        "                   where l.occurrence_id = o.occurrence_id "
        "                     and l.state in ('confirmed', 'auto_provisional', 'proposed')) "
        "order by o.occurrence_id",
        (repository.workspace_id,),
    ).fetchall()
    candidates: list[Candidate] = []
    for row in rows:
        context = signals.of(row["capture_id"])
        if context is None:
            continue
        candidates.append(
            Candidate(
                occurrence_id=row["occurrence_id"],
                identity_key=bytes(row["identity_key"]),
                occurrence_class=row["class"],
                label=_label_of(row["quality"]),
                context=context,
            )
        )
    return candidates
