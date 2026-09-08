# Shared screening currency

Migration 0040 separates a historical review from permission for a new geometry operation.
It does not rewrite dated screenings or apply to retained public. Personal-data activation still
requires the separate asset-read work described below.

## Approved scope and exact inputs

This work starts from integrated `38625d2`, after manual review and personal admission. The
orchestrator approved adding only `ingest/person_state.py` (its current-state reader and necessary
imports/docstring) to the original writable set. The existing reader ignored consent expiry and
future effective times and folded overlapping scopes differently from SQL. The producer now reads
one database-resolved snapshot through `ingest/spine/privacy.py`. `CaptureRegionState` and the
existing mask digest formats remain unchanged. The offline fold, pipeline, stage registry and
other producer files are unchanged.

`current_privacy_inputs` takes the workspace privacy lock, then evaluates at one database clock
instant. Its snapshot names the workspace, capture, exact original bytes, latest edit digest for
**every** region key (including deleted regions), and each live region's key, silhouette, subject,
resolved state, naming permission and applicable consent digests. Edit identities distinguish a
new review input even if its pixels are identical; keeping deleted edit identities prevents an
old empty-inventory review from reviving after add/delete. Capture absence is not an empty review.

Consent evaluation preserves SQL's region-specific-over-subject-wide precedence, then sequence,
with receipt digest as a deterministic tie breaker. Future decisions are excluded. Expired
receipts no longer hold; an older still-valid applicable receipt may hold under this established
resolver. Withdrawals remain terminal even if another grant follows. All scopes use the same
instant. A future effective time or expiry can change the snapshot without a database write.
No evaluation timestamp is included in the binding, so unchanged effective inputs remain reusable.

## How a mask proves its recorded inputs

The mask stage already paints the supplied outlines using supplied resolved states and records
an input digest over the sorted hashes of:

1. The intake artifact's content (the canonical EXIF/probe record, not the source pixels).
2. `person-region-set/v1`: capture ID, original source hash and sorted live keys/silhouettes.
3. `person-consent-state/v1`: capture ID, source hash and sorted region state/masked/naming values.

0040 recomputes these existing digests from the shared snapshot, with canonical integral JSON,
and matches the artifact's recorded `input_digest`, exact source, current stage version and
parameters. The intake artifact must also match its current stage definition. The mask must be
complete, unpurged and not marked for repair. An UPDATE cannot relabel an existing mask's lineage
or replace its non-null content hash. Purge can still clear bytes.

This is recorded producer lineage, not a cryptographic proof of rasterization against a malicious
database writer who can fabricate an entirely new artifact row. The executed rehearsal uses the
real producer and store. No insertion trigger stamps current inputs onto work computed earlier.
SQL checks database records; store readers remain responsible for existence and digest checks of
actual bytes. Neither newest creation time nor the existence of any mask establishes currency.

New screening canonical records include the exact input snapshot and, when masking is required,
the exact existing mask ID/content hash. The SQL predicate compares both bindings with current
inputs and artifact lineage. A review recorded without its mask cannot activate when a mask later
appears. Rebuild alone cannot revive a review for changed inputs: explicitly re-screen. A same-input
retry reuses the existing mask and review; a same-pixel new edit can reuse the mask but needs a new
review. Mask and review currency are intentionally different comparisons.

Legacy records lacking the new binding remain historical facts but do not authorize new geometry.
There is no policy version bump invalidating detection receipts: detection-only remains a separate
observation purpose. Human screening must cover exactly the current region keys and states; a
no-person review binds an empty inventory. Synthetic exemption requires no live person regions.
Withdrawal, capture tombstones and authorization/screening expiry still refuse geometry.

## SQL consumers and operation boundaries

The shared predicate reaches frontier preflight and demonstration selection, scene admission,
admission-member/scene policy triggers from 0029, point-map selection/exact resolution in
`ingest/spine/artifacts.py`, and training input selection in `world_package/training_inputs.py`.
No frontier caller change was needed. The Python guard delegates mask currency to the same SQL
contract. Scene mask declaration and exact resolution also check current lineage and refuse a
missing declaration when a member now requires masking.

