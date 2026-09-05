# ADR-0018: Contextual proposals may organize as explicit guesses

- Status: Accepted
- Date: 2026-09-05
- Deciders: Exulanica build, under the unblocked backend program

## Invariant

The automatic identity producer writes proposals using only `context_place`,
`context_cooccurrence` and the permitted but currently dormant `user_text` vocabulary.
A unique highest-scoring entity may acquire an `auto_provisional` link at 800 milli-units.
It cannot acquire a `confirmed` link: that still requires a human and `user_confirm` at the
database boundary. The explicit `INCLUDE_PROPOSALS` Selection scope may widen retrieval on
that guess, and every packet built under that scope remains non-citable.

## Rationale

The former proposer deliberately wrote no links. The new program explicitly authorizes
organizational guesses so that the existing proposal-aware Selection and human decision paths
can operate on production rows. The threshold is an unvalidated organizational policy, not a
probability or an accuracy measurement. Place and co-occurrence each contribute 400 milli-units;
one alone remains below the 500 milli-unit surface threshold. Multiple exemplars of the same
entity contribute one best candidate, not multiple votes. A tied best score does not create an
automatic link, and an entity already confirmed in the candidate's capture is excluded.

`calibrated_p` remains NULL and `calibration` has no new writer. There are no observed user
calibration bins and the schema does not yet express per-user calibration provenance. Creating
empirical frequencies from synthetic fixtures would assert evidence we do not have. A-26's
minimum sample policy remains unvalidated. Proposal raw scores remain internal storage values:
neither graph rows nor answer packets gain a score field. The proposal's basis records the
weights, thresholds, extractor version and the explicit absence of calibration. `user_text`
stays dormant because no caller passes annotation text; no proposal quality claim includes it.

## Canonical representation

`PROPOSER_PARAMS` version 2 binds the arithmetic through `params_digest`. Proposal `basis`
contains sorted `modalities`, `extractor_versions`, integer `weights_milli`, integer
`thresholds_milli` and the calibration-unavailable reason. `basis_digest` retains the existing
modality-plus-extractor-version encoding. The proposal outcome remains `surfaced` even when a
provisional link is written, because it still awaits a human answer; `auto_provisional` is the
link's state, with method `context_weighted_sum` and no deciding user.

The production `identity_match_context` derivative is the confirmed exemplar index consumed by
the proposer. Its `exulanica.identity-match-context/v1` payload has sorted anchors naming source
entity, resolved entity, occurrence, capture, class, detector label and user-stated display name.
It records the corresponding entity, occurrence and capture dependency keys. Merges retain the
source exemplars while resolving them to the survivor. Capture, interval and entity withdrawals
are excluded when the index is rebuilt. Current context signals are read independently rather
than persisting raw floating-point geography in the canonical index.

The first derivative identity is a workspace-scoped UUID5 over the canonical payload digest.
An unchanged live index is reused. A stale index stays stale; explicitly rebuilding identical
content after an undo creates a new historical generation. Payload bytes and dependencies can
be deterministic while refresh-history identifiers and timestamps differ. Identity writes and
index refreshes use the same workspace transaction lock. Model outputs are not regenerated.

## Compatibility impact

No schema migration, API signature, browser model or export shape changes. Proposals retain their
existing outcomes and scores remain absent from graph responses. `ProposalReport` gains the
created provisional link ids. Existing emit keys are unchanged: previously recorded proposals
are not rewritten or retroactively linked under the new arithmetic. They remain available for
a human decision. The former no-link test is superseded by the actual widened
Selection and non-citable packet contract. Confirm, reject and undo use their existing state
transitions: confirmation revokes the guess, rejection rejects it, and undo restores `proposed`.
The derivative gives the existing dependency invalidator a real production consumer.
Existing proposal emit keys remain unchanged: old questions stay human-actionable, and are
neither rewritten nor retroactively linked when the arithmetic changes. New proposal rows use
the new organizational policy.

## Failure behaviour

No corroborating modality produces no proposal. A single contextual modality is recorded but
not surfaced. Rejection memory suppresses the pair on the observed modality set. A tie produces
questions without an automatic link. Proposal and link writes share one transaction; a failed
link write leaves no partial new question. The database refuses automatic confirmation and
withdrawn evidence. A derivative marked stale on arrival is refused by its consumer; refresh
never silently clears its stale bit. Calibration stays absent until a separate observed-data
decision can justify it. P-1 remains unanswered.

## Affected surfaces and verification

- Schema: existing `match_proposal`, `entity_link`, `derived_artifact`; no migrations.
- Producer: `identity/proposer.py`, `identity/match_context.py`, `identity/repository.py`.
- Decisions: existing confirm, reject, undo and invalidation; module description updated.
- APIs and browser: existing Selection, packet, graph and pending-proposal readers consume the
  newly reachable states; no new wire fields or raw score exposure.
- Deletion: dependency keys carry source captures and both source/resolved entities; stale rows
  remain historical records and are never admitted as current proposer input.
- Tests: `tests/test_match_proposals.py`, existing identity, Selection and ingest preconditions.
  Executed negative controls and exact outcomes are retained in the program evaluation record.
