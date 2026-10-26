# World kinds

A world kind states a kind of place people can live in (a farm, a building site, a cafe) as one
typed, versioned document. This contract owns that document, the checks that admit it, the site
grammar that generates a world from it, the society such a world holds, the receipt that keeps
it, the drawing it serves and the routes that list, keep and make worlds of kinds. The town keeps
its own generator; the [grammar contract](grammar-package.md) owns the city stages, and
[decision 0029](adr/0029-a-world-kind-is-data-a-site-grammar-realises.md) records why a kind is
data that one grammar realises rather than code per kind.

Contents: [the document](#the-kind-document), [roles](#engine-roles-and-look-roles),
[declared requirements](#declared-requirements-and-structural-classes),
[checks](#checks), [the site grammar](#the-site-grammar), [people](#people-in-a-site-world),
[the receipt](#a-world-made-from-a-kind), [the drawing](#the-drawing),
[storage and routes](#storage-and-routes),
[a world from a sentence](#a-world-made-from-a-sentence), [the town](#the-town-as-a-kind),
[limits](#limits).

## The kind document

Profiles `exulanica.world-kind/v1` and `exulanica.world-kind/v2`, read by `read_kind` in
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
| `bounds` | Optional, in both profiles: `{"version": 3}`, the bounds catalog the kind is read, sampled and regenerated with. Absent, a kind is read with its profile's own (version 1 for `exulanica.world-kind/v1`, version 2 for `v2`), exactly as every kind written before the key existed |

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
people passing, to 12 m. [Version 2](../assets/catalogs/world-kinds/kind-bound.v2.json), which a
kind with requirements is read with, allows taller and thicker boundaries and bounds a fixture's
height on its own, from 20 mm; [version 3](../assets/catalogs/world-kinds/kind-bound.v3.json) is
version 2 with more storeys, and is read only for a kind that names it. A world's receipt names
the digest of the bounds its kind was read with.

A **form** says how the generator lays a part out and draws it: `path`, `area`, `structure`,
`room`, `fixture` or `boundary`. A **placement** says where a zone lies: `front`, `middle` and
`back` beside the spine, `left` or `right` of it, or `edge_back` across the far edge on a cross
path. A **pattern** says how a zone or a room lays out what it holds: `fill`, `row`, `grid`,
`scatter`, `perimeter`, `cluster`, `centre` or `back_wall`. A zone with `closed` access is one
people never enter, such as a crane's reach.

**An arcade.** A structure part may state `arcade`, `{"bays": n, "depth_mm": d}`, in both
profiles: its front divided into `n` equal bays with an open arch in each, and a covered walk `d`
deep behind the arches that people walk along and through, with the structure's door in the wall
at its back. With `"sides": 2` its back is an arcade too, with its own covered walk and a door at
that walk's back, so the ground storey is open on both long sides, as a hall with an aisle on each
side is. Absent, a structure reads and is laid out exactly as before. The
[arcade catalog](../assets/catalogs/world-kinds/structure-arcade.v1.json) bounds the figures and
states the ones every arch is laid out with, each with its reason: 1 to 24 bays, a walk 2 m to
12 m deep in whole modules, 800 mm piers, an arch's head 600 mm under the ground storey's ceiling
and an arch at least 1,500 mm wide.
[Version 2](../assets/catalogs/world-kinds/structure-arcade.v2.json) keeps every entry of version
1 and adds `sides` (1 or 2); it is read only for a kind whose arcade states its sides, and every
arcade of such a kind is laid out by it. An arcade may also name a `use_class` people stand under
its arches by, furniture people visit (`kind_role_unmet` otherwise, `kind_reference_unknown` for
one the kind and the routine do not state), and `stands_per_bay`, how many stand in each bay of
each covered walk, which needs a use class;
[version 3](../assets/catalogs/world-kinds/structure-arcade.v3.json) adds `stands_per_bay` (1 to
4, its least where the kind states none) and is read for a kind whose arcade names either. A structure with an arcade takes a role or rooms, since its
walk leads to a door (`kind_role_unmet`), and a ground storey high enough for a door's 2,100 mm
under an arch's head (`kind_out_of_bounds`). The catalog is read only for a kind that states an
arcade.

**Values.** A person, a model choosing values for them and an API client ask for a world the same
way: a preset and, optionally, values for its parameters. `KindDocument.values` holds each value to
its parameter's range and step and refuses by name with the specification's codes
(`specification_value_unknown`, `specification_value_out_of_range`); it never clamps. An unknown
preset is `unknown_world_recipe`.

## Declared requirements and structural classes

Version 2 adds `requirement_source` (`sha256` of the sent description and its character count)
and one to 48 `requirements`. Each requirement has a minted `key`, integer `source_span`
(`[start, end]` in that description), `status` (`fulfilled` or `omitted`), `omission`, expected
`form`, `roles`, `look`, `shape_class`, `roof_form`, `minimum_count` and target `parts` keys.
These fields retain no copied source text. For a drafted kind the source digest must match
`provenance.words_sha256`; an uploaded kind's unavailable original text cannot be verified.

A fulfilled claim has targets and no omission reason, and declares at least one constraint.
Every target must exist, be placed and meet every declared constraint. Its guaranteed total
quantity includes nested rooms and fixtures and uses each count span or parameter's minimum,
across all allowed worlds. An unplaced water part or a shed labelled harbour cannot satisfy a
claim expecting an area with the `water` role. A campfire claim expecting `fixture` and
`fixture.campfire` cannot be satisfied by a building. An omitted claim has no targets and one
reason: `unsupported_geometry`, `unsupported_layout`, `unsupported_behavior`, `unavailable_asset`
or `outside_bounds`. The checks validate declared claims, not whether a model extracted every
requested requirement or chose sufficiently specific constraints.

A version 2 structure or boundary may declare `shape_class`: a reference with `key`, catalog
`version` and exact `sha256`. The structural catalog and its checker apply numeric constraints to
all parameter and span endpoints. A class is independent of a part's label. Its defaults are
resolved while compiling a brief; saved parts retain their resolved figures and pinned class.
Both flat and gabled roofs remain supported; an explicitly declared roof requirement is checked.

| Class | Authored default | Supported operating range |
| --- | --- | --- |
| `fortified_residence` | 20 x 20 m, five 3 m storeys, flat roof | Each side 8 to 40 m; total height 12 to 36 m; height divided by shorter side 0.5 to 4 |
| `defensive_wall` | 5 m high, 1.5 m thick | Height 3 to 10 m; thickness 1 to 3 m; no battlements or wall walk |

These are authored operating ranges, not universal definitions. English Heritage describes
[Middleham's keep](https://www.english-heritage.org.uk/visit/places/middleham-castle/history/description/)
as about 15 m high, 24 m wide and 32 m deep, and
[Dunstanburgh's mantlet](https://www.english-heritage.org.uk/visit/places/dunstanburgh-castle/history/)
as 6.5 m high and 1.3 m thick. Those examples support representative proportions without making
every keep taller than its footprint. A 6 m building cannot declare this fortified residence class.

Version 2 uses the second bound catalog: boundary
height extends to 10 m and thickness to 3 m; fixture height is independently 20 mm to 12 m,
while width and depth retain their 200 mm minimum. The
fixture vocabulary adds a 50 mm sleeping
mat. Version 1 keeps its original bounds and vocabulary. The site grammar and composer versions
remain unchanged; these fields establish structure and admissibility, not recognizable meshes.

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
material catalog](../assets/catalogs/world-kinds/surface-material.v3.json), so sand is drawn as sand
and adobe as adobe in any pack, and glass hides nobody behind it ([style pack contract](style-pack-contract.md), section 3).

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
`kind_out_of_bounds`, `kind_role_unmet`, `kind_requirement_unmet`, `kind_shape_unmet`.

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
thread, as a town's sample does: stage B, composing a world of a kind, generating a site
world's records again for its drawing or for the place its society walks, and drawing a site's
landscape. No site is generated on a request's thread: the reader every
other generated world's records go through refuses a site world, and a site world states no roads,
so the reads that ask a world for its roads (capabilities, the clock, traffic and the role hosts)
answer without generating it. Composing a site on a landscape realizes none of its volumes: its
landscape's drawing is a job of its own, made when the landscape routes first ask for it, so the
time its volumes take is never counted against making the world. The worker's bounds:

- a check waits at most 40 s, a world's composition 15 s, a drawing 15 s, a landscape drawing
  40 s and a place 15 s, each counted from when the worker's process starts the job: a request
  first waits out the jobs handed to the process before its own, so time queued behind other work
  never refuses it;
- work that yields to a person's (the shipped settings' ground below, warmed as an API starts where
  `EXULANICA_WARM_SETTING_GROUNDS` is on) is skipped while any job runs, and a job asked while only
  such work runs ends that process and runs at once in a new one;
- one request waits for a job; asking for a job already running is answered at once;
- at most four jobs wait besides the one running, and one workspace has at most two jobs waiting or
  running, each counting until it finishes, whoever stopped waiting for it;
- finished checks (by the workspace and the kind document's digest, 32 kept, so one workspace is
  told nothing of another's check of the same document), drawings (by the receipt's digest, 16
  kept), landscape drawings with their chunks and tops (by the receipt's digest, 16 kept) and
  places (by the receipt's digest and the place, 16 kept) are kept, so asking again reads them; a
  composed world is never kept, since each is made for a fresh identity, and its drawing and its
  society's place are kept as they are made;
- a process whose oldest job runs past 160 s is replaced, checked at every request and every
  second a request waits out the jobs before its own.

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
in each wall between two rooms. A structure with an arcade has an arch in each bay of its front
wall instead of the door (each arch its bay less a pier, centred in the bay, so a pier stands
between two arches and half a pier against each end wall), the covered walk behind the arches,
and its door in a wall across the walk's back; its rooms stand behind that wall. An arcade on both
sides repeats the arches, the walk and the door along the back, its rooms between the two walks,
and its zone keeps a lane clear behind it (a zone too shallow for that lane is refused by name).
An arch narrower than the catalog's least opening, or walks that leave less than a room's depth
between them, is refused by name. Nothing is drawn from the seed for an arcade. What does not fit
is refused by name, never shrunk.

It writes `site.extent`, `site.path`, `site.zone`, `site.area`, `site.structure`, `site.room`,
`site.wall` and `site.fixture` records and, for a structure with an arcade, `site.loggia` (the
covered walk's rectangle and its bays, owned by the structure), every figure in integer
millimetres in the site's frame (x east, y north, from the south-west corner); a structure open on
both sides has two, its front walk ordinal 0 and its back walk ordinal 1. A wall's openings are
doors, gates and arches. A structure without an arcade has exactly the records it had before
arcades existed, so every world made before them regenerates to its plan and output digests
(`tests/test_site_pinned.py`).

## People in a site world

The site place producer
([`society_site_place.py`](../exulanica/world/society_site_place.py)) turns a site's records into
a society place (`society-place` version 2): a walking lattice over open ground and corridors that
stays clear of every blocker, doors into structures, rooms, fields reached at their access point,
fixtures with places along their fronts, and the kind's homes, workplaces and shops as
destinations. A structure with an arcade is walked through: its covered walk is open ground, a
line of places runs along its middle, each arch joins the zone's ground to that line through the
arch, and the structure's door, at the front walk's back, is reached from the walk; a back walk
is walked the same way from the ground behind the structure. Where the kind names a use class
for an arcade, each covered walk is a destination of that use, outdoors, its subject the walk's
record (`site.loggia`), with standing places along the walk's middle at each arch, the
routine's standing spacing apart; the society records each such arcade's use class and standing
places per bay in the receipt's society (`arcades`, absent for every kind that names none). A fixture is
approached from its front; where something the layout set within its
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
city's `city_place`. The living engine is `exulanica-society/v5`, unchanged. A site world holding a
thing its author placed when its people are brought in is a society of things,
`exulanica-society/v7`, over `exulanica.society-input/walking-surfaces-v3` with the same navigation
profile and place dependency; that input carries no place. The
[society contract](synthetic-society-contract.md) owns inputs and engines. A site world's society
ground is the society ground catalog's `generated_site` entry. The page hosts
a site world's people in the site's frame, as it hosts a town's. The place a site world's society
walks is made in the kind worker from the world's receipt, never on a request's thread, and kept by
the workspace, the receipt and the place; the place the world's checks built is kept when the world
is made. Nothing waits for the worker inside a transaction:

- **Bringing people in** asks the worker for the place before its transaction begins, holding no
  lock, and waits for it at most 15 s; inside the transaction the place is only read from what the
  worker keeps.
- **Each later input of a living society**, such as one an edit composes, is composed from the
  place the society's last input carries (held to its `site_place` digest, the world's snapshot,
  which names the receipt, and the routine the receipt names), so such an edit never asks the
  worker.
- **Each later input of a society of things** is composed over the place the worker keeps, since
  its inputs carry none. An authored edit asks the worker for it before the edit's transaction
  begins, holding no lock, and waits at most 15 s, as bringing people in does; a server that
  started again, or whose kept places turned over, makes the place then and the edit is made in
  the one ask.
- **An erased creature's telling** composes such an input too
  ([things](things-contract.md)). The erasing request asks for the place before each telling,
  within what is left of the telling's budget. A minute that tells a society nobody reached (a
  step, a manual step, a playback round) asks for it only once it has met the missing place, waits
  at most 15 s, and tries once more: a step is answered in the one ask, and a playback round goes
  on playing. A place still not made is answered 503 with a `Retry-After` by both step routes and
  pauses a playback round as any input that cannot be composed does.
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
("Farmhand on this farm, invented for this world.", "walking across the farm"), served with the society's
places as `place_words`. A world's saved entry serves `society_engine`, the engine its people are
brought in with, which the page reads rather than deriving from the entry's shape.

## A world made from a kind

The site-plan composer ([`site_plan.py`](../exulanica/world/composers/site_plan.py)) makes a world
of a kind for the world's own identity: it tries the kind's seed candidates in order and keeps the
first whose site is laid out and meets every need above. The world is one region,
`region:generated`, whose frame is the site's own. A person arrives on the spine 4 m in from the
entry, facing into the site; on a placed volume's top, on the open top just outside the gate,
facing the site through it ([landscape contract](landscape-contract.md#a-site-on-a-volumes-top)).

The receipt (`world_generation_receipt`, the same profile a town's uses) names the composer
`site-plan` and carries:

- the **whole kind document** and the values, so the world regenerates from its receipt alone and
  no later version of a kind, in a workspace or in the library, moves it;
- the site grammar and its descriptor digest, the plan digest and the generation's output digest,
  which hold the world;
- the kind catalogs' digests, as provenance: an edit to a catalog that leaves the plan and records
  as they were does not unmake the world; a world of a kind that states an arcade also names the
  arcade catalog's (`structure-arcade`), of the version its arcades are laid out by;
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

A site world without an explicit support attachment serves `exulanica.site-drawing/v1`, made from
the records its receipt generates again ([`site_drawing.py`](../exulanica/world/site_drawing.py)):

- **slots**, one per drawn piece: a stable identity (the record's subject identity, with the piece
  it names for walls, lintels, doors and roofs), the look role, the base centre of its box, its
  quarter turns, its box, its front (+y of the slot), its family's fit, the engine's own primitive
  (`box`, `plane`, `gable` or `none`) and, for a surface, a UV frame at physical scale. Surfaces lie
  a few millimetres apart by kind (ground, zone, path, area, floor), so none fights another for the
  same pixels. A slot that is a piece of a building (its walls, lintels and doors,
  its roof, its rooms' floors and the fixtures in its rooms) states `structure`, the identity of
  the building's own slot, so a pack that fills that slot with one piece for the whole building
  can show or hide the building's own pieces together; a slot of no building states none. A
  building's own slot also states its storey height (`storeyHeightMm`), of which its height is a
  whole number, so what dresses its walls, such as a facade's rows of windows, follows its
  storeys; no other slot states it, and a reader given a drawing without it uses its own default.
  A building with an arcade states on its own slot how many bays its front has (`arcadeBays`) and
  how deep its covered walk is (`loggiaDepthMm`), together, and `arcadeSides` 2 when its back is
  an arcade too, so what dresses it draws its arches where people walk through them; every other
  building states none of them. An arch is open under its
  lintel, with no door slot, and the covered walk shows its zone's ground;
- **walk**: the floor a person exploring stands on and the boxes they keep out of (wall pieces,
  blocking fixtures and water);
- **seats**: each seat's height;
- the kind, the extent and enclosure, and the arrival.

A site created with admitted support authoring serves `exulanica.site-drawing/v2`. It carries the
same slots and a source-bound support adapter: the sealed network, place digest, node-to-surface
bindings and declared entry surface. The browser reads both versions. Its version 2 person consumer
binds the recorded 340 mm radius and 1800 mm height, draws additional horizontal support tops at
exact dimensions, and carries explicit surface/connection state through accepted swept movement
and recovery. It does not select a floor from overlapping meshes. Reopening starts at the declared
entry. [Canonical support and connectivity](world-composition-contract.md#canonical-support-and-connectivity)
owns the geometry, state rules and outstanding inhabitant, elevated-object and transit limits.

A site made on land (composer version 5, [landform contract](landform-contract.md#sites-on-land))
serves `exulanica.site-drawing/v5`: the version 1 slots, each standing at the graded land's height
under it, a pond's water at its level, the site's ground, zones, paths, dry areas and boundary walls
marked `drape` (each point of a draped slot as far above the land under it as its base stands above
the land under its base's centre), the arrival at its height, and a `land` section naming the
land's digest, each chunk's place and digest, the backdrop's digest and the water over the land,
and, for a site made under land rules 5 or later, the retaining walls where its levels meet
(`walls`, an optional field; [landform contract](landform-contract.md#sites-on-land)). The chunks
and the backdrop are served by those digests. Every earlier version is unchanged. The
application reads version 5: it holds each chunk and the backdrop to the digest the drawing names,
lays each draped slot on the land, draws the land in place of the site's base ground and the
look's ground beyond, out to the backdrop's horizon, draws the walls the section lists, and stands
the site's people and things on it.

A site made on a landscape (composer version 6, [landscape contract](landscape-contract.md#a-site-on-a-landscape))
is laid out on the landscape's land exactly as version 5 lays it out and serves the same
`exulanica.site-drawing/v5`; its land routes serve as version 5's do. Its landscape's volumes stand
off the site and are named by their own drawing, `exulanica.landscape-drawing/v1`, served beside
the site's. The application draws them round the site in rock
([landscape contract](landscape-contract.md#readers-in-the-browser)).

A site made on a placed volume's top (composer version 7, [landscape
contract](landscape-contract.md#a-site-on-a-volumes-top)) serves `exulanica.site-drawing/v6`:
version 5's slots, drape and arrival standing on the volume's graded top, and a `top` section in
place of `land` naming the graded top by digest (`exulanica.site-top/v1`, served by
`GET /world/versions/{version_id}/land/top`), the landscape and placement, the site's corner in the
volume's frame, the water on the top and the cells drawn as land. It has no land chunks or
backdrop. Its landscape is drawn as `exulanica.landscape-drawing/v2`, with the land below the
volume served by digest. The application reads version 6, draws the graded top as land on the
island and the landscape round it with the land below
([landscape contract](landscape-contract.md#readers-in-the-browser)).

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
a slot the pack does not dress keeps its primitive and fallback colour. On version 1, a person
exploring stands on the floor and nowhere beyond it; blocker and keep-out boxes are obstacles
checked with the society's 340 mm walking radius, so a person comes into a building through its
door. On version 2, the canonical support network supplies the surfaces, solid clearance and
explicit small-step connections. The About panel says
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
stages. A shipped kind may start on a setting ([landscape contract](landscape-contract.md#settings)):
a world of it made with no land, landscape or support of its own stands on that setting's
landscape, the shipped document only, never a workspace's kind of the same key.

| Route | Permission | Behaviour |
| --- | --- | --- |
| `GET /worlds/kinds` | world read | The town, every shipped kind and the workspace's own kinds, each with its parts, parameters and presets in plain words, and whether this caller may draft a kind of place here |
| `POST /worlds/kinds/drafts` | world write and model invoke | Starts a draft of a kind of place from a description (1 to 1,000 characters; a body over 16,384 bytes is refused 413 before it is read) and answers 202 with the draft at once; before anything is spent, 503 without a model credential, 429 `budget_exceeded` with its `spending` member when the workspace's allowance for the drafting model is spent and 409 `kind_cap_reached`; 409 `kind_draft_busy` while this workspace runs a draft, naming its `draft_id` only to the person who started it; 429 `kind_draft_limit` with a `Retry-After` when the caller has started 12 drafts in the last hour; 503 `kind_draft_capacity` with a `Retry-After` when the server runs as many drafts as it may |
| `GET /worlds/kinds/drafts` | world read | The caller's drafts the server still holds in this workspace, newest first |
| `GET /worlds/kinds/drafts/{draft_id}` | world read | The draft's state: drafting, ready with the kept kind, or refused by name; 404 `kind_draft_unknown` for an id the server does not hold for this caller in this workspace, another person's draft included |
| `POST /worlds/kinds` | world write | Keeps a creator's kind (origin `uploaded`, at most 65,536 bytes; a body over 131,072 bytes is refused 413 before it is read) once both stages pass; 422 names the refusal and writes nothing; 409 `kind_version_exists` or `kind_cap_reached`, asked before any sample world is built; 503 when the worker cannot answer in time |
| `POST /worlds/kinds/{kind}/worlds` | world write | Makes a world of a kind with a preset, values and a title, and saves its entry; the latest version unless one is named; a body over 16,384 bytes is refused 413 before it is read; 503 when the worker cannot answer in time |
| `GET /world/versions/{version_id}/site` | world read | The drawing, served only to the world whose snapshot names its receipt, with its digest as the entity tag; made in the kind worker and kept, 503 with a `Retry-After` while it cannot be |
| `GET /world/versions/{version_id}/land/chunks/{chunk_x}/{chunk_y}` | world read | One chunk of a site's graded land (`exulanica.landform-chunk/v1`), with its digest as the entity tag, made and kept with the drawing; 404 `land_unavailable` for a level world, 404 `land_chunk_unavailable` for a chunk the land does not hold |
| `GET /world/versions/{version_id}/land/backdrop` | world read | The site's land drawn to the horizon (`exulanica.landform-backdrop/v1`), with its digest as the entity tag; 404 `land_unavailable` for a level world or a world on a volume's top |
| `GET /world/versions/{version_id}/land/top` | world read | The graded top a site on a placed volume's top stands on (`exulanica.site-top/v1`), with its digest as the entity tag, made and kept with the drawing; 404 `land_unavailable` for a level world or a world on land |
| `GET /world/versions/{version_id}/land` | world read | A town on its land's land section (`exulanica.town-land/v1`): the digests of its chunks and backdrop, served by the two routes above, and its water, with its digest as the entity tag, made in the kind worker and kept by the town's receipt ([landform contract](landform-contract.md#towns-on-land)); 404 `land_unavailable` for a town on level ground, 404 `unknown_reference` for any other world |
| `GET /world/versions/{version_id}/landscape` | world read | A site on a landscape: its landscape drawing (`exulanica.landscape-drawing/v1`, or `/v2` for a site on a volume's top), with its digest as the entity tag, made in the kind worker after the site's drawing and kept, 503 with a `Retry-After` while it cannot be; 404 `landscape_unavailable` for a world on no landscape |
| `GET /world/versions/{version_id}/landscape/chunk?sha256=` | world read | One chunk of a placed volume's surface (`exulanica.volume-chunk/v1`) the landscape drawing names by that digest; 404 `landscape_document_unavailable` for a digest it does not name as a chunk |
| `GET /world/versions/{version_id}/landscape/top?sha256=` | world read | One walkable top of a placed volume (`exulanica.volume-sheet/v1`) the landscape drawing names by that digest; 404 `landscape_document_unavailable` otherwise |
| `GET /world/versions/{version_id}/landscape/ground?sha256=` | world read | A world on a volume's top: one chunk (`exulanica.landform-chunk/v1`) or the backdrop (`exulanica.landform-backdrop/v1`) of the land below it, which its landscape drawing (`exulanica.landscape-drawing/v2`) names by that digest; 404 `landscape_document_unavailable` otherwise |

Making a world answers 404 for an unknown kind or preset, 422 for a value the kind does not offer
(naming the key, the value and the range) or an empty title, 422 for a `land` document the landform
catalog refuses (naming its `path`) and 422 `landform_not_served` for land asked with a support
declaration or of the town where the deployment makes no worlds on land (`EXULANICA_WORLDS_ON_LAND`),
422 for a `landscape` document refused by its readers or that does not fit its site (naming its
`path` and code, [landscape contract](landscape-contract.md#refusals), a kind whose people come
from homes off the site or a site off a volume's top or its rock among them) and 422
`landscape_not_served` for a landscape asked of the town or beside land or a support declaration,
409 with every refusal when no candidate makes a world people can live in (on land, when no
candidate's layout the land can take; a town on land tries one identity), 409 when the workspace holds as many generated worlds
as the count policy allows, and 403 `worlds_read_only` when the deployment's database role cannot
register a world. Nothing is written when any is refused. A stranger is told a world does not
exist, as for every world route. The browser offers no upload: keeping a kind is the API path a
creator or an agent uses.

## A kind drafted from words

The kind drafter ([`kind_drafting.py`](../exulanica/selection/kind_drafting.py)) asks a model to
fill a **brief** ([`kind_brief.py`](../exulanica/selection/kind_brief.py)) for a person's
description: zones holding their structures, rooms, areas and fixtures, each part's use stated
where it stands, with no key, and every closed word a list the form offers. Version 7 of the
drafting prompt adds copied requirements and exact part labels as their targets. Code
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

Fixtures may use the authored dimensions of a named leaf in the
fixture vocabulary. The transient brief's `size_source`
is `catalog` to use that leaf's box, or `stated` to keep its own dimensions. A request for catalog
sizing with an unlisted look is refused and repaired; an unlisted leaf with stated dimensions
remains valid. The compilation trail counts defaulted and unlisted fixture parts. These are
authored placement defaults, not measured assets or evidence of visual resemblance. Roles and
uses still govern behavior. The catalog grants no boat movement or crane operation.

The drafting instructions include the vocabulary's exact file digest and dimensions; the existing
`prompt_version` and `prompt_sha256` provenance bind those inputs. The saved kind contains resolved
figures. Replay reads those figures without consulting the fixture
vocabulary, so changing it cannot resize an existing world.

The compiler resolves each requirement's `part_labels` uniquely to part keys; missing or ambiguous
labels are refused. A phrase absent from the sent description, or cutting a replaced saved name,
is refused and repaired. Version 7 compiles world-kind/v2, with the text-free requirement records
above. `shape_source` chooses stated or catalog structural dimensions; `roof_form: catalog`
resolves a class default only when no explicit roof is chosen. Sizing must still meet the class
and requirement checks. The sentence answer reports omitted source phrases through `left_out`;
an overlapping appearance or setting phrase cannot hide a content omission. Published prompts
5 and 6 keep their forms and instructions: v5 has no fixture defaults, v6 uses vocabulary v1 and
transient `not_supported` phrases, and both compile world-kind/v1. Version 7 has deterministic
contract coverage, without live-model or visual acceptance evidence.

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
with the draft's id, and never waits on the model: a durable job claimed by an API worker drafts on the
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
| `refused` | "These words did not draft a kind of place people can live, walk and work in: {sentence} Try describing it another way." ({sentence} the refusal's `detail`, a fixed sentence from the refusal catalog; where no check refused, the refusal's `check` is null and the page says the two sentences without it, since the drafter's own sentence would repeat the first) |

A refusal that is not the drafted kind's (`budget_exceeded`, `kind_draft_unanswered`,
`kind_draft_model_failed`, `kind_work_unavailable`, `kind_draft_failed`, `kind_cap_reached`,
`kind_version_exists`) is said in the closed list's words. A model that did not answer within the
role's timeout is `kind_draft_unanswered`; a provider's error status, a connection that failed or a
call refused before it was sent is `kind_draft_model_failed`, never said as the model's silence.
Ready and refused carry what the drafting cost, every call made included, except a draft ended for
running past its deadline, whose calls the server no longer reads. Saved names are replaced in the
words when the claimed job prepares its request, and the workspace's rules, releasing no place's name, are applied again
as each request leaves. A draft takes at most the longest its client takes for one call of the role
and the checks' bound, for each of its three attempts. Making a world of the kept kind is
`POST /worlds/kinds/{kind}/worlds`.

## A world made from a sentence

A person says the world they want and it is made, with no kind, preset or value met on the way.
`POST /worlds/drafts` (world write and model invoke) takes the words (1 to 1,000 characters; a body
over 131,072 bytes, including operation metadata, is refused 413 before it is read) and answers
202 with a durable draft and request id at once;
`GET /worlds/drafts/{draft_id}` (world read) is polled. A job in the API process
([`world_making.py`](../exulanica/api/world_making.py)) does three things and says which it is at:

| State | What the job is doing |
| --- | --- |
| `queued` | The accepted durable job waits for a native drafting slot |
| `choosing` | Asks which tool should make the place: a forced choice among the entries of the [world tool catalog](../assets/catalogs/world-tools/world-tool.v1.json), each a composer with its drafter and its own words for what it can make and what it cannot, which is all the chooser is shown ([`tool_choosing.py`](../exulanica/selection/tool_choosing.py), role `world_tool_chooser`). Where the chooser answers none, is refused twice or fails, the catalog's tool for an unsure choice is taken, the site grammar's, and the answer says so (`tool.chosen_by` `unsure`) |
| `drafting` | That tool's drafter writes what its composer takes: the kind drafter a whole kind document, held to both stages of the checks as above, or the specification drafter a town's preset and values, held to the gate every town passes. Then two short steps ask what the same words say of how the world is drawn and where it stands: the look chooser among the library's looks and the setting chooser among the named parts of a setting ([the setting offer](style-pack-contract.md#121-a-setting-offered-from-a-description)). Neither can fail the draft |
| `making` | The world is composed and its entry saved, as `POST /worlds/kinds/{kind}/worlds` and `POST /worlds/generated` make one. Where the deployment makes places on land (`EXULANICA_WORLDS_ON_LAND`, on unless set off), a place or a town is composed on the land its words, its setting or the default name, or on level ground where no layout of it fits that land ([landform](landform-contract.md#land-for-a-world-made-from-a-sentence)) |
| `ready` | `entry` is the saved world; `look` and `setting` are what the job took from the words, each with the person's own words that chose it, or null; `made` lists every part that was made, with its words, form and look role, how many slots the world's drawing draws for it and the largest box among them (a town's parts state none); `left_out` the phrases of the description nothing in the made world says, in the person's own words; `land` the land a place or a town stands on: its `recipe` and `title`, `chosen_by` (`words`, `setting` or `default`), the person's own `words` that chose it, and `fell_back` where no layout fitted it and the world was made level; null where the deployment does not make worlds on land |
| `refused` | `refusal` names why by code and sentence, and no world was written. `refusals` lists every code of the draft's own routes and job with what each means; a refusal by the composer or by a town's values carries that check's own code and sentence |

Ready and refused both carry what the draft cost, every call included. A world that was made
always ends `ready`: nothing that happens after its making reports it as not made. A start may
name web notes to draft with (`reference_id`): a town's drafter is handed them, any other place is
drafted from the words alone, and `references` says which
([reference notes](reference-notes-contract.md#9-notes-for-a-drafter)). A further
generator is one more entry of the tool catalog and no change to the choosing.

**Before a word is typed.** `GET /worlds/drafts` (world read) says what a start would meet, for
this person in this workspace: `offered`, or the first refusal a start would give by `code` and
`detail`, in the order the start asks them; `calls_at_most`, the most times one draft asks a model,
including schema repairs, transport retries, declared fallbacks and both native tool paths;
`operation`, a sealed monetary reservation ceiling derived from fresh provider metadata, with
per-provider bounds, individual model rates, response digests and expiry. Its basis is
`request_envelope_ceiling`: each request is priced at its role's request envelope of input
(`assets/catalogs/request-envelopes/`, the most bytes its escaped JSON may hold, schema and repairs
included, never more than the model's context window), which each stage states as
`request_bytes_at_most`, and its answer limit; the draft's chain refuses any request beyond either
before sending it, so the ceiling is the worst case the draft can reach. A quote priced before
envelopes keeps its whole-context basis (`full_context_reservation_ceiling`) and is held to it.
The operation also states `step_usd_at_most`, overall and for each provider: the dearest single
request of any stage at its worst case, the least an allowance must leave for a draft to send
anything;
`left_usd`, where the workspace's own allowances have less left than the operation's
`maximum_usd`: what they have left for it (each provider's at most its ceiling, summed), the most a
draft started now may spend;
`starts`, the hourly
allowance and starts left for this actor across workspaces and API processes, counting both native
kind and whole-world starts;
`description_characters`;
`running_draft_id`, this person's own draft of a world still running here; and, where the host
states one (`EXULANICA_HOST_KEEPS_UNTIL`), `host_keeps_until`, the day it keeps what is made on it
until, which the page says under the field; `notes`, where a draft is offered, whether web notes
may be asked for with it, the most searches they send and the most their two model calls may add
([reference notes](reference-notes-contract.md#9-notes-for-a-drafter)); and `own_key`, true on a person's own install
(`EXULANICA_PERSONAL_INSTALL`), whose models run on its owner's key, so the page's price line names
that key ("with your Nebius key"), false on a shared server, where a server's budget pays. A page shows the calls
and the starts before the words are sent. Another person's running draft is `kind_draft_busy`
with no id. Every refusal that is known before a model is asked is answered by the start before
one is, so nobody is charged to be told no: the server's switch, a missing model credential, an
allowance that admits no attempt (429 `budget_exceeded`), an allowance with less left than one
step of the draft (409 `world_draft_bound_exceeds_left`, with `left_usd`), a workspace holding as
many generated worlds as it may (409 `world_limit_reached`), and a database role that cannot
register a world (403 `worlds_read_only`). An allowance with at least one step left but less than
the operation's most is offered: the draft holds each step as it is sent and stops where what was
left runs out. The world limit is asked again where it holds, as the world is
registered. A draft cannot be withdrawn once started: it runs to its end, one at a time in a
workspace.

**The look and the setting are taken, not offered.** The town's own draft
(`POST /worlds/specification/drafts`) offers what the two steps chose and the person picks. This
job has no second screen, so it takes what the words asked for, says what it took and in whose
words, and names it in the made world's appearance as `POST /worlds/generated` names a town's: the
look that was taken or else the library's default, with the parts of the setting composed for that
look. A person changes either afterwards in the world's appearance. Because nobody picks, the job
holds the steps' answers to a stricter rule than an offer: a part invented is worse than a part
missed. The parts of a setting are taken only when the answer copied at least as many phrases as it
names parts, and otherwise none is taken, since one list of phrases serves all three axes and one
phrase can carry a part for each; and a look is not taken when every phrase that chose it overlaps
a phrase that chose a kept part of the setting, since words about the hour or the weather ask for
a sky and not for a look. The rule counts phrases and binds none to an axis, so it bounds an
invention and does not prove each part. A step that fails, is refused or runs out of allowance
takes nothing, and the world is made in the default look. A setting the look cannot be drawn in is
left off. A made world's setting reaches a page through its appearance, whose setting states its
named parts (`parts`, each an `axis` and a `key`).

**Where a server keeps a kind from a person.** A kind of place a person brings is the person's
own document, drafted from their words or written by them, and it is kept in rows no removal
reaches. A server takes one only where its deployment says so (`EXULANICA_KINDS_FROM_PEOPLE=on`,
[deployment](deployment.md)). Elsewhere every route that would keep one answers 403
`kinds_from_people_not_offered` before anything is drafted, built or written, and
`GET /worlds/drafts` and the library's `drafting` say so. The setting refuses only a request that
would otherwise be taken: a body that is no description or no kind is refused for itself first
(422), and a kind nobody keeps is unknown (404), as on any server:

| Route | Covered | What it keeps of a person's |
| --- | --- | --- |
| `POST /worlds/drafts` | Yes | The drafted kind document in the made world's receipt, and what the table below lists |
| `POST /worlds/kinds/drafts` | Yes | The drafted kind document as a version the workspace keeps (`world_kind_version`) |
| `POST /worlds/kinds` | Yes | The uploaded kind document as a version the workspace keeps |
| `POST /worlds/kinds/{kind}/worlds` | Yes, for a kind the workspace keeps | That kind's whole document once more, in the made world's receipt. A world of a shipped kind or of the town is made either way |
| `POST /worlds/specification/drafts` | No | Nothing: it answers a proposal and writes no row, and the town a person then makes from it holds a preset and values |

**No kind is kept.** A place made this way appends nothing to the workspace's kinds: its receipt
carries the whole kind document, so the world regenerates from its receipt alone, and the kinds a
workspace keeps are the ones a person chose to keep. The draft runs under the same holder and the
same three budgets as a kind's draft; while one runs in a workspace the other is answered 409
`kind_draft_busy`. Only the person who started a draft reads it, and only through this route.

**Durable confirmation and readback.** Workspace Companion preparation
(`POST /selection/world-drafts/prepare`, world read) returns a digest-bound proposal with one
explicit native `POST /worlds/drafts` step and the operation ceiling. Preparation creates no job
and asks no model. The native POST requires world write and model invoke, rechecks the quote,
opens one durable bound for each of the quote's providers, and enqueues the existing world maker.
Each bound is the lesser of the quote's ceiling for that provider and what the workspace's grant
there has left at the start, so the bounds sum to at most the accepted total. The definition stores
them (`funding`), so a start recovered after its process stopped opens exactly those bounds. Every
attempt is admitted against its bound at its own worst case as it is sent. Where a bound no longer
covers the next attempt, that attempt is refused before it is sent and the draft ends refused with
what it spent (`budget_exceeded`, its `spending` member naming `spending_limit_reached`); nothing is
spent past what was left. Missing prices, changed configuration or an inactive worker are named
refusals. The ceiling prices each request's envelope and its answer limit; it is not expected spend
or an invoice. A draft's read states `funded_usd`, the most it may spend: its bounds' ceilings summed.
`accounting` reads actual reservations, reported charges and unknown liability separately.
`execution` names served models only where a response supplied that identity.

An explicit `idempotency_key` binds the actor, workspace, description and accepted quote terms.
The same key and terms read the same request without inference; changed terms are refused.
Description-only callers receive a fresh server key for every accepted POST and cannot use
same-key replay without preserving that identity. Native kind and whole-world starts share durable
workspace concurrency and actor hourly limits across API processes. The offer is advisory; the
start checks both limits atomically. Minimal start identities and timing remain after draft content
is erased, so deletion does not replenish the hourly allowance.

A worker reclaims an interrupted job without asking it again. If its fixed world identity already
has a saved entry, readback recovers that entry; otherwise it records `world_draft_interrupted`.
The native generation receipt remains the deterministic world replay source. Spending already
sent remains recorded. `POST /selection/world-drafts/outcome` reads the authoritative native
result matching the prepared request; a client-supplied success grants nothing.

**What is kept of the words.** The full sentence is stored in `world_draft_input` while work is
pending and removed when an outcome is recorded. A draft that made its world first keeps the
sentence with that world (`world_made_from`, migration 0222), so the world's History can quote
back what the person typed to make it; the draft read (`GET /worlds/drafts/{draft_id}`, for the
person who started it) answers it as `description`. It is the person's own words: read by its
workspace alone, deleted with the world's erasure or the workspace's, and never part of a world
package, a reviewer seed or a world's project: a source test holds that nothing in
`exulanica/world_package` reads it, and the reviewer seed (`exulanica-seed`) classifies its table
as one it never carries. The seed also refuses a workspace with a draft still being made, whose
input and job it would otherwise carry. A draft that made no world keeps nothing of the sentence. Progress and result records retain selected
omission/look/setting phrases for readback until world or workspace erasure. Those erasures
cancel work, delete draft content and clear its job payload; start timing and financial identifiers
remain without a content fingerprint. A backup restore reapplies those erasures and grants no
content recovery. The words are sent to the hosted models that choose and draft,
every saved name replaced first; a request already sent is beyond any deletion here. What a made
world keeps that was written from the words:

| Where | What |
| --- | --- |
| The sentence the world was made from (`world_made_from`), kept once at the draft's end | The person's whole sentence, as typed; served only by the draft read to the person who started it; erased with the world |
| The world's receipt (`world_generation_receipt`), appended once and never changed | For a place, the whole kind document: its key, label and summary, every part's and use's key and label, and `provenance.words_sha256`, the SHA-256 of the words as sent. The label and summary may repeat the words closely. For a town, its preset and values only |
| The saved entry's title (`saved_world_entry`) and the first version's title (`world_alternate_version`) | For a place, the same label with a capital first letter and the rest as written. A town's are the person's own words: their sentence as typed up to its first comma, or its first 48 characters ending on a whole phrase (a cut that falls inside a phrase goes back to before that phrase's joining word), with a capital first letter and no full stop, ending before any saved name it would hold, and cut short in any of these ways never ending on a joining word ([title-joining-word.v2.json](../assets/catalogs/world-titles/title-joining-word.v2.json): articles, prepositions, conjunctions and the like) (`exulanica/api/world_making.py` `title_from_words`); the preset's label where fewer than two words are left. Unlike the whole sentence, a title travels with the world: in a world package, a world project's checkpoint and a reviewer seed |
| The world's structure records (`world_structure_snapshot` and the element tables under it) | For a place, the document's part keys and look roles. A town's records are the city grammar's, generated from its preset, values and seed |
| A town's tile bake jobs (`job`) | Ids, a digest and a tile in each payload, and nothing of the words |
| The world's appearance (`world_style_version`) | The look's id and the keys of the setting's named parts: catalog keys, none of the person's words |
| The API process, until it restarts or the entry is the least recently read | A made place's drawing and its society's place, and the checks of a drafted document, a refused one's included: built from the document, never written to storage or to a file |
| Durable draft progress/outcome, until world or workspace erasure | A town's or site's `left_out` phrases and the phrases that chose a look or a setting, as they were typed, saved names included, read by the person who started the draft and nobody else |

World registration states that a world was generated from a world kind without repeating its
key. World removal erases its receipt, saved entry and structural rows; independently kept
library kinds remain until separately erased. Spending records retain accounting facts.
A request already sent to an outside provider is not recalled.

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
- A surface is drawn in its material's colour with its material's pattern, courses or boards or a
  grain, in colour only: it has no relief and is no photograph. The pattern is written for two
  shader languages and has run in one: every page asks for WebGL 2, and the WGSL text has run on no
  device, so a WebGPU page would be the first to run it
  ([style pack contract](style-pack-contract.md), sections 3 and 7.1). A roof is shaped by its material
  (thatch steep and overhanging, a canvas roof a tent's, an earth roof a slab with a parapet); the
  walls under it are not: every structure but a tent is a box of walls, and a tall thing standing
  near a tent's side shows through its canvas.
- Beyond an open site its ground runs out to the pack's reach, flat, with the setting it wears,
  unless the site is made on land ([landform contract](landform-contract.md#sites-on-land)).
  A sea setting changes that ground beyond the site; it supplies no water area inside it, shore
  layout or boats. Settings supply no individual trees.
- Native kind drafts keep their identity, requester, input, bounded execution metadata and outcome
  in PostgreSQL. Any API process can answer the original requester's poll; no sticky routing is
  required. Never-claimed queued work can resume within its admitted deadline plus the two-minute stale
  margin. An expired running claim
  is not sent to a model again: an atomic committed result remains readable, and unfinished work
  ends `kind_draft_failed`. Changed prompt or model-manifest pins also refuse before inference.
  The checked kind, outcome and terminal job state commit together under the live claim; a late
  worker cannot publish after cancellation or claim replacement. A provider-reported model
  identity absent from the response or outside the answering provider's admitted manifest refuses
  publication; it is retained as unavailable,
  rather than storing arbitrary provider text or attributing the result to a different model.
  The description is removed at termination. Ended views remain available for one hour; subsequent cleanup removes their
  outcome and attempt content while retaining minimal admission anchors. Workspace erasure
  cancels work and scrubs content; erasing a completed kind removes its associated draft content.
  A minimal draft identity on the kept kind survives outcome cleanup and is carried by its
  erasure record, so replay can also scrub a backup taken before the draft produced its kind.
  The [world draft policy](../exulanica/world/world-draft-policy.v1.json) owns workspace, process
  and actor budgets (one, two and twelve), with deployment overrides. Workspace concurrency and
  hourly actor starts are shared across native-kind and whole-world jobs; execution capacity
  remains a separate limit in each API process. A native-kind POST still creates a new server
  identity each time; retrying the HTTP request is not an idempotent replay.
- A world made from a sentence takes the look and setting validated from its words, or the
  host's default where none is taken. Where it stands on land, the land is one of the land
  recipes, chosen without a model by the words a recipe lists, the setting's ground part or the
  default, so a "no" more than a word before a land word is not seen. A site's draft reports only the content requirements its
  model identified as omitted; it can still miss others. An interrupted whole-world draft is
  recovered or refused without another model ask; its spending remains recorded.
- A drafted kind is kept once it passes, without a separate accept, and takes one of the
  workspace's kind versions. Its creator or workspace owner can erase an unused version through
  the erasure routes below; a retained world receipt prevents erasure.
- The library ships the town's adapter and one site-grammar kind, the island hamlet ("Hamlet on a
  sky island", `island_hamlet.v1.json`), which starts on the settings catalog's sky island over the
  bay. A world made from its card (no land, landscape or support of its own) is drawn in the
  setting parts that setting names (`landscape-setting.v2.json`: a clear noon sky) over the host's
  look: the host's default pack with those parts composed for it, named as the world's second
  version as `POST /worlds/generated` names a town's look. A world of a workspace's kind of the same
  key, or one made with its own landscape, starts on no setting and is drawn in the host's look as
  it states. The kinds under `tests/fixtures/world-kinds` are hand-written test fixtures.
- Only the ground storey of a structure is walked inside. A structure stands at most six storeys,
  or as many as bounds version 3 states for a kind that names it; every storey above the ground is
  drawn, not walked, and a taller structure adds no slot to the drawing and no place to the walk.
- Roads and parking are drawn as surfaces and kept clear; nothing drives in a site world. Water is
  never walked. A being of a society of things whose kind swims crosses it by the swimming module,
  over the lattice the site's composer lays in it
  ([movement modules contract](movement-modules-contract.md#swimming)); nothing else moves on it.
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
  layout needs, makes the world unreadable by name. An unreadable kept version remains erasable.


## Erasing a kept version

`GET /worlds/kinds/versions/{document_sha256}/removal` previews a kept version and its retained
world-receipt count. `DELETE /worlds/kinds/versions/{document_sha256}` permanently erases that
version's document and validation report. The preview requires `world.read`; deletion requires
both `world.write` and `deletion.write`. Both require the version's creator or the browser
account's current ownership of its workspace. A program's bearer grant gives no owner override.
Shipped kinds are not workspace rows and cannot be erased here. Disabling new kinds from people
does not disable erasure of an already kept version.

Every retained world receipt copying that version blocks deletion with `409 world_kind_in_use`;
remove those worlds first. Erasure never cascades to a world, another kind version or another
workspace. An unknown digest returns `404 unknown_world_kind`, a different creator without
ownership `403 world_kind_not_yours`, an erased version `410 world_kind_erased`, and a sealed
restore checkpoint `409 restore_sealed`. Successful deletion returns 204. No document parsing is
required for deletion, so a version that current catalogs no longer read is still removable.

The document digest and SHA-256 of its UTF-8 kind key, together with its version, permanently
retire both the original bytes and the original version identity in that workspace. A later
version may be kept. These retained values are fingerprints, not anonymization. The immutable
record also retains workspace, erasure, tombstone and actor identities and the erasure time;
it retains no label, summary, document, validation report or original key. Spending records
remain. Library appends cannot reuse the retired key/version or document digest. Receipt checks
match only the erased document digest: an independent inline world can use the same key/version
with different bytes, since it has no library binding. Database guards refuse a late receipt
from a composition of the erased document already in flight.

A backup restore carries this record even if the backup predates the kind. World erasures replay
first, removing any receipts that the older backup still holds, then the kind is erased again.
A surviving receipt blocks replay rather than silently deleting its world. The erased bytes and
version identity cannot be reintroduced after restore.

After commit, the serving process drops the parsed document and sample-check cache, discards
its owned kind-worker child and prevents late callbacks from refilling those caches. Other
finished worlds remain cached; other in-flight work on that shared child may retry. Associated durable kind-draft content is scrubbed in the erasure transaction. Kind publication
and draft completion share one transaction, so no intermediate kept-but-unrecorded result remains.
Other API processes retain no authoritative draft cache. In-flight publication checks the live
claim and durable retirement record; an unrelated draft whose kind has not been saved is not
mistaken for an erased one. Immediate memory erasure
across processes and recall of responses already sent are not provided. This backend API does
not add a library-removal page or enable public deployment.
