# Product specification

Status: mixed. Every claim carries exactly one label, per the convention in
[README.md](README.md): **VERIFIED** (primary source URL and retrieval date), **DECISION** (with the
alternative rejected), **ASSUMPTION** (with the experiment that settles it), **OPEN**.

Retrieval date for every VERIFIED claim on this page: **2026-08-27**, except the two deprecation
notices cited in section 8, which were re-read on **2026-08-28** and carry that date inline.
Promoted from the reconciled research in `.exulanica/` (reconciliation date 2026-08-27). Where the
research recorded a disagreement as unresolved, it is preserved here as unresolved.

Companion document: [interaction-model.md](interaction-model.md) covers the spatial and interaction
design. This page covers what the product is, what it does, and what it deliberately does not do.

---

## 1. What Exulanica is

**DECISION, updated 2026-09-08.** Exulanica is a Personal World Memory Model for building a
customizable world from personal experiences and extending it through creation. Movement and
interaction are the longer-term simulation ambition. The current authority for product scope and
delivery order is [product-direction.md](product-direction.md).

The remaining sections retain earlier implementation decisions and research. Still-image intake
is a current implementation boundary, not the product identity. The earlier memory-exploration MVP
is superseded by the creative-world demonstration in the linked direction document.

Three constraints continue to apply:

1. Historical claims resolve to original evidence. Creative worlds may depart from that evidence,
   with their changes preserved as authored or generated state rather than historical fact.
2. Models may propose identities; an identity link needs confirmation before it supports a
   historical factual claim. The separate person-proposal policy decision remains unresolved.
3. Reconstruction limitations and missing information remain visible. Future simulation must not
   be implied by a static rendering or a generation receipt.

### 1.1 Why commitment 2 is forced, not chosen

VERIFIED. Open-set face identification reaches only about **60% identification rate at FAR = 0.01**
for the best evaluated method, and the source explicitly warns that thresholding verification-like
scores is a widespread misconception as a solution to open-set identification.
https://ar5iv.labs.arxiv.org/html/1705.01567

VERIFIED. Person re-identification collapses across domains: `osnet_x1_0` scores 94.2% rank-1
same-domain on Market-1501, while the domain-generalization variant `osnet_ain_x1_0` scores
**52.4% rank-1 / 30.5% mAP** on Market1501 to DukeMTMC.
https://raw.githubusercontent.com/KaiyangZhou/deep-person-reid/master/docs/MODEL_ZOO.md

VERIFIED. Cloth-changing re-identification 2026 state of the art on LTCC is **56 to 58% rank-1 /
30 to 32% mAP**. https://arxiv.org/html/2606.11661

At those numbers, autonomous cross-capture identity is not a feature that needs polish. It is a
feature that cannot be shipped. The user confirmation loop is therefore load-bearing product
structure, and it is presented that way: uncertainty surfaced and resolved by the user **is** the
demonstration, not an apology for a weak model.

---

## 2. Corpus decision, and the scope correction it forces

### 2.1 The corpus is photographs

**DECISION.** The MVP corpus is a personal photograph library (a travel set). It is still images.
There is no video and no audio track.

Rejected alternative: a self-shot video corpus, which is what the research streams assumed
throughout. Video would supply speech, speaker turns, temporal continuity within a scene, and dense
multi-view frames for reconstruction. It was rejected because it requires shooting new material with
consented participants inside a 64 day window (reconciled report Q-H3, Q-H7, named there as the item
with the longest human lead time and no engineering recovery), and because it puts an entire
self-hosted ASR and diarization workstream on the critical path (A1, R-02).

### 2.2 Consequences that follow mechanically

| Brief said | Corrected |
| --- | --- |
| Captures are phone and smart-glasses video | Captures are photographs. A capture is a set of stills, not a clip |
| Recurrence spans people, **voices**, places, objects, **conversations**, events | Recurrence spans people, places, objects, events. Voices and conversations are deferred (2.3) |
| Claims resolve to an exact original **moment** in a timeline | Claims resolve to an exact original **image**, optionally to a normalized region inside it |
| Reconstruction consumes video frames | Reconstruction consumes photographs. Structure from motion over an unordered image set is the classic case, and the single-image rung is unaffected |

### 2.3 DEFERRED: recurring voices and recurring conversations

