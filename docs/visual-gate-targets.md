# Visual gate targets

This contract owns what a run of the visual gate scores and what it may and may not do: its targets,
how a page proves who it is, what a record binds, what halts a run, and what the keys cannot see.
The gate scores a page of the development preview, the owned district or a generated street,
against eight mechanical keys and one judged key, `readsAsInhabitedStreet`, which only the named
judge of the [rubric](visual-gate-rubric.md) answers. The key set is
`exulanica.visual-gate-keys/v5` (`exulanica/evaluation/gate_keys.py`); `scripts/capture_visual_gate.mjs`
runs a page, `exulanica/evaluation/visual_gate.py` decides a record, and
`scripts/record_visual_gate_evidence.py` writes it under `docs/evaluation/`. Neither continuous
integration nor the rehearsal runs the gate; its tests do run with the backend suite.

The runs that shaped these rules, each prediction beside what was then measured, among them the
first walk of a composed world, are kept at revision 47f9f7d3
([visual-gate-targets.md at 47f9f7d3](https://github.com/twinkling-reality/exulanica/blob/47f9f7d3/docs/visual-gate-targets.md)),
and their evidence is in the retained records.

<details>
<summary>Sections</summary>

- [Targets](#targets)
- [Authentication conditions](#authentication-conditions)
- [What a record says](#what-a-record-says)
- [What the gate will not do](#what-the-gate-will-not-do)
- [What the keys cannot see](#what-the-keys-cannot-see)
- [A definition with two readings, known and deliberately left](#a-definition-with-two-readings-known-and-deliberately-left)
- [Digest-bound inputs](#digest-bound-inputs)

</details>

## Targets

A **target** says which page a run scores, and everything that makes two runs of it comparable: how
the page is reached, the exact title it must show, what counts as a world being mounted, which
authentication conditions it may run under, what its record binds as the inputs that were scored,
and where the route rule's inputs come from. Targets are declared twice and held to each other:
`GATE_TARGETS` in `exulanica/evaluation/gate_keys.py`, which records may state, and `TARGETS` in
`scripts/capture_visual_gate.mjs`, which the harness may run. `tests/test_visual_gate_targets.py`
asserts the two sets are equal in both directions, so neither can gain a page the other cannot.

| Target | Page | Title | The record binds | The route rule reads |
| --- | --- | --- | --- | --- |
| `owned-district` | The product's shell showing an owned district, at `/` | `PRODUCT_TITLE` in `web/packages/app/src/config.ts` | The district artifact, matched byte for byte on the wire, and the renderer module that drew it | The product's own arrival pose, the collision rings its navigation world holds, and the field bounds the artifact states |
| `generated-tile-evaluation` | The development route that draws a baked tile: `/?preview=1` with exactly one of `tile`, `baked_tile` or `city` | `PREVIEW_TITLE` in the same file | Every drawn container's SHA-256 and `tile_inputs_digest`, the city seed and grammar versions the containers state, the tile runtime module, and the look descriptor | The arrival pose the tile's records state, and the route obstruction rings its navigation side states |

A production build has no code that reaches the generated target.

## Authentication conditions

The gate records how a page proved who it was before it scores what that page drew.
`authenticationConditionOf` in `scripts/capture_visual_gate.mjs` names the condition from the run's
own traffic, and `AUTHENTICATION_CONDITIONS` in `gate_keys.py` is the closed list. A page that
matches none is refused rather than guessed; that refusal is the gate working.

| Condition | The page | Named when |
| --- | --- | --- |
| `credentialed-api` | The product shell, which talks only to the real API | It made no `/preview-api/` request, it was served `/api/graph`, and an anonymous read of the API is refused |
| `vite-preview-api` | The development preview, which talks only to development routes | It made `/preview-api/` requests and no `/api/` request at all |
| `preview-shell-credentialed-tiles` | A development preview that reads its street from the real API with a credential | All five clauses below hold |

A run is `preview-shell-credentialed-tiles` when:

1. the page made at least one `/preview-api/` request, so it is the preview and not the product
   shell;
2. every `/api/` response served 200 was under `/api/tiles`, so nothing else was served to it;
3. it asked `/api/graph` and was not served it, so the credential does not carry the graph;
4. an anonymous read of the API is refused;
5. at least one tile was actually served. Without this clause, clause 2 is true of a page served
   nothing.

The evidence behind the rule, measured on the page it was written for: the page asks for the graph
and gets `403 Forbidden`, asks for the street's tiles and gets 200, and a caller with no credential
gets `401 Unauthorized`. The pair is stronger evidence than an absence would have been: the API
distinguishes no credential from a credential that does not carry this, and the page holds the
second kind.

**DECISION.** The third condition is admitted onto the closed list. Rejected alternatives: widening
the product-shell condition, which means "this is the shipped product" only because the page used no
development routes; widening the preview condition, which means "nothing here came from the real
system" only because the page never touched the real API, and under which an earlier judged run is
retained, so loosening it would change what that record asserts; and committing the street as a
file, which cannot hold the walk, because the walk needs about 131 m of ground and a committed file
holds one 128 m tile. Leaving the list at two names would let the gate walk a stored street and never
score it, because a stored street is served only by the real API.

**Its limits, stated rather than buried.** Clause 3 rests on the page happening to ask for something
it is refused. If the page stops asking, the fact stays true while its evidence disappears, and runs
halt for a reason that looks nothing like the cause. That fails in the safe direction; the durable
repair is for the harness to ask with the page's credential itself. The rule admits any development
preview, for any world and any number of tiles, so long as the real API served it nothing but tiles,
refused it the graph and refuses anonymous callers. It constrains what a page did, not what its
credential is allowed to do: **the rule certifies that a run was clean; it cannot certify that the
credential was narrow.** Issuing the harness a credential that carries tiles and nothing else would
make the two the same.

## What a record says

A record states its target. A record that does not state one scored the owned district, and always
did: the retained records were written before any other page could be scored, and they are
immutable, so that is the only reading that keeps them true. A record of the owned district is
byte-identical to one written before targets existed.

A baseline comparison is allowed across targets only when both records were measured by the same key
set and answered against the same rubric, and it states both targets. The keys do not know which
page they measured; what they cannot survive is a different question.

## What the gate will not do

**It will not compare against a title it cannot derive.** Each target names a symbol in the
product's own source, and the harness reads the title from there. If the symbol is gone the run
halts, because a derivation that quietly yields nothing would compare an empty expectation against
an empty title and pass.

**It will not accept a pose a run chose.** A pose is admitted only when a committed file states it,
the run asks the page for that same pose, and the record binds the file by digest. The URL and the
file have to agree, and either alone is a refusal: a pose in the URL with no file is a pose this run
chose, and a file with no pose in the URL is a walk the page was never asked to take. A run must
never choose where the camera starts. The file is named by `--walk`, must be inside the repository,
and is read strictly, because it is prose: a file that states no walk is refused, and so is a file
that states two different ones. The same walk written twice is one walk. The comparison is made in
the frame the file states, integer millimetres of the city frame and an integer facing, against the
same four integers in the URL, and then against the four the page states as data on its shell,
where the opening is `stated` or `default`. A page that opened at its default when a file states a
walk halts the run.

**It will say when the rule ran without deciding.** A record states `candidatesWithFrontage`: how
many qualifying headings had frontage on both sides at any sample. Zero means the first tie-break
was equal for every candidate and a later one chose, so the heading is the rule's fallback rather
than its preference. Nothing in the rule reads that count.

**It will not walk a route that nothing chose.** The route rule keeps the headings a capsule can
walk and then prefers the one with frontage on both sides. Given no collision rings every heading
qualifies, both tie-breaks are equal and the answer is the lowest heading that fits: a default in
the costume of a decision. So a page with no rings halts.

**It will not derive its own rings.** When a tile carries them, the gate reads the route obstruction
rings the runtime holds. A gate that derives its own scores a walk past obstacles the world does not
have. Those rings are the plan regions a walking capsule is kept clear of: they choose a heading,
they drop anything above head height, and they are not collision solids. Nothing in them stops a
body, so a walk that goes around a bench and a walk that passes through one look the same in a
still frame.

**It will not choose a heading before the world is composed.** The route rule chooses from the
field and the rings of the composed world, so the harness fetches every tile within reach of the
start, not only those along a line it has not yet chosen. A narrower fetch would guess the heading,
and a wrong guess fails as missing ground, which looks like a hole in the pavement. A square with no
ground beside a single row of tiles is the edge of the world, not a defect.

**It will not put a claim about the run inside a judged frame.** Before every capture the harness
hides the development furniture that describes the run (`.generated-tile-evaluation` and
`.scene-segments`) and names what it hid in each capture's record (`furnitureHidden`). It hides
nothing that belongs to the world: the product's hatching over a surface it has no material for
stays in the frame, because a judge deciding whether a street reads as inhabited should see it. The
Companion stays too; it is the product.

**It will not mix its words with the product's.** When a run halts because the product would not
mount a world, the halt record keeps the gate's `reason` and, separately and verbatim,
`productSurface.text`, the words the product showed a person. A missing shell element is `null`, a
shell showing nothing is empty text, and the reader never throws, so an unreadable page records that
it was unreadable and the halt keeps its own reason.

## What the keys cannot see

- **On a generated target, the facade half of `continuousTexturedStreetAndFacades` measures
  nothing.** `facadeTriangles` counts near-vertical triangles along building exterior rings, and a
  tile states none, so the count is zero by construction. The hatching that marks a surface with no
  material is itself a texture, so `untexturedStreetAndFacadeTriangles` cannot tell a dressed surface
  from one wearing that mark. The key can therefore hold over a frame that is only unavailable
  hatching; the block as a whole fails while other keys fail, and changing the key's definition
  needs a new reconciliation record (see the next section).
- **A key does not know which page it measured.** A key that holds on a generated tile can say less
  than the same key on the owned district, so a record states its target and its key set.
- **No mechanical key says anything about the street.** The judged key does, and only the named
  judge answers it; no model may answer, suggest an answer or break a tie ([rubric](visual-gate-rubric.md)).

## A definition with two readings, known and deliberately left

`completeCapsuleClearanceVerification` defines itself, in `exulanica/evaluation/gate_keys.py`, as
true only when a capsule "keeps at least 0.34 m from every drawn triangle that rises more than
0.18 m above that surface and lies outside every building exterior ring with at least 0.34 m to its
nearest edge".

That sentence has two readings:

**A.** Rings EXCLUDE triangles from the test: measure clearance only from triangles that lie outside
every building exterior ring.

**B.** Two conditions: clear of every qualifying drawn triangle, AND outside every building exterior
ring by at least 0.34 m.

**The implementation is B, and has always been B.** That can be established without reading the
implementation at all, from the key's own declared structure: its `decided_by` lists
`capsuleRingContactSamples` as one of the four values that decide it, and a pure exclusion reading
needs no ring counter whatsoever. Reading the code agrees: `measureCapsule` counts triangle contacts
against the drawn triangle table with no ring filter, and separately counts ring contacts against
the prisms, skipping any prism outside the capsule's height band.

**No retained score is affected and none moves.** The measurement has not changed, the key set
version has not changed, and the rubric digest is over `docs/visual-gate-rubric.md`, which states
nothing about capsules or clearance. Every retained record was scored by reading B, because reading
B is what the code has always done.

The sentence is left exactly as it is, on purpose. Its text is quoted verbatim by retained,
digest-bound reconciliation records, and the gate re-checks the current text against them, so
changing one word of it fails those record checks. Editing it therefore needs a new reconciliation
record, and a reconciliation record binds a named human judge's calibration reply, which is a
person's answer and not a thing to be manufactured for a wording change.

## Digest-bound inputs

These files are inputs to scored runs and are never edited in place.

| Input | Bound by | Changing it needs |
| --- | --- | --- |
| [The rubric](visual-gate-rubric.md) | The v5 reconciliation record fixes its SHA-256; `scripts/record_visual_gate_evidence.py` refuses to score unless the file and its copy under the record's artifacts match it | A new rubric version and a new reconciliation record |
| A stated walk file, such as [the corridor walk](visual-gate-corridor-walk.md) | Each run record that walked it binds its SHA-256 | A new file; a bound file keeps its bytes |
| The key definitions in `gate_keys.py` | Retained reconciliation records quote them verbatim, and the gate re-checks the text against them | A new key set version and a new reconciliation record |
