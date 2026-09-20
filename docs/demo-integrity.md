# Demonstration integrity

Status: mixed, labelled per item.

This document holds the rules a hosted demonstration of this project has to obey, and the design
that makes obeying them possible: what may be precomputed and what has to run live for every
visitor, how the hosted deployment is shaped, how it resets between visitors, what fails during a
live run and what happens when it does, and the checks that are run before anyone is shown
anything.

It is separate from [demo-runbook.md](demo-runbook.md), which records only what this repository can
and cannot do today. Nothing in section 2 exists yet. It is recorded now because the reset design
constrains the data model, and retrofitting it later is what produces a demonstration that a
previous visitor has broken.

---

## 1. Pre-seeded versus computed live

**DECISION**, carried from [product-specification.md](product-specification.md) section 4.1 without
softening.

**Pre-seeded, and disclosed on the page itself:** photograph ingest and its vision observations,
embeddings, scene grouping, whatever reconstruction artifacts exist, and the persisted layout. This
is exactly what a returning user experiences, which is why it is legitimate.

**Computed live, every time, for every visitor:** focus resolution and view recomposition in the
browser, the confirmation write, retrieval, the answer turn on Nemotron, evidence resolution behind
every citation chip, and the public-entity lookup.

**Never, under any framing:**

- a progress bar that is not driven by real job state,
- a spinner in front of a cached response,
- hardcoded answers,
- any query path that special-cases the scripted questions,
- claiming live reconstruction over a precomputed asset.

**DECISION.** One test runs the demonstration questions with the demonstration flag off and asserts
identical results. That test is the proof that nothing is special-cased, and it belongs in the
repository where any reader can find it. **OPEN**: it cannot be written until the answer path
exists.

**Disclosure copy**, on the page and not in the README: one line naming when the captures were
ingested and stating that everything the visitor does from that point runs live.

---

## 2. The hosted demonstration

**Status: OPEN in its entirety.** Nothing in this section is built.

### 2.1 Topology

Per [architecture-overview.md](architecture-overview.md) sections 2.1 and 7.2: the API process and
PostgreSQL on a Compute VM with a restart policy in eu-north1, assets on Nebius Object Storage, a
static front-end build on a separate host, and an external check hitting `/healthz` every five
minutes and alerting a real phone. The Preview-grade serverless option is deliberately not used for
anything whose death is unrecoverable.

### 2.2 Reset

**DECISION.** Per-visitor ephemeral tenants, not one shared mutable account. This removes the entire
class of failure where the previous visitor left the demonstration in a strange state, and it is
worth more than any other reliability work here.

- The seed is one versioned artifact: a PostgreSQL logical dump plus a manifest of
  content-addressed object storage keys, produced by a real ingest run and identified by a seed
  hash. It is never hand-edited.
- A new visitor gets a tenant identifier and a copy of a few thousand graph rows. The rows point at
  the same shared assets, so nothing large is copied and the operation is milliseconds.
- **Object storage is never touched by a reset.** Keys are content-addressed, so a reset that
  deleted them would be deleting the evidence the whole product rests on.
- A visible reset control, and an automatic reset after 30 minutes idle.
- The seed hash and the catalog snapshot date are displayed somewhere a visitor can find them.

### 2.3 Unattended operation

The demonstration is expected to run unattended for weeks at a time. The controls are in
[architecture-overview.md](architecture-overview.md) section 7.2 and are not repeated here. Two of
them are runbook items rather than code: a named person performing a weekly check, and that check
including a catalog diff rather than only a health ping. A ping succeeds right up until the first
query reaches a withdrawn model. **OPEN**: the person is not named.

---

## 3. Failure modes and their fallbacks

Ordered by likelihood during a live run. The status column says whether the fallback exists in code
today.

