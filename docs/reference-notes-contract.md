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
| A drafter's prompt carrying the notes | Implemented for the describe-a-town drafter (`POST /worlds/specification/drafts` with `reference_id`, prompt version 3, and a town Create makes from a sentence, `POST /worlds/drafts` with `reference_id`) and creature drafts (`POST /things/creatures`, purpose `things`, web or authorized selected-picture notes and prompt version 2); not built for the kind, look and piece drafters, each of which adds them in a prompt version of its own |
| Notes read from a person's own pictures: the reading call, its role, the checks on its notes, the job's picture step and the routes | Implemented, off by default (`EXULANICA_REFERENCE_PICTURES`) and never offered on a `public` installation; it stays off until Nebius Token Factory Sales confirms in writing that its terms allow it |
| A picture search for a creature: the person's words as its one search, the pictures it finds passed to its requester from memory and never stored | Implemented, off by default (`EXULANICA_REFERENCE_WEB_PICTURES`), offered to listed workspaces only and never on a `public` installation; no live picture search has run through the product |
| Keeping a picture a person picks from a picture search: fetched once, kept apart from their photographs, read and erased | Implemented (migration 0215, section 13), off with picture searches; no live fetch has run through the product |
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
No search fetches a picture; a person may keep one they pick (section 13). A request serves its notes, its steps and our own record of each
search (the source, its outcome, how many results, the credits it reported and when), never a
result and never the query text.

Where picture searches are offered, a person making a creature may ask for pictures from the web
(`web_pictures`). Their words, at most eight once saved names are replaced, are the one search, sent
without a planner. The pictures it finds, at most eight, each its address, its website and the
source's words about it, are passed to that person alone, from the memory of the process that ran
the job, for at most thirty minutes: their page shows each picture from its own website. Nothing of
a picture is written to the database, the store or a log, and nothing is fetched until the person
picks one and keeps it (section 13).

## 2. Sources are catalog data

`assets/catalogs/reference-sources/` holds versioned catalogs in the house envelope
(`exulanica/grammar/catalogs.py`), read by `exulanica/references/catalogs.py`:

- `reference-source.v2.json`: each source states whether it returns leads (words for drafting,
  never kept) or records (admissible facts), the one origin it is reached at, its credential
  variable, its terms as read (address, the date the provider states, the date read, the digest of
  the text read), which classes of its data are kept, shown and exported, which it passes (served to
  the person who asked from memory for one request, never kept, shown to anyone else or exported),
  whether it is offered to everyone or to the operator only, its cost per call and the one request
  shape its adapter sends. The reader refuses a leads source that keeps, shows or exports anything
  it returned, that passes anything but a picture's address and words, or that passes what it
  keeps, and any records source until record admission exists. `reference-source.v1.json`, which
  passes nothing, stays readable.
- `reference-aspect.v1.json`: the closed vocabulary for existing requests and world purposes.
  `reference-aspect.v2.json` adds anatomy and part layout for web notes with purpose `things`;
  materials and colour and rough scale keep their existing meanings. Selected things pictures
  use the expanded vocabulary with `reference-picture-screen.v2.json`; its no-person and no-writing
  word screens match v1. Historical picture requests retain their v1 vocabulary and screening.
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
| plan | Once the source is known to be configured, one call of the `reference_drafting` role writes at most three search subjects; skipped by a picture search, whose one subject is the person's words, about anatomy |
| search | Each subject passes the boundary; each search is admitted against the source's spending, sent, and recorded in `reference_lookup`; a picture search's pictures are held for its requester and the step states only how many (`pictures`) |
| read | One call of the `reference_drafting` role writes at most twelve notes from what the searches found; a note sharing six consecutive words with anything it was shown, or failing the screen, is dropped |
| read_picture | Before the searches, once for each picture the request names: the picture is read and its notes checked (section 10); the step names the picture's capture id |
| bundle | The kept notes become a reference bundle (v1 for existing/world requests, v2 for web-only things, v3 for selected things pictures), complete or partial with the steps it missed |

A request that did not ask for web notes skips plan, search and read; one that names no picture
has no picture step. Planner and reader words are versioned data. Existing requests and world
purposes use `exulanica/references/reference-prompts.v1.json` (content version 2); new `things`
requests without selected pictures use `reference-prompts.v3.json` (content version 3); things
requests with selected uploaded captures use `reference-prompts.v4.json` (content version 4).
Each request pins its file's digest.
The worker resolves that exact digest and purpose before admitting any provider call; an unknown
or incompatible digest fails with `reference_prompts_unavailable`, without substituting newer
words. Historical picture digests retain their prompt and closed vocabulary.

