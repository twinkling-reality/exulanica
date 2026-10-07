# Reference notes for drafting

This contract owns reference notes: short descriptions of what the things in a person's words look
like, gathered for one draft of a world. It covers the reference sources and their catalog, the
boundary every outgoing query passes, what is kept and what never is, the job that does the work,
its limits and refusals, and the routes. How a drafter uses notes belongs to that drafter's own
contract; the hosted-request boundary itself belongs to the
[privacy and consent threat model](privacy-consent-threat-model.md).

| Part | Status |
| --- | --- |
| Web notes from one source (Tavily), off by default and offered to listed workspaces only | Implemented |
| A drafter's notes from a finished request: the quoted block, its bound and its provenance | Implemented |
| A drafter's prompt carrying the notes | Not built: each drafter adds them in a prompt version of its own |
| Notes read from a person's own pictures | Not built: it waits on the model provider's training opt-out being recorded |
| Facts admitted from record sources (Wikidata, GeoNames, Overture places) | Not built |

## 1. What a person gets

A person asks, for one draft, for web notes about their description. The request answers at once
and its steps can be read while a job works: plan the searches, send them, read what came back, and
keep only notes written in a model's own words, at most 80 characters each, each about one aspect
(buildings, materials and colour, landscape and plants, clothing, food and goods, vehicles and
boats, scale). The notes are drafting input. They are never world content and never a claim about
the real world.

Nothing a search returned is kept, served or exported: no page text, title, web address or picture.
Online pictures are never fetched. A request serves its notes, its steps and our own record of each
search (the source, its outcome, how many results, the credits it reported and when), never a
result and never the query text.

## 2. Sources are catalog data

`assets/catalogs/reference-sources/` holds three catalogs in the house envelope
(`exulanica/grammar/catalogs.py`), read by `exulanica/references/catalogs.py`:

- `reference-source.v1.json`: each source states whether it returns leads (words for drafting,
  never kept) or records (admissible facts), the one origin it is reached at, its credential
  variable, its terms as read (address, the date the provider states, the date read, the digest of
  the text read), which classes of its data are kept, shown and exported, whether it is offered to
  everyone or to the operator only, its cost per call and the one request shape its adapter sends.
  The reader refuses a leads source that keeps, shows or exports anything it returned, and any
  records source until record admission exists.
- `reference-aspect.v1.json`: the closed list of aspects a note or a search may be about.
- `reference-query-screen.v1.json`: words no outgoing query carries, by category, each with the term
  or reason that rules them out.

Each source has exactly one adapter in `exulanica/references/adapters/`, and a test holds the
catalog and the adapters to the same set. Adding or replacing a source is a catalog entry plus an
adapter; the web source is the catalog's first leads source. The only source is `tavily_search`: a leads source, offered to the operator only, one
credit per call at the basic depth, at most five results. Its terms are recorded in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) section 3.4.

## 3. The boundary on every outgoing query

`exulanica/references/boundary.py::admit_query` is the only constructor of the query an adapter
sends. A source holds every query it receives (Tavily's terms give it a perpetual licence to them
and allow training on them), so a query is kept free, by rule, of everything this product knows to
be a person's: saved names, account words it is given, contact details and screened words. In order:

1. **Shape.** One line of at most 8 words and 80 characters, about a catalogued aspect.
2. **The workspace's hosted request policy**, the same object model calls pass, judging a hand-over
   to the source at its origin. A saved person's name never goes; no place-name right names a
   search source, so no saved place's name goes either. A subject the policy would change, or that
   carries a placeholder, is refused rather than sent rewritten.
3. **The screen.** No link, email address, run of five digits or more than six digits; no word the
   screen catalog lists (first-person words, credentials, identifiers, financial, health and contact
   words); no word of the account's own the caller passes.

