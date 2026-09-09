# The Companion question path

Status: built, covered by tests, and measured twice against the retained bowl workspace with real
models. Section 6 has what the first run measured and the record is
`docs/evaluation/2026-09-09-companion-question.json`. Sections 9 to 12 are the second pass: the
Companion's memory of all this is now durable, and the composer swap section 6.1 offered as a
proposal has been measured again and made. That record is
`docs/evaluation/2026-09-09-companion-memory.json`.

`product-direction.md` makes this a delivery gate: "Ask about the selected place through the
actual Companion; ground the answer in available evidence and show missing information
honestly", and the scheduling consequence is to "verify the existing runtime path and record the
executed model, task, latency and output".

Two words in that gate were doing all the work and neither was satisfied before this change.
**Through the actual Companion**: no browser code called `POST /selection/ask`, so the answer
path was reachable with a terminal and by nothing a person could press. **Record the executed
model**: `AnswerView` carried no executed identifier, no latency and no usage, so the only way to
say which model answered was to read the manifest, which says which model was asked.

## 1. The path, end to end

```
composer keystroke
  -> ui/companion-composer.ts            free text, submitted
  -> ui/companion-choice-rail.ts         handlers.onSay
  -> companion.ts                        controller.say
  -> companion-runtime session.say       parse.ts finds no change in the words
  <- refused, reasonKey                  refused.couldNotParse or refused.noSubject
  -> companion-ask-api.ts                POST /selection/ask   (the question)
                                         POST /selection/packet (where its citations live)
  -> ui/companion-speech.ts              the answer, the abstention label, the provenance line
  -> ui/companion-choice-rail.ts         one chip per citation, E opens the first
  -> evidence.ts -> /evidence/{span}/masked
```

The server half is unchanged in shape. `answer_question` still plans, validates, executes, builds
a bounded packet, composes, validates the answer and repairs once. What is new is that it now
records what each model call was and cost, and that a browser can reach it.

## 2. What the answer path may and may not do

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
* The rail an answer renders holds two controls, and neither is an assertion about anybody.

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

## 3. Which refusals mean "this was a question"

Two, named in one set in `companion.ts` rather than inferred:

| reasonKey | What it means | Routed |
| --- | --- | --- |
| `refused.couldNotParse` | The parser found no name and no relation in the words | yes |
| `refused.noSubject` | The open turn has nothing to attach a change to | yes |
| `refused.noTurn` | The panel is not open | no |
| `refused.useSubmit`, `refused.notAMultiSet`, `refused.nothingSelected` | Statements about a choice | no |
| `refused.tierNotOfferableHere`, `refused.subjectMissing`, `refused.unavailable`, `refused.unknownOption` | Statements about a permission or a target | no |

A refusal routed here becomes a question. What the ANSWER path then does with a question it
cannot express is section 6: it abstains under `UNANSWERABLE_NOT_UNDERSTOOD` rather than
failing, and it says so without claiming anything about the library.

**`refused.noSubject` is in that set for a measured reason and it is a deviation from the
original instruction, which named only `refused.couldNotParse`.** `generateTurn` returns the
`acknowledge` turn when nothing is open: `subjectEntityId` is null, `freeTextAllowed` is true, and
`CompanionSession.say` refuses with `refused.noSubject` before the parser ever runs. The retained
bowl workspace holds zero entities and zero captions, so that is the state of every turn there.
Routing only `couldNotParse` would leave the answer path unreachable on the exact library it was
built to answer questions about. Both refusals mean the same thing, which is that these words
describe no change to this graph, and neither can have staged anything before returning.

## 4. The execution block

`POST /selection/ask` answers with everything it answered with before, plus:

```json
"execution": {
  "prompt_version": "selection-1",
  "rejections": [],
  "calls": [
    {
      "role": "structured_extraction",
      "requested_model": "Qwen/Qwen3-235B-A22B-Instruct-2507",
      "served_model": "Qwen/Qwen3-235B-A22B-Instruct-2507",
      "used_fallback": false,
      "attempts": 1,
      "latency_ms": 5600,
      "prompt_tokens": 812,
      "completion_tokens": 96,
      "reasoning_tokens": null
    }
  ]
}
```

Every field is read off the response and none is read off the manifest. `requested_model` is what
the chain sent and `served_model` is what the body echoed; they differ exactly when
`used_fallback` is true, which is the case a record derived from configuration reports wrongly
and silently.

`latency_ms` is a whole number of milliseconds. A float rewrites its own last digits on a JSON
round trip, and every evaluation record in this repository refuses one.

A token count is `null` when the provider's `usage` object did not carry it, never zero.
`CallUsage` coalesces a missing count to zero, which is correct for a bill and wrong for a record
of what was observed, so these are read from the raw body instead.