Bundle profiles version the closed note vocabulary. `exulanica.reference-bundle/v3` serves
things with creature-compatible picture aspects. Older profiles cannot carry these picture
aspects, even when a caller supplies a broader catalog. `exulanica.reference-bundle/v1` remains
readable with identical canonical bytes and digest. `exulanica.reference-bundle/v2` has the same
fields, serves only purpose `things`, and accepts the expanded web-note vocabulary. Database
constraint 0204 admits those two profiles and requires a v2 bundle's purpose to match its things
request. Other profiles are refused. The dual reader, renderer and existing creature consumer
preserve the bundle's digest through note usage and creature origin ingredients.

The things planner and reader describe anatomy, relative parts, materials, colour and rough scale
from text. They do not infer missing anatomy, dimensions, rigging or behavior, and do not claim to
have seen or matched an image. Notes remain suggestions: the creature drafter receives the
person's unchanged explicit edits with higher priority than reference features, while its supported
body and action checks remain authoritative. Prompt precedence is not proof that a model will
follow an edit or achieve visual resemblance; those need evaluated outputs.

Their role, `reference_drafting`, has the same model chain on
Nebius Token Factory as `structured_extraction` and is offered for no place-name right and no
personal model right, so no right granted for another role reaches a web lookup
([model selection](model-and-service-selection.md)).

Each step has its own share of the job's time, each from a measured latency by the model
manifest's timeout rule (the longest measured, times two, rounded up to five seconds): the planner
and the reader the `reference_drafting` role's timeout, a picture the `reference_vision` role's, and
the searches, which are sent at once, their own basis (`SEARCH_LONGEST_MS` in
`exulanica/references/adapters/base.py`, 17,440 ms across the eighteen searches measured on
2026-10-09). Both the search transport timeout and the search stage use this basis, giving a
35-second allowance under the manifest's rule and an 85-second web-only job. The job's
deadline is the sum of its steps' shares, so slow searches never take the reader's time. Each model
call is given its share, or what is left of the deadline when that is less; a call cut by it is
recorded with the reason `deadline`. Past the deadline the job ends partial with what it has, so a
person is never left waiting on a source.
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
| Our record of each search: source, aspect, query text, outcome, credits, provider request id, result count | `reference_lookup`, appended and never changed but for its query text cleared after 30 days, with the workspace | Any picture, picture address or picture description a source returned |
| The bundle's model calls: provider, role, model, tokens and USD | In the bundle | The person's description, after the job ends |
| Nothing of a withdrawn request's bundle | The request keeps its status `withdrawn` and steps | Notes made from a picture whose right stopped or which was deleted, or the web notes kept beside them |

Both tables are under forced row-level security keyed on the workspace. Query text is served to
nobody through the routes, and it is kept for 30 days after its search was sent
(`reference_lookup_query_retention()`, the one place the figure is written), then cleared; the rest
of the search record stays, with the time its query was cleared. The runtime role cannot change a
search record: the database's `reference_lookup_clear_queries`, run as the login-less definer owner,
clears a workspace's old queries, and the table's trigger allows exactly that change and no other. A
query is cleared at the first sweep after its 30 days: at each process start, for every workspace
the process knows; hourly in a process that plays reference jobs, for the workspaces it serves; and
whenever the workspace next uses the reference routes. A clear that fails is logged with its
error's class and tried again: by a worker a minute later, by startup and the routes at their next
sweep. It never fails the list, a request, the worker's claim or startup.

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
| `EXULANICA_REFERENCE_WEB_PICTURES` | Off unless `on`, `1`, `true` or `yes`: listed workspaces may also ask for picture searches. Any other value stops startup |
| `TAVILY_API_KEY` | The source's credential, named by its catalog entry |
| `EXULANICA_EGRESS_ALLOWLIST` | Must include `https://api.tavily.com` for web notes |

## 8. Routes and refusals

