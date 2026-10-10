# Things contract

Status: **THING KINDS, BODY PLANS, ABILITIES, OFFERS, LOOKS, THE ORIGIN RECORD AND TRANSLATION
MANIFESTS ARE DATA HELD TO THEIR CHECKS, A WORLD'S AUTHOR PLACES THINGS BY THEIR KIND, THE SOCIETY OF
THINGS LIVES WITH THEM AND ITS BEINGS SAY LINES AND LEAVE BY THEIR DECIDERS' CHOICE, A CREATURE'S BODY
PLAN, SKETCH AND KIND ARE BUILT FROM A DRAFTED BODY RECIPE, A CREATURE ITS WORKSPACE KEEPS LIVES IN
THE SOCIETY OF THINGS AS A BEING, AND THE BROWSER DRAWS A VERSION'S PLACED THINGS BY THEIR LOOKS**.

A thing is anything addressable in a world: a knight, a lantern spirit, a sword, a well, a gate, a
visitor that came in from another program. What a kind of thing is and can do is one typed,
versioned, fingerprinted record, its **thing kind**. How it is drawn is a separate record, a
**look**, any look of its body may be chosen, and nothing the thing does depends on which. Where a
kind, a look or a crossing came from is one **origin record**. A new kind of thing is data held to
deterministic checks, never code of its own.

This contract owns the thing kind and its checks, the four catalogs a kind is read against (body
plans, abilities, offers and look kinds), the look, the origin record and the readers that turn
each existing origin vocabulary into it, translation manifests, the kinds and looks this
repository ships, and creatures: body plans built from a drafted body recipe, their sketches and
the drafter that asks a model for them. Who decides for a thing, including an outside program, is
the [decision roles contract](decision-roles-contract.md)'s; walking is the
[movement modules contract](movement-modules-contract.md)'s; the people a society simulates are the
[society contract](synthetic-society-contract.md)'s; objects placed in a world's authored plane are
the [world objects contract](world-objects-contract.md)'s; the look roles a style pack dresses are
the [style pack contract](style-pack-contract.md)'s; which licences may ship is the
[licence matrix](license-matrix.md)'s. [ADR-0030](adr/0030-a-thing-is-a-typed-record-whose-looks-never-reach-the-simulation.md)
records the choice and the alternatives it rejected.

<details>
<summary>Sections</summary>