`attempts` is zero exactly when the client's cache served the response, which is the convention
`exulanica/models/results.py` already established. The API builds its `ModelClient` without a
cache, so on this route the count is at least one.

`plan` and `selection` are nullable, for one case only: `abstained` is
`UNANSWERABLE_NOT_UNDERSTOOD` and the planner never produced a runnable Selection. Null rather
than an empty plan, because an empty plan is legal and means everything. A client that never hits
that case sees exactly the response it saw before.

`rejections` carries the validator's own words about the model's output. It is present because a
measurement of this path has to record which rule an answer broke: `deterministic` says the
output was discarded and says nothing about whether the model invented a number, cited a token
that does not exist, or made a historical claim with no citation, and those are three different
failures with three different fixes.

### What the block does not contain, and why

**A call that failed before returning a result is absent from the list.** A body the schema
refused, or one the endpoint truncated, raises out of `ModelClient.structured` before any
`ChatResult` reaches `exulanica/selection/question.py`, and `exulanica/models` was not this
change's to alter. The absent entry is not replaced by one with invented fields; `repaired` and
`rejections` are what say that a discarded attempt happened. A composer answer that
`validate_answer` refused IS listed, because that one came back.

**The list is per question and never per process.** `ModelClient` holds a ledger of every call the
process made, which is the right scope for a cost report and the wrong one here: the API builds
one client and FastAPI runs a synchronous route in a threadpool, so two questions answered at
once would interleave in that ledger and neither could be attributed. `CallLog` is created inside
`answer_question`.

**An abstention still lists the planner, and reading it otherwise printed a false sentence.** The
first version of this document and of both docstrings said "`calls` is empty exactly when no
model was asked anything". It is not. The browser sends the question alone, so `answer_question`
always runs the planner and always records it; the packet then comes back empty and the composer
is never called. `provenanceOf` in the client read "no composing model in the list" as "no model
was asked", and the speech band printed **No model was asked** over every abstention the
interface could produce, while a model had just been asked to plan it and its identifier was in
the body the page had already parsed.

What an abstention actually guarantees is narrower and still worth having: no COMPOSER call is in
the list, because there is no code path from an empty packet to one. The provenance line has four
cases rather than three, and `search` is the one that was missing: a model read the question, no
model wrote the answer, and the line says both.

## 5. What is established and what is not

Established by execution, on this branch:

* The execution block, the abstention with zero calls, the fallback naming the model that served,
  a refused answer and its repair both listed, and a reported count carried through exactly. All
  driven by `tests/model_fakes.py::FakeTransport`, which is the real `ModelClient` against
  prepared HTTP responses.
* The browser path: the permalink join, evidence ordered by first mention and deduplicated by
  photograph, a citation the packet could not locate rendered as one that cannot open, the four
  failure kinds, the four provenance cases, the read-only guarantee, and a per-request deadline.
* That a late answer is held rather than drawn over a dismissed Companion, and that the numbered
  options leave the keyboard while a question is out. The second is a read-only property rather
  than a nicety: the rail keeps the open turn while it is detached, `main.ts` routes every digit
  to it, and submitting the composer drops focus to `body` so the host's "is the user typing"
  guard stops firing. A person typing a next question beginning with a digit could otherwise
  select a tier 2 option they could not see, and the confirmation surface would open over
  "Looking through your library" for a claim about a person that nobody chose.
* `docs/patches/companion-question-main.patch` applies to `main.ts` at 5675b33, and section 7 is that
  patch applied and driven in a browser.
* That the planner prompt describes the form the schema actually sends. Every field the prompt
  offers `null` is nullable in the generated JSON Schema, and the one array field is offered `[]`.
  This is the invariant `selection-2` broke, and it is a test rather than a habit.

NOT established here, and stated plainly:

* **No answer quality is measured.** Five questions is not a gold question set, and
  `evaluation-methodology.md` M3 needs one before an abstention rate or a hallucination rate
  means anything. Section 6 records what five answers said; it scores none of them. Every test in
  this repository still drives a scripted transport.
* **Three of the `selection-3` rules are held by the prompt and by nothing else.** That a
  historical clause cites a source is enforced; **what that source depicts is not**, and cannot
  be, because the validator resolves a token and never sees a photograph. The composer asserting
  a person into a picture it has no description of is refused by wording alone, and a model that
  ignored the wording would pass every mechanical check. This is the sharpest limit in the whole
  path and it is why section 6.1 records the failure rather than only the fix.
* **No latency claim from the tests.** The scripted transport returns instantly, so every
  `latency_ms` in a test is zero or near it, which is a true measurement of a fake. The numbers
  in section 6 come from the live run and from nowhere else.