This is the largest correction to the brief, and it is deferred for **two independent reasons**,
either of which alone would be sufficient.

**Reason 1, no platform path. VERIFIED.** Nebius Token Factory has zero audio capability. The live
OpenAPI specification (`info.version = 20260825-124edf374`) contains zero case-insensitive
occurrences of `audio`, `transcri`, `speech`, `whisper`, `tts`, `asr` or `voice`. There is no
`/v1/audio/*` path and no `input_audio` content part. Chat message content is a discriminated union
of exactly three part types: `text`, `image_url`, `video_url`. The model catalog contains only
`text2text`, `image2text` and `embedding` types. The 235 entry documentation index has zero hits for
`audio`.
https://api.tokenfactory.nebius.com/openapi.json ,
https://tokenfactory.nebius.com/api/public/models_info ,
https://docs.tokenfactory.nebius.com/llms.txt
Found independently by three research streams and confirmed independently by adversarial verification
using three methods. It is the most solid fact in the corpus.

**Reason 2, no source material. DECISION.** Photographs have no audio track. Even with a self-hosted
ASR container on Nebius AI Cloud, there is nothing to transcribe.

What deferral means concretely:

- No claim about voices, speech, conversations, transcripts, speaker identity or "what someone said"
  appears in the product, the demo, the README, the documentation, or any marketing surface.
- The evidence spine keeps a `track` concept so that adding an audio track later is an extension
  rather than a rewrite (D3).
- The unresolved Sortformer v2 license question (reconciled report C-D1: `cc-by-4.0` versus NVIDIA
  Open Model License, unconfirmed by adversarial verification) is **not resolved by this deferral,
  only postponed.** It must be settled before any diarization code is written, whenever that happens.

### 2.4 What carries recurrence instead

Four entity kinds, all of which a photograph can support:

| Kind | Signal | Confidence posture |
| --- | --- | --- |
| Person | Face detection, alignment, embedding; same-day appearance vector | Proposal only. Never asserted without user confirmation (1.1) |
| Place | Scene and landmark recognition, EXIF GPS where present, user annotation | Proposal, with a strong user-annotation path |
| Object | Open-vocabulary detection | Proposal only |
| Event | Temporal clustering plus co-presence of confirmed people and places | Derived from confirmed links only |

**DECISION.** Because a person appears in a photograph without appearing in a *time interval*, the
cross-capture person link is the recurrence backbone, and it is exactly the link the measured
accuracy in 1.1 says must be user-confirmed. The product's most differentiating interaction and its
weakest model are the same thing, which is why the confirmation loop is the demo rather than a
settings screen.

---

## 3. The defining loop

The brief's seven step loop, corrected. Steps in bold changed.

| # | Step | Status |
| --- | --- | --- |
| 1 | A capture (a photo set) becomes a navigable memory region. Originals are retained under an append-only policy | Unchanged in substance, reworded in 6.1 |
| 2 | **A recurring person, place, object or event is proposed across separate regions** | Narrowed: voices and conversations removed (2.3) |
| 3 | The user confirms or rejects uncertain continuity and adds context the capture could not know | Unchanged, and promoted from courtesy to structure (1.1) |
| 4 | The Atlas filters and highlights around that continuity | Unchanged in intent. Implementation is a view transformation, never a rebuild (interaction-model.md section 7) |
| 5 | Natural language questions retrieve evidence across regions | Unchanged |
| 6 | **Every historical claim opens the exact supporting original image** | Reworded from "moment" (6.2) |
| 7 | A separate, opt-in public lookup connects a remembered public entity to its current state | Unchanged, and structurally quarantined (6.4) |

---

## 4. What the MVP will actually demonstrate