- [Names](#names)
- [A thing kind](#a-thing-kind)
- [Body plans](#body-plans)
- [Abilities and offers](#abilities-and-offers)
- [Looks](#looks)
- [The origin record](#the-origin-record)
- [Translation manifests](#translation-manifests)
- [Lines](#lines)
- [The kinds and looks this repository ships](#the-kinds-and-looks-this-repository-ships)
- [Creatures: bodies drafted from words](#creatures-bodies-drafted-from-words)
- [A creature in a society](#a-creature-in-a-society)
- [A workspace's own things](#a-workspaces-own-things)
- [Drawing](#drawing)
- [What is not built](#what-is-not-built)
- [Implementation and evidence](#implementation-and-evidence)

</details>

## Names

| Term | Meaning | Not to be confused with |
| --- | --- | --- |
| thing | Anything addressable in a world | the evidence graph's `entity` |
| thing kind | What a kind of thing is and can do, `exulanica.thing-kind/v1` | a world kind, which is a kind of world |
| body plan | The semantic shape of a body: bones, sockets, size and motions, named `<key>/v<version>`; a catalog entry, or a document drafted for one workspace | a vehicle's body family in traffic |
| body recipe | The few figures a drafted body is built from, `exulanica.body-recipe/v1` | a world object's recipe of parts |
| ability | Something a thing can do, served by one ability module (`exulanica-ability/<name>/v<N>`) | a model's answering mechanism |
| offer | Something a thing lets others do to it | the society's affordances (rest, visit, stand, talk), which offers map onto |
| look | One way a thing of a body plan is drawn, `exulanica.look/v1` | a character look, which is a recipe over one catalog body |
| look kind | How a look is drawn, and which plans it fits | a style pack's look role, which one look kind draws |
| origin record | Where a piece came from, `exulanica.origin/v1` | an assertion's provenance, which says who supports a claim |
| translation manifest | What an import or a crossing kept and lost, `exulanica.translation-manifest/v2` | |
| line | One plain line of words, held to one rule wherever words are stored or said | |

## A thing kind

[`kinds.py`](../exulanica/things/kinds.py) reads a kind with `read_thing_kind`. A kind is
canonical JSON with no floats, and every object in it states exactly its keys:

| Field | Holds |
| --- | --- |
| `profile`, `kind`, `version` | `exulanica.thing-kind/v1`; a lowercase key; a whole number from 1 |
| `label`, `summary` | lowercase words, 2 to 40 letters and spaces, the words an option or a card uses ("lantern spirit"); one line of at most 160 plain characters |
| `class` | `being`, which acts and has a decider, or `object`, which decides nothing and does nothing |
| `body` | its body plan and the figures the plan bounds: a height range `{from, to}` for a humanoid, a radius for a bodiless thing, a box `{width, depth, height}` and whether it blocks walking for a rigid one |
| `origin` | its [origin record](#the-origin-record) |
| `moves` | the movement modules it moves by, each one its plan moves by; none for an object |
| `abilities`, `offers` | `[{key, parameters}]` from the [catalogs](#abilities-and-offers), each parameter within its bounds |
| `routine` | a being's routine: a whole-number weight from 0 to 10,000 for each ability the routine draws among, the kinds whose holders it prefers to follow (`follow_holders_of`) and a reason; none for an object |
| `deciders` | a being's `{default, allowed}`: the [decider](decision-roles-contract.md#who-decides-deciders-and-the-owners-choice) kinds that may run it, among `routine`, `model`, `person` and `external`, the default the routine or an outside program; none for an object |
| `looks` | at most 16 references `{look, version, sha256}`, each a look of the kind's body plan, the first the default; may be empty |
| `ext` | source data kept verbatim, at most 8 KiB of canonical bytes, which no engine reads |

A kind's identity is its key and version, and its digest is the SHA-256 of its canonical bytes; a
version never changes, and a kind that must change gets its next version beside the first. The lock
beside the kinds, `assets/catalogs/things/kinds.lock.json`, names every shipped version with the
digest it shipped with, and the kind loader refuses a file it does not name at that digest, or a
locked version with no file. A thing names its kind by all
three: a world's author places one by its kind in a version's authored plane
([world objects contract, section 14](world-objects-contract.md#14-placed-things)), a being only
where its kind's deciders allow the routine. A kind its workspace keeps (below) is placed by its
digest alone, never by its key, which a person's words may have made. What a society
is given of a shipped kind is `ThingKind.semantics()`: every field but `looks`, `origin`, `ext` and
`summary`, with the kind's reference, so no look reaches a society through its kind. What it is
given of a kind its workspace keeps is that kind's run form
([a creature in a society](#a-creature-in-a-society)), which holds no word of it.

### Refusals

A kind is refused with `ThingKindRefused`: a code, the field at fault and a sentence.

| Code | Refused |
| --- | --- |
| `thing_kind_invalid` | A key the document does not state, a missing field, a float, a malformed value |
| `thing_kind_reference_unknown` | A body plan, ability, offer, movement module or look the catalogs do not state |
| `thing_kind_out_of_bounds` | A figure outside its plan's or its parameter's bounds |
| `thing_kind_body_unmet` | An ability the body cannot serve: a hands ability on a plan with no socket, an ability that walks on a kind that does not move, any ability on an object; a routine weight for an ability the kind lacks, or for `say` or `leave` (the routine never says anything and never leaves) |
| `thing_kind_offer_implausible` | A grip outside the box; a holdable thing longer than any socket of any plan holds; a place beyond reach (1,500 mm) of the box; places on a thing with no box |
| `thing_kind_look_unfit` | A look of another body plan than the kind's, when the reader is given looks to resolve |
| `thing_kind_origin_invalid` | An origin record the origin reader refuses |
| `thing_kind_not_locked` | A shipped kind file the lock does not name at its digest, or a locked version with no file |

`shipped_thing_kinds()` reads every kind under
[`assets/catalogs/things/kinds`](../assets/catalogs/things/kinds) and refuses a file named for
another kind or version than it states.

## Body plans

[`body-plans.v1.json`](../assets/catalogs/things/body-plans.v1.json) states three:

| Plan | Bones | Sockets | Size | Motions | Moves by |
| --- | --- | --- | --- | --- | --- |
| `humanoid/v1` | The VRM 1.0 humanoid's 55 bone names and parents, 15 required: hips, spine, head, and the upper leg, lower leg, foot, upper arm, lower arm and hand of each side | `hand.right` on `rightHand` and `hand.left` on `leftHand`, each holding one thing up to 1,500 mm long with a grip section up to 60 mm | height 900 to 2,400 mm; reach 1,500 mm | idle and walk required; run, reach, hold, talk and sit optional | walking |
| `bodiless/v1` | none | `float`, beside it, one thing up to 300 mm long | radius 100 to 600 mm; reach 1,500 mm | none | walking |
| `rigid/v1` | none | none | a box from 10 to 10,000 mm a side | none | none: it moves only when carried |

Every figure is in the world's slot frame, the frame of style pack slots, world kind parts and the
world object catalog: whole millimetres, width along x, depth along y with the front at +y, height
along z, the pivot at the base centre. glTF meets it by `X = -x`, `Y = z`, `Z = y`, a proper
rotation, so nothing is mirrored. A humanoid's rest pose is the T-pose, facing +y with its left at
-x, which is glTF's facing +Z with its left at +X.

"Blocky" is a look, not a body: a blocky figure and a knight share `humanoid/v1`, so either may be
drawn in the other's look. A sword, 1,000 mm long, fits a hand and not a float socket, so a lantern
spirit is refused it by name. No four-legged, winged or many-headed plan is shipped: such a body is
drafted for the creature that has it ([Creatures](#creatures-bodies-drafted-from-words)). No wheeled
plan exists.

## Abilities and offers

[`abilities.v1.json`](../assets/catalogs/things/abilities.v1.json) states what a thing can do, each
served by one ability module, with what it needs of the body and what its target must offer:

| Ability | Module | Needs | Its target offers | Parameters |
| --- | --- | --- | --- | --- |
| `wait`, `stand`, `talk`, `rest`, `visit` | `exulanica-ability/purposeful/v1` | a way to move, except `wait` | `talk_to`, `rest_at`, `visit` for `talk`, `rest`, `visit` | |
| `pick_up`, `put_down`, `give`, `take` | `exulanica-ability/hands/v1` | a socket, and a way to move except `put_down` | `holdable`, a top or the ground, `receive`, `let_take` | |
| `follow` | `exulanica-ability/follow/v2` | a way to move | `be_followed` | |
| `say` | `exulanica-ability/say/v1` | nothing; takes a line | `hear` | |
| `leave` | `exulanica-ability/crossing/v1` | a way to move | `leave_through`, or none | `quiet_minutes` 1 to 60 |

The purposeful abilities are the purposeful routine's actions with exactly its rules, and talking
stays wordless: words are said. A line is written only by a decider, never by the routine. Under the
module's second version (`exulanica-ability/purposeful/v2`), which every society of things made
since records, a being does only those its kind lists: the routine plans only them, its decider is
offered only them, a talk takes two beings whose kinds both list talk, and a request for another is
refused `activity_not_offered`
([society contract](synthetic-society-contract.md#the-society-of-things-v7)). Waiting is
everybody's, and a being whose kind does not rest is never tired. A society that recorded the first
version runs it for its whole life, where every being may do all five.

[`ability-modules.v1.json`](../exulanica/abilities/ability-modules.v1.json) states each module once,
by version, read by [`registry.py`](../exulanica/abilities/registry.py): the abilities it serves,
its bounded parameters (a figure the module uses itself, or a range a kind states within), the
event kinds its minute records, and whether it is built. Purposeful (versions 1 and 2), say,
crossing (versions 1 and 2, the second naming a visitor in every summary by what it is, from
outside, never as simulated) and hands (versions 1 and 2: `reach_mm` 1,500, `approach_mm` 8,000,
`walk_minutes_maximum` 3) are built, and so is follow's second version (`follow_distance_mm` 2,000, `lost_after_minutes`
3); its first was stated and never built, so no society records it, and it is still refused by name
(`follow_not_built`). A society of things records
the modules it runs in its first input and runs exactly those for its whole life
([society contract](synthetic-society-contract.md#the-society-of-things-v7)), so a module version
stays in the table while any stored society names it, and a new version is a new row. A later
version of a module serves the same abilities, so the abilities catalog names one version of each
module and an ability is served by whichever version a society runs.

[`offers.v1.json`](../assets/catalogs/things/offers.v1.json) states what a thing lets others do to
it, and the parameters a kind states for each:

| Offer | Parameters |
| --- | --- |
| `holdable` | `hands` 1 or 2; `grip`, a point inside its box; `axis`, the direction it extends from the hand, one of `+x`, `-x`, `+y`, `-y`, `+z`, `-z` |
| `receive`, `let_take`, `talk_to`, `hear`, `be_followed`, `leave_through` | none |
| `top` | `capacity`, 1 to 8 things |
| `rest_at`, `visit` | `places`, 1 to 16 |
| `arrive_through` | `point`, one place |
| `perch`, `host` | the world object catalog's perches and flyers, read by flight alone |

A place is `{x_mm, y_mm, faces, seat}` in the thing's slot frame: where a person stands, within
reach of the box, the way they face there (`+x`, `-x`, `+y` or `-y`), and the seat they sit on, a
point inside the box with the way it faces, or none. Whether a socket holds a thing is the
socket's to say, by the thing's longest side and its section through the grip. A sword is held
150 mm up its length with the blade up (`+z`); a lantern by the ring on its cap, 290 mm up,
hanging below the hand (`-z`). A gate's arrival point is 1,000 mm in front of it, facing away
from it (`+y`), so a visitor steps out of the gate into the world.

The world object catalog's uses map onto offers: `rest` to `rest_at` with its places and seats,
`visit` to `visit`, perches to `perch` and hosted flyers to `host`. A kind's routine draws among
`wait`, `stand`, `talk`, `rest`, `visit`, the hands abilities and `follow`, by the kind's weights.
No society reads these weights yet: the society of things' routine is the purposeful planner's, and
only a decider, or the world's owner by a direct request
([society contract](synthetic-society-contract.md#typed-user-directed-actions)), uses a being's
hands.

## Looks

[`looks.py`](../exulanica/things/looks.py) reads a look with `read_look`:

| Field | Holds |
| --- | --- |
| `profile`, `look`, `version`, `label` | `exulanica.look/v1`; a lowercase key; a whole number; lowercase words of at most 80 characters, the card's |
| `body_plan`, `look_kind` | the plan it fits and the look kind that draws it, which must fit that plan |
| `container` | `{sha256, bytes, media_type}` of one binary glTF, where its look kind draws one, and none otherwise |
| `rig` | where its look kind is rigged: every bone of the plan it maps to one of the rig's joints, each joint once, all the plan's required bones mapped, and the rig's clip for each motion it has; it may also state `sockets`, the rig's joint for each of the plan's sockets (each joint once), and `ground_speed_mm_per_s`, how fast each of its moving clips (`walk`, `run`) carries the body at the look's own height, whole millimetres a second from 1 to 10,000 |
| `height_mm` | its natural height, within the plan's bounds, for a body with a height or an extent; none otherwise |
| `sampling` | `linear`, or `nearest` for pixel art |
| `light` | where its look kind is a light: an sRGB colour, an intensity and a radius |
| `role` | where its look kind is dressed by a style pack: the look role, `family.leaf` |
| `origin` | its [origin record](#the-origin-record) |

[`look-kinds.v2.json`](../assets/catalogs/things/look-kinds.v2.json) states how looks are drawn (its
first version, which fitted the rigged and rigid kinds to the humanoid alone, stays beside it). A
look kind's plans may name `any_with_bones`: it fits every plan that has bones, whatever its name.

| Look kind | Plans | What it is |
| --- | --- | --- |
| `catalog_person` | humanoid | A person drawn from the published people catalog by the street population draw, as every society's people are drawn |
| `skinned` | humanoid; any plan with bones | A rigged glTF: a person's figure admitted as a reviewed component with its own clips, or a creature's sculpted look; its rig maps every required bone of its plan |
| `rigid_on_bones` | humanoid; any plan with bones | One `exulanica.static-glb/v1` container with one node per dressed bone, named `bone:<bone name>`, each a direct child of the scene root at that joint's rest position with no rotation or scale, its rigid parts as children; a joint node for every required bone of its plan; posed by procedural motion on the bones. A blocky figure and a creature's sketch are this look |
| `light` | bodiless | No file: a light, a glow and a slow drift, in the colour and radius the look states |
| `static` | rigid | One `exulanica.static-glb/v1` container inside the thing's box: a reviewed object, a person's prepared asset or a generated piece |
| `look_role` | rigid | A look role the world's style pack dresses, fitted to the thing's box |
| `none` | all, and any plan with bones | Nothing is drawn; the thing is still there |

A `skinned` look's container is one binary glTF of the profile `exulanica.skinned-glb/v1`, read by
`read_skinned_glb` in [`skinned.py`](../exulanica_pieces/skinned.py), plain Python with no numpy so
the product reads it at admission. One node draws a mesh: it has a skin and no transform, is a root
of the one scene, and its mesh holds up to 16 triangle primitives on that skin, each with
`POSITION`, `JOINTS_0` and `WEIGHTS_0` and a colour (`COLOR_0`, or `TEXCOORD_0` with the material's
one base colour texture, a PNG or JPEG of at most 1,024 by 1,024 pixels in the binary chunk), never
a morph target or a second set of joints. Joints are placed by translation, rotation and scale,
never a matrix; nothing that is not a joint lies between a joint and the scene's root; each inverse
bind matrix is the inverse of its joint's world matrix at rest within one part in ten thousand, so
the bind pose is the rest pose procedural motion starts from. Every vertex's four weights name
joints of the skin, are not negative and sum to one within one part in a thousand. A clip is named
by a motion of the vocabulary, moves joints only and stays in place: every key of the root joint's
translation keeps its first key's ground position. At most 128 joints, 20,000 triangles, 2
materials, 16 clips and 8 MiB; no extension and no external file. Given a look's `rig.bones` and its
plan's parents, the reader also holds the joint tree to the plan's: each mapped bone's nearest
mapped ancestor joint is the joint of its plan parent.

Where a held thing goes is a socket of the body plan, which names the bone it is on
(`hand.right` on `rightHand`). In a `rigid_on_bones` container a socket's place is a node named
`socket:<socket key>`, a child of its bone's node; in a `skinned` look it is the rig's joint
`rig.sockets` names. The node's origin is the grip and the thing extends along the node's slot
`+z`, which is the glTF node's `+Y`, so a held thing follows the node as a clip moves it; a thing
whose holdable axis is `-z` hangs straight down from the origin whatever the joint does, which is
presentation alone. Where a look states no socket node, a thing is held at its bone node's origin
and turned with the body.

**Requirement:** no look reference enters a society's input, state or decision context. Looks are
records apart from what a thing is, a kind is given to a society only through its semantics, and
a crossing's look rides beside its arrival, never in it. Swapping a thing's look therefore changes
no state and no decision.

The look a thing wears in a version is a choice recorded beside it
([`thing_looks.py`](../exulanica/world/thing_looks.py), migration 0156): a shipped look by key,
version and digest, one the library holds, whose body plan is the thing's kind's (refused otherwise
as `look_not_shipped`, `look_unfit` or `thing_kind_not_shipped`). `check_crossing_look` checks the
look a crossing brings, against the shipped catalogs or, asked on a workspace's connection, the
looks that workspace keeps, so a door refuses an arrival before it writes anything; `record_crossing_look` records it, for a door to call in the transaction of the
minute that binds the arrival as arrived, once per crossing however often it is handed over. Choices
are appended and never changed, each naming the crossing or the actor that made it, and the newest
per thing that still names a look to wear is worn: a choice naming a shipped look the library no
longer serves at that digest (one a later release dropped) is passed by like one naming a withdrawn
look of the workspace's, and the choice before it read; a thing with none wears its kind's first
look.
A thing may also wear a look its workspace keeps (a creature's sketch, a look a deployment built or
imported), named by the digest of its document alone, `{source: "workspace", sha256}`, never by a
key a person's words made: the choice is checked against the looks the workspace holds and has not
withdrawn (`admitted_look_by_digest`) and against the kind's body plan, and recorded with `source`
`workspace` and no key or version (migration 0167). A choice naming a look the workspace no longer
holds or has withdrawn stays, and every read passes it by for the choice before it. The database
picks each thing's one choice to wear, so a read is one row per thing however many were appended.
`GET /world/versions/{version_id}/thing-looks` (`world.read`, never cached) answers
`exulanica.thing-look-choices/v1`: for each thing of the version, in thing id order, the newest
choice it may still wear, each with the thing's id in its society, the author's id for a placed
thing, the look, who chose it and when; one whose look is a shipped one under `looks`, as every
reader of the profile reads it, and one whose look is the workspace's own under `workspace_looks`,
stated only when some thing wears one, which a reader that does not know it leaves alone (the thing
then wears its kind's first look there). Choices stay with the version, as its society does.

### A thing's card

`GET /world/versions/{version_id}/society/things/{thing_id}` (`world.read`, never cached) answers one
thing or being of the version's society of things, by the id the society gives it (never an
author's placed id, which the move and remove routes take), as `exulanica.thing-card/v1`
([`thing_card.py`](../exulanica/api/thing_card.py)); a version whose society is not a society of
things, or holds no such thing, answers 404, and one whose input names something no longer available
answers 424 `unavailable_society_input`, as the society read does. The card states:

- what it is, in its kind's words: the label, summary, class (`being` or `object`) and body plan,
  and how it came (`placed`, `crossed` or `populated`);
- what it can do here and what others can do with it (`abilities`, `offers`, each `{key, words,
  module}`): only what a module the society runs acts on, the modules listed as `runs`, each
  entry naming the version the society runs, so an ability or offer of a module the society does
  not run (following, in a society made before it was built) is never listed; nor is an offer
  whose taking-up activity the being's own
  kind does not do under the second purposeful module (a talk takes two beings whose kinds both
  list it, so a lantern spirit's card offers no talk);
- where it is (`where`: on the ground, held by whom and in which socket) and, for a being of a
  society running hands, what it holds (`holding`, null where hands are not run);
- who decides for a being (`decider`): its own program where it came from outside, else a person
  playing it (`person`, with `played_by_you`, never which account;
  [decision roles](decision-roles-contract.md#a-person-playing-a-being)), else the model or the
  routine a choice names (its own, or its gate's), with whether the owner may change it and why a
  chosen model is not asked here; null for an object;
- how it is drawn (`look`: the newest look chosen for it that it may still wear, else its kind's
  first, with its label, its look kind's words, whether the owner chose it and its origin) and what
  else it may be drawn as (`looks`: every shipped look made for its body and, for a body with bones,
  every look the workspace keeps for it, by digest; for a body with no bones, an object drawn at its
  kind's size, only its kind's own shipped looks), each with its licence as its origin states it;
- its kind's origin record, the lines a being said lately (`lines`, newest first, at most eight,
  each with its minute and who decided it, read through an index of said events by speaker,
  migration 0167), and `crossing`, null until a door states its record. A line said under an input
  that no longer authorizes (one naming something withdrawn since) is left out, and the card says
  how many and why (`lines_left_out: {count, reason}`, stated only where some were): the society's
  own inputs decide whether it may be read at all, so one old line never refuses the whole card;
- the society's minute and state digest as the card was read (`society: {tick, state_sha256}`).

`POST /world/versions/{version_id}/society/things/{thing_id}/look` (`world.write`) records the
world's owner's choice of a look, `{look: {look, version, sha256}}` or `{look: {source: "workspace",
sha256}}`, one the card would list, appended to the look table with the actor who chose it, and
answers the card as it read it before, with only the look it now wears replaced. The card is read
once in the swap's transaction, the inputs its lines were said under announced with the society's
own before the first authorization, so their stored bytes are read before the asset read lock is
taken ([asset-read-currency.md](asset-read-currency.md)). A look is chosen beside a thing, never in
it, so the minute and the state digest the answer states are the ones the card stated before; a
line left out does not hold the swap back, since nothing the swap writes depends on what that
line's input names. A look the library does not hold, or another
workspace's (answered exactly as a digest nobody keeps), is refused `look_not_shipped`, and one made
for another body, or for another kind of object, `look_unfit`; nothing is written. The owner may
dress any thing or being of the world, a visitor another program decides for included: a look is
how this world draws it, never anything its program or its game reads, and the look its crossing
brought stays recorded and listed, so the owner can choose it again.


The looks this repository authors are recipe documents, profile `exulanica.look-recipe/v1`, under
[`assets/catalogs/things/recipes`](../assets/catalogs/things/recipes), one file per recipe version,
each with its origin record. A recipe states named nodes, each at a point in the slot frame and
holding boxes and upright cylinders in whole millimetres, each in one colour and some glowing; or it
builds on another recipe (`base`) and colours it with its `palette`, a colour being `#rrggbb` or a
palette role's name. The two blocky figures are one recipe in two palettes, so their joints are
stated once. One reader, [`authored.py`](../exulanica/things/authored.py), names no look: a recipe
is a look's when every colour it reaches resolves, and a test holds that no module of the things
package states a shipped kind's, look's or recipe's key. [`pieces.py`](../exulanica/things/pieces.py)
writes each into a binary glTF the same on any machine: every vertex a whole number of millimetres
turned into metres by one float32 division, a cylinder's corners from a table of square roots.
Their containers are not committed. Each look document pins its container's digest and length, and
a test writes each container again, compares it and passes it through the product's static glTF
admission (`inspect_static_glb`). A blocky figure stands its joints where a 1,700 mm figure's stand
in the T-pose, with an upper arm, a lower arm and a hand as three boxes, so its elbow bends.

## The origin record

[`origin.py`](../exulanica/things/origin.py) reads the record with `read_origin`. A thing kind, a
look and a crossing each carry one:

| Field | Holds |
| --- | --- |
| `class` | How the piece came to exist here: `authored`, `drafted`, `generated`, `uploaded`, `imported` or `crossed` |
| `by` | Who or what made it: `{kind: project}`; `{kind: account, account_id}`; `{kind: model, provider, model_id, prompt_version, prompt_sha256, words_sha256, execution_sha256}`, each figure none where an older record named its model only through its receipts; `{kind: program, bridge, adapter_version, mapping_sha256, grant_id}` |
| `sources` | At most 32 `{reference, retrieved_on, revision, licence_page_sha256}`; a person's free-text reference is kept and never fetched |
| `licence` | `{spdx, verdict, attribution, share_alike, licence_url, licence_text_sha256}`: an SPDX expression or a `LicenseRef-` identifier, and the licence matrix's verdict |
| `authors` | At most 16 names, as the source credits them |
| `lineage` | Ingredients and generation receipts by digest, and the translation manifest's digest |
| `distribution` | `public`, `private` (its own workspace) or `restricted` (never in a public artefact) |

The record holds these rules, each refused by the field at fault:

| Class | Made by | Also |
| --- | --- | --- |
| `authored` | this project or a person | |
| `drafted` | a model | |
| `generated` | a model | names its receipts |
| `uploaded` | a person | never public |
| `imported` | this project or a person | names where it was taken from |
| `crossed` | the outside program it came through | names its translation manifest |

A licence asking for attribution states it, and a CC0 dedication states none. A share-alike
licence, and only one, is marked share-alike. A person's own work (`LicenseRef-Exulanica-Own-Work`)
and bytes baked for one workspace are never public.

### The vocabularies it reads

Pieces made before the record keep their bytes and their own origin vocabulary.
[`vocabularies.py`](../exulanica/things/vocabularies.py) reads each into the record, checked by the
record's reader, so whatever shows where a piece came from reads one shape:

| Vocabulary | Read as |
| --- | --- |
| A world kind's `origin`, `provenance` and `licence` | its class; drafted by the model its provenance names, uploaded by the account, otherwise by this project |
| A style pack's `origin`, `provenance`, `licence` and `authors` | its class; drafted by its model; generated with its receipts; imported from its source |
| A generated piece's receipt | generated, its receipt and its request in its lineage |
| A person's prepared asset's rights | uploaded by them, private: their own work, or licensed with its attribution and source |
| A reviewed asset's import manifest | imported by this project from its pinned source and revision, its bytes an ingredient |
| A people catalog family | imported by this project from the sources its definition names, the licence text pinned by digest |
| A catalog entry's licence | an original entry authored by this project; a derived one imported from its source |

Three vocabularies stay apart by design: a placed object's `origin.kind` and `origin.role`, a claim
the person makes about the object; a character's and a representation's per-trait origins, which
describe evidence for traits; and an assertion's provenance, which answers who supports an
assertion ([world memory model, section 3.1](world-memory-model.md)).

## Translation manifests

Bringing something into a world from elsewhere is a translation, and none is silent. An import or a
crossing writes a manifest ([`manifests.py`](../exulanica/things/manifests.py)): the translator
(key, version, digest), the source (its format, the source's own type for the thing, the digest of
what it read), what it made, and every field of the source exactly once, each with `words`: one
[line](#lines) saying what the field is and what it became ("A torch, which arrives as a lantern"),
taken from the translator's own data (a crossing's mapping file), so whoever shows a manifest needs
no words of its own for any program. A field that is not exact also states its `reason`, the plain
why. What it made is a thing kind by digest, with the look it is drawn in or none (a crossing, a
kind's import); or, for an import whose product is a look alone, no kind and the look by key and
version only, the look naming the manifest by digest in its origin record's lineage, so neither
digest depends on the other. A manifest of the first profile, `exulanica.translation-manifest/v1`,
states no words and is read as it was written:

| Disposition | Meaning |
| --- | --- |
| `exact` | Carried across unchanged, to the field it names |
| `approximated` | Carried across with a stated reason, to the field it names: an arm of one box mapped onto the upper arm, its elbow bend lost |
| `dropped` | Not carried, with a stated reason: a player's name, because a person's name never crosses; health, because this world has no health |
| `opaque` | Kept and never read here: by an importer, verbatim in the kind's `ext`; by a crossing, by the program it came from, under the thing's id |

`check_accounting` holds a manifest to its source: every field the source states is accounted for
exactly once, at its own path or under one of its ancestors, and no path names a field the source
lacks. Foreign mechanics are never emulated: a field only a module this world's rules hold could
act on is dropped or opaque.

## Lines

A line is one plain line of words, held to one rule wherever words are stored or said
([`lines.py`](../exulanica/things/lines.py)): 1 to 200 code points in Unicode normal form C, with
no control, format, surrogate, private-use, line-separator or paragraph-separator character
(categories Cc, Cf, Cs, Co, Zl and Zp) and no white space at either end. Text not already in normal
form C is refused rather than rewritten, so what is stored is what was written; a caller holding
text from outside normalises it first. A translation manifest's words are lines.

## The kinds and looks this repository ships

[`scripts/things/shipped_things.py`](../scripts/things/shipped_things.py) writes the first version
of every shipped kind, and `--check` exits non-zero when a committed one differs. A later version
of a kind is data: its committed document is the source, which the script reads, checks against the
things catalogs and formats, and never writes from figures of its own. Every look is data in the
same way, and a look changes only as a new version: the script reads each committed look and holds
it to its source by what it is (an authored look's recipe, a reviewed asset and its dedication, the
people family's origin, or an imported look's committed files, below), reports one that differs or
that it cannot hold to a source, and when writing only formats documents and refreshes a recipe
look's container block.
The script keeps the lock, adding a line for each new version and refusing to change one already
there. The six pieces of furniture are derived from the world object catalog, their places, seats,
perches and hosted flyers as that catalog derives them, so no figure is stated twice. The kinds are
this project's own, under the repository's licence.

The host serves what it ships, the same for every workspace and only to a session (`world.read`):
`GET /things/library` lists every kind with the looks it suggests, every look with its container
and the body plans catalog's digest (`exulanica.thing-library/v1`), and
`GET /things/library/{content_sha256}` answers a kind or a look as its canonical JSON, the body
plans catalog as its file, or a look's container as `model/gltf-binary`, named by the SHA-256 of
exactly those bytes and cached as immutable; any other digest is 404 `unknown_reference`
([`thing_library.py`](../exulanica/world/thing_library.py)). The library is read when the host
starts. An authored look's container is written from its pieces, a furniture look's is its reviewed
asset and an imported look's is the container file committed with its import, each held to the
digest its look pins. A look file named for another look or version, a container no source gives, and a
kind suggesting a look the library does not hold at the kind's digest each stop the start, named.

| Kind | Class | Body | Abilities | Offers | Deciders | Look |
| --- | --- | --- | --- | --- | --- | --- |
| `knight` | being | humanoid, 1,700 to 1,900 mm | wait, stand, talk, rest, visit, pick_up, put_down, give, take, follow, say | talk_to, hear, receive, be_followed | the routine by default; a model, the owner or an outside program | version 2: `kaykit-knight`, then `blocky-knight`; version 1: `blocky-knight` |
| `traveller` | being | humanoid, 1,550 to 1,800 mm | as the knight; version 2 also leave after 5 quiet minutes, offered only once it crossed in | as the knight | as the knight | `blocky-traveller` |
| `lantern_spirit` | being | bodiless, radius 200 mm | wait, follow, say, pick_up, put_down, give, take | talk_to, hear, receive, be_followed | as the knight; its routine follows whoever carries a lantern | `spirit-light` |
| `visitor` | being | humanoid, 1,500 to 2,000 mm | wait, stand, talk, say, pick_up, put_down, give, take, follow, leave after 5 quiet minutes | talk_to, hear, receive, be_followed | an outside program only | none: its crossing brings one |
| `villager` | being | humanoid, 1,500 to 1,950 mm | wait, stand, talk, rest, visit | talk_to, hear | the routine; a model or the owner | `people-catalog` |
| `sword` | object | versions 2 and 3: 240 x 80 x 1,000 mm, as wide and deep as a sword's guard and pommel; version 1: 120 x 40 x 1,000 mm | | holdable, one hand, 150 mm up its length | | version 3: `kaykit-sword`, then `primitive-sword`; versions 1 and 2: `primitive-sword` |
| `lantern` | object | 180 x 180 x 300 mm | | holdable, one hand | | `primitive-lantern` |
| `well` | object | 1,600 x 1,600 x 2,200 mm, blocks walking | | visit, from two sides | | `primitive-well` |
| `gate` | object | 3,000 x 400 x 3,000 mm, walked through | | arrive_through, leave_through | | `primitive-gate` |
| `bench`, `cafe_table`, `seating_planter` | object | their catalog dimensions, blocking walking | | rest_at, a seat at every place | | their reviewed asset |
| `market_stall` | object | its catalog dimensions, blocking walking | | visit | | its reviewed asset |
| `planter_tree` | object | its catalog dimensions, blocking walking | | visit, perch, host | | its reviewed asset |
| `lamp_post` | object | its catalog dimensions, blocking walking; version 2 870 mm deep (version 1 250 mm); version 3 also 4,500 mm high (versions 1 and 2 6,000 mm) | | perch | | its reviewed asset |

The six pieces of furniture each ship a version 2 that differs from version 1 in its summary alone, plain
words a card shows ("A wooden bench people sit on.", "A small cafe table people sit at.", "A street lamp on a
post that lights the way.", "A market stall with goods laid out under an awning.", "A young tree growing in a
planter.", "A planter with a seat built along its edge."), and, for the lamp post, a box deep enough for the
generated lamps its look may be swapped for (870 mm); version 1 stays as it shipped. The lamp post's version 3
is version 2 at a town lamp's height, 4,500 mm, for the lamp posts generated for it (versions 1 and 2 are the
catalog lamp's 6,000 mm); its reviewed look is drawn at that size, and its perch, on the lamp's arm, scales with
it (956 mm out and 4,350 mm up, from 1,275 and 5,800). Versions 1 and 2 stay as they shipped.

| Look | Look kind | Origin |
| --- | --- | --- |
| `blocky-knight`, `blocky-traveller`, `blocky-hoplite` | `rigid_on_bones` | authored here, CC0 |
| `primitive-sword`, `primitive-lantern`, `primitive-well`, `primitive-gate` | `static` | authored here, CC0 |
| `spirit-light` | `light` | authored here, CC0 |
| `people-catalog` | `catalog_person` | imported, CC0: the people catalog's MakeHuman family through MPFB 2, with Quaternius locomotion |
| `bench`, `cafe-table`, `seating-planter`, `market-stall`, `planter-tree`, `lamp-post` | `static` | authored here, CC0, pinned to the reviewed asset's dedication |
| `kaykit-knight` | `skinned` | imported, CC0: the knight of Kay Lousberg's KayKit Adventurers 2.0, with idle, walk, run and pick-up clips from that pack and holding and sitting clips from KayKit Character Animations 1.1, standing 1,800 mm, holding at its own hand slots |
| `kaykit-sword` | `static` | imported, CC0: the one-handed sword of KayKit Adventurers 2.0, scaled to stand inside the sword's box |
| `kaykit-mannequin` | `skinned` | imported, CC0: the medium mannequin of KayKit Character Animations 1.1 with that pack's idle, walk, run, pick-up, holding and sitting clips, standing 1,750 mm, its printed name tag covered; no hand slots, so it holds things at its hand bones |

### Imported looks

A look made from a pack another maker published is imported by one translator,
[`scripts/things/import_looks.py`](../scripts/things/import_looks.py), from an import document
(`exulanica.look-import/v1`, `assets/things/<folder>/import.json`) that states, as data, each source
pack (its page and the date it was read, its archive by digest, its licence file), and for each
look the files it reads, how a figure's joints map onto the body plan's bones and sockets, the clip
each motion uses, the joints its clips move that the figure lacks, any region printed on its picture
that a body here does not show, the box an object stands inside, and why each joint, clip or region
that does not come across stays behind. The translator names no pack or thing. It merges a rigged
figure into the shared skinned shape (`exulanica.skinned-glb/v1`): one skinned mesh of the figure's
parts with only the clips its motions use, each named by its motion, holding the joints the document
names at their first key's ground position so a clip never carries the figure, with the uniform
scale that stands it at the look's height baked into its vertices, bind matrices, joints and clips,
so no node is scaled. A clip's channels on a joint the figure lacks are left out only where the
document names that joint; a printed region such as a name tag is covered by drawing its triangles
from one plain point of the same picture, no pixel changed. It fits an object inside its box and
prepares it as any person's static container is. It measures each
moving clip's ground speed from the clip itself. Beside the import document it commits each
container with a reviewed import receipt, each source's licence file byte for byte and a source
reading per look; under `assets/catalogs/things` it writes the look and its translation manifest
(version 2), which accounts for every field of the reading and names the importer by the digest of
the file that first made it, so an importer edited since makes a shipped look again without moving
it. The archives are never committed; with them present, `--check` makes everything again and
compares every byte. The API image carries
`assets/things` beside the catalogs.

## Creatures: bodies drafted from words

A creature a person imagines, with any number of heads, legs, wings or tentacles, is a thing kind
of class `being` whose body plan was drafted for it rather than shipped. The model that drafts it
never writes bones: it fills a few figures, and code written once for every creature builds the
rest. Nothing names any particular creature in code, which `tests/test_no_creature_code.py` holds
by scanning every source of the product, the shared piece formats, the GPU tooling and the web
packages for creature names.

### The body recipe

[`bodies.py`](../exulanica/things/bodies.py) reads a body recipe, `exulanica.body-recipe/v1`, with
`read_body_recipe`, against the body grammar
([`body-grammar.v1.json`](../assets/catalogs/things/body-grammar.v1.json)), whose entries state
every choice and bound with its reason:

| Field | Holds |
| --- | --- |
| `posture` | `upright` (a torso standing on one or two pairs of legs), `horizontal` (a torso along the ground on none to six pairs), `serpentine` (mostly spine, lying along the ground) or `floating` (no ground contact, no legs), each with its spine segments, leg pairs and extent bounds |
| `spine` | torso segments, 1 to 8 (serpentine 6 to 24) |
| `upper_body` | `none`, or `upright`: the front of a horizontal or serpentine body rises into an upright torso carrying its arms and heads |
| `heads` | 1 to 5, each with 0 to 8 neck bones and a jaw or none |
| `limbs` | groups `{role, count, segments}`: legs, arms, wings and fins in left and right pairs (up to 6, 3, 2 and 4 pairs), tentacles up to 12; 2 to 4 segments (fins 1 to 2, tentacles 2 to 8) |
| `tail` | 0 to 16 bones |
| `extent_mm` | `length` (nose to tail tip), `width` (wings folded), `height` (ground to the top of its head), `span` (wingtip to wingtip, 0 with no wings) |
| `holds_with` | `none`, `jaws`, `hands` or `front_claws` |
| `colours` | 2 to 4 of the grammar's named colours: its body, belly, accent and eyes |
| `appearance` | 12 to 200 characters for a sculptor, one line, no numerals |

| Code | Refused |
| --- | --- |
| `body_recipe_invalid` | A field it does not state, a value out of shape, a name the grammar does not hold, numerals in the appearance |
| `body_recipe_out_of_bounds` | A count, segment number or size outside the grammar's bounds; an odd number of a paired limb |
| `body_part_unfit` | A part its posture does not take: an upright torso on an upright or floating body, legs on a floating one |
| `body_too_many_bones` | More than 128 bones, counting every segment of every neck, limb and tail |
| `body_holds_nothing` | Carrying with jaws, hands or front claws it does not have |
| `body_span_unfit` | Wings spanning less than its width, or a span with no wings |

The grammar's movement entries say what each body can do and which module it does it by: walking
(at least one pair of legs, four or more tentacles, or a serpentine body, never a floating one) is
`exulanica-movement/walking/v1`. Flight, swimming, climbing and burrowing are stated with no module
and with the sentence a creature asked for one is refused with ("This world has no flying creatures
yet.").

### The builder and a drafted plan

`build_body` (`exulanica-body-builder/v1`) turns a recipe into a body plan document,
`exulanica.body-plan/v1`:

- **Bones** with parents, every one required, named by one grammar: `hips`, `spine2`, `upper1`,
  `head1Neck3`, `head1`, `head1Jaw`, `leg3Left2`, `wing1Right3`, `tentacle4Segment2`, `tail4`.
  Bone names are a lowercase letter then letters and digits, which every VRM name still is.
- **Chains** (`limbs`): `{key, role, side, order, bones}`, each bone list from the body outward,
  role `spine`, `neck`, `tail`, `jaw`, `leg`, `arm`, `wing`, `fin` or `tentacle`, side `left`,
  `right` or `centre`, order counting from the front, so whatever moves a body reads its chains
  and never its names. On a body lying along the ground (horizontal or serpentine) each pair of
  legs, wings, fins or arms hangs from the stretch of spine beside its root, so a spine that bends
  carries every pair with its own part of the body.
- **Sockets** from `holds_with`: `mouth` on each jaw (`mouth.head2` and on for further heads),
  `hand.left` and `hand.right` on the first arms' tips, `claw.left` and `claw.right` on the front
  feet, each holding one thing up to a quarter of the body's length with a grip section up to a
  sixth of its width.
- **Size**, the figure `extent_mm`: ranges from four fifths to five quarters of the recipe's own.
- **Motions**: idle; walk where it walks; talk with a jaw; hold with a socket. The motion
  vocabulary is idle, walk, run, reach, hold, talk, sit, fly, glide, take_off and land.
- **Moves**: the built modules its body can move by.
- **Joints at rest** in the slot frame, by one rule per posture: a horizontal body's nose at the
  front of its stated length and its tail tip at the back, feet on the ground, wings level at rest
  reaching half the span, a neck rising at its angle without lifting a head above the stated
  height; an upright body in the T-pose; a serpentine body straight along the ground; a floating
  body's tentacles hanging short of the ground. Integer arithmetic only, with cosines and sines
  from a table of square roots, so a recipe builds the same bytes on any machine and a left limb is
  the exact mirror of its right.

`read_body_plan` reads a plan document with the catalog entries' own field readers, and also:
every chain is the plan's own bones, parent-linked from the body outward, no bone in two chains,
each role from the list; at most 128 bones; motions from the vocabulary; an origin record in place
of a catalog licence; its digest. Its key may not be a shipped plan's (`body_plan_name_taken`).

A kind of a drafted plan names it by name and digest and states its four figures inside the plan's
ranges: `body: {plan, plan_sha256, extent_mm}`. `read_thing_kind` and `read_look` take `plan_of`,
which resolves a plan the catalogs do not state. A kind's `moves` entry may be the module's name
or `{module, parameters}`, the figures a module leaves to each kind, whose bounds the module checks
where the kind is used.

### The sketch

[`sketch.py`](../exulanica/things/sketch.py) draws a drafted plan's **sketch**: look kind
`rigid_on_bones`, labelled "a sketch of its body", one node per bone named `bone:<name>` at its
joint at rest, each carrying a tapered six-sided limb from the joint to where the bone ends,
pointed at both ends; a wing bone also carries its stretch of membrane, drawn from both sides; each
head carries two eyes. Its colours are the recipe's: the body, the belly (jaws, membranes), an
accent (the last segment of every limb and the tail's tip) and the eyes. It is authored by this
project from the plan (class `authored`, CC0-1.0, the plan's and the recipe's digests among its
ingredients), its container written by [`pieces.py`](../exulanica/things/pieces.py), whose
oriented parts are triangles in whole millimetres, each lit by its own normal, and admitted by the
product's static glTF reader. It is the creature's own body plan made visible, never a picture
standing in for it.

### Assembling a creature

[`creatures.py`](../exulanica/things/creatures.py) `assemble_creature` turns a drafted form into the
recipe, the plan, the sketch and the kind, each read by its own reader, so a creature passes the
checks every thing passes. The kind is of class `being`, its default decider the routine with
`routine`, `model` and `person` allowed, its sketch its first look, its label lowercase words and
spaces (its key the label with underscores). The kind's and the plan's origins are `drafted`, by
the model that filled the form, with the recipe's digest (and the kind's also the plan's) among
their ingredients. A refusal keeps its reader's code, or is one of these:

| Code | Refused |
| --- | --- |
| `creature_cannot_move_so` | A movement its body does not allow, in the movement's words ("a creature that flies needs a pair of wings, or a floating body") |
| `creature_movement_unbuilt` | A movement this world has not built, in the grammar's sentence |
| `creature_name_taken` | The name of a kind of thing that already exists |
| `creature_form_invalid` | A field the form does not state, an ability, offer or movement outside its list |

### The drafter

[`creature_drafting.py`](../exulanica/selection/creature_drafting.py), with its words in
[`creature-drafting.v1.json`](../exulanica/selection/creature-drafting.v1.json), asks a model for a
creature and assembles its answer:

- The form is flat: every field holds one value (its heads are alike; each kind of limb is a count
  and its segments; four colour fields; a yes or no for each movement, ability and offer; a weight
  for each ability its routine does), so no reply can stop between a list and the field after it.
  Every choice comes from the grammar and the catalogs at call time.
- The instructions render the grammar's postures, parts, movements and colours, the abilities and
  offers, the kinds the world already has, and the sentence of every check that may refuse a
  creature, from the checks' own tables.
- A creature the checks refuse is told the check's code, the form's field and the check's sentence,
  never the reply's text, and drafted once more; a second refusal is `creature_not_drafted`.
- Saved names are replaced before the words are sent, by the caller; the origin names the model
  that answered, the prompt's version and the digests of the instructions and the words, never the
  words.

### Drafting a creature from words

`POST /things/creatures` takes a person's words for one creature (one plain line of at most 400
characters) and answers `202` at once with a draft, `exulanica.creature-draft/v1`
([`thing_creatures.py`](../exulanica/api/routes/thing_creatures.py)). A worker in the API process
([`creature_drafts.py`](../exulanica/selection/creature_drafts.py), migration 0184) plays it: the
drafter is asked under the `creature_drafter` role with the words' saved names replaced, the
creature is held to every check above, and one that passes is kept in the workspace's own store
(below), its sketch its first look. `GET /things/creatures/drafts/{draft_id}` answers the draft as
it goes:

| Status | The draft names |
| --- | --- |
| `queued`, `running` | Nothing yet |
| `kept` | The kind made and its sketch, each by key, version and digest, its label, and the model that drafted it |
| `erased` | Nothing: the draft was kept, and the workspace has erased the creature since |
| `refused` | The refusing check's code, the field of the drafter's form it refused, and the code's fixed sentence, an unbuilt movement's in the grammar's own words ("This world has no flying creatures yet.") |
| `failed` | Why, by code: `drafter_unavailable`, `spending_refused`, `request_refused`, `expired`, `stranded`, `not_served` |
| `cancelled` | Why, by code: `workspace_deleted`, its workspace erased before the draft ended |

`GET /things/creatures/offered` (`exulanica.creature-offer/v1`) says before anyone types whether
the workspace may ask here and why not by code, how long the drafter's calls take by the record its
timeout rests on (the median and longest call, rounded up to whole seconds, and the timeout), and
the closed lists of codes a draft may end with: a refusal outside the list is carried as
`creature_not_drafted`. `GET /things/creatures/drafts` lists the requester's own drafts, newest
first, so a reload finds one still running; a draft states when it was asked, when a worker first
took it and when it ended.

A draft is a row and a job on the shared job queue, claimed with a lease and a claim token as a
reference job is. The words live only in the job until the draft ends, and the draft keeps nothing
of them, not even their digest: a digest of a short sentence is the sentence. What the draft makes
is the workspace's own: a kept creature's kind and plan name the digest of the words it was drafted
from in their origin (`words_sha256`, below), which anyone holding the workspace's `world.read`
reads with the kind until the creature is erased. A kept draft names
its kind by the digest of the kind's document alone, with no key and no foreign key, so erasing the
creature (below) is never held up by it; a refused draft keeps a code and a field, never a
sentence, since a check's own sentence may quote the drafted label, and the table refuses anything
else in those columns. Only the workspaces an installation lists draft creatures
(`EXULANICA_CREATURE_WORKSPACES`, the worker set off by `EXULANICA_CREATURE_WORKER`); a requester
has one draft open at a time and a bounded number an hour, reads only their own drafts, and needs
`world.write` and `model.invoke` to ask. A workspace not listed is told `creatures_not_run_here`;
words that are not one plain line, `words_refused`. A workspace with a draft still queued or
running is not seeded for another server, as the draft's job holds the words. A workspace's
tombstone ends its unfinished drafts in the tombstone's own transaction, whoever writes it, a
restore's replay included: each job is cancelled with its words blanked, and its draft ends
`cancelled`. A draft is asked under the workspace's lock, and never once that tombstone is
written: it is refused `410 tombstoned` and no job is written, so a draft and its workspace's
tombstone never interleave. A worker that drafted for a cancelled draft keeps nothing; a call it had
already sent finishes at the provider, and its answer is discarded.

The page asks from the open world: **Make a creature** (a rail and palette action) opens a sheet
([`creature-sheet.ts`](../web/packages/app/src/ui/creature-sheet.ts), run by
[`creature-maker.ts`](../web/packages/app/src/composition/creature-maker.ts)) that says first, from
`GET /things/creatures/offered`, whether creatures are made here and why not in words by code, and how
long one usually takes. Make sends the person's line and reads the draft every second, at most twice
the drafter's timeout and ten seconds more; a draft still running when the sheet opens is followed,
so a reload loses nothing. A kept creature is placed by its kind's digest alone in front of the
person and turned to face them, at the pose the objects panel offers, or, in a world made from a recipe or a world kind,
where that panel places nothing, the same distance ahead in the one region drawn there, on the plane
its people stand on; through the same edit as a planned thing (the version's compare-and-swap, the
saved entry advancing). Where the page cannot say where the person stands it places nothing and says
so; the creature stays kept. A refusal shows its code's fixed sentence
and keeps the line, and a failure says why in one sentence.

Spending is keyed by the job: under durable spending a job taken again after a crash is admitted
under the same key, and the authority refuses what was already paid; under process spending
(`EXULANICA_SPENDING=process`) the key is not checked, so a job taken again may pay again, once for
each of its at most two claims. Every API process of an installation carries the same creature
settings: at startup each process ends, as `not_served`, the unfinished drafts of every workspace
it knows but does not serve, so a process started with the worker off, a shorter list or no model
client would end another process's drafts, one being drafted included.

The words leave the live rows when a draft ends, but copies outlive them: PostgreSQL keeps dead row
versions until vacuum and the write-ahead log keeps them until it is recycled, and a backup taken
while a draft was queued or running keeps the job's words for as long as that backup is kept. A
restore from it brings them back into the live job until the draft is played or the restored
installation's startup ends it. A draft of a workspace that no process knows any more (no token,
account or list names it) waits with its words until one does.

## A creature in a society

A creature its workspace keeps lives in a society of things as any being does
([society contract](synthetic-society-contract.md#the-society-of-things-v7)): placed by its kind's
digest, it arrives at the open node nearest where it was put, walks, rests, visits, stands and
talks by the routine as far as its kind lists each, says lines and uses what it holds with where a
decider chooses, may be decided for by a model or played by a person where its kind allows, and
leaves when its author removes it. Nothing in the kind changes for this, so every creature a
workspace already keeps lives when it is placed.

**The run form.** A society never holds a kept kind's document. The kind's label, key and summary,
its plan's title and its recipe's appearance are words drafted from a person's, which an erasure
promises gone at once ([below](#a-workspaces-own-things)), and a society's records are bound to
each other by digest and cannot be blanked in part. What a society runs of a kept kind is its
**run form**, `exulanica.thing-kind-run/v1`
([`run_forms.py`](../exulanica/things/run_forms.py)), built by code from the kept kind, the drafted
plan it names by digest and the recipe that plan was built from, each read again from the
workspace's store (`ThingStore.run_form`):

| Field | Holds |
| --- | --- |
| `reference` | `{"source": "workspace", "sha256"}`: the digest of the kind's document alone |
| `class` | `being` |
| `body` | the plan's digest; the kind's four figures (`extent_mm`); the plan's reach and its sockets by key, how many each holds and how long and thick a thing; the recipe's posture, spine, heads, limbs by role with their counts and segments, tail, what it holds with and its colours, each a number or a body grammar name |
| `moves`, `abilities`, `offers`, `deciders` | as the kind states them |
| `routine` | the kind's weights, and the kinds whose holders it follows where they are shipped kinds |
| `label`, `summary`, `named_by` | its body name and its body sentence, and the names catalog that gave them (`body-names/v1`) |

It is written field by field, never the kind with fields taken out, and it never holds the kind's
key, version, label, summary or origin, the plan's name or title, the recipe's appearance, a look,
or a digest of words. Its reader (`read_run_form`) holds every string to a digest, a movement
module the body grammar's movements name, a socket's key, or a name of the body grammar or the
things catalogs; holds every parameter's name to what its ability or offer declares (a movement
module declares none); bounds every list by its catalog; and holds the label and the summary to
exactly what the body's own figures give under the names catalog `named_by` states. So no field of
a run form can carry free text, whoever composed it. The naming functions and the reader are frozen
with the profile and the names catalog version a form states: a stored form is read by them as
written. A later run
form is a new profile beside this one, and a society keeps the one its input recorded.

**Named by its body.** [`body-names.v1.json`](../assets/catalogs/things/body-names.v1.json) states
how a body is named and described, each entry with its reason. A body name is at most two features
in rank order (heads past one, with how many; wings; legs, with how many; tentacles; arms; fins; a
long body with no legs) and the noun: "winged four legged creature", "three headed four legged
creature", "long bodied creature". A body sentence states its length and height in metres, its
parts by count, a tail where it has one, whether it moves over the ground and what it carries with:
"A creature about 12 m long and 2.6 m high with one head, two wings, four legs and a tail. It moves
over the ground. It carries a thing in its jaws." The society names the being by its body name,
numbered from the second present as any kind's beings are, its summaries and every option naming
it say that name, and a decider asked for it is told that name and that sentence as what it is.
Two different creatures may share a body name. The name and the summary its maker's words gave it
are the workspace's alone to show: the page asks the workspace's store for the kind by the digest
the state names and says its label over the being, in the headers of the lines it says and hears,
and on its card, and says nothing of it once the store no longer answers.

**Its card.** The card of such a being
(`GET /world/versions/{version_id}/society/things/{thing_id}`) states what it can do here, where
it is, what it holds, who decides for it (with whether a model may be chosen) and the lines it
said, from the society, as any being's card does. Its `kind` states `source` `workspace` and the
digest, `held` (whether the workspace still holds the kind), the label and summary the workspace's
store holds for it, its body's name and sentence (`body`), and `drafted_by`: the provider, model
id and served name of the open model that drafted it, from the kind's origin. Its look is its
sketch, by digest, and `kind_origin` states its class and that model and nothing of the words.
Where the workspace no longer holds the kind, `held` is false, the label and summary are its
body's, and `drafted_by` and the look are null with no looks listed; the page then says it has no
look to be drawn in.

**Erased.** Erasing a creature ([below](#a-workspaces-own-things)) removes its rows from the
workspace's store as before. Each version of the workspace that holds a society and a placed thing
of that kind, not removed, is then told as an authored edit tells it: the society's next input
leaves the thing out and names it, by its placed id, among those gone, and the being leaves in that
society's next minute (`thing_departed`, `kind_erased`), a recorded event like any departure. No
record of the society is changed or deleted, since none ever held a word of the creature; the
society replays as before. What stays in a society that ran the creature: the kind's digest (as the
erasure's own row keeps it), its body's figures, names and sentence, the lines beings said to or
about it, every copy already sent to a hosted model provider, and the placed thing's own id, which
is its author's text (up to 200 characters, kept in the version, its edits and every input, state
and event that names the thing): the page names a creature it places `creature:` and the first
eight characters of its draft's id, and a caller of the route who names a thing after its creature
has put that name where no erasure reaches. A version that cannot be told (its input cannot be
composed at that moment) is passed by; its society loses the being at its next input all the same,
because a thing whose kind is gone is left out whoever composes it, and asking for the erasure
again (the route answers 404, as for any kind the workspace does not hold) tells it again, appending
nothing to a society already told. The erasure stands whatever a society does. A thing whose kind
its workspace still holds but whose run form cannot be built (its plan or recipe no longer reads)
is left out of the input too and is not named among those gone: a being that was it leaves as a
removed one does.

## A workspace's own things

A workspace keeps the things it made or admitted as the documents they were read as
([`thing_store.py`](../exulanica/world/thing_store.py), migration 0159): body recipes, the body
plans built from them, thing kinds and looks, each version appended once and never changed (an edit
is a new version) and removed only by an erasure (below), each row inside its workspace by row-level
security. Each document is read by its own reader before it is kept and again when it is read back,
at the digest its row states. A drafted recipe holds its figures, colours and the appearance drafted
with it; the digest of the words it was drafted from is held only in its plan's and its kind's
origin, and the words nowhere. The things the product ships stay files and are never rows here, and
no row takes a shipped key: a shipped kind, plan or look resolves first, so a row shadowing one
would never be reached. A workspace keeps at most 128 kind versions and 256 look versions.

A look's container is held by digest in the workspace's own `looks` namespace of the
content-addressed store, and its row states what the container's reader measured: the static
container profile's admission for a `rigid_on_bones` or `static` look, the skinned reader against the
plan's own tree for a `skinned` one. A look whose kind draws no file is not kept here. Its licence
columns are read from the document's origin record, one source, and a share-alike look is kept only
with the credit its licence asks: its attribution, its authors and its licence's address, which the
store and the table both require.

Each intake checks everything before it writes anything: the documents and the container first,
then, under the workspace's lock, the caps and the versions already held. Then, holding the
container's own lock, which the purger also takes, it records the container in the looks
namespace's inventory (`look_object`) and commits, writes the container's bytes, and writes the
rows naming them in one transaction that takes the workspace's lock and asks the caps, the versions
and whether the workspace is being erased again. A row never names bytes the store lacks, and the
store never holds bytes its inventory lacks. A keep refused after its record (another keep reached
a cap first, or the workspace is being erased) leaves the container recorded and unreferenced until
the workspace's erasure purges it.

| Path | What it keeps |
| --- | --- |
| `keep_creature` | A creature drafted from words: its recipe, plan, sketch with its container, and kind, the four rows in one transaction |
| `admit_look` | A look made elsewhere (generated, imported or uploaded) with its container, read by `read_admission` and then by its intake's own check. `read_admission` makes every check that needs no database: the look's reader, a shipped key, a container that is not the look's or that its reader refuses, the line rule on the label and on the origin's words (attribution, the licence's address, authors, source references and revisions, the maker's provider, model, prompt version and bridge), and a share-alike look's credit |
| `erase_creature` | An erasure of a creature drafted from a person's words, by its kind's digest, under the workspace's lock: a `creature` tombstone, and one row naming the kind by that digest and that tombstone and holding nothing a person wrote, whose trigger deletes at once, as the definer owner, the kind and, with its drafted plan, the plan, its recipe and every look drawn on it with their withdrawals (migration 0172). A society that ran a being of it is told afterwards and holds nothing to erase ([a creature in a society](#a-creature-in-a-society)). Asked by the person who drafted the creature or by an owner of the workspace, and refused as `kind_not_yours` to anyone else. A restore carries the row and replays the tombstone, so a restore from an older backup loses the creature again |
| `withdraw_look` | A withdrawal of one of the workspace's own looks, once, with a reason in one line, naming the version and the digest it was kept at. The look stays held and is never admitted again; a choice naming it stays, as choices are appended. A restore carries the withdrawal ([withdrawal catalog](../exulanica/deletion/withdrawals.v2.json)), so a restore from an older backup never admits the look again |

Every read passes a withdrawn look by unless it asks for withdrawn looks. A kind naming a withdrawn
look still reads, as it stays what it is, so a creature whose one look, its sketch, was withdrawn
reads with no look to draw.

An erasure removes at once every row that holds a person's words or words drafted from them: the
kind's label and summary, the keys made from the label, the plan's title, the recipe's appearance
and the digest of the words, which only the plan's and the kind's origin hold. A recipe another
creature's plan still names stays, with its figures, colours and appearance and no digest of either
creature's words, and a plan another kind names stays with it. The containers of the looks it
deletes are enqueued as `look` purge jobs of its `creature` tombstone, a sculpted or imported look's
as the sketch's, and `exulanica-purge` destroys them within its bound; until then nothing serves
one, because a container is served only through a look row. A container that a look the workspace
still holds names, the same creature kept again, stays, and its job waits until that look is
erased too. A sketch container holds geometry, the body grammar's part and bone names and the
palette's colours, never a person's words: `tests/test_thing_store_words.py` checks every string
the sketch writer writes, across the grammar, against the grammar's own vocabulary. Every container
the store writes is recorded in the namespace's inventory before its bytes, and that record
outlives its look. The workspace's own erasure, a workspace tombstone, erases every creature's rows
at once in the same way and enqueues every recorded container, its erased creatures' included.
A workspace erased before the store's erasure existed loses its rows when the migration that adds
the erasure runs, its recorded containers are enqueued on its tombstone, and that tombstone's
purge is complete again only once they are gone.
Two kinds of bytes no record names stay out of reach: a container a keep wrote before the
inventory existed and that no look row names, and one recorded after a backup set's database dump
and before its objects were copied, which a restore brings back with its bytes and no record (as
for a workspace's own assets).
Either tombstone's purge is complete only once its containers are gone. Once a workspace tombstone
is effective, nothing more is kept in that workspace. A thing's choice of look naming one of the
looks an erasure deletes stays, as every choice does, and is passed by, as a choice naming any look
the workspace no longer keeps is.

The erasure row keeps the kind's digest for as long as the workspace keeps it, so a restore can
match the kind again. The drafter answers the same words with the same document, so someone who
holds the row and guesses the words could confirm the guess by drafting them. A database backup
taken before an erasure keeps the creature's rows until the backup set passes its retention bound
([deployment.md](deployment.md#9-backups-and-recovery)), and a restore from it replays the
erasure.

A traveller who crosses in from an outside game arrives looking like itself only when its
workspace holds that look. A deployment builds the look from its own copy of the game's figure
(the bridge's look builder writes the document and its container, never committed), and the
operator admits the pair into each workspace that grants such travellers with
[`thing_store_command.py`](../exulanica/api/thing_store_command.py) (`admit-look`, `withdraw-look`
and `list`). `admit-look` reads the bridge's mapping file: its digest must be one that a bridge the
deployment declares pins (`EXULANICA_DOOR_BRIDGES`), and the door's mapping check reads it. The look
is admitted only when one of the mapping's looks names the look document's digest, and that entry's
source digest is among the look's ingredients, its SPDX identifier is the look's and its share-alike
mark is the look's. A document relabelled under another licence has another digest, and no mapping
names it. Without `--apply` each command makes every check that needs no database and writes
nothing: `admit-look` the look's, its container's and the mapping's (a look drawn on a plan the
workspace drafted is read only with `--apply`), `withdraw-look` its reason's.

A judge seed refuses a workspace that holds looks or thing kinds of its own, or a container an
erased creature left that is not yet purged: a look's container is not in the store a seed copies
from, and a drafted kind holds words drafted from a person's.

A workspace's own looks and kinds are served beside the shipped library
([`thing_store.py`](../exulanica/api/routes/thing_store.py)), each read needing `world.read`, and
each reaching only the requester's own workspace:

| Route | Answers |
| --- | --- |
| `GET /things/looks/{look_sha256}` | The look document held at that digest, its canonical bytes as the library serves its own, never cached |
| `GET /things/looks/{look_sha256}/container` | That look's container, verified against the digest the look names, tagged with the look's digest and revalidated before each use (`no-cache`): a revalidation is answered 304 while the look is held and 404 once it is withdrawn |
| `GET /things/kinds/{kind_sha256}` | The kind held at that digest, read again with its looks and plan resolved in the store, never cached |
| `GET /things/plans/{plan_sha256}` | The drafted body plan held at that digest, read again, its canonical bytes, never cached: what a page draws a held kind's figure on, since the shipped library holds only shipped plans |
| `DELETE /things/kinds/{kind_sha256}` | Erases the creature that kind was drafted for (`erase_creature`) and tells each society that runs a being of it, whose being then leaves (`kind_erased`); asked again for a creature already erased it answers 404 and tells any society not yet told, needing `world.write` and `deletion.write`, for the person who drafted it or an owner of the workspace: an owner by the membership record (a browser session held in the `owner` role), anyone else only a creature their own actor drafted, so a guest, or a bearer token, which holds no membership, erases only its own, and anyone else's ask is 403 `kind_not_yours`. 204, after which its kind, its look and its container answer 404; 409 `kind_changed` for a row the database refuses, 409 `restore_sealed` while the installation is sealed for a restore, and 409 `busy` with `Retry-After` while another transaction holds the workspace |

Another workspace's look, kind or plan, a withdrawn look and an absent digest all answer 404
`unknown_reference` alike, and a renderer then draws the kind's first look. The container is
addressed by its look's digest, never its own, so only a held look's container is served, and
withdrawing the look stops it, in a browser's cache as well.

`admitted_look` answers the look a workspace holds at exactly the key, version and digest asked,
read again on the caller's connection, or nothing: no such row, another digest, withdrawn, a
document the reader now refuses, or another workspace's. `admitted_look_by_digest` answers the same
for a digest alone, which is how a world names a workspace's own look: never by a key a person's
words made. Neither takes a lock.

Refusals, by code: `thing_key_shipped`, `thing_version_exists`, `thing_cap_reached`, `look_refused`
(the look reader's own sentence), `look_without_container` (a look whose kind draws no file),
`look_container_mismatch` (bytes that are not the container the look names),
`look_container_refused` (the container profile's reader refused it), `look_text_refused` (a label
or an origin word that is not one plain line), `look_credit_missing`, `look_not_admitted` (the
intake's own check), `look_unknown`, `withdrawal_reason_refused`, `kind_unknown` (an erasure of a
kind the workspace does not hold), `kind_not_yours`, `kind_changed`, `restore_sealed`,
`workspace_erased` (keeping anything once a workspace tombstone is effective), `keep_in_transaction`
(a keep asked on a connection without autocommit or inside an open transaction, refused before
anything is recorded) and `look_plan_gone` (a look whose creature was erased while it was kept).
Each refuses with no row written; only a keep refused after its container was recorded leaves that
container, as above.
The command's own are `mapping_refused` (a file that is not a mapping) and `mapping_not_admitted`
(no declared bridge pins it).

## Scenes

A scene (`exulanica.scene/v1`) is data a server lays into a saved world: things by their shipped
kind and version, each placed from where a person arrives in the world (`right_mm` to their right,
`forward_mm` ahead and `turn_microradians` counterclockwise seen from above, where a turn of 0 faces
the person arriving, as an object a person places in front of themselves turns to face them), the
open model each of its beings is given as a mind, the society engine it lives on, the ground it is
laid out for (a starter, a generated town or a site) and, optionally, the gate travellers come
through with the mind they are given there. Each version ships as
`assets/catalogs/scenes/<scene>.v<N>.json` with a line in `scenes.lock.json`
(`exulanica.scene-lock/v1`) naming its digest, the SHA-256 of its canonical JSON; a shipped version
never changes. The reader ([`scenes.py`](../exulanica/world/scenes.py)) refuses a scene by name: a
thing named twice or by an id a placement refuses, a kind not shipped (`scene_kind_unshipped`) or
one an author may not place (`scene_kind_not_placeable`), a place more than a kilometre to either
side of the arrival or ahead of or behind it (each bound by itself), a mind for anything but one of
its beings or by a decider its kind does not allow, a model the manifest does not declare, a
travellers' gate that is not one of its things offering arrival, an engine the engine table does not
state or no longer makes, and minds on an engine that is not a society of things, which alone seats
placed beings.

The scene dressing ([`scene_dressing.py`](../exulanica/api/scene_dressing.py)) lays a scene into a
saved world from the world's own arrival, through the paths a person's edits and choices take. Each
thing is placed with the things route's edit, inside the binding to the saved entry every authored
edit runs in, so the world reopens with it. The owner's own edits stand: a thing already placed as
the scene places it is left as it is, and so is one of the same kind the owner moved
(`things_left_moved`), one the owner removed (`things_left_removed`) and one whose placing the owner
undid (`things_left_undone`); only a thing of another kind under the scene's id is refused
(`scene_thing_placed_otherwise`), and an edit's refusal comes back by the code the authored-edit
routes answer with. The version's society is then made as the society route makes one, and each mind
is recorded as the owner's choice under a key drawn from the scene's digest, the society and the
thing, the same key the demo builder uses, so asking again records nothing new. A refusal of the
society, such as a host that does not offer the engine (`society_engine_not_offered`) or one with no
adapter for a society's first input (`unavailable_society_input`), keeps the things placed and comes
back by the code the society routes answer with. A model the people role does not take is refused
for that being alone, by its code, and the routine decides for it; the owner's later choice of a
mind stands, since the latest choice decides. A scene laid out for another ground than the world's
is refused (`scene_ground_mismatch`). The caller has already found the actor allowed to change the
world and to cause what its minds spend, and passes the workspace's connection idle: each step
commits its own. The mind a gate gives travellers is the door's: it is recorded with the grant when
the world's owner opens the gate, never by the dressing.

## Drawing

The browser draws a thing from its look, never from what it is
([`things/`](../web/packages/atlas-react/src/playcanvas/things)). It reads the host's thing library
by digest: the list names every kind, look, container and the body plans catalog by the SHA-256 of
its bytes, and every answer is hashed again and refused by name when it is other bytes, so nothing
substituted or truncated is read. One figure draws each look kind:

| Look kind | Drawn as |
| --- | --- |
| `catalog_person` | One of the world's people, drawn from the thing's id by the people catalog's draw |
| `skinned` | The rigged container with its own clips; standing, walking and running blend by ground speed (`rig.ground_speed_mm_per_s`) and the clips' cadence follows it as a catalog person's does, so a planted foot moves as fast as the ground: slower than its walk clip's pace the walk plays slower, down to half its cadence, and only below that fades into standing; slower than 0.02 m/s the figure stands. A clip plays at most twice its pace, and a motion with no clip is drawn idle. A rig with no clips at all, as a creature sculpted for its own plan has, is posed by the same solved gait as `rigid_on_bones`, its skin following its joints; it must rest translation-only with each joint hung from its plan parent's, and is refused by name otherwise |
| `rigid_on_bones` | The container's `bone:<name>` nodes, each hung from its nearest dressed ancestor in the body plan's parent table, posed procedurally |
| `light` | An omni light of the look's colour, intensity and radius, a core and a glow, floating 1,250 mm over the thing's point and drifting within its radius (presentation only) |
| `static` | The container at the thing's place, turned by its placed yaw as an authored object is, at its kind's size: scaled uniformly so its longest side is its kind's box's longest side, the side the hands fit to a socket; within 1 mm a metre of that it is drawn as authored |
| `look_role` | The engine's box primitive in the kind's box: no style pack dresses a thing yet |
| `none` | Nothing; the thing keeps its place |

A body is drawn at its look's natural height kept inside its kind's height range, so a look never
makes a kind taller or shorter than the kind allows; an object is drawn as long as its kind says, so
a thing in a hand is the size the society fitted to that hand, whatever unit its container was
made in. The look keeps its own proportions, so a container shaped unlike its kind's box may reach
past the box's narrower sides. No bone is named in the drawing: a skeleton's
limbs are read from its shape and its plan's sockets (a chain ending near the ground is a leg, one
carrying a socket an arm, the one ending highest the head), so any body plan's skeleton is read the
same way. Standing figures breathe and turn their heads; walking figures step in their skeleton's
gait, clocked by the distance walked so a planted foot never slides: slower than 0.5 m/s at the
look's height the steps are drawn shorter and come as often as at that pace, the clock true to the
shortened stride down to a tenth of the full one. No thing's figure steps for a turn, so a thing
that is going nowhere stands however it is turned; under reduced motion they stand still.

A version's placed things stand where it places them, in the frame their region is drawn in: the
region a saved world's people live in, or an authored object's region root. A thing in a region
the world does not draw, a document the library does not hold at its digest, a look kind the page
does not draw or a container that does not read is drawn as nothing, its reason kept by name
(`ThingLayer.misses`), never stood in for.

Where a society of things runs (`exulanica-society/v7`), its people are the society's crowd's, which
walks everyone along their recorded paths as it walks every society's people: at their own walking
pace, then standing, or evenly over the presented minute where the walk is too long for that
([character representation](character-representation-contract.md#drawing-a-societys-people)). A rigged
look's declared walk speed, at the height it is drawn, is the pace its person is walked at; a look
that declares none is walked at the catalog person's pace for the person's id, and so is a minute
read before the person's figure is made, when its look's pace is not yet known. A person whose look
is not the people catalog's is drawn by its own figure, in full wherever it is within the crowd's far
radius and ranked before the world's people for the full places of the measured budget; a placed
being's standing figure is then not drawn. A placed being faces as it was placed until it first
walks, by the same rule the layer turns it by before a society holds it: its yaw turns the look's
front from +Z, so at yaw 0 it faces +Z. Each object stands where the state puts it, its plan point
turned by its yaw, or is held in the socket the state names, its grip at the socket's place; an
object the state does not list is not drawn. A thing of a kind its workspace keeps that the state
lists among neither its things nor its people (a society made before the thing was placed and not
yet told, or one that does not take things in) stands where its version places it while the
society is drawn; one the state lists as a person is the crowd's, drawn in its kind's first look,
its sketch, asked of the workspace's store by the digest the state names. A rigged look whose rig names a hold clip stands in it
while it holds something. A thing that changes hands, or is picked up or put down, moves when the
people it passes between have walked to where the state ends their walks: the later of the two
drawn walks for a hand-over, the actor's own for a pick up or put down. Until then it is drawn where
it was, in the giver's socket or on the ground; a pair already in reach exchanges at once. The
event's `at_ms` is the simulation's own instant and is not what the drawing waits on: the crowd
walks each person at a walking pace, or evenly over the presented minute where the walk is too long
for that, the state's budget being a bound.

A visitor who crossed in is drawn stepping out of the gate it came through, from the gate to where
the state first places it, and back into the gate when the state no longer holds it, carrying what
it carries out, which leaves the hand only when the visitor goes. It steps at its own walking pace,
as the crowd walks everyone: its look's declared walk speed where it has one, taken up as soon as
its figure is made, and otherwise the catalog person's for its id. Its
gate is the placement its `thing_arrived` event names, at that placement's position; the page reads
a minute's events just after its state, so a visitor who has just crossed in is unseen until its gate
is read, at most 3 seconds. Neither step is in the state: the state places a visitor beside its gate
in the minute it arrives and has it gone in the minute it leaves, so the drawing presents a departure
for the seconds the step takes after the minute that records it: at most 5 m at the visitor's pace,
which is 5 s at a catalog person's slowest 1.00 m/s and 9.9 s at the armoured knight's 0.504 m/s.
A visitor more than 5 m from
its gate, or one whose arrival the page never read, appears and goes where it stands, as does everyone
under reduced motion.

A thing wears the look chosen for it where one is, from the looks chosen for its version's society
(`GET /world/versions/{version_id}/thing-looks`): a person in the crowd, a placed thing in the layer;
a thing with none wears its kind's first look. The choices are read when a society of things is first
drawn and then once a minute while it is drawn, playing or paused: one private read a minute for each
open world page. A look chosen on the page is read at once: once its look route answers, the chooser
raises `exulanica:thing-look-chosen` on the shell, naming the thing by its id in the society, and the
page reads the choices outside the minute (looks chosen while a read is under way are read once more
after it) and draws what the read lists, not what was sent. A drawn minute that brings in a visitor
the last read was not asked with is read at once too: the crossing recorded the visitor's look before
that minute, so the visitor arrives in the look its crossing chose, never in its kind's first until
the next minute's read. The minute's read brings a choice made in another browser, and a choice the
read no longer lists (one naming a look the workspace withdrew) leaves, the thing returning to its
kind's first look. A thing wearing a look its workspace keeps is listed apart (`workspace_looks`) by
the look's digest alone; its key and version are its own document's, read by that digest and held to
it, and one no longer held is left out. A person whose look changes is made again where they stand,
and nobody else is; what they hold stays in their hand, the old figure letting it go and the new one
taking it.

A kind or look the shipped library does not hold at the digest named is asked of the workspace's
own store (`GET /things/kinds/{sha256}`, `GET /things/looks/{sha256}` and its `/container`), only
then: its document is held to that digest and must name the key and version asked for, and a held
look's container is held to the digest its own document names. A thing placed by a workspace kind's
digest alone has its kind asked by that digest, its key and version its own document's, and is drawn
on the drafted body plan the kind names by digest (`GET /things/plans/{sha256}`), held to that
digest and to the plan its look names; a thing the version marks `gone` is drawn nowhere. A 404
there is a look or kind the workspace does not hold, drawn as any other miss. The page keeps what it read by digest while it is
open and asks again each time it is opened, so a look the workspace withdraws is no longer drawn from
the next time the world is opened.

Who runs each person of a saved world's society is marked over them, by one decision the thing card
makes too ([`composition/thing-marks.ts`](../web/packages/app/src/composition/thing-marks.ts)): a
person whose model is asked (chosen for them, and refused neither by the host nor for them) wears an
`AI` pill with the first word of the model's served name; a visitor its own program decides for
wears its bridge's mark as the door lists it here: `from` and the bridge's label for a game, read as
decided from outside (no person is claimed, which nothing a game sends shows), an outlined `AI`
pill for an outside agent, and `from outside` for a bridge the door does not list. An outside agent's pill names it in its own words, as its program last said them at the door
(the world's grants, `GET /door/grants`, read at most once a minute while such an agent is drawn
without a name; set as text only, a long name cut short on the pill and read whole), and says
`agent` until its program says. A visitor the world decides for (its arrival's `decided_by` is
`world`) is marked by who decides here: the `AI` pill naming the model asked, followed in the same
pill by `· from` and its bridge's label, or, while its routine runs it, `from` and the label alone,
read as run by this world. Everyone else, and every object, wears none. The pills are part of the
page, not the picture: a fixed pool of nodes placed each frame over the box a person is drawn and
picked by, read by a screen reader in the card's words and
picked by a click as by aiming. The model's short name and the person's kind show over the selected
person, a speaking one and the three nearest marked people within 12 m drawn on screen; no pill is
drawn beyond 60 m. A pill that would cover a nearer person's stands just above it (2 px apart), so two
people in line from the camera both read; the nearest stays over its person. When a person plays a
being (Play this one; the app has no screen to start it yet: see below), it is marked by who decides
now, before its mind: a `You` pill in the world-mark person colour for the one playing it and `Played`
for anyone else, read as played by you or by another person (and, for a visitor the world decides for,
from where, in the words read only); the one playing also sees a steady ring in the same colour at its
feet as the crowd draws it, and another on the ground where its next walk goes, each on a dark edge in
the person ink so it reads on pale ground. Who plays is read from the models read's person choice,
which says only whether the viewer is the one playing, never who.

Each line a being says is drawn over it as it is said, from the society's `said` events read with
each minute: only lines said after the page first read the society, each once, oldest first, at most
four bubbles at once and one per speaker, each shown for two to nine seconds by its length. A line's
words are set as text only. The bubble opens with the line's own mark, decided from the line's record
by one function the thing card shares (`lineMarkOf` in
[`composition/thing-marks.ts`](../web/packages/app/src/composition/thing-marks.ts)): a model's line is
always an AI's, naming the model only where its event names it, so the speaker's model now is never
claimed for an older line, and keeping where a visitor the world runs came from; an outside
program's line wears its speaker's mark; a line a person said while playing a being wears the
`Person` pill, read as played by a person, never naming who (no event names the account). Its header
says who said it to whom by the library's kind labels, numbered only where more than one of a kind is
drawn, then the model where named, or that a person played it
([`composition/thing-lines.ts`](../web/packages/app/src/composition/thing-lines.ts)). Lines cost no
request of their own: the events are read with the minute.

Aiming and pressing E picks the nearest drawn thing or person along the ray. A picked thing raises
one event on the shell, `exulanica:thing-pick`, whose detail names it by the version's id, the
society's thing id and its person id where each exists, and how it was picked; the same event with
no detail clears the pick. The picked thing wears a ring in the design tokens' signal colour.

## What is not built

These are material limits of the boundary above, not partial behaviour:

- The society of things ([society contract](synthetic-society-contract.md#the-society-of-things-v7))
  reads a placed thing's kind, places its beings, lets visitors cross in and leave, says the lines
  its beings' deciders choose and does the hands acts they choose or the world's owner asks for by
  a direct request. A being follows another only where a person playing it chooses to: no model or
  outside program is offered following yet (the engine's terms state no follow action), the
  routine never follows (so a lantern spirit's `follow_holders_of` is unread), and no direct request
  asks it. The routine says nothing and uses no hands; only a model chosen for a being, a visitor's
  own program, or the world's owner's direct request does.
  A visitor the world decides for takes no person's direct request yet, and nobody in the app can
  take a being over and play it.
- A workspace's own kinds and looks are kept and served (a creature's by the creature route, a look
  made elsewhere by the operator's command, and a route erases a drafted creature). A thing may
  wear a look the workspace keeps, by its digest; nothing yet shows a picture of one (`preview` is
  null).
- A creature in a society ([above](#a-creature-in-a-society)) walks at the people's pace whatever
  its body: no society reads a pace from a body yet. Its routine is the purposeful routine held to
  the abilities its kind lists; the weights drafted with it are read by nothing, so a creature
  whose kind lists none of rest, visit, stand and talk waits where it is. A decider is told its
  body, never a temperament: nothing drafts or carries one. The page poses its sketch by guessing
  each limb's role from its shape, not from the chains its plan states: a chain that carries a
  socket is read as an arm, so a jawed head and its neck are posed as an arm is; no role is a
  wing, a tail or a tentacle; a body with no legs has no walk; and a being faces along its last
  step with no turning rate, so a long body turns about its middle at once. It wears only its sketch: a
  choice of another look for it is refused (`look_unfit`). A creature placed in a world whose
  society is not a society of things (a living town already made) is taken in by nothing and
  stands where it was placed.
- A model's line names its model only where its said event records one (a society made since its
  modules are recorded keeps it) and the page has read that model; otherwise it says `an AI model`.
  A person in flight wears no pill: the flock draws them, not the crowd.
- No creature flies, swims, climbs or burrows: the grammar states those movements and refuses them
  in words. A floating body therefore cannot move at all yet.
- No creature wears a sculpted look: its sketch is its only look. The route that makes one (route C
  of [generated appearance](generated-appearance.md)) is built. In its two pre-registered rig
  trials one and then four bodies of eight counted, against the five the rule needed, so the sketch
  stays every creature's default. Nothing in the product asks for a sculpted look yet. A look request is written by
  [`creature_looks.py`](../exulanica/things/creature_looks.py) from a creature's body and sketch.

- Nothing calls the scene dressing yet: a guest's arrival world dressed with a scene, named by the
  arrival catalog, is planned with the society of things on a public server.

## Implementation and evidence

| Part | Source | Tests |
| --- | --- | --- |
| Catalogs | [`catalogs.py`](../exulanica/things/catalogs.py), [`assets/catalogs/things`](../assets/catalogs/things) | `tests/test_thing_kinds.py`, `tests/test_catalog_provenance.py` (every entry says why it exists) |
| Thing kinds | [`kinds.py`](../exulanica/things/kinds.py) | `tests/test_thing_kinds.py` (each refusal by name, against a positive control) |
| Looks | [`looks.py`](../exulanica/things/looks.py), [`authored.py`](../exulanica/things/authored.py), [`pieces.py`](../exulanica/things/pieces.py), [`recipes`](../assets/catalogs/things/recipes) | `tests/test_thing_kinds.py`, `tests/test_thing_looks_and_origins.py` (each authored container written again and admitted, a blocky figure's joints, a static look inside its box), `tests/test_thing_recipes.py` (each recipe read or refused by name, the blocky figures one stated body, no things module naming a shipped key) |
| Imported looks | [`import_looks.py`](../scripts/things/import_looks.py), [`assets/things`](../assets/things) | `tests/test_thing_imports.py` (each imported look held to its committed container, receipt, licence, manifest and source reading; a figure's rig naming only what its container holds, its clips in place, its height; an imported static look inside its kind's box; the merge on a small figure made in the test, with a joint the figure lacks and a covered region; every file shipped in the API image), `tests/test_thing_skinned_looks.py` (every shipped skinned look read by the skinned container reader) |
| Origin record and vocabularies | [`origin.py`](../exulanica/things/origin.py), [`vocabularies.py`](../exulanica/things/vocabularies.py) | `tests/test_thing_looks_and_origins.py` |
| Translation manifests and lines | [`manifests.py`](../exulanica/things/manifests.py), [`lines.py`](../exulanica/things/lines.py) | `tests/test_thing_looks_and_origins.py` (words held to the line rule, a look's import, each refusal against a positive control) |
| Shipped kinds and looks | [`shipped_things.py`](../scripts/things/shipped_things.py), the lock `kinds.lock.json` | `tests/test_thing_kinds.py` (`--check`), `tests/test_placed_things.py` (every shipped version at its locked digest; a changed, unlocked or missing file refused) |
| The thing library | [`thing_library.py`](../exulanica/world/thing_library.py), [`things.py`](../exulanica/api/routes/things.py) | `tests/test_thing_library.py` (every shipped document and container by digest, an imported container by the digest its look pins, each refusal against a positive control), `tests/test_thing_library_routes.py` (a session required, the bytes a digest names, 404 otherwise), `tests/test_image_ships_startup_reads.py` (every file it reads ships in the API image) |
| A thing's card and its look swap | [`thing_card.py`](../exulanica/api/thing_card.py), [`world_things.py`](../exulanica/api/routes/world_things.py), the said-events index of migration 0167 | `tests/test_thing_card_postgres.py` (a knight's card lists only what running modules act on, an object's lists no decider or lines and only its kind's looks; choosing a look answers the same minute and state with only the look changed; a look for another body or object refused by name, nothing written; an unavailable input refused 424 as the society read is, nothing written; a look a release dropped passed by and another still chosen; a line said under an input no longer available refused as the events read refuses it), `tests/test_existence_oracle.py` (a stranger cannot tell another workspace's thing from an invented one) |
| Look choices | [`thing_looks.py`](../exulanica/world/thing_looks.py), [`world_things.py`](../exulanica/api/routes/world_things.py) (the read), migrations 0156 and 0167 | `tests/test_thing_looks.py` (a shipped look fit for the kind, each refusal by name), `tests/test_thing_looks_postgres.py` (as the deployed writer: one look per crossing, the newest per thing, no change or removal; the table's shape and its append-only trigger; another workspace sees nothing; the route), `tests/test_workspace_looks_worn_postgres.py` (a workspace's own look listed, worn and passed by once withdrawn, for the choice before it; licences as their origins state them; another workspace's look answered as one nobody keeps; a look withdrawn between two reads), `tests/test_thing_look_source_migration.py` (0167 over stored choices; the said-events index and its use) |
| Placed things | [`placed_things.py`](../exulanica/world/placed_things.py), the object repository, [`world_things.py`](../exulanica/api/routes/world_things.py), migrations 0152 and 0188 | `tests/test_placed_things.py`, `tests/test_placed_things_postgres.py` (as the deployed writer: place, move, remove, undo and place again; the kind fixed by the table; another workspace sees nothing; a branch keeps them; the routes' refusals by name), `tests/test_edit_kind_undo_postgres.py`, `tests/test_placed_workspace_kinds_postgres.py` (a creature placed by its kind's digest alone, the row naming no key or version; another workspace's kind and an invented digest refused alike with nothing written; the table holding where a thing's kind comes from; an erased creature's thing gone, its move refused by name and its removal standing, and the same creature kept again not bringing it back; the plans route serving a held plan and answering 404 alike; a shipped thing stored before 0188 reading as it always was; a world holding only a creature not made a world of things; a thing gone by its kind's row alone, with no erasure recorded; undoing a gone thing's removal keeping it gone and undoing its placing taking it out; a branch holding a gone thing gone after its creature is kept again), `tests/test_society_thing_inputs.py` (a thing of a workspace kind left out of a society's input), `tests/test_walking_surfaces_v3.py` (a creature left out of a town's v3 input, blocking and offering nothing), `web/packages/app/test/things-composition.test.ts` and `web/packages/atlas-react/test/things-workspace-kind.test.ts` (the page reading a workspace kind by digest, its held plan, and drawing a gone thing nowhere) |
| The society of things | [`society_things.py`](../exulanica/world/society_things.py), [`society_thing_inputs.py`](../exulanica/world/society_thing_inputs.py), [`crossings.py`](../exulanica/world/crossings.py), the things composition in [`society_authored_ground.py`](../exulanica/world/society_authored_ground.py) and, on a generated town, in [`society_walking_surfaces.py`](../exulanica/world/society_walking_surfaces.py), migrations 0151 and 0169 | `tests/test_society_things.py` (genesis, a minute equal to the planner's, placed beings, crossings, the state check), `tests/test_society_thing_inputs.py` (the composition and its shape), `tests/test_society_things_postgres.py` (through the routes: made by name, an edit reaching it, a visitor crossing in and out, replay), `tests/test_outside_deciders_postgres.py` (a visitor decided for by its own program), `tests/test_traveller_choices_postgres.py` (a visitor the world decides for, by its gate's travellers' choice), `tests/test_society_request_rule_parity.py`, `tests/test_walking_surfaces_v3.py` (a town's things: what blocks, what is offered, what is unreachable, the town's v1 and v2 inputs unchanged), `tests/test_walking_surfaces_v3_postgres.py` (a society of things on a town through the routes, replayed; the input checks), `tests/test_town_target_names.py` (what a town's place calls a premises or a bench on its targets, an input from before the field, a name never moving a destination, every label lower case) |
| A creature in a society | [`run_forms.py`](../exulanica/things/run_forms.py), [`body-names.v1.json`](../assets/catalogs/things/body-names.v1.json), [`society_kinds.py`](../exulanica/world/society_kinds.py), `ThingStore.run_form` in [`thing_store.py`](../exulanica/world/thing_store.py), the composers' `made_kinds` in [`society_authored_ground.py`](../exulanica/world/society_authored_ground.py) and [`society_walking_surfaces.py`](../exulanica/world/society_walking_surfaces.py), the things phase in [`society_things.py`](../exulanica/world/society_things.py), the made being's card in [`thing_card.py`](../exulanica/api/thing_card.py), the erasure telling societies in [`thing_store.py`](../exulanica/api/routes/thing_store.py) | `tests/test_thing_kind_run_forms.py` (each fixture creature assembled under nonsense words: none of them, nor the drafting model's provenance, the recipe's digest or the plan's title, in its run form; every string of a run form in a vocabulary read from the catalogs' own files; each body's name and four bodies' sentences written by hand; its sockets the plan's own and its figures the fixture's; each field that could carry words refused by name; a kind, plan and recipe that do not belong together refused), `tests/test_society_made_kinds.py` (with no database: it arrives named by its body and by its kind's digest alone, the input and the state stating its run form once; two of one kind told apart by number; it walks and stays by the routine and an hour twice is the same bytes; it is offered what its kind lists and may be given a mind or played; a decider is told its body's sentence; jaws pick a sword up into `mouth` and a body that holds with nothing is offered no hands act; it leaves the minute its kind is erased, for that reason, and the society goes on; an author's removal stays an author's removal; none of the nonsense words in the inputs, the states, the events or a decider's context, with a positive control; an input with no made thing keeps its bytes; the input's and the state's checks each refuse a made kind stated wrongly), `tests/test_society_made_kinds_postgres.py` (through the routes: a creature alone makes the world one of things and lives in its society, which replays; its card names it as its maker did with who drafted it and who decides, and refuses another look by name; erasing it appends an input naming the kind gone, its card then names nothing, the being leaves the next minute for that reason, the society replays, and no row of any table of the schema holds a nonsense word, which the same search found in the workspace's store before; a society that could not be told loses the being at its next input), `tests/test_placed_workspace_kinds_postgres.py` (a world holding only a creature is a world of things while its kind is held and not once it is erased), `web/packages/atlas-react/test/things-workspace-kind-standing.test.ts` (a being named by digest alone drawn by the crowd in its sketch; an erased kind a miss by name), `web/packages/app/test/visitor-notices.test.ts` and `thing-lines.test.ts` (a kind's reference read in either shape; a line's header naming a made speaker as the workspace's store does), `web/packages/app/test/thing-card-route.test.ts` and `thing-card-placed.test.ts` (the card's drafting model) |
| Creatures: recipes, plans, sketches, assembly | [`bodies.py`](../exulanica/things/bodies.py), [`sketch.py`](../exulanica/things/sketch.py), [`creatures.py`](../exulanica/things/creatures.py), [`body-grammar.v1.json`](../assets/catalogs/things/body-grammar.v1.json) | `tests/test_creature_bodies.py` (thirteen hand-written creatures: each body where its recipe says, a left limb the mirror of its right, each limb of a lying body hung from the stretch of spine beside it, the bone count the recipe's own sum, each refusal by name, the sketch read back from its bytes) |
| The creature drafter | [`creature_drafting.py`](../exulanica/selection/creature_drafting.py), [`creature-drafting.v1.json`](../exulanica/selection/creature-drafting.v1.json) | `tests/test_creature_drafting.py` (scripted replies: a pass with its provenance, a refusal repaired with its check's sentence, two refusals, a form outside the schema, a reply cut off in blank space), `tests/test_hosted_boundary.py` (its request carries no saved name) |
| A workspace's own things | [`thing_store.py`](../exulanica/world/thing_store.py), [`thing_store_command.py`](../exulanica/api/thing_store_command.py), the routes in [`thing_store.py`](../exulanica/api/routes/thing_store.py), migrations 0159 and 0172, the `looks` namespace and its purge in [`namespaces.py`](../exulanica/store/namespaces.py), the seed's refusal in [`judge_seed.py`](../exulanica/orchestration/judge_seed.py) | `tests/test_thing_store_admission.py` (with no database: a static and a skinned look read by their containers' readers, a broken rig refused; a look the reader refuses, a shipped key, a look that draws no file and another container each refused by name; the line rule on the label and each word of the origin, its licence's address included, the field named; a share-alike look refused without its attribution, its authors or its licence's address), `tests/test_thing_store_postgres.py` (as the deployed writer: a drafted creature kept whole and read back at its assembly's digests; no update or delete, even by the table's owner (the owner's TRUNCATE is not refused: no truncate guard like 0013's is attached); another workspace reads none of it and keeps its own; each table's row written only in its own workspace's context, even by a superuser; a shipped kind, plan or look key, another container, a held version drawn from other bytes and a full library of kinds or of looks each refused with nothing written, bytes included; a look kept only after its intake's own check, with its licence as columns; the table's own checks on a share-alike look's credit, a container profile and its look kind, a kind's plan digest and a withdrawal's digest; a withdrawn look passed by unless asked for, its kind still read, and a look the reader refuses withdrawn by its row), `tests/test_thing_erasure_postgres.py` (an erasure removes a creature's kind, plan, recipe, looks and their withdrawals at once and nothing of another creature, naming the kind by digest and its `creature` tombstone only; the rows go only through it, not by the runtime role nor the table's owner; a plan or recipe another still names stays, and a shared recipe holds no words digest; an unknown, foreign or somebody else's kind refused with nothing deleted and no tombstone; the same creature in another workspace untouched; the erasure waits for the workspace's lock; its containers, a second look's on the plan too, destroyed by the purge, which completes its tombstone; a container another creature or the same creature kept again names stays, its job waiting, or skipped when the look arrives while the purger waits for the container's lock; a creature tombstone reaching no capture, photograph, artefact or other creature, and a capture tombstone erasing no creature; a container recorded before its bytes, its purge waiting for them; a keep that dies after recording, or is refused after it, reached by the workspace's erasure; the migration's backfill recording containers kept before the inventory; a workspace tombstone purges every recorded container, an erased creature's too, completion waiting for it, a worker without the looks namespaces leaving it open, a capture tombstone not authorized; the purge command's worker destroying them; a database without the look question claiming every other kind; nothing kept after it), `tests/test_thing_store_words.py` (every string a sketch container holds, for every fixture creature and 160 recipes drawn across the grammar: names from the grammar's vocabulary, colours from its palette and nothing else but the format's own words), `tests/test_restore_replay_withdrawals.py` (a look withdrawn after a backup stays withdrawn, and a creature erased after a backup stays erased, its container purged by the replayed tombstone, through a real restore, as it does when the backup holds its withdrawn sketch or when the whole workspace is erased after it), `tests/test_thing_store_command.py` (a mapping admitted only when a declared bridge pins it and the door's check reads it; the intake's check on the entry's digest, source, SPDX identifier and share-alike mark and on the look being imported; a look document that is not JSON and a withdrawal reason that is not one line refused by the dry runs; against PostgreSQL, a dry run that writes nothing, a copy relabelled CC0 and public and an unpinned mapping refused with nothing written, the positive control, once only, a listing and a withdrawal), `tests/test_thing_store_routes.py` (as a deployment serves them: the document's bytes hash to the URL's digest; the container's bytes, tag and `no-cache`, a revalidation answered 304 with no body; a kind; another workspace's, a withdrawn, a revalidated withdrawn and an absent one all 404 alike, and missing bytes too; 503 without a look store; a writer's erasure, then 404 for its kind, look and container, a reader, a token without `deletion.write`, a stranger and an invented digest erasing nothing, nor an installation sealed for a restore; a session required), `tests/test_judge_seed.py` (a workspace holding a look, a kind or an unpurged container of its own is not seeded, and a schema without the inventory is read without it), `tests/test_existence_oracle.py` (a stranger cannot tell a held look or kind from an invented digest) |
| Drafting a creature from words | [`creature_drafts.py`](../exulanica/selection/creature_drafts.py), [`thing_creatures.py`](../exulanica/api/routes/thing_creatures.py), migration 0184, the seed's refusal in [`judge_seed.py`](../exulanica/orchestration/judge_seed.py) | `tests/test_creature_drafts_postgres.py` (as the deployed writer, the drafter's replies scripted: a draft queued, played and kept, naming its kind by digest, with no word of the request or the label left on the draft or its job; a refusal by code and the form's field, an unbuilt movement read in the grammar's own sentence; a refusal whose check quotes the label keeping only its code and field; the table refusing a sentence in either column; a drafter that does not answer; one draft open a requester; read by its requester alone; a draft no worker takes ended with its words blanked; a lost claim ends nothing; a workspace tombstone, written by the runtime role or by the owner, cancelling the workspace's unfinished drafts with their words blanked and nothing of another workspace or of another kind of tombstone; a worker whose draft was cancelled while it drafted keeping nothing), `tests/test_thing_creatures_routes.py` (asked, read as it goes, kept and served by the look routes; erased since, naming nothing of it; refused with its code, field and fixed sentence; absent to anyone else; refused by name before anything is queued; the grants it needs), `tests/test_judge_seed.py` (a workspace with an unfinished draft is not seeded; with the draft ended, it is), `tests/test_restore_replay_withdrawals.py` (a workspace erased after a backup has its drafts cancelled and their words blanked again by the restore's replay) |
| The skinned container | [`skinned.py`](../exulanica_pieces/skinned.py) | `tests/test_skinned_glb.py` (containers built in the test from struct packing: a positive control, then each rule broken alone and refused by name) |
| A creature's look request and its sculpted look | [`creature_looks.py`](../exulanica/things/creature_looks.py), `ml/appearance/exulanica_appearance/creatures/` | `tests/test_creature_sculpt.py` (each development creature's sketch filled, rigged, written and read back against its plan's tree; the creature job end to end with stand-in models, a body that is not its plan's refused by the rig with its measures in the receipt), `ml/appearance/tests/test_creature_rig.py` and `test_creature_route.py` (a box figure: every check against a positive control, fused legs refused with every measure, a missing leg, a turn undone to the degree, a stretched body refused with the fit it refused; the all-at-once rasteriser equal to the loop; the camera on each plan's front left; the sketch's voxels in TRELLIS's frame), `ml/appearance/tests/test_trellis_second_stage.py` (the second stage's call order, and each refusal of a structure and of a pipeline's signatures alone); the two rig trials on Nebius AI Cloud, [first record](evaluation/2026-10-07-creature-rig-trial.json) and [second record](evaluation/2026-10-07-creature-rig-trial-2.json), each held equal to what its script builds from its evidence (`tests/test_creature_rig_trial_record.py`, `tests/test_creature_rig_trial_2_record.py`) |
| Scenes and their dressing | [`scenes.py`](../exulanica/world/scenes.py), [`scene_dressing.py`](../exulanica/api/scene_dressing.py), [`assets/catalogs/scenes`](../assets/catalogs/scenes) | `tests/test_scenes.py` (every shipped scene locked at its digest; each refusal by name against the shipped scene; poses equal to the demo builder's, which shares no code with it, and a turned arrival's worked by hand), `tests/test_scene_dressing_postgres.py` (a starter dressed through the application: its things bound to the saved entry where the builder would place them, in the arrival's region, authored as fictional and placed by the owner, the society and each mind read back, a second dressing changing nothing, a thing placed as another kind refused, the owner's moves, removals and undos standing, a host without the engine, a society with no first input, a model the role refuses for one being alone, another workspace and a busy connection refused), `tests/test_demo_scene.py` |
| No creature in code | | `tests/test_no_creature_code.py` (with a planted name the scan finds) |
| Ability modules | [`registry.py`](../exulanica/abilities/registry.py), [`ability-modules.v1.json`](../exulanica/abilities/ability-modules.v1.json) | `tests/test_ability_modules.py` (every module the abilities catalog names a row whose every version serves exactly its abilities, the figures a module's requests are asked under, a society running what its first input records or what every society ran before, a new society recording each module's newest built version while older ones stay readable, a table breaking a rule refused by name, every row keeping its bytes) |
| The routine held to each kind | `routine_withheld` in [`society_planner.py`](../exulanica/world/society_planner.py), the options in [`society_decision_contract.py`](../exulanica/world/society_decision_contract.py), the request check in [`society_actions.py`](../exulanica/world/society_actions.py), the card's versions in [`thing_card.py`](../exulanica/api/thing_card.py) | `tests/test_society_kind_gates.py` (a lantern spirit offered no place, stand or talk and waiting for its kind's reason; a knight and villagers offered and doing exactly what the first version gives them; no villager talking with a spirit; a request refused `activity_not_offered`; a history the first version recorded, a spirit resting, standing, visiting and talking in it, replaying byte for byte; a card naming the version a society runs), `tests/test_society_things_postgres.py` (a society made through the routes records the second version, and its spirit never rests over an hour while others rest beside it) |
| Hands | [`society_hands.py`](../exulanica/world/society_hands.py), the hands step in [`society_things.py`](../exulanica/world/society_things.py), migration 0166, a person's request in [`society_actions.py`](../exulanica/world/society_actions.py) and migration 0170 | `tests/test_society_hands.py` (picking up into a socket that fits, an author's move or removal taking a thing out of a hand, no giving to a kind that does not receive, a visitor leaving the world's things behind and taking what it brought, what a visitor brought going home with it unless a being here holds it and then when put down, visitors coming and going leaving nothing behind, a brought thing its bringer left behind refused by the state check, a removed being putting down what it holds, two things of one kind offered apart, an author's turn and height applying to a thing nobody moved, things carried in held in separate sockets, an act chosen while walking done where both stood as the minute began, beings on neighbouring nodes handing over, the data hands replay by pinned), `tests/test_society_hands_postgres.py` (through the decision host: a knight walks, picks a sword up and gives it to another knight; replay asks no model; a request failing its own check undone alone while the minute's others are asked; both models reads judging the budget by the terms a society of things asks under), `tests/test_outside_deciders_postgres.py` (an outside request failing its own check undone alone), `tests/test_society_things_carried_out.py` (a visitor with the right carries a placed thing out when it leaves by its own choice or is called home by its player, never otherwise; the eight-an-hour bound; never put back while its placement stands; a moved placement places it again; the two crossing fields held to their shapes), `tests/test_society_hands_requests.py` (a person's request built, applied and done as asked, walked to when farther off, its wait and walk recording a request's reasons and never a model's, a decider's own act keeping the model's, a blocked being and one standing a while walking when asked, the being's own model set aside that minute, a give to the being beside, an asked put-down, each refusal by name with the module read first, a take no shipped kind allows, a visitor's brought thing refused at the request and at the minute, a second being refused where the first holds the only place within reach, an asked act its decider replaces and a decider's act a request replaces each recorded as left undone, `asked` on an asked act's miss only, a being an outside program decides for refused, a v1 request keeping its shape, the state check admitting `asked` only as true, the same bytes on replay, the second request for one being in a minute superseded), `tests/test_society_hands_requests_postgres.py` (through the route: a knight asked picks the sword up and the society replays, a refusal by the route's name, a body naming the other being wrongly refused at the boundary, the binding with its own words and the intent check each refusing the one thing made wrong against a bound control, a society not running hands and one that is not of things refused, 0060's four checks replaced by two), `tests/test_society_hands_request_migration.py` (the migration over stored go_to and perform requests: every row unchanged, replay verified, a new request of each profile bound and consumed), `tests/test_society_hands_history_before_requests.py` (a history recorded before hands requests by the minute the repository composes, a person's v1 request and a model's sealed pick-up and put-down, recomputed to its recorded digests) |
| Purity | The import contract "Things are pure data" in `pyproject.toml`: no database, store, evidence, pipeline, world, traffic, movement step, model or numeric stack | `lint-imports` |
| Drawing | [`things/`](../web/packages/atlas-react/src/playcanvas/things), [`composition/things.ts`](../web/packages/app/src/composition/things.ts), [`things-library.ts`](../web/packages/app/src/things-library.ts) | `web/packages/atlas-react/test/things-*.test.ts` (the shipped documents read, digests refused, skeletons read by shape with a ten-legged plan, planted feet, placement, misses, picking, a society's things through the crowd, a held thing in its holder's hand, the marks and lines overlay, a thing of a workspace kind standing while a society of things is drawn), `web/packages/atlas-react/test/society-crowd-things.test.ts`, `web/packages/atlas-react/test/society-crowd-anchors.test.ts`, `web/packages/atlas-react/test/society-crowd-refresh.test.ts`, `web/packages/atlas-react/test/society-crowd-walk-ended.test.ts`, `web/packages/atlas-react/test/things-placed-facing.test.ts`, `web/packages/app/test/things-composition.test.ts`, `web/packages/app/test/environment-selection-things.test.ts`, `web/packages/app/test/environment-selection-marks.test.ts`, `web/packages/app/test/thing-marks.test.ts`, `web/packages/app/test/door-grants-api.test.ts`, `web/packages/app/test/environment-selection-agents.test.ts`, `web/packages/app/test/thing-lines.test.ts`, `web/packages/app/test/environment-selection-lines.test.ts`, `web/packages/app/test/door-bridges-api.test.ts`, `web/packages/app/test/thing-looks-api.test.ts`, `web/packages/app/test/things-composition-looks.test.ts`, `web/packages/app/test/environment-selection-looks.test.ts`, `web/packages/app/test/things-composition-facing.test.ts`, `web/packages/app/test/things-library-held.test.ts` |