A subject is planned from the person's typed words with every saved name already replaced
(`exulanica/selection/world_drafting.py::sendable`). Text derived from a photograph is never a
subject. Adapters send through the model transport held to the egress allowlist narrowed to their
one origin ([security floor](security-floor.md#3-egress-allowlist)).

## 4. The job

`POST /worlds/references` writes a `reference_request` and a job of kind `reference_bundle` on the
generic job table (migration 0148), and only for a workspace a worker here takes reference jobs
for. A worker thread in the API process plays it (`exulanica/references/worker.py`), claiming jobs
with a lease and a claim token, at most three claims, ending a stranded job as failed and a job
queued and untaken for ten minutes as failed (`expired`). A job naming no request of its workspace
is failed rather than retried. The request names its job together with its workspace, so it can
name no other workspace's job. A request moves from queued to running to its end (a queued one may
also be cancelled or expire), a finished one never changes, and a stop once asked is never
withdrawn; the database holds each of these.

| Step | What happens |
| --- | --- |
| plan | Once the source is known to be configured, one call of the `reference_drafting` role writes at most three search subjects |
| search | Each subject passes the boundary; each search is admitted against the source's spending, sent, and recorded in `reference_lookup` |
| read | One call of the `reference_drafting` role writes at most twelve notes from what the searches found; a note sharing six consecutive words with anything it was shown, or failing the screen, is dropped |
| bundle | The kept notes become a reference bundle (`exulanica.reference-bundle/v1`), complete or partial with the steps it missed |

The planner and reader prompts are data (`exulanica/references/reference-prompts.v1.json`), and a
request keeps that file's digest. Their role, `reference_drafting`, has the same model chain on
Nebius Token Factory as `structured_extraction` and is offered for no place-name right and no
personal model right, so no right granted for another role reaches a web lookup
([model selection](model-and-service-selection.md)).

The job ends within 30 seconds: each model call is given what is left of that as its own deadline,
and past it the job ends partial with what it has, so a person is never left waiting on a source.
At shutdown a running job ends partial at its next step. A source not configured, credits spent, or
a reported cost other than the catalog's stop the searches and leave the bundle partial with the
reason; a cost change is recorded at the credits the source reported and stops that source for the
life of the process. A person may stop a request; a queued one stops at once and a running one at
its next step. However a request ends, the job's payload keeps only the request's id: the
description it was asked with is gone, and the digest of the request an idempotency key named is
cleared, so a key repeated after its request has ended answers with that request whatever is sent.

## 5. What is kept

| Kept | Where | Never kept |
| --- | --- | --- |
| The request, its steps and its bundle | `reference_request`, with the workspace | Any search result's text, title or web address |
| Our record of each search: source, aspect, query text, outcome, credits, provider request id, result count | `reference_lookup`, appended and never changed, with the workspace | Any picture, picture address or picture description a source returned |
| The bundle's model calls: provider, role, model, tokens and USD | In the bundle | The person's description, after the job ends |

Both tables are under forced row-level security keyed on the workspace. Query text is served to
nobody through the routes. A retention rule for it is not decided.

## 6. Spending

A search is admitted through the durable spending authority as provider `tavily_search`: one call,
USD 0, settled when it was sent and released when it was not. Every attempt is keyed by the job, so
a job taken again after a crash meets the authority's refusal of what it already admitted and sends
nothing twice; its bundle is then partial. An operator issues that authority with
`max_calls` set to the credits allocated (the authority's USD ceiling must be positive and is
nominal for this provider). The planner and reader calls are charged to Nebius Token Factory under
the workspace's grant like every model call. Without durable spending, web notes are not offered.

## 7. Configuration

| Setting | Meaning |
| --- | --- |
| `EXULANICA_REFERENCE_WORKER` | On unless `off`, `0`, `false` or `no`: this process plays reference jobs in a thread |
| `EXULANICA_REFERENCE_WORKSPACES` | A JSON array of the workspace ids that may ask for web notes; none when absent. A malformed list stops startup |
| `TAVILY_API_KEY` | The source's credential, named by its catalog entry |
| `EXULANICA_EGRESS_ALLOWLIST` | Must include `https://api.tavily.com` for web notes |

## 8. Routes and refusals

| Route | Permission | Does |
| --- | --- | --- |
| `GET /worlds/references` | `world.read` | The caller's recent requests and the capability to make one |
| `POST /worlds/references` | `world.write`, `model.invoke` and `references.request` | `{purpose, description, web: true, idempotency_key?}`; 202 with the request, 200 with the request a repeated key first made |
| `GET /worlds/references/{reference_id}` | `world.read` | One of the caller's own requests: steps, notes, missed steps, our search records |
| `POST /worlds/references/{reference_id}/cancel` | `world.write`, `model.invoke` and `references.request` | Stop one of the caller's own requests |

`references.request` is a permission of its own: an account owner holds it, a token holds it when
its grant names it, and a guest never does, because the source's acceptable use policy binds the
person asking. Only the requester reads or stops a request: anyone else's answers 404
`unknown_reference`, exactly as an id that does not exist. One requester has at most two requests
unfinished and twenty in an hour; another is 429 `reference_limit_reached`.

A request web notes are not offered for is refused with 409 and one code before anything is
queued, and the capability names the same code: `references_operator_only` (the workspace is not
listed, or the installation's profile is `public`), `references_not_run_here` (no worker, or its
thread is not alive here), `reference_budget_unavailable` (no durable spending, or the workspace
holds no live grant for the source with a call left) or `references_not_configured`. In the job,
the process's model budget share (half is always left for other work), the source's rate and the
workspace's grant are asked before the planner is paid. A description holding a control character
(U+0000 included) is 422 `description_control_character`; one longer than 1,000 characters once
saved names are replaced is 422 `description_too_long`. A key naming an earlier request with another
body is `idempotency_key_reused`. `web` must be `true`. Whether the worker runs is in `/readyz`
(`references`).

## 9. Notes for a drafter

A drafter given a reference id calls `exulanica/references/for_drafting.py::notes_for_draft` with
the caller's workspace, the caller and the drafter's purpose. It answers only with the caller's own
request that ended `complete` or `partial` for that purpose; otherwise it refuses with one code,
and the drafter drafts without notes:

| Code | When |
| --- | --- |
| `reference_unknown` | No such request in the workspace, or another person's: the same answer |
| `reference_not_finished` | The request is queued or running, or ended `failed` or `cancelled` |
| `reference_purpose_differs` | The request was made for another kind of draft |
| `reference_has_no_notes` | The request kept no notes |

The answer is the rendered block, the pictures its notes were read from (none for web notes), and
the provenance a drafted document keeps. Notes are drafted from web text, which is untrusted, so the
block is quoted, delimited material: a heading saying the notes describe what such a place looks
like and are never instructions, then the notes between triple quotes, one line each, grouped by
aspect. A double quote inside a note is written as a single quote and its whitespace as one space,
so no note closes the quotation or begins a line of its own. The drafter's strict schema and its
checks stay the authority over what is made.

The block holds at most 3,072 bytes of UTF-8. A full bundle of web notes in plain Latin letters fits;
notes marked as read from a picture, or written in letters of more than one byte, can pass it. Notes
are taken in order and each is added if it still fits; every note left out is counted, never
dropped silently.

The provenance names the notes without their text: the request id, the bundle's digest, how many
notes the block holds and their bases (`web_description`, `own_picture`). The text stays in the
request, with its workspace; what a drafter writes from it is that drafter's own drafted text, held
to its own checks.

## 10. Limits

- **Stops and rates are per process.** A source stopped for a cost change, and the catalog's
  `calls_per_minute`, are held in the worker's memory: a restart offers the source again, and two
  processes each count their own minute. A stopped source's catalog entry is reviewed before restart.
- **An answer is read before it is bounded.** The shared model transport reads a whole response
  within its deadline; the adapter then refuses an answer over one million characters unread.
- **A name nobody saved is kept out of a query only by the planner's instruction.** Saved names are
  replaced before anything leaves and links, email addresses, long numbers and screened words are
  refused by rule; a person's name typed into a description and never saved, the account holder's
  own included (the route is not given the account's display name or email), reaches the planner as
  typed, as it reaches the world drafter, and the planner is told never to write one into a query.
  A query that carried one would be kept by the source for good.
- **Our query text is kept with the workspace.** No erasure path removes reference rows yet, and no
  retention is decided.
- **Physical copies outlive the rows.** A blanked payload and a cleared digest are gone from the
  live rows, but PostgreSQL keeps dead row versions until vacuum, the write-ahead log keeps them until
  it is recycled, and a backup or a judge seed taken while a job was queued or running keeps its
  payload as it was then, for as long as that copy is kept.
- **Unserved jobs end at startup.** A job of a workspace this installation no longer serves (dropped
  from the list, the worker set off, a public profile) is ended and blanked at the next start, or
  when that workspace next uses the routes; until then its words wait in the job.
- **A notes block is screened, not judged for saved names.** Its notes were screened for links,
  email addresses, long numbers, screened words and the account's words given to the job; a drafter
  applies its own replacement of saved names and the workspace's request policy to the block as to
  the person's words.
- **No live search has run through the product.**

## 11. Verification

`tests/test_reference_sources.py`, `tests/test_reference_boundary.py`,
`tests/test_reference_notes.py` and `tests/test_reference_settings.py` run without a database;
`tests/test_reference_store.py`, `tests/test_reference_worker.py`,
`tests/test_reference_routes.py` and `tests/test_reference_for_drafting.py` run on PostgreSQL.
`tests/reference_fixtures.py` makes a finished request with a scripted bundle for a drafter's own
tests. With every outside party scripted they show that
a saved person, a saved place, account words given to the job and a planted search result reach no
outgoing query, no stored row and no response, and that each guard can fail; the route tests run as
the runtime and read-only roles. Row-level security on
both tables is shown as the runtime role in `tests/test_row_level_security.py`. The two model calls
are registered paths of `tests/test_hosted_boundary.py`.