* **Nothing about the answer path is claimed for a personal corpus.** The retained bowl workspace
  is CC0 reference material with zero entities and zero captions.

## 6. What the live run measured

Executed 2026-09-09 against the retained bowl workspace through the real HTTP route, under an
operator cap of $0.50 and 40 calls. The record is
`docs/evaluation/2026-09-09-companion-question.json` and the raw bodies are beside it.

**The first pass answered nothing.** All five questions failed: four with a 404
`unknown_reference` because the planner returned a well-formed UUID naming nothing, and one with
a 502 because it returned a string that is not a UUID at all. The catalogue is empty, and the old
prompt only covered "the question names somebody who is not in the catalogue", which none of
these questions did. Under a strict schema every property is required, so the model filled a
nullable field because the form had a slot for it.

The resolved-ids rule did exactly what it exists for. No invented id reached the data; each was
refused by lookup. It cannot get an answer, so the fix is one sentence in the planner prompt
stating the impossibility, and `PROMPT_VERSION` moves `selection-1` to `selection-2` because the
constant is an input to the response cache key.

**The second pass, after that sentence:**

| Question | Outcome | Model latency | Wall clock | Cost |
| --- | --- | --- | --- | --- |
| When were these photographs taken? | *"These photographs were taken on 2026-02-01"*, cited | 40.2 s | 40.2 s | 2119 uUSD |
| How many photographs are there? | *"Your photographs number 51."* | 27.3 s | 27.4 s | 1656 uUSD |
| What is this place? | Abstained, `UNANSWERABLE_NOT_CAPTURED` | 10.4 s | 10.5 s | 449 uUSD |
| Who is in these photographs? | *"Your photographs contain no describable information about people"* | 10.1 s | 10.1 s | 1219 uUSD |
| What is the current exchange rate for the pound? | *"Your photographs do not contain any information about currency exchange rates."* | 6.6 s | 6.7 s | 1235 uUSD |

**Nobody was named on a workspace with no named entities.** That is the failure the whole path
exists against, and getting there took three prompt corrections rather than one; section 6.1 is
the sequence. Composer latency is not stable: the same two questions measured between 17.7 s and
54.5 s across passes on packets of the same size. An abstention is fast because the composer is
never called on an empty packet.

### 6.1 The out-of-library question, from a 502 to an answer, in three steps

**It was a 502.** `model_refused`, which a caller cannot tell from the server falling over.

**Step one: the answer path learned to abstain.** The cause was not what it looked like.
`entities` was null, so the empty-catalogue prompt was working. The planner was asked a question
carrying no time at all and stamped the same instant into `start` and `end`. A zero-width
half-open window is empty by construction, and `CaptureWindow._non_empty` is a Pydantic model
validator, invisible to a schema-enforcing endpoint, so the refusal lands locally after the call
is paid for. Three times out of three.

`answer_question` now catches the terminal planner failure and abstains under a fourth reason
code, `UNANSWERABLE_NOT_UNDERSTOOD`, with `plan` and `selection` null. It catches the same defect
wearing a 404 as well: `unknown_reference` on a plan the **model** proposed.

**A fourth code rather than reusing `NOT_CAPTURED`.** That one says "Nothing in your library
matches". Saying it about a question nobody searched would assert a fact about somebody's
photographs from a failure to read their sentence, and M3 would score it as a correct abstention.
That is the laundering M3 adds reason codes to prevent, and it is the argument that added
`NOT_IN_MODALITY`. `plan` is null rather than empty for the same family of reason: an empty plan
is legal and means *everything*.

**Step two: the planner stopped failing, and the instruction that broke it was one this work
added.** `selection-2` told the planner that "`entities`, `time`, `place`, `capture` and
`semantic_query` are each either a value or null". `time` is an **array** and takes no null. A
model that tried null there would be refused by the schema, so it filled the field instead. That
line was added one turn earlier, while fixing the entity case.

`selection-3` states the empty value per field, says a window is half-open with `end` strictly
after `start`, and says never to put the current time in a window at all. **A test now holds the
prompt against the schema it describes**, so the two cannot drift again; the negative control is
in the commit message of its own test, and the `selection-2` wording fails it.

Measured after: `time: []` on all five questions and no planner failure in any pass. The
abstention from step one therefore no longer fires here. It remains the floor for a planner that
genuinely cannot produce a runnable Selection, and its tests drive that shape directly.

**Step three: the composer had to learn two things before the answer was honest.** With the
planner succeeding, the question reached the composer, and:

* Asked who is in them, on a workspace with zero entities and zero captions where every packet
  line carries `text: null`, it wrote *"This photograph features an individual not further
  identified"* three times, each citing a token that resolves. **The validator passed it.**
  Mechanism 1 checks that a claim is supported by a source; it cannot check what that source
  depicts.
