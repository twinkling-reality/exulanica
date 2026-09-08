# Remaining work to a thorough personal world memory model

Measured 2026-09-08 against `main` at `4c4a3dc`. This is a **sizing and sequencing document**, not a
plan of record: the tickets in `phase-10-tickets.md` remain the authority on what a ticket is, and
this file says only what is left, how big it is, and what order removes the most blocking.

## How it was measured, and why the number is a floor

Five read-only inventories, one per area, each sizing work in **chat-sized packages** where one
package is roughly twenty commits with executed exit criteria and a digest-bound record. Each
inventory was then attacked by a separate pass told to assume it was too low.

**Every one of the five was judged too low.** The inventories totalled 35 packages; the challenges
raised it to 42.5. The challengers found whole categories nobody had costed, of which the largest
was hosted operation, backup and recovery, omitted by all five.

So **treat 42.5 as a floor**. It has already been corrected upward once by the only process available
for correcting it.

| Blocker | Packages | Can more chats help? |
| --- | --- | --- |
| Code | about 30 | Yes |
| Data | about 6 | No: needs a corpus the operator supplies |
| Decision | about 3.5 | No: needs the operator |
| Calendar | about 2.5 | No: needs elapsed time |

At three concurrent chats, the code half is roughly ten to fourteen working days. **The system is
not engineering-bound.** It is bound by a photo corpus, a signing key, a second capture weeks after
the first, and three decisions.

## Three findings that change the shape of the work

**The tickets file understates progress.** Seven Phase 10 exit criteria are already satisfied by
commits `6051456` and `64816ac`, which never touched `phase-10-tickets.md`. Some of what reads as
remaining is bookkeeping. Verifying and ticking them is half a package, not seven.

**Persistent objects is the cheapest capability, not the most expensive.** The ticket files it as
"Deferred. Not started", and that is wrong about the substrate. The proposer already runs in the
ingest path, ranks on non-biometric context, hard-constrains on detector label, writes
`auto_provisional` and never `confirmed`, keeps rejection memory keyed by evidence and basis, and
confirm, reject, merge, split and undo are live routes. Two real gaps remain.

**The second gap is a reading question, not a safety defect, and an inventory pass got this wrong.**
The roadmap says people are excluded from automatic linking, no biometric templates. An inventory
agent read `exulanica/identity/proposer.py:167-170`, saw it constrain on class equality alone, and
reported that people are not excluded. Checked against the module's own docstring, that is
misleading: this proposer exists **specifically** to ask whether a person named in one photograph is
the same person in another, and it refuses biometrics explicitly. Face, voice and gait have no
producer, the decision that would permit a face embedding is recorded as open in
`privacy-consent-threat-model.md` section 10, and the three signals are context alone. It writes
`auto_provisional` and never `confirmed`, and only a human creates a confirmed link.

So the roadmap sentence is ambiguous rather than violated. "Excluded from automatic linking" can
mean "no biometric templates", which holds, or "people are never proposed at all", which does not.
**That is a decision for the operator to record, not a bug to fix**, and recording it is worth more
than the code it would change.

## The cost nobody had priced

The first person region recorded on a retained capture invalidates that capture's `masked_source`
idempotency key. `exulanica/ingest/masked_inputs.py:150-185` then refuses rather than reconstructing,
which forces masked re-derivation, a retrain of the bowl, and re-records of every digest-bound record
naming those scenes.

"Turn the privacy layer on for real" is therefore not one package. It cascades through geometry and
evidence, and the cascade is correct behaviour rather than a defect. Know it before screening the
first photograph.

## Sequence

Ordered so that each tier removes blocking for the tiers under it. Sizes in packages.

### Tier 0. Operator actions. Not code, and they gate the rest

- Push the twenty unpushed commits. The only item here with no undo if the disk fails.
- Take capture one of a place. The exit needs two captures **weeks apart**, so this is a clock and
  not a task; every day it waits is a day added to the end.
- Assemble the authorized photo directory, and generate the Ed25519 signing key.

### Tier 1. Before any personal photograph enters the system (about 3.8)

- **0.3** Exclude people from automatic linking, or record the decision not to. Safety, and it is a
  stated constraint currently unenforced.
- **1.0** A pinned local person segmenter, so the operator's photographs are not sent to a hosted
  model to find people in them. This is a decision with a licence and a lock file attached.
- **1.5** Personal capture admission and screening: an authority the frontier command can use for
  media that is not a published benchmark set.
