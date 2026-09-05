# Demonstration runbook

Status: mixed, labelled per item. Buildability audited against the repository on **2026-08-28**.

**CORRECTED 2026-09-04.** Section 1 remains the dated audit it says it is, but its reconstruction
and assembled-application rows are no longer current. The API, application shell, production
point-map delivery, and rung-3 multi-photograph scene path now exist. The latter is documented in
[scene-reconstruction-operations.md](scene-reconstruction-operations.md). No authorized real dense
capture set has run through it, and there is still no hosted URL, so this correction is not a claim
that the demonstration backlog is closed.

Two things have to exist before this project can be shown to anyone who is not sitting beside the
person running it, and they are different artifacts with different failure modes:

- a short public video showing the project working, and
- a **hosted demonstration** a visitor can open and use without private credentials, without a long
  GPU job, and without a person standing by.

This runbook is written against what the repository can actually do today, not against the full
product. Section 1 is the audit that makes the rest of the document set trustworthy, and section 2
is the backlog that audit produces. What a demonstration is allowed to precompute, how the hosted
deployment is shaped and reset, what fails during a live run, and the checks that run beforehand are
all in [demo-integrity.md](demo-integrity.md).

---

## 1. What can be demonstrated today

**VERIFIED by inspection of the repository on 2026-08-28.** Everything in this table was checked by
reading the code that would have to run, not by reading a plan that describes it.

### 1.1 Runs now

| Capability | How it runs | What a viewer sees |
| --- | --- | --- |
| Catalog preflight | `uv run exulanica-preflight` | Every model identifier in the manifest resolved against the live catalog, exit 0 or 1 |
| Platform verification pass | `uv run scripts/verify_platform.py` | A live NVIDIA Nemotron call, a live vision call over an image, a live embedding call, and structured output, with the responses archived |
| Public-entity lookup, as a script | `uv run scripts/verify_web_lookup.py` | One real Tavily search with its request payload retained |
| Photograph ingest | `uv run exulanica-ingest ingest <dir>` | Real vision observations over real photographs through `MiniMaxAI/MiniMax-M3`, EXIF normalisation, scene grouping, content-addressed storage, and a second run that skips everything and issues zero model calls |
| Landing surface | `pnpm --dir web landing` | The public title and Method surfaces. Its CTA links to the real app when that destination is configured; it does not replay a mock Atlas |
| First-person traverse of a region | `pnpm --filter @exulanica/atlas-react bakeoff:playcanvas` | Pointer-lock mouse-look, WASD, reticle targeting and the live anchor overlay over point-map islands, on **synthetic** fixtures |
| Test suite | `uv run pytest` | 1447 tests, 677 of which skip without a live PostgreSQL 18 server with pgvector |

### 1.2 Does not exist yet

Named plainly, because each one blocks a specific part of the demonstration path.

| Missing | Consequence for the demonstration |
| --- | --- |
| No HTTP API process | Nothing in the browser can reach the evidence spine. The front end runs on fixtures |
| No retrieval or answer path | The cross-region question cannot be demonstrated |
| No embedding stage | The embedding role is declared in the manifest and reachable through the client, but no pipeline stage computes or stores vectors |
| No entity writes at all | No cross-capture continuity proposal can be raised from real data, so the confirmation cannot be demonstrated |
| No reconstruction pipeline in the repository | No region has earned a rung from real photographs. The renderer is exercised on synthetic point maps |
| No public-entity lookup inside the product | The lookup exists as a verification script, not as an opt-in surface |
| No assembled application shell | `atlas-react`, `world-index`, `companion-runtime` and `graph-client` are separate packages with no page that composes them |
| No hosted deployment, health check, seed or reset | There is no URL to give a visitor, and no reset procedure has been executed |
| Migration not applied to PostgreSQL 18 | Every SQL-level guarantee is a text-level claim until it is |

**Consequence, stated once and not softened: as of 2026-08-28 no part of the demonstration path can
be performed end to end against real data.** The honest demonstration available today is the ingest
pipeline spending real money on real photographs, the platform verification pass, and the renderer
traversing synthetic geometry. That is a build state, not a demonstration, and section 2 is the plan
for closing the gap rather than a description of something that exists.

---

## 2. Open items owned by this document

| # | Item | What would resolve it |
| --- | --- | --- |
| D-1 | No part of the demonstration path is performable end to end | The API process, the retrieval and answer path, and an application shell that composes the existing front-end packages |
| D-2 | No corpus is ingested, so there is no pre-seeded state | Ingest the photograph corpus once the consent question in `product-specification.md` section 10 is answered |
| D-3 | The seed and reset mechanism does not exist | Build it before the corpus is ingested, not after, so the seed is produced by a real run rather than reconstructed |
| D-4 | No hosted URL | Deployment topology is decided in `architecture-overview.md` section 2.1 and has not been stood up |
| D-5 | The weekly check through the unattended window has no named owner | An operator decision, not a technical one |
| D-6 | The no-special-casing test cannot be written yet | Depends on D-1 |