| # | Failure | Fallback | Status |
| --- | --- | --- | --- |
| 1 | A model identifier is withdrawn mid-window | The manifest declares a fallback identifier per role; the client selects it on a 404-class error only; a preflight fails the build if any identifier has disappeared | **Built and covered by tests.** Five tests drive the selection rule through a scripted transport, including the cases that must NOT trigger it. It has never run against the live platform, and there is no continuous integration to run it in, which is why `deployment.md` D-7 still lists it as unexecuted |
| 2 | Token Factory returns 429 or 5xx during a live query | Retry with backoff on the same model. Do **not** switch models: a rate limit is the platform having a moment, and swapping would hide an incident behind a quality regression nobody would attribute correctly. If retries are exhausted, the surface says the answer is unavailable rather than answering without evidence | **Built.** Client policy, `exulanica/models/client.py` |
| 3 | Prepaid balance runs out | Spend cannot exceed the balance, so this degrades rather than escalates. Mitigation is to precompute and freeze embeddings so the demonstration never calls the embedding endpoint, plus a balance check in the weekly pass | Partly. The budget guard and usage ledger are built; the frozen-embedding decision is **OPEN** |
| 4 | The backend host dies | Restart policy, external `/healthz` check every five minutes to a phone, one-command redeploy tested from a clean shell, nightly `pg_dump` to object storage | **OPEN**, none built |
| 5 | Total backend loss | The static front-end build serves a clearly labelled recorded tour. Labelling it as recorded is the whole point; presenting it as the live application would not be honest | **OPEN** |
| 6 | Frame rate collapses on the visitor's hardware | Frame-time-driven downgrade through the representation tiers, ending at the source-first layout, which needs no geometry at all. Never device sniffing, so no guessed hardware number is load-bearing | **Built and contract-tested.** Target-hardware thresholds remain unmeasured. |
| 7 | WebGL context loss | Restore retained decoded resources; if unrecoverable, hand over to the World Index, which is a complete and equivalent path to every function rather than a reduced one | **Built and contract-tested.** PlayCanvas recovery on target hardware remains unmeasured. |
| 8 | A visitor opens it on a phone or a window at or below 60rem | A factual viewport-boundary notice says the current prototype requires a laptop or desktop window. No mobile controls or alternate Index mode are implied | Built in the authenticated shell; ADR-0006 |
| 9 | A previous visitor left mutable state | Per-visitor ephemeral tenants, section 2.2 | **OPEN** |
| 10 | Tavily credits exhausted | The lookup is opt-in and its results can never be cited, so its absence removes a panel and breaks nothing. On failure the panel says the lookup failed. The declared fallback is to cut the feature, never to fake a result | Partly. The call is verified; the product surface is **OPEN** |
| 11 | Pointer lock is refused by the browser | The keyboard route and the World Index, both of which are complete paths | Partly |
| 12 | Someone asks to see reconstruction run live | It does not run in the live path, by decision. Each region displays the rung it earned, and the rung is part of the region's identity rather than something hidden | Decided. `rungProperties` exists in `atlas-core` |

---

## 4. Pre-demonstration checklist

Run in order. Anything that fails stops the demonstration rather than being worked around in front
of whoever is watching.

**Platform state**

- [ ] `uv run exulanica-preflight` exits 0. Record the date of the catalog snapshot it checked against.
- [ ] Prepaid balance is sufficient for the session, checked in the billing console.
- [ ] The exact model identifiers about to be named match `exulanica/models/models.manifest.json`
      character for character. The catalog's display names differ from the callable identifiers, and
      repeating a display name puts a wrong identifier in front of whoever is watching.

**Demonstration state**

- [ ] The demonstration questions return identical results with the demonstration flag off.
- [ ] The disclosure line naming the ingestion date is visible on the page.
- [ ] A fresh tenant has been created, so the session starts from the state a visitor will see.
- [ ] The seed hash is recorded alongside the session, so what was shown can be reproduced rather
      than only described.

**Consent and privacy**

- [ ] Every identifiable person visible on screen is covered by consent, or is not on screen.
- [ ] No credential, balance, personal file path or unrelated notification appears on screen.
- [ ] The browser runs a clean profile: no bookmarks bar, no extensions, no unrelated tabs, neutral
      window title.