**Historical MVP scope, superseded for delivery priority by
[the product roadmap](product-direction.md#first-milestone).** The list below preserves the earlier
design target; it is not a statement that each item is implemented or visually accepted.

**In scope:**

- Three memory regions in one continuous Atlas, no loading screen between overview and interior,
  layout computed once and persisted.
- Desktop first-person navigation: pointer lock, WASD, reticle targeting, no jump, comfort settings
  honouring `prefers-reduced-motion`.
- Two verbs only: contextual Interact, and Summon Companion.
- The Companion: an embodied non-humanoid presence in the world plus a separate adaptive dialogue
  panel, with suggested replies, multi-select, free text, "Not sure" and "Skip".
- Structured update proposals with the four band provenance panel (what you told me / what the
  captures support / what I inferred / what I still do not know) and tiered confirmation.
- The World Index: a non-spatial, keyboard-first, fully equivalent path to every function, which is
  the desktop accessibility and direct-navigation route.
- The Atlas Map: the same scene from a high vantage, carrying a permanent caption that positions are
  not geographic.
- Cross-region view recomposition for single entity, OR, and AND (co-presence), with AND and OR
  visually distinguishable rather than only numerically different.
- Citations: every historical clause opens the exact source image, with the anchor in the world
  pulsing at the same time.
- The reconstruction rung earned by each region, displayed (section 5).
- Processing shown as spatial formation in the place the region will occupy, every visual state
  paired with a factual label naming the real pipeline stage (section 5.3).

**Out of the MVP, designed and deferred:** mobile delivery, entity split and delete
(tier 3 operations), batch operations, voice input, Companion spontaneous initiative (the ambient
open-question channel ships, the speech gate does not), glide traversal, and fine grained
reconstruction telemetry.

### 4.1 The core walkthrough

**DECISION**, adapted from the research's end to end path with the audio dependent steps removed.
The elapsed column indicates the pace a first-time user moves through the loop. It is not a budget
for any particular recording, and nothing in the product depends on hitting these marks:

| Elapsed | What happens |
| --- | --- |
| 0:00 to 0:20 | Land. The Atlas is already populated with three regions |
| 0:20 to 0:45 | Walk into a region, focus a person, two other regions light up |
| 0:45 to 1:10 | A pending continuity candidate appears. The user confirms or rejects it |
| 1:10 to 1:50 | The Atlas relinks visibly. A cross-region question is typed; the answer returns with citation chips |
| 1:50 to 2:15 | A chip is clicked; the original photograph opens with the supporting region highlighted, and the world anchor pulses simultaneously |
| 2:15 to 2:40 | An unanswerable question is asked; the system abstains and says why |
| 2:40 to 3:00 | The opt-in public lookup is toggled on; the result renders in a visually separate panel that cannot be cited |

**DECISION** on demo honesty, carried unchanged from the research: pre-ingested captures are
acceptable and **must be disclosed on the page itself**. Explicitly unacceptable: a progress bar not
driven by real job state, a spinner in front of a cached response, hardcoded answers, any query path
that special cases the scripted questions, or claiming live reconstruction over a precomputed asset.
A test runs the demo questions with the demo flag off and asserts identical results.

---

## 5. The reconstruction fallback ladder

**DECISION.** Four rungs. A quality gate runs automatically after pose recovery and after training,
and the Atlas renders whichever rung the region actually earned.

| Rung | Producer | Gate to earn it | What the user gets |
| --- | --- | --- | --- |
| 1, full navigable splat | Structure from motion, then Gaussian splat training, pre-baked offline | At least ~80% of images registered into a single model, low median reprojection error, real camera translation, held-out quality above threshold, floater count under threshold | Free movement inside a photoreal region |
| 2, constrained corridor | Same splat, but coverage is one sided or thin. A spline is fitted through the recovered camera trajectory, with a bounded lateral envelope and look-around cone, fading to a designed void outside the observed frustum | Poses and splat exist, but coverage analysis says the region only looks right near the capture path | A camera move along the path actually walked, with real parallax and freedom to look around. Reads as intentional framing, not as a wall |
| 3, 2.5D point maps from single images | Per image monocular metric point maps, no poses required, placed at recovered poses where they exist and on a derived path where they do not | **No gate that can fail.** Monocular depth is defined for every image | A constellation of photographic panels with real depth relief and a few degrees of true parallax each. Every panel opens its source image |
| 4, source first | Image thumbnails laid out by time and by semantic proximity. No geometry | Everything else failed, or the device is low power | A navigable spatial arrangement of evidence cards inside the same continuous Atlas. Cross-region continuity links still render |

Two rules from the research, carried without softening:

- **Rung 4 must be complete and good before rung 1 is attempted.** It is the product floor and the
  only rung with a 100% success rate.
- **Rung 2 is the highest value engineering investment in the ladder**, because it converts the most
  common partial success into something that reads as intentional rather than broken.

**The ladder admits no generated rung and no generated segment.** Every rung is defined by what was
recovered from photographs. Generatively completed geometry, meaning surface a world model invents
where no camera looked, is refused, and generated material of any kind, if it is ever shown at all,
is governed by [adr/0008-generated-geometry.md](adr/0008-generated-geometry.md).

**CORRECTED 2026-09-03, the rung 2 row.** The Producer column above says "the same splat" with thin
coverage. That was written before the corridor artifact existed, and the code it describes already
disagrees: `exulanica/reconstruction/navigation.py` publishes rung 2 from the corridor's own measured
clearance, slope and destinations, and a splat appears nowhere in its inputs. What defines rung 2 is
its fourth column, what the user gets. Two substrates deliver it: an accepted splat with thin
coverage, or camera poses with the monocular point maps of rung 3 placed at them. The artifact
records which, and the displayed sentence says so, because posed relief is not photoreal and must
never be described as though it were. See
[adr/0009-the-ladder-above-rung-3.md](adr/0009-the-ladder-above-rung-3.md) D2.

Reconstruction never runs in the live demo path.

### 5.1 The rung is visible, and that is the point

**DECISION.** Each region displays the rung it earned, in the interface, as a normal part of the
region's identity. It is not hidden, not smoothed over, and not described in language that implies a
higher rung than was achieved.

This is an honesty feature with a product payoff. A region that says "this is the path I walked, and
I cannot show you the other side of the room" is trustworthy in a way that a region silently
presenting garbage geometry as a room is not. It also makes the fallback survivable in front of a
first-time user: a rung 3 region is a designed outcome with a label, not a visible failure.

### 5.2 Rung wording

Labels state the capability, never the deficiency, and never overclaim. A rung 2 region does not say
"degraded". It says what the user can do and what they cannot. Exact copy is deferred to
implementation; the constraint is that no label may imply free movement in a region that does not
have it.

### 5.3 Processing is shown as formation, with honest labels

**DECISION.** While a capture processes, the region forms in the place it will occupy, and every
visual state is paired with a factual label naming the real pipeline stage and the real unit of
progress. There is no synthetic progress bar and no invented percentage. If remaining time is
unknown, no remaining time is shown; the count that is actually known is shown instead. If progress
is not measurable at all, the visual breathes rather than advances and the label reports elapsed
time.

**ASSUMPTION (A-29).** The ingest pipeline can emit real per stage counters over a server-sent event
stream. Experiment: inspect the pipeline stage boundaries and confirm counters exist, roughly two
hours of backend investigation. **This must be checked first**, because if the counters are not
available, several stages degrade to breathing plus elapsed time, which is still honest but is a
materially smaller design. Nothing else in the formation design should be built before this is
answered.

---

## 6. What Exulanica claims, and what it refuses to claim

### 6.1 Retention: "append-only by policy", never "immutable"

**VERIFIED.** Nebius Object Storage does not support Object Lock or Legal Hold. Verbatim from the
documentation: "Write-once-read-many (WORM) retention policies are not supported."
https://docs.nebius.com/object-storage/interfaces/s3-api-compatibility

**DECISION.** Enable bucket versioning at bucket creation time, write originals under
content-addressed keys, and deny delete permissions to the runtime service account by bucket policy.
The words **immutable**, **WORM** and **tamper-proof** are banned from all product copy. The
supportable phrase is "append-only by policy".

### 6.2 Citation: exact, and now genuinely exact

The reconciled report demoted "every claim resolves to the *exact* moment" because word level speech
timestamps do not support it. **VERIFIED**: at a 200 ms collar with exact word match, WhisperX
reaches 93.2% precision / **65.4% recall** on Switchboard and 84.1% / **60.3%** on AMI, meaning
roughly 35 to 40% of words on conversational audio lack a correct-within-200 ms timestamp.
https://www.isca-archive.org/interspeech_2023/bain23_interspeech.pdf

**DECISION.** That failure mode is a property of speech alignment. With a photograph corpus and no
audio there is no alignment step and therefore no alignment error: a citation addresses a whole
image, optionally with a normalized region inside it. The word "exact" is defensible for this corpus
for this reason and no other. **If audio is ever added, the A3 hedge returns with it** and the copy
must change back at the same time.

The evidence address defined in the research is
`(sha256 of the original bytes, track key, exact rational time interval [, normalized region]
[, transcript char range])`, with a canonical axis of signed int64 nanoseconds. A still photograph
has no time interval, so the research left the address form for a still undefined.
**Settled in [domain-and-evidence-model.md](domain-and-evidence-model.md) section 1.5 (spine-9): a
photograph is a single-sample track (`track_key = img`) carrying a real, non-empty, half-open
interval `[0, 1)` nanoseconds, with wall clock held in a separate clock anchor derived from EXIF.**
That document owns the address; this one does not restate it. The consequence at product level is
that a citation to a photograph is a citation to the whole image, refined by a normalized display
space region when a region matters.

### 6.3 Identity: proposals, never assertions

Covered in 1.1 and 2.4. Four architectural guards from the research are load-bearing and are stated
here because they are product constraints, not implementation details:

1. No probe-image search endpoint exists at all.
2. Person clusters are tenant scoped with no global index.
3. Embeddings never appear in any API response or export.
4. **The system never proposes a real-world identity.** It proposes only "the same person as in these
   other captures". Names come solely from the account holder's own annotation.

Guard 4 also defuses defamation by mismatch, which is a live risk at the accuracy levels in 1.1.

**OPEN (Q-H4).** When may a biometric embedding exist for a person who has not consented? Three
research streams produced three incompatible rules. The reconciled recommendation is the middle one
(compute, propose, short time-to-live, persist only on confirmation), but this is a risk-appetite
decision for the operator, not an engineering one. It gates the confirmation loop and therefore gates
the defining loop's step 2 and step 3.

### 6.4 The public lookup is quarantined by construction

**DECISION.** The outbound query string for the opt-in public entity lookup is constructed server
side from a whitelist of public entity fields. There is no code path in which model generated text
becomes an outbound query string. Responses land in a separate store with no foreign key into the
memory graph, render in a visually distinct panel, **cannot be cited as evidence for any historical
claim**, and expire in 24 hours. An append-only log records the verbatim outbound string, including
denials, and is surfaced to the user.

This is required rather than defensive: the provider may reuse query data and forwards it to third
party search index providers, so everything sent outbound must be treated as permanently public.

---

## 7. Explicitly excluded

Excluded from the product, not merely from the MVP:

- **Always-on or background capture.** Exulanica ingests a library the user chose to give it.
- **Any blanket claim of on-device or local-only processing.** Configured hosted model paths send
  media to third-party APIs. Offline and local paths have different execution boundaries; see
  [development setup](development-setup.md). The README does not promise local-only processing.
- **Identifying strangers.** See the four guards in 6.3.
- **Any completion metric.** No streaks, no progress rings, no "N remaining", no urgency. The open
  question counter is allowed to read a non-zero number forever.
- **The words "unlearning", "forgetting" and "the model has forgotten".** The truthful phrasing is
  "removed from retrieval and from future training, with every derived artifact recomputed from the
  remaining data", which at the chosen learning level is exact by construction and is a stronger
  claim than approximate-unlearning methods can support.

Deferred with a path back:

- Audio, voices, conversations, transcripts and speaker identity (2.3).
- Mobile Atlas traversal (a platform constraint, see interaction-model.md section 2).
- Learned identity-classification weights. This identity subsystem stays non-parametric:
  per-entity exemplar sets with cohort
  normalized scoring and a three way accept / reject / ask decision. Rejected alternative, a small
  trained head over frozen embeddings for demo credibility, was rejected on measured evidence: a
  linear probe is 38.53 points behind a non-parametric cache at 1 shot and still 4.2 points below the
  no-training baseline at 16 shots per class.

That identity decision does not exclude scene-specific Gaussian training, which is implemented,
or settle the future world-generation and simulation work in the product roadmap.

---

## 8. Model plan, in one table

Detail and exact identifiers belong in
[model-and-service-selection.md](model-and-service-selection.md) and
[adr/0002-model-routing.md](adr/0002-model-routing.md). What matters at product level is that
**nothing depends on a model scheduled for removal.**

**VERIFIED.** Nebius removed 11 models from Token Factory Serverless on 2026-06-22 and removes 10
more on 2026-08-31. **CORRECTED 2026-08-28:** the August notice does not name one replacement for
both NVIDIA vision models. It maps `nvidia/Cosmos3-Super-Reasoner` to `MiniMaxAI/MiniMax-M3` and
`nvidia/Nemotron-3-Nano-Omni` to `nvidia/Nemotron-3_5-Lightning`, which declares no `image` use case,
so neither recommendation keeps both the vendor and the modality.
https://docs.tokenfactory.nebius.com/june-2026-deprecation-notice ,
https://docs.tokenfactory.nebius.com/august-2026-deprecation-notice (both retrieved 2026-08-28)

| Role | Choice | Note |
| --- | --- | --- |
| Reasoning, Companion phrasing, cross-region reasoning | NVIDIA text Nemotron: `nvidia/Nemotron-3_5-Lightning`, with `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, `nvidia/nemotron-3-super-120b-a12b` and `nvidia/Nemotron-3-Ultra-550b-a55b` as the declared alternates | All survive 2026-08-31. Satisfies the NVIDIA open model requirement |
| Vision sensor over photographs | A non-NVIDIA Token Factory vision model. `MiniMaxAI/MiniMax-M3` is Nebius' named replacement for the removed `nvidia/Cosmos3-Super-Reasoner`; `openbmb/MiniCPM-V-4_5` is the reconciled report's Apache-2.0 candidate | Selection between the two is deferred to the technology document. **All NVIDIA multimodal models leave Serverless on 2026-08-31 and none may be depended on** |
| Text embeddings | A Token Factory embedding model | Image embeddings do not exist on Token Factory and must be self-hosted |

**DECISION** on deprecation survival, because the hosted demo must run unattended for roughly 46 days
after feature freeze: every model ID lives in one manifest file and is never inlined at a call site;
a preflight check fails the build if any referenced ID is absent from the live catalog; every role
has a declared fallback exercised in CI; and the weekly uptime check includes a catalog diff, not
only a health ping.

**ASSUMPTION (A-33), high plausibility.** Another deprecation round lands between feature freeze and
the end of the unattended deployment window. It cannot be validated in advance, only mitigated
structurally as above.

---

## 9. Assumptions this specification rests on

| # | Assumption | Experiment that settles it |
| --- | --- | --- |
| A-28 | Reconstruction is legible enough that walking inside a region reads as a place. Named in the research as the highest-stakes assumption in the interaction stream | X-1, one day on real captures. If it fails, rung 3 carries the product |
| A-29 | The pipeline emits real per-stage counters | Two hours of backend inspection. Do this first (5.3) |
| A-18 | Single-signal cross-capture identity lands at Recall@1 40 to 65%. **Extrapolated, not measured. No recall number may appear in the README, the documentation or any marketing surface until it is measured** | X-6, one day |
| A-31 | Evidence references resolve to the exact source asset in the browser | X-3. Simplified but not eliminated by the move to stills |
| A-14 | Browser rendering budget on the actual demo hardware. Every desktop number in the corpus was extrapolated from different hardware | Measure on the real machine, one hour. Ship a frame-time-driven auto-downgrade so no guessed number is load-bearing |

## 10. Open items owned by this specification

| # | Item | Why it is still open |
| --- | --- | --- |
| P-1 | The consent rule for biometric embeddings of unconsented people (Q-H4, 6.3) | Three streams, three incompatible rules. Operator risk decision |
| P-2 | Exact rung labels shown per region (5.2) | Copy not written. The constraint is fixed; the wording is not |
| P-3 | Whether the corpus contains identifiable people who have not consented, and what that permits | Depends on P-1 and on the operator's own library. Not answerable from research |

---

## 11. Known limitations

**This section is part of the product, not a disclaimer bolted onto it.** Exulanica's argument is that
a memory system is only worth trusting when it is explicit about what it does not know. A
specification that held the user's memories to that standard and exempted itself would not be
credible.

Everything below is settled. Each item is a property of the product as scoped, with a decision or a
measurement behind it, not an outstanding fault. Unvalidated assumptions are in section 9 and
undecided questions are in section 10, and neither is repeated here. This is a curated list of
product-level limitations rather than a defect tracker, and it does not replace reading the sections
it points to.

| # | Limitation | Status | Specified in |
| --- | --- | --- | --- |
| L-1 | **Cross-capture identity is proposed, never asserted.** The measured accuracy of open-set face identification and of cloth-changing re-identification does not support autonomous linking, so a proposed link may drive layout, filtering and highlighting but may not support a historical factual claim until the account holder confirms it | DECISION, on VERIFIED measurements | 1.1, 2.4, 6.3 |
| L-2 | **No accuracy figure for cross-capture identity is published.** Exulanica's own recall has not been measured, and no recall or precision number appears in the README, the documentation, the demo or any marketing surface until it is | ASSUMPTION A-18, unmeasured | 9 |
| L-3 | **Reconstruction quality is uneven and is not guaranteed.** Each region renders at whichever rung of the fallback ladder it earned, and the earned rung is displayed rather than smoothed over. A photograph library shot as travel photography does not naturally contain the dense overlapping coverage rung 1 requires, so a region reaching rung 1 is the exception rather than the expectation | DECISION | 5, 5.1 |
| L-4 | **Reconstruction is precomputed and never runs in the live demo path.** The demo's pre-ingested state is disclosed on the page itself. A progress bar not driven by real job state, a spinner in front of a cached response, and any query path that special-cases the scripted questions are all out of bounds, and a test asserts the demo questions return identical results with the demo flag off | DECISION | 4.1, 5, 5.3 |
| L-5 | **Retention is append-only by policy, not immutable.** Nebius Object Storage does not support Object Lock or Legal Hold, so the property rests on bucket versioning, content-addressed keys and a bucket policy denying delete to the runtime service account. The words immutable, WORM and tamper-proof do not appear in product copy | VERIFIED | 6.1 |
| L-6 | **Nothing is private, local or end to end encrypted.** Media is processed by third party cloud APIs, the project does not inherit its providers' certifications, and it makes no claim of on-device processing, anonymity or regulatory compliance | DECISION | 7, and `privacy-consent-threat-model.md` |
| L-7 | **There are no voices, conversations or transcripts.** Deferred for two independent reasons: the platform has zero audio capability, and photographs carry no audio track. No claim about speech or speaker identity appears anywhere in the product, the documentation or any marketing surface | VERIFIED and DECISION | 2.3 |
| L-8 | **A citation resolves to a whole image, optionally to a normalized region inside it.** It does not resolve to a moment inside a span, because a still photograph has no span to index into. If audio is ever added, this wording changes back at the same time | DECISION | 6.2 |
| L-9 | **The embedding model has no in-catalog fallback, and vector search is exact rather than indexed.** `Qwen/Qwen3-Embedding-8B` is the only embedding-typed model in the Token Factory catalog, and its 4096-dimensional output is above pgvector's 4000-dimension index ceiling. Exact search is both faster and strictly more correct at personal-library scale, and it is not a design that scales to millions of vectors | VERIFIED | `runtime-verification.md` 7, `domain-and-evidence-model.md` 4.4 |
| L-10 | **Model availability is a live exposure for the whole unattended deployment window.** Nebius removed 11 models from Token Factory Serverless in June 2026 and removes 10 more on 2026-08-31. A further round landing between feature freeze and the end of that window is mitigated structurally, by one model manifest, a preflight check against the live catalog, a declared per-role fallback exercised in CI, and a weekly catalog diff. It is mitigated, not eliminated | ASSUMPTION A-33 | 8 |
| L-11 | **The hosted demo runs unattended for roughly 46 days**, which is the planning horizon between feature freeze and the end of the deployment window. The Nebius Serverless option is Preview grade, with no service level and no automatic recovery, so the API and database run on a Compute VM with a restart policy, behind an external health check, with a clearly labelled recorded tour on a second host as the fallback. Uptime is engineered for, not guaranteed | DECISION | `architecture-overview.md` 2.1, 7 |
| L-12 | **The current prototype is desktop/laptop only.** At or below the existing 60rem viewport boundary it displays a factual boundary notice rather than an unvalidated mobile Index or touch navigation mode | DECISION | 4, `interaction-model.md` 2.5, and ADR-0006 |

Two further limitations are named in their own sections rather than compressed into a row: the
consent rule for biometric embeddings of people who have not consented is undecided and identity work
does not begin before it is decided (section 10, P-1), and the per-region rung labels are constrained
but not yet written (section 10, P-2).
