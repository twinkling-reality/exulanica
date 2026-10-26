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
| `label`, `summary` | lowercase words, 2 to 40 letters and spaces (a creature drafted from words, 2 to 32, as its plan's key is), the words an option or a card uses ("lantern spirit"); one line of at most 160 plain characters |
| `class` | `being`, which acts and has a decider, or `object`, which decides nothing and does nothing |
| `body` | its body plan and the figures the plan bounds: a height range `{from, to}` for a humanoid, a radius for a bodiless thing, a box `{width, depth, height}` and whether it blocks walking for a rigid one; an object that blocks walking, placed on a lane of a town made under traffic rules 2, closes that lane to the town's traffic ([traffic](traffic-contract.md#served-traffic)) |
| `origin` | its [origin record](#the-origin-record) |
| `moves` | the movement modules it moves by, each one its plan moves by; none for an object |
| `abilities`, `offers` | `[{key, parameters}]` from the [catalogs](#abilities-and-offers), each parameter within its bounds |
| `routine` | a being's routine: a whole-number weight from 0 to 10,000 for each ability the routine draws among, the kinds whose holders it prefers to follow (`follow_holders_of`) and a reason; none for an object |
| `deciders` | a being's `{default, allowed}`: the [decider](decision-roles-contract.md#who-decides-deciders-and-the-owners-choice) kinds that may run it, among `routine`, `model`, `person` and `external`, the default the routine or an outside program; none for an object |
| `looks` | at most 16 references `{look, version, sha256}`, each a look of the kind's body plan, the first the default; may be empty |
| `ext` | source data kept verbatim, at most 8 KiB of canonical bytes, which no engine reads |
| `fits` | optional: the worlds the kind fits, `{eras, reason}`, `eras` either `any` or the keys of `assets/catalogs/era.v1.json` it belongs in, each once (none for a kind no era fits, such as a story world's sword), with its reason; a placing tray orders its kinds by it and no engine reads it |

The placing tray offers every object kind, the latest version of each: those that fit the world
first in the library's order, then the rest after a wider gap, unlabelled, so nothing is hidden. A
kind fits any world, or a world in one of the eras it lists. No world states its eras yet, so a world
is taken as in every era of `era.v1.json`: a kind that lists any era fits, and one that lists none
comes after.

A kind's identity is its key and version, and its digest is the SHA-256 of its canonical bytes; a
version never changes, and a kind that must change gets its next version beside the first. The lock
beside the kinds, `assets/catalogs/things/kinds.lock.json`, names every shipped version with the
digest it shipped with, and the kind loader refuses a file it does not name at that digest, or a
locked version with no file. A thing names its kind by all
three: a world's author places one by its kind in a version's authored plane
([world objects contract, section 14](world-objects-contract.md#14-placed-things)), a being only
where its kind's deciders allow the routine. A kind its workspace keeps (below) is placed by its
digest alone, never by its key, which a person's words may have made. What a society
is given of a shipped kind is `ThingKind.semantics()`: every field but `looks`, `origin`, `ext`,
`summary` and `fits`, with the kind's reference, so no look reaches a society through its kind. What it is
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

A society records the module versions that execute these abilities. For following, version 3
keeps an accepted pursuit between decision opportunities; version 2 requires a keeping decision
each minute. Current model terms offer following only with version 3, while the player's existing
version-2 controls remain available. The [society contract](synthetic-society-contract.md#the-society-of-things-v7)
defines cancellation and target-loss rules. A follow ability still requires a way to move.

The purposeful abilities are the purposeful routine's actions with exactly its rules, and talking
stays wordless: words are said. A line is written only by a decider, never by the routine. Under the
module's second and third versions (`exulanica-ability/purposeful/v2` and `/v3`), a being does
only those its kind lists: the routine plans only them, its decider is
offered only them, a talk takes two beings whose kinds both list talk, and a request for another is
refused `activity_not_offered`
([society contract](synthetic-society-contract.md#the-society-of-things-v7)). Waiting is
everybody's, and a being whose kind does not rest is never tired. The third version also reads
the kind's purposeful activity weights for autonomous choices; the second keeps the world's
routine weights. A society that recorded the first version runs it for its whole life, where
every being may do all five. New societies record the third version; stored societies retain
their recorded version.

[`ability-modules.v1.json`](../exulanica/abilities/ability-modules.v1.json) states each module once,
by version, read by [`registry.py`](../exulanica/abilities/registry.py): the abilities it serves,
its bounded parameters (a figure the module uses itself, or a range a kind states within), the
event kinds its minute records, and whether it is built. Purposeful (versions 1, 2 and 3), say,
crossing (versions 1 and 2, the second naming a visitor in every summary by what it is, from
outside, never as simulated) and hands (versions 1 and 2: `reach_mm` 1,500, `approach_mm` 8,000,
`walk_minutes_maximum` 3) are built, and so is follow's second version (`follow_distance_mm` 2,000, `lost_after_minutes`
3), with persistent accepted pursuit in its third version; its first was stated and never built,
so no society records it, and it is still refused by name
(`follow_not_built`). A society of things records
the modules it runs in its first input and runs exactly those for its whole life
([society contract](synthetic-society-contract.md#the-society-of-things-v7)), so a module version
stays in the table while any stored society names it, and a new version is a new row. A later
version of a module serves the same abilities, so the abilities catalog names one version of each
module and an ability is served by whichever version a society runs.

Speech version `exulanica-ability/say/v2` retains the previous state's workspace-kind run forms
when deciding who hears a line. Shipped and workspace beings must offer `hear`, remain present,
share the permitted space and be within the recorded hearing reach. The first speech version
retains its shipped-kind hearing read, including its omission of workspace-kind hearers, for
exact replay. Societies record the speech version in their first input; adding the second version
does not reinterpret older events or add a model decision.

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
`visit` to `visit`, perches to `perch` and hosted flyers to `host`. A kind may state weights for
its purposeful activities, hands abilities and following. Recorded purposeful/v3 and later read only
`wait`, `stand`, `talk`, `rest` and `visit` for ordinary autonomous choices. Missing keys and
explicit zero weights both mean no preference; an empty or unavailable distribution waits
safely. Automatic conversation requires positive talk preference from both participants.
Durations, need thresholds, relief, reach and capacity remain the world's routine rules.
Tiredness may select an available rest place despite zero rest preference, and a being that
finishes at a destination makes room before waiting. Explicit model, player and owner choices
remain governed by capabilities rather than weights. Earlier purposeful versions ignore kind
weights, and people with no kind retain world-routine selection. Hands and follow weights and
`follow_holders_of` are not executed by the routine; only a decider, or the world's owner by a direct request
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
then wears its kind's first look there); and under `kind_looks`, stated only when there is one, the
look each of the workspace's creatures wears by its kind ([a creature's made
look](#a-creatures-made-look)), by the kind's digest and the look's, which a thing with no choice of
its own wears before its kind's first look. Choices stay with the version, as its society does.

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
- for a being its author placed, who its world's owner wrote it to be (`character`: the newest
  record's `revision`, `character` and `written_at`, each null where nobody wrote one, and `shown`,
  whether this society shows a character at all), read from the character table rather than the
  society, whose next minute takes a new one in ([below](#who-a-placed-being-is)); null for anything
  else;
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

### Who a placed being is

A world's owner may write who a being they placed is (`exulanica.thing-character/v1`): a `name` of
1 to 40 characters, words `about` it of 1 to 300, or both, each one plain line under the
[line rule](#lines), stored in Unicode normal form C. It is fiction the owner writes for whoever
decides for the being, and the one way a being is given a temperament. Nothing derives one from a
photograph, a kind's description or a person. A character carrying any name the account holder
saved, of any kind, is refused, since no right releases a saved name to a decider
([`thing_characters.py`](../exulanica/world/thing_characters.py)).

`POST /world/versions/{version_id}/things/{thing_id}/character` (`world.write`) appends a record for
the being placed under `thing_id`, the author's placed id as the move and remove routes take it,
over the newest record the writer read: `{base_revision, character}`, `base_revision` null where it
read none and `character` null to clear it. It answers the record (`profile`, `version_id`,
`placed_id`, `revision`, `character`, `written_at`) and whether the version's society shows it
(`society`: `runs_characters`, `began_before_characters`, or `none` while the version holds no
society). It refuses by name, writing nothing: `character_changed` (409, with the newest
`revision`) for a writer that read an older record, `no_change` (409) for one that says what the
newest already says, `character_out_of_bounds` and `character_carries_a_saved_name` (422) for the
text, `character_for_beings_only` (422) for an object, and 404 for a thing the version does not hold.

`GET /world/versions/{version_id}/things/characters` (`world.read`, never cached) answers
`exulanica.thing-characters/v1`: the newest record of every placed thing of the version anyone
wrote one for, a clearing one included (`placed_id`, `revision`, `character`, null where the record
clears it, and `written_at`), in placed id order, and `society` as the write answers it. It is one
read for a reader that follows a whole world, such as a world's project
([world memory package](world-memory-package.md#capture-and-automatic-tracking)), where a being's
card would be one read a being. A version the world does not hold is 404 `unknown_reference`.
`GET /world/versions/{version_id}/things/characters/history` (`world.read`) answers
`exulanica.thing-character-history/v1`: every record of the version, newest first and bounded
(`limit`, at most 500), with its `placed_id`, `revision`, whether it states a name and words about the
being (`states_name`, `states_about`; both false, it clears them) and `written_at`, never the words,
which the newest read holds.

Records are appended to `world_thing_character` (migration 0213) with the actor who wrote each and
the record it replaced, never changed, and only the newest may be replaced: the database holds
that too. A record belongs to one version, as a look choice does: a version branched or carried
from it starts with none, and its owner writes the character there again. A world's erasure and its
workspace's deletion delete every record.

A society whose first input records the character module (`exulanica-ability/character/v1`, every
society of things made since it was built) carries the newest character of each placed being in its
inputs: writing one composes the society's next input in the same transaction (or answers 424
`unavailable_society_input` and writes nothing where that input cannot be composed). The being keeps
it in its state from the society's next minute, and its decider alone is shown it, quoted as
fiction ([minds](minds-contract.md#who-a-being-is)). Every other being still calls it by what it
is. A society made before the module, the first society of any existing world among them,
carries, keeps and shows none: a character reaches such a being only in a new version's society,
since a new version starts a new society.


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
| `lantern_spirit` | being | bodiless, radius 200 mm | wait, follow, say, pick_up, put_down, give, take | talk_to, hear, receive, be_followed | as the knight; its authored preference to follow a lantern's holder is not executed by the routine | `spirit-light` |
| `visitor` | being | humanoid, 1,500 to 2,000 mm | wait, stand, talk, say, pick_up, put_down, give, take, follow, leave after 5 quiet minutes | talk_to, hear, receive, be_followed | an outside program only | none: its crossing brings one |
| `villager` | being | humanoid, 1,500 to 1,950 mm | wait, stand, talk, rest, visit; versions 2 and 3 also say | talk_to, hear | the routine; a model or the owner; version 3 also an outside program | `people-catalog` |
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
`read_body_recipe`, against the body grammar's newest version
([`body-grammar.v3.json`](../assets/catalogs/things/body-grammar.v3.json), which lets legs swim by
paddling and names the gaits catalog version a swimmer's pace in water is read from; the second,
[`body-grammar.v2.json`](../assets/catalogs/things/body-grammar.v2.json), named the swimming
module, and the first,
[`body-grammar.v1.json`](../assets/catalogs/things/body-grammar.v1.json), named none; both are kept
as they were published), whose entries state every choice and bound with its reason:

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
`exulanica-movement/walking/v1`, and swimming (at least one pair of fins, at least one pair of legs
to paddle with, four or more tentacles, or a serpentine body) is `exulanica-movement/swimming/v1`,
by which a being crosses the water its society's input states
([movement modules contract](movement-modules-contract.md#swimming)). Flight, climbing and
burrowing are stated with no module and with the sentence a creature asked for one is refused with
("This world has no flying creatures yet.").

A creature drafted to swim states its pace in water with its swimming move
(`{"module": "exulanica-movement/swimming/v1", "parameters": {"pace_permille": N}}`), read from the
gaits catalog version the grammar's swimming entry names
([`gaits.v2.json`](../assets/catalogs/things/gaits.v2.json), `swim_pace_permille` in
[`gaits.py`](../exulanica/things/gaits.py)): its own walking pace times the largest share among the
ways it can swim, fins seven tenths, four or more tentacles or a long body six tenths, paddling legs
four tenths, so a larger body swims faster as it walks faster. Its run form carries the figure as the
kind states it. A creature kept before the grammar named a pace states its swimming by module alone,
is built again as it was, and swims at the swimming module's reference pace.

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

A plan's reason names the body grammar version that built it, so the same recipe builds another
plan under a newer version. Code that builds a kept plan again builds it with `built_again`,
under the plan's own key, version, title and origin and the version that built it, every version
being kept as it was published. This covers a creature's look request
([`creature_look_command.py`](../exulanica/hosting/creature_look_command.py)) and an authored
surface's check ([`body_surfaces.py`](../exulanica/things/body_surfaces.py)). The authoring script
([`author_surfaces.py`](../scripts/things/author_surfaces.py)) builds the body under the newest
version whose plan is the one the surface pins. A creature kept from before a newer version keeps
its plan, its moves and its looks.

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

### Authored body surfaces

The body-surface writer writes a `rigid_on_bones` look from an
`exulanica.body-surfaces/v1` document. It pins the recipe and body-plan digests, verifies the
builder's rest joints, and attaches each surface to a named bone of that plan. Rounded ellipsoids
with optional radial ridges and swept tubes with bounded subdivision are declarative appearance
inputs. Coordinates and radii are whole slot-frame millimetres. The document admits at most 128
parts and 20,000 triangles; every generated rest vertex must fit the recipe's width, length and
height and stay above its support plane. Degenerate geometry, unknown fields or attachments,
invalid material factors and mismatched pins refuse before a container is written.

The mesh writer accepts optional finite unit normals per vertex and roughness/metalness in whole
thousandths. A mesh without these additions retains its flat normals and exact container bytes.
The resulting look uses the existing look and static-container checks. Its origin retains the
recipe, plan and surface digests; an authoring receipt identifies the writer, output digest, counts
and rest bounds. Authored geometry carries authored provenance, with no invented model receipt.

The low-level mesh writer also accepts normalized atlas UVs and optional embedded material maps.
`PngMap` checks complete PNG chunks, checksums and bounded compressed pixel data: eight-bit RGB or
RGBA, non-interlaced, each side at most 4096 pixels. `MaterialMaps` assigns base colour in sRGB,
tangent-space normal XYZ, and linear packed roughness/metallic in the green/blue channels. Existing
colour and material factors multiply the maps. A normal map requires explicit unit tangents
orthogonal to its normals, handedness of plus or minus one, and nondegenerate triangle UVs after
float32 conversion. Tangents rotate with geometry from the slot frame to glTF; UVs retain their
stated orientation. Flat meshes duplicate UVs with their corners; smooth meshes remain indexed.
Exact image bytes are embedded once per unique image in the existing static container, with no
external references. The writer enforces the static admission image and texel ceilings and the
look's 32 MiB container ceiling. Admission, workspace retention, serving and withdrawal use the
existing look contracts. The declarative body-surface document provides no UV unwrap, texture bake
or map fields; these inputs are for authored meshes supplied to the lower-level writer. They do
not extend the skinned-container profile or the sculpting pipeline.

The operator utility that assembles surfaces into an asset bundle assembles a
declared recipe, body, surface, look, kind and origin into an immutable asset bundle. It provides
no browser body editor or upload operation. The kind's admitted abilities and movement modules
remain authoritative. Rest bounds and cosmetic deformation do not establish locomotion clearance;
the host must provide a compatible graph and supported recorded action. Visible sole contact
requires checking the posed mesh, including geometry beyond a limb's last joint.

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
[`creature-drafting.v3.json`](../exulanica/selection/creature-drafting.v3.json), asks a model for a
creature and assembles its answer. A creature's label is 2 to 32 letters, since it is its body plan's
key with spaces as underscores; versions 1 and 2 of the words allowed 40, which the key refused.

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
| `kept` | The kind made and its sketch, each by key, version and digest, its label, the model that drafted it, and, once one is asked, its creature's newest look job (`look_job`, as `GET /things/creatures/looks/{look_id}` answers it; [below](#a-creatures-made-look)) |
| `erased` | Nothing: the draft was kept, and the workspace has erased the creature since |
| `refused` | The refusing check's code, the field of the drafter's form it refused, and the code's fixed sentence, an unbuilt movement's in the grammar's own words ("This world has no flying creatures yet.") |
| `failed` | Why, by code: `drafter_unavailable`, `spending_refused`, `spending_suspended` (the spending authority held closed until an operator acts: spending paused, nothing spent), `request_refused`, `reference_withdrawn`, `expired`, `stranded`, `not_served` |
| `cancelled` | Why, by code: `workspace_deleted`, its workspace erased before the draft ended |

In every status a draft states what it spent (`spend`), read from the durable spending authority's
own records of its attempts, which are admitted under its job's key: `spent_usd`, what those that
ended settled at (a reported cost, nothing for one that never left, the whole reservation of one
whose outcome is unknown, or what an operator reconciled it to), and `held_usd`, what attempts
still under way hold, both decimal strings at the ledger's eight places. It is never an estimate:
where no durable authority admits the process's calls, nothing is recorded and `spend` is null.

`GET /things/creatures/offered` (`exulanica.creature-offer/v1`) says before anyone types whether
the workspace may ask here and why not by code (`creatures_not_run_here`, `models_not_configured`,
and, from the workspace's own spending, `spending_suspended` while the durable authority is held
closed for the drafter's provider or `budget_exceeded` where it refuses that provider otherwise or
less is left than one attempt's answer bound and instructions cost), the model a draft asks first
(`model`, by id and the name a person reads), the most one draft may be charged (`price`), how long
the drafter's calls take by the record its timeout rests on (the median and longest call, rounded
up to whole seconds, and the timeout), and the closed lists of codes a draft may end with: a refusal
outside the list is carried as `creature_not_drafted`. The price is `usd_at_most`, a decimal string,
with the account it is charged to (`provider` and `provider_description`) and its basis
(`request_envelope_ceiling`): each dispatch priced at the drafter's request envelope of input
(`assets/catalogs/request-envelopes/`, the most bytes its request may send, never more than the
model's context window) and the route's answer bound, at the manifest's prices, for a form and one
repair, each sent as often as the client may send it (every fallback and retry), at the route's
dearest model. A draft runs under those two bounds, kept with its job when it is asked for, so a
catalog changed while it waits changes nothing for it (a job queued before they were kept runs under
the catalog's): its client's chain refuses an attempt larger than either before sending it, so
neither a reported cost nor the reservation an attempt of unknown outcome keeps passes the price; a
typical draft spends a small part of it. A request's escaped JSON bytes bound its input tokens,
since a tokenizer that works on bytes makes no token of less than one. Under those bounds each
attempt is reserved, and admitted by the durable authority, at its own worst case: its request's
bytes as tokens and its whole answer, so a report never passes what the attempt held and a grant is
never spent past its ceiling. Where the catalog names no envelope for the drafter, the basis is
`full_context_ceiling`, each dispatch priced at a whole context window, and an attempt is reserved
at an estimate that counts prompt characters at a fixed rate, which is no bound and which the price
does not use. With no model client the price is null. Where a draft is offered, the offer's `notes`
says whether this person may ask for web notes with it (`offered`, and `code`: a code of the
references read, `references_not_permitted` without `references.request`, which a guest never holds,
or `references_price_unavailable` where no current rate prices their model calls), the most searches
one notes request sends (`searches_at_most`, the planner's limit for things) and the most its two
model calls may add at current rates (`maximum_usd`, null where not offered), so a page says the
whole most before anything is sent; where no draft is offered, `notes` is null.
`GET /things/creatures/drafts` lists the requester's own drafts, newest
first, so a reload finds one still running; a draft states when it was asked, when a worker first
took it and when it ended.

An optional `reference_id` names a finished reference request owned by the requester, made with
purpose `things`. The worker takes web notes through the existing
[reference authority](reference-notes-contract.md). Selected-picture notes use its v3 bundle and
a separately declared, current creature-role consent. Unknown, foreign, unfinished or
wrong-purpose requests retain their visible `not_used` fallback. A selected-picture request whose
authority ended fails closed, including before its first dispatch. No-reference requests retain their response shape and
`creature-drafting-3` prompt. Consumed notes select `creature-drafting-4`, are quoted as untrusted
descriptions after the person's words, and cannot override the body's supported bounds or actions.
Explicit requested changes take priority in the prompt; the use record does not establish that a
model followed a particular change or that a reference caused an output field.

Reference-bearing drafts expose `references` with the request ID and a state. `pending` means no
attempt has been recorded; `not_attempted` means the draft ended before that point. `used` means an
exact notes-conditioned request returned a model response or matched a cached response. `unknown`
means a dispatch may have reached the provider without a response, including a worker interrupted
before recording its result. `not_used` means no eligible notes or known non-delivery. Used and
unknown records name the bundle digest, note count and the consumed bases (`web_description`,
`own_picture` or both), never note text. Every state also carries `searches` and `spent_usd`: how
many searches the requester's own notes request sent and what its model calls spent, as its bundle
records them, so a page counts the notes in the whole spend; both are null for a request that kept
no bundle (one that failed, was stopped or is not finished) or that is not the requester's own.
Picture-derived requests bypass response caching.
The draft queue preserves this record across reclaim without changing the job's spending key.
The body's and kind's existing origin ingredient lists bind the consumed bundle digest; the user
words' digest remains separate, and no generation receipt is invented.

The worker checks reference authority before each model attempt and under a reference-row lock
inside both existing creature-store transactions. For picture notes, privacy currency and the
source lifecycle lock precede the claim and reference rows; exact right currency is read without
locking right rows. Feature eligibility, screening, person findings and the explicit consent
binding are checked again within those guards. No lock spans a provider call. Withdrawal before
the final store check discards the answer with `reference_withdrawn`; a completed call remains
recorded as used. A lost claim publishes no stale completion. Bytes written before a second store
check refuses remain in the existing inventory and are reached by workspace erasure. This path
uses semantic anatomy, relative part layout, material, colour and rough-scale suggestions. It
does not recover geometry, match an appearance from pixels, add a reference-selection UI or make
inhabitant behavior model-driven. Already kept invented definitions remain until ordinary
creature erasure; a stopped or erased source cannot authorize another attempt.

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
where that panel places nothing, the same distance ahead in the one region drawn there, on the ground
its people stand on: the plane at the arrival's height, a site's land, or, in a town on land, the
ground its tiles walk and its land where they walk none; through the same edit as a planned thing (the version's compare-and-swap, the
saved entry advancing). A creature stands with its middle at its place, so it is put half its body's
stated length farther along the way the person faces: its head is then as far from them as any
placed thing is, 3,500 mm, whatever its size, on the ground found at that distance; a kind whose
extent the page cannot read is placed at the distance as given. Where the page cannot say where the
person stands it places nothing and says so; the creature stays kept. A refusal shows its code's fixed sentence
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
digest, it arrives at the open node nearest where it was put (never at a door's, in a society
recording purposeful/v4 or later), walks, rests, visits, stands and
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
| `moves`, `abilities`, `offers`, `deciders` | as the kind states them; the walking it moves by also states `pace_permille`, its body's pace in thousandths of a society's own (optional: a form written before it states none) |
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

**Paced by its body.** [`gaits.v1.json`](../assets/catalogs/things/gaits.v1.json) states how fast a
drafted body walks, each entry with its reason, and
[`gaits.py`](../exulanica/things/gaits.py) computes it. The rule is the dynamic similarity of
animal walking (Alexander and Jayes, 1983): bodies of different sizes move alike at equal Froude
numbers, so pace goes as the square root of the height a body stands at. A body with legs stands
at its hips, the height the builder hangs its leg chains from (the lowest, where pairs differ); a
body with no leg that steps on its tentacles is read where they hang, by analogy and not by a
published result; a legless body lying along the ground keeps the society's own pace, a chosen
default. The reference is the 900 mm at which the hips of the 1,700 mm figure stand. A pace is a
whole number of thousandths of the society's own, the whole root of a whole quotient so it is the
same on any machine, held between 100 and 3,000: hips at 1,235 mm give 1,171, at 57 mm 251. The run
form states it with the walking the body moves by; a reader takes any whole number from 1 to
10,000 there and no other figure. A society of things whose first input records the second
walking module moves each being by its own pace's share of the society's budget, floored to a
whole millimetre: at 60 m a minute a body at 251 walks 15,060 mm in a minute and one at 1,171
walks 70,260 mm ([movement modules contract](movement-modules-contract.md#walking)). A hand-over
is timed by what each party spends. A society whose first input records no movement module walks
every body at the one budget, whatever its run form states. The catalog's second version,
[`gaits.v2.json`](../assets/catalogs/things/gaits.v2.json), keeps the first's walking entries and
adds a swim entry for each way the grammar lets a body swim, each a share of its walking pace with
its reason, chosen figures rather than published ones: hips at 1,235 mm on paddling legs give
1,171 x 0.4, 468, in water (`tests/test_swim_paces.py`).

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
has put that name where no erasure reaches. The erasure stands whatever a society does.

**A society finds out by itself.** The telling above is a courtesy, held to a budget of 2 seconds
read from the server's clock before each version
([`thing-erasure-telling.v1.json`](../exulanica/world/thing-erasure-telling.v1.json), a chosen
budget): a version it does not reach, one whose input cannot be composed at that moment, a society
that is not running, and a society restored from a backup whose erasure the restore replays are
told by nobody at the time. So every minute asks first. A society of things is untold when its
latest input still lists a placed thing whose kind is gone (a being already there, or one placed
and erased before any minute, which the next minute would otherwise bring in), or when its
latest input is unavailable and its state holds a placed being whose kind is gone (an unavailable
input lists nothing and names nobody, and would leave the being there). An available input that
does not list a being the state holds is not behind: the minute sends away every placed being its
input does not list, so a creature whose thing was removed, before or after its erasure, leaves
in the next minute as any removed thing does. The minute asks from the row and the
inputs it has already read: where neither names a thing of a kind its workspace kept it asks
nothing, and otherwise one query asks which of them have their kind gone, by the condition a
version's things are read with (`THING_KIND_GONE_SQL` in
[`thing_kind_gone.py`](../exulanica/world/thing_kind_gone.py)). Where the society is untold, the
input that sends the thing away is composed first, by the code an authored edit runs: a being
there leaves in that minute as `kind_erased`, and one not yet arrived never arrives. This holds
for the step route, a manual step and the minutes a new society is opened with. An erasure, a
placing edit and a minute each take the workspace's lock first, so each is wholly before or
wholly after the others: a minute that begins after an erasure commits never runs the erased
creature. A minute that cannot compose that input runs nothing and is refused: as an unavailable
input where the society's input is unavailable, else by name (`SocietyInputBehind`, answered as a
society that changed).

Playback composes nothing inside a round (a round takes the asset read lock only after its
minutes are computed), so its worker asks before each claimed round, in a transaction of its own.
It reads the society's engine alone first, and for a society of things takes the workspace's lock,
reads the society and asks whether its version holds any thing whose kind is gone, so a society
none of whose things is of an erased kind has its input read by nobody. A round asks no model,
and is one minute the routine decides, wherever the state may still hold an erased being until
that minute runs: a society just told, one the erasing request had already told, one whose
creature's thing was removed, and one that could not be told.
Where the society is behind and the input that sends the being away could not be composed
(the minute's two refusals above), that minute pauses it with the reason a person already reads
for a source that cannot be read (`paused_due_to_error`, `source_unavailable`); it is not left
playing and standing still. Any other fault while asking is a failed round like any other: no
minute runs, the lease is left to expire, and a society whose rounds keep failing is paused by
the claim that finds its three attempts spent (`lease_recovery_limit`). An
erasure that commits after the worker asked stops the round at the minutes it has computed, with
no pause, and the next round is told first. A society paused for a month is told at its first
minute back. A replay reads the inputs that were recorded and composes none. Asking for the
erasure again (the route answers 404, as for any kind the workspace does not hold) also tells,
appending nothing to a society already told. A thing whose kind
its workspace still holds but whose run form cannot be built (its plan or recipe no longer reads)
is left out of the input too and is not named among those gone: a being that was it leaves as a
removed one does.

An open page forgets the creature too. It keeps the name its maker gave the kind, and what its
library read of the kind (its document, its drafted plan, its looks and their containers), only
while a being of that kind is among the people it draws or a notice of one waits to be told. Once
none is, and when it reads a placed thing as gone, it drops them; were a being of that kind listed
again it would ask the workspace, which answers that it holds none, and say no name.

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
[`thing_store_command.py`](../exulanica/hosting/thing_store_command.py) (`admit-look`, `withdraw-look`
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
| `GET /things/kinds` | Every kind the workspace holds, newest first (at most its cap of 128), each read again as the one-kind read reads it, a document the reader now refuses left out: its reference (`kind`, `version`, `sha256`), `label`, `class`, `body_plan`, `looks`, `body` as the kind's document states it (a drafted creature's `extent_mm`) and `made_at` (`exulanica.held-thing-kinds/v1`), never cached: the creatures made from a person's words that build mode offers to place |
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

### A creature's made look

A creature drafted from words wears its sketch. A made look, a 3D model made from a picture of it and
fitted with its plan's skeleton ([generated appearance, route P](generated-appearance.md)), is asked
for as a look job ([`creature_look_jobs.py`](../exulanica/world/creature_look_jobs.py), migration
0220) and made by an operator's run; the API spends nothing. A made look is the default way a kept
creature looks: a draft from words alone asks for its creature's made look in its owner's name as it
keeps it, and the creature wears its sketch until a run makes the look and whenever the fit refuses.
The draft has ended `kept` before the ask, which never undoes it: an owner at their limits, a
workspace being erased or a creature erased since leaves the creature kept with no job. A draft
conditioned on a reference asks nothing by itself, as its words may carry what notes read from a
picture; a member with the grants may still ask through the route. A run takes the queued jobs of the
workspaces it serves, writes each one's request from the creature's kept documents, marks them
`staged` under the run with the request's digest, and once its GPU job and the fit are done ends
each: `made`, naming the look the workspace now keeps by its document's digest; `refused`, by the
fit's code; `failed` or `cancelled`, by why; each with its share of what the run cost. A job moves
forward once and an ended one never changes. A made look is appended as its kind's look (`kind_look`):
the creature then wears it wherever it is placed, the newest kept and not withdrawn worn, unless a
thing's own choice names another.

The run is the operator's ([`creature_look_command.py`](../exulanica/hosting/creature_look_command.py)),
in five steps, each without `--apply` a check that writes nothing: `stage` takes the listed
workspaces' queued jobs and writes their requests; `ml/appearance`'s `creatures make-job` writes the
route P job record; the generated assets tooling runs the GPU job under its bound; `creatures fit-run`
fits every model it made on the operator's machine and states each request's outcome; and `admit`
keeps each passed look (generated, private, drawn on the creature's own plan, the fit's receipt in
its lineage, its cut-out among its ingredients, CC0 as invented content), then ends its job made and
appends its kind's look together, ends a refused or unmade one by code, and gives each job an equal
share of the run's measured cost. A job no longer staged under the run, its creature erased since,
keeps nothing. The product and the job meet only at documents: the request, the fits' record, the
receipts and the containers.

A job holds ids, digests, codes, times, a cost and who asked, and no word: the request a run writes
carries the creature's drafted appearance and lives only in the run's folder and its GPU job. At most
one job waits for a creature, and one requester has at most four unfinished and twelve in an hour;
only the workspaces the installation lists (`EXULANICA_CREATURE_WORKSPACES`) ask. A creature's
erasure deletes its jobs and kind looks with it, and a workspace tombstone every one of its
workspace's, both as the definer owner; the rows refuse every other delete, and a kind look every
update.

| Route | Answers |
| --- | --- |
| `POST /things/creatures/{kind_sha256}/looks` | Asks for a made look of the creature of that kind, needing `world.write` and `model.invoke`: 202 with its job, `exulanica.creature-look/v1`, queued, or the one already waiting for that creature; 404 `unknown_reference` for a kind the workspace does not keep as a creature; 409 `creatures_not_run_here` for a workspace the installation does not list; 429 `look_limit_reached` |
| `GET /things/creatures/looks/{look_id}` | The job, for any member of the workspace (`world.read`, never cached), as it is the creature's, holds no word and is answered to whoever asks again for that creature while it waits: its status, the kind's digest, the made look's digest, the refusal's code, the failure, its cost and its times; another workspace's or an erased creature's answers 404 `unknown_reference` |

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

A plan that states its chains, as every drafted body's does, is not read from its shape: each
chain is a limb with the role, side and order its plan states, and a bone outside every chain is a
head where a neck chain ends at its parent or a jaw chain hangs from it, and otherwise keeps its
rest turn. Each role is posed by one rule, written once for every body:

| Role | How it is posed |
|---|---|
| `leg` | Steps in the gait, its place taken from its chain's order and side: left and right in turn, each rank against the next, for any number of pairs. A planted foot keeps its point of the ground and its height. A leg of one segment cannot bend to reach, so it swings about its hip like a paddle |
| `arm` | Hangs and swings against the legs, carries what its sockets hold and reaches, as any figure's arm does |
| `spine` | The hips sway with the legs and the spine turns that sway back twice over, so the shoulders sway against the hips. A body lying along the ground does not lean into its walk |
| `neck` and the head | The neck returns what the body turned, so the head faces where the being goes; neck and head share a slow look to each side, and the head nods on each beat while the being speaks |
| `jaw` | Opens on each beat of speech; stays shut on what its socket carries, and otherwise |
| `tail`, and a `tentacle` that hangs | A wave that travels outward, each joint a lag behind the one before: about the upright for a chain along the ground, about the body's length for one that hangs |
| `wing` | Folded along the body: each segment turned from where its look drew it spread toward the body's back, so its bones lie inside the body's width, and rolled about its own length so the side its membrane is stretched from hangs outward and down the flank. It settles a little on each step. Nothing flies |
| `fin` | A slow sway about the body's length |
| `tentacle`, on a body with no leg | The body steps on its tentacles, alternate ones together; while it stands they hang and wave |

A body with neither leg nor tentacle whose spine lies along the ground moves by a wave down that
spine. The wave is fixed to the ground the body has covered and not to a clock: each joint comes to
where the joint ahead of it was, so the body moves forward as it bends and does not glide, and it
lies still and curved when it stops. Its neck keeps its head to the front.

Every angle, period and share those rules use is data, one entry each with its class and its
reason, in [`body-motion.v1.json`](../assets/catalogs/thing-presentation/body-motion.v1.json)
(`exulanica.body-motion/v1`), which the page reads and hands its figures. It is presentation only:
no recorded position, path, ability or event changes with it. A drafted body draws its full walk
from a speed its own stride sets (`full_walk_strides_per_second`), where a shipped figure uses
0.5 m/s whatever its size. A figure handed no table poses a drafted body's legs and arms and holds
its other chains at rest. Under reduced motion nothing waves, sways, nods or looks about; a wing
stays folded and a legless body keeps the curve it lies in.

The second version of the table,
[`body-motion.v2.json`](../assets/catalogs/thing-presentation/body-motion.v2.json)
(`exulanica.body-motion/v2`), keeps every figure of the first and adds postures: what a body is drawn
in while its state says it is doing something. A society's action kind names the posture (rest is
drawn settled, talk speaking, stand standing; any other activity stands). Settled lowers the hips by
a stated share of how far the legs reach down, never further than every bending leg can keep its
foot where it stands, and bows a head the plan names; speaking nods and opens the jaw on the beat of
speech. A body settles into a posture and rises out of it over the table's blend, at once under
reduced motion or after a move without walking. Postures are presentation only and change no
recorded position, action or event.

A body whose society's walking paces each kind (`exulanica-movement/walking/v2`) walks its own bound
each minute, the society's bound times its kind's `pace_permille` over a thousand, as the engine's
`tick_budgets` does, and walks at that bound over the minute's simulated seconds when nothing
hurries it; any other body walks at the pace its figure states or the catalog person's.

A kind that states its body's extent (`body.extent_mm`, as a drafted kind does) is drawn at that
size on the ground. Its pick volume is its width by its length to its look's height, so the ring
around a picked or played one takes its body in, and in a society's crowd it is picked over that
footprint turned as it is drawn. It turns toward the way it walks no faster than its ends may
sweep (`turn_end_speed_mm_per_second`): a body half a metre long turns a quarter in about a tenth
of a second, one 12 m long in about three seconds, the shorter way round. A jump in the drawn
minute faces it at once. A kind that states no extent is picked and turned as before.

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
front from +Z, so at yaw 0 it faces +Z. As anyone who stops keeps the way they came, it keeps that
way while it is open ahead; with a wall within 3 m ahead (the door of a shop it was taken in at), it
turns where it stands to the open way nearest it. Each object stands where the state puts it, its plan point
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
a thing with none wears its workspace kind's made look where the read names one (`kind_looks`, each
resolved by digest as a workspace look is, one no longer held left out), else its kind's first look.
A look is given to a placed thing only when it changes, since each look given draws the layer again.
The choices are read when a society of things is first
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
it, and one no longer held is left out. A thing's card and the world's other server reads wear the
same order (`effective_look`), and a participant may read a present being's kind look as it may a
chosen one. A person whose look changes is made again where they stand,
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

Who decides for each person of a saved world's society is marked over them, by one decision the thing card
makes too ([`composition/thing-marks.ts`](../web/packages/app/src/composition/thing-marks.ts)): a
person whose model is asked (chosen for them, and refused neither by the host nor for them) wears an
`AI` mark always, and with it the model's whole served name wherever the name can be tied to them
(below), never a part of it and never in letters smaller than a stated floor; a visitor its own program decides for
wears its bridge's mark as the door lists it here: `from` and the bridge's label for a game, read as
decided from outside (no person is claimed, which nothing a game sends shows), an outlined `AI`
pill for an outside agent, and `from outside` for a bridge the door does not list. An outside agent's pill names it in its own words, as its program last said them at the door
(the world's grants, `GET /door/grants`, read at most once a minute while such an agent is drawn
without a name; set as text only, a long name cut short on the pill and read whole), and says
`agent` until its program says. A visitor the world decides for (its arrival's `decided_by` is
`world`) is marked by who decides here: the `AI` pill naming the model asked, followed in the same
pill by `· from` and its bridge's label, or, while its routine runs it, `from` and the label alone,
read as run by this world. A being its own routine decides for wears nothing at rest, since that is
most beings in any world, and says "Their own routine", the card's own words, while it is the picked
one, so every being has an answer when asked; every object wears none. A being a person plays wears
`You` or `Played`. Those words keep the same floor a model's name keeps. The marks are part of the
page, not the picture: nodes kept and reused, placed each frame just over the box a person is drawn
and picked by, or, for someone lowering onto a seat or sitting on it, just over the figure as it is
drawn (the bounds its drawn meshes state in the pose they are in), so a seated person's name is over
their head and not a head above it; read by a screen reader in the card's words and picked by a click
as by aiming. They read nothing of the kind of world they are drawn over: a point over each being and
how tall it stands, from the society drawn, are all they ask, so they are the same over a town, a
farm or a site.

Every mark stands on its own being's head and is never lifted off it. A being a model decides for
wears two things: a small `AI` mark on its head, always, the same near or far, alone or in a crowd,
and the model's whole name in a row over the mark, joined to it by a neck. A name is bounded by what
can be read, never by how many beings a model decides for
(`assets/catalogs/thing-presentation/decider-marks.v2.json`, each value with its class and reason,
read by [`decider-marks.ts`](../web/packages/app/src/decider-marks.ts)). Nearest first, a name is
drawn where its being stands at least a stated height on the screen, while the names cover no more
than a stated share of the view (what a name adds over its mark; the marks are no part of the share),
and where it would cover no name already drawn and nobody else's mark. Where any of the three fails
the being wears its mark alone, which is still a button that picks it, and pointing at the mark or
reaching it by keyboard opens its name over whatever stands there. So of two people on a bench one
is named and both are marked, and no name stands where a reader cannot tell whose it is. The one
named however small it stands is the nearest whose name covers nobody's mark. A mark alone over a
being that stands lower on the screen than the catalog's `dot_under_px` is a dot of the mark's own
colour on its head, the same mark with no room for letters, so a crowd far off is a row of dots and
not a smudge of pills; pointing at a dot or reaching it by keyboard opens the pill and the name. The
catalog's first version states no such height and is read as before, with no mark a dot. The picked person, a speaking one and one at a
decision are named whatever stands by, outside the share, with their kind over the name, and are
drawn over the other marks. A marked being no model decides for (a game's player, a person's) has no
shorter form: too small or beyond the share it wears nothing. Every name not drawn is counted by why
(too small, beyond the share, would cover another) on the overlay (`data-named`, `data-unnamed`), and
the canvas states who decides for how many beings and how many are indoors (`data-deciders`), read
from each being's own state: one that states it is indoors (`indoors` true, or `location.indoors`
true where the state keeps a location) is not drawn and is counted indoors, and one that states
nothing of it is in the street. Limits: marks are not kept off each other, so people standing nearer than a mark is wide
wear marks that overlap, pills or dots; and a held being's name is drawn over the marks of those
standing by it, which it hides for as long.

What hides a being is the world's own plan, asked one question: how far a sight line runs before
something stands in it ([`sight.ts`](../web/packages/app/src/composition/sight.ts)). In a town the plan
is the one its first view is chosen by: every building's base and each trunk and post that crosses a
standing person's eye height, from the town's own tiles. In a place made from a world kind it is
every box the place's drawing draws across that height, turned as it is drawn; walls there are
pieces with a gap at each door, so a person inside is seen through the door and not through the
wall beside it. A being with something of the plan between
it and the viewer wears no mark and no name, its line of speech is not drawn, and a click or an aim
picks neither it nor a placed thing behind what stands there; it is counted (`hidden` in
`data-unnamed`). What stands within the first-view catalog's `sight_margin_mm` of a point is the
thing the point is at, so a person in a doorway is seen from in front. Two beings are followed
through a wall, because the person asked to: the picked one and the one the viewer plays keep what
they wear, drawn in one look that says behind something (faded and flat, `thing-mark-behind`), and
neither can be picked through the wall nor heard through it. It is the plan's answer and no more:
a parked vehicle, a bench, a bin, a tree's canopy, a thing lower than the eye and another person
hide nobody, since none crosses eye height in the plan; a town's doorway is not an opening in its
building's base, so past the margin a person standing inside one is hidden; a made place's roof is
no box, so a ridge that comes down lower than its walls hides nothing more than they do; and it is
asked in plan, which is right for a viewer on foot. A saved world with no town under it and a
district state no such plan to the marks yet, and there a name still shows through a wall; the
district's own click already stops at its buildings. Nothing is read back from the picture.

When a minute takes up a model's decision, what the model chose opens over its name, in the action's
offered words as the models read serves them ("Chose “walk to the well”."), with what came of it where
the minute did not act on it and why by its code's words, for as long as a line of speech of that length
stays, and closes ([`thing-decisions.ts`](../web/packages/app/src/composition/thing-decisions.ts)). Each
decision opens once, and none from before the page first read the society. The line says what was
chosen and never why the model chose it: a decision records no reason of its decider's, and the line
has a place for the decider's own stated words that stays empty and takes no room until a decision
contract serves any. It opens for a model's decisions; a person's and an outside program's choices are
not served by that read. The sentence a being's card shows as "Recorded by the engine" is the engine's
own account of what the being is doing, not a model's reasoning. When a person plays a
being (Play this one; the app has no screen to start it yet: see below), it is marked by who decides
now, before its mind: a `You` pill in the world-mark person colour for the one playing it and `Played`
for anyone else, read as played by you or by another person (and, for a visitor the world decides for,
from where, in the words read only); the one playing also sees a steady ring in the same colour at its
feet as the crowd draws it, and another on the ground where its next walk goes, each on a dark edge in
the person ink so it reads on pale ground. Who plays is read from the models read's person choice,
which says only whether the viewer is the one playing, never who.

Each line a being says is drawn over it as it is said, from the society's `said` events read with
each minute: only lines said after the page first read the society, each once, oldest first, at most
four bubbles at once and one per speaker, each shown for two to nine seconds by its length (the marks'
catalog states each of those figures as a budget of reading, with its reason). A line's
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
  a direct request. A person playing a capable being may choose following; current model terms
  also offer it when the society records follow/v3. Accepted pursuit persists until an explicit
  stop or superseding choice, an applied owner command, or the recorded target-loss conditions.
  Older follow/v2 keeps its per-minute rules and is withheld from current model choices. The
  routine never initiates following (so a lantern spirit's `follow_holders_of` is unread), and no
  direct owner request starts it. The routine says nothing and uses no hands; only a model chosen for a being, a visitor's
  own program, or the world's owner's direct request does.
  A visitor the world decides for takes no person's direct request yet, and nobody in the app can
  take a being over and play it.
- A workspace's own kinds and looks are kept and served (a creature's by the creature route, a look
  made elsewhere by the operator's command, and a route erases a drafted creature). A thing may
  wear a look the workspace keeps, by its digest; nothing yet shows a picture of one (`preview` is
  null).
- A creature in a society ([above](#a-creature-in-a-society)) walks at its body's own pace
  only in a society whose first input records the second walking module; in one made before, it
  walks at the people's pace. The pace changes how far it walks in a minute and nothing else: a
  route is still the shortest by length whoever walks it, a follower slower than the one it
  follows falls behind, and the minutes a hands act may take to reach its thing are the same for
  every body, so a slow one may not reach it in time. Its routine is the purposeful routine held to
  the abilities its kind lists. Recorded purposeful/v3 and later read its five purposeful weights; earlier
  versions retain world-routine selection. A wait preference does not remove movement or rest
  capability, and tiredness and making room remain exceptions to ordinary waiting. A creature
  whose kind lists none of rest, visit, stand and talk waits where it is. A decider is told its
  body; nothing drafts a temperament. Only the world's owner gives a being one, as the character
  they write for a being they placed ([who a placed being is](#who-a-placed-being-is)), shown to
  that being's decider alone in a society recording the character module. In a society made
  before paces were read, which moves every body at the people's pace, a small body's legs step as often as that
  pace asks of its short stride, and a large body's seldom. A leg of one segment does not lift as it swings forward. A sketch is posed
  in full at any distance within the crowd's far radius; how many the page poses in a frame is not
  measured. Its owner may choose another admitted workspace look on its exact held body plan.
  The choice is recorded beside the thing; its identity, society minute, decisions and replay
  do not change. Withdrawn, erased, foreign-workspace and incompatible looks are refused;
  a withdrawn chosen look falls back to its admitted first look. A creature placed in a town before
  its people come makes the town's society one of things, and walks its streets by its routine. One
  placed in a living town stands outside the society where it was placed until the town takes in
  what was placed ([a living town takes in what was placed after its people
  came](synthetic-society-contract.md#a-living-town-takes-in-what-was-placed-after-its-people-came)),
  which makes the town a society of things with the same people, where it walks too.
- A model's line names its model only where its said event records one (a society made since its
  modules are recorded keeps it) and the page has read that model; otherwise it says `an AI model`.
  A person in flight wears no pill: the flock draws them, not the crowd.
- No creature flies, climbs or burrows: the grammar states those movements and refuses them in
  words. A floating body walks by no module; one with four or more tentacles swims, and any other
  cannot move at all yet. How a swimmer is drawn and a swimming activity in the routine are not
  built: a swimmer is drawn along its path as a walker is, and swims only on the way to somewhere on
  land. The shipped pond duck's kind names no swimming yet, so it walks round water.
- A creature may wear an admitted compatible look. The sculpted-look pipeline (route C
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
| The society of things | [`society_things.py`](../exulanica/world/society_things.py), [`society_thing_inputs.py`](../exulanica/world/society_thing_inputs.py), [`crossings.py`](../exulanica/world/crossings.py), the things composition in [`society_authored_ground_uses.py`](../exulanica/world/society_authored_ground_uses.py) and, on a generated town, in [`society_walking_surfaces.py`](../exulanica/world/society_walking_surfaces.py), migrations 0151 and 0169 | `tests/test_society_things.py` (genesis, a minute equal to the planner's, placed beings, crossings, the state check), `tests/test_society_thing_inputs.py` (the composition and its shape), `tests/test_society_things_postgres.py` (through the routes: made by name, an edit reaching it, a visitor crossing in and out, replay), `tests/test_outside_deciders_postgres.py` (a visitor decided for by its own program), `tests/test_traveller_choices_postgres.py` (a visitor the world decides for, by its gate's travellers' choice), `tests/test_society_request_rule_parity.py`, `tests/test_walking_surfaces_v3.py` (a town's things: what blocks, what is offered, what is unreachable, the town's v1 and v2 inputs unchanged), `tests/test_walking_surfaces_v3_postgres.py` (a society of things on a town through the routes, replayed; the input checks), `tests/test_town_target_names.py` (what a town's place calls a premises or a bench on its targets, an input from before the field, a name never moving a destination, every label lower case) |
| A creature in a society | [`run_forms.py`](../exulanica/things/run_forms.py), [`body-names.v1.json`](../assets/catalogs/things/body-names.v1.json), [`society_kinds.py`](../exulanica/world/society_kinds.py), `ThingStore.run_form` in [`thing_store.py`](../exulanica/world/thing_store.py), the composers' `made_kinds` in [`society_authored_ground.py`](../exulanica/world/society_authored_ground.py) and [`society_walking_surfaces.py`](../exulanica/world/society_walking_surfaces.py), the things phase in [`society_things.py`](../exulanica/world/society_things.py), the made being's card in [`thing_card.py`](../exulanica/api/thing_card.py), the erasure telling societies in [`thing_store.py`](../exulanica/api/routes/thing_store.py) | `tests/test_thing_kind_run_forms.py` (each fixture creature assembled under nonsense words: none of them, nor the drafting model's provenance, the recipe's digest or the plan's title, in its run form; every string of a run form in a vocabulary read from the catalogs' own files; each body's name and four bodies' sentences written by hand; its sockets the plan's own and its figures the fixture's; each field that could carry words refused by name; a kind, plan and recipe that do not belong together refused), `tests/test_society_made_kinds.py` (with no database: it arrives named by its body and by its kind's digest alone, the input and the state stating its run form once; two of one kind told apart by number; it walks and stays by the routine and an hour twice is the same bytes; it is offered what its kind lists and may be given a mind or played; a decider is told its body's sentence; jaws pick a sword up into `mouth` and a body that holds with nothing is offered no hands act; it leaves the minute its kind is erased, for that reason, and the society goes on; an author's removal stays an author's removal; none of the nonsense words in the inputs, the states, the events or a decider's context, with a positive control; an input with no made thing keeps its bytes; the input's and the state's checks each refuse a made kind stated wrongly), `tests/test_society_made_kinds_postgres.py` (through the routes: a creature alone makes the world one of things and lives in its society, which replays; its card names it as its maker did with who drafted it and who decides, and refuses another look by name; erasing it appends an input naming the kind gone, its card then names nothing, the being leaves the next minute for that reason, the society replays, and no row of any table of the schema holds a nonsense word, which the same search found in the workspace's store before; a society that could not be told loses the being at its next input), `tests/test_placed_workspace_kinds_postgres.py` (a world holding only a creature is a world of things while its kind is held and not once it is erased), `tests/test_made_creature_in_a_town_postgres.py` (a kept creature placed in a small town before its people come makes its society one of things and walks a path away from where it was placed; placed in a living town, it is taken in with the town's take-in and walks there too; each society replays), `web/packages/atlas-react/test/things-workspace-kind-standing.test.ts` (a being named by digest alone drawn by the crowd in its sketch; an erased kind a miss by name), `web/packages/app/test/visitor-notices.test.ts` and `thing-lines.test.ts` (a kind's reference read in either shape; a line's header naming a made speaker as the workspace's store does), `web/packages/app/test/thing-card-route.test.ts` and `thing-card-placed.test.ts` (the card's drafting model) |
| Creatures: recipes, plans, sketches, assembly | [`bodies.py`](../exulanica/things/bodies.py), [`sketch.py`](../exulanica/things/sketch.py), [`creatures.py`](../exulanica/things/creatures.py), [`body-grammar.v2.json`](../assets/catalogs/things/body-grammar.v2.json) | `tests/test_creature_bodies.py` (thirteen hand-written creatures: each body where its recipe says, a left limb the mirror of its right, each limb of a lying body hung from the stretch of spine beside it, the bone count the recipe's own sum, each refusal by name, the sketch read back from its bytes) |
| The creature drafter | [`creature_drafting.py`](../exulanica/selection/creature_drafting.py), [`creature-drafting.v3.json`](../exulanica/selection/creature-drafting.v3.json) | `tests/test_creature_drafting.py` (scripted replies: a pass with its provenance, a refusal repaired with its check's sentence, two refusals, a form outside the schema, a reply cut off in blank space; a label of 32 letters builds and one of 33 is refused by the form, the words and the assembly alike), `tests/test_hosted_boundary.py` (its request carries no saved name) |
| A workspace's own things | [`thing_store.py`](../exulanica/world/thing_store.py), [`thing_store_command.py`](../exulanica/hosting/thing_store_command.py), the routes in [`thing_store.py`](../exulanica/api/routes/thing_store.py), migrations 0159 and 0172, the `looks` namespace and its purge in [`namespaces.py`](../exulanica/store/namespaces.py), the seed's refusal in [`judge_seed.py`](../exulanica/orchestration/judge_seed.py) | `tests/test_thing_store_admission.py` (with no database: a static and a skinned look read by their containers' readers, a broken rig refused; a look the reader refuses, a shipped key, a look that draws no file and another container each refused by name; the line rule on the label and each word of the origin, its licence's address included, the field named; a share-alike look refused without its attribution, its authors or its licence's address), `tests/test_thing_store_postgres.py` (as the deployed writer: a drafted creature kept whole and read back at its assembly's digests; no update or delete, even by the table's owner (the owner's TRUNCATE is not refused: no truncate guard like 0013's is attached); another workspace reads none of it and keeps its own; each table's row written only in its own workspace's context, even by a superuser; a shipped kind, plan or look key, another container, a held version drawn from other bytes and a full library of kinds or of looks each refused with nothing written, bytes included; a look kept only after its intake's own check, with its licence as columns; the table's own checks on a share-alike look's credit, a container profile and its look kind, a kind's plan digest and a withdrawal's digest; a withdrawn look passed by unless asked for, its kind still read, and a look the reader refuses withdrawn by its row), `tests/test_thing_erasure_postgres.py` (an erasure removes a creature's kind, plan, recipe, looks and their withdrawals at once and nothing of another creature, naming the kind by digest and its `creature` tombstone only; the rows go only through it, not by the runtime role nor the table's owner; a plan or recipe another still names stays, and a shared recipe holds no words digest; an unknown, foreign or somebody else's kind refused with nothing deleted and no tombstone; the same creature in another workspace untouched; the erasure waits for the workspace's lock; its containers, a second look's on the plan too, destroyed by the purge, which completes its tombstone; a container another creature or the same creature kept again names stays, its job waiting, or skipped when the look arrives while the purger waits for the container's lock; a creature tombstone reaching no capture, photograph, artefact or other creature, and a capture tombstone erasing no creature; a container recorded before its bytes, its purge waiting for them; a keep that dies after recording, or is refused after it, reached by the workspace's erasure; the migration's backfill recording containers kept before the inventory; a workspace tombstone purges every recorded container, an erased creature's too, completion waiting for it, a worker without the looks namespaces leaving it open, a capture tombstone not authorized; the purge command's worker destroying them; a database without the look question claiming every other kind; nothing kept after it), `tests/test_thing_store_words.py` (every string a sketch container holds, for every fixture creature and 160 recipes drawn across the grammar: names from the grammar's vocabulary, colours from its palette and nothing else but the format's own words), `tests/test_restore_replay_withdrawals.py` (a look withdrawn after a backup stays withdrawn, and a creature erased after a backup stays erased, its container purged by the replayed tombstone, through a real restore, as it does when the backup holds its withdrawn sketch or when the whole workspace is erased after it), `tests/test_thing_store_command.py` (a mapping admitted only when a declared bridge pins it and the door's check reads it; the intake's check on the entry's digest, source, SPDX identifier and share-alike mark and on the look being imported; a look document that is not JSON and a withdrawal reason that is not one line refused by the dry runs; against PostgreSQL, a dry run that writes nothing, a copy relabelled CC0 and public and an unpinned mapping refused with nothing written, the positive control, once only, a listing and a withdrawal), `tests/test_thing_store_routes.py` (as a deployment serves them: the document's bytes hash to the URL's digest; the container's bytes, tag and `no-cache`, a revalidation answered 304 with no body; a kind; another workspace's, a withdrawn, a revalidated withdrawn and an absent one all 404 alike, and missing bytes too; 503 without a look store; a writer's erasure, then 404 for its kind, look and container, a reader, a token without `deletion.write`, a stranger and an invented digest erasing nothing, nor an installation sealed for a restore; a session required), `tests/test_judge_seed.py` (a workspace holding a look, a kind or an unpurged container of its own is not seeded, and a schema without the inventory is read without it), `tests/test_existence_oracle.py` (a stranger cannot tell a held look or kind from an invented digest) |
| A creature's made look | [`creature_look_jobs.py`](../exulanica/world/creature_look_jobs.py), the operator's run in [`creature_look_command.py`](../exulanica/hosting/creature_look_command.py), the routes in [`thing_creatures.py`](../exulanica/api/routes/thing_creatures.py), the kind looks in [`thing_looks.py`](../exulanica/world/thing_looks.py), migration 0220 | `tests/test_creature_look_jobs_postgres.py` (as the deployed writer: a look asked once for a kept creature and answered again while it waits; a kind not kept, or a digest that names no creature, refused; a requester at their limit refused, another counted alone; a run stages a job with its request's digest and ends it once, another run ending nothing; a made look worn by its kind, the newest still kept, a withdrawn one worn no more, and a look the workspace does not keep never worn; the rows change only forward, a job dated by the statement that asks it; a run's end and wear and a creature's erasure taking the workspace's lock in one order, so an erasure asked between them waits and never closes a cycle; no delete by the runtime or the table's owner, only by the definer owner; row-level security forced and keyed on the workspace, another workspace reading none; a creature's erasure taking its jobs and kind looks and nothing of another creature; a workspace tombstone taking all of them, after which nothing more is asked), `tests/test_thing_creatures_routes.py` (as a deployment serves them: asked once, 202 and queued, read by any member of the workspace; another workspace and an invented id 404; a kind not kept and a kept one asked from another workspace 404 alike; a caller without `world.write` and `model.invoke` 404 with nothing queued), `tests/test_existence_oracle.py` (a stranger cannot tell a held kind or job from an invented one), `tests/test_creature_drafts_postgres.py` (a kept draft asks its creature's made look for its owner, a queued job calling no model; an owner at their look limits keeps the creature with no job; a refused draft asks nothing), `tests/test_thing_creatures_routes.py` (a kept draft names its creature's look job as the look route answers it, a draft conditioned on a reference names none and asks none, an erased creature's draft names none), `tests/test_creature_look_command.py` (against PostgreSQL with stand-in models: dry runs write nothing; staging writes the request and marks the job staged under the run; admitting keeps the made look, generated, private, on the creature's plan with the fit's receipt and cut-out in its lineage, ends the job made with its share of the cost, and the kind wears it; admitting again keeps nothing; a refused fit and an unmade request end their jobs by code, an end the database broke off to end a lock cycle tried again; a creature erased after staging keeps nothing), `ml/appearance/tests/test_creature_pictures.py` (the job record draws each request once a seed, seed-major, and is checked; a run's fit keeps each request's first passing model, a refused body by code, an unmade request failed), `tests/test_kind_looks_worn.py` (with no database: a being with no choice wears its kind's made look before its first, its own choice first, a look on another plan or no longer kept passed by, another kind's never; a participant reads a present being's kind look and no absent kind's), `web/packages/app/test/thing-looks-api.test.ts` and `things-composition-looks.test.ts` (the page reads `kind_looks`, an unheld one left out, and dresses a thing with no choice in its kind's look, its own choice first, an unchanged look not given again, a withdrawn one returning it to its first) |
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
