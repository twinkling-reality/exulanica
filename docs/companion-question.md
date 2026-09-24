# Companion questions, memory and proposals

This contract owns grounded questions, retained conversation state and the boundary between a
model answer and a reviewed editing proposal. The Companion is the person's AI partner within the
world. [Product direction](product-direction.md) owns its broader role and continuity goals;
[interaction policy](interaction-policy-backend.md) owns durable capability policy.

## Reading map

- [Request path](#request-path)
- [Answer and source boundaries](#answer-and-source-boundaries)
- [Execution provenance](#execution-provenance)
- [Conversation memory](#conversation-memory)
- [Appearance proposals](#appearance-proposals)
- [Evidence and limits](#evidence-and-limits)

## Request path

The [Selection routes](../exulanica/api/routes/selection.py) expose question planning, answering,
evidence packets and appearance proposals, and the
[environment proposal route](../exulanica/api/routes/selection_environment.py) proposes the NYC
environment panel's typed edits. The [question implementation](../exulanica/selection/question.py)
sequences the path: the [planner](../exulanica/selection/planner.py) proposes a Selection from the
question, and the question implementation validates and executes it, builds a bounded packet,
composes and validates the answer, with the supported repair path. Both system prompts and the
version they are recorded under are in [prompts](../exulanica/selection/prompts.py). The path
records per-question model execution with [calls](../exulanica/selection/calls.py) rather than
inferring execution from the manifest.

The browser's `companion-ask-api.ts` calls `POST /selection/ask` and obtains the packet needed to
resolve citations. The [application composition](../web/packages/app/src/main.ts) connects question,
appearance and conversation-memory clients. The [frontend contract](atlas-frontend-integration.md)
defines how a reviewed proposal becomes a preview and an accepted world change.

A question is asked in a world. `POST /selection`, `POST /selection/ask` and `POST /selection/packet`
require the open world as `world_id`, and a world the workspace does not hold answers
`404 unknown_reference`. Photographs and admitted environment sources belong to the workspace and
answer the same in every world. The authored environment instances, synthetic inhabitants and
simulation events a content answer may cite are the named world's and no other world's, and the
host is asked to authorize only that world's society inputs (`execute` in
`exulanica/selection/executor.py`). `tests/test_companion_reads_one_world.py` asks in each of two
worlds that stand over one place, through these routes, and no answer, evidence packet or content
page names the other world.

A question that cannot be understood, one with no supporting evidence, unavailable models and a
failed network request remain distinguishable. None authorizes an invented factual answer. The
exact response shapes and refusal codes live in the route models and API schema snapshots.

## Answer and source boundaries

**It is a read and it cannot become a write.** `interaction-model.md` 4.3 fixes that free text "is
parsed into the same update proposal draft that a choice would produce and goes through the
IDENTICAL confirmation flow", and that "No path writes to the graph without a proposal". That is
still true of every utterance the parser can turn into a change. The question branch is what
happens when it cannot, and the guarantee is structural rather than promised:

* `companion-ask-api.ts` returns a `CompanionAnswer`. Nothing in the workspace turns one into a
  `ProposalDraft`, and `companion.ts` reaches `onAwaitingConfirmation` only from a
  `SelectionOutcome` that `companion-runtime` produced.
* The gate never leaves `session.ts`. `.dependency-cruiser.cjs` names that one file, so a second
  importer of `@exulanica/graph-client/mutations` fails the boundary check rather than a review.
* The rail an answer renders holds two controls and, for an answer about a place the account holder
  named, the control for where that place's name may go; none is an assertion about anybody.

**A question it cannot read is an abstention, not an error.** The path has four ways to say
nothing and they are four different facts: nothing matched, the matches are unconfirmed, the
answer would need a modality this corpus does not have, and the question never became a search at
all. Merging the last into the first would assert something about the user's photographs from a
failure to read their sentence.

**A failure is stated, never substituted.** A 503 from an instance with no model credential, a
refusal, a lost session and a request that never arrived are four different facts, and the
encounter says which. There is no path from a failed question to a sentence from the copy table
dressed as a reply.

**Citations open through the masked route.** The answer names its evidence with per-request
citation tokens; `EvidenceCache` opens a photograph by span id through `/evidence/{span}/masked`,
which returns the masked derivative when somebody in the frame is hidden and refuses outright
when a mask is required and missing. The permalink route `GET /evidence?uri=` resolves the same
citation and returns the original bytes, so pointing a chip at it would be a route by which an
unconsented person reached a viewer's screen. That is why the client makes a second request:
`POST /selection/packet` is what carries both the permalink and the span id.

**The two responses are joined on the permalink, never on the token.** Token namespaces are
random per request, so the packet's tokens are not the answer's tokens. Matching them would
resolve nothing, silently, and every chip would open nothing.

**A citation opens inside the Companion.** A chip, or `E`, draws the masked photograph in the
Companion's own surface in place of the answer or question that cited it, with the date its citation
carries and a way back: `Back to the answer`, or `Back to the question` for the photograph a
question is about (`web/packages/app/src/ui/companion-evidence.ts`, and `showEvidence` in
`web/packages/app/src/ui/companion-encounter.ts`). Escape closes the photograph before it closes the
Companion, whether or not the keyboard is in the Companion: inside it the Companion's own handler
takes the key, and outside it the page's handler in
`web/packages/app/src/composition/input-modes.ts` offers the key to the photograph before dismissing
the Companion. Going back either way returns the keyboard to what opened the photograph, the
answer's chip or the question's `Open the source` button. A read is drawn only while its photograph
is still the one open, so going back, opening another or sending the Companion away before it
arrives leaves it undrawn, and opening a photograph again while its first read is under way shares
that read rather than making a second copy (`web/packages/app/src/evidence.ts`). A photograph that
does not open, because it was deleted, is not available to this session or needs a mask that does
not exist, is said in words with the reason the server gave, and nothing is drawn in its place: a
stand-in picture would claim the evidence exists and looks like that. A copy the page has since
released is said the same way, as "This page no longer holds its copy. Go back and open it again."
`web/packages/app/test/companion-evidence.test.ts` and
`web/packages/app/test/evidence-cache.test.ts` hold both faces, the late reads, the shared read and
the keyboard, and the end-to-end run recorded in
`docs/evaluation/2026-09-23-companion-place-link-outcome.json` shows both faces in the running app.

**Photograph-derived text reaches the composer only under a personal model right.** A packet
carries the claims stored about each photograph it cites: a transcribed sign, a described scene, a
recorded date. Those are personal exactly when the photograph is, and the account holder has
decided that derived text goes to a hosted model only under a current right naming that model and
its destination, the same as the photograph's bytes. `answer_question` therefore requires a
`before_compose` check, which the API supplies from `exulanica/api/composer_rights.py` because
answering and ingesting are sibling workflows that may not import each other. Before the composer
is called, every photograph the packet cites must pass `require_model_right` for every model the
`reasoning_cheap` role can reach, or be screened under a synthetic or benchmark exemption. It is
all or nothing: if any photograph fails, no composing model is called, the deterministic answer is rendered
locally from the same packet, and the execution block carries `model_right_refused` with the
reason. Composing from the permitted part alone would answer about some photographs while seeming
to answer about all of them. A personal photograph admitted without a right for that role is
therefore answered deterministically, never composed. The composer's request also names the
packet's captures, so the boundary described below asks the same right again as the request
leaves; a right withdrawn between the two checks refuses the request there, with nothing sent.

**Saved names are filtered before hosted requests.** A name exists in this
product only because the account holder typed it: who a person is, what a place is called. A
person's name never goes to a hosted model, with or without a right, and a confirmed place name goes
only under a right the account holder grants for that place and that model. Every hosted request
passes one boundary that applies the rule, described after the limitations below. The requests this
section describes also replace, before the request is built, every saved name no right can release:
a person's, a voice's, an object's, an event's and a conversation's. A place's name is left to the
boundary, which sends it or withholds it for each request and each hand-over. One record per
question, `RequestNames` in `exulanica/selection/request_names.py`, reads the saved names once
through `exulanica/epistemics/saved_names.py` and holds the placeholder each entity it recognises
is given, and every request of the question hands that record to the boundary, so a place withheld
from a request is written with the same placeholder in the question, the catalogue and the packet.
A saved name is recognised whole, case-insensitively and as a whole word; a person's or a voice's
name is also recognised by any part of at least three letters, because people are named by first
name, while other names are recognised whole only, because their parts are ordinary words and a
saved "Lantern House" must not turn "photos of the house" into a filter on one place. Every saved
name is recognised in one pass, longest first, so a person's first name inside a place's name does
not break the place's name apart. Each entity recognised gets a placeholder of its class,
`[person A]`, `[place A]`, stable for the whole question. A place whose whole saved name reads as
another saved name, as a place called Rose does beside a person saved as Rose Smith, is written by
its placeholder, given by its id, so the boundary is never left to guess which of the two the words
mean. The planner's catalogue lists every entity as an id and a class, and an entity the question
named as the question is sent: a person by its placeholder, a place by its name for the boundary to
send or withhold. The question the planner, the composer, the request classifier and both drafters
are sent is prepared the same way, and so is every line of packet text, because a saved name can be
painted on a building or written on a shirt as easily as typed. The answer's `names` field maps each
placeholder to its entity so the client can restore the name from the account holder's own data.
What still works: asking about anything by a name the account holder has saved, which is resolved
locally and reaches the plan as an id. What is lost: the model can no longer pick a person out from
a description, nor a place the account holder has not allowed for it. Two limitations, stated
rather than hidden. A name the account holder has not saved cannot be
recognised, so it leaves as the text it was typed as. And a saved name that is also an ordinary
word is replaced wherever that word appears, which for a person includes each part of their name:
somebody saved as Rose makes "the rose garden" arrive as "the [person A] garden". That is a
deliberate bias towards privacy, and it can make a question harder for the model to read.

**The browser puts each name back from the account holder's own library.** One resolver,
`companionNames` in `web/packages/app/src/companion-names.ts`, draws every clause of an answer and
every turn's words in the Companion's speech band. For each placeholder the text carries, the
answer's `names` says which entity it stands for, and the name shown is that entity's `displayName`
in the graph this session read with the account holder's own credential (`GET /graph`), read when
the answer is drawn. Only a person's own naming writes that column (`display_name` in
`exulanica/migrations/0001_spine.sql`), and nothing a model wrote is read as a name: not the
sentence around a placeholder and not the letters inside one. The composer does not always copy a
placeholder exactly, and the end-to-end run recorded in
`docs/evaluation/2026-09-23-companion-place-link-outcome.json` found `place A` and `PLACE A` beside
`[place A]`, so an answer's own labels are recognised without their brackets too, the class word in
lower case, with a capital or in capitals (`place A`, `Place A`, `PLACE A`) and the letters as the
server wrote them, but only where a label cannot be an ordinary word. A label whose letters could be
a word, `I` or `O`, `A` after a class word in capitals, or two letters or more, is restored only
where punctuation or the end of the text follows it, so "the place I visited" keeps its pronoun and
"taken at place I." is restored. In text with no `names`, only a bracketed placeholder is
recognised. A placeholder the page cannot resolve is said in words and never shown as brackets:

| Why the name is not shown | What the Companion says |
| --- | --- |
| The entity has no name | a place you have not named |
| The person's consent was withdrawn | a person whose consent was withdrawn |
| The entity was merged into another | a place you merged into another |
| The account holder deleted the entity | a place no longer in your library |
| The library this page read does not hold the entity | a place whose name this page has not loaded |
| The text does not say which entity it is | a place this answer does not name |

The noun follows the placeholder's class, `a person`, `a place`, `an object` and so on, from
`web/packages/app/src/ui/copy.ts`, and `tests/test_companion_placeholder_parity.py` holds the
browser's placeholder pattern and naming predicate to the server's. What it does not do: an answer
the Companion remembers across a reload keeps its text and not its `names`, because
`companion_answer` has no column for them, so each placeholder in it reads as one this answer does
not name and none is restored; an appearance proposal's words arrive with no `names` either; and a
name is the one in the library the page holds when the answer is drawn, so an answer drawn again in
the same page session, once the page has read a rename, shows the new name, even where the
placeholder stood for the words on a sign.

**The composer is told where the account holder confirmed a photograph was taken.** A Selection
filtered by a place holds a photograph because of a confirmed link from the photograph's place
occurrence to that place, and only a person's decision writes a confirmed link
(`confirmed_needs_a_human` in `exulanica/migrations/0001_spine.sql`). `build_packet` in
`exulanica/selection/packet.py` keeps that link on the photograph's line as the place's id
(`ConfirmedPlace`), which adds no line and no token. `_without_names` in
`exulanica/selection/question.py` names the place from the request's record, by its id and from its
own saved name alone, and `_render_packet` states it under the photograph's token as
`user_confirmed_place: [place A]`. The composer's prompt, `selection-7`, says that line is the
user's confirmation that the photograph was taken there, which supports a historical clause citing
it, and that it says nothing about what the photograph shows. Without it, each such photograph
reached the composer as a bare line with no description, and asked which photographs were taken at
the place, the composer answered that no photograph could be identified as taken there (measured
under Evidence and limits). The line names the place as the request names it: by its placeholder,
or by its saved name where the account holder allowed that place's name for the composer, whose
role, `reasoning_cheap`, the uses file (`exulanica/consent/place-name-uses.v1.json`) offers for
writing the Companion's answer. A person or an object linked the same way is not stated, because
telling a hosted model who is in a photograph is a decision about people that this path does not
make, and a place with no saved name has no placeholder and is not stated.
`tests/test_companion_place_link.py` holds the line, the placeholder given by id, and, with no right
granted, the absence of the saved name from every request.

**Every hosted request passes one boundary.** `ModelClient` in `exulanica/models/client.py` hands
every request it sends, from `chat`, `structured`, `vision` and `embed` alike, to the policies
attached to it before the response cache key is computed, and sends exactly the text they return.
A client with no policy refuses to send, by name, with `NoHostedRequestPolicy`
(`exulanica/models/policy.py`), and the one client an instance builds carries none. The policy
that applies the account holder's rules is `WorkspaceRequestPolicy` in
`exulanica/epistemics/hosted_requests.py`, attached where the workspace is known: a route sends
through `Services.hosted_model`, the caption-vector pass and the vision stage attach it for the
photograph whose text or bytes they send, and the society runtime for the decision it asks for. As each request leaves
it:

* replaces every saved name in every user and assistant message and every embedding input: a
  person's, a voice's, an object's, an event's and a conversation's always, and a place's unless
  the place-name right releases it for every model that request's role can reach, at its
  destination;
* writes each name it withholds with the placeholder the caller's record gives that entity when the
  request carries one (`placeholders` on `chat` and `structured`), so the requests of one question
  name a withheld place one way. It refuses a record that gives two entities one label, gives an
  entity something that is not a placeholder, or gives an entity another class's placeholder, and it
  drops an entry for an entity with no saved name and keeps that label reserved. `embed` and
  `vision` take no record: an embedding request is text for a vector with nothing to restore, and
  the vision stage sends the product's own instruction and a photograph;
* checks a current personal model right for every photograph the request names, all or nothing:
  the composer names its packet's captures, the caption pass its capture, and the vision stage its
  photograph; a capture screened under a synthetic or benchmark authority passes as it does
  everywhere else, and a request with an image part and no photograph is refused.

`tests/test_hosted_boundary.py` finds every hosted call the product package makes by walking its
syntax trees, requires each to be a registered path with a scripted run, and runs each through the
code the product runs over a person and a place saved through `name_occurrence` and written on a
photograph's sign. No request carries either name, system messages included; every request the
transport recorded was admitted by the policy, text for text; and the five paths whose call site
prepares names itself hold with that preparation disabled.

**Which requests honour a place right.** Every request of a role the uses file offers
(`exulanica/consent/place-name-uses.v1.json`) leaves a place's name to the boundary, and the file
names each such request path by module and function: the caption-vector pass and the embedding of a
question's query for the embedding role, the composer for `reasoning_cheap`, and the planner, the
request classifier, the appearance drafter and the environment drafter for `structured_extraction`.
A place whose right names a role's whole chain at its endpoint reaches that role's requests by name,
and a stop holds it back from the next request; a person's name reaches none of them, with or
without a right. The caption pass sends a photograph's text as it is stored, so a sign naming an
allowed place goes by that name. The query carries a place's name only where the query itself names
it, as a plan the caller supplies can: the planner puts a place the question names in the plan's
place dimension, by id, and removes both its name and its placeholder from the semantic query, so
neither becomes a search term. A decision changes the requests sent after it and no vector already
stored: the index is keyed by the text as stored, so a caption embedded before a grant is not sent
again, and a vector made while the name was allowed stays after a stop. The resolver that reads the
right, `released_place_names` in `exulanica/consent/place_name_rights.py`, is the one every instance
runs: `build_services` injects it as `Services.released_place_names`, which the Companion's routes
and the API's derivative worker ask, and `exulanica/ingest/worker_command.py` gives it to the
standalone worker's caption pass. A `Services` built by hand, as most tests build one, keeps the
resolver that releases nothing. A society decision releases no place's name on whatever role it
runs: `Services.request_policy` requires the release to be named, and the society runtime names
`no_place_released`, because a grant for the Companion's roles describes the Companion's requests.
The vision stage sends the product's own instruction and the photograph, and its policy releases no
place's name. `tests/test_place_name_release_paths.py` runs each path the uses file names and
requires it to carry an allowed name, so a use cannot be offered while inert, and holds that a
request to another destination, or one that can reach a model the grant does not name, carries the
placeholder. `tests/test_companion_place_release.py` holds that a place allowed for the composer
reaches the composer's request and no other, that a stop holds the composer's next request back, and
that no person's name leaves on any registered path with every place use allowed, whether the
boundary, the call sites or both prepare the names.
`tests/test_society_decision_place_names_postgres.py` holds the society decision.

**What the boundary does not do.** It never rewrites a system message: a system message is product
instruction, and rewriting one would put `[person A]` for every "may" in every prompt of somebody
saved as May. The byte test holds that no system message on any path carries a saved name
instead. It cannot recognise a name the account holder has not saved. And an embedding request
carries no record, so the boundary assigns its placeholders per request, in the order it recognises
names: in embedding text `[place A]` is a different place in each caption and in each query, and a
query about one withheld place shares that token with every caption that holds any saved place.
That leaks nothing, and what it costs vector retrieval is measured under Evidence and limits.

## Execution provenance

The Selection response's execution block records prompt version, validator rejections and model
calls returned to the workflow. A call identifies requested and served model, fallback use,
attempts, latency and available token counts. Provider usage that is absent remains absent rather
than becoming a measured zero. Read the exact fields in
[Selection response models](../exulanica/api/routes/selection.py).

The list is per question, not the process-wide model ledger. A discarded answer that returned a
model result can have a recorded call; a failure before a result reaches the workflow need not have
one. The list is therefore not a complete transport audit. The transport and request-policy evidence
have their own scope.

A deterministic or abstained answer does not mean no model executed: a planner can run even when
there is no composing call. UI provenance must distinguish search/planning from answer composition.
Use actual execution metadata to describe model use; manifest configuration alone is insufficient.

## Conversation memory

The [memory repository](../exulanica/world/companion_memory.py) and
[authenticated routes](../exulanica/api/routes/companion.py) own retained answers, escape choices,
corrections and deletion. The actor is scoped from the authenticated session, not supplied as a
request-body authority. Workspace isolation and actor scoping are both required.

| Route | Operation |
| --- | --- |
| `GET /companion/memory/recent` | Read the actor's retained answers and escapes |
| `POST /companion/memory/answers` | Retain an answer with its citation bindings |
| `POST /companion/memory/escapes` | Retain a supported escape choice |
| `POST /companion/memory/answers/{id}/corrections` | Record a correction linked to an answer |
| `DELETE /companion/memory/answers/{id}` | Withdraw the answer lineage |

Conversation text is retained separately from durable interaction policy. It may inform a turn
without granting a capability. The policy plane refuses its declared conversation-input keys;
that key check does not detect arbitrary text hidden under an unrelated key. Source rights and
hosted-request policy still govern model use.

Stored citation bindings preserve the dependency through which source withdrawal reaches an
answer. An answer with unresolved cited sources is not stored by dropping the unavailable citations.
Deleting an answer withdraws its correction lineage as well, so a correction cannot keep the
removed text visible through its quotation.

The browser [memory client](../web/packages/app/src/companion-memory-api.ts) loads retained state.
`memoryFromPersisted` in the [Companion runtime](../web/packages/companion-runtime/src/memory.ts)
replays supported escapes through the same cooldown logic as a live session. Per-session suppression
and the no-penalty Later choice do not become permanent suppression after reload. A failed memory
write is a durability failure, distinct from displaying a correctly supported answer.

These mechanisms establish bounded conversation persistence. They do not by themselves establish
autonomous activity, complete lifelong shared context or model training.

## Appearance proposals

`POST /selection/appearance` returns a supported appearance proposal or refusal. It does not apply
the proposal. The [proposal implementation](../exulanica/selection/proposal.py) classifies the request,
drafts from the reviewed style registry and validates the result. A question about evidence and a
request to change appearance have distinct inputs and responsibilities.

A proposal cites the evidence of the world it is asked in: the slots that world's current topology
binds, then the reviewed photographs attached to its saved entry that are available when it is
read, each named to the drafter by its attachment id alone. A world with neither, such as a starter
with no attached photograph, is refused as `unsupported_reference`, in words saying that attaching a
reviewed photograph makes a proposal possible.

The drafter's schema derives from the registry's profiles, controls, ranges and choices. An invalid
value is refused, not silently converted into a different proposed value. Apply remains a separate
reviewed operation through [world style](world-style-backend.md) and the
[customization contract](atlas-world-customization-contract.md). Conflicts require review against
the relevant version; natural language does not bypass the same validation as direct controls.

Broader structural edits and environment proposals follow their own registered capabilities and
contracts. This route's existence does not establish arbitrary creation, simulation control or a
model's permission to act without review.

## Evidence and limits

The [model selection record](model-and-service-selection.md) identifies implemented callers and
measured candidate comparisons. The question, memory, proposal, prompt and place-query investigations
are retained with their original inputs and limitations in the
[fixed implementation history](https://github.com/twinkling-reality/exulanica/blob/857cffe730dad97f9edb34535c773115277e2769/docs/companion-question.md).
Some cited campaign artifacts are local-only; a clone does not contain them. Do not present a
historical result, patch or unconfigured route as a live end-to-end demonstration.

**A confirmed place, end to end.** A place-class entity comes from the vision role's place
proposal, which `exulanica/ingest/vision.py` makes under a versioned rule: a place is written only
when its name is read whole on a sign the photograph transcribes
(`exulanica/ingest/place_proposal.py`, measured in
`docs/evaluation/2026-09-23-vision-place-proposal-d-outcome.json`). One measurement takes that
proposal through to the answer a person reads, on two synthetic workspaces on an acceptance runtime
with the model client, through the routes the browser uses: four synthetic drawings of one place,
MIRELAND HALL (two whole nameplates, one with its last word covered, one with no text), each with a
recorded capture time, admitted with the model rights the synthetic account holder granted. The
vision stage wrote the place for the two whole nameplates and for neither of the others, and the
measuring script confirmed it as the account holder. Three questions, registered with the answers
the photographs support before any model call, were asked once each, with the packet before the
change (`selection-6`) and with the confirmed place on each photograph's line (`selection-7`):

| Question | `selection-6` | `selection-7` |
| --- | --- | --- |
| What does the sign say at Mireland Hall? | wrong: "The sign says this photograph." | right: "The sign reads '[place A]'." |
| Which of my photographs were taken at Mireland Hall? | wrong: "No description mentions [place A], so no photograph can be identified as taken there." | right: "These photographs were taken at place A.", citing both |
| When were my photographs at Mireland Hall taken? | wrong: "The provided evidence does not contain any information about place A." | right: "Your photographs were taken on 2026-08-14 and 2026-08-16.", citing both |

In the running app the Companion showed each answer with the confirmed name in place of the
placeholder, opened the cited photograph inside the Companion from the masked route, and said "This
photograph cannot be shown." with no picture when the capture script answered that read 410. Costs,
from the provider's reported usage: 0.00771565 and 0.00864106 US dollars for the two arms and
0.00282130 for the final browser run. What this does not establish: one draw per question per arm,
so a difference is one observation each and not a rate; synthetic drawings of one place; English
questions; no remembered answer or rename. The records are
`docs/evaluation/2026-09-23-companion-place-link-preregistration.json` and
`docs/evaluation/2026-09-23-companion-place-link-outcome.json`.

**Caption vectors in use.** The derivative worker runs the caption-vector pass for each admitted
photograph, through the boundary above and under a personal model right for the embedding role
(`exulanica/ingest/worker_command.py`); a capture's tombstone reaches its caption vectors
(migration 0044 records each vector a tombstone targets, and the purge worker deletes it;
`tests/test_caption_vector_lifecycle.py`). In the measurement above, the one question whose plan
carried a semantic query made one query-vector call each time it was asked, of two prompt tokens,
taking 7858, 9586 and 10907 ms. Embedding quality, the 0.65 threshold and latency over a large
corpus are not measured.

**Withheld places in vector search.** One pre-registered measurement compared three things a
withheld place's name can become in text sent for a vector: the placeholder the boundary assigns
per request, one placeholder per saved place for the whole workspace (the alternative), and the
place's name allowed through `POST /place-name-rights` (a reference, never a candidate). Twenty-four
synthetic drawings went through the product's admission, vision and naming path; the vision stage
proposed a place on twenty, and the six places drawn on three photographs each were saved. Twelve
queries named a place and five described content. Each was scored by R-precision, the share of the
photographs it should find that rank among its first that many, over the caption vectors alone and
in the order the executor returns:

| Mean R-precision | Per request | Per place | Allowed name |
| --- | --- | --- | --- |
| Place-named queries, vectors alone | 0.1667 | 0.7778 | 1.0000 |
| Place-named queries, as the executor ranks | 0.8889 | 0.9722 | 1.0000 |
| Content queries, vectors alone | 0.5692 | 0.5205 | 0.5538 |
| Content queries, as the executor ranks | 0.4897 | 0.4897 | 0.4897 |

The alternative gained 0.6111 over the vectors alone and 0.0833 as the executor ranks, and the
registered gate asked for 0.25 and 0.10, so the placeholder assigned per request stays. The
executor's lexical match reads each caption as stored, with the place's name in it, which is the
likely reason it recovers most of what the vectors lose; that was not measured separately. A pass
would not have been enough on its own: a placeholder stable across requests lets a provider link
the photographs of one withheld place, so adopting one needs the account holder's decision. What
this does not establish: synthetic drawings, English names and six places; one run of captions,
shared by every arm; and place-named queries that stand for a plan a person supplies, since a
question asked in words never puts a place's name or placeholder in its query. No person is named
in the corpus. The run made 191 model calls for 0.03437730 US dollars, from the provider's reported
usage. The records are `docs/evaluation/2026-09-23-embedding-placeholders-preregistration.json` and
`docs/evaluation/2026-09-23-embedding-placeholders-outcome.json`, made by
`scripts/measure_embedding_placeholders.py`.

Changes to this contract require checking the affected route, repository, request-policy and
browser boundary. Broader continuity, live-model usefulness and personal-source acceptance need
explicit evidence beyond fixture checks or storing a transcript.
