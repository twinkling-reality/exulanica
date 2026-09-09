# The Companion question path

Status: built, covered by tests, and measured once against the retained bowl workspace with real
models. Section 6 has what that measured. The record is
`docs/evaluation/2026-09-09-companion-question.json`.

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
* `docs/companion-question-main.patch` applies to `main.ts` at 5675b33, and section 7 is that
  patch applied and driven in a browser.

NOT established here, and stated plainly:

* **No answer quality is measured.** Five questions is not a gold question set, and
  `evaluation-methodology.md` M3 needs one before an abstention rate or a hallucination rate
  means anything. Section 6 records what four answers said and what two silences were; it scores
  none of them. Every test in this repository still drives a scripted transport.
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
| When were these photographs taken? | Answered, one cited historical clause | 42.3 s | 42.3 s | 2038 uUSD |
| How many photographs are there? | Answered, `capture_count` 51 | 43.5 s | 43.6 s | 2337 uUSD |
| What is this place? | Abstained, `UNANSWERABLE_NOT_CAPTURED` | 1.8 s | 1.9 s | 139 uUSD |
| Who is in these photographs? | Answered, hedged, named nobody | 38.9 s | 39.2 s | 2092 uUSD |
| What is the current exchange rate for the pound? | Abstained, `UNANSWERABLE_NOT_UNDERSTOOD` | n/a | 6.7 s | 0 |

**Nobody was named on a workspace with no named entities**, which is the failure the whole path
exists against. Across passes the "who" question came back both ways, sometimes as an abstention
and sometimes as an `uncertain` clause saying it cannot tell who is there; both are honest and
neither ever produced a name.

Composer latency is not stable. The same two questions measured 17.9 s and 24.3 s on one pass and
42.3 s and 43.5 s on another, on packets of the same size. An abstention is fast because the
composer is never called on an empty packet; the avatar's working state exists for the rest.

### The last row used to be a 502

A question about something outside the library came back HTTP 502 `model_refused`, which a caller
cannot tell from the server falling over. It now abstains.

**The cause was not what it looked like.** `entities` was null, so the empty-catalogue prompt was
working. The planner was asked a question carrying no time at all and stamped the same instant
into `start` and `end`, and a zero-width half-open window is empty by construction.
`CaptureWindow._non_empty` is a Pydantic model validator, invisible to a schema-enforcing
endpoint, so the failure lands locally after the endpoint has said yes. Reproduced three times
out of three, the same `[now, now)` window each time.

`answer_question` now catches the terminal planner failure and abstains under a fourth reason
code, `UNANSWERABLE_NOT_UNDERSTOOD`, with `plan` and `selection` null. It catches the same defect
wearing a 404 as well: `unknown_reference` on a plan the **model** proposed.

**A fourth code rather than reusing `NOT_CAPTURED`, and that is the whole argument.**
`NOT_CAPTURED` says "Nothing in your library matches". Saying that about a question nobody
searched would assert a fact about somebody's photographs from a failure to read their sentence,
and M3 would score it as a correct abstention. That is exactly the laundering M3 adds reason
codes to prevent, and it is the same argument that added `NOT_IN_MODALITY`.

**`plan` is null rather than empty**, because an empty plan is legal and means *everything*, and
reporting one would say the whole library was searched when nothing was. That is the same reason
`propose_plan` still refuses instead of returning one.

Two things are deliberately still refusals:

* `POST /selection/plan` still answers 502. Its whole job is to return a plan, so it has nothing
  to abstain with.
* `unknown_reference` on a **caller-supplied** plan is still 404. That code is deliberately one
  code for "not there" and "not yours" so the surface is not an existence oracle, and answering
  200 would let a stranger read existence off the difference between an abstention and a refusal.
  Only an id the model invented abstains, because that one was never the caller's to ask about.

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

Spend: 7360 micro-dollars for the recorded pass, about 25000 across all five passes, against a
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