| Route | Permission | Does |
| --- | --- | --- |
| `GET /worlds/references` | `world.read` | The caller's recent requests, the capability to make one, `pictures` and `web_pictures` |
| `POST /worlds/references` | `world.write`, `model.invoke` and `references.request` | `{purpose, description, web, pictures?, web_pictures?, idempotency_key?}`; 202 with the request, 200 with the request a repeated key first made |
| `GET /worlds/references/{reference_id}` | `world.read` | One of the caller's own requests: steps, notes, missed steps, our search records |
| `GET /worlds/references/{reference_id}/pictures` | `world.read` | The pictures one of the caller's own picture searches found, while this process holds them: `{reference_id, pictures: [{n, address, website, description}], seconds_left}`, with `Cache-Control: no-store` |
| `POST /worlds/references/{reference_id}/cancel` | `world.write`, `model.invoke` and `references.request` | Stop one of the caller's own requests |
| `POST /worlds/references/{reference_id}/pictures/{n}/keep` | `world.write` and `references.request` | `{answer, licence?}`; keep the picture one of the caller's own picture searches found at place `n` (section 13); 201 with the kept picture |
| `GET /worlds/web-pictures`, `GET /worlds/web-pictures/{picture_id}` | `world.read` | The pictures the workspace keeps, newest first, or one of them |
| `GET /worlds/web-pictures/{picture_id}/bytes` | `world.read` | One kept picture's bytes, verified against their digest, `Cache-Control: private, no-store` |
| `DELETE /worlds/web-pictures/{picture_id}` | `world.write` and `deletion.write` | Erase one kept picture; 204 |

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
Naming pictures where they are not offered is 409 with the code the list's `pictures.code` states
(`reference_pictures_not_offered`, or why a request without web notes is refused here), answered
before anything about web notes, and naming one that may not be read is 409
`reference_picture_not_admitted` with its reason in the detail (section 10); either is refused
before anything is queued.

A picture search is a web search for a creature: `web_pictures` without `web` is 422
`web_pictures_need_web`, and for any purpose but `things` 422 `web_pictures_for_things`. Where
picture searches are not offered it is 409 with the code the list's `web_pictures.code` states
(`web_pictures_not_offered`, or why web notes are refused here), and words longer than eight, or
than the query's character limit, once saved names are replaced, are 422 `web_pictures_words`;
each is refused before anything is queued. A query the boundary refuses in the job sends nothing
and holds nothing. The pictures route answers 404 `pictures_not_held` when this process holds none
for the request: their thirty minutes are up, the request was stopped, the process restarted, or
another process ran the job. With more than one API process, a request's pictures are served only
by the process that ran its job. The list's `web_pictures` is `{offered, code, words}`, `words`
being 8.

The list's `pictures` is `{offered, code, maximum, consent?}`: `offered` is whether this workspace
may name pictures here, `code` says why not (`reference_pictures_not_offered`, or the code a request
without web notes would be refused with), `maximum` is 4, and `consent` holds `uses`, the model
right uses offered on this step with the exact words each is granted against and stopped with. It
is served while pictures are offered, and also whenever the caller holds a current picture right,
so a page can always offer the stop (a right is also stopped by id through
`POST /personal-admission/model-rights/{right_id}/withdraw`). A page offers no new pictures while
`offered` is false.

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
block is quoted, delimited material: v1 describes a place; v2 and v3 describe things and explicitly
states that the person's changes take precedence. Both deny instructional authority. Notes appear
between triple quotes, one line each, grouped by
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

The describe-a-town drafter is the first to take notes. `POST /worlds/specification/drafts` takes an
optional `reference_id`, a request made with purpose `world_draft`; it hands the drafter the web
notes alone, after the person's words in the same message, and asks with version 7 of its words
(`exulanica/selection/world-drafting.v7.json`), which says what the notes are and that the person's
words win. Saved names in the notes are replaced under the labels the words gave them. The form is
the same as without notes, and a phrase the drafter reports as not on the form must be copied from
the person's words, never from a note. The answer's `references` says whether the notes were used,
how many, and the request, bundle digest and bases that name them, or the code above when they were
not; any id that is not a request of the caller's own is answered `reference_unknown`, whoever made
it, and the draft is drafted from the words alone. A draft naming no reference asks with
version 2, byte for byte, and its `references` is null.

