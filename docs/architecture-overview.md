# Architecture overview

**Current direction, 2026-09-12:** read [product-direction.md](product-direction.md)
and [world-composition-contract.md](world-composition-contract.md) before using the
historical architecture below. The intended system combines memories, permitted
real-world selections and authored/fantasy variations in one interactive and
queryable world. The production renderer is PlayCanvas; earlier statements below
that renderer selection is open are historical. The composition contract identifies
unimplemented geography, retrieval and editing extensions; it does not change
existing API or package compatibility by itself.

- Status: mixed, labelled per claim. See `README.md` for the status convention.
- Date: 2026-08-27
- Source: promoted from the reconciled research report, Part D, with the disagreements in Part C
  preserved rather than resolved.

Every claim below carries exactly one label. **VERIFIED** claims cite a primary source URL retrieved
2026-08-27. **DECISION** names the alternative rejected. **ASSUMPTION** names the experiment that
settles it. **OPEN** is unresolved and stays that way here.

Two project decisions are inputs to this document rather than conclusions of it:

- The corpus is a personal photograph library. There is no audio. Nebius Token Factory has zero audio
  capability, so the recurring-voices and conversations pillars have neither a platform path nor
  source material. They are deferred, not claimed. See
  [product-specification.md](product-specification.md) section 2.
- Nebius removes all NVIDIA multimodal models from Token Factory Serverless on 2026-08-31. Nothing in
  this architecture depends on a model scheduled for removal.

---

## 1. System shape

**DECISION: a modular monolith for the request path, plus asynchronous jobs for everything that can
take minutes.** Rejected alternative: a service-per-capability decomposition. Rejected because the
whole system is one tenant's data with one consistency domain (section 3), and every service boundary
crossed by a delete would become a second deletion path that can be left half done. The nine-week
window and the single-operator team make network boundaries a cost with no compensating benefit.

The split that does exist is between work that must answer inside a request and work that must not.
Reconstruction, perception and batch ingest are minutes-to-hours, retryable, and idempotent. They run
as self-terminating jobs. A job failure is retryable; a database failure is not, and that asymmetry is
the only reason the boundary is drawn where it is.

### 1.1 Front-end module boundaries

**DECISION.** Module boundaries are enforced by a forbidden-imports contract, not by convention.

| Module | Contains | Forbidden imports |
| --- | --- | --- |
| `atlas-core` | scene graph, island frames, focus resolution, view manifest application, layout solver | React, DOM |
| `atlas-react` | renderer bindings, anchor overlay, HUD, comfort settings | graph mutations |
| `companion-runtime` | turn generation, option pool construction, proposal drafting, escape handling, initiative gate | renderer, React, DOM |
| `world-index` | index UI, entity detail, provenance panel | renderer |
| `graph-client` | entity graph reads and writes, assertion log, evidence resolution | all of the above |

Two of these boundaries are load-bearing and the rest follow from them:

- **`graph-client` is the only module permitted to mutate**, and it rejects any mutation whose
  proposal id is not in the pending proposal set. This is a runtime check, not a lint rule. It exists
  because the product's epistemic guarantee is that the system may organize on a guess but never
  assert on one, and that guarantee is worthless if any UI component can write an assertion.
- **`companion-runtime` and `world-index` may not import the renderer.** This is what makes the
  renderer question in ADR-0003 survivable: a renderer switch touches `atlas-core` and `atlas-react`
  and nothing else. Without the contract the blast radius is the entire front end.

`atlas-react` is named for a renderer binding layer, not for a specific engine. Which engine sits
under it is **OPEN**: see [adr/0003-renderer-selection.md](adr/0003-renderer-selection.md).

### 1.2 Replaceable interfaces

A boundary is only worth its cost if a specific, named, plausible event forces a swap across it.
These four qualify. Nothing else in the system is abstracted for the sake of abstraction.