- **1.0** The two production screening writers the admit-ingest-rescreen flow needs, plus a re-run
  trigger. Without these the two-pass flow exists only in tests.

### Tier 2. Make the privacy layer true of a running deployment (about 3.2)

- **1.0** The reviewer can add a region no detector proposed. The only path to a person that does
  not depend on a model, and the screen is already wired.
- **0.2** Person regions on the 284 retained captures. Operator labour, not code.
- **1.0** Run the whole chain once on the retained photographs: vision, regions, review, consent,
  rebuild. Nothing here has ever run against a real photograph.
- **1.0** A masked scene can still be Gaussian-trained. Today training a masked scene is refused.

### Tier 3. Make the bundle usable by somebody who is not us (about 3.5)

- **1.5** Per-person consent state a recipient can check, without putting the clock inside the
  digest. The bundle names this itself as one of the two things blocking a release state above
  `internal_only`.
- **1.0** Geometry entries name the source derivative they were built from. The other of the two.
- **1.0** Serve the posed view bytes, masked where consent requires. Today the bundle carries
  calibration and geometry and no photograph, so what a generative model can condition on is
  narrower than the phase claims.

### Tier 4. Places become visible and durable (about 4.5)

- **1.0** Places reach the browser at all: wire types, a world-read client, a per-region time
  control. VERIFIED 2026-09-08 by word-boundary search, because a substring search for "place"
  matches `placement` and ordinary prose and reports a false positive: `place_id`, `PlaceRow`,
  `placeId` and `place_version` appear in none of `graph/payload.py`, `graph-client/src/wire.ts` or
  `graph-client/src/snapshot.ts`. The place plane stops at the World Read bundle.
- **2.0** The web surface for places: regions merged across versions, time as a dimension.
- **1.0** The `place_alignment_job` queue: claim, lease, heartbeat, reclaim, worker command.
- **0.5** Two consented captures of one real place, joined and shown. Calendar.

### Tier 5. Cheap, parallel, and each one makes the next change safer (about 4.6)

Any of these can run alongside anything above. They are the modularity and verification debt, and
they get more expensive the more surfaces exist.

- **0.5** Verify and tick the seven Phase 10 exits the code already satisfies.
- **0.5** A wire-schema parity check between the Pydantic payload and the TypeScript copy.
- **0.25** An exhaustiveness guard on the snapshot adapter, so the next wire field cannot vanish
  silently. `graph-client/src/snapshot.ts` is the drop point and nothing catches it.
- **1.0** Break `mount()` into named phases before two more surfaces are wired into it.
- **1.0** Materialise the observation graph so a page is a range scan rather than a full re-parse.
- **0.5** Move SQL out of the six route modules and make the thin-route rule executable.
- **0.5** Run the reconstruction tests in CI, and push the commits CI has never seen.
- **0.35** Correct the two stale package counts in the docs, and rename the engine-named subpath.

### Tier 6. Close the frontier milestone (about 5.0)

- **1.0** Close the three section-13 clauses the command never exercises.
- **1.0** Let the frontier world and receipt see a reconstructed scene.
- **0.5** Bind browser degradation and reconstruction quality into the receipt.
- **0.5** Run configured vision and `moge` depth through the command once.
- **1.0** Run it on the authorized personal corpus and fix what first contact breaks.
- **1.0** Attempt one splat on the personal corpus and record the honest outcome. A refusal that
  retains the lower rung satisfies the milestone; a pretty render is not required.

### Tier 7. After the milestone (about 4.0)

- **1.0** Measured cross-capture object precision on a blind split. Capability 4's real exit.
- **1.0** FR-12: condition a real generative model on a read bundle and measure the seam.
- **1.0** Subject-facing consent, so the photographed person can answer for themselves. The design
  note's own word for its absence is theater.
- **0.5** Fit `PLACE_ALIGNMENT_POLICY` thresholds to an observed residual distribution. Today they
  are unvalidated engineering choices.
- **0.5** Feed real resident bytes into the pressure ladder, which demotes on frame time alone.

### Not sized, and omitted by every inventory

Hosted operation, backup and recovery. `docs/deployment.md` marks all three recovery paths as
unexercised. This is not on the path to the milestone and it is on the path to a system anybody
depends on.

## What this document is not

It is not a promise. Every number here was produced by reading code and tickets, not by doing the
work, and the one adversarial pass available raised it by a fifth. The categories most likely to
grow are the ones involving first contact with real photographs, because that is where this
repository has repeatedly found that a module with no production caller was reported as done.
