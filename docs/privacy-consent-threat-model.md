# Privacy, consent, deletion, and threat model

This contract owns the privacy boundaries the code enforces: what the product processes, the guards
that bind, the consent and rights records a person keeps, what leaves for a hosted model, deletion
and restore, honest disclosure, the prompt-injection posture, misuse boundaries, and the one open
decision about biometric data. Photographs, the Companion and reconstruction are features and ways
to build a world; most of what follows governs them. Route permissions, quotas, egress and model
spend are the [security floor](security-floor.md)'s.

Every claim below carries one label where the distinction matters: **VERIFIED** (a primary source or
the code), **DECISION** (with the rejected alternative), **ASSUMPTION** (with what settles it) or
**OPEN**. **This is not legal advice.** No one on this project is a lawyer, nothing here establishes
compliance with anything, and the project makes no compliance claim (section 6). The legal research
this contract rests on, and the designs that were proposed and never built, are summarised in
sections 2 and 12 and kept in full at revision 47f9f7d3.

<details>
<summary>Sections</summary>

- [1. What is processed](#1-what-is-processed)
- [2. The legal landscape](#2-the-legal-landscape)
- [3. Architectural guards versus policy promises](#3-architectural-guards-versus-policy-promises)
  - [3.1 The guards that bind](#31-the-guards-that-bind)
  - [3.2 Isolation between workspaces](#32-isolation-between-workspaces)
- [4. Consent](#4-consent)
  - [4.1 Principles](#41-principles)
  - [4.2 The consent and rights records the product keeps](#42-the-consent-and-rights-records-the-product-keeps)
  - [4.3 What each record permits](#43-what-each-record-permits)
  - [4.4 Revocation cascade](#44-revocation-cascade)
  - [4.5 Where a place's name may go](#45-where-a-places-name-may-go)
- [5. Deletion](#5-deletion)
  - [5.1 What a deletion reaches](#51-what-a-deletion-reaches)
  - [5.2 Who may delete](#52-who-may-delete)
  - [5.3 Vector search and deletion](#53-vector-search-and-deletion)
  - [5.4 Tombstones that survive retries and restores](#54-tombstones-that-survive-retries-and-restores)
  - [5.5 The honest limits](#55-the-honest-limits)
- [6. Honest disclosure](#6-honest-disclosure)
  - [6.1 Claims that must never be made without implementing them first](#61-claims-that-must-never-be-made-without-implementing-them-first)
  - [6.2 The notices the product shows](#62-the-notices-the-product-shows)
  - [6.3 Append-only, not immutable](#63-append-only-not-immutable)
- [7. Prompt injection](#7-prompt-injection)
  - [7.1 Why Exulanica is exposed](#71-why-exulanica-is-exposed)
  - [7.2 Untrusted-input inventory](#72-untrusted-input-inventory)
  - [7.3 Defences](#73-defences)
  - [7.4 Adversarial tests](#74-adversarial-tests)
- [8. Misuse boundaries](#8-misuse-boundaries)
- [9. Demonstration material and reconstruction admission](#9-demonstration-material-and-reconstruction-admission)
  - [9.1 Published demonstration material](#91-published-demonstration-material)
  - [9.2 Repository hygiene](#92-repository-hygiene)
  - [9.3 Reconstruction privacy admission](#93-reconstruction-privacy-admission)
  - [9.4 Person-scoped reconstruction withdrawal](#94-person-scoped-reconstruction-withdrawal)
- [10. OPEN: when may a biometric embedding exist at all](#10-open-when-may-a-biometric-embedding-exist-at-all)
- [11. What this document does not settle](#11-what-this-document-does-not-settle)
- [12. Designs not built](#12-designs-not-built)

</details>

## 1. What is processed

This section exists because the analysis below is worthless if it is applied to the wrong system.

| What | Where it comes from | Notes |
| --- | --- | --- |
| Photographs | A person's upload (`POST /intake`), an import, or `exulanica-ingest` | Kept in the content-addressed store; still photographs only, no video and no audio |
| Photograph derivatives | The [derivative worker](derivative-worker-operations.md): renditions, vision observations, caption vectors, person regions and masked derivatives, point maps, object masks | Each is keyed to its source and removed with it (section 5) |
| Scene reconstructions | The scene worker and scene training | Admitted per exact capture set (section 9.3) |
| Names a person types | People, places, objects, events and conversations the account holder names | A name exists only because the account holder typed it; no model writes one |
| Companion conversations and memory | The Companion | Deletable by the account holder |
| Worlds, their objects and their simulated people | The person building the world | A world's people are simulated; they are no real person |
| Account records | Google sign-in, when configured | Outside workspace scope ([deployment](deployment.md#514-browser-accounts)) |

What leaves the process is decided at one boundary (section 4.4): hosted models receive text and,
for the vision role, a reduced rendition with no EXIF, only under the rights section 4 describes.

**VERIFIED.** No face template, voice template or other biometric identifier is produced. Identity
proposals are built from context (where, alongside what, and what a person wrote) and never from
biometrics: face, voice and gait have no producer (`exulanica/identity/proposer.py`), and whether a
biometric embedding may ever exist is the open decision in section 10.

## 2. The legal landscape

Research read on 2026-08-27 covered Illinois BIPA, Texas CUBI, the GDPR, the EU AI Act (including
Regulation (EU) 2026/1744), the CCPA as amended by the CPRA, Colorado HB24-1130 and the
all-party-consent wiretapping statutes. Its analysis, quotations, sources and open readings are
kept at revision 47f9f7d3
([privacy-consent-threat-model.md at 47f9f7d3](https://github.com/twinkling-reality/exulanica/blob/47f9f7d3/docs/privacy-consent-threat-model.md));
nothing here re-verifies them. The conclusions that shape this contract:

- A photograph is excluded from BIPA's "biometric identifier", but a template derived from a face is
  not, and under the GDPR and the AI Act comparing such templates to recognise a person is
  biometric identification. That is why no template is produced (section 10).
- Consent to biometric processing must come from the person in the photograph, not from the account
  holder who took it (principle P4).
- No demographic or affect inference on faces: no age, gender, ethnicity or emotion field exists,
  not even as an internal value (guard G7).
- A person must be able to tell when they are dealing with a model and which content a model
  generated.

## 3. Architectural guards versus policy promises

A **policy guard** is a sentence in a document. An **architectural guard** cannot be evaded without
shipping new code. Only the second kind is a control.

### 3.1 The guards that bind

| # | Guard | Blocks | Status |
| --- | --- | --- | --- |
| G1 | **No probe-image search.** No route, no UI and no internal function accepts an arbitrary image and returns who it shows | "Upload a stranger's photo, find them" | Holds by absence: there is nothing to call |
| G2 | **Nothing is compared across workspaces.** There is no face index at all, and caption vectors live in a table partitioned by workspace | A cross-account database of people | Holds: partitioning, not a metadata filter |
| G3 | **Vectors never leave.** No API schema carries an embedding or vector field, and a World Memory Package refuses one | Extracting representations for reuse elsewhere | Holds: `tests/snapshots/api-openapi.json` and the package profile's forbidden keys |
| G4 | **The system never proposes a real-world identity.** Names come solely from what the account holder saved; a model never writes one | Turning the product into an identification service | Holds: the vocabulary refuses any name from a model |
| G5 | **A person is hidden until they consent.** A detected person's region is filled before depth and segmentation read the photograph, and absence of a record is never read as permission | Processing and showing a person who never agreed | Holds for detected regions ([person presentation consent](person-presentation-consent.md)) |
| G6 | **A model has no authority.** Every model output is a validated choice among offered options or a proposal the owner accepts; nothing a model writes changes a world, a right or a deletion by itself | Every prompt-injection path that ends in an action | Holds: see section 7.3 |
| G7 | **No demographic or affect inference on faces** | AI Act Art. 5(1)(f) and (g) exposure | Holds, by not building the field |
| G8 | **A photograph's location stays in its workspace.** A GPS fix from EXIF is a capture-supported claim served only within its own workspace, where a place's position is the median of its photographers' fixes and never a georeference | Locating people from outside the workspace | Holds for reads; nothing publishes a coordinate |
| G9 | **No unattended ingestion integration.** There are no webhooks and no third-party ingestion API; automated clients hold bearer-token grants an operator configures, each with named permissions ([security floor](security-floor.md#1-route-permissions)) | Wiring the product into a surveillance pipeline | Weak: a grant holder can script uploads |

**DECISION.** G1 through G4 plus G6 are the load-bearing controls, and the honest external framing
is: "Exulanica is architecturally incapable of identifying a person you have not captured yourself,
and it cannot compare people across accounts. It cannot prevent a determined user from misusing
their own photographs, and it does not claim to." Rejected alternative: presenting heuristic speed
bumps as protections, rejected because they are evadable and describing them as protections would be
an overclaim of exactly the kind section 6 forbids. The speed bumps once proposed are listed in
section 12.

### 3.2 Isolation between workspaces

**Isolation is a claim that must be earned.** Every workspace table is under `FORCE ROW LEVEL
SECURITY` keyed on `current_workspace()`, and the runtime connects as a role that owns nothing and
lacks `BYPASSRLS` ([deployment](deployment.md#513-runtime-row-level-security-is-checked-at-startup)).
The workspace a connection reads is set by the server from the authenticated session, a bearer
grant or a browser account's membership, never from a header or a body. Caption vectors are
partitioned by workspace. A foreign id answers **404, never 403**, because a 403 confirms existence
([security floor](security-floor.md#1-route-permissions)).

**ASSUMPTION.** These controls produce zero cross-workspace retrieval. Authorisation fuzzing exists:
`tests/test_existence_oracle.py` replays every id-bearing route with another workspace's ids, as a
non-superuser runtime role, and requires the not-found answer. The other two proofs, a nonce canary
over every answer and log line and an index-level proof, are not built (section 12). Until they are,
"only you can see your memories" is not claimed (section 6.1).

## 4. Consent

### 4.1 Principles

**DECISION.** Six rules, each with the alternative it rejects.

| # | Rule | Rejected alternative |
| --- | --- | --- |
| P1 | **Deny by default.** A person with no consent is hidden in every derived representation and never linked, and absence of a record means no. | Treating absence of a record as "undecided" and processing pending review. |
| P2 | **Per-person, per-scope, independently revocable.** One decision per person, right, role or place. | A single "I consent" checkbox. Rejected as non-specific under GDPR Art. 4(11), and because it gives the subject no meaningful partial control. |
| P3 | **Consent expires.** `expires_at` is mandatory, default 90 days, renewable. | Perpetual consent. |
| P4 | **The account holder cannot consent for anyone else.** They may *attest* they obtained consent, which is a weaker record type carrying strictly fewer downstream permissions. | Letting the account holder tick boxes on a subject's behalf. |
| P5 | **Records are append-only.** Revocation is a new superseding record, never an update; a chain of decisions carries the digest of the one before. | Mutable consent rows, which cannot answer "what were we permitted to do on date X". |
| P6 | **The exact notice text is kept with the record.** | Storing a notice version string only. If the exact wording shown cannot be reproduced, there is no consent. |

### 4.2 The consent and rights records the product keeps

| Record | Migration | What it is |
| --- | --- | --- |
| Person presentation consent | 0037 | Whether a person in a photograph may be shown; a person is hidden until they consent ([person presentation consent](person-presentation-consent.md)) |
| Training-use consent | 0039 | A person's permission for their material in one exported dataset package, for one licensee and term; not the scene training right ([person presentation consent](person-presentation-consent.md#training-use-is-a-separate-consent-plane)) |
| Personal model right | 0073 | Which model may receive a photograph, or text derived from it, and where the bytes go ([personal admission](personal-admission.md)) |
| Point-map right binding | 0092 | Binds each point map to the right that permitted it (section 4.4) |
| Place-name right | 0097 | Whether a confirmed place's name may go to the models of one hosted role (section 4.5) |

Migration 0001 also defines a `consent_record` table with per-person biometric scopes. No code
reads or writes it; it belongs to the design section 12 lists.

### 4.3 What each record permits

| Record | Grants | Withdrawn by | Effect of withdrawal |
| --- | --- | --- | --- |
| Person presentation consent | Showing a person, their name beside their outline, or their likeness | The person's revocation or withdrawal | The person is masked again; on withdrawal their derived artifacts are purged and rebuilt |
| Personal model right | Sending a photograph, or text derived from it, to one hosted role's models, or running the depth model over it | One stop per role per photograph | Every later read and request refuses; point maps it permitted stop being served; the search entries a stopped search right made are deleted |
| Place-name right | A confirmed place's name leaving in one role's requests | A stop, a rename, a deletion or a merge | The next request carries a placeholder |
| Training-use consent | A person's material in one exported dataset package | A revocation or a withdrawal; a withdrawal cannot be undone by a later grant | Export excludes the person's material unless masking is proven for every exported representation |

### 4.4 Revocation cascade

Revocation is a write to a record plus, where bytes or derivatives must go, a tombstone and an
asynchronous purge. **The write is synchronous and authoritative.** The system behaves as revoked the
instant the row lands, before any cleanup has run: every read path resolves the current decision, so
a withdrawn person, photograph or name disappears from results immediately even while a derived row
still physically exists. Four rules make revocation work rather than appear to:

1. **A derived aggregate is recomputed, not row-deleted.** An aggregate computed over a withdrawn
   member still encodes it; deleting the member row while keeping the aggregate is silent retention.
2. **Generated text is a derivative.** Text generated from a withdrawn source restates it in new
   words, so generated text must record the sources it was conditioned on.
3. **Revocation is idempotent and replayable.** Deletion runs from the tombstone table, not from a
   queue message that can be lost.
4. **Revocation survives a restore** (section 5.4).

The account holder's own decisions about their own photographs follow the same rule. A **personal
model right** (migration 0073) says which model may receive a photograph and where the bytes go;
withdrawing it is synchronous and final, and every model read resolves it again at the instant of
the read. A **depth estimate** made under such a right is stored, so a right that governed only the
inference would have let a withdrawal stop the next one and leave a three-dimensional reading of the
room servable. Migration 0092 binds each point map to the right that permitted it, inside the
publication transaction, and `asset_point_allows` refuses a bound artifact whose right has ended: the
geometry route, the graph, scene selection and world composition all ask that one predicate, so the
estimate stops being readable everywhere at once. A map published before the binding existed is
unaffected, because nothing here invents a right for a photograph processed before rights did.

**Where a person gives a model right.** In the photo drawer, each right is its own tick, unticked,
beside the notice the server states for it. Authorizing processing offers the three rights a
grounded Companion answer needs: the vision model, which is sent a copy of each photograph, reduced
if it is large, with the people in it visible, because it is the model that finds them; the
embedding model, which is sent the descriptions made from it; and the composer, which is sent the
descriptions and dates of the photographs a question finds. Recording the human review offers the
depth estimate. `GET /personal-admission` states every offered right in `model_right_offers`: its
notice, filled from [`model-right-uses.v1.json`](../exulanica/ingest/model-right-uses.v1.json) with
the host and every model of the role's chain, and the words that stop it. The browser keeps no copy
of any of them, sends the notice back unchanged, and the server refuses any other text (rule P6). A
role the app does not offer, such as a local segmentation role, is granted through the route only
with no notice. Each saved photograph lists every role given over it with the end of its recorded
term, and one stop per role, which withdraws every current right of that role over that photograph,
because a request to the role can reach every model of its chain. Stopping the search right also
deletes the search entries already made from that photograph through the purge a deletion uses
(migration 0104), and the photograph can still be found by the words of its own description. A right
granted through the API before its role had stated words keeps its own terms until its term or
authority ends or the person stops it, and the drawer says it was allowed without the wording shown.

**Every hosted request passes one boundary.** `ModelClient` in `exulanica/models/client.py` hands
every request it sends, from `chat`, `structured`, `vision` and `embed` alike, to the policies
attached to it before the response cache key is computed, and sends exactly the text they return.
A client with no policy refuses to send, by name, with `NoHostedRequestPolicy`
(`exulanica/models/policy.py`), and the one client an instance builds carries none. The policy
that applies the account holder's rules is `WorkspaceRequestPolicy` in
`exulanica/epistemics/hosted_requests.py`, attached where the workspace is known: a route sends
through `Services.hosted_model`, the caption-vector pass and the vision stage attach it for the
photograph whose text or bytes they send, and the decision host and a comparison for each decision
they ask for. As each request leaves it:

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
transport recorded was admitted by the policy, text for text; and the paths whose call site
prepares names itself (the planner, the composer, the request classifier and the appearance,
environment and specification drafters) hold with that preparation disabled.

**Which requests honour a place right.** Every request of a role the uses file offers
(`exulanica/consent/place-name-uses.v1.json`) leaves a place's name to the boundary, and the file
names each such request path by module and function: the caption-vector pass and the embedding of a
question's query for the embedding role, the composer for `reasoning_cheap`, and the planner, the
request classifier, the appearance drafter and the environment drafter for `structured_extraction`.
The specification drafter, which drafts a world's specification from a person's description
([`exulanica/selection/world_drafting.py`](../exulanica/selection/world_drafting.py)), is no use:
it replaces every saved name, a place's included, before the description is sent.
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
runs: `Services.request_policy` requires the release to be named, and the rules the decision host
and a comparison attach to every ask (`Services.person_decision_policy`) name
`no_place_released`, because a grant for the Companion's roles describes the Companion's requests.
The vision stage sends the product's own instruction and the photograph, and its policy releases no
place's name. `tests/test_place_name_release_paths.py` runs each path the uses file names and
requires it to carry an allowed name, so a use cannot be offered while inert, and holds that a
request to another destination, or one that can reach a model the grant does not name, carries the
placeholder. `tests/test_companion_place_release.py` holds that a place allowed for the composer
reaches the composer's request and no other, that a stop holds the composer's next request back, and
that no person's name leaves on any registered path with every place use allowed, whether the
boundary, the call sites or both prepare the names.

**What the boundary does not do.** It never rewrites a system message: a system message is product
instruction, and rewriting one would put `[person A]` for every "may" in every prompt of somebody
saved as May. The byte test holds that no system message on any path carries a saved name
instead. It cannot recognise a name the account holder has not saved. And an embedding request
carries no record, so the boundary assigns its placeholders per request, in the order it recognises
names: in embedding text `[place A]` is a different place in each caption and in each query, and a
query about one withheld place shares that token with every caption that holds any saved place.
That leaks nothing, and what it costs vector retrieval is measured in
[Companion questions](companion-question.md#evidence-and-limits).

The World Memory Package applies the read path's withdrawal rule to the names it exports: a
withdrawn person's entity and naming assertions keep their rows, lose their values and say why,
and the projector refuses to sign a package in which any value is a name that person was ever
saved under, unless somebody who did not withdraw is saved under the same name
(`exulanica/world_package/projector.py`, [world memory package](world-memory-package.md)).

### 4.5 Where a place's name may go

**DECISION.** A name exists in this product only because the account holder typed it, and the
account holder decides where it may go. A person's name never goes to a hosted model, with or
without any right, and nothing in this section can release one. A place's confirmed name goes to a
hosted model only while the account holder who named that place allows that use, asked for each
place. Rejected alternatives: one switch covering every place, rejected because a home or a clinic
is a place somebody may never want named outside the product; and borrowing a photograph's personal
model right (migration 0073), rejected because a place name is an annotation on an entity many
photographs link to, so one photograph's permission would release a name the account holder never
allowed on its own, and withdrawing it would not stop the name leaving through another.

The right is stored by migration 0097 and read by
[`exulanica/consent/place_name_rights.py`](../exulanica/consent/place_name_rights.py); what a
decision means is stated once, in [`exulanica/consent/place_names.py`](../exulanica/consent/place_names.py).

| Term | Rule |
| --- | --- |
| What is offered | One use per hosted model role whose requests can honour a release, declared in [`place-name-uses.v1.json`](../exulanica/consent/place-name-uses.v1.json) with its purpose and the request paths that honour it; an offered use names at least one. It offers three: the embedding role, which indexes the descriptions of photographs and searches them; `reasoning_cheap`, which writes the Companion's answer; and `structured_extraction`, which reads what the account holder types to the Companion to plan a search, tell a question from a request to change the world, and draft the change. A society decision and the vision stage release no place's name, so neither is a use. A role absent from that file never receives a place name |
| What is decided | One use at a time, meaning every model of that role's chain at the manifest's endpoint, because a request to the role can reach the fallback as well as the primary. It is stored per place, model identity and destination |
| Default | Not allowed. A place with no decision releases nothing, and so does a request that names a model outside the chain it allowed, another destination, or the models of two roles |
| Record | Append-only events in `place_name_right_event`, forced row-level security. Each allow and each stop is a new row after the last one for its place, model and destination, carrying the digest of the one before it (rule P5). The database refuses an update, a deletion, a row out of sequence and a stop with no grant before it |
| Notice | The exact words the account holder read, naming every model, the host the name travels to, the purpose and the term, are kept with the grant (rule P6). A grant counts only while the product states the same words for that use: a changed model chain, host, purpose or term needs a new yes |
| Term | A grant ends after the default term rule P3 states; `tests/test_place_names.py` fails if the uses file and P3 disagree |
| Who | Only the account holder who stated the place's name may allow it; anyone the workspace session belongs to may stop it, because stopping only ever sends less |
| Naming | A grant rests on the active naming assertion the place's current name is the cache of. A rename, including one back to the same words, a deletion or the place being merged into another entity stops it. Undoing a merge restores a grant that was never stopped; a stop recorded in between holds |
| Stop | Takes effect from the next read. The grant it ends stays readable, so what was allowed at any instant has an answer |

**The resolver.** `place_name_released(connection, workspace_id, entity_id, handoff)` answers
whether one place's name may go to every model a
[`ModelHandoff`](../exulanica/models/handoff.py) can reach, and `released_place_names(connection,
workspace_id, handoff)` answers for every place at once. Both default to no and read under the
same final read check as a photograph's model right, stated once in
[`final_read_check`](../exulanica/db/read_check.py): an idle connection, a read-only transaction,
the global asset read lock and one evaluation instant, released before anything is sent. A grant,
stop, rename, merge or deletion therefore cannot commit while a name is being checked; it is either
seen or refused with `busy` until the check has finished. A caller holding an open transaction
resolves the released names before entering it, or on a fresh connection.

**Where it is decided.** `GET /place-name-rights` and `GET /place-name-rights/{entity_id}` read each
use's notice and state under `consent.read`; `POST /place-name-rights/{entity_id}/grants` and
`/withdrawals` record a decision under `consent.write`. A grant sends back the notice it was shown
and is refused as `notice_changed` if a single character differs. The Library's detail for a named
place, and the places a Companion answer is about, show each use with its notice, its state in a
sentence and one button, "Allow" or "Stop sending".

**What it does not do.** A grant sends nothing by itself: it lets a place's name stay in a request
the product sends anyway, and only in a request that honours a release. Which requests those are,
and how every other saved name is kept out, is section 4.4's.

## 5. Deletion

### 5.1 What a deletion reaches

Anything a deletion does not reach is silent retention. The implemented reach, by mechanism:

| Mechanism | What it covers |
| --- | --- |
| Tombstone guards | `BEFORE INSERT` triggers on `evidence_span`, `occurrence`, `assertion`, `embedding` and `entity_link` refuse a derivative of a tombstoned subject inside the writing transaction (migration 0001); "tombstoned" is terminal and never retried |
| The purge worker | `exulanica-purge` destroys stored bytes once no live holder in any workspace remains ([deployment](deployment.md#524-the-purge-worker)) |
| A photograph's rights | A stopped model right stops every later read and request, point maps it permitted stop being served, and a stopped search right deletes its search entries (section 4.4) |
| Person-scoped withdrawal | Geometry, scenes, jobs, artifacts, vectors and assertions that depend on a confirmed person follow the person's tombstone (section 9.4) |
| Scene training | A withdrawn training right destroys what it produced (migration 0082) |
| Restore | A restored database replays every withdrawal before it serves (section 5.4) |

### 5.2 Who may delete

**DECISION.** Two roles: a runtime role that **cannot** delete, and a separate purge role used only
by the tombstone-driven purge ([security floor](security-floor.md#5-database-roles)). Rejected
alternative: giving the runtime delete permission, rejected because an injected or mistaken request
could then destroy what nobody asked to delete, while a deletion a person asks for still happens
through the purge path.

### 5.3 Vector search and deletion

Caption vectors are searched exactly. A 4096-dimension `halfvec` column cannot carry an HNSW or
IVFFlat index at all (migration 0001), so there is no approximate index whose on-disk structure could
keep a deleted vector after its row is gone: deleting the row removes it from search. An approximate
index would bring back the compaction problem section 12 records, and would need a check that a
deleted vector is absent from the index's own files before any deletion claim is made.

### 5.4 Tombstones that survive retries and restores

The `tombstone` table (migration 0001) is workspace-scoped and holds no content, only identifiers:
its scope (`capture`, `interval`, `entity`, `assertion`, `workspace`, and the later
`scene_training` and `caption_search`), its subject, who asked, when it takes effect, and when the
purge completed. Migration 0074 makes a tombstone written once: every change but
`purge_completed_at` is refused.

Rules:

1. The tombstone is written **in the same transaction** as the user-visible state change, before any
   asynchronous work is enqueued. If the purge worker dies, the tombstone is the durable record.
2. **Every writer checks the tombstone before persisting a derivative**, enforced by the
   `BEFORE INSERT` triggers of section 5.1 inside the writing transaction. "Tombstoned" is a
   terminal, non-retryable error class. This is the retry race that silently resurrects data: a
   slow model call plus a retry policy opens a window of minutes.
3. **Tombstones are never deleted.** They are the compliance evidence and they contain no content.
4. **Capture tombstones are keyed by the capture, never by the blob hash.** A hash-keyed tombstone
   would permanently blocklist those exact bytes and silently break a deliberate re-import; blocking
   the bytes is an explicit opt-in (`blocklist_hash`).
5. **Restore**: any restore from a backup must, before the system accepts traffic, replay every
   withdrawal made after the backup. The offline replay of
   [ADR-0019](adr/0019-offline-restore-tombstone-replay.md) (`exulanica/deletion/restore.py`) does
   this from a sealed checkpoint. A search entry is a row of the restored database, so each replayed
   tombstone's own cascade erases the entries it reaches there, and the replay refuses to complete
   while an entry the checkpoint records as erased is present and was made before its deletion took
   effect; one made again later, under a search right granted after a stop, is kept
   (`tests/test_restore_replay_search_entries.py`). A backup that holds a model right restores: every
   function a restore runs while loading rows resolves its own names (migration 0106), and
   `exulanica-local-db` loads a dump taken before 0106 by giving those functions a path between its
   schema and its rows (`tests/test_local_database_restores_older_dumps.py`). Every withdrawal that
   is not a tombstone, a stopped model right or a withdrawn consent among them, is in the checkpoint
   too and is written again before any tombstone, and a checkpoint older than its backup is refused
   ([ADR-0026](adr/0026-a-restore-carries-every-withdrawal.md)). A person's retraction of a claim
   they made is written again by the product's retract, so a name they retracted stays off its place
   and a place-name right resting on it stays ended (`tests/test_restore_replay_retractions.py`); a
   place-name withdrawal whose chain gained a grant after the backup withdraws the chain the backup
   holds as its next decision.

### 5.5 The honest limits

These belong in the product copy, not only in this document.

| Limit | Why it exists | What is promised |
| --- | --- | --- |
| Backups predate the deletion | A restore from a backup taken before a deletion reintroduces the deleted rows, and the backup file itself is not rewritten | A declared offline restore replays a sealed checkpoint of every tombstone and withdrawal before it serves ([ADR-0019](adr/0019-offline-restore-tombstone-replay.md), [ADR-0026](adr/0026-a-restore-carries-every-withdrawal.md), section 5.4). A personal install keeps its backups on the same disk until they are copied elsewhere; no hosted backup policy exists, and a production restore rehearsal is OPEN |
| Object versions persist | Object storage without WORM, Object Lock or Legal Hold makes append-only a policy enforced by access rights, and the versioning that protects originals also preserves them against erasure | **Requirement, not implemented:** crypto-shredding as the primary erasure mechanism (a per-capture key wrapped by a per-person key wrapped by a per-workspace KMS key), so destroying the key makes retained versions unreadable ciphertext. Say exactly that, never "the bytes are gone". The implemented store is local (`exulanica/store/local.py`) and holds no keys |
| Vector index residency | A row deleted from a table may persist inside an approximate index until compaction | Caption vectors carry no approximate index (exact search over `halfvec(4096)`, section 5.3). If one is added, the vector-residency experiment (X-11 in the [domain and evidence model](domain-and-evidence-model.md)) must show a deleted vector is physically absent before any residency number is published |
| Inference provider | Nebius Token Factory receives what the boundary of section 4.4 lets through | Whether the provider retains it depends on the account's zero-data-retention setting, which **Exulanica relies on and cannot verify** (OPEN below) |
| Outbound lookup | A search provider may reuse the queries it receives | No outbound lookup is built, and no product code calls a web-lookup provider. A lookup, if one is built, treats anything sent as permanently public and constructs its query server-side from public entity fields, never from model output |
| Already exported | Downloaded files, screen recordings, share links and exported packages leave the system | Beyond reach. A World Memory Package is a projection at a named version that a later deletion cannot recall, and that must be said at export time |
| Logs | A stack trace can carry a fragment of content | No host with a log retention policy exists |
| Human memory | A person may have read something before it was withdrawn | The product deletes it; the account holder is not un-told |

**OPEN.** Whether Nebius zero-data-retention, once enabled on the account profile, covers **every**
endpoint and model identifier used, including the vision model. **Settled by**: written confirmation
from Nebius naming the specific model identifiers.

## 6. Honest disclosure

### 6.1 Claims that must never be made without implementing them first

Several of these are FTC Section 5 deception exposure, not merely bad manners. Each is forbidden
**unless and until** the implementation exists and its test is green.

| Forbidden claim | Why it would be false |
| --- | --- |
| "Private" or "privacy-first", unqualified | Photographs and text derived from them are sent to a third-party cloud for inference. |
| "On-device", "runs locally", "your data never leaves your device" | Hosted inference runs on Nebius. |
| "End-to-end encrypted" | Exulanica reads the content in order to process it. End-to-end encryption means the operator cannot read the content. |
| "Zero-knowledge" | Same reason. |
| "Anonymous", "de-identified" | A photograph of a person identifies them, and a saved name identifies whoever it names. |
| "GDPR compliant", "BIPA compliant", "CCPA compliant" | Compliance is a legal conclusion about an operating organisation, not a product feature. There is no DPIA, no DPO, no Art. 30 records, and no established lawful basis for non-user subjects. |
| "HIPAA compliant" | Not a covered entity or business associate; nothing here is designed for PHI. |
| "SOC 2", "ISO 27001" | **Nebius holds those certifications for its infrastructure. Exulanica does not inherit them.** |
| "Fully deleted", "permanently erased", "gone forever" | Provider logs, backups and already-exported artifacts survive for a period (section 5.5). |
| "Immutable", "WORM", "tamper-proof" | See 6.3. |
| "We never share your data" | Derived text and media go to Nebius under the rights a person grants. |
| "Secure", unqualified | Unfalsifiable. State what is actually done. |
| "Consent verified" | A record can be verified to exist. That the signer is the person in the frame cannot be. |
| "Only you can see your memories" | True only once all three isolation proofs of section 3.2 are green. Claim it after, not before. |
| "Accurate recall", "high accuracy", "reliable", "production ready", "state of the art" | Retrieval is probabilistic and a wrong person link is a defamation vector. |

### 6.2 The notices the product shows

A person grants a right against exact words the server states, and the grant keeps those words
(rule P6). The words are data: a personal model right's notice is filled from
[`model-right-uses.v1.json`](../exulanica/ingest/model-right-uses.v1.json) with the host and every
model of the role's chain, and a place-name right's from
[`place-name-uses.v1.json`](../exulanica/consent/place-name-uses.v1.json). A notice names what is
sent, to which models at which host, for what purpose and for how long, and how to stop it. A change
to any of those is a statement nobody has agreed to, so a grant made against older words stops
counting until the person allows the new ones.

### 6.3 Append-only, not immutable

**DECISION.** Product copy says **"append-only by policy"** and never "immutable", "WORM" or
"tamper-proof". The runtime cannot delete stored bytes and a separate purge role can
([deployment](deployment.md#4-the-content-store)), which is exactly as strong as that separation.
Rejected alternative: "original media preserved immutably", rejected because nothing the product
runs on can back it, and because immutability and the deletion requirement of section 5 are in
direct tension.

## 7. Prompt injection

### 7.1 Why Exulanica is exposed

**The untrusted content is the product.** A photograph can carry any text in front of the camera:
signs, menus, posters, whiteboards, screens, printed clothing. An attacker who wants to compromise a
specific person only has to be holding a piece of paper when that person takes a photograph. A
world's own descriptions reach the models that decide for its people, so a world can carry text
aimed at a model too.

**VERIFIED.** OWASP LLM01:2025 distinguishes direct injection from indirect injection, flags
**multimodal injection** (instructions hidden in images), and states that its mitigations are **not
a complete fix**, "because injection is inherent to how generative models process input".
Source: https://genai.owasp.org/llmrisk/llm01-prompt-injection/ (retrieved 2026-08-27)

**ANALYSIS.** There is no known complete defence. The posture is to make injection *harmless*
rather than *impossible*, by ensuring a model has no authority worth stealing (guard G6).

### 7.2 Untrusted-input inventory

Every item below is untrusted: it is evidence, never an instruction.

| Source | Enters via |
| --- | --- |
| Text transcribed from a photograph (signs, menus, posters, whiteboards, screens, packaging, clothing) | The vision observation, the primary vector. The vision stage records its observations with `trust_tier` T2 (`exulanica/ingest/stages/vision.py`) |
| Object and scene labels from the vision model | The vision observation |
| Filenames, EXIF and XMP fields | Upload |
| Names, notes and requests the account holder types | The Library and the Companion |
| A world's descriptions and its people's situations | The context a person's decision shows a model |
| Any model output derived from the above | Captions, answers, proposals |

**The transitivity rule is the one usually missed: a text generated from untrusted content is itself
untrusted.** If a model is compromised by an injected instruction, its output carries the payload
forward.

### 7.3 Defences

1. **A model has no authority to steal** (G6). A person's decision is one of the offered actions,
   checked again by the engine; an answer that is not one is refused and the routine decides. A
   Companion proposal to change a world applies only when the world's owner accepts it. Deletion,
   sharing, publishing and export are never initiated by a model.
2. **Untrusted text is fenced and labelled.** The Companion's composer receives the evidence packet
   with its model-written fields fenced as `untrusted_text`, and its prompt says those fields are
   untrusted (`exulanica/selection/question.py`, `exulanica/selection/prompts.py`); the instruction a
   model deciding for a person receives tells it not to follow instructions found in the description
   of the person or the world. Nothing depends on a model obeying either.
3. **Structured output checked by the server.** Every hosted structured reply is validated against
   the exact schema sent. A Companion answer may cite only the items of the packet the server
   assembled; an answer that fails validation is repaired once and then replaced by a deterministic
   answer.
4. **Egress control.** Network egress from the inference and answer path is allowlisted: the model
   transport, the catalog preflight and sign-in reach only declared origins
   ([security floor](security-floor.md#3-egress-allowlist)).

Rejected: **injection-classifier models** and **regex denylists** as gates. A gate that fails open is
worse than no gate, because it manufactures confidence.

### 7.4 Adversarial tests

The probe set and its metric are [evaluation methodology](evaluation-methodology.md) section 5 and
M11. `tests/test_selection_answer.py` runs the photographed-text injection cases against the answer
path.

## 8. Misuse boundaries

**DECISION.** The following are out of scope and are stated so in any terms of use:
law-enforcement identification, employee or student monitoring, covert surveillance, stalking or
locating individuals, public CCTV ingestion, dating or background-check screening, and any
consequential decision about a person (hiring, firing, housing, credit, insurance, immigration,
policing).

**Documentation prevents nothing.** The mapping from each boundary to the guard that actually
enforces it:

| Boundary | Enforcing guard | Honest strength |
| --- | --- | --- |
| **Law-enforcement identification** | G1 (no probe-image search), G2 (nothing compared across workspaces), G4 (no real-world identity ever proposed) | Architectural |
| **Employee or student monitoring** | G5 (a person is hidden until they consent) | Strong for showing a person; nothing stops an employer from photographing people, and G9 is weak |
| **Covert surveillance** | G5 | G5 is strong for what is shown. No capture manifest, volume limit or motion gate is built (section 12) |
| **Stalking and locating a person** | G8 (a location stays in its workspace), G4 | They bind for everyone outside the workspace; the account holder sees the fixes of their own photographs |
| **Public CCTV ingestion** | None | Nothing blocks it. Say so |
| **Consequential decisions about a person** | G4 (the system asserts only co-appearance, never identity or character), G7 (no demographic or affect inference exists to be misread as an assessment) | Architectural |

**The honest external framing**, which is the only framing permitted in any Exulanica material:

> Exulanica is architecturally incapable of identifying a person you have not captured yourself, and it
> cannot compare people across accounts. It cannot prevent a determined user from misusing their own
> photographs, and we do not claim that it can.

**DECISION.** The system **never proposes a real-world identity**. It says "the same person as in
these other captures", and names come solely from the account holder's own annotation. Rejected
alternative: surfacing a proposed name from a confidence-ranked match, rejected because cross-capture
identity is not reliable enough to assert, and a wrong person link in a product that promises every
claim resolves to evidence lends unearned authority to the mistake.

## 9. Demonstration material and reconstruction admission

### 9.1 Published demonstration material

**Published demonstration material is public.** A non-consenting person appearing in it is the
highest-probability real-world harm, and blurring afterwards does not cure it. The rehearsal and the
development corpus use synthetic drawings with no people in them. Material showing a real photograph
follows these rules, checked file by file by a named person before publication:

| # | Rule |
| --- | --- |
| 1 | **Every identifiable person is a consenting adult** whose consent covers public demonstration, before the file is ingested. |
| 2 | **No minors**, including in photographs on walls, in frames or on screens within the image. |
| 3 | **No bystanders.** A photograph containing an identifiable non-consenting person is excluded at selection, not blurred after ingest. |
| 4 | **No credentials or secrets:** no passwords, PINs, codes, keys, tokens, QR codes, badges or legible ID cards. |
| 5 | **No addresses, plates or documents:** nothing that pins a private address, no licence plates, mail, labels, prescriptions, bank cards or identity documents. |
| 6 | **No private screens:** no unlocked laptop or phone showing email, chat, calendars, boarding passes or a password manager. |
| 7 | **Rights-clear content:** no copyrighted work as the visual focus, and no brand presented as an endorsement. |
| 8 | **Metadata stripped:** EXIF, XMP, GPS and device serials removed, and no personal name, private location or identifying date in the filename. |

### 9.2 Repository hygiene

**Belongs in the public repository:** code and schemas, migrations, notice templates, the deletion
cascade and its tests, the adversarial test corpus, this document, licence notices, and a
`.env.example` with empty values.

**Never in the repository, an issue, a pull request, a screenshot or a CI log:** real photographs,
any vector file, real transcripts or annotations, signed consent documents or anything carrying a
real signature, email or phone number, database dumps containing real data, keys, tokens, `.env`,
workspace ids that map to real people, screenshots showing a real face or a private place name,
application logs, and provider account identifiers.

**DECISION.** Enforce mechanically rather than by policy wherever a check can: `.gitignore` covers
media, vector and database files, and the build context is an allowlist
([deployment](deployment.md#1-what-the-repository-holds-and-what-is-not-provisioned)). Rejected
alternative: a documented rule and reviewer diligence alone, because the realistic leak arrives
through an issue attachment or a CI log, not a deliberate commit.

### 9.3 Reconstruction privacy admission

Migration 0029 and `exulanica.ingest.privacy` add a fail-closed boundary before point-map inference
and scene queueing. The boundary has three immutable records:

1. A capture authorization binds the exact source digest, corpus class, purpose, actor,
   authorization scope, and evidence. Synthetic authorization also binds a canonical generator
   manifest. Benchmark authorization requires an official source URL, retrieval date, license
   document digest, and permitted use. Personal authorization records account authority only. It
   does not claim that the account holder consented for another person.
2. A per-capture screening receipt binds the authorization, source digest, method, reviewer,
   sensitive regions, policy version, policy parameter digest, validity time, eligibility, and
   blockers. Benchmark and personal media require a named human review of the exact bytes. A failed
   or expired review is not equivalent to no person.
3. A scene admission binds the exact ordered capture set, every source and screening receipt,
   one corpus class, one authorization scope, policy version, validity time, eligibility, and
   blockers. Every scene job stores that admission id and digest as immutable input.

Each record stores canonical UTF-8 JSON beside its SHA-256 digest. PostgreSQL verifies that the
bytes decode to the stored JSON and that their digest matches. The database also refuses a new
point map without an eligible receipt, refuses a scene job without an eligible exact-set
admission, checks every job member against the admission ordinal, and rechecks the admission on
claim and publication. Missing, failed, blocked, expired, deleted, or mismatched inputs stop the
flow.

The synthetic exemption is narrow by construction. Both the application and a database trigger
require the linked capture authorization to have corpus class `synthetic` and a generator
manifest digest. It cannot be used for benchmark or personal media. Synthetic plumbing results
remain evidence about runtime plumbing only, not about real-world reconstruction quality.

A person the region stage proposes is hidden in a versioned masked derivative (`masked_source`),
and that derivative, not the original, is the exact input to depth and segmentation;
[person presentation consent](person-presentation-consent.md) owns the regions and what consent
unmasks.

### 9.4 Person-scoped reconstruction withdrawal

A human-confirmed identity link creates durable dependency edges to person-dependent geometry, all
scenes and scene jobs containing that occurrence's capture, every retained artifact for those
scenes, person or occurrence vectors, dependent aggregates, and entity or scene assertions.
Registration failure does not remove the dependency: an unregistered input was still given to the
reconstruction process. Model-only identity proposals never authorize deletion.

An entity tombstone follows those stored edges without rerunning any detection. Serving stops in the
tombstone transaction. Pending reconstruction work is cancelled, assertions are retracted, and the
purge queue removes stored geometry plus the vector rows themselves. The original source photograph
remains live. A canonical digest-bound withdrawal receipt records the exact tombstone, entity, edge
count, purge count, cancellation count, assertion count, and source-retention policy. The dependency
rows and purge jobs retain target-level audit evidence.

## 10. OPEN: when may a biometric embedding exist at all

**OPEN. This needs an explicit human decision and it is not an engineering question.**

Three research streams produced three incompatible rules. They cannot all be true of one system.

| Rule | Statement | Strictness |
| --- | --- | --- |
| **R-strict** | A detected face with **no consent record** is blurred everywhere, excluded from linking, and its embedding is **not persisted at all**. | Strictest |
| **R-middle** | Compute the embedding, propose the identity, hold it under a **short TTL**, and persist **only on user confirmation**. Discard unconfirmed candidates when the TTL expires. | Middle |
| **R-loose** | Occurrence-level embeddings are persisted routinely; only the cross-capture **entity link** is consent-gated. | Loosest |

**The tension is structural, not a drafting error.** Deny-by-default gating makes the
propose-then-confirm loop impossible for anyone who has not already consented, which is a
chicken-and-egg problem: the point of the loop is to identify people who are unnamed. R-loose
resolves it by persisting biometric identifiers for people who never consented, which is precisely
the collection BIPA s.15(b) and the processing GDPR Art. 9(1) govern.

**What is settled:** nothing in the product computes a biometric embedding. Face, voice and gait
have no producer, and identity proposals are contextual (`exulanica/identity/proposer.py`), so the
question binds before any identity work that would compute one.

**What is not settled:** the rule itself. The research recommends R-middle, on the reasoning that
it is the strictest rule that still permits a propose-then-confirm loop, and that a short TTL is a
defensible answer to "why did you hold a non-consenting person's face template at all". **That
recommendation is recorded, not adopted.** It is a risk-appetite decision, it belongs to a human,
and it must be made before identity work begins.

This section owns the unresolved biometric-embedding policy question. Historical product research
does not decide it or override the implemented admission and presentation rights.

Two consequences of leaving it open, so that nobody is surprised later:

- Guard G5 and principle P1 are written on **R-strict**. Choosing R-middle requires a TTL field, a
  discard job, and a line in the notices explaining that a template may briefly exist before
  confirmation. Choosing R-loose would require rewriting the notices and would forfeit the honest
  framing in section 8.
- No external Exulanica material may describe the embedding-existence rule until this is decided,
  because there are three answers.

## 11. What this document does not settle

| # | Item | Status | Settled by |
| --- | --- | --- | --- |
| 1 | The rule for when a biometric embedding may exist | OPEN | An explicit policy decision under section 10 |
| 2 | The open legal readings of the 2026-08-27 research: the amended EU AI Act dates, the text of the 2024 BIPA s.20 amendment, the *Ryneš* ratio for personal capture in public, and the CPRA subsection letter | OPEN | Reading each primary text; the questions are listed at revision 47f9f7d3 |
| 3 | Whether Nebius zero-data-retention covers every endpoint and model identifier, including vision | OPEN | Written confirmation from Nebius |
| 4 | Whether the workspace isolation controls produce zero cross-workspace retrieval | ASSUMPTION | The nonce canary and the index-level proof of section 3.2, beside the authorisation fuzzing that exists |

Nothing on this list may be stated as settled in the README, the documentation, published
demonstration material, or any external material until the named action has been performed and its
result committed.

## 12. Designs not built

These were proposed for a product that recognised people across a personal photograph library, and
none is part of the code. Each is described in full at revision 47f9f7d3
([privacy-consent-threat-model.md at 47f9f7d3](https://github.com/twinkling-reality/exulanica/blob/47f9f7d3/docs/privacy-consent-threat-model.md)).

- A face re-identification loop: face templates, cluster centroids and cross-capture person links,
  with per-person biometric consent scopes on the `consent_record` table and a subject-facing capture
  notice for them.
- Speed bumps against misuse: a signed capture-session manifest required at ingest, a
  fixed-viewpoint and duration gate, capture volume limits with human review, a consequential-query
  refusal classifier, and break-glass production access.
- A policy engine that admits a model-proposed action only with a single-use user gesture token.
- A workspace setting derived with `SET LOCAL` from a verified JWT claim.
- Crypto-shredding under per-capture, per-person and per-workspace keys, which section 5.5 keeps as
  a requirement, and an approximate vector index with a compaction check.
- A nightly verifier that proves each completed tombstone's absence everywhere and sets
  `verified_at`.
- A startup check that the provider's zero-data-retention mode is on.
- A nonce canary over every answer and log line, and an index-level proof of workspace isolation.
- Published deletion targets (a day for live systems, an hour for indexes) and encrypted backups kept
  for thirty days.
