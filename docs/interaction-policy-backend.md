# Reviewed interaction-policy authority

Status: **IMPLEMENTED** for the capability registry, immutable policy history, Settings and
Companion proposal paths, preview/apply/discard/rollback, stale-base protection, recommendation
observations, and cross-device Settings persistence. Human comprehensibility and longitudinal
stability have **not** been validated with real participants.

The implementation is migration `0021_interaction_policy_versions.sql`, the reviewed
`interaction-policy-registry.v1.json`, `exulanica/world/interaction.py`,
`exulanica/world/interaction_repository.py`, the `/world/interactions` API, and the browser client in
`web/packages/app/src/interaction-policy.ts`.

## Authority and capability boundary

The registry contains only eight capabilities that code already understands: field of view, look
sensitivity, vignette, camera bob, turn mode, transition style, provenance detail, and Companion
initiative. Values are booleans, bounded integers, or enumerated strings. The runtime roles can
read the registry and cannot extend it. A proposal cannot carry code, layout, shaders, URLs, or an
unreviewed capability.

Every candidate is derived deterministically from the current complete parameter set plus a
validated patch. Canonical JSON contains no floats; sensitivity is stored in integer thousandths.
The policy SHA-256 therefore has one language-independent input representation.

Interaction policy belongs to a world: every `/world/interactions` route except the catalog
requires `world_id`, and the browser reads and writes the policy of the world it has open, when
that world opens. Settings saved in one world are not read in another.

## One lifecycle, two origins

Settings and Companion both create the same durable proposal and isolated preview records.
Settings is a direct user choice, so the browser may apply its preview after the control's final
`change` event. Range `input` events are transient local previews and create no history.

A Companion suggestion stops after preview and returns a review handle. A separate confirmation
surface must call `applyCompanionReview`; the suggestion method cannot apply its own proposal.
Companion proposals require an origin reference, model id, prompt version, and at least one source
or observed-choice reference. Raw utterances, messages, transcripts, conversation payloads, and
prompt text are rejected from durable proposal input.

The browser hydrates an existing durable version on a later session or device while retaining
device-only display choices. It does not silently migrate an old local preference bundle when no
durable policy version exists. A failed durable write remains visibly reported as device-only.

## Protected bases and history

Preview and apply compare the current policy version together with the current structural snapshot
id and topology SHA-256. Both the supplied bases and the preview's recorded bases must match under
the same workspace advisory lock used by structural authority. An interaction transaction cannot
modify topology, layout, placement, or neighborhoods.

Applied versions and audit events are append-only. Discard closes only the preview. Rollback copies
a prior complete parameter set into a new child version and records the target; it never moves the
current pointer backward or edits history. Proposal records retain origin, actor, input summary,
capability mapping, explanation, references, validation issues, refinement parent, and lifecycle
state so a user-facing inspector can answer why a change exists.

## Recommendations are observations, not writes

`GET /world/interactions/recommendations` counts repeated applied and rejected explicit choices.
It returns a proposed value, observation counts, and an explanation. Reading recommendations never
creates a proposal, preview, version, or audit event. A recommendation must still enter through the
reviewed lifecycle before it can change current policy.

## Verification boundary

PostgreSQL tests cover registry parity, deterministic candidates, state-neutral discard, immutable
apply, origin/model/prompt/refinement records, transcript exclusion, stale policy and structural
bases, append-only rollback, and recommendation non-mutation. API tests cover the production route
and error contracts; browser tests cover exact Settings patches, transient slider previews,
cross-device hydration, and the Companion preview/explicit-apply split.

Those tests establish determinism, reversibility, session persistence mechanics, and absence of
topology effects. They do not establish that explanations are understandable or that adaptations
remain desirable over weeks. That requires consented participants, repeated sessions, a defined
instrument, and recorded results; none are present in this checkout.