| Interface | What it hides | The event it must survive | Evidence |
| --- | --- | --- | --- |
| Model manifest | every model id, and a declared fallback id in the same region tier for every role | **VERIFIED:** Nebius removed 11 models from Token Factory Serverless on 2026-06-22 and 10 more on 2026-08-31, two rounds in ten weeks. Sources: https://docs.tokenfactory.nebius.com/june-2026-deprecation-notice , https://docs.tokenfactory.nebius.com/august-2026-deprecation-notice | See section 7.2 |
| Renderer binding | scene graph and camera control behind `atlas-core` | **OPEN:** ADR-0003 is unresolved and settles at end of week 3 | ADR-0003 |
| Reconstruction rung | which of four reconstruction rungs produced a region, with the earned rung displayed to the user rather than hidden | **VERIFIED:** casual and egocentric footage breaks structure-from-motion at severe rates. BANMo registered 18 of 811 images on a motion-dominated casual clip. Source: https://arxiv.org/pdf/2112.12761 | Reconstruction is never in the live demo path |
| External lookup | the public-entity lookup provider, behind a server-side query constructor | **DECISION:** the feature is on the cut list. If its egress gate does not pass red-teaming, it is cut entirely rather than shipped leaky | Section 6.3 |

**DECISION: model ids are never inlined at call sites.** Rejected alternative: constants next to each
call, which is faster to write and makes the preflight check in section 7.2 impossible.

**Not abstracted, deliberately:** the database. There is one PostgreSQL and the schema is used
directly. A repository layer over it would buy portability nobody needs and would obstruct the
range, multirange and partition-prune behaviour that section 3 depends on.

---

## 2. Platform split and deployment topology

**DECISION.** Rejected alternatives are stated per line.

| Concern | Runs on | Notes |
| --- | --- | --- |
| Browser SPA | Vercel Hobby, static, $0 | **VERIFIED:** Hobby static upload cap 100 MB, 45-minute build cap. https://vercel.com/docs/limits |
| Splat, image and derived assets | Nebius Object Storage, eu-north1, Intelligent class, anonymous-read bucket policy, CORS, Range | See section 4 |
| API and PostgreSQL 18 + pgvector | Nebius AI Cloud Compute VM, `cpu-d3 2vcpu-8gb`, Network SSD volume, restart policy, nightly `pg_dump` to Object Storage | See section 2.1 |
| Asynchronous ingest and perception | Nebius Serverless AI Jobs, self-terminating, per-second billing | ASR and diarization jobs are deferred: no audio in the corpus |
| Reconstruction | Separate restartable worker; CPU pycolmap pose path runs now, while future gsplat work retains the proposed Nebius `gpu-l40s-a 1gpu-8vcpu-32gb` shape | Prepared asynchronously before a live request; no rung-1 GPU result is claimed |
| LLM, VLM and text embeddings | Nebius Token Factory, `https://api.tokenfactory.nebius.com/v1/` only | NVIDIA text Nemotron for reasoning plus a non-NVIDIA vision model as a sensor |
| Public-entity lookup | Tavily, opt-in, server-constructed query only | Section 6.3 |

**VERIFIED: region pinning.** All Nebius AI Cloud GPU work goes to eu-north1. Default GPU quotas show
us-central1 with no GPU type at a non-zero default at all, while eu-north1 has L40S = 2. Custom images
and disk snapshots default to 0 in every region, so workloads ship as containers and never as baked
custom images. Source: https://docs.nebius.com/compute/resources/quotas-limits

**VERIFIED:** Token Factory public endpoints report Region "Global" and Nebius warns the processing
location "can change at any time, without notice", and that a regional base URL "can stop working if
the endpoint's processing region changes". Per-model region strings are therefore informational for
latency, not for addressing. Source:
https://docs.tokenfactory.nebius.com/ai-models-inference/overview

**Rejected alternative: Cloudflare R2 as the asset origin.** Free egress would save roughly $2 to $10
across the project. Rejected because keeping the origin on Nebius keeps the platform constraint
literally true, and $2 to $10 is not worth qualifying it for. A Cloudflare edge cache in front of the
Nebius origin is compatible with this and is recommended for users outside Europe.

### 2.1 Where PostgreSQL runs: a preserved disagreement

**The research streams disagreed and the disagreement is real.** One stream recommended running
PostgreSQL as a container co-located with the API on a Nebius Serverless AI endpoint, which scores
marginally better on platform alignment. That recommendation puts the database on the least reliable
component in the stack.

The facts on both sides:

