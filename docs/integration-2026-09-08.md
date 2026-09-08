# Exulanica integration, 2026-09-08

This is an integration audit, not an implementation ticket. Feature work belongs to the three
branches below. The integration owner inspected their changes, commit messages, executed
negative controls and retained evidence, then rebased and ran each branch's full gates before
landing it. No feature code was written during integration.

## Landing order and verification

| Order | Branch | Reported frozen tip | Rebased tip | Independent backend gate | Independent web gate |
| --- | --- | --- | --- | --- | --- |
| B | `phase-7b-training-consent` | `23ed18f` | `23ed18f` | 2019 passed, 3 skipped; 459.25 seconds | 852 passed |
| C | `frontier-run-and-read-bounds` | `17987c7` | `f10a014` | 2041 passed, 3 skipped; 402.27 seconds | 867 passed |
| A | `gpu-and-real-geometry` | `f456672` | `fb15c34` | 2058 passed, 3 skipped; 367.67 seconds | 867 passed |

B landed first so C's ordinary demonstration and clean-process verifier execute with the new
package profile and source-publication locks. A inherits both. Both rebases preserved every patch
unchanged, verified with `git range-diff`. B and C landed by fast-forward. While A's final suite
ran, main received `1fc91e2`, adding only `docs/goal-brief-2026-09-08-remaining-work.md`. A landed
with a merge commit to preserve that independent document. Comparing the merged tree with the
tested A tip shows exactly that one documentation file and no executable difference. No code
changed after the gate.

The [integration verification record](evaluation/2026-09-08-integration-verification.json)
retains all eighteen independent gate logs, their digests, the three tested heads, and the
post-gate documentation-only difference. It follows the retained GPU control record.

The gates are the complete backend suite against the permitted test database, Ruff, all four
import contracts, web typecheck, package boundaries and the complete web suite. Locked `pose`
and `reconstruction` extras were installed before integration testing. Earlier owner runs that
failed for missing dependencies are not counted as passing integration runs.

## Shared contracts and scope

- Migration 0039 adds B's training permission table. The three workspace RLS prose counts move
  from 65 to 66 and their live-schema assertion runs in the suite. No other changes were made
  in those three shared files. A needed no migration; 0040 remains unused.
- None of the three branches changes `STAGES`, `SCORED`, the public-route allowlist, router
  registration, import layers, route probes, or the spine module inventory. C's retained pipeline
  digest still equals the combined tree's digest.
- `web/packages/app/src/main.ts` was not changed. No implementation task was granted concurrent
  ownership of it.
- A received a narrow evidence-only scope extension for two new generated evaluation records.
  Existing evaluation records were not edited. B's existing count-only exception remained narrow.
- Commit messages are one-line imperatives without trailers. The added text was checked for
  prohibited em dash characters and authorship notices. Explicit paths are staged for integration.

## Evidence and limits

The training acceptance record is
[`2026-09-08-training-consent-acceptance.json`](evaluation/2026-09-08-training-consent-acceptance.json).
Integration verified its envelope, predecessor, all 26 bound artifacts, seven named mutant
failures, and both signed packages. The sample contains generated images and scripted pose and
training fixtures. Account-holder attestations do not independently authenticate subject consent
or licensor authority. Offline verification cannot discover later revocation or retrieve copies
already delivered. FR-11's two prospective licensees remain outstanding.

C's [`frontier readiness record`](evaluation/2026-09-08-frontier-readiness.json) establishes a
generated-input rehearsal and read bounds, not an authorized personal-corpus run. Three negative
controls were checked against their exact named failure lines and bound logs. The browser still
loads the whole graph and refuses partial answers. The retained bowl measurement is 97,633,587
canonical bytes whole versus 4,973,392 bytes for a 500-point page. Paging bounds the answer, not
server grouping work or the browser's eventual memory. No real production signing key was used.

A's [`retrospective bowl record`](evaluation/2026-09-08-bowl-retrospective-masked-geometry.json)
decoded one million Gaussians across 51 recovered cameras, with zero recorded person regions and
zero intersections. Integration verified its envelope and predecessor, and all five named
failures and source/log hashes in the linked
[`negative-control record`](evaluation/2026-09-08-gpu-geometry-negative-controls.json).
Zero over an empty region inventory does not establish masking effectiveness. Queue dispatch is
tested against real database claims with a scripted processor; real SSH/Docker dispatch, CUDA
training and fresh registry-pull savings remain unproved. No GPU was rented.

The blanket handoff claim that no test runs real COLMAP was stale. With the `pose` extra,
`tests/test_reconstruction_pycolmap_executor.py` executes the real library through the controller
on deterministic rendered rooms. Those four tests are included in the integration full suite.
This is not real-photo recovery, a cross-capture place alignment, or CUDA training.

## Deployment state

Retained `public` was independently read at migration 0038 with 284 captures, 880 artifacts,
5 scenes and zero person regions. Integration does not apply 0039 to that schema. An executed
read-only frontier preflight after B landed refused the live run and named pending 0039.
The generated rehearsal uses isolated schemas. The code and retained deployment therefore have
different migration maxima, deliberately stated rather than hidden by a green test suite.

Main began 20 commits ahead of the remote, whose tip was checked directly. No push is part of
this integration. Remote backup remains an operator action worth doing promptly.

## Next bounded brief: generated model and seam disclosure

Start one implementation task after this integration finishes. The three feature branches are
frozen; do not launch another wide parallel batch merely because their implementation slots are
free.

- Worktree: `../exulanica-generated-disclosure`.
- Branch: `codex/generated-tier-disclosure`, created from integrated main.
- Migration: none. Do not reserve a migration for a read/display change.
- Own: new `web/packages/presentation/src/generated-geometry.ts` and
  `web/packages/presentation/test/generated-geometry.test.ts`;
  `web/packages/presentation/src/index.ts`; `web/packages/app/src/ui/status.ts`;
  `web/packages/app/test/status-rungs.test.ts`; `web/packages/graph-client/test/snapshot.test.ts`;
  new `docs/generated-tier-disclosure.md`.
- Reserved: `web/packages/app/src/main.ts`, all backend source, migrations and stage registries.
  If the status-input adapter needs wiring in `main.ts`, stop and deliver its exact proposed
  patch for serialized integration. Do not silently widen ownership or duplicate the adapter.
- Deliver: status text naming each generated artifact's model/version and recorded/generated
  seam from the existing `generatedGeometry` snapshot fields. Missing metadata must be disclosed;
  it must not be invented or confused with what the renderer actually draws.
- Exit: execute a wire-payload to snapshot to rendered-status check, plus a negative control
  that drops the generated field and fails that same named check. Run the full required gates.
  Show the model and seam in a browser using a clearly labelled fixture; do not claim that a
  real model ran. Do not mark P10-2-b's status criterion complete until the serialized adapter
  wiring and browser check are both executed.

Real person-region review, the missing second capture, production frontier inputs, registry
publication and licensee demand evidence remain separate prerequisites. This brief closes a
specific read-to-display gap and does not claim to close them.