The point-map trigger checks both the screening and the named masked source. It also checks a
named mask when current inputs no longer require masking, and covers relevant artifact UPDATEs
as well as INSERTs. Clearing historical content during purge is not a new geometry operation and
remains possible. Point-map acceptance tests use placeholder geometry content and exercise the
actual SQL write boundary; they perform no depth inference.

## Concurrency contract and tradeoffs

Person-region writes, consent writes, screening insertion and permission checks take the same
transaction advisory lock per workspace. Subject-wide consent therefore cannot bypass a
capture-only lock. The predicate takes a fresh snapshot after acquiring the lock. READ COMMITTED
is required; repeatable-read/serializable transaction snapshots are refused with serialization
failure so the caller can retry in a supported transaction. Time-dependent consent is evaluated
**after** waiting for the lock. The linearization point is the permission check, not eventual
commit or later asset delivery; a permission does not promise that consent will never expire.

The producer's read lock need not span image computation. Its artifact records the inputs actually
used, and subsequent admission/write checks reject it if those inputs became obsolete. The
workspace lock is deliberately coarse and can serialize otherwise independent captures. This
cost buys one checkable policy within the approved scope. Tombstone/purge and asset-delivery
transactions retain their existing contracts; no global read-versus-deletion lock guarantee is made.

## Executed evidence and remaining verification

The recorder executes generated labelled media through real PostgreSQL and the real mask stage.
The end-to-end sequence covers authority, empty review, region addition, masking/review, outline
edit and blocked review, direct SQL refusal, actual frontier preflight, demonstration selection,
scene admission and point-map refusal, followed by rebuild/re-screen/retry success. It verifies
that the old receipt digest is unchanged. Full frontier preflight supplies no signing key; its
screening check passes or fails as expected while signing remains unavailable.

Additional cases cover expired and future grants, region-specific precedence, unknown subject,
consent changes, expiry without writes, withdrawal, region deletion, cross-workspace requests,
legacy receipts, premature unbound reviews, immutable mask lineage, geometry UPDATE, missing/stale
worker declarations, unchanged inputs and exact evaluation boundaries. Two-connection tests
exercise region commit and expiry while a predicate waits; stale transaction snapshots refuse.

Executed negative controls remove review-input binding, mask-input digest comparison and consent
expiry filtering in subprocess memory. Every killed claim requires its exact selector's `FAILED`
line. These are shared SQL policy mutants. The earlier personal-admission baseline is still an
observed SQL defect, and its earlier command-local mutant proved only that local caller's guard.
Neither earlier record demonstrated a stale depth write or disclosure.

Generate fresh evidence without replacing accepted records:

```sh
uv run python scripts/record_screening_currency_evidence.py \
  --output docs/evaluation/NEW-screening-currency.json \
  --artifacts docs/evaluation/artifacts/NEW-screening-currency \
  --predecessor docs/evaluation/2026-09-08-command-personal-admission-flow.json
```

Records have exactly `profile`, `record`, `record_sha256`, a canonical SHA-256, no floats, explicit
predecessor and digest/size-bound artifact paths. The test harness removes isolated schemas.
Full backend/Ruff/import/web gates must be bound to a frozen commit in the final gate record.

## Separate remaining activation dependency: asset-read currency

`api/routes/evidence.py` still chooses masked-source bytes by stage version and creation time,
without matching current mask inputs. Original evidence access has separate exact-byte semantics.
`graph/geometry.py` reads point-map bytes with live-source/purge/withdrawal checks, and
`graph/scene_geometry.py` checks scene/job/gate/purge/withdrawal state when serving trained assets.
Those are not a universal current-screening/currency contract for already-produced assets.
Read-time mask and geometry currency, and read-versus-withdrawal races, require separately scoped
implementation and tests before activation. This brief does not implement all media delivery or
World Read release policy, and admission-only evidence is not a global disclosure guarantee.