Create's making from a sentence takes notes the same way. `POST /worlds/drafts` takes an optional
`reference_id`, the person's own request with purpose `world_draft`; its job reads the notes with
the words, by the person who started it, with saved names replaced as above, and where the words
choose a town hands them to the same drafter with the same words. Where they choose another place,
whose kind drafter takes no notes yet, the world is drafted from the words alone. The draft's read
says which in `references`, as above, or `reference_not_for_this_tool`, with `searches` and
`spent_usd`, how many searches the person's own request sent and what its two model calls spent,
for the page's spend line. A start naming notes keeps the id in its terms, so one request key
never names two sets of notes; a start naming none keeps its terms and definition byte for byte.
Before a word is typed, the draft offer's `notes` says whether this person may ask for notes here
(by the codes of section 8, or `references_not_permitted` without `references.request`), the
planner's limit on searches, and the most the notes' two model calls may add at current rates.
Make a creature asks the same way: the creature offer's `notes` states the same figures for
purpose `things`, and a creature draft's `references` the same searches and spend
([things](things-contract.md)).

## 10. Notes from a person's own pictures

What a picture may become is fixed before any model sees one. One call of the `reference_vision`
role (`exulanica/references/pictures.py::read_picture`) reads the picture's rendition, the 768 px
copy with no location or camera details, and answers a strict form: `refuse`, one of
`shows_people`, `shows_text` or `not_a_place` for historical/place requests, with `not_a_thing`
replacing the last reason for selected things pictures, or null, and then at most six notes of at most 80
characters. A refusal keeps nothing of the picture but its reason. The form has no field for a
person, a place name or any writing, and nothing in a picture is located, cropped, embedded or
compared. The call declares its picture, so the workspace's request policy refuses it unless the
person's current right names this role's chain for that picture.

| A picture may become | A picture never becomes |
| --- | --- |
| At most six notes in the model's words, about buildings, materials and colour, landscape and plants, food and goods, vehicles and boats, or scale; selected things pictures also allow visible anatomy and relative part layout | Anything about a person: clothing is closed to pictures because in a picture somebody wears it |
| A refusal with one reason | Text read from it, a place name, a search query, geometry or a stored derivative |

Every note kept passes, in order: its aspect is open to pictures; it holds no word of
`assets/catalogs/reference-sources/reference-picture-screen.v1.json`, or the matching v2 screen
for selected things pictures (people, faces, bodies and
the like); it holds no quotation mark and no capitalised word inside a sentence, so lettering and
proper names read from the picture are dropped; it does not end in a word cut at the length bound;
it names none of the workspace's saved names, as the request boundary recognises them; then the
screen every note passes. The role's model is MiniCPM-V-4_5 with no fallback, and its
timeout rests on code-made drawings ([record](evaluation/2026-10-07-reference-vision-latency.json)),
not photographs.

A person admits a picture as they admit a photograph (`POST /intake`, then `POST
/personal-admission`), granting the picture reader's right against the words the list's
`pictures.consent.uses` states. Each use in version 2 of the model-right uses catalog says where
it is offered (`offered_on`: `photos` when absent, or `reference_pictures`); the photograph
admission screen lists only uses offered on photographs, and the reference picture use is listed
only on this step: while pictures are offered, and whenever the caller holds a current picture
right (section 8).

A picture may be read only while a privacy screening permits looking at it, a current right names
every model of the `reference_vision` chain for it, every such right was granted by the person
asking, the product has found no person in it, and its rendition exists
(`exulanica/api/reference_pictures.py`). Otherwise it is refused by code: `picture_not_screened`
(a picture of another workspace reads the same), `picture_not_admitted` (no such right, or one
another person granted, so a request reads only its requester's own pictures), `shows_people` (a
current person region, so the picture is never sent) or `picture_has_no_rendition`. The route asks
before queueing; the job asks again, on the read-only database, before each reading, and as the
reading is sent it asks once more that exactly the rights it was admitted under are still current,
that its requester has stopped none of their reading rights on it since the request was made, and
that no person has been found in it since; otherwise the step ends as above and nothing is sent.
The workspace's saved names are read once, before any picture is sent; if they cannot be read, each
picture step is missed (`saved_names_unread`). Only the rendition's bytes are handed to
the reader, never the original. A picture's step ends `done` with how many notes were kept and
dropped, `refused` with the reader's reason (or `shows_people` found before sending), or `missed`
with a code (`pictures_not_read_here` where this process reads no pictures, `process_budget_spent`,
`picture_unreadable` when its bytes or the database could not be read, or a refusal above); a missed
picture makes the bundle partial. The bundle names each picture the workspace's request policy let
through, with the rights it was read under and the model that read it (the role's model when no
answer came back), and each note kept from a picture has basis `own_picture` and names its picture.
A drafter is given web notes only unless it asks for picture notes (section 9).

