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
| Notes read from a person's own pictures: the reading call, its role, the checks on its notes, the job's picture step and the routes | Implemented, off by default (`EXULANICA_REFERENCE_PICTURES`) and never offered on a `public` installation; it stays off until Nebius Token Factory Sales confirms in writing that its terms allow it |
| Facts admitted from record sources (Wikidata, GeoNames, Overture places) | Not built |

## 1. What a person gets

A person asks, for one draft, for web notes about their description. The request answers at once
and its steps can be read while a job works: plan the searches, send them, read what came back, and
keep only notes written in a model's own words, at most 80 characters each, each about one aspect
(buildings, materials and colour, landscape and plants, clothing, food and goods, vehicles and
boats, scale). The notes are drafting input. They are never world content and never a claim about
the real world.

Where pictures are offered, a person may also name up to four of their own pictures, each admitted
with a right for the picture reader that the same person granted, and get notes on the places and
things they show (section 10).

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
also be cancelled or expire), a finished one never changes except to be withdrawn (section 10),
and a stop once asked is never
withdrawn; the database holds each of these.

| Step | What happens |
| --- | --- |
| plan | Once the source is known to be configured, one call of the `reference_drafting` role writes at most three search subjects |
| search | Each subject passes the boundary; each search is admitted against the source's spending, sent, and recorded in `reference_lookup` |
| read | One call of the `reference_drafting` role writes at most twelve notes from what the searches found; a note sharing six consecutive words with anything it was shown, or failing the screen, is dropped |
| read_picture | Before the searches, once for each picture the request names: the picture is read and its notes checked (section 10); the step names the picture's capture id |
| bundle | The kept notes become a reference bundle (`exulanica.reference-bundle/v1`), complete or partial with the steps it missed |

A request that did not ask for web notes skips plan, search and read; one that names no picture
has no picture step. The planner and reader prompts are data (`exulanica/references/reference-prompts.v1.json`), and a
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
| Nothing of a withdrawn request's bundle | The request keeps its status `withdrawn` and steps | Notes made from a picture whose right stopped or which was deleted, or the web notes kept beside them |

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
| `EXULANICA_REFERENCE_PICTURES` | Off unless `on`, `1`, `true` or `yes`: listed workspaces may also name their own pictures. Any other value stops startup |
| `TAVILY_API_KEY` | The source's credential, named by its catalog entry |
| `EXULANICA_EGRESS_ALLOWLIST` | Must include `https://api.tavily.com` for web notes |

## 8. Routes and refusals

| Route | Permission | Does |
| --- | --- | --- |
| `GET /worlds/references` | `world.read` | The caller's recent requests, the capability to make one, and `pictures` |
| `POST /worlds/references` | `world.write`, `model.invoke` and `references.request` | `{purpose, description, web, pictures?, idempotency_key?}`; 202 with the request, 200 with the request a repeated key first made |
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
body is `idempotency_key_reused`; a request's pictures are part of its body. Whether the worker runs
is in `/readyz` (`references`).

`web` is stated on every request. A request asks for web notes, names one to four pictures by
capture id, or both; one asking for neither is 422 `nothing_to_look_up`, and one naming a picture
twice is 422 `pictures_repeated`. A request without web notes needs no grant for the source and no
configured adapter, and still needs durable spending, because reading a picture is a model call.
Naming pictures where they are not offered is 409 `reference_pictures_not_offered`, and naming one
that may not be read is 409 `reference_picture_not_admitted` with its reason in the detail
(section 10); either is refused before anything is queued.

The list's `pictures` is `{offered, code, maximum, consent?}`: `offered` is whether this workspace
may name pictures here, `code` says why not (`reference_pictures_not_offered`, or the code a request
without web notes would be refused with), `maximum` is 4, and while pictures are offered `consent`
holds `uses`, the model right uses offered on this step with the exact words each is granted
against. A page shows nothing about pictures while `offered` is false.

## 9. Notes for a drafter

A drafter given a reference id calls `exulanica/references/for_drafting.py::notes_for_draft` with
the caller's workspace, the caller and the drafter's purpose. It answers only with the caller's own
request that ended `complete` or `partial` for that purpose; otherwise it refuses with one code,
and the drafter drafts without notes:

| Code | When |
| --- | --- |
| `reference_unknown` | No such request in the workspace, or another person's: the same answer |
| `reference_not_finished` | The request is queued or running, or ended `failed` or `cancelled` |
| `reference_withdrawn` | The notes were withdrawn with a picture they were made from (section 10) |
| `reference_purpose_differs` | The request was made for another kind of draft |
| `reference_has_no_notes` | The request kept no notes |

The answer is the rendered block, the pictures its notes were read from (none for web notes), and
the provenance a drafted document keeps. A drafter takes web notes only unless it names more bases:
a note read from a person's own picture is declared as that picture, and the workspace's request
policy refuses the whole call unless the person's right names the drafter's role, so a drafter asks
for picture notes only once its role is offered for them. Notes are drafted from web text, which is untrusted, so the
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

## 10. Notes from a person's own pictures

What a picture may become is fixed before any model sees one. One call of the `reference_vision`
role (`exulanica/references/pictures.py::read_picture`) reads the picture's rendition, the 768 px
copy with no location or camera details, and answers a strict form: `refuse`, one of
`shows_people`, `shows_text` or `not_a_place`, or null, and then at most six notes of at most 80
characters. A refusal keeps nothing of the picture but its reason. The form has no field for a
person, a place name or any writing, and nothing in a picture is located, cropped, embedded or
compared. The call declares its picture, so the workspace's request policy refuses it unless the
person's current right names this role's chain for that picture.