| Claim | Status | Source |
| --- | --- | --- |
| Serverless AI is Preview, with "no Service Level provided", and "does not provide automatic retry, recovery, or redundancy mechanisms". "Infrastructure failures may result in workload failure with no automatic recovery." | **VERIFIED** | https://docs.nebius.com/legal/specific-terms/serverless-ai |
| Typical Serverless AI endpoint lifetime is stated as "hours to days" | **VERIFIED** | https://docs.nebius.com/serverless/overview |
| Serverless AI has no pricing of its own: it applies Compute pricing and quotas. `2vcpu-8gb` is 2 x $0.012 + 8 x $0.0032 = $0.0496/hr = $35.71/month either way | **VERIFIED** | https://docs.nebius.com/serverless/pricing-quotas , https://docs.nebius.com/compute/resources/pricing |
| Volume mounting is documented for Serverless **jobs**. For endpoints it is undocumented | **VERIFIED (as an absence)** | https://docs.nebius.com/serverless/jobs/manage |
| Serverless AI has no automatic scale-to-zero. Endpoints support manual stop/start and bill per second of the underlying VM while active | **ASSUMPTION.** Settled by leaving an endpoint idle for one billing cycle and inspecting granularity. Partly answered already: the docs describe manual stop/start and no automatic scale-to-zero | https://docs.nebius.com/serverless/quickstart/endpoints |
| The deployment must survive roughly 46 days unattended, with no operator watching | **DECISION**, a stated planning horizon rather than an observed fact | Section 7.1 |

**Recommendation, and the reasoning: run the API and PostgreSQL on a plain `cpu-d3` Compute VM with a
Network SSD volume and a restart policy.** The cost is identical, the platform constraint is
satisfied identically because a Compute VM is still Nebius AI Cloud, and the difference is entirely
in recovery behaviour across 46 unattended days. The endpoint variant additionally rests on an
undocumented assumption about volume mounting.

Keep Serverless **Jobs** for reconstruction, perception and batch ingest. That is where the
self-terminating per-second model is a genuine fit, and where failure is retryable. It also still
captures the platform alignment benefit in the one place where it costs nothing.

**Rejected alternative: Nebius Managed PostgreSQL.** The on-brand choice. **VERIFIED:** the documented
`4vcpu-16gb` example is $0.28/hr, about $204/month, which is roughly +$755 across the project period
for a sub-1-GB database. Source: https://docs.nebius.com/postgresql/resources/pricing

**Rejected alternative: Render free tier.** **VERIFIED:** free web services spin down after 15 minutes
idle with about a minute to reactivate, and free PostgreSQL expires 30 days after creation. Against a
46-day unattended window that is fatal: the database expires 30 days in, with nobody present to
notice. Source: https://render.com/docs/free

**Rejected alternative: Fly.io.** Technically fine and cheap, but it is not Nebius, and running on
Nebius Token Factory or Nebius AI Cloud is a project constraint rather than a preference. Keep an
unused `fly.toml` as break-glass.

**OPEN:** the domain and the deployment account.

**ASSUMPTION:** that a Preview-grade service can be relied on at all for the unattended window. Settled
by experiment X-0b: run a canary Nebius Serverless AI endpoint continuously for the whole project and
log every restart, failure and unexplained outage. This experiment quantifies how right the
Compute-VM recommendation is rather than deciding it.

---

## 3. Storage

**DECISION: PostgreSQL 18 with pgvector >= 0.8.6 and native range and multirange types. No dedicated
vector database. No graph database.**

**VERIFIED:** PostgreSQL 18 (18.6, released 2025-09-25) ships built-in `uuidv7()`. PostgreSQL 14
reaches end of life 2026-11-12, inside the unattended window. Sources:
https://www.postgresql.org/docs/18/functions-uuid.html , https://www.postgresql.org/support/versioning/

**VERIFIED:** PostgreSQL provides a multirange type for every range type, indexable by GiST and
SP-GiST for `=`, `&&`, `<@`, `@>`, `<<`, `>>` and `-|-`, and usable in exclusion constraints. Source:
https://www.postgresql.org/docs/18/rangetypes.html

**VERIFIED:** pgvector index limits are lower than its type limits. The `vector` and `halfvec` types
accept 16,000 dimensions, but HNSW and IVFFlat index `vector` to only 2,000 and `halfvec` to 4,000.
Source: https://github.com/pgvector/pgvector/blob/master/README.md

**VERIFIED:** pgvector documents an overfiltering hazard. "With approximate indexes, filtering is
applied after the index is scanned." With a filter matching 10 percent of rows at default settings,
roughly 4 of 10 expected results are returned. Mitigations are `hnsw.iterative_scan`,
`ivfflat.iterative_scan` and `hnsw.max_scan_tuples`. Source: same.