Selected things pictures are semantic references for invented creatures. The v4 reader refuses
any human person, human part or depiction, and readable writing or a screen. A permitted drawing
of a nonhuman creature may yield visible anatomy, relative part layout and materials or colour;
it establishes no absolute dimensions, hidden parts, rig, actions or visual resemblance. The
existing word screens remain conservative. No selected pixels are passed to creature drafting.

The creature consumer accepts `own_picture` notes only from v3 bundles, while picture reading is
offered to that workspace and a fresh, explicitly bound `creature_drafter` right covers every
model of its chain. [Personal admission](personal-admission.md) owns that consent binding. The
worker declares the captures to the hosted request policy, disables response caching for these
image-derived requests, and rechecks exact rights, current notice and chain, screening, person
findings and feature eligibility before every attempt and in both creature-store transactions.
A stop, expiry or source erasure before final publication refuses the result; known completed
calls remain recorded as used. Creature-role stops prevent further creature use without withdrawing
the notes from other authorized consumers. Reader-role stops and source erasure withdraw the
whole reference bundle. Invented creature definitions already kept remain under their ordinary
erasure authority; retaining them grants no further source or note access.

Only the person who granted a picture's reading right, or an owner of the workspace, may stop it;
anyone else is answered 404 as for an id nobody granted. Stopping it ends every reading right not
yet withdrawn that its grantor holds on that picture, in one transaction of the withdraw route (the
rows locked in right id order before any changes), so nothing more of it is sent under another of
them. Stopping an already stopped right again ends only the rights granted at or before its first
stop, never a consent given since. Stopping it, or deleting the picture, withdraws the notes made
from it (migration 0160). A finished request whose bundle names the stopped right, or whose
requester granted the stopped right and whose bundle names its picture (so a right that expired and
was granted again is no way around a stop), or that names a picture a new tombstone blocks (scope
`capture` or `interval` naming it, or `workspace`), becomes `withdrawn`: its bundle and the bundle's
digest are cleared, its web notes go with it, and nothing else about it changes. A deletion
withdraws when it is asked, whatever its effective time. Database triggers do this for every writer
of a right's stop or a tombstone, in the writer's own workspace session, and a restore that replays
the stop or the tombstone withdraws again. A job whose picture is stopped while it reads ends
`withdrawn` rather than keep the notes: its finish ends withdrawn when a right its bundle names was
stopped, when its requester stopped any reading right on one of its pictures at or after the instant
the request was made, or when a tombstone blocks one of its pictures. It asks under the
per-workspace lifecycle lock that every stop of a reading right and every tombstone also takes
before it withdraws, so a stop or deletion made while a finish is under way, of any right, including
one granted meanwhile, is seen by one of the two. A drafter asking for a withdrawn request's notes
is refused `reference_withdrawn`; a document already drafted from them keeps only the digest it
recorded. An expired right is not a stop and withdraws nothing.

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
- **A query can outlive its 30 days.** It is cleared at the first sweep after them (section 5). A
  process that only knows a workspace sweeps it when it starts, so a query that turns 30 days old
  in a workspace no process has started, served or heard from since keeps its text until one does;
  and physical copies (below) keep it as long as those copies are kept. A restore of a backup taken
  before a clear brings the text back into the live table until the restored installation's next
  sweep. A judge seed carries the text, and a judge stack does not clear it: its role cannot run the
  clear. No erasure path removes a workspace's reference rows themselves yet.
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
- **"Own picture" means a picture the requester granted a right on.** Captures record no uploader,
  so a person who may admit a workspace's photographs may grant their own picture right on any of
  them and then name it; a request reads a picture only under rights its requester granted, and
  another person's right never stands in for it.
- **A picture is named when the policy let it through.** A later check (the budget, the provider)
  may still stop the call before anything is sent; the bundle then names a picture no model saw,
  which a withdrawal treats like one that was read.
- **No live search has run through the product.**

## 12. Verification