* Asked for an exchange rate it answered *"51 photographs are captured"*, which invents nothing
  and answers nothing.

Two rules close both: you have not seen any photograph and know nothing about one with no
description, and if the evidence has nothing to do with the question, say so plainly and stop.
Plus a list of this system's own words that may not appear in an answer, because the first draft
of the rule modelled the very word it was forbidding and the model dutifully echoed it.

**Three of those rules are held by the prompt and nothing else**, and that is stated here rather
than implied. The validator cannot refute a claim about what a photograph shows.

Two things stay refusals, deliberately:

* `POST /selection/plan` still answers 502. Its whole job is to return a plan, so it has nothing
  to abstain with.
* `unknown_reference` on a **caller-supplied** plan is still 404. That code is deliberately one
  code for "not there" and "not yours" so the surface is not an existence oracle, and answering
  200 would let a stranger read existence off the difference between an abstention and a refusal.
  Only an id the model invented abstains.

**The composer is the latency, and its own fallback is four times faster.**

| Model | Role | Packet 1 | Packet 2 | Packet 3 | Conformed |
| --- | --- | --- | --- | --- | --- |
| `Qwen/Qwen3-235B-A22B-Instruct-2507` | planner | 1.1 s | 2.5 s | n/a | yes |
| `nvidia/Nemotron-3_5-Lightning` | composer | 16.7 s | 21.8 s | n/a | yes |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | composer, pinned | 7.9 s | 7.4 s | **never finished** | twice of three |
| `nvidia/nemotron-3-super-120b-a12b` | escalation | 2.3 s | n/a | n/a | once of three |

The reasoning core spends almost all of its wall clock on reasoning it cannot be told to skip:
4354 of 4416 completion tokens on one answer, 5673 of 5731 on the other. Its declared fallback
answered the same packets in roughly a fifth of the time and reported no reasoning tokens at all.

**And on a third packet the fallback ran away.** It spent all 32768 completion tokens without
producing an answer, and the composer fell through to the deterministic floor. That is why
pointing `reasoning_cheap` at the Nano is offered here as a proposal and not made: two packets in
a fifth of the time and a third that never finished is a reason to measure more, not a model swap
this measurement supports. It is also a change to `models.manifest.json`, which this task was
told not to edit.

`nvidia/nemotron-3-super-120b-a12b` conformed once and did not twice. On one ten-item packet it
returned exactly what the original note describes, text that is not JSON at all; on another it
answered correctly; on an empty packet it returned a top-level JSON array rather than an object.
It is reliably neither, which is why nothing routes to it, and why validating every reply locally
is what makes the difference visible instead of silent.

Spend: 6678 micro-dollars for the recorded pass, about 55000 across all nine passes, against a
cap of $0.50. The balance behind it was NOT verified: the
inference API exposes no balance endpoint and the Token Factory console failed to render its
billing panel, so a three-token embedding call was made first to prove the credential serves and
the prepaid balance is not exhausted.

## 7. The answer, in the running app

Driven in a browser on 2026-09-09 against a throwaway world at the branch's own schema, because
the retained bowl database is at 0038 and `GET /graph` here needs 0041. Nothing was migrated: a
separate schema was created inside the same permitted test database and three photographs were
ingested into it.

One gate was bypassed and it is named here so nobody has to guess which: **Pointer Lock**. The
app enters traverse mode only on a `pointerlockchange` event, and no browser automation can
acquire the lock, so `document.pointerLockElement` was overridden and one event dispatched.
Everything after that ran for real.

What happened, in order:

1. The Companion opened on the `acknowledge` turn, with `Other…` and the escapes. That is what
   `generateTurn` returns on a library with no named entities, and it is why
   `refused.noSubject` had to be routed.
2. `Other…` opened the composer. "when were these photographs taken?" was typed and submitted.
3. `companion-runtime` refused it with `refused.noSubject`, the controller sent it to
   `POST /selection/ask`, the encounter showed **Looking through your library**, and the avatar
   went to `working`, its three pulsing dots.
4. Fifty-eight seconds later: *"Historical: this photograph was taken on 2026-02-01, as part of a
   selection of 3 captures spanning from 2026-02-01 to 2026-03-04."* Under it, **Answered by
   nvidia/Nemotron-3_5-Lightning in 58.2 s.**
5. `E` opened the cited photograph, and the request it made was
   `GET /api/evidence/{span}/masked`. That is the whole point of the second request: the citation
   token became an openable span through the permalink join, and it opened through the route that
   applies person masking rather than the permalink route that returns the original bytes.

