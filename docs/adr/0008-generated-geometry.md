# ADR-0008: Generatively completed geometry is not admitted to the reconstruction ladder

- Status: **ACCEPTED as a refusal with a stated path.** The refusal holds. The admission
  checklist in section 4 is not scheduled and nothing in it is built. It exists so that admitting
  generated geometry has to supersede a decision rather than reinterpret a silence.
- Date: 2026-09-03
- Deciders: Exulanica build. Three independent proposals (admit as a segregated appearance layer;
  refuse with a checklist; admit only a transient two-dimensional imagined view) were scored by
  three judges on truth-guarantee, deletion-and-consent, and product-experience lenses. All three
  judges chose the refusal, at 29, 27 and 27 of 30 against 16, 19 and 18 for the appearance layer.
- Supersedes: nothing.
- Superseded in part by
  [ADR-0023](0023-epistemically-typed-world-memory.md): the refusal still governs the recorded
  reconstruction ladder, evidence, navigation, collision, and unlabeled rendering. A generated
  receipt may enter the artifact and read models as explicitly generated, non-citable,
  non-rung metadata. Generated geometry bytes remain unserved and unrendered until separately
  admitted.
- Related: [product-specification.md](../product-specification.md) section 5;
  [atlas-spatial-architecture.md](../atlas-spatial-architecture.md) section 5;
  [atlas-visual-language.md](../atlas-visual-language.md) sections 2, 4 and 5;
  [privacy-consent-threat-model.md](../privacy-consent-threat-model.md) 6.2(d);
  [license-matrix.md](../license-matrix.md);
  [reconstruction-findings.md](../reconstruction-findings.md);
  [adr/0009-the-ladder-above-rung-3.md](0009-the-ladder-above-rung-3.md).

## Context

### The wish, and the two things inside it

The question put to this work was whether a world model should fill what the camera never saw, so
that an ordinary photograph becomes a place a person can walk around. Two different requests hide
inside that sentence, and only one of them is a design question.

**Generated geometry as space**, meaning surfaces a walker can stand on, be contained by, be
measured against, or see drawn on the Map, is already forbidden by three recorded decisions that
no proposal asked to supersede. Relief "never becomes an invented walkable floor, and unseen backs
are blocked by coarse panel proxies" (atlas-spatial-architecture.md:117). Appearance proposals
"cannot add evidence, confirm a relationship, move a region, change navigation, or widen
traversal" (atlas-visual-language.md:226). "The renderer cannot expand the validated movement
envelope" (frontier-roadmap.md:344). The movement envelope is this product's strongest implicit
claim about what was observed, and a generated floor under the walker is unseen space drawn as
captured space whatever badge it carries.

**Generated geometry as appearance**, meaning a disclosed, non-navigable, non-metric, non-citable
layer, is forbidden by no document. The only text that anticipates a synthesised scene at all is
the AI Act badge decision, which permits one on disclosure terms
(privacy-consent-threat-model.md:228, :768). So the real question was whether an appearance-only
layer could be admitted honestly, and the answer below is that it cannot, for reasons that
are about what exists and what is drawn rather than about invariant 2.

### What the models can and cannot do

**VERIFIED**, retrieved 2026-09-02, licences read from LICENSE files and raw model-card
frontmatter rather than from badges or catalogue labels:

No released generator exposes an observed-versus-generated mask as a product output, and every
diffusion pipeline re-synthesises the observed region as well as the unobserved one. GEN3C is
trained to "translate imperfectly rendered video into a high-quality video, correcting any
artifacts" (https://arxiv.org/html/2503.03751). Marble's own documentation says the model
"interprets your image creatively, so the generated world may expand beyond what's visible in your
original image" and that unseen parts "are generated plausibly to keep the world explorable, so
they won't match a real floor plan"
(https://docs.worldlabs.ai/marble/create/prompt-guides/image-prompt.md and
multi-image-prompt.md). Several models compute a visibility mask internally as a conditioning
signal and none documents exporting it.

The licence position, which is the harder wall:

