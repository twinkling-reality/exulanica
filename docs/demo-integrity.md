# Demonstration integrity

Status: mixed, labelled per item.

This document holds the rules a hosted demonstration of this project has to obey, and the design
that makes obeying them possible: what may be precomputed and what has to run live for every
visitor, how the hosted deployment is shaped, how it resets between visitors, what fails during a
live run and what happens when it does, and the checks that are run before anyone is shown
anything.

The [demonstration audit archive](demo-runbook.md) retains a historical readiness inspection.
The hosted design below is a set of requirements, not evidence of a configured deployment.
[Deployment](deployment.md) owns service configuration; each demonstration must establish its
actual setup, reset behavior and supported user journey.

---

## 1. Pre-seeded versus computed live

The selected demonstration declares which operations are retained and which execute live. The
[product acceptance gates](product-direction.md#delivery-gates-for-the-first-demonstration) define
the complete journey; this contract defines disclosure within it.

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
- [ ] The automated rehearsal (section 5) ran from a clean start on the build being shown, and no
      step the demonstration relies on failed or was not reachable.

**Consent and privacy**

- [ ] Every identifiable person visible on screen is covered by consent, or is not on screen.
- [ ] No credential, balance, personal file path or unrelated notification appears on screen.
- [ ] The browser runs a clean profile: no bookmarks bar, no extensions, no unrelated tabs, neutral
      window title.

---

## 5. Automated rehearsal

`scripts/rehearsal/` repeats the first demonstration in the real application without a person
clicking through it, and reports which step of which
[delivery gate](product-direction.md#delivery-gates-for-the-first-demonstration) and
[first-milestone deliverable](product-direction.md#first-milestone) works. Its step list,
`scripts/rehearsal/steps.json`, is data. Each step is one action a person takes, with the results
that must be observable after it on the page, in the API and after a reload, and the owner area a
failure routes to. The gates are read from the product roadmap itself; `tests/test_rehearsal_steps.py`
fails when a gate there has no step, when a step names no observable result, and when a runnable
step has no driver.

**Running it.**

```bash
python3 scripts/rehearsal/rehearse.py --worktree <checkout> --slot <n> --out <new directory> --launcher scripts/acceptance/launch.py --model-env <environment file>
```

- `--worktree` is the checkout whose application is rehearsed, a linked worktree or a plain clone.
  It needs its own `.venv` and web packages. The runtime comes from the acceptance launcher that
  `--launcher` names; from a clone that is the repository's own, `scripts/acceptance/launch.py`.
  Without `--launcher` the rehearsal looks for `.exulanica/acceptance/launch.py` in the main
  checkout, an ignored file a clone does not have. The launcher starts that checkout's disposable
  test server, a fresh synthetic workspace with its own token, and the API, on the port block
  `--slot` chooses.
- The application is built for production into the run directory and served with `vite preview` on
  the slot's spare port. No development token is built in, so every page load passes the
  application's own access-token gate. Account sign-in is not exercised.
- Each browser session is one headless Chrome with one page, driven over the DevTools protocol, and
  waits its turn behind the development machine's GPU slot where that machine provides one.
- `--model-env` names the environment file that holds the hosted-model key. A child process reads
  only `NEBIUS_API_KEY` from it and hands it to the launcher by environment, together with the step
  list's `spend.bound_usd` as `EXULANICA_BUDGET_USD`, so the API itself refuses a model call past
  the run's bound. Without `--model-env`, the steps that call a hosted model are reported not
  reachable. They also stop starting once the spend the product reports reaches that bound, and a
  step list whose estimates exceed `spend.ask_before_usd` is refused before anything runs.

**The launcher on its own.** `scripts/acceptance/launch.py` also runs the application for a
person, without the rehearsal:

```bash
python3 scripts/acceptance/launch.py up --worktree <checkout> --slot <n> --production
python3 scripts/acceptance/launch.py status --worktree <checkout>
python3 scripts/acceptance/launch.py down --worktree <checkout>
```

Slot `n`, from 0 to 6, owns ports 19200 + 5n to 19204 + 5n: the database, the API, the application,
a browser debugging port and a spare. With `--production` the application is a production build,
made with no `VITE_` variable in its environment and served by `vite preview`, so the page asks for
the workspace token, which is in the run directory's `token` file; without it, the Vite development
server runs with the token built in. `--model` passes `NEBIUS_API_KEY`,
`EXULANICA_EGRESS_ALLOWLIST` and `EXULANICA_BUDGET_USD` from the environment to the API and refuses
without any of them. Run state and records stay in the system temporary directory, `down` stops
only what `up` started, and every refusal prints `refused (<name>)` and exits 2.

**Reading the result.** The run directory holds `result.json`, described by
`scripts/rehearsal/result.schema.json`, a `summary.txt` table, one screenshot per observed moment
and each browser session's log. Every step appears once, in step-list order:

| Status | Meaning |
| --- | --- |
| passed | Every observable the step list declares for it was checked and held. A runner that checks less, or something undeclared, fails the step. |
| failed | The observation, the screenshots, the API reads and the page's own requests are in the step's evidence. |
| not_reachable | A step it requires did not pass, its browser session ended first, or no hosted model was configured. The reason says which. |
| not_available | The step list declares that the product cannot attempt it, and says why. |

The gate table gives each gate the worst status of its steps and names its first failed step with
that step's owner area. The command exits 0 only when every step passed or is declared not
available, and 3 when the run directory holds the workspace token.

**What it does not do.** It does not observe a person or record demonstration footage, and it
measures no frame time. The photo drawer grants only the depth right, so the rehearsal grants the
vision, embedding and composer rights through `POST /personal-admission`, and it confirms the
proposed place through the identity routes rather than through the application. Every photograph it
uses is a synthetic drawing.
