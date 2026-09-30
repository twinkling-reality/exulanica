# Companion questions, memory and proposals

This contract owns grounded questions, retained conversation state and the boundary between a
model answer and a reviewed editing proposal. The Companion is the person's AI partner within the
world. [Product direction](product-direction.md) owns its broader role and continuity goals;
[world version authorities](world-version-authorities.md#comfort-settings-authority) own durable
comfort-settings policy.

## Reading map

- [Request path](#request-path)
- [Answer and source boundaries](#answer-and-source-boundaries)
- [Questions about a world's people](#questions-about-a-worlds-people)
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
composes and validates the answer, with the supported repair path. The composer is waited for one
deadline from the moment the answer's fixed words are ready, over its primary, any fallback and its
repair: the 99th percentile of its role's calls in the measurement the role's timeout rests on
(`timeout_basis.p99_ms` in the model manifest, read by `library_composer_wait_seconds`). A repair is
asked only while the role's median call still fits in what is left. When the composer does not
answer within the deadline, times out or fails, the answer is the fixed words, led by a sentence
saying the model that writes the answer did not answer, and the question never fails for it. The
system prompts and the
version they are recorded under are in [prompts](../exulanica/selection/prompts.py). The path
records per-question model execution with [calls](../exulanica/selection/calls.py) rather than
inferring execution from the manifest.

The browser's `companion-ask-api.ts` calls `POST /selection/ask` and obtains the packet needed to
resolve citations. The [application composition](../web/packages/app/src/main.ts) connects question,
appearance and conversation-memory clients. The [customization contract](atlas-world-customization-contract.md#7-frontend-integration-boundary)
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
IDENTICAL confirmation flow", and that "No path writes to the graph without a proposal". That holds
for every utterance the parser can turn into a change. The question branch is what
happens when it cannot, or when all it makes of the words is a note: the parser keeps whatever
follows a first comma as a note, so a draft of notes alone, typed while one of the Companion's own
questions is open, is cancelled unwritten and asked as a question, unless the words answer that
question: a reply to "How do you know them?", which a person answers in their own words, or one
that opens with a yes or a no to a question that asks for one (`answersOpenQuestion` in
[the controller](../web/packages/app/src/companion.ts)). The guarantee is structural rather than
promised:

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
failure to read their sentence. The last includes a Selection the planner proposes that refers to a
person, a place or a thing the question does not name by the name the account holder gave it. The
planner's catalogue names nothing else, so such an id is a guess, and `answer_question` in
`exulanica/selection/question.py` refuses it before anything is searched, answering with the
sentence `abstain_from_a_guess` in `exulanica/selection/answer.py` writes: that answering would mean
guessing, and that a person, a place or a thing is found by the name the account holder gave it.
Searching such a Selection would answer a question about a place nobody saved from the photographs
of the saved place the planner stood in for it, and cite them. A plan the caller supplies is the
caller's own choice and is not held to the question's words. A statement about the search, a `meta`
clause, carries no citation: `validate_answer` refuses one that does, so no photograph is offered
under a sentence about the whole library.

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

**Every clause cites in the packet's own spelling.** The packet shows each photograph to the
composer as a bracketed token, `[2EXZHVS3UA]`, and a composer that copies the brackets is not
refused: `EvidencePacket.resolve` in [packet.py](../exulanica/selection/packet.py) strips them,
because a token resolves bracketed exactly when it resolves bare. What the route returns is the
token that resolved, once per clause (`_in_canonical_form` in
[question.py](../exulanica/selection/question.py)), so the response's `citations` map, the page's
chips and a remembered answer read one form. A remembered answer stores the span each citation
resolved to, never a token.

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
passes one boundary that applies the rule
([privacy and consent threat model](privacy-consent-threat-model.md), section 4.4). The requests this
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
browser's placeholder pattern and naming predicate to the server's. An answer the Companion
remembers across a reload keeps its `names` with its text: `companion_answer_name`
(`exulanica/migrations/0103_a_remembered_answer_keeps_whom_its_placeholders_stood_for.sql`) holds
each placeholder and the entity it stood for, as ids and never as a name, append-only, of the
entity's own class and refused for an entity already deleted, and a correction keeps the map of the
answer it replaces. `GET /companion/memory/recent` serves the map with each answer, and the browser
draws a remembered answer through the same resolver as a fresh one, so every case in the table
above holds for it, and under the provenance line it was first drawn under
([Conversation memory](#conversation-memory)). An appearance proposal's words carry the same map:
`propose_appearance` returns the request's record with the proposal or the refusal
(`AppearanceOutcome.names` in `exulanica/selection/proposal.py`), `POST /selection/appearance`
serves it as `names`, and the page
draws the spoken change and a `not_in_catalogue` detail through the same resolver and writes the map
back with the proposal, so a reload shows the same names. `tests/test_appearance_proposal_names.py`
holds the map and the absence of a person's saved name from every request on that path, with no
right granted and with every entity released as though a right existed for each. What it does not
do: a name is the one in the library the page holds when the words are drawn, so an answer or a
proposal drawn again after a reload, or once the page has read a rename, shows the new name, even
where the placeholder stood for the words on a sign.

**The composer is told where the account holder confirmed a photograph was taken.** A Selection
filtered by a place holds a photograph because of a confirmed link from the photograph's place
occurrence to that place, and only a person's decision writes a confirmed link
(`confirmed_needs_a_human` in `exulanica/migrations/0001_spine.sql`). `build_packet` in
`exulanica/selection/packet.py` keeps that link on the photograph's line as the place's id
(`ConfirmedPlace`), which adds no line and no token. `_without_names` in
`exulanica/selection/question.py` names the place from the request's record, by its id and from its
own saved name alone, and `_render_packet` states it under the photograph's token as
`user_confirmed_place: [place A]`. The composer's prompt says that line is the
user's confirmation that the photograph was taken there, which supports a historical clause citing
it, and that it says nothing about what the photograph shows. Without it, each such photograph reaches the composer as a bare line with no description, and asked
which photographs were taken at the place, the composer answers that no photograph can be
identified as taken there (measured
under Evidence and limits). The line names the place as the request names it: by its placeholder,
or by its saved name where the account holder allowed that place's name for the composer, whose
role, `reasoning_cheap`, the uses file (`exulanica/consent/place-name-uses.v1.json`) offers for
writing the Companion's answer. A place with no saved name has no placeholder and is not stated.
`tests/test_companion_place_link.py` holds the line, the placeholder given by id, and, with no right
granted, the absence of the saved name from every request.

**The composer is told who the account holder confirmed is in a photograph, by placeholder only.**
A Selection filtered by a person holds a photograph because of a confirmed link from one of its
person occurrences to that person. `build_packet` keeps that link on the photograph's line as the
person's id (`ConfirmedPerson`), and `_render_packet` states it as
`user_confirmed_person: [person A]`: the request's placeholder, never the name, because a person's
saved name never reaches a hosted model, with or without a right, and the browser restores it. The
composer's prompt, from `selection-8` on, says that line is the account holder's statement that the person
is in the photograph, not something anybody saw; that it supports a historical clause saying so;
and that it says nothing about how they look, where they are in the picture, what they wear or
what they are doing, which only the photograph's own description may say, and never that a person
is visible or can be seen. A person who was deleted, who was merged into another, or whose consent
was withdrawn is not stated, the last because their name is withheld from every surface and a
statement that they are in a photograph is the same fact in other words; a person with no saved
name has no placeholder and is not stated; and an object linked the same way is not stated.
`tests/test_companion_person_link.py` holds the line, each person who is not stated, and the
absence of every form of the person's saved name from every request, with no right granted and
with every entity released as though a right existed for each. Its effect on answers is measured
under [Evidence and limits](#evidence-and-limits).

**Every hosted request passes one boundary.** The Companion's requests, like every other hosted
request, pass the one policy boundary that applies the account holder's naming and model-right
rules as each request leaves; the boundary, the requests that honour a place-name right and what
the boundary does not do are owned by the
[privacy and consent threat model](privacy-consent-threat-model.md), section 4.4.

## Questions about a world's people

A question may carry the society the page shows, as `society_context`: the world version whose
society it is, and the inhabitant selected in the inspector. The server resolves both in the named
world. One the world does not hold, or a person not in it, is answered as a question asked with no
society, alike in every case (`tests/test_companion_asks_inhabitants_api.py`). A society that cannot
be read under current authorization is left out: the question reaches the planner in the person's
own words, as any question does, and the answer says first, in a clause of its own, that the people
were left out; a question about the people themselves is refused as `society_unavailable`. An event
recorded under an input a withdrawal no longer authorizes is left out alone, among the latest events
as among those that explain a person's state: the rest of the society still answers, without that
citation. `POST /selection/plan` reads no society and refuses a `society_context` by name
(`society_context_not_planned`).

A question about the world's simulated people is a Selection of intent `society`, with a `scope`
(`selected` or `world`) and an `aspect` (`who`, `doing`, `why`, `recent`, `talk_content` or
`unrecorded`) ([plan](../exulanica/selection/plan.py)). The planner proposes one from words, told
only that simulated people are in view and which one is selected, by placeholder. The inspector's
Ask buttons supply one, which needs no model. It is answered from the society's current state and
its latest recorded events, read under the same current authorization the inspector's reads take,
each input authorized once per question however many of those reads it is behind ([society
question](../exulanica/selection/society_question.py)), and a society Selection that reaches `POST
/selection` or `POST /selection/packet` is refused as `malformed_plan`, because it is never
searched.

Who someone is, what they are doing and why are the inspector's own words, from one data file both
read ([inhabitant words](../assets/catalogs/society-words/society-inhabitant-words.v1.json)), cited
to the society's state and to the event that explains it, read by its id however long ago it was
recorded, with no model call. The page and the server choose among those words by one rule, held by
cases both run (`tests/test_inhabitant_words.py`, `society-inhabitant-words.test.ts`). What happened
over the whole world is chosen by the answer composer role (`answer_composer` in the
[model manifest](../exulanica/models/models.manifest.json)) from at most 24 event lines rebuilt from each
event's recorded outcome, reason and minute in the same words, never from a stored summary, a
position, a seed or a digest. The line of a minute whose goal a person's model chose names that
model, by the name the People panel shows (`Manifest.model_name` in
[the model manifest](../exulanica/models/manifest.py)), from the one `decision_applied` event of
that minute and person that applied a choice, read under the same authorization; it names none when
there is not exactly one. The composer writes nothing: it returns which lines answer the
question, at most nine, and at most one of the fixed framings the words catalog lists, and the
answer is each chosen line in its own words, cited to it, in the order they were recorded. The
answer leads with the simulated minutes of the lines it shows, because the simulation counts minutes
and has no time of day. A choice that names a line not in the list, or more lines than nine, is
refused, and its reasons are kept with the answer. The composer is then asked once more, told
those reasons, only while at least the chosen model's median call is left of its deadline;
otherwise the latest lines are given in fixed words at once. They are also given when no choice comes: the answer says first whether
the composer did not choose within its deadline, did not answer in time, or did not answer, and
whether one line or several follow.

The composer's choice is optional: the fixed words it chooses among are ready before it is asked.
So it is waited for at most 10 seconds from that moment, primary, fallback and repair together
(`COMPOSER_WAIT_SECONDS` in [society question](../exulanica/selection/society_question.py)), a
declared product figure rather than a measurement of the model. About 10 seconds is the limit for
keeping a person's attention on a dialogue while they wait (Nielsen, "Response Times: The 3
Important Limits"), and it is the speed bound the comparison that chose the model pre-registered.
The one model client ends the call at that deadline, which may be shorter than the role's manifest
timeout and never longer (`deadline_s` in [the model client](../exulanica/models/client.py)); an
attempt it ends is recorded as `deadline_ended` and charged as a timed-out attempt is, at the most
it can have cost, and an attempt left no time to be sent is recorded as never sent, at no cost.
So a typed question waits at most its plan, two planner calls of 25 seconds each, then 10 seconds
for the choice: 60 seconds, apart from the server's and the page's reads and the moment a
withdrawn primary takes to refuse before its fallback is asked. A question asked from the
inspector carries its plan, asks no planner, and waits at most the 10 seconds. The composer
role's 90 second manifest timeout, twice its model's slowest call in that comparison (44.2
seconds) rounded up, still bounds any one of its requests. In that comparison 7 of the chosen
model's 8 calls came back within 10 seconds, and its median call took 6.5 seconds
([record](evaluation/2026-09-29-society-composer-models.json)). While the answer is composed, the
Companion says it is looking at what happened in this world.
After the composer's wait the society is checked again from its row alone, so a withdrawal made
while it chooses applies from the next question. Every simulated fact is a clause of type
`simulation`, which must cite and is never a statement about the person's past; an answer about
simulated people carries no `historical` clause. Every citation is returned in `simulation`, with
truth class `simulation` and `personal_visit_evidence` false, and every answer closes by saying the
people are simulated. The page labels each citation Simulation, and opening one selects the person
in the inspector with the cited words and the minute they are from.

No inhabitant's name is in a hosted request or in an answer. A question is read once, longest words
first, over saved names and inhabitants' names together, as saved names are read for every hosted
request: a saved person called Emi Tanaka is that person however an inhabitant called Emi is named,
and an inhabitant's full name, Ari Ash, is that inhabitant however a saved Ash Ketchum is named.
Only a form that names exactly one inhabitant, or the selected one, is written `[inhabitant A]`. A
form several share, with none of them selected, stays the person's own word, and a question about
one of them named that way is refused as `select_a_person`; a single word every inhabitant's name
shares, such as a surname they all have, names nobody, so "the ash cloud" stays a cloud. A typed
`[inhabitant A]` names nobody, because its letter belongs to the answer it came from, and is refused
as `typed_inhabitant_label`, asking for the name or a selection. A place they use is `[spot A]`;
`inhabitants` and `spots` say which each stands for, and the page draws the name from the society it
shows, marked simulated, and the place by the person's own object there
(`web/packages/app/src/companion-simulated.ts`). Synthetic names come from a small table, so the
same words can read as a saved name and as an inhabitant's. With the inhabitant who has them
selected, such a question is refused as `synthetic_name_collision` before it is planned, naming both
ways to ask: the saved person by full name, or the selected one without the name. With nobody
selected who has them, the words are the saved person's, as they are with no people on screen, and
an answer about the library says first, in a clause of its own, that someone in the world shares the
name, and that it is about the person saved or, for a place or any other name, that it reads the
words as the name saved. An answer about the world's people says nothing of it, because it is not
about anybody saved. No refusal or note carries a bracketed label, which the page would draw as a
person. The society composer's call site replaces every saved name, a place's included, and its
client adds a policy that releases no place's name (`society_answer_model` in
`exulanica/api/routes/selection.py`), so a place-name right granted for answers about photographs is
no use of it (`tests/test_society_composer_place_names.py`).

Talking has no content. An event line says who talked with whom and nothing more, and a question
about what anybody said is refused as `UNANSWERABLE_NOT_IN_MODALITY`. Every sentence of an answer
about the world's people is the inspector's words, a recorded line's own words, or the code's, so
nothing the simulation did not record, what anybody said above all, can reach an answer, whichever
lines the composer chooses. The notes an answer leads with are the code's and cost it no clause.

What it does not do: it answers for the purposeful profile the words catalog names, and refuses any
other society by name (`society_profile_has_no_words`); and an answer about the world's people is
not kept in the Companion's memory,
which holds photograph citations and saved names only. A remembered answer that cites nothing is
drawn as a statement about the search, never as the person's past.

## Execution provenance

The Selection response's execution block records prompt version, validator rejections and every
attempt the request paid for, or may have, in order. Each entry names its role, the model it was sent
to, its `outcome` and its `cost_basis`. The outcome is `completed` for a call that returned a result
to the workflow, `timed_out` or `failed` for an attempt that returned no reply (a withdrawn primary
before its fallback among them), and `reply_refused` for a reply the client refused as truncated or
outside the schema. The cost basis is `known`, `unknown` when the request was sent and nothing
priced it, so the provider may bill it and `usd` is null, or `not_sent` when the connection was
never made. A completed call identifies requested and served model, fallback use, attempts, latency
and available token counts. Each model it names comes with the name a person reads for it,
`requested_model_name` and `served_model_name` by `Manifest.model_name`
([manifest](../exulanica/models/manifest.py)), and the page prints those names and derives none;
the world style versions and proposals and the environment proposals the panels show carry
`model_name` beside `model_id` by the same rule. The served model of every call, the query-vector
call included, is the identifier the response body named; when a body names none, the record keeps
it null with the reason `response_names_no_model`, and an attempt that returned no result carries
`result_not_returned`, rather than repeating the requested model. Provider usage that is absent
remains absent rather than becoming a measured zero, and no entry carries the provider's or the
transport's words about a failure. Read the exact fields in
[Selection response models](../exulanica/api/routes/selection.py) and
[the call record](../exulanica/selection/calls.py).

The list is per request and never read from the process-wide ledger. Each question and each
proposal sends through its own copy of the model client (`ModelClient.with_attempts` in
[the client](../exulanica/models/client.py)), which keeps the workspace's policies and hands the
request's log each attempt as the shared ledger records it, so two questions in flight at once each
list only their own attempts (`tests/test_execution_every_attempt.py`). A request that a
hosted-request policy or the budget guard refused before it left sent nothing and is not in the
list. When an error ends the request, a model's failure, a policy's refusal as a request left, or a
refusal of the plan or the world the request named after it was paid for, the problem body carries
the same block, validator rejections included, as its `execution` member
beside `code` and `detail`, and the page shows it where it shows a completed answer's provenance.
The `detail` of a model failure says what happened in this product's words and never repeats the
provider's answer or a model's reply. The page finds the composer's call by its role and outcome,
never by its place in the list. An environment proposal (`POST /selection/environment`) records
its attempts the same way.

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

A retained answer keeps what kind of answer it was, which decides the provenance line drawn under
it: a model's answer, the search's, a change a model drew, a refused or never-shown change, what
became of a proposal, a correction, and the other kinds `AnswerComposed` in the
[memory repository](../exulanica/world/companion_memory.py) lists. It also keeps whether the model
that answered was a fallback and how many of its requests returned no answer, with whether any of
their costs is unknown
([migration 0112](../exulanica/migrations/0112_a_remembered_answer_keeps_what_kind_of_answer_it_was.sql)).
`POST /companion/memory/answers` requires all four and refuses a kind it does not know; a
correction is recorded as `corrected` by its own route and by no other. The browser draws a
remembered answer under the line of its kind with the same sentence about unanswered requests, so
after a reload it reads as it did when it was first drawn, and a proposed change is never redrawn
as an answer. The browser keeps each paragraph it drew apart in the text it stores, a blank line
between them, and draws them apart again, so a remembered answer keeps its paragraphs; an answer
stored as one paragraph is drawn as one. An answer retained before the kind was kept takes its kind from what its row holds
(its origin, its prompt version and, for a drafter's reply, the reviewed sentence a refusal opens
with) and claims no fallback and no unanswered request, which those rows did not keep.

The browser [memory client](../web/packages/app/src/companion-memory-api.ts) loads retained state.
`memoryFromPersisted` in the [Companion runtime](../web/packages/companion-runtime/src/memory.ts)
replays supported escapes through the same cooldown logic as a live session. Per-session suppression
and the no-penalty Later choice do not become permanent suppression after reload. A failed memory
write is a durability failure, distinct from displaying a correctly supported answer.

These mechanisms establish bounded conversation persistence. They do not by themselves establish
autonomous activity, complete lifelong shared context or model training.

## Appearance proposals

`POST /selection/appearance` returns a supported appearance proposal or refusal. It does not apply
the proposal. The Companion speaks about a proposal only once the world style authority has
answered the preview the proposal asks for (`POST /world/styles/previews`): one the authority shows
is described as waiting in Customize; one it refuses is a single answer saying so in reviewed words
with the authority's own detail, and one no surface is there to show is a single answer saying that
it could not be put in front of the person, each under a provenance line saying the change was never
shown. When the authority has not answered within
`PROPOSAL_ANSWER_WAIT_MS` ([the Companion's composition](../web/packages/app/src/composition/companion.ts),
5 s, a bound measured against a preview's own requests), the Companion says it could not confirm
the change, which may still appear in Customize, and what becomes of it is kept as its own
record. The [proposal implementation](../exulanica/selection/proposal.py) classifies the request,
drafts from the reviewed style registry and validates the result. A question about evidence and a
request to change appearance have distinct inputs and responsibilities.

A proposal cites the evidence of the world it is asked in: the slots that world's current topology
binds, then the reviewed photographs attached to its saved entry that are available when it is
read, each named to the drafter by its attachment id alone. A world with neither, such as a starter
with no attached photograph, is refused as `no_evidence`, in words saying that attaching a
reviewed photograph makes a proposal possible. A draft that names none of the evidence the world holds, or names
evidence outside it, is refused as `unsupported_reference`, and the page says each of the two in
its own words (`proposal.refused.*` in `web/packages/app/src/ui/copy.ts`).

The drafter's schema derives from the registry's profiles, controls, ranges and choices. It states
each range control as the values on its grid rather than as a number between two bounds: as a
number, the endpoint's constrained decoding wrote 1.25 as `1` and `25` on two lines, a reply that is
not JSON ([measured before and after](evaluation/2026-09-24-appearance-draft-grid-outcome.json)).
An invalid value is refused, not silently converted into a different proposed value. The draft
names the controls it changes and never the modules that own them: the proposal's modules are the
ones the registry says own a control that moved, so a change is never refused for a module the
draft left out.

When no draft can be read after its repair, or a draft is cut at its token limit, the request is
refused as `not_drafted`. The page says that a model's reply could not be read
(`provenance.undrafted`), and keeps "The reviewed design has no way to make that change"
(`provenance.refused`) for a refusal that states a limit of the design, such as `not_in_catalogue`.
The page waits for the route as long as the server may take: `appearance_bound_seconds` in the
proposal implementation, the classifier and the draft and its repair at their role's worst case,
plus the page's read allowance, held by
[test_companion_propose_deadline.py](../tests/test_companion_propose_deadline.py). Apply remains a separate
reviewed operation through the [appearance authority](world-version-authorities.md#appearance-authority) and the
[customization contract](atlas-world-customization-contract.md). Conflicts require review against
the relevant version; natural language does not bypass the same validation as direct controls.

Broader structural edits and environment proposals follow their own registered capabilities and
contracts. This route's existence does not establish arbitrary creation, simulation control or a
model's permission to act without review.

## Evidence and limits

The [model selection record](model-and-service-selection.md) identifies implemented callers and
measured candidate comparisons. Earlier question, memory, proposal, prompt and place-query
investigations are retained with their original inputs and limitations in the
[fixed implementation history](https://github.com/twinkling-reality/exulanica/blob/857cffe730dad97f9edb34535c773115277e2769/docs/companion-question.md).
Some cited campaign artifacts are local-only; a clone does not contain them. Do not present a
historical result, patch or unconfigured route as a live end-to-end demonstration.

| Measured result | Records | Limits |
| --- | --- | --- |
| **A confirmed place, end to end.** With the confirmed place on each photograph's line (`selection-7`), three registered questions about a synthetic place were answered right, citing its photographs; without it (`selection-6`) all three were wrong. In the running app the Companion showed each answer with the confirmed name, opened the cited photograph inside the Companion from the masked route, and said a photograph the server no longer served could not be shown. | `docs/evaluation/2026-09-23-companion-place-link-preregistration.json`, `docs/evaluation/2026-09-23-companion-place-link-outcome.json` | One draw per question per arm; synthetic drawings of one place; English questions; no remembered answer or rename |
| **A confirmed person, by placeholder.** On the held-out split, answers to six questions about a person cited only that person's photographs in 30 of 30 with the line and 7 of 30 without it; no clause said a person was seen or described them; four questions naming no person passed 20 of 20 in both arms. | `docs/evaluation/2026-09-24-companion-person-link-preregistration.json`, `docs/evaluation/2026-09-24-companion-person-link-outcome.json` | A synthetic library of eight photographs with two named people; how the vision role describes people on personal photographs is not measured |
| **Withheld places in vector search.** One placeholder per saved place gained 0.6111 in mean R-precision over the caption vectors alone and 0.0833 as the executor ranks, against the registered gates of 0.25 and 0.10, so the placeholder assigned per request stays. | `docs/evaluation/2026-09-23-embedding-placeholders-preregistration.json`, `docs/evaluation/2026-09-23-embedding-placeholders-outcome.json`, made by `scripts/measure_embedding_placeholders.py` | Synthetic drawings, English names and six places, one run of captions; a placeholder stable across requests would let a provider link a withheld place's photographs, so adopting one needs the account holder's decision |
| **A place nobody saved.** With the two abstention rules, 0 of 60 held-out answers about an unsaved place cited a photograph (22 of 60 without them) and all 60 abstained; answers about a saved place cited a photograph confirmed there 60 of 60 in both arms. | `docs/evaluation/2026-09-24-companion-absent-place-preregistration.json`, `docs/evaluation/2026-09-24-companion-absent-place-outcome.json`, made by `scripts/measure_companion_absent_place.py` | Synthetic drawings; libraries of one and three saved places with no saved person; a planner that leaves an unsaved place out of its plan never occurred |

A place-class entity comes from the vision role's place proposal, written only when its name is
read whole on a sign the photograph transcribes (`exulanica/ingest/place_proposal.py`, measured in
`docs/evaluation/2026-09-23-vision-place-proposal-d-outcome.json`). The derivative worker runs the
caption-vector pass for each admitted photograph through the hosted-request boundary and under a
personal model right for the embedding role (`exulanica/ingest/worker_command.py`); a capture's
tombstone reaches its caption vectors (migration 0044 records each vector a tombstone targets, and
the purge worker deletes it; `tests/test_caption_vector_lifecycle.py`). Embedding quality, the 0.65
threshold and latency over a large corpus are not measured.

Changes to this contract require checking the affected route, repository, request-policy and
browser boundary. Broader continuity, live-model usefulness and personal-source acceptance need
explicit evidence beyond fixture checks or storing a transcript.
