# World kinds

A world kind states a kind of place people can live in (a farm, a building site, a cafe) as one
typed, versioned document. This contract owns that document, the checks that admit it, the site
grammar that generates a world from it, the society such a world holds, the receipt that keeps
it, the drawing it serves and the routes that list, keep and make worlds of kinds. The town keeps
its own generator; the [grammar contract](grammar-package.md) owns the city stages, and
[decision 0029](adr/0029-a-world-kind-is-data-a-site-grammar-realises.md) records why a kind is
data that one grammar realises rather than code per kind.

Contents: [the document](#the-kind-document), [roles](#engine-roles-and-look-roles),
[checks](#checks), [the site grammar](#the-site-grammar), [people](#people-in-a-site-world),
[the receipt](#a-world-made-from-a-kind), [the drawing](#the-drawing),
[storage and routes](#storage-and-routes), [the town](#the-town-as-a-kind),
[limits](#limits).

## The kind document

Profile `exulanica.world-kind/v1`, read by `read_kind` in
[`exulanica/world/kinds/document.py`](../exulanica/world/kinds/document.py). Every key is closed:
a key the profile does not state is refused. Every figure is an integer; a float is refused
wherever it appears. A kind is identified by its key (`[a-z][a-z0-9_]{0,31}`), its version (1 to
9999) and the SHA-256 of its canonical JSON.

| Field | Meaning |
| --- | --- |
| `kind`, `version`, `label`, `summary` | Identity and plain words |
| `origin`, `provenance`, `licence` | `authored`, `drafted`, `uploaded` or `imported`; who or what made it; one of Apache-2.0, CC-BY-4.0, CC0-1.0, MIT |
| `generator` | `site-plan` version 1, the composer that generates every kind this profile states |
| `site` | Enclosure (`open` or `indoor`), width and depth, the ground's part, the spine path from the entry, an optional boundary and the entry's width |
| `society` | Off-site residents who come in through the entry, the share of residents who work, per mille, and optionally the words and use class of the off-site residents' home (`offsite_home`) and what is said of where its people are and walk (`place_words`: `here`, such as "on this farm", and `around`, such as "across the farm") |
| `use_classes` | The kind's own workplaces, shops and homes in the society's use-class form, with shifts from the shift catalog |
| `parts` | Each part's key, label, description, form, engine roles, look role, use class and the sizes its form needs |
| `zones` | Each zone's placement, share of the site, access, pattern and the parts it holds with counts |
| `parameters`, `presets` | At most sixteen values a person may change, each with its range and step, and one to eight named presets |

What a kind's society reads where the kind states nothing is the
[kind society catalog](../assets/catalogs/world-kinds/kind-society.v1.json), resolved once as the
kind is read: the use class a seat (`bench`) and a home (`residential`) take when they name none,
the home off the site ("home, off the site", `residential`), and the place words `here` ("here")
and `around` ("around here"). An off-site home's use class is a residential one; place words are
one line of at most 60 characters each. A world records what was resolved in its receipt's
society, and a receipt written before kinds stated these reads the catalog's.

A **figure** is a whole number, a parameter's value (`{"parameter": key}`) or, for a figure drawn
per placed thing, a span the seed draws from (`{"from": a, "to": b}`). Lengths a layout steps along
are whole modules of the site: 500 mm outdoors and 100 mm indoors. The
[bounds catalog](../assets/catalogs/world-kinds/kind-bound.v1.json) states every figure's range
with its reason, for example a site from 8 m to 256 m on each side and a path from 1.5 m, two
people passing, to 12 m.

A **form** says how the generator lays a part out and draws it: `path`, `area`, `structure`,
`room`, `fixture` or `boundary`. A **placement** says where a zone lies: `front`, `middle` and
`back` beside the spine, `left` or `right` of it, or `edge_back` across the far edge on a cross
path. A **pattern** says how a zone or a room lays out what it holds: `fill`, `row`, `grid`,
`scatter`, `perimeter`, `cluster`, `centre` or `back_wall`. A zone with `closed` access is one
people never enter, such as a crane's reach.

**Values.** A person, a model choosing values for them and an API client ask for a world the same
way: a preset and, optionally, values for its parameters. `KindDocument.values` holds each value to
its parameter's range and step and refuses by name with the specification's codes
(`specification_value_unknown`, `specification_value_out_of_range`); it never clamps. An unknown
preset is `unknown_world_recipe`.

## Engine roles and look roles

A part's **engine roles** say what the engine does with it. The sixteen roles, the forms that may
take each and why, are the [role catalog](../assets/catalogs/world-kinds/kind-role.v1.json): `bed`,
`boundary`, `decoration`, `field`, `gathering`, `ground`, `home`, `no_go`, `obstruction`,
`parking`, `path`, `road`, `seat`, `shop`, `water` and `workplace`. A part's **look role**
(`family.leaf`) names what a style pack dresses. The sixteen families, each with its fit
(`contain`, `fill`, `tile` or `surface`), are the [look-family
catalog](../assets/catalogs/world-kinds/look-family.v1.json); the leaf is the kind's own word, so
a pack dresses any leaf of a family it knows and the engine's own primitive draws the rest. A
surface's leaf (a ground, a path, water, a wall, a roof) is read by its words in the [surface
material catalog](../assets/catalogs/world-kinds/surface-material.v2.json), so sand is drawn as sand
and adobe as adobe in any pack ([style pack contract](style-pack-contract.md), section 3).

## Checks

Nothing is generated from a kind, and nothing is kept, until both stages pass. Each refusal has a
code, the place in the document and a sentence; `KIND_CODES` in the document module states every
code with its meaning.

**Stage A, the document** (`read_kind`): closed keys, integers, the bounds catalog, references that
resolve (a part, zone, use class, shift or parameter the kind states), roles the part's form may
take, and the needs each role brings (a seat states its seats, a workplace a workplace use class).
Use classes pass the society's own use-class checks. Text, a use class's words included, holds no
control, format or private-use characters, and no string anywhere in the document holds a NUL;
every lookup a value names is refused by name when the value is not a key. Two caps bound what
generating the kind can cost, each figure at its most:
a site's grid (its width by its depth in modules) is at most 512 by 512 points (`grid_points`), and
everything the kind places, a structure's rooms and their fixtures included, at most 512 things
(`placed_things`). Codes: `kind_document_invalid`, `kind_role_unknown`, `kind_reference_unknown`,
`kind_out_of_bounds`, `kind_role_unmet`.

**Stage B, sample worlds** ([`samples.py`](../exulanica/world/kinds/samples.py)): every preset
with two seeds, and each parameter's least and greatest with one, at most 48 samples. Each sample
is made the way a world of the kind is made, and a seed candidate is kept only when

- the site grammar lays it out (`kind_generation_refused`) within its layout budget: one world's
  layout tries at most 100,000 placements (`layout_trials`), and every sample of one check together
  at most 1,000,000 (`check_layout_trials`), a placement being one footprint tried or one point a
  search for free ground lists (`kind_layout_over_budget`);
- its place passes the society's place check under the kind's routine (`kind_generation_refused`);
- its walking graph has at most 962 places, the largest graph a living society's tick was measured
  on within its budget, held while the graph is built so an oversized site stops early
  (`kind_graph_over_budget`);
- it houses 1 to 128 people, the most one tick was measured to hold (`kind_population_out_of_bounds`);
- every destination is reached from the entry (`kind_unreachable`);
- a kind with workplaces has at least one worker (`kind_capacity_short`).

Four candidates are tried per sample, as a town's preset states. A sample none of whose candidates
is kept refuses the kind with every candidate's sentence. The outcome of every sample is the
validation report, `exulanica.world-kind-validation/v1`, which a kept kind stores beside it.

Everything generated from a kind runs in the kind worker
([`worker.py`](../exulanica/world/kinds/worker.py)), one spawned process apart from the request's
thread, as a town's sample does: stage B, composing a world of a kind, and generating a site
world's records again for its drawing or for the place its society walks. No site is generated on a request's thread: the reader every
other generated world's records go through refuses a site world, and a site world states no roads,
so the reads that ask a world for its roads (capabilities, the clock, traffic and the role hosts)
answer without generating it. The worker's bounds:

- a check waits at most 40 s, a world's composition 15 s, a drawing 15 s and a place 15 s;
- one request waits for a job; asking for a job already running is answered at once;
- at most four jobs wait besides the one running, and one workspace has at most two jobs waiting or
  running, each counting until it finishes, whoever stopped waiting for it;
- finished checks (by the workspace and the kind document's digest, 32 kept, so one workspace is
  told nothing of another's check of the same document), drawings (by the receipt's digest, 16
  kept) and places (by the receipt's digest and the place, 16 kept) are kept, so asking again reads
  them; a composed world is never kept, since each is made for a fresh identity, and its drawing
  and its society's place are kept as they are made;
- a process whose oldest job runs past 160 s is replaced, checked at every request.

A job the worker does not finish in time, cannot take or loses answers 503 `kind_work_overran`,
`kind_work_busy` or `kind_work_unavailable` with words and a `Retry-After`, and nothing is written.
The limits rest on measured stress kinds (the worker module and the bounds catalog state them).

## The site grammar

The site grammar (`site` version 1,
[`exulanica/grammar/grammars/site/`](../exulanica/grammar/grammars/site/)) is a pure, seeded,
integer generator under the generic grammar contract. It is built per plan rather than registered,
because its input is a kind resolved with values (`KindDocument.plan`), not a recipe. Its
descriptor's digest is pinned with every other grammar's.

A site is a rectangle entered from the middle of its south edge
([`layout.py`](../exulanica/grammar/grammars/site/layout.py)). The spine runs north from the entry
through the middle of the site. An `edge_back` zone takes a strip across the far edge, fronted by a
cross path. Every other zone takes a lot on one side of the spine, as long as its parts need and
then its share of what is left of that side, so every lot fronts the spine; a side that cannot
hold what its zones need is refused, naming each figure. In its lot's own frame a zone lays a
walkable verge along its front, its structures in a row with their doors facing the front, a lane,
its areas to the back, its fixtures by their patterns in the free ground between with a clear
corridor to each, and its boundary with a gate in the middle of its front. A pattern that cannot
place a fixture where its line says takes the nearest free place along the same line. A scattered
holding draws its cells one at a time as it tries them, and a search for free ground lists its
points a band at a time, so the work a layout does follows what it places, not the size of the
site, and a layout over its budget is refused before it does the work. A structure
is four walls with its door in the front one; its rooms stand in a row along its front with a door
in each wall between two rooms. What does not fit is refused by name, never shrunk.

It writes `site.extent`, `site.path`, `site.zone`, `site.area`, `site.structure`, `site.room`,
`site.wall` and `site.fixture` records, every figure in integer millimetres in the site's frame
(x east, y north, from the south-west corner).

## People in a site world

The site place producer
([`society_site_place.py`](../exulanica/world/society_site_place.py)) turns a site's records into
a society place (`society-place` version 2): a walking lattice over open ground and corridors that
stays clear of every blocker, doors into structures, rooms, fields reached at their access point,
fixtures with places along their fronts, and the kind's homes, workplaces and shops as
destinations. A fixture is approached from its front; where something the layout set within its
clearance stands on that approach, from its back, and its places then face its back. People the
kind states as off-site residents live in one home at the entry (`home:offsite`) and come in
through it.

A kind's routine is the living town's routine with an **overlay**
([`routine.py`](../exulanica/world/kinds/routine.py)), `exulanica.routine-overlay/v1`: the kind's
use classes and its employment share. The overlaid routine is named by SHA-256 over the base
routine's digest and the overlay, and its binding states the overlay, so a society reads the same
routine again from its input alone. A routine with no overlay is the base routine, unchanged: a
town's input, binding and every minute played from it are the bytes they were before overlays
existed (`tests/test_town_society_unchanged_by_site_worlds.py`). The kind's checks build every
sample world's place and hold it to the society's place check under that routine.

A site world's society uses the walking-surfaces input profile
(`exulanica.society-input/walking-surfaces-v2`) with the navigation profile
`site-walking-surfaces/v1`, site record subjects and a `site_place` dependency in place of a
city's `city_place`. The living engine is `exulanica-society/v5`, unchanged; the
[society contract](synthetic-society-contract.md) owns inputs and engines. A site world's society
ground is the society ground catalog's `generated_site` entry. The page hosts
a site world's people in the site's frame, as it hosts a town's. The place a site world's society
walks is made in the kind worker from the world's receipt, never on a request's thread, and kept by
the workspace, the receipt and the place; the place the world's checks built is kept when the world
is made. Nothing waits for the worker inside a transaction:

- **Bringing people in** asks the worker for the place before its transaction begins, holding no
  lock, and waits for it at most 15 s; inside the transaction the place is only read from what the
  worker keeps.
- **Each later input**, such as one an edit composes, is composed from the place the society's last
  input carries (held to its `site_place` digest, the world's snapshot, which names the receipt,
  and the routine the receipt names), so an edit never asks the worker.
- A place neither holds is asked of the worker without waiting, and the request is answered 503
  `kind_work_overran`, `kind_work_busy` or `kind_work_unavailable` with a `Retry-After`, nothing
  written; asking again reads the finished place.
- A place whose walking graph would grow past the bounds catalog's `walking_nodes` is refused by
  name (424 `unavailable_society_input`, its detail naming `kind_graph_over_budget`), as a kind's
  checks refuse it.

A site's place states the kind's place words (`words`: `here`, `around`), which a town's never
does. People are told and spoken of in them: a person asked to choose is told it is a given
minute "on this farm" rather than "in the town"; the inspector and the Companion read the words
the inhabitant words catalog keys by the society ground `generated_site`
("A simulated farmhand on this farm.", "walking across the farm"), served with the society's
places as `place_words`. A world's saved entry serves `society_engine`, the engine its people are
brought in with, which the page reads rather than deriving from the entry's shape.

## A world made from a kind

The site-plan composer ([`site_plan.py`](../exulanica/world/composers/site_plan.py)) makes a world
of a kind for the world's own identity: it tries the kind's seed candidates in order and keeps the
first whose site is laid out and meets every need above. The world is one region,
`region:generated`, whose frame is the site's own. A person arrives on the spine 4 m in from the
entry, facing into the site.

The receipt (`world_generation_receipt`, the same profile a town's uses) names the composer
`site-plan` and carries:

- the **whole kind document** and the values, so the world regenerates from its receipt alone and
  no later version of a kind, in a workspace or in the library, moves it;
- the site grammar and its descriptor digest, the plan digest and the generation's output digest,
  which hold the world;
- the kind catalogs' digests, as provenance: an edit to a catalog that leaves the plan and records
  as they were does not unmake the world;
- the routine binding with its overlay, what each part is for, the candidate kept and every
  earlier refusal, the seed, the subject identity and the arrival;
- no tiles: a site world is drawn from its records and never baked.

A receipt whose kind document, grammar or routine catalogs no longer read the same, or whose
records come out otherwise, is refused by name (`generated_world_grammar_changed`,
`generated_world_catalogs_changed`, `generated_world_output_changed`,
`generated_world_unreadable`) and its saved entry reads as unavailable with that reason, as for a
town ([saved world entries](saved-world-entry.md)).

A site world's saved entry states `generated_site` (the kind, its version and label, the region
and the arrival with the way a person faces) and no `generated_ground`. An available generated
entry states exactly one of the two. Migration 0140 widens the receipt table's check so a site receipt
states its kind and no tiles, while a town's receipt is held to the rule 0118 states.

## The drawing

A site world serves one document, `exulanica.site-drawing/v1`, made from the records its receipt
generates again ([`site_drawing.py`](../exulanica/world/site_drawing.py)):

- **slots**, one per drawn piece: a stable identity (the record's subject identity, with the piece
  it names for walls, lintels, doors and roofs), the look role, the base centre of its box, its
  quarter turns, its box, its front (+y of the slot), its family's fit, the engine's own primitive
  (`box`, `plane`, `gable` or `none`) and, for a surface, a UV frame at physical scale. Surfaces lie
  a few millimetres apart by kind (ground, zone, path, area, floor), so none fights another for the
  same pixels. A slot that is a piece of a building (its walls, lintels and doors,
  its roof, its rooms' floors and the fixtures in its rooms) states `structure`, the identity of
  the building's own slot, so a pack that fills that slot with one piece for the whole building
  can show or hide the building's own pieces together; a slot of no building states none;
- **walk**: the floor a person exploring stands on and the boxes they keep out of (wall pieces,
  blocking fixtures and water);
- **seats**: each seat's height;
- the kind, the extent and enclosure, and the arrival.

A style pack dresses a slot by its look role and never changes it. Nothing in the drawing decides a
look.

The application draws a site world from this document
([`generated-site`](../web/packages/atlas-react/src/playcanvas/generated-site/), opened by
[`site-world.ts`](../web/packages/app/src/composition/site-world.ts)). It reads the drawing through
the world's version, holds it to the entity tag the route names (SHA-256 over its canonical JSON)
and refuses a document of another profile or world by name; a drawing that cannot be read is not
drawn and the page says so. While the kind worker is still making the drawing, the page says the
world is still being drawn and asks again after each `Retry-After`, at most six times. Each slot is drawn as its primitive at its base, turned by its quarter
turns counterclockwise seen from above, in a fallback colour of its look family (or, for a ground,
path or road, of a material its leaf names). The site is drawn in the look the page chooses for any
world, the address's, else the pack its appearance names, else the host's default: the pack's
light lights it and the pack dresses its slots by their look roles, its swatches on the primitives
and its pieces in their slots ([drawing a site in a pack](style-pack-contract.md#71-drawing-a-site-in-a-pack));
a slot the pack does not dress keeps its primitive and fallback colour. A person exploring stands on the floor and nowhere beyond it, and every
blocker and keep-out box is an obstacle the movement resolver collides against with the society's
340 mm walking radius, so a person comes into a building through its door. The About panel says
the world was made from its kind. The person's view stays first person, as on a generated tile,
because the follow camera does not keep out of a site's walls.

## Storage and routes

A workspace's own kinds are rows of `world_kind_version` (migration 0140): the document as
admitted, its digest, origin and validation report, appended once and never changed or deleted,
inside the workspace under row-level security. An edit is a new version. A workspace keeps at
most 64 kind versions; one more is refused 409 `kind_cap_reached`. An uploaded kind's provenance
says only that it was uploaded to its workspace and keeps no words the document carried; the row
records the uploading account, so neither the document nor any world's receipt names an account. A kept kind the catalogs no
longer read is left out of the library and refused 409 `kind_unreadable` when a world of it is
asked for; its row stays kept. The kinds the product
ships are files under `assets/catalogs/world-kinds/library`, read by
[`library.py`](../exulanica/world/kinds/library.py); a test holds every shipped kind to both
stages.

| Route | Permission | Behaviour |
| --- | --- | --- |
| `GET /worlds/kinds` | world read | The town, every shipped kind and the workspace's own kinds, each with its parts, parameters and presets in plain words, and whether this caller may draft a kind of place here |
| `POST /worlds/kinds/drafts` | world write and model invoke | Starts a draft of a kind of place from a description (1 to 1,000 characters; a body over 16,384 bytes is refused 413 before it is read) and answers 202 with the draft at once; before anything is spent, 503 without a model credential, 429 `budget_exceeded` with its `spending` member when the workspace's allowance for the drafting model is spent and 409 `kind_cap_reached`; 409 `kind_draft_busy` while this workspace runs a draft, naming its `draft_id` only to the person who started it; 429 `kind_draft_limit` with a `Retry-After` when the caller has started 12 drafts in the last hour; 503 `kind_draft_capacity` with a `Retry-After` when the server runs as many drafts as it may |
| `GET /worlds/kinds/drafts` | world read | The caller's drafts the server still holds in this workspace, newest first |
| `GET /worlds/kinds/drafts/{draft_id}` | world read | The draft's state: drafting, ready with the kept kind, or refused by name; 404 `kind_draft_unknown` for an id the server does not hold for this caller in this workspace, another person's draft included |
| `POST /worlds/kinds` | world write | Keeps a creator's kind (origin `uploaded`, at most 65,536 bytes; a body over 131,072 bytes is refused 413 before it is read) once both stages pass; 422 names the refusal and writes nothing; 409 `kind_version_exists` or `kind_cap_reached`, asked before any sample world is built; 503 when the worker cannot answer in time |
| `POST /worlds/kinds/{kind}/worlds` | world write | Makes a world of a kind with a preset, values and a title, and saves its entry; the latest version unless one is named; a body over 16,384 bytes is refused 413 before it is read; 503 when the worker cannot answer in time |
| `GET /world/versions/{version_id}/site` | world read | The drawing, served only to the world whose snapshot names its receipt, with its digest as the entity tag; made in the kind worker and kept, 503 with a `Retry-After` while it cannot be |

Making a world answers 404 for an unknown kind or preset, 422 for a value the kind does not offer
(naming the key, the value and the range) or an empty title, 409 with every refusal when no
candidate makes a world people can live in, 409 when the workspace holds as many generated worlds
as the count policy allows, and 403 `worlds_read_only` when the deployment's database role cannot
register a world. Nothing is written when any is refused. A stranger is told a world does not
exist, as for every world route. The browser offers no upload: keeping a kind is the API path a
creator or an agent uses.

## A kind drafted from words

The kind drafter ([`kind_drafting.py`](../exulanica/selection/kind_drafting.py)) asks a model to
fill a **brief** ([`kind_brief.py`](../exulanica/selection/kind_brief.py)) for a person's
description: zones holding their structures, rooms, areas and fixtures, each part's use stated
where it stands, with no key and no reference, and every closed word a list the form offers. Code
compiles the brief into a kind document: the keys and references, a use class for each use, the
spine and the boundary, seat and standing places trimmed to the society's spacing, a bed's
sleepers, and who comes in where nobody lives there.

The compiler then sizes the site. The site is made at least as deep as the layout's need function
says its zones need; then its sample worlds are built as the checks build them, and each refusal
sizing can answer is answered from the layout's own figures, for at most 64 rounds: a side of the
spine short by its stated shortfall, a zone too shallow for its structure, a zone across the far
edge given more of the depth, a structure too small for its rooms grown a quarter each way, a
walking graph over budget shrunk. Once the samples pass, each structure sizing grew is trimmed to
the smallest that passes, and a site holding no area to twice its smallest passing size each way.
Both stages of the checks stay the one authority: a kind they refuse is refused by name. The
drafter sends one brief and at most two repairs, each naming the check's code, the place in the
brief and the check's own sentence, never the reply's words; there is no fallback model.

The page calls a world kind a **kind of place**. Before anything is typed, `GET /worlds/kinds`
says whether this caller may draft one here (`drafting`: `offered`, and otherwise `code`:
`not_authorised` without world write and model invoke, `provider_credential_absent` without a
model credential, `budget_exceeded` when the workspace's allowance for the drafting model admits
no attempt, spent or below the least one attempt reserves (its answer bound and its instructions
at the model's prices), `kind_cap_reached` when the workspace is full, `kind_draft_busy` while the
workspace runs a draft, `kind_draft_limit` when the caller has started as many drafts this hour as
one person may), with `refusals`, the closed list of every code a draft's routes and its job answer
with, so the page shows no field the server would refuse this caller here. The server's own
capacity changes from moment to moment, so an offered start may still be refused
`kind_draft_capacity`, which says when to try again; an allowance just above that least amount may
still meet its ceiling at a repair, and the draft then ends `budget_exceeded`. A person asks for a
draft with `POST /worlds/kinds/drafts` and the words they typed. The route answers at once, 202
with the draft's id, and never waits on the model: a job in the API process drafts on the
`kind_drafter` role, holds each drafted kind to both stages in the kind worker as an
upload is held, and keeps a passing kind in the workspace, origin `drafted`, under the key its
brief states or, where the workspace already keeps that key, the key with the first number free
after it. The kind's provenance names the role, the model, the prompt version and digest and the
words' digest, never the words. The page polls `GET /worlds/kinds/drafts/{draft_id}`, and
`GET /worlds/kinds/drafts` lists the caller's drafts the server still holds, newest first, so a
reload, a second tab or a return finds a draft still running. Only the person who started a
draft reads it, and its `description` holds their words only while it runs: a draft that ended
forgets them, so a page that offers the words again keeps them itself. A draft is in one of three
states, which the page says in these words:

| State | What the page says |
| --- | --- |
| `drafting` | "Drafting your kind of place, {elapsed} so far. It can take a few minutes. You can leave: it keeps going, and it will be among your kinds when it is ready." ({elapsed} from the answer's `elapsed_seconds`) |
| `ready` | "{label}: {summary}" and "Drafted from your words by {model name}" (the answer's `model_name`), then its presets and values |
| `refused` | "These words did not draft a kind of place people can live, walk and work in: {sentence} Try describing it another way." ({sentence} the refusal's `detail`, the last check's own sentence; where no check refused, the refusal's `check` is null and the page says the two sentences without it, since the drafter's own sentence would repeat the first) |

A refusal that is not the drafted kind's (`budget_exceeded`, `kind_draft_unanswered`,
`kind_draft_model_failed`, `kind_work_unavailable`, `kind_draft_failed`, `kind_cap_reached`,
`kind_version_exists`) is said in the closed list's words. A model that did not answer within the
role's timeout is `kind_draft_unanswered`; a provider's error status, a connection that failed or a
call refused before it was sent is `kind_draft_model_failed`, never said as the model's silence.
Ready and refused carry what the drafting cost, every call made included, except a draft ended for
running past its deadline, whose calls the server no longer reads. Saved names are replaced in the
words before the job starts, and the workspace's rules, releasing no place's name, are applied again
as each request leaves. A draft takes at most the longest its client takes for one call of the role
and the checks' bound, for each of its three attempts. Making a world of the kept kind is
`POST /worlds/kinds/{kind}/worlds`.

## The town as a kind

The library lists the town through an adapter (`exulanica.world-kind-adapter/v1`,
[`town.v1.json`](../assets/catalogs/world-kinds/library/town.v1.json)) that names the world
specification schema and the preset catalog by their files' SHA-256 and copies neither, and lists
the town's parts in the same words and look roles every kind uses. Making a town of the kind
`town` makes it from its preset through the same gate and composer as `POST /worlds/generated`, so
it is the same world with the same receipt. The city grammar keeps generating every town; no
town's receipt or digest depends on the adapter.

## Limits

- A site takes a pack's swatches and pieces only: it holds no texture set's images, so a leaf a pack
  dresses with a texture set takes its material where its words name one, and otherwise its
  family's `default`.
- A surface is drawn in one flat colour for its material
  ([style pack contract](style-pack-contract.md), section 3). A roof is shaped by its material
  (thatch steep and overhanging, a canvas roof a tent's, an earth roof a slab with a parapet); the
  walls under it are not: every structure but a tent is a box of walls, and a tall thing standing
  near a tent's side shows through its canvas.
- Beyond an open site its own base ground runs out to the pack's reach, flat. What surrounds a
  place is not read from its words: an island has no sea round it and a forest camp no tree.
- A draft's state lives in the API process that started it, so drafting needs one API process or
  routing that sends each person to the same one ([deployment guide](deployment.md), 5.4): a poll
  another process answers reads `kind_draft_unknown` while the draft still runs. A draft still
  running when its process stops is lost, what it had spent stands, and its page reads
  `kind_draft_unknown` and offers to start again. A ready draft's kind is kept in the workspace and
  outlives the process; an ended draft's state is answered for an hour after it ended, and one
  still drafting past its deadline and two minutes ends as `kind_draft_failed`. One workspace runs
  one draft at a time, one person starts at most 12 an hour and the process runs two. Running
  drafts on the durable job queue is planned work, not delivered.
- A drafted kind is kept once it passes, without a separate accept, and takes one of the
  workspace's kind versions; no kind is removed. Hiding a kind no world uses is planned work.
- The library ships the town's adapter and no site-grammar kind. The three kinds under
  `tests/fixtures/world-kinds` are hand-written test fixtures.
- Only the ground storey of a structure is walked inside.
- Roads and parking are drawn as surfaces and kept clear; nothing drives in a site world. Water is
  never walked, and nothing moves on it.
- A kind's sample worlds house at most 128 people and lay at most 962 walking places, the bounds
  a living society's tick was measured on in towns; a site near them (879 places, 128 people)
  ticked within a town's in the same run (`scripts/measure_living_site.py`), measured on a loaded
  development machine, so the figures compare the two rather than state either's time on a quiet
  one. A site is at most 256 m on a side.
- One kind worker process serves the whole server, so one workspace's slow kinds can keep
  another's waiting until its own jobs finish, within the bounds above.
- An edit of a site world whose society's last input carries no place (its people were
  unavailable), or was made from another snapshot, needs the place from the worker: it is answered
  503 `kind_work_*`, and not made, until the worker has made that place.
- A kept kind is read again with the catalogs this server holds; a world of a kind regenerates
  from the kind document its receipt carries, read with those catalogs too and laid out again
  within the layout budget, so a later bound that refuses the document, or a lower budget than its
  layout needs, makes the world unreadable by name. Withdrawing a kept kind is not offered.