`tests/test_reference_sources.py`, `tests/test_reference_boundary.py`,
`tests/test_reference_notes.py`, `tests/test_reference_pictures.py` and
`tests/test_reference_settings.py` run without a database, as does most of
`tests/test_reference_web_pictures.py`, whose picture search through the worker and routes runs on
PostgreSQL; `tests/test_reference_store.py`,
`tests/test_reference_worker.py`, `tests/test_reference_routes.py`,
`tests/test_reference_for_drafting.py`, `tests/test_reference_worker_pictures.py`,
`tests/test_reference_picture_admission.py`, `tests/test_reference_withdrawal.py` and
`tests/test_reference_query_retention.py` run on PostgreSQL; a restore that withdraws again is in
`tests/test_restore_replay_withdrawals.py`. `tests/reference_fixtures.py` makes a finished request
with a scripted bundle for a drafter's own tests. With every outside party scripted they show that a
saved person, a saved place, account words given to the job and a planted search result reach no
outgoing query, no stored row and no response, and that each guard can fail; the route tests run as
the runtime and read-only roles. Row-level security on both tables is shown as the runtime role in
`tests/test_row_level_security.py`. The three model calls (planner, reader and picture reader) are
registered paths of `tests/test_hosted_boundary.py`.

## 13. Pictures a person keeps

A person who picks a picture from a picture search, and says they may use it for their own world,
keeps that one picture. It is kept apart from their own photographs: it is never a capture, so no
library, admission, scene, world input, export or model hand-over that reads a person's photographs
sees it (`exulanica/world/kept_web_pictures.py`, migration 0215).

| What | How |
| --- | --- |
| The kept bytes | The fetched picture decoded within the photograph pipeline's pixel budget, one frame only, turned upright and written again in its own format with no metadata: no EXIF, XMP, ICC profile, text chunk or comment. Only JPEG, PNG and WebP of at most 10 MiB and 16,384 pixels a side are kept |
| Where | By digest in the workspace's own `web-pictures` namespace of the content store, recorded in its inventory (`web_picture_object`) before the bytes are written |
| The record | `web_picture`: the digests of what was fetched and what was kept, media type, size and pixel size, the picture's address and website, its licence where its source states one, the person's answer (`made_or_permitted`, `licence_allows` with the licence it names, or `private_world_only`), who answered, the picture search it came from, and when. Never the source's words about the picture |
| Erasure | Asked by the person who kept the picture, or an owner: a `web_picture` tombstone and a `web_picture_erasure` row naming the picture, its bytes' digest and that tombstone, in one transaction. The row's trigger deletes the record and enqueues the bytes for `exulanica-purge`, unless another kept picture of the workspace holds the same bytes. A workspace's tombstone deletes every record and enqueues every object. A restore carries the erasure row before it replays the tombstone, which then enqueues the bytes |
| Who reads it | Only routes that name the table, for the workspace that keeps it |
| Keeping one | `POST /worlds/references/{reference_id}/pictures/{n}/keep`, by the search's requester while this process holds its pictures: the answer is checked, the picture fetched once from its address under the fetch rules the [security floor](security-floor.md) names (`exulanica/references/picture_fetch.py`), cleaned and kept, recording the address and website the person picked. A fetch refused for the picture is 422 with its code (`picture_address_refused`, `picture_host_not_public`, `picture_too_many_redirects`, `picture_not_an_image`, `picture_too_large`); one the website failed is 502 (`picture_unreachable`, `picture_timed_out`); a picture the keeper refuses is 422 (`picture_not_an_image`, `picture_format_not_kept`, `picture_too_many_pixels`, `licence_missing`); a workspace being erased is 409. Where picture searches are not offered it is 409 `web_pictures_not_offered`; pictures no longer held are 404 `pictures_not_held`, and a place the search did not fill 404 `picture_unknown` |
| Erasing one | `DELETE /worlds/web-pictures/{picture_id}`: the keeper, or an owner of the workspace; anyone else is 403 `picture_not_yours`, and a picture the workspace does not keep 404 `unknown_web_picture` |

**No hosted provider model ever receives a web picture**: not a vision, language or notes model,
nor any other model reached through a provider. The one model that may read a kept picture is its
owner's own creature job, an open-weights model run on the product's own GPU job, which is the
reason a person keeps the picture; what that job makes stays private as the picture does. That job
is not built.

A kept picture and anything made from it stay private: a judge seed refuses a workspace that keeps
one (`exulanica/orchestration/judge_seed.py`), and no export reads the table.
