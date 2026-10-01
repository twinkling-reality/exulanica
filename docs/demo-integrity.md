# Demonstration integrity

This guide owns the rules a demonstration of Exulanica obeys: what may be seeded and what must run
live, how a demonstration discloses the difference, how a seeded stack resets, what fails during a
live run and what happens when it does, the checks run before anyone is shown anything, and the
automated rehearsal of the first demonstration (section 5). The
[delivery gates](product-direction.md#delivery-gates-for-the-first-demonstration) define the journey
a demonstration shows; this guide defines how it is shown honestly. [Deployment](deployment.md) owns
configuration and the seeded reviewer stack, and the
[demonstration audit archive](demo-runbook.md) retains an earlier readiness inspection.

---

## 1. Pre-seeded versus computed live

A demonstration declares which of what it shows was retained beforehand and which executes live.

**Pre-seeded, and disclosed on the page itself:** whatever the seed carries, such as photographs and
their derivatives (vision observations, caption vectors, point maps and reconstructions), the saved
worlds and their versions, and the stored decisions and comparisons a replay reads. This is exactly
what a returning user experiences, which is why it is legitimate.

**Computed live, every time, for every visitor:** whatever the demonstration shows happening. A
simulated minute, a model's decision for a person, a Companion answer and the evidence behind each
citation, and an edit a visitor makes all run on the stated host when they are shown.

**Never, under any framing:**

- a progress bar that is not driven by real job state,
- a spinner in front of a cached response,
- hardcoded answers,
- any path that special-cases the scripted questions or the scripted world,
- a replay of stored decisions presented as models deciding live,
- claiming live reconstruction over a precomputed asset.

**DECISION.** No code path distinguishes a demonstration: there is no demonstration flag, so a
demonstration runs the same routes, models and checks as any other session. Rejected alternative: a
demonstration mode, which would need a test that runs the demonstration with the mode off and asserts
identical results before anyone could trust it.

**Disclosure copy**, on the page and not in the README: one line naming what was seeded and when,
and stating that everything the visitor does from that point runs live.

---

## 2. The hosted demonstration

### 2.1 Topology

No host is provisioned. The seeded reviewer stack (`deploy/judge/compose.yaml`) runs a seeded
workspace on one machine behind a same-origin proxy
([deployment, section 8](deployment.md#8-a-seeded-deployment-for-a-reviewer)). The hosting options
and the unattended-operation plan once researched for a hosted demonstration are summarised in
[deployment, section 10](deployment.md#10-hosting-options-researched-and-not-built); none is built.

### 2.2 Reset

**DECISION.** A seeded demonstration returns to one versioned seed, never to whatever the previous
visitor left.

- The seed is one versioned artifact: a verified archive of one workspace's rows and bytes, produced
  from a real workspace by `exulanica-seed export`, verified against its own manifest, and never
  hand-edited.
- `exulanica-seed reset` returns a used stack to the archive's rows.
- **Object storage is never touched by a reset.** Keys are content-addressed, so a reset that
  deleted them would be deleting the evidence every citation resolves to.
- Required and not built: a separate workspace per visitor, a visible reset control, an automatic
  reset after 30 minutes idle, and the seed's digest shown where a visitor can find it.

---

## 3. Failure modes and their fallbacks

Ordered by likelihood during a live run. The status column says whether the fallback exists in
code.

| # | Failure | Fallback | Status |
| --- | --- | --- | --- |
| 1 | A model identifier is withdrawn during a demonstration | The manifest declares a fallback identifier per role; the client selects it on a 404-class error only; the catalog preflight names any identifier that has disappeared | **Built and covered by tests.** `tests/test_models_client.py` drives the selection rule through a scripted transport, including the cases that must not trigger it. It has never been forced against the live platform ([deployment](deployment.md#11-open-items) D-7). The embedding role and a model a world chose for a person have no fallback |
| 2 | Token Factory returns 429 or 5xx during a live query | Retry with backoff on the same model where the client is built with more than one attempt. Do **not** switch models: a rate limit is the platform having a moment, and swapping would hide an incident behind a quality regression nobody would attribute correctly. When no attempt is left, the surface says the answer is unavailable rather than answering without evidence, and a person run by a model is decided by their routine | **Built** in `exulanica/models/client.py`. The API's client makes one attempt per call; the ingest command's makes three |
| 3 | Prepaid balance runs out | Spend cannot exceed the balance, so this degrades rather than escalates, and the process's own ceiling (`EXULANICA_BUDGET_USD`) stops calls before the balance does. Freezing the embeddings a demonstration needs would keep it off the embedding endpoint | Partly. The budget guard and usage ledger are built; frozen embeddings are **OPEN** ([deployment](deployment.md#11-open-items) D-6) |
| 4 | The backend host dies | A restart policy, an external check of `/healthz`, a one-command redeploy tested from a clean shell, and a database backup to restore | **OPEN**. No host is provisioned; `compose.yaml` restarts its workers, and no redeploy command or backup job exists ([deployment](deployment.md#9-backups-and-recovery)) |
| 5 | Total backend loss | The static front-end build serves a clearly labelled recorded tour. Labelling it as recorded is the whole point; presenting it as the live application would not be honest | **OPEN** |
| 6 | Frame rate collapses on the visitor's hardware | Frame-time-driven downgrade through the representation tiers, ending at the source-first layout, which needs no geometry at all. Never device sniffing, so no guessed hardware number is load-bearing | **Built and contract-tested.** Target-hardware thresholds remain unmeasured. |
| 7 | WebGL context loss | Restore retained decoded resources; if unrecoverable, hand over to the World Index, which is a complete and equivalent path to every function rather than a reduced one | **Built and contract-tested.** PlayCanvas recovery on target hardware remains unmeasured. |
| 8 | A visitor opens it on a phone or a window at or below 60rem | A factual viewport-boundary notice says the current prototype requires a laptop or desktop window. No mobile controls or alternate Index mode are implied | Built in the authenticated shell; ADR-0006 |
| 9 | A previous visitor left mutable state | `exulanica-seed reset` returns the stack to its seed (section 2.2) | Partly. Per-visitor workspaces are not built |
| 10 | Pointer lock is refused by the browser | The keyboard route and the World Index, both of which are complete paths | Partly |
| 11 | Someone asks to see reconstruction run live | It does not run in a request, by decision. Each region displays the rung it earned, and the rung is part of the region's identity rather than something hidden | Decided. `rungProperties` exists in `atlas-core` |

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

- [ ] The disclosure line naming what was seeded and when is visible on the page.
- [ ] The stack has been reset to its seed (`exulanica-seed reset`), so the session starts from the
      state a visitor will see.
- [ ] The seed archive's digest is recorded alongside the session, so what was shown can be
      reproduced rather than only described.
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
[first-milestone deliverable](product-direction.md#first-milestone), including the saved-world
foundation beneath it, works. Its step list, `scripts/rehearsal/steps.json`, is data. Each step is
one action a person takes, with the results that must be observable after it on the page, in the
API and after a reload, and the owner area a failure routes to. The gates are read from the product
roadmap itself. A gate no step serves is named in the step list with its reason, and a gate whose
steps rehearse only part of it is named with what they leave out. `tests/test_rehearsal_steps.py`
fails when a gate has no step and no such reason, when a step names no observable result, and when
a runnable step has no driver.

**Running it.**

```bash
python3 scripts/rehearsal/rehearse.py --worktree <checkout> --slot <n> --out <new directory> --model-env <environment file>
```

- `--worktree` is the checkout whose application is rehearsed, a linked worktree or a plain clone.
  It needs its own `.venv` and web packages. The runtime comes from the acceptance launcher,
  `scripts/acceptance/launch.py` in the rehearsal's own tree unless `--launcher` names another,
  run with `up --production` and the flags the step list's `runtime.society_playback` names
  (`--society-playback`). It starts that checkout's disposable test server, a fresh synthetic
  workspace with its own token, and the API, on the port block `--slot` chooses, and the API plays
  that workspace's societies at the host's declared base wait, the pace the product ships.
- The launcher builds the application for production, with no development token in the build
  environment, and serves it with `vite preview` on the slot's application port. Every page load
  passes the application's own access-token gate. The result records the build's hashes and the
  hash of the page the preview served. Account sign-in is not exercised.
- Each browser session is one headless Chrome with one page, driven over the DevTools protocol, and
  waits its turn behind the development machine's GPU slot where that machine provides one. A
  session that names an instrument (`scripts/rehearsal/instruments.mjs`) has it installed before
  the page loads. The living session's instrument reads where the page draws each walker in every
  animation frame and changes nothing the page does.
- `--model-env` names the environment file that holds the hosted-model key. A child process reads
  only `NEBIUS_API_KEY` from it and hands it to the launcher by environment, together with the
  effective API allocation as `EXULANICA_BUDGET_USD` and the step list's call ceiling as
  `EXULANICA_BUDGET_MAX_CALLS`, so the API itself refuses a model call past either bound. The
  derivative worker gets a separate money allocation; both process ceilings add to no more than
  the effective total run cap. Without `--model-env`, hosted-model steps are reported not
  reachable. They also stop starting once the spend the product reports reaches that bound, and a
  step list whose estimates exceed `spend.ask_before_usd` is refused before anything runs.
- The launcher starts one `exulanica-generated-tile-worker` for its workspace, checks its startup
  event, records its bake events and stops it with the stack. The rehearsal checks that the worker
  reported each saved town tile as baked. The rehearsal starts `exulanica-derivative-worker` over
  the same database and workspace, with the depth model and device the step list gives it, handing
  it the key through the child process.
- `--bound-usd` sets a lower total spend cap for one run and reduces both process ceilings;
  the result records the requested and effective total cap and both allocations. `--sessions`
  runs only the named browser sessions; `--reuse-database` reuses the slot's database; `--gpu-slot`
  names the machine's GPU slot command.

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
server runs with the token built in. `--no-derivative-worker` starts the API with
`EXULANICA_DERIVATIVE_WORKER=off`, the production shape. `--model` passes `NEBIUS_API_KEY`,
`EXULANICA_EGRESS_ALLOWLIST`, `EXULANICA_BUDGET_USD` and `EXULANICA_BUDGET_MAX_CALLS` from the environment to the API and refuses
without any of them. `--society-playback` makes the API play the run's own workspace
(`EXULANICA_SOCIETY_CONTROL_WORKSPACES` names it alone) at the declared base wait, or at
`--society-tick-interval-ms`, and `up` refuses unless readiness reports that workspace played. Run
state and records stay in the system temporary directory. `status` names the tile worker's running
state and its successful and failed bake events; `down` stops only what `up` started, and
every refusal prints `refused (<name>)` and exits 2.

Runs with more than one client use four further options, each off by default so a run without them
starts what it always did. `--port-base` moves the slot table to start at another port, for a run
that must sit inside a port block leased elsewhere. `--workspaces K` makes K synthetic workspaces,
each with its own actor, token file (`token`, then `token-2` onward) and embedding partition, served
by the one API; tiles, the tile worker and playback serve the first alone. `--read-only-token`
writes `token-read`, which grants the first workspace `world.read` alone. `--scripted-model PLAN`
serves the API through `scripts/acceptance/scripted_model.py`, whose model transport answers from
the plan while the model client, hosted-request policy, budget and receipts run as they do with a
provider; it refuses to start when any provider credential, provider variable or egress allowlist
is set, labels itself in `/readyz` with the plan's digest, and establishes mechanics only, never
model quality. `--spending process|durable` states its `EXULANICA_SPENDING` explicitly: the plan's
own bounds, or the durable spending authority with its witness directory in the run directory. The wheel and every image leave `scripts/` out, which
`tests/test_acceptance_scripted_model.py` checks. `restart-api` stops the recorded API and starts
it again on the same port, database, store and grants, and with `--revoke <token file>` leaves that
grant out, so a client can reopen its work from a fresh process or be shown a withdrawn credential
refused.

`scripts/acceptance/foundation.py baseline` checks a finite set of acceptance rows against such a
stack as an independent client: world creation for each world kind, the no-model mode, workspace
isolation with two client processes at once, the edit lifecycle, and the observable part of a
connected journey in which a bench placed in a saved starter world becomes a place its people rest.
Each row ends passed, failed or blocked with the missing prerequisite named; there is no skipped
state. A claim that an operation writes nothing is checked by dumping the run's database and
listing its store around it, after a plain read has shown the same check sees no change.

**Reading the result.** The run directory holds `result.json`, described by
`scripts/rehearsal/result.schema.json`, a `summary.txt` table, a JPEG screenshot of every observed
moment and at least one of every browser step, and each browser session's log. A step's evidence
keeps each request and response body of at most 4 KiB whole and a larger one as its SHA-256 and
size (`RECORDED_BODY_BYTES` in `scripts/rehearsal/resultdoc.py`); a step's checks read whole bodies
while the run is live and keep what they read in their observations. Every step appears once, in
step-list order:

| Status | Meaning |
| --- | --- |
| passed | Every observable the step list declares for it was checked and held. A runner that checks less, or something undeclared, fails the step. |
| passed_on_stand_in | Gates only. Every step that serves it passed, and at least one rests on an action the rehearsal driver performed in place of a person; the gate carries the stand-in's qualification. |
| passed_in_part | Gates only. Every step that serves it passed, and the step list states that those steps rehearse only part of the gate; the gate carries what they leave out. |
| not_served | Gates only. No step serves it, and the step list states why. |
| failed | The observation, the screenshots, the API reads and the page's own requests are in the step's evidence. |
| not_reachable | A step it requires did not pass, its browser session ended first, or no hosted model was configured. The reason says which. |
| not_available | The step list declares that the product cannot attempt it, and says why. |

The gate table gives each gate the worst status of its steps and names its first failed step with
that step's owner area. The command exits 0 only when every step passed or is declared not
available, and 3 when the run directory or the production build holds the workspace token.

**The living world.** The first-use card's "Start with a small square" is pressed at arrival, the
only moment it is offered, because the card greets only a starter that holds nothing and a
workspace has one starter. The rehearsal places the square from the card and then takes it back
one change at a time, so the creation steps still begin with an empty world. The living session
then furnishes the starter with the Create panel's own square and brings inhabitants in. It
presses Play in People nearby, lets a minute pass on its own and watches for a minute. Walking
counts as continuous when someone is drawn walking and the 95th percentile of the pace walkers are
drawn at is at most 6 m/s: people walk on rather than rush a minute's path and stand. Standing is
not a failure, since people linger by design. It reads one inhabitant in the inspector, waits for
someone to use an object of the square, and pauses the world. These steps serve the first
milestone's A world to run and the Usable world delivery gate with the town session's.

**Models deciding for people.** In People nearby, under Who decides for them, the rehearsal ticks
four of the starter's people and chooses DeepSeek V4 Flash for them before it presses Play. While the
host plays the world it waits for a decision that model served and the minute applied, reads it in
the inspector (Decided by, Latest decision) and reads the same decision from the API: the request
with the options the person saw, the receipt naming the model that served it, and a replay of the
society from its stored decisions. It then waits for one of those people to stand a while or talk
because their model chose it. That model chose those actions most often of the models measured
([model actions record](evaluation/2026-09-26-society-model-actions.json)). The birds of the square's tree are watched for a minute in which some fly and some
perch: each drawn bird must be moving exactly while the flight route serves it off its perch at
that moment of the shared clock, away from a change of state, and every press of the World menu
meanwhile must be answered within 200 ms, the Core Web Vitals line for a good Interaction to Next
Paint.

**A town.** The town session makes a market town through Create in the World menu, with two of its values moved to
the next value inside the ranges the server serves, and waits while the tile worker bakes its tiles
until the town opens and reopens after a reload. It brings the town's people in and plays: society
reads a host interval apart must place one person on one tile and then on another, a tile being the
town's extent over its tiles along it, and within one traffic episode a traffic read must serve a
vehicle that moves while the page draws them. It chooses Nemotron 3 Nano 30B for four of the town's
people, pauses the town and starts a comparison through Compare in the World menu for that group, against Nemotron
3.5 Lightning with a same-model control run on one development seed, under the bound the plan
suggests for a typical comparison to finish or 0.05 USD when that is less. It waits until the comparison finishes,
records any run its bound stopped, and checks that the town is unchanged by it. It asks the
Companion what happened in the town and checks that the page says which model chose the answer's
lines, or that none did within the answer's wait. Last, it describes a town in words under Describe
it, uses the values the model drafts and makes that town too. The Compare view then shows the town's
comparison, and the developer client reads it, its runs and their decisions through the API
(`python -m exulanica_client comparisons`). A development seed is never judged, so Honest difference
is reported `not_served`; the model and comparison gates are served in part, for one group under one
model and one simulated hour of the town.

**The judge seed.** The last session exports the run's workspace with `exulanica-seed export`,
verifies the archive, and restores it into a fresh database on the run's own server and an empty
data directory with the judge deployment's jobs (`exulanica-db`, `exulanica-seed role` and
`restore`), then reads each town's tiles back from them: every tile must read baked, with its bytes
in the restored tile store.

**The Companion's memory and the made world.** In the world made from the photographs the Companion
is asked for a change the reviewed design cannot make and must answer once, without offering to
open Customize, with a provenance line naming the model that read the request; after a reload it
must redraw that answer in the same words with the same provenance line. The same holds for the
proposal it makes and Customize shows. The last session places the small square in the made world
and brings people in: they must stand on the floor the world declares, with Who decides for them
beside them.

**What it does not do.** It does not observe a person or record demonstration footage. It does not
ask for a change Customize itself refuses, since no request in words makes one: that refusal follows
a proposal made stale or a design the panel cannot show. It judges
no frame time: the walking measure reads how far walkers are drawn to move between frames, not
how long a frame takes. The human review of its photographs is given by the rehearsal driver
through the photo drawer's own controls, as a stand-in the step list states once (`stand_ins` in
`scripts/rehearsal/steps.json`): the reviewer name and purpose it records say so, every step resting
on it carries that statement in the result, and a gate resting on it reports `passed_on_stand_in`
rather than `passed`. It runs the production derivative worker with its depth model on the
development machine's processor, and it does not run multi-view reconstruction: no scene group of
its photographs holds the three photographs with point maps that pose recovery needs, and the scene
worker requires the pose runtime image by digest as provenance, which the development machine does
not build. It confirms the proposed place through the identity routes rather than through the
application. The photograph it adds to the made world on its return rests on the same stand-in
review. Every photograph it uses is a synthetic drawing.