**DECISION, CORRECTED 2026-08-27.** Embeddings are `halfvec(4096)` in a table partitioned by list
on `workspace_id`, so tenancy is a partition prune rather than a post-scan filter. The dimension is
not 1024: runtime verification **measured** `Qwen/Qwen3-Embedding-8B` at 4096 dimensions
([runtime-verification.md](runtime-verification.md) section 7), which is above pgvector's 4000-dimension ceiling
for an indexed `halfvec`, so the column carries **no ANN index and search over it is exact**. The
reasoning and the additive fallback are in
[domain-and-evidence-model.md](domain-and-evidence-model.md) section 4.4. The overfiltering hazard
above therefore does not currently apply, and `hnsw.iterative_scan = relaxed_order` is dormant until
an approximate index exists to set it on. **ANN is used for recall and ranking only, never for set membership.** A
question like "which people were present" is answered relationally from confirmed link rows, never
from a nearest-neighbour result.

### 3.1 Why one consistency domain matters

The argument is not performance. It is deletion.

Embeddings derived from a redacted interval leak the redacted content. A face embedding computed from
a photograph that the subject later withdraws consent for is not a pointer to that photograph, it is a
lossy copy of the subject's face. **The embedding must be purged in the same transaction as the
interval it was derived from.** Two storage systems means a two-phase delete, and a two-phase delete
can be left half done: the source is gone, the derived vector is not, and the system now holds
biometric data whose provenance record no longer exists.

One consistency domain makes that failure mode unrepresentable rather than merely tested for.

**Rejected alternative: Qdrant, Milvus or Pinecone alongside PostgreSQL.** Better pure-ANN
performance, and this is a real cost being paid. Rejected because every real query in this product is
ANN plus hard relational predicates plus a join back to evidence spans, and an external store forces
one of three outcomes: limited pre-filtering, lossy post-filtering, or a duplicated consistency
domain. The third is fatal for the reason above. A list partition per workspace is also, by
construction, the namespace isolation that the privacy analysis requires.

**Rejected alternative: Neo4j.** The graph here is shallow, and the expensive query, co-presence, is
an interval-overlap join. It is expressible directly as `range_intersect_agg` over `range_agg` of
per-entity presence multiranges under GiST. A graph database buys one query pattern the product does
not need and costs a second deletion path, which is the same defect as the vector-store alternative.

**ASSUMPTION:** that PostgreSQL alone holds at production scale. Settled by experiment X-18: HNSW at
1M and 10M `halfvec(1024)` rows, workspace-partitioned, with selective filters and
`iterative_scan=relaxed_order`, measuring build time, index size, p95 latency and recall@10.
**CORRECTED 2026-08-27:** as written this measures a configuration that does not exist. The column
is `halfvec(4096)` and carries no HNSW index. X-18 must either measure **exact** search at those row
counts, or be deferred until a truncated 1024-dimension recall column is added. It is
safe at demo scale regardless; the experiment decides what may be claimed beyond demo scale.

**ASSUMPTION:** that deleting an embedding physically removes it rather than filtering it from query
results. Settled by experiment X-11: delete an embedding, force compaction or partition rebuild, open
the raw index and assert the vector id is absent. Until X-11 passes, no residency claim may be
published.

---

## 4. Object storage reality

**VERIFIED: Nebius Object Storage does not support Object Lock, Legal Hold or write-once-read-many
retention.** Verbatim: "Write-once-read-many (WORM) retention policies are not supported." It also
does not support object ACLs, SSE-KMS or SSE-S3, S3 Select, static website hosting, bucket inventory,
replication, event notifications, or Object Ownership. Source:
https://docs.nebius.com/object-storage/interfaces/s3-api-compatibility

**VERIFIED:** anonymous public read exists, but only via bucket-policy rules using `"anonymous": {}`
with roles limited to `storage.viewer`, `storage.object-viewer` and `storage.object-lister`, at most
10 rules per bucket and 10 paths per rule. **This is not S3 `Principal` syntax**, so every S3 tutorial
for this step is wrong. Versioning, lifecycle, `PutBucketCORS`, `GetObject` (hence HTTP Range) and
full multipart upload are supported. Sources: same, plus
https://docs.nebius.com/object-storage/buckets/bucket-policy

