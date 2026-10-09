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
- [World actions](#world-actions)
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

The planner's form is sent with each object's lists last (its time windows, an entity selector's
ids), only in the schema the model is given, so the Selection model and its API description keep
their own order. Its reply may spend at most 640 completion tokens (`PLANNER_MAX_TOKENS`, the
structured-extraction role's floor); the longest plan a record holds, 263 tokens
(`docs/evaluation/2026-09-22-companion-planner-outcome.json`), leaves room inside it for the role's
fallback, which reasons in its reply before it answers. A plan cut at that limit is repaired once,
told how it ran on, as the Companion's drafters are (see World actions), and a plan cut or refused
twice is answered with an abstention that says the question could not be turned into a search, never
an error. Putting lists last removes one place a reply was measured running on, after a list; a plan
has also run on in whitespace after a single value, which only the ceiling, the repair and the
abstention bound.

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
failed network request remain distinguishable. None authorizes an invented factual answer. A route
that needs a model answers an instance with no model credential `503 provider_credential_absent`,
the code a capability read gives the same condition, with a detail sentence clients already
recognise. The exact response shapes and refusal codes live in the route models and API schema
snapshots.

## Answer and source boundaries

**It is a read and it cannot become a write.** `interaction-model.md` 4.3 fixes that free text "is
parsed into the same update proposal draft that a choice would produce and goes through the
IDENTICAL confirmation flow", and that "No path writes to the graph without a proposal". That holds
for every utterance the parser can turn into a change. The question branch is what
happens when it cannot, when all it makes of the words is a note, or when the words ask: the parser
keeps whatever follows a first comma as a note, and reads whether the words end with a question mark
or open with a word that asks (`asks` in
[the parser](../web/packages/companion-runtime/src/parse.ts)). So a draft of notes alone, or any
draft of words that ask, typed while one of the Companion's own questions is open, is cancelled
unwritten and asked as a question, unless the words answer that question: a reply to "How do you
know them?" that does not ask, which a person answers in their own words, or a reply that opens with
a yes, a no or a maybe to a question that asks for one, which the parser reads (`reply`) and keeps
whole in the note it records (`answersOpenQuestion` in
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
answer's chip or the question's `See the photo` button. A read is drawn only while its photograph
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
name, except an article, a determiner, a preposition or a conjunction that refers to no one
([name-part-function-words.v1.json](../exulanica/epistemics/name-part-function-words.v1.json)) where
the saved name writes it in lowercase and capitalises another part: the "the" of a saved "Joe the
Plumber" is no name by itself. The saved name's own writing decides, so a doubt is a redaction:
"Nguyen The Anh" keeps "The", "Tom With" keeps "With", and a saved name written all in lowercase keeps
every part. The list holds words that are no given name or surname in any major naming culture, with
one declared exception, "the", which is also a Vietnamese name part written without its diacritic and
which the rule keeps wherever it is written as a name. Other names are recognised whole only,
because their parts are ordinary words and a saved "Lantern House" must not turn "photos of the
house" into a filter on one place. Every saved
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
citation. An answer about what is at a place says first, in a clause of its own, when a society at
that place was left out of its content, and why: nothing it is made from is recorded, what it is
made from no longer checks, something it is made from is not available, or it changed while it was
read (`SocietyLeftOut` in [the executor](../exulanica/selection/executor.py)). `POST /selection/plan`
reads no society and refuses a `society_context` by name
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
cases both run (`tests/test_inhabitant_words.py`, `society-inhabitant-words.test.ts`). A person who
came in from outside this world is never called invented for it: the page and the Companion say where
they came from, as the door lists their bridge for the workspace (or "outside this world" where it
lists none), and who decides for them there, this world or the program they came with, from their
arrival's record (`what_crossed_world`, `what_crossed_program`). What happened
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

Each simulation citation also says what the event followed. `input_seq` is the society input the
event's minute consumed. For an event whose target is a placed authored object, `object_id` names
it, and `edit_seq` and `edit_id` name the version edit that last set that object at or before the
authored state the input followed, as `GET /world/versions/{version_id}` lists it in `edits`. A
state line and an event with no placed target leave them null. So an answer about why a person
rests at a bench leads from the cited event to the bench and to the edit that placed it
(`tests/test_companion_actions_postgres.py`). The fields are ids only; no line text carries them,
and none is sent to a model.

An answer about a world's people cites only events up to the minute the page shows. A coupled
world with roads runs its people ahead of what the page shows, by up to its clock's lead, so every
event after the clock read's `presented_through_tick` (`exulanica.world-clock/v1`) is left out of
each list that answer reads; a legacy world shows its people's head minute and leaves nothing out.
A person's state line still describes the head minute, because only the society's current state is
stored. A planned search's simulated evidence, a society in a confirmed place's events, is not
bounded this way.

It answers for the purposeful society and the living town profiles named by the words catalog,
using the living resident's recorded home, work, activity and model decision events without
exposing need levels or place identifiers. It refuses any other society by name
(`society_profile_has_no_words`). The browser does not keep an answer about the world's people in
the Companion's memory; the memory routes accept one with its simulation citations
([conversation memory](#conversation-memory)). A remembered answer that cites nothing is drawn as a
statement about the search, never as the person's past.

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

An answer about a world's simulated people is kept with what it cited instead
([migration 0127](../exulanica/migrations/0127_a_world_project_keeps_what_its_person_chose.sql)):
`POST /companion/memory/answers` takes the world asked about, the answer's `simulation` citations in
reading order (result kind, version, inhabitant, event, tick, and the society input, placed object
and version edit that explain an event where the answer named them) and its `inhabitants` and
`spots` labels, all as ids; no event line is stored, because it is read again under the society's
current authorization when the answer is drawn. An answer cites photographs or a simulation, never
both; it names its world exactly when it cites a simulated record, and keeps labels only with one.
A citation of a version whose source a deletion invalidated is refused
`424 unavailable_society_input`, and a version or event this world does not hold is an unknown
reference. A correction keeps them as it keeps photograph citations. `AnswerView` returns the same
fields, each citation with `truth_class` `simulation`.

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
autonomous activity, complete lifelong shared context or model training. What a person chooses to
keep about their work in a world, beyond what was asked, is their
[world project context](project-context.md); deleting a remembered answer deletes every project item
drawn from it.

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

A proposal states what it is drawn from, and the caller chooses; it is never inferred. The request's
`appearance_basis` is `evidence` unless it says otherwise. An evidence proposal cites the evidence
of the world it is asked in: the slots that world's current topology binds, then the reviewed
photographs attached to its saved entry that are available when it is read, each named to the
drafter by its attachment id alone. A world with neither, such as a starter with no attached
photograph, is refused as `no_evidence`, in words saying that attaching a reviewed photograph makes a
proposal possible. A draft that names none of the evidence the world holds, or names evidence outside
it, is refused as `unsupported_reference`, and the page says each of the two in its own words
(`proposal.refused.*` in `web/packages/app/src/ui/copy.ts`).

An `authored_design` proposal is a design choice drawn from no evidence. Its drafter reads no
evidence and its form has no field for a reference, under its own prompt version
(`proposal-authored-1`, so the evidence drafter's measured wording and `proposal-4` are unchanged).
The proposal and the version applied from it record the basis (`appearance_basis`). The world style
authority refuses a Companion proposal drawn from evidence without a reference and a design choice
with any (`_validate_proposal_provenance` in `exulanica/world/repository.py`), and migration 0128's
check holds the same rule in the database, so choosing a basis in a request cannot bypass either
rule. Other origins state no basis.

The drafter's schema derives from the registry's profiles, controls, ranges and choices. It states
each range control as the values on its grid rather than as a number between two bounds: as a
number, the endpoint's constrained decoding wrote 1.25 as `1` and `25` on two lines, a reply that is
not JSON ([measured before and after](evaluation/2026-09-24-appearance-draft-grid-outcome.json)).
An invalid value is refused, not silently converted into a different proposed value. The draft
names the controls it changes and never the modules that own them: the proposal's modules are the
ones the registry says own a control that moved, so a change is never refused for a module the
draft left out.

The draft is sent with its references list last, and its reply may spend at most 1024 completion
tokens (`DRAFT_MAX_TOKENS` in the proposal implementation); its longest measured successful reply,
404 tokens (`docs/evaluation/2026-09-24-appearance-draft-grid-outcome.json`), leaves room inside it
for the role's fallback to reason before it answers. A draft cut at that limit is repaired once,
told how it ran on and to keep `spoken` to one or two sentences. When no draft can be read after its
repair, or a draft is cut at its token limit, the request is refused as `not_drafted`. The page says
that a model's reply could not be read (`provenance.undrafted`), and keeps "The reviewed design has
no way to make that change" (`provenance.refused`) for a refusal that states a limit of the design,
such as `not_in_catalogue`. The page waits for the route as long as the server may take:
`appearance_bound_seconds` in the proposal implementation, the classifier and the draft and its
repair at their role's worst case, plus the page's read allowance, held by
[test_companion_propose_deadline.py](../tests/test_companion_propose_deadline.py). Apply remains a
separate reviewed operation through the [appearance
authority](world-version-authorities.md#appearance-authority) and the [customization
contract](atlas-world-customization-contract.md). Conflicts require review against the relevant
version; natural language does not bypass the same validation as direct controls.

Structural edits and simulation controls the Companion prepares are the
[world actions](#world-actions); environment proposals follow their own registered capabilities and
contracts. Neither establishes arbitrary creation or a model's permission to act without review.

## World actions

The Companion prepares world work as a plan of the exact requests a direct client sends, and never
sends them itself. `POST /selection/actions` (`world.read` and `model.invoke`) reads one utterance
in the world it is asked in, against the version the page shows, and answers
`exulanica.companion-action-plan/v1` ([action routes](../exulanica/api/routes/selection_actions.py),
[planner](../exulanica/selection/action_plan.py)). The person confirms a step; the client sends that
step's request to the route it names; the receipt is that route's own answer and record. An
operation reached through the Companion therefore has the same permission, validation, transaction,
saved-entry lock and refusal as the same operation sent directly, because it is the same request.

| Companion action | Preview (writes nothing) | Request a confirmed step sends |
| --- | --- | --- |
| Place one reviewed object | `POST .../compositions/preview` | `POST .../compositions/apply` |
| Move an object to where the person points | `POST .../objects/{object_id}/move/preview` | `POST .../objects/{object_id}/move` |
| Remove an object | `POST .../objects/{object_id}/remove/preview` | `POST .../objects/{object_id}/remove` |
| Take back the newest edit | `POST .../objects/undo/preview` | `POST .../objects/undo` |
| Place a published arrangement | `POST .../arrangements/preview` | `POST .../arrangements/apply`, one transaction |
| Change the look | the style preview is the reviewed record | `POST /world/styles/previews`, then `POST /world/styles/previews/{preview_id}/apply` |
| Play, pause or change speed | none; the plan carries the clock read its bases came from | `PUT .../society/control` |
| Move time on 1 to 10 simulated minutes | none, as above | `POST .../society/control/steps` once a minute, chained; a playing world is paused first and played again last |
| Bring people into a world with none | none | `POST .../society` |
| Add a thing by its kind, beside something named or where the person points | none; the route's own checks run in process | `POST .../things` |
| Ask one of the world's beings to go to a place or use it, or to pick up, put down, give or take a thing | none; the step is prepared again just before it is sent | `POST .../society/actions` |

A plan names each step's route key, path values, body, the permissions its route declares, the
version pins (`base_state_sha256` and `edit_seq`), the authority's preview document and its digest,
what replaying the request does and which route compensates it. The model fills enums only: an
operation from the fixed vocabulary above or `other`, and options from the reads a direct client
makes, the reviewed kinds a person may place, the kinds of thing an author may add, the version's
objects and placed things offered by opaque label so a client-chosen id never reaches a hosted
request, the society's beings and the places they use (a town's premises and benches by the name
and number the town gives them), and the published arrangements. Positions
come from the page's placement or viewer context, or from what a thing is put beside, and the
origin role of anything added is the person's stated choice. What is missing is asked about before
anything is prepared (`asset_ambiguous`, `object_ambiguous`, `object_required`,
`arrangement_ambiguous`, `origin_role_required`, `placement_required`, `viewer_required`,
`kind_ambiguous`, `anchor_ambiguous`, `being_required`, `being_ambiguous`, `place_required`,
`place_ambiguous`, `thing_ambiguous`); the answer goes to `POST /selection/actions/prepare`
(`world.read`, no model),
which validates typed actions as any direct body is validated.

A step the operations cannot express (`other`) refuses the whole plan. A drafted plan takes back at
most one change: a second `undo_last_edit` step is refused `action_not_offered`, and asking again
takes back the next. A plan has at most eight steps, and each world-edit step the model fills is an
operation and then one list of up to four options drawn from the listed kinds, objects, things,
beings, places and arrangements; the list is read by the list each label came from, and an option
from a list the operation takes nothing from names nothing. The list is the step's
last field, so a list that names something can be followed only by the step's closing brace: under a
strict schema a list followed by another field needs a comma, and a model that writes a line break
there instead can then write only whitespace. The world-edit and simulation drafters each make one
try and one repair, and each reply may spend at most 640 completion tokens (`DRAFT_MAX_TOKENS`, the
structured-extraction role's floor), well above what a filled form takes, so a reply that runs on is
cut inside the role's timeout rather than at it. A reply cut at that limit is classified by how it
ran on (`runaway_shape` in [response.py](../exulanica/models/response.py)): whitespace when it ends
in at least 256 whitespace characters, repetition when its last 8 whole items are one item,
otherwise neither. The repair tells the model which, without showing it the reply, and a second
refused reply is refused `not_drafted`. The limit of the ceiling: the role's fallback reasons in its
reply before it answers, so a three-step form with every list full, drafted by the fallback, may not
fit in 640 tokens and is then refused `not_drafted`.

Availability and permission are the version capability read's (`GET /world/versions/{version_id}/capabilities`,
read in process). An operation it calls unsupported, unavailable or not permitted is refused with
its own descriptor (`action_unsupported`, `action_unavailable`, `action_not_permitted`), never
approximated by an operation that is offered. A preview is computed by the function its preview
route calls, on a connection opened only when the caller's grant satisfies that preview route's
declaration, in a transaction that is read only before anything runs in it. A version the page no
longer shows is refused `stale_version` before a model is asked, and a preview the authority blocks
is refused `preview_blocked` with the authority's own reason on the step. `what can I do here` is
answered from the descriptors, one entry per Companion action, with the appearance bases available
on this world.

Simulated time moves only through the playback controls. Every base a simulation step sends comes
from one read of the version's clock (`GET /world/versions/{version_id}/clock`), which the plan
carries as `clock`: the control's revision, the society's minute and state, and the clock's own
revision as `base_clock_revision`, so a plan made before the world's clock was coupled is refused
`stale_clock_revision`. The model fills an action (`play`, `pause`, `set_speed`, `advance`,
`bring_people` or `other`), a listed speed and a number of minutes, nothing else. Moving time on N
minutes, 1 to 10 (the prepare body refuses any other count), is a chain of control steps under one
confirmation: the first step says `confirmation` `required` and each later one `chained`, and each
later step reads its bases from the response to the step before it, as `body_from` names them (a
step index and a dotted field). A playing world is paused first and played again at its speed last.
The first refusal stops the chain where it is, and nothing is retried inside a confirmation: a
coupled world with roads lets its people run at most its lead ahead of sealed traffic, so a longer
chain stops at `clock_lead_exhausted`. Asking for what the controls already hold is refused
`no_change`; a missing speed, count or region is asked about (`speed_required`, `minutes_required`,
`region_required`); a world with nobody in it refuses a control with its descriptor's code and
offers `bring_people`; a society whose engine cannot play is refused with its descriptor's code
(`legacy_society_not_playable`). Each step says whether sending it can lead to a hosted model call
(`spends`), and the plan says so before the one confirmation (`spends`, and in `spends_by` the
decision roles asked). Only the playback worker asks a person's chosen model, before each minute it
plays, so a step that plays the world spends when the owner chose a model for a person; a control
step asks no person's model. In a coupled world with traffic, sealing the minutes the people ran asks
each light's chosen model, so a control step spends there too, and so does playing. A legacy world's
lights run on the wall clock, whatever its people do.

Only the first step of a compound world edit is prepared. Each later step is typed and prepared
after the previous step's receipt, against the state it left, so every confirmed step was previewed
against the state it meets; steps commit one at a time, and only a single arrangement is atomic. A
simulation chain's later steps need no preparing: their requests are stated in full, with the bases
`body_from` takes from the response before them.
`POST /selection/actions/outcome` (`world.read`) reads what the authorities recorded for a plan's
steps ([outcome read](../exulanica/selection/action_outcome.py)): `applied` with the receipt's ids
and whether the record matches the preview, `not_applied` while the version still stands at the
pin, `superseded` when another change came first, `pending` for a step not yet prepared, and
`partial` for a plan with some steps applied. A style proposal the lifecycle refused reads as
refused, never as applied: `superseded` with `code` `stale`, or `not_applied` with `code`
`rejected`. A step that does not have the shape a plan gives it is refused
`422 invalid_outcome_step`. The read trusts the plan it is sent only to decide what to look up:
`plan_sha256` is echoed unverified and `matches_preview` compares the records with the preview the
client sent back, so an outcome is that client's answer and no proof of a plan this server made.

A step is credited only with the record its own request produced. Two requests sent from the same
bases make records of the same shape, the later one refused as stale, and the other writer can be
the same person in another tab, so neither the bases nor the actor tell them apart. Each step a
client sent comes back with `answer`: the `status` its own request was answered with, the problem
`code` when it was refused, and the identity that answer named, by the step's route. An edit
(`compositions/apply`, `objects/{object_id}/move`, `remove`, `objects/undo`) names its `edit_seq`
and `state_sha256`, an arrangement the same fields of the `version` it returns, a control step its
`receipt`'s `event_seq` and `document_sha256`, a configuration its `revision` and `last_event_seq`,
and bringing people in its `society_id`; a style step sends only `status` and `code`, because its
proposal id is already the step's own. A record is the step's receipt only when the answer names
it, it matches what the step asked, and, for an edit or a playback control, the caller's actor made
it. Bringing people in is idempotent: the same request sent after another's is answered with the
society already there, and that answer names it. A step sent back with no answer, or with a
refusal, is never `applied`: it reads `not_applied` while its bases stand and `superseded` once
they moved, and records other requests made from its bases are listed under `repeats`, never as its
receipt. Sending a confirmed step again is refused by the authority as stale; a version whose
content returns to the pinned state (after an undo) takes the same request again as a new edit,
which the read lists under `repeats`. A plan is never a
reservation: discarding one changes nothing, except an appearance plan's first step, which creates
the style lifecycle's durable proposal and preview record once confirmed and is discarded through
`DELETE /world/styles/previews/{preview_id}`. Each appearance plan carries a fresh proposal id, so
confirming one plan twice is refused by the lifecycle and asking again makes a new proposal.

A simulation plan is read as the chain it was sent as, from its first step's pins along the
controls' own receipts, each the event its step's answer names: a configuration is the control
event that moved the control revision one past its base to its mode and speed, and a control step
is the `manual_step` event that ran the society on from the minute and state the step before it
left, or, after a configuration, one recorded after it at its revision (a playing world moves on
until its pause lands). The first step without such a record stops the reading. Each receipt
carries `operation`, `world_id`, `version_id`, `revision`, `tick` and `state_sha256` (both null for a configuration),
the fields a project's context stores for it under the same names, and the event's own `event_seq`
and `document_sha256`. A step pinned to a clock revision that moved reads `superseded`. A chain
that paused a playing world and stopped before playing it again leaves it paused: the outcome's
`current.society` says so and `alternatives` offers `play`, and nothing resumes it on its own.
Bringing people in reads back the version's society in the region the step named, when the step's
answer names it.

Behaviour changes, photo point maps, environment instances, model choices, comparisons, character
and thing looks, style rollback, interaction policy, sending people away or bringing them back,
and playing a being are not prepared by the Companion: the drafter's form has no slot for them, so
a request for one is refused `action_not_offered`. Conversation and remembered context never make a
step permitted, and the planner imports neither the interaction-policy plane nor stored
conversation (`tests/test_companion_action_policy_boundary.py`). Scripted tests hold the mechanics;
two measurements of a live model reading held-out requests into these plans, before and after
each step's options moved last under a 640-token ceiling, are in
[evidence and limits](#evidence-and-limits). The later binds the prompt `action-plan-5`; the
current prompt, `action-plan-7`, adds things and beings and a being's hands acts, and is measured by
neither.

### Things and beings

A thing is added as `place_thing`, the request `POST /world/versions/{version_id}/things` takes
([world_things.py](../exulanica/api/routes/world_things.py)): a kind an author may place, at its
newest shipped version and by its digest, an id minted when the plan is made
(`companion:<kind>:<12 hex digits>`, carried in the typed step so a later step of the same request
can name it before it exists), a pose and the person's origin role. The drafter names the kind and
what it goes beside: a listed thing, object or being, or the kind of thing an earlier step of the
request adds. A kind whose first look draws a reviewed object's own container is offered as that
object (`place_object`), so a request for a bench takes the measured object path. Where it stands
is laid out without the model ([action_things.py](../exulanica/selection/action_things.py)):
beside what is named, on its side toward the person first, then its right, its left and behind it,
the two sizes and a clearance apart; otherwise at the pointed spot, or on rings about it when that
is taken; at the society ground's elevation, turned to face the person. The route has no preview,
so its own pure checks run in process before a step is offered, and a step they refuse is
`blocked` with the route's code (`invalid_object_state`, `thing_limit_reached`,
`invalid_thing_placement`), or with `no_free_place_near` or `anchor_not_here`; the route stays the
authority when the step is sent.

One of a world's own beings is asked as `direct_thing`, the request
`POST /world/versions/{version_id}/society/actions` takes: to go to a place the society's consumed
input lists (`go_to`), or to use it (`perform` its activity). The request is built by the function
the route builds it with, on the society's state and the input a request would be made against now,
so a step is offered only where the route would take it, and a refusal is the route's own name
(`decided_from_outside` for a visitor its program decides for, `target_unreachable`,
`destination_full`). Its pins are that minute's, so the browser prepares it again just before
sending it; while the society holds an input it has not taken in, the step is `pending` with
`society_input_queued`; while the being is in the middle of something, or was already asked
something at this minute (the route takes one request per being per minute), with
`inhabitant_action_in_progress`; and while every place at the destination is taken, with
`destination_full`, since places free as visits end and the person asked for that place. The
browser waits for the next minute, at most 90 seconds, before saying it was not sent. Each
thing step carries `titles`, what it names as the reads label them, for the page's words. A being
from outside is offered to the drafter by its kind and number alone, so nothing its program
declared reaches a hosted request. A placing step reads back as its own `add_thing` edit; an
asking step reads back as the request its answer names, `pending` until a minute takes it, then
`applied`, or `not_applied` with the minute's reason.

In a society of things running the hands module, a being may also be asked to pick a thing up, put
it down, give it to another being or take it from one: a `direct_thing` step whose act is the
ability, naming the thing by its placed id and, to give or take, the other being, sent as the hands
intent `{kind: "hands", ability, thing_id, with_id}` with the society's id for the thing
([synthetic-society-contract.md](synthetic-society-contract.md)). The drafter names the beings and
the thing; which being holds the thing is read from the society, or from what the plan's earlier
steps have them do, never from the order the drafter named them in: the holder gives, is taken
from, and puts down, and a put-down naming no thing is of what the being holds. A kind of thing an
earlier step of the same request adds names that thing, by the id it was minted, so "give the knight
a lantern" is a lantern placed beside the knight and then the knight asked to pick that lantern up;
the second step waits for the minute that takes the lantern in. Two things the words could mean, or
none, are asked about as `thing_ambiguous`. A refusal is the route's own name (`act_not_offered`,
`thing_gone`, `belongs_to_visitor`); no shipped kind lets a thing be taken from it, so a take is
refused `act_not_offered`. A later step asking the same being waits as any asking step waits, so in
"pick up the sword and give it to the traveller" the give is prepared once the knight is free
again, and refused `act_not_offered` if the knight does not hold the sword by then. `titles` names
the being, the act, the thing and the other being.

### The browser's path

The browser does not decide what a sentence asks for: the runtime's parse knows names, relations and
whether words ask, nothing about world actions. With a world open, every sentence the Companion is
asked to read goes to `POST /selection/actions` first, in the place `POST /selection/appearance`
held (`web/packages/app/src/composition/companion-plan.ts`). The classifier is therefore
`classify_action`'s five kinds in place of the appearance route's two (`classify_request`);
appearance drafting is unchanged, because both routes call the same drafter with the same default
basis. A question goes on to `POST /selection/ask`. An appearance plan's first step carries the
drafted proposal, which is read by the same function as the appearance route's answer and reviewed
in Customize as before, with no second drafting call; its two style steps are never sent from a
plan, and a basis other than `evidence` takes the old path. A world edit or simulated time is shown
as a plan on the sheet with its spending stated before the one confirmation. "What can I do here"
is said from the action registry's words. Where the route cannot answer (no model, unreachable,
past the appearance route's wait) or no world is open, the sentence takes the path it took before.

A confirmed plan is sent step by step through the action registry
(`web/packages/app/src/ui/actions/planned.ts`): a step's typed action picks its registry entry, and
the request goes to that entry's own route, never to a route the plan names. The plan supplies only
the route's path values, the body and the pins in it, and a chained step's bases from the response
before it (`body_from`); the world scope is the page's. A step whose typed action maps to no entry,
or whose route key differs from its entry's operation, is refused in the browser and never sent.
Each later world-edit step is prepared again against the state the step before it left. The first
refusal stops the chain; each step then reads as done, not done (with the action's own words) or not
reached, and Play is offered when the outcome read says a chain left the world paused. With the
outcome read the browser sends each sent step's own `answer`: the status its request got, the
problem code when it was refused, and the identity its route returned (an edit's `edit_seq` and
`state_sha256`, at the top of the body or under `version`; a clock step's receipt `event_seq` and
`document_sha256`; a clock setting's `revision` and `last_event_seq`; a society's `society_id`).
A step not sent carries none (`stepAnswer` in `web/packages/app/src/ui/actions/planned.ts`). Each
step's own answer is also what the sheet shows. The outcome read credits a step only with the
record its own answer names, so a step refused because another writer moved the world first reads
as superseded, never as that writer's record.

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
| **World-action plans from a live model.** On 54 held-out typed requests, the plans Qwen3-235B drafted matched the expectation frozen before any call exactly in 41 of 54 in the first pass and 44 of 54 in the second, where answering every request as a question scores 6; the first pass named every request's kind. Simulated time, the look of the world, questions and what can be done here were exact in both passes, changes to the world's objects in 6 and 7 of 12. Over 194 requests no watched table changed and no value planted in a request reached a step. | `docs/evaluation/2026-10-02-companion-action-plans-set.json`, `docs/evaluation/2026-10-02-companion-action-plans-preregistration.json`, `docs/evaluation/2026-10-02-companion-action-plans-amendment.json`, `docs/evaluation/2026-10-02-companion-action-plans-amendment-2.json`, `docs/evaluation/2026-10-02-companion-action-plans-result.json` | One model, one set of 78 requests, one machine, no comparison with another model; 28 of the 146 requests that drew a draft (17 of 45 changes to objects) had a reply refused at the 2048-token cap, and the third pass stopped at the 10 percent provider-error rule; the rule for an attempt of unknown cost was changed after the second attempt stopped, as the second amendment states |
| **World-action plans after the drafter's form changed.** On a new set of 60 held-out typed requests, written and frozen before any call, Qwen3-235B's plans matched the expectation exactly in 55 of 58 scored requests in each of three passes, where answering every request as a question scores 5; changes to the world's objects were exact in 16 of 16 each pass, and every request got the same answer in all three passes. No world-edit reply ran to its ceiling (0 of 54 that drew a draft, against 17 of 45 at the 2048-token cap before); 3 of 183 drafts did, all one appearance request at the appearance drafter's 1024, each repaired and exact. Every miss was the same in each pass: a clarification asked for was answered with a default (one minute, speed 2), a recolouring was read as a change of look, and a removal carrying a planted version id was refused. Over 243 requests no watched table changed, no planted value reached a step, and no plan held more than one undo step. | `docs/evaluation/2026-10-04-companion-action-plans-set.json`, `docs/evaluation/2026-10-04-companion-action-plans-preregistration.json`, `docs/evaluation/2026-10-04-companion-action-plans-result.json` | One model, one set of 81 requests, one machine, no comparison with another model and no paired comparison with the earlier set; the run measured main after the question planner and appearance drafter were bounded too, a change that landed after the set was frozen, as the result states |

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