| A picture may become | A picture never becomes |
| --- | --- |
| At most six notes in the model's words, about buildings, materials and colour, landscape and plants, food and goods, vehicles and boats, or scale | Anything about a person: clothing is closed to pictures because in a picture somebody wears it |
| A refusal with one reason | Text read from it, a place name, a search query, geometry or a stored derivative |

Every note kept passes, in order: its aspect is open to pictures; it holds no word of
`assets/catalogs/reference-sources/reference-picture-screen.v1.json` (people, faces, bodies and
the like); it holds no quotation mark and no capitalised word inside a sentence, so lettering and
proper names read from the picture are dropped; it does not end in a word cut at the length bound;
it names none of the workspace's saved names, as the request boundary recognises them; then the
screen every note passes. The role's model is MiniCPM-V-4_5 with no fallback, and its
timeout rests on code-made drawings ([record](evaluation/2026-10-07-reference-vision-latency.json)),
not photographs.

A person admits a picture as they admit a photograph (`POST /intake`, then `POST
/personal-admission`), granting the picture reader's right against the words the list's
`pictures.consent.uses` states. Each use in `exulanica/ingest/model-right-uses.v1.json` says where
it is offered (`offered_on`: `photos` when absent, or `reference_pictures`); the photograph
admission screen lists only uses offered on photographs, and the reference picture use is listed
only on this step, only while pictures are offered.

A picture may be read only while a privacy screening permits looking at it, a current right names
every model of the `reference_vision` chain for it, every such right was granted by the person
asking, the product has found no person in it, and its rendition exists
(`exulanica/api/reference_pictures.py`). Otherwise it is refused by code: `picture_not_screened`
(a picture of another workspace reads the same), `picture_not_admitted` (no such right, or one
another person granted, so a request reads only its requester's own pictures), `shows_people` (a
current person region, so the picture is never sent) or `picture_has_no_rendition`. The route asks
before queueing; the job asks again, on the read-only database, before each reading, and the request
policy checks the right once more when the reading is sent. Only the rendition's bytes are handed to
the reader, never the original. A picture's step ends `done` with how many notes were kept and
dropped, `refused` with the reader's reason (or `shows_people` found before sending), or `missed`
with a code (`pictures_not_read_here` where this process reads no pictures, `process_budget_spent`,
`picture_unreadable` when its bytes or the database could not be read, or a refusal above); a missed
picture makes the bundle partial. The bundle names each picture the workspace's request policy let
through, with the rights it was read under and the model that read it (the role's model when no
answer came back), and each note kept from a picture has basis `own_picture` and names its picture. A drafter is given web notes only unless it asks for
picture notes (section 9).

Stopping a picture's reading right, or deleting the picture, withdraws the notes made from it
(migration 0160). A finished request whose bundle names the stopped right, or names a picture a new
tombstone blocks (scope `capture` or `interval` naming it, or `workspace`), becomes `withdrawn`: its
bundle and the bundle's digest are cleared, its web notes go with it, and nothing else about it
changes. A deletion withdraws when it is asked, whatever its effective time. Database triggers do
this for every writer of a right's stop or a tombstone, in the writer's own workspace session, and a
restore that replays the stop or the tombstone withdraws again. A job whose picture is stopped while
it reads ends `withdrawn` rather than keep the notes: its finish takes the bundle's right rows and
the tombstones' lock before the request's row, the order every withdrawal takes them in. A drafter
asking for a withdrawn request's notes is refused `reference_withdrawn`; a document already drafted
from them keeps only the digest it recorded. An expired right is not a stop and withdraws nothing.

## 11. Limits

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
- **A word list catches the words it lists.** A note about a person in words the picture screen
  does not hold passes it; the reading model is also told to refuse a picture showing a person.
- **A name nobody saved can open a picture note.** The lettering check drops a capitalised word
  inside a sentence, not the first word of one, so a note beginning with a name read from the
  picture, or one the model supplied, is kept unless it is a saved name.
- **A picture is named when the policy let it through.** A later check (the budget, the provider)
  may still stop the call before anything is sent; the bundle then names a picture no model saw,
  which a withdrawal treats like one that was read.
- **No live search has run through the product.**

## 12. Verification

`tests/test_reference_sources.py`, `tests/test_reference_boundary.py`,
`tests/test_reference_notes.py`, `tests/test_reference_pictures.py` and
`tests/test_reference_settings.py` run without a database;
`tests/test_reference_store.py`, `tests/test_reference_worker.py`,
`tests/test_reference_routes.py`, `tests/test_reference_for_drafting.py`,
`tests/test_reference_worker_pictures.py`, `tests/test_reference_picture_admission.py` and
`tests/test_reference_withdrawal.py` run on PostgreSQL; a restore that withdraws again is in
`tests/test_restore_replay_withdrawals.py`.
`tests/reference_fixtures.py` makes a finished request with a scripted bundle for a drafter's own
tests. With every outside party scripted they show that
a saved person, a saved place, account words given to the job and a planted search result reach no
outgoing query, no stored row and no response, and that each guard can fail; the route tests run as
the runtime and read-only roles. Row-level security on
both tables is shown as the runtime role in `tests/test_row_level_security.py`. The three model
calls (planner, reader and picture reader) are registered paths of `tests/test_hosted_boundary.py`.