**VERIFIED:** bucket versioning, once enabled, can only be suspended, never disabled. Enabling it on
an existing bucket takes up to 15 minutes; setting it at bucket creation is immediate. ETag is not
always MD5, so integrity checks must use `X-Amz-Checksum-*`. Source:
https://docs.nebius.com/object-storage/buckets/versioning

### 4.1 Append-only by policy

**DECISION.** The design that the platform can actually back:

1. Enable bucket versioning **at bucket creation time**, which avoids the documented 15-minute
   propagation window during which a newly-versioned bucket is not yet protected.
2. Write originals under content-addressed keys (sha256 of the original bytes).
3. Deny `DeleteObject` and `DeleteObjectVersion` to the runtime service account via bucket policy.
   The runtime can write and read. It cannot destroy.
4. Verify integrity with `X-Amz-Checksum-*`, never with ETag.

Deletion, when a user requests it, is performed by a separate privileged path, not by the runtime
service account. This is deliberately asymmetric: accidental or injected deletion is impossible from
the request path, while intentional deletion remains real. Note the tension honestly: versioning plus
delete-denial makes real deletion harder, not easier, and the deletion design has to carry that
weight rather than pretend the conflict does not exist.

### 4.2 Required wording

**DECISION, and it is a product constraint rather than a documentation preference.**

| Say | Never say |
| --- | --- |
| append-only by policy | immutable |
| versioning enabled, delete denied to the runtime service account | WORM |
| originals are content-addressed and are not overwritten in normal operation | tamper-proof |

The platform provides no cryptographic or administrative guarantee that a sufficiently privileged
actor cannot delete a version. "Append-only by policy" is exactly as strong as the bucket policy and
says so. Any of the three right-hand terms would be an overclaim, and one caught overclaim discounts
every other claim this project makes.

---

## 5. Query and answer safety

The product's core promise is that every historical factual claim resolves to the exact original
source moment. The architecture makes that mechanical rather than aspirational.

### 5.1 The restricted declarative query plan

**DECISION.** The model emits a **closed-vocabulary JSON QueryPlan**: a fixed intent enum, resolved
entity ids only, no table names, no column names, no operator names, no workspace id. A fixed compiler
turns the plan into parameterized SQL with **zero string interpolation of model output**. Free text
exists in exactly one field, the semantic query string, and becomes a bound parameter.

**Rejected alternative: model-generated SQL with a parser and an allowlist.** Rejected because a plan
that is a filled-in form has no expressive surface left to sanitize. Sanitizing generated SQL is a
containment problem; emitting a form is not.

### 5.2 Server-side validation, fail-closed

**DECISION.** Six stages, in order, each of which can only reject:

1. Structural schema validation.
2. Reference resolution. **Nonexistent ids and ids belonging to another tenant return the identical
   `unknown_reference` code**, so the surface is not an existence oracle.
3. Authorization derived from the session only, never from anything in the plan.
4. Cost bounds.
5. Compilation to parameterized SQL.
6. Execution in a read-only transaction with a `statement_timeout`.

Exactly one model repair attempt is permitted, then a deterministic clarifying question. There is no
silent repair.

**VERIFIED, and load-bearing:** PostgreSQL table owners bypass row-level security unless `FORCE ROW
LEVEL SECURITY` is set, and "Superusers and roles with the `BYPASSRLS` attribute always bypass the row
security system". Source: https://www.postgresql.org/docs/18/ddl-rowsecurity.html

**DECISION.** Execution connects as a non-owner `exulanica_ro` role that owns nothing and lacks
`BYPASSRLS`, with `FORCE ROW LEVEL SECURITY` on every table. An executor connecting as the table owner
makes every isolation policy silently inert, which is a failure with no symptom.

**ASSUMPTION:** that cross-tenant isolation actually holds end to end. Settled by two experiments.
X-9 seeds tenant B with high-entropy nonces in an OCR string, an annotation, a person label and a
filename, runs the full question corpus as tenant A, then greps every answer, evidence pointer, log
line, trace span and raw vector hit for B's nonces. X-14 is an authorization fuzzing harness that
sends tenant A's token with tenant B's resource id in every id-bearing position and asserts 404, never
403, on every endpoint, on every pull request. Until both are green, no isolation claim is published.

### 5.3 The bounded evidence packet and the citation validator

