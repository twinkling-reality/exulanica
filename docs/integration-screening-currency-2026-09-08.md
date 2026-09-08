# Shared screening currency integration, 2026-09-08

Follow-up: `integration-asset-read-currency-2026-09-08.md` records the subsequent asset-read
integration. The report below preserves its original verified state and then-open dependencies.

The screening-currency branch is integrated on main. Independent gates at `53039d4` passed:
2098 backend tests, 3 skipped; 876 web tests; Ruff, all four import contracts, typecheck and
frontend boundaries. Locked pose and reconstruction extras were installed before the suite.
The six patches from owner tip `7532a32` were unchanged when rebased onto scope approvals at
`85c5047`. No feature code was implemented by the orchestrator.

`evaluation/2026-09-08-screening-currency-integration.json` binds the seven independent
environment/gate logs and follows the owner's final verification record. All three owner
envelopes and 133 artifact/source bindings were independently checked; historical source
bindings were checked at their recorded heads. The five complete-record mutant logs each
contain the named selector's own FAILED line. Subsequent integration edits are docs/evidence.

## Corrections and executed scope

The initial brief assumed the shared admission predicate could be corrected without touching
mask production. The producer actually dropped expiry, included future-effective consent and
used a different precedence order. The approved person_state.py extension reads the shared
current policy. Database-backed producer cases now cover the expired grant that first exposed
the mismatch. The original in-memory probe alone was not acceptance evidence.

The admission command discarded the exact outline, subject and naming state obtained for review.
Its approved call-site extension preserves those rows, so strict screening rejects missing or
stale claimed inputs instead of substituting a newer state that the person did not review.

A two-writer baseline also demonstrated duplicate subject-consent sequence allocation. The new
workspace locking contract rejects the conflicting allocation with retryable 40001 while
preserving exact receipt replay. Ambiguous legacy chains refuse rather than choosing by hash.
Permission is evaluated after locking under READ COMMITTED; this does not authorize later delivery
indefinitely or establish read-versus-withdrawal ordering.

An intermediate green candidate selected historical masks even when no current mask was needed.
The final selection uses current requirements, accepts an actually matching mask, and omits
unneeded obsolete masks after deletion or a likeness grant. An explicitly queued artifact still
has to match; selecting a different artifact does not legitimize the queued bytes.

Migration 0040 binds geometry screening to exact current privacy inputs and validates actual mask
producer digests at SQL admission/write boundaries. Generated-media tests execute the real mask,
review/rescreen commands and shared consumers. Point-map writes use placeholder payloads to test
the SQL boundary; they do not demonstrate depth inference. Frontier preflight exercised stored
source screenings but was not a complete signed personal frontier run.

Initial full-suite failures and the subsequent mask-selection correction remain in the evidence.
Fixture changes prepare current detection/review permission without removing masking, collision,
no-person, training-consent or withdrawal assertions. Accepted historical records were preserved;
the documented narrow replacement applied only to an unpublished candidate.

## Deployment and next work

After independent gates, a read-only retained-public snapshot still showed migration 0038,
284 captures, 880 artifacts, 5 scenes and 0 person regions. Nothing was migrated there. Current
person-state readers now require 0040, so deploying this code against that database requires an
explicitly authorized 0039/0040 migration. Code integration is not deployment readiness.

Asset-read currency and read-versus-withdrawal remain activation dependencies. The masked-photo
route still selects a stored derivative by version/time, and geometry readers need their own
current-permission and actual-lineage checks. Admission tests do not prove a disclosure guarantee.
The queued next brief is `briefs/2026-09-08-asset-read-currency.md`, ahead of World Read recipient
evidence. No new task has been dispatched for it.

No real personal-media run, hosted model, GPU spend, public migration or push was performed.
Main remains unpushed. Off-device Git backup is still the immediate operator action, separate
from a tested database and artifact recovery plan.