**Running it found a defect the tests did not.** The avatar's working state was set and
overwritten inside one tick: `main.ts`'s `onSay` calls `say(text)` and then
`reflectTurnState(current())` on the next line, the open turn is `acknowledge`, and that sets the
presence back to `resting`. The presence sat still for the whole fifty-eight seconds. The
controller now reports the working state on a microtask, after the caller's own synchronous
handling, and a test whose host does what `main.ts` does holds it.

The model wrote `Historical: ` into its own sentence, which is the clause type leaking into
prose. The composer prompt already says bookkeeping is not prose. Not fixed here; recorded.

## 8. Reproducing the measurement

`scripts/measure_companion_questions.py` asks five questions through the real HTTP route, then
composes the same packets with the composer role pinned to
`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, then makes one call to
`nvidia/nemotron-3-super-120b-a12b` to record whether it still answers with something that is not
JSON. It edits no manifest file and does not move `pipeline_version`: the pinned comparison
replaces one role binding on an in-memory copy.

It refuses to start unless the operator's ceiling is stated twice, once in `EXULANICA_BUDGET_USD`
where `BudgetGuard` reads it and once on the command line where a person typed it, and the two
agree. A single statement would let an accidental default look like an authorisation, and the
guard's own default ceiling is five dollars.

`--skip-live` exercises only what spends nothing: the deterministic packet route and the 503 an
instance without a model credential answers `POST /selection/ask` with.

The reference launcher strips `NEBIUS_API_KEY` by design and is not edited. A live run starts
uvicorn directly with the same environment it sets, plus the key and the two budget variables.

---

## 9. The Companion now remembers, and what that changed

Everything above happened inside one page. `web/packages/companion-runtime/src/memory.ts` held
the whole model of what the Companion had been told: the Not sure and Skip cooldown windows, the
wrong-question signal, the dismissed threads, a transcript of every turn. All of it was built at
mount and dropped at unload.

**That was not a missing nicety, and the sharpest way to say so is with the contract's own
words.** `interaction-model.md` 4.3 and 5.5 both say the Companion may never speak "within 7 days
of a Skip or 14 days of a Not sure on the same entity". A fourteen-day window held in a page a
reload discards is a fourteen-day window that had never once been enforced past a single page
view. The person who said "not sure" and came back the next day was asked the same question again,
by a system whose own contract said it would not.

`product-direction.md` makes the durable half a delivery gate in the Improvement over time table,
on the Companion continuity row: **"Persist approved memory, retrieve it across sessions, and
support correction and deletion; this is not model weight training."** All four verbs are section
10. Nothing in this work trains anything.

### 9.1 Conversation text is stored, and it is not a policy input

This is the boundary worth stating first, because storing conversation durably for the first time
is exactly the change that makes it easy to erode. There is now a table full of the very text the
interaction-policy plane refuses, one import away from it.

`exulanica/world/interaction_repository.py` refuses a proposal whose input carries `conversation`,
`messages`, `raw_utterance`, `transcript` or `prompt_text`, and 0021 says the same in its own
header: that plane "contains no camera pose, open panel, pending choice, conversation transcript,
topology, renderer code, or neural weights".

**That refusal is not a statement that conversation text may never be stored.** It is a statement
that it may never become an INPUT TO A POLICY DECISION about what this system is permitted to do.
A question somebody typed is evidence about that person. A capability the system may exercise is a
rule. Letting the first author the second is how a typed sentence silently widens a permission.

The word "policy" means two different things across these files and the collision is why this is
spelled out. 4.4's "policy over the entity graph snapshot plus the conversation transcript" is the
TURN GENERATOR: per session, in the browser, choosing the next question. The plane the exclusion
protects is the durable capability policy. The first may inform the next question and may never
author the second.

Held three ways, and only one of them is the existing refusal:

* **Structurally.** Neither `exulanica/world/companion_memory.py` nor
  `exulanica/api/routes/companion.py` imports an interaction type, so a call site that wanted to
  launder a question into a capability decision has to add the import first, in a diff a reviewer
  can see. A test parses both files and fails on one.
* **In the schema.** No foreign key joins the two planes in either direction, checked against
  `information_schema` rather than asserted.
* **By the existing guard**, re-driven with real stored text under every one of the five refused
  keys, so the thing being refused is the thing this branch actually keeps.

The one limit, stated rather than implied: `_private_keys` walks keys and never values, so a
transcript filed under an unlisted key is not caught. That limit is the interaction plane's and
was not this task's to change. What this branch adds is a test that fails if the five refused
names ever shrink, because a set losing a member is indistinguishable from the guard working right
up until somebody uses the removed name.

## 10. Migration 0043, and what a withdrawal reaches

Three tables, all workspace-scoped under FORCE row-level security, all append-only:
`companion_answer`, `companion_answer_citation`, `companion_escape`.

**A correction supersedes and never edits.** The spine settled this shape for `assertion` already:
`supersedes`, a status enum, and a trigger whose hint reads "Write a new assertion with supersedes
set, or record a retraction." The reasoning transfers exactly. A correction is somebody telling the
system it was wrong, which is the most valuable row in the table; an UPDATE that overwrote the
wrong answer would destroy the evidence that the system had ever been wrong, which is the one
record the correction exists to create. 5.4: "Nothing is ever silently rewritten."

The correction inherits the superseded answer's citations verbatim, and that is not tidiness. It
is the same question about the same photographs, so it must be reachable by the same withdrawal.

**A withdrawal reaches this plane through the machinery that already exists.**
`domain-and-evidence-model.md` 6.4 names the failure in its own words: "a generated title naming a
person can be invalidated when that person is deleted. Without the recorded set, the name survives
its own deletion inside a caption." An answer is a generated title with a longer sentence.
`companion_answer_citation` is the recorded set.

Both halves of 0035's lesson are present and they are different mechanisms:

| | What it does | Where |
| --- | --- | --- |
| Backwards, at tombstone time | Withdraws every stored answer the new tombstone reaches | `tg_tombstone_withdraws_companion_memory`, AFTER INSERT ON tombstone |
| Forwards, afterwards | Refuses a NEW citation of evidence a tombstone already covers | `tg_companion_answer_citation_live`, BEFORE INSERT |

The sweep asks the existing `tombstone_blocks_capture` and `tombstone_blocks_span` predicates
rather than branching on the scope name, so it is correct for workspace, capture and interval
scopes at once and a fourth scope would not need a fourth branch. It is also independent of
trigger order: `tombstone_blocks_capture` reads the `tombstone` table directly and never looks at
`capture.deleted_at`, which another trigger writes.

**The forward half REFUSES where 0035 marks stale, and the asymmetry is deliberate.** 0035 argues
that refusing an insert "would fail the whole ingest for a workspace where somebody has withdrawn,
which turns exercising a right into an outage". Neither half of that applies here: one composed
answer is not an ingest, and an answer citing withdrawn evidence has no legitimate remainder to
preserve. Refusing costs one unstored answer the person can ask for again.

**What it deliberately does NOT reach, named rather than half-solved:** an entity tombstone.
Withdrawing a person does not withdraw the photographs they appear in, and the cascade 0030 and
0035 build for that case works on `person_derivative_dependency`, which a Companion answer has no
row in. An answer that named a withdrawn person is a real problem and a different one: it would
need the answer's text attributable to an entity, which nothing records, because the composer is
never told an entity id.

### 10.1 Why 0043 sits above a gap

0042 is assigned to a concurrent task and this number was reserved above it, so this branch
carries a hole until that one lands. **Closing it by renumbering would be the worse failure by a
wide margin.** Two branches claiming one number merge cleanly, because neither touched the other's
file; `apply_pending` then runs both bodies and records only the first, and the next boot refuses
to start citing checksum drift on a schema that has already forked. That is what
`exulanica/migrations/__init__.py` refuses to enumerate, in those words. A hole is visible and
harmless; a collision is invisible and is not. `tests/test_migration.py` names the reservation and
fails once 0042 lands with the entry still in place, so the list shrinks on its own.

### 10.2 The routes, and one thing they are not

`GET /companion/memory/recent`, `POST /companion/memory/answers`, `POST /companion/memory/escapes`,
`POST /companion/memory/answers/{id}/corrections`, `DELETE /companion/memory/answers/{id}`.
Authenticated by the same session dependency as everything else; the actor comes from the resolved
session and no request model carries one.

The actor is the SCOPE here rather than provenance, which is why `CompanionMemoryRepository` takes
it as a constructor argument and not as a per-method keyword. Row-level security keys on the
workspace and cannot see the actor, so `and actor_id=%s` in every statement is the whole of the
separation between two people sharing a workspace, and a keyword a call site can omit is the wrong
shape for the one clause that must never be omitted.

Deleting one memory withdraws its whole lineage in both directions. A correction quotes what it
corrected, so leaving the correction behind would leave the deleted thing on the screen inside its
own replacement.

## 11. Hydration, and what the reload actually shows

`companion-runtime` gains a durable shape and one function that folds it back:
`memoryFromPersisted` replays the stored escapes through `recordEscape` itself, in chronological
order, rather than writing `takenAtMs + SKIP_COOLDOWN_MS` into a map directly. Three lines saved
would have been a second implementation of a rule that already has one, and the failure that
prevents is the sharp one: somebody fixes a cooldown in the live path and the durable fold keeps
the old rule, so a window is one thing in this session and another after a reload. A test asserts
the two produce the identical instant rather than trusting that they do.

**What is durable and what is only this sitting is a decision, not a consequence of what was easy
to store.** `askedThisSession` is NOT hydrated: it exists to stop the generator looping on one
question inside one sitting, and hydrating it would permanently suppress every question ever
delivered, leaving the Companion silent for good on the library it knows most about. `later` is
not hydrated either, because 4.3 gives it "NO PENALTY" and says a dismissal is not re-opened "in
the same session"; a new session is not the same session, and carrying it over would turn the one
escape that costs nothing into the one that lasts forever.

The write-back hook lives in `ui/companion-encounter.ts` rather than in the controller, and fires
AFTER the answer is drawn and unconditionally. "After it is on the screen" is then a fact at that
call site instead of an assumption about microtask ordering somewhere else, and a host that keeps
answers cannot delay one reaching the screen or stop one arriving. A write-back that fails is
drawn UNDER the answer as its own sentence: a durability failure is not an answer failure, and
what is on the screen is still correct and still cited.

An answer whose cited photographs the packet could not locate is not stored at all. Dropping the
unlocatable citations and keeping the rest would be the same defect wearing a tidier shape, because
the citation set is the join a withdrawal travels along.

**`main.ts` is not edited on this branch.** It is the composition root and several concurrent
branches own it at once, so the wiring ships as `docs/patches/companion-memory-main.patch`, exactly
as `companion-question-main.patch` did before it. `persistedMemory` and `rememberAnswer` are
optional and a host that has not applied the patch gets the behaviour it had. That is deliberate
rather than a courtesy: a default that half worked would be a Companion claiming to remember and
quietly not.

### 11.1 In the running app

Driven in a browser on 2026-09-09 against a throwaway world at this branch's own schema, for the
reason section 7 gives: the retained bowl database is at 0038 and this branch needs 0043. Nothing
was migrated. Three photographs were ingested through `CountingVisionModel`, the test fake, so the
browser check spent nothing.

One gate was bypassed and it is the same one: **Pointer Lock**. Everything after that ran for real.

1. On first paint, before any question, `GET /api/companion/memory/recent?limit=50` returned 200.
2. Summoning the Companion put the previous answer back on the screen, with its provenance line,
   under `data-remembered="true"`, which is what says it was read back rather than composed and is
   why it was not stored a second time.
3. `Open the photograph` on that restored answer made `GET /api/evidence/{span}/masked`. The
   citation survived the reload as something that opens, through the route that applies person
   masking rather than the permalink route that returns original bytes.

**Running it found a defect the tests did not, again.** A restored answer's chip rendered
correctly and opened nothing. `evidenceAt` resolves a chip against the CONTROLLER's held answer,
and the restore had been drawn by calling the panel directly, so the lookup fell through to the
open turn, which was an acknowledgement with no evidence. Both halves were individually correct
and the citation on the screen was dead. Restoring now goes through the controller, and a test
holds it.

## 12. The composer swap, measured and made

Section 6.1 offered pointing `reasoning_cheap` at the Nano as a proposal and refused to make it:
"two packets in a fifth of the time and a third that never finished is a reason to measure more,
not a model swap this measurement supports." The single runaway is what held it. This is 48 more
composer calls on the same packets, and the swap is now made. The record is
`docs/evaluation/2026-09-09-companion-memory.json`; the harness is
`scripts/measure_companion_memory.py`.

Four questions, two models, two ceilings, three passes each. The packets are rebuilt once per
question and reused across every cell, so exactly one thing varies.

| Composer | Ceiling | Calls | Median | Min | Max | Reasoning tokens | Rejections | Ran away |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | 32768 | 12 | **3.6 s** | 1.9 s | 6.8 s | none reported | 0 | 0 |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | 16384 | 12 | 3.5 s | 2.3 s | 8.6 s | none reported | 0 | 0 |
| `nvidia/Nemotron-3_5-Lightning` | 32768 | 12 | **18.6 s** | 10.4 s | 44.1 s | 5190 | 1 | 0 |
| `nvidia/Nemotron-3_5-Lightning` | 16384 | 12 | 21.5 s | 7.1 s | 53.4 s | 5836 | 0 | 0 |

**5.1 times faster at the median, and the Nano's worst case is below the Lightning's best.** The
mechanism is in the usage object rather than in the parameter count: the declared primary spends a
median 5190 reasoning tokens per answer and the Nano reports none at all, on answers of about 60
tokens either way.

**The runaway did not reproduce.** Zero of 24 Nano calls exhausted the ceiling and zero reached the
deterministic floor. That does not explain the recorded one; it bounds it at under one in
twenty-four rather than the one in three that was visible before.

**The one conformance failure belonged to the declared primary.** Zero validator rejections in 24
Nano calls, one in 24 Lightning calls, and it is worth naming: *"clause 0 references value
'capture_count: 51', which the packet does not have"*.

**Cost is not the reason and is not a saving.** Both models are $0.06 per million input tokens and
$0.24 per million output. This is a latency and conformance decision.

**The context rationale it replaces.** The role's rationale read that context length, not parameter
count, was the binding constraint. A ten-item packet measured 1325 prompt tokens, so the Nano's
262144 window holds roughly two thousand items and the constraint was never binding at any observed
size. The Lightning stays as the fallback and keeps its 1048576 window for the case where it
becomes so. `pipeline_version` moves 1 to 2 because it is an input to the response cache key.

### 12.1 The second ceiling changed nothing, and is not moved

16384 was chosen because it is the largest ceiling at which this call has ever been recorded to
fail: `COMPOSER_MAX_TOKENS`'s own comment says the composer "conformed at 16384 on a 24-item packet
and TRUNCATED at the same ceiling on an 8-item one", with no artifact behind it.

It did not reproduce. Nothing truncated at either ceiling for either model in 48 calls, and the
medians differ by less than the spread inside a single cell. That is not a refutation: the packets
here are ten items and the note describes an eight-item one, and a note with no artifact cannot be
refuted by a run that does not reproduce it. `COMPOSER_MAX_TOKENS` stays at 32768. It lives in
`exulanica/selection/question.py`, which this task may not edit, and nothing measured here asks for
it to move: the Nano's median completion is about 1100 tokens, so the ceiling is thirty times the
observed spend and is doing no work either way. The measurement rebound it in memory for the
duration of each call and restored it in a `finally`; no source file was touched.

### 11.2 What the gates say, including the part that is not green

| Gate | Result |
| --- | --- |
| `ruff check .` | clean |
| `lint-imports` | 4 contracts kept, 0 broken |
| web `typecheck` | clean |
| web `boundaries` | 0 violations, 386 modules |
| web `vitest` | 953 passed, 116 files |
| backend suite, this branch | 2272 passed, 7 failed, 14 errors |
| backend suite, unmodified `abe6040` | 2197 passed, 12 failed, 26 errors |

**The backend suite is not green and it was not green before this work either.** The branch is the
better of the two runs, and the residual failures are shared-database contention on one developer
machine rather than regressions. Three separate observations say so rather than one: two
consecutive full runs of the SAME commit produced DISJOINT failure sets; every file that failed on
the branch passes when run alone; and `test_world_read_views.py` produces the identical single
error on both commits. `tests/pg_harness.py` isolates by schema inside one shared database with
cluster-wide roles and a shared `public`, which is what makes a full campaign contend with itself,
and the harness says to serialize one.

What would settle it is a serialized run on a quiet database, or CI. That is not done here, and
the numbers above are offered as a comparison rather than as a pass.

Two environment gaps cost a confusing detour and are recorded so the next person skips it. A fresh
worktree needs `uv sync --extra reconstruction --extra server --extra pose`, or numpy and pycolmap
are missing and four tests fail in a way that reads exactly like a code regression. And
`.exulanica/` is gitignored, so a worktree has none, and the measurement scripts cannot find the
reference workspace ids until it is symlinked.

### 12.2 Streaming would not make the first words appear early

Token Factory does stream. `stream: true` returns `text/event-stream`, `stream_options:
{"include_usage": true}` puts the usage object including `reasoning_tokens` in the final chunk, and
reasoning arrives in a `reasoning_content` delta separate from the answer's `content` delta.

Three instants were timed separately, because conflating them would report a first token in
milliseconds for an answer whose first word arrives twenty seconds later:

| Composer | Ceiling | First SSE chunk | First reasoning | **First ANSWER word** | Total |
| --- | --- | --- | --- | --- | --- |
| Lightning | 32768 | 0 ms | 1 ms | **19.9 s** | 20.0 s |
| Lightning | 16384 | 0 ms | 1 ms | **34.2 s** | 34.4 s |
| Nano | 32768 | 0 ms | never | **2.8 s** | 3.0 s |
| Nano | 16384 | 0 ms | never | **4.9 s** | 5.1 s |

The first answer word arrives at 99.2% of the Lightning's wall clock at the declared ceiling, and
99.5% at the lower one. The cause is structural rather than incidental: the composer is schema
constrained, so the content channel carries one JSON object the model does not begin emitting until
it has finished thinking.

**So streaming is not implemented, and it is not proposed either.** It would buy between 0.5 and 8
percent of the wait and would surface a reasoning monologue the interface has nowhere to put. It
would also mean editing `exulanica/models/transport.py` and `client.py`, which are a `post_json` /
`get_json` protocol over a fully materialised response, and `exulanica/selection/question.py`, none
of which this task may write. The swap in section 12 takes the same wait from 18.6 seconds to 3.6,
which is the thing streaming was meant to hide.