**DECISION.** The model never sees the corpus. It sees an **EvidencePacket** of at most 24
EvidenceItems, assembled by the deterministic query path. Each item carries a random 10-character
token that is valid only within that one packet, mapped server side to `(span_id, assertion_id)` for
the lifetime of the request.

Answers are **structured objects**, not prose: per-clause text, a clause type in
`historical | uncertain | meta`, citation tokens, and value references. Prose is rendered client side
from the structure.

**How the validator enforces citation rather than trusting the model to comply.** Three mechanisms,
none of which depends on the model behaving:

1. **The token space is unforgeable and packet-scoped.** The model cannot construct a valid reference
   to anything outside its packet, because tokens are random per request and resolve only through a
   server-side map. A hallucinated citation is not a wrong citation, it is a lookup failure, detected
   deterministically. There is no "plausible-looking" failure mode.
2. **Generated clause text may contain no digit sequence unless it is covered by a value reference
   from the deterministic query result.** This is a syntactic check on the output string, not a
   semantic judgement. It mechanically kills the highest-damage hallucination class in a memory
   product: a confidently invented date, count or duration.
3. **On a second validation failure the model output is discarded entirely and a deterministic
   templated answer is rendered from the query result and its citations.** That path is a first-class
   output, not an error page. A correct, cited answer therefore exists at zero model compliance.

Point 3 is what makes points 1 and 2 safe to enforce strictly: rejecting model output has a defined,
useful outcome, so the validator has no incentive to be lenient.

**Rejected alternative: generate prose and classify each clause as historical or meta afterwards.**
Retained only as a documented fallback if constrained JSON decoding proves unreliable. It is
materially weaker because the classifier is itself a heuristic sitting directly on the product's core
guarantee.

**ASSUMPTION:** that constrained JSON decoding is reliable enough on the chosen Nebius model to emit
schema-valid answer objects, and that a Nemotron honours `response_format: json_schema` at all. None
of the surviving Nemotrons carries the catalog's "JSON mode" tag, and the OpenAPI spec and the docs
disagree on structured-output support. Settled by experiment X-4: run the answer schema against the
chosen model over roughly 200 real questions with 24-item packets and measure schema-valid rate and
validator pass rate, then separately run 20 nested-schema extraction requests with
`response_format json_schema strict:true` and repeat with `extra_body.guided_json`. If both fail, the
fallback is prose plus a clause classifier, or a non-NVIDIA model for extraction while the Nemotron
call retains the reasoning step.

---

## 6. Prompt injection posture

**VERIFIED:** OWASP LLM01:2025 distinguishes direct from indirect prompt injection, explicitly flags
multimodal injection (instructions hidden in images) as expanding the attack surface beyond what
current defences reliably detect, and states that its seven mitigations are mitigations rather than a
complete fix, "because injection is inherent to how generative models process input". Source:
https://genai.owasp.org/llmrisk/llm01-prompt-injection/

That verified statement sets the goal. The goal is not to make injection impossible. **The goal is to
make the model's authority not worth stealing.** Exulanica is unusually exposed for a photograph corpus:
any sign, screen, poster or handwritten note visible in a photograph is OCR-able text that enters the
pipeline, and the attacker does not need access to the system to place one.

### 6.1 Trust tiers

**DECISION.** Three tiers with **transitive propagation**:

| Tier | Contents |
| --- | --- |
| T0, trusted | system prompt, schemas, server-constructed templates |
| T1, semi-trusted | the user's own question |
| T2, untrusted | OCR text extracted from photographs, user annotation text, external page content, and transcripts if audio is ever added |

**Any model output derived from T2 is itself T2.** This is the rule that stops laundering: a summary
of an injected sign does not become trustworthy by passing through the model once.

T2 never enters the system prompt. It is delivered in a typed JSON envelope delimited by a
**per-request random nonce**, which injected content cannot guess and therefore cannot close. A fixed
delimiter such as a `<document>` tag can be closed by the attacker and is rejected for that reason.
T2 renders as escaped plain text with no HTML, no markdown image loading, and no auto-linkification.

**DECISION: regex denylists and injection classifiers are telemetry only, never gates.** A gate that
fails open creates false confidence, and every published classifier fails open on some input. They are
worth running to see what is being attempted; they are not worth trusting.