| Candidate | Position |
| --- | --- |
| Tencent family (HunyuanWorld, Voyager, HY-World 2.0) | Licence "DOES NOT APPLY IN THE EUROPEAN UNION, UNITED KINGDOM AND SOUTH KOREA" (https://raw.githubusercontent.com/Tencent-Hunyuan/HY-World-2.0/main/License.txt). **Conditional, not settled**: whether it excludes this project turns on whether the deployment region and the licensee are inside those territories, and neither has been verified |
| NVIDIA Lyra 2.0 | "You may not use the Model or a Derivative Model in a production environment" (https://huggingface.co/nvidia/Lyra-2.0) |
| NVIDIA GEN3C, Cosmos, Lyra 1.0 | NVIDIA Open Model License weights, refused by license-matrix.md:441 "not even for self-hosted use" |
| FlashWorld | Code Apache-2.0, weights `cc-by-nc-sa-4.0` (https://huggingface.co/imlixinyang/FlashWorld/raw/main/README.md) |
| Stable Virtual Camera | Stability Non-Commercial, and the output "follows the same non-commercial license" |
| WonderWorld, SceneScape | No LICENSE file at all |
| WonderJourney | MIT at its own code; its third-party weights were not read |
| ViewCrafter | Apache-2.0 at its own code and weights, but its base video model's licence is unread and its default depth conditioning is DUSt3R, which is CC BY-NC-SA and BLOCKED at license-matrix.md:229 |
| World Labs Marble, SpAItial | Hosted. Marble's terms take a licence-back on User Content; SpAItial's take a "worldwide, irrevocable, perpetual, royalty-free, sublicensable licence" over Generated Content |

Nothing in the class runs on Apple Silicon by any primary source, and the VRAM floors (Voyager
60 GB, WonderWorld 48 GB, GEN3C about 43 GB) are far above this machine's 18 GiB in any case.

**VERIFIED 2026-09-03.** The Nebius Token Factory catalogue, the one provider this product already
trusts with photographs, carries 29 models whose `type` values are 22 text2text, 6 image2text and
1 embedding. There is no image-output model on it at all.

### What the numbers say about the wish

The handoff carried one number, 27.1 percent of a region's own bounding box filled from above, and
called a single-view shell a curtain rather than a landscape. The conclusion is right and the
number needs its conventions: 27.1 percent is a 12x12 grid at the support floor, while the Map
actually samples at 40x40 and discards cells with fewer than three samples, which is 10.1 percent.
Decomposing it, in [reconstruction-findings.md](../reconstruction-findings.md) section 2, changes
what it means: 26.4 percent of the box lies outside the camera's field of view by geometry alone,
and within 20 m of the camera, on the same grid, 83.8 percent of the frustum cells hold a point.

A generator can raise the first number only by drawing the quarter of the box nobody photographed.
A second photograph from a different place raises it by observation. The frustum-union bound goes
from 73.6 percent for one photograph to 86.1 percent for the eight-view arc, **though about 5.6 of
those 12.5 points are a wider lens rather than more viewpoints**: a single camera with the arc's
lens already reaches 79.2 percent. These are unions of horizontal wedges with no range limit and
no occlusion, so they bound what could be seen rather than what would be filled.

The honest form of the argument does not need the inflated version. **The emptiness is the shape of
one viewpoint, and the answer to it is another viewpoint**, because a second photograph adds
observation where a generator adds invention.

## Decision

**DECISION 1.** Generatively completed geometry is refused from the reconstruction ladder as the
guarantees are recorded. No generated point, segment, splat, mesh, panorama or fill enters
`exulanica.reconstruction`, the `.opm` container or any new container, the artifact table, the rung
predicate, the scene graph, the Map, relief, residency, the metric frame, the query path, or the
World Memory Package, until every item of section 4 exists and a superseding record names the
sentences it amends.

**DECISION 2.** The grounds, stated precisely, because a refusal resting on a false ground is
reopened the moment somebody reads the code.

Grounds that carry the refusal:

1. **Drawn versus captured.** A per-point "generated" flag answers the word captured. It does not
   answer the word drawn. A generated surface behind or beside the camera is exactly the unseen
   back that atlas-spatial-architecture.md:117 blocks with panel proxies, and a generated surface
   at ground level is the terrain platform atlas-visual-language.md:100 removed. Mature disciplines
   that permit reconstruction still refuse where the evidence ends: the Venice Charter requires
   restoration to "stop at the point where conjecture begins" and rules reconstruction out a
   priori except for reassembling existing parts
   (https://www.icomos.org/images/DOCUMENTS/Charters/venice_e.pdf); Agisoft Metashape makes
   extrapolation beyond observed support an explicit non-default mode
   (https://www.agisoft.com/pdf/metashape_2_1_en.pdf).
2. **The rung is defined by what was recovered, and it is displayed** (product-specification.md
   :214, :226). A completed region either takes a rung it did not earn or one whose definition it
   does not meet.
3. **No admissible generator has been established** on the evidence above. Every candidate is
   non-commercial at the weights, territorially excluded, refused by the self-hosted weights
   decision, hosted with a licence-back, **or unread**. The last arm is a task rather than a wall,
   and it is stated as one: ViewCrafter's base video model and WonderJourney's third-party weights
   have not been read, and reading them is how this ground would become conditional. It is not
   worth doing until the grounds above it are answered, since no reading of a licence repairs
   them.
4. **The badge has no render site.** Art. 50 requires a visible Generated badge. The rung itself is
   displayed nowhere: the four rung sentences in the app's copy table are referenced by no
   render site, and the server's terminal formation event hardcodes rung 4
   (exulanica/ingest/formation.py:414). A badge would be satisfied by sequencing rather than by code.

A fifth consideration, **people**, is recorded here as a **precondition shared by both paths rather
than as a ground**, because it does not distinguish them. A generator conditioned on a photograph
containing a person would draw that person from angles nobody photographed, which is worse. But
D16 already classes any 3D reconstruction as face-bearing
(privacy-consent-threat-model.md:532), the renderer's rule that a person is never baked into
geometry cannot fire because the producer writes one unsegmented segment, and the segmentation
model selected for people-masking (`facebook/sam2.1-hiera-tiny`,
model-and-service-selection.md:163) appears nowhere in the code. **That condemns the rung 3 path
that ships just as much**, so it is named in ADR-0009 as work owed before posed rung 3 runs
over an ordinary library, and refusing generation does not discharge it.

Grounds that do **not** carry the refusal, recorded so they are not reused:

- **Invariant 2 is not a ground.** A generated artifact is also not a blob and also cannot be
  cited; the AST test walks every file in the package and would cover a completion module
  automatically. Anyone arguing that generation breaks the citation guarantee is wrong on the code.
- **Deletion closure is not a ground** against a fill conditioned on exactly one photograph, which
  inherits the existing derivative identity, the tombstone enqueue, `purge_releases_bytes` and the
  tombstone guard with no new join. The many-to-many source relation is owed to posed sets and
  splats, not to completion. **This is verified for capture-scoped and workspace-scoped deletion
  only.** A person-scoped withdrawal reaches no artifact at all: the enqueue trigger returns
  without queueing anything for any scope other than `capture` or `workspace`
  (0015_a_tombstone_marks_what_it_deletes.sql:58), while the scope enum admits `interval`, `entity`
  and `assertion` (0001_spine.sql:84). That is a live defect in what ships, recorded as an
  open item below rather than as a ground here, because it is not about generation.
- **Mis-citation is not a ground.** A predicate whose claim is "this capture has a completion
  conditioned on it" is supported by the conditioning photograph, exactly as the depth stage cites
  the frame the model looked at for its rung claim.
- **"There is nothing to read origin from" is not a ground, but the repair is weaker than it
  looks.** If completion is ever pursued, origin would be decided by a visibility cull of the
  generator's output against Exulanica's own rung 3 point map rather than by asking the generator,
  which is strictly better than trusting a model's self-report. It does not make origin
  model-independent, and this record does not claim it does: **the valid mask is itself a MoGe-2
  output**, so epi-1 applies to it, and a zero in that mask means the model declined to place a
  position rather than that the photograph observed nothing. Sky is the clearest case. So the cull
  separates "where the model placed surface" from "where it did not", which is a weaker statement
  than "photographed" versus "invented", and any admission would have to say which of the two it
  is claiming. That is checklist item D5's real burden.

**DECISION 3.** What is settled, whichever way admission goes.

- The licence matrix gains rows refusing World Labs Marble and SpAItial for any feature that sends
  a photograph, on two grounds: the zero-data-retention assumption that governs every provider
  call, and the deletion-closure ground that an irrevocable perpetual sublicensable licence over
  content derived from a user's photograph cannot be closed by a tombstone while "fully deleted" is
  already a forbidden claim. It also records ViewCrafter as Apache-2.0 with its base model
  UNVERIFIED, and the Tencent family, Lyra 2.0, FlashWorld weights, Stable Virtual Camera,
  WonderWorld and SceneScape as refused with the quoted terms.
- The model selection document gains the row "Generated completion: none selected", with the
  measured absence of any image-output model on Token Factory as of 2026-09-03.
- product-specification.md section 5 gains one sentence: the ladder admits no generated rung and no
  generated segment, and generated material, if ever shown, is governed by this record.
- The artifact kind name `point_map_generated` is reserved, with a test asserting that no
  registered stage emits it and no selector reads it. This pins a name, not a behaviour.

## Section 4: the admission checklist

Ordered by how far upstream the change sits. Items D4, D6 and D7's stride decision are owed to the
posed-set work of ADR-0009 regardless and are not work done for generation's sake.

- **D1.** A superseding ADR that names, by dated CORRECTED paragraphs, every sentence it amends:
  product-specification.md:213; atlas-spatial-architecture.md:117; atlas-visual-language.md:38,
  :100, :127; adr/0007:58; frontier-roadmap.md:575.
- **D2.** A visibly distinct completion state, never a rung number. `ReconstructionRung` stays
  `1 | 2 | 3 | 4` in all five of its declaration sites. A `CompletionModifier` on the island
  carries `impliesFreeMovement: false` and `entersNavigation: false`, is displayed beside the rung,
  and extends the existing copy tests to forbid "freely" and "anywhere" in its labels. Not "walk":
  the specification's own rung 2 sentence is "the path actually walked", so banning the word would
  fail the honest description of a corridor. This requires the rung to be displayed at all first, which it is not.
- **D3.** No fifth `ProvenanceClass`. epi-1 says any model output is an inference and a generated
  point is a model output. Origin is an axis orthogonal to provenance, declared on the artifact
  row, never a fifth palette slot in the shader.
- **D4.** Many-to-many artifact sources, so that deleting one of N conditioning captures reaches
  the derivative. Specified in ADR-0009, where posed sets need it.
- **D5.** Stage and model registration: integer-only params, `deterministic = false`, a reviewed
  seed, a licence read from raw frontmatter at a pinned revision, a notices row, and conditioning
  on exactly one photograph so the fill has one source blob. The model need not export an observed
  mask, because none does. Origin is decided by Exulanica's visibility cull of the generator's output
  against the rung 3 point map, discarding anything where the photograph observed surface within a
  tolerance and anything nearer than observed surface. What survives is generated by definition,
  and must additionally be culled where it would draw an unseen back or a ground-level floor.
- **D6.** Never a rung assertion. A generated artifact carries no `reconstruction_rung_is`.
- **D7.** Its own container and its own renderer entity, never inside the point map container
  (OPM/1 when this was written, OPM/2 since 2026-09-03, and ADR-0010 D8 restates the prohibition
  there rather than leaving this reference to age): no pick id, excluded
  from relief and from every navigation surface, clipped inside the observed footprint so layout
  and arrival see an unchanged number, and present only at the fullest residency stage so it is the
  first thing shed under frame pressure.
- **D8.** A visual dictionary row before any register is borrowed. Cool violet and graphite are
  assigned to absence and unresolved material; reusing that colour for invented presence inverts
  what the colour says.
- **D9.** Per-artifact provenance on export: content class, what it was conditioned on, the
  generator and its revision, and an IPTC `digitalSourceType`
  (https://cv.iptc.org/newscodes/digitalsourcetype/), stamped inside the bytes as well as shown in
  the interface, because a badge does not survive a screenshot.
- **D10.** A gate that can fail, checking that the observed artifact is unchanged, that relief
  excludes generated points, that no occurrence and no evidence span references a generated
  artifact, that the badge renders, that deletion closes, and that no person appears in generated
  output from a people-masked conditioning image.
- **D11.** The evaluation corpus contract declares that a bundle contains generated geometry.
- **D12.** The exact-recompute claim is weakened in writing to exclude generated artifacts, which
  are deleted rather than recomputed. **This is owed, and not by admission**: the claim rests on
  there being no trained weights, and MoGe-2 is trained weights and is the shipping rung 3
  producer, whose stage is already registered non-deterministic for exactly that reason. It is
  listed here for completeness and tracked as a live defect below.

## Alternatives rejected

1. **A generated segment inside the observed `.opm`, with provenance `inference` and support
   zero** (the sketch this work inherited). Rejected: `inference` absorbs it silently, since the
   type is defined as any model output; the Map's relief reads every point with no provenance
   filter; it changes every observed byte and the cross-language fixture whenever the generator
   changes; and it puts non-photograph colour beside photograph colour in a file whose colour is
   the photograph.
2. **A segregated, disclosed, non-citable, non-navigable appearance layer conditioned on one
   photograph.** Rejected as written. Its cull kept points behind the camera, outside the image and
   at ground level, which draws exactly the unseen backs and floors two documents forbid, without
   naming a supersession. Its sound parts are kept as checklist material: origin by Exulanica's own
   cull, single-photograph conditioning, a separate kind and container, the per-artifact export
   fields, and the perception-boundary tests.
3. **A walkable generated room in a sandbox scene outside the Atlas.** Rejected: walking is the
   property that makes generated content geometry; disconnected scenes are already rejected at
   atlas-spatial-architecture.md:45; and "the stronger Exulanica demonstration is not 'AI generated a
   pretty scene'" (frontier-roadmap.md:575).
4. **A display-time generated surround or outpainted skybox behind a rung 3 panel.** Rejected:
   every outpainting model re-synthesises the observed region, so the result is a second readable
   copy of the source at the same vantage, which visual-language rule 2 forbids. The existing
   model-free atmosphere already reads as imagination rather than record and needs no generation.
5. **Hosted generators.** Rejected on the two grounds in Decision 3, and because they add an
   outbound flow of private photographs that the privacy model does not describe.
6. **A fifth rung, or a rung 3.5.** Rejected: every rung is defined by what was recovered from
   photographs, and completion changes nothing about what the user can do.
7. **Refusal by silence, deferring this record until a model exists.** Rejected: silence is exactly
   how a refusal gets reinterpreted.

Not rejected and not admitted: a transient, badged, non-photographic "imagined view" shown as a
picture rather than as geometry. It is outside this record's question, and it is deferred to its
own record with the conditions all three judges attached, including that no such thing is built
unless a predeclared study shows it recruits second photographs better than the plain designed
void does.

## Consequences

What refusing costs, stated plainly:

- A walkable place from one ordinary photograph does not exist in this product. One photograph
  stays rung 3.
- Libraries made mostly of bursts stay mostly at rung 3. The fraction of a personal library that
  carries a registrable multi-photograph component is genuinely unknown; the published proxies
  bracket it between 1.6 percent for an unfiltered user corpus and 20 to 25 percent for
  landmark-filtered collections.
- The Map keeps drawing a ribbon for a one-photograph region, because the ribbon is the truth.
- The wish is answered with a capture loop that the user closes with a camera, not with a
  generator.

What it commits the ladder work to, because completion would have needed the same things:
people-masking wired into reconstruction before posed rung 3 runs over an ordinary library; the
many-to-many artifact source relation before any scene-level artifact ships; the formation event
reading the recorded rung so that the rung is displayed at all.

## Live defects this record surfaced, which are not about generation

Both were found while testing the grounds above, and both are defects in what ships. They
are recorded here because this is where they were found, and they belong to the ladder work rather
than to any admission.

- **A person-scoped withdrawal reaches no derivative.** The tombstone trigger enqueues purge jobs
  only for `capture` and `workspace` scopes, while the scope enum also admits `interval`, `entity`
  and `assertion`, so withdrawing a person queues nothing and no artifact derived from their
  photographs is destroyed. The privacy model's own withdrawal row expects otherwise.
- **The exact-recompute claim is already false.** It rests on there being no trained weights at
  this stage, and MoGe-2 is trained weights and is the shipping rung 3 producer, whose stage is
  registered non-deterministic for that reason. The claim needs correcting whether or not anything
  generative is ever admitted.

## What must be measured before any admission

- The filled fraction of the frustum union for a real multi-photograph capture, against the
  single-photograph decomposition in reconstruction-findings.md section 2.
- The fraction of places in a personal library with a registrable multi-photograph component. This
  is the number the wish actually turns on, and nobody has it.
- Whether a rendered view of generated geometry is "synthetic image content" under EU AI Act
  Art. 50(2), which is an open legal question this record answers by assuming the stricter reading.
- Only if admission is pursued: ViewCrafter's base model and checkpoint licences at a pinned
  revision; whether its conditioning accepts a MoGe-2 map in place of DUSt3R; its wall time and
  peak VRAM on the L40S preset; and the rate at which a person detector fires on generated frames
  whose conditioning image was people-masked.