**ASSUMPTION:** that the nonce envelope and trust tiers hold against real multimodal injection, and
that the defences are not English-only. Settled by experiment X-10: stage physical signs including one
low-contrast, one mirrored or inverted, one non-English, and one using zero-width characters and
homoglyphs, photograph them, and assert the answer is unaffected and the sign is reported as cited
content. The experiment carries a benign arm measuring injection-induced degradation on 10 ordinary
questions, because a system that resists by refusing everything scores perfectly and is useless.

### 6.2 The policy engine the model cannot talk past

**DECISION: the LLM has no direct tool-calling authority.** It emits a proposed action into a
structured field. A server-side policy engine decides whether that action executes, by checking:

1. A valid, single-use user gesture token. No user gesture, no side effect. There is no path from
   model output alone to a state change.
2. Tenant ownership of every id in the payload.
3. Payload conformance to a minimisation schema.
4. An egress allowlist.

The model cannot argue with any of these, because none of them reads model text as an instruction.
They read ids and compare them to session state. A perfectly convincing injected instruction produces
a proposed action that fails check 1.

### 6.3 External lookup

**VERIFIED:** Tavily may reuse query data and forwards it to third-party search index providers.
**DECISION: treat everything sent to Tavily as permanently public.**

The controls follow from that single premise:

- The outbound query string is constructed **server side** from a whitelist of public entity fields.
  There is no code path in which model-generated text becomes an outbound query string.
- The model can only nominate an `entity_id` that already exists with `visibility = 'public'`, set by
  an explicit human classification step.
- Responses are T2. They land in a separate `external_lookup` store with **no foreign key into the
  memory graph**, render in a visually distinct panel, and expire in 24 hours.
- **External content cannot be cited as evidence for any historical claim**, enforced by the evidence
  resolver accepting only capture pointers. This is a structural bar, not a policy.
- An append-only log records the **verbatim** outbound string, including denials, surfaced to the user
  in a "What left Exulanica" panel.

**ASSUMPTION:** that the minimizer holds under attack. Settled by experiment X-13: attempt to get a
private detail into an outbound query via an injected instruction, a crafted entity label, and a
manually edited entity record, and verify all three are blocked and every denial is logged verbatim.
**DECISION: if X-13 does not pass cleanly, cut the feature entirely.** A leaky gate is worse than no
feature, and worse than anything the feature is worth.

---

## 7. The uptime obligation

### 7.1 The obligation

**DECISION: the deployment is designed to run unattended for roughly 46 days**, from the last commit
before a release to the next point at which an operator is scheduled to touch it. That horizon is a
planning choice rather than an observed fact, and it is stated as one: this is a single-operator
project, and 46 days is the longest gap between hands-on attention the schedule realistically
produces. Rejected alternative: designing for steady-state operations with somebody on call, which
would justify a much cheaper recovery story and is not the situation this deployment is in.

The consequence is that the person clicking the URL is a user who will leave rather than an operator
who will file a bug, and a dead URL is not a degraded experience. It is the whole product, because
everything the application does sits behind it.

**VERIFIED:** the services this runs on are Preview-grade with no SLA and no automatic recovery. See
section 2.1.

### 7.2 Resilience design

**DECISION.** Against an unattended window on a no-SLA platform, every item here exists to convert a
class of silent failure into either automatic recovery or a phone alert.

| Control | Failure it addresses |
| --- | --- |
| API and database on a Compute VM with a restart policy, not a Preview endpoint | Host or process death with no automatic recovery (section 2.1) |
| External check hitting `/healthz` every 5 minutes, alerting a real phone | Anything that dies without a human present, which is the default state for 46 days |
| One-command redeploy in the Makefile, tested from a clean shell | A redeploy that has never been run from scratch is not a recovery path |
| Nightly `pg_dump` to Object Storage | A lost host costs minutes rather than the corpus |
| A static SPA build on Vercel that works with zero backend, serving a **clearly labelled recorded tour** | Total backend loss. Labelling it as recorded keeps it honest; presenting it as the live app would not |
| A named person doing a weekly check through the unattended window | Seven weekends of drift. **OPEN:** the person is not yet named |

Model deprecation is the failure mode specific to this platform and this window:

| Control | Detail |
| --- | --- |
| Every model id in one manifest file | Never inlined at call sites, so a single edit changes every reference |
| Build-time preflight | Fetch `https://tokenfactory.nebius.com/api/public/models_info` and fail the build if any referenced id is absent |
| A declared fallback id per role, in the same region tier | Selected at runtime on a 404-class error, and exercised in CI so the fallback path is not first executed during the unattended window |
| The weekly check includes a catalog diff, not only a `/healthz` ping | A ping succeeds right up until the first query hits a removed model |

**VERIFIED, and the reason the above is not paranoia:** code must read the catalog's `model_id` field
and never the human-readable `name`, because they differ. The name "Nemotron-3.5-Lightning" uses a dot
where the id uses `3_5`, and the name "Nemotron-3-Nano-30B-A3B" lacks the doubled `NVIDIA-` prefix
present in the id. Source: https://tokenfactory.nebius.com/api/public/models_info

**VERIFIED:** Nebius documentation is materially stale in several places. The inference overview page
still documents a `-fast` flavor whose ids were all deleted on 2026-06-22, and the vision-capabilities
page cites model ids that do not exist in the catalog. **DECISION: treat only `models_info` and
`openapi.json` as authoritative.** Sources: https://docs.tokenfactory.nebius.com/august-2026-deprecation-notice ,
https://api.tokenfactory.nebius.com/openapi.json

**ASSUMPTION:** that another deprecation round lands between feature freeze and the end of the
unattended window. Two rounds in ten weeks is the observed cadence. This assumption cannot be
validated in advance, which is precisely why it is mitigated structurally rather than monitored.

**ASSUMPTION:** that a Preview endpoint can survive the window at all. Settled by experiment X-0b, the
canary endpoint, running from now to the end of the window.

### 7.3 Two cost traps

Named because they are the two realistic ways this project's spend goes from small to embarrassing.
Expected total infrastructure cost is roughly **$275 to $600 across 3.7 months**, dominated by hosting
uptime rather than by AI inference.

**Trap 1: a forgotten GPU VM.** $32 to $37 per day on an on-demand L40S, $92 per day on an H100. Two
forgotten weeks is more than the entire expected project budget.

**VERIFIED:** GPU quotas count a VM from creation to deletion, running **or stopped**, so a stopped VM
also blocks the next job from starting. Source:
https://docs.nebius.com/compute/resources/quotas-limits

**DECISION.** Auto-stop script on every GPU VM. Checkpoint reconstruction every 5,000 iterations so
`--preemptible` is actually usable. Prefer Serverless **Jobs**, which self-terminate, over endpoints,
with a conservative `--timeout`. Lifecycle rules deleting reconstruction intermediates after 7 days.
A billing alert at $300.

**Trap 2: Nebius Managed PostgreSQL.** Roughly **+$755 over the project period** for a sub-1-GB
database, against $0 marginal cost for a container on the Compute VM that already has to exist. This
is the on-brand, obvious, wrong choice, and it is wrong by more than the entire expected AI spend. See
section 2.1.

---

## 8. What this document deliberately does not decide

| Question | Where it lives |
| --- | --- |
| Which browser renderer | [adr/0003-renderer-selection.md](adr/0003-renderer-selection.md). **OPEN**, settles at end of week 3 |
| The evidence address, the epistemic model and the assertion log | Domain and evidence model document, not yet written |
| Consent scopes, deletion cascade and the misuse guards | Privacy, consent and threat model document, not yet written |
| Model selection and routing | Validated technology and model selection document, not yet written |
| Reconstruction rungs and their quality bar | [reconstruction-findings.md](reconstruction-findings.md) for the measurements, [adr/0009-the-ladder-above-rung-3.md](adr/0009-the-ladder-above-rung-3.md) for how the rungs above 3 are earned |
| The domain and deployment account | **OPEN** |
| Who owns the weekly uptime check | **OPEN** |

---

## 9. What has been executed, and what has not

This section previously recorded, as a verified absence, that not one model id in this architecture
had ever been invoked, and said that the sentence would stand until it was false. It is now false.

**VERIFIED by execution on 2026-08-27.** A real request against `nvidia/Nemotron-3_5-Lightning`
returned HTTP 200 with the model identifier echoed in the response body, and a real Tavily search
returned HTTP 200 with its request payload retained. Both are recorded in
[runtime-verification.md](runtime-verification.md), which overrides this document on conflict.

The rest of this document remains a design. Every platform fact above is verified against primary
documentation, catalogs and specifications retrieved 2026-08-27, and the infrastructure it describes
has not been stood up.
