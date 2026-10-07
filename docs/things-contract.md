# Things contract

Status: **THING KINDS, BODY PLANS, ABILITIES, OFFERS, LOOKS, THE ORIGIN RECORD AND TRANSLATION
MANIFESTS ARE DATA HELD TO THEIR CHECKS, A WORLD'S AUTHOR PLACES THINGS BY THEIR KIND, THE SOCIETY OF
THINGS LIVES WITH THEM AND ITS BEINGS SAY LINES AND LEAVE BY THEIR DECIDERS' CHOICE, A CREATURE'S BODY
PLAN, SKETCH AND KIND ARE BUILT FROM A DRAFTED BODY RECIPE, AND THE BROWSER DRAWS A VERSION'S PLACED
THINGS BY THEIR LOOKS**.

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
where its kind's deciders allow the routine. What a society
is given of a kind is `ThingKind.semantics()`: every field but `looks`, `origin`, `ext` and
`summary`, with the kind's reference, so no look reaches a society through its kind.

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
| `follow` | `exulanica-ability/follow/v1` | a way to move | `be_followed` | |
| `say` | `exulanica-ability/say/v1` | nothing; takes a line | `hear` | |
| `leave` | `exulanica-ability/crossing/v1` | a way to move | `leave_through`, or none | `quiet_minutes` 1 to 60 |

The purposeful abilities are the purposeful routine's actions with exactly its rules, and talking
stays wordless: words are said. A line is written only by a decider, never by the routine.

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
look a crossing brings, reading only the shipped catalogs, so a door refuses an arrival before it
writes anything; `record_crossing_look` records it, for a door to call in the transaction of the
minute that binds the arrival as arrived, once per crossing however often it is handed over. Choices
are appended and never changed, each naming the crossing or the actor that made it, and the newest
per thing is worn; a thing with none wears its kind's first look.
`GET /world/versions/{version_id}/thing-looks` (`world.read`, never cached) answers
`exulanica.thing-look-choices/v1`: the newest choice for each thing of the version, in thing id
order, each with the thing's id in its society, the author's id for a placed thing, the look, who
chose it and when. Choices stay with the version, as its society does.


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
| `traveller` | being | humanoid, 1,550 to 1,800 mm | as the knight | as the knight | as the knight | `blocky-traveller` |
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
| `lamp_post` | object | its catalog dimensions, blocking walking | | perch | | its reviewed asset |

| Look | Look kind | Origin |
| --- | --- | --- |
| `blocky-knight`, `blocky-traveller` | `rigid_on_bones` | authored here, CC0 |
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

## Drawing

The browser draws a thing from its look, never from what it is
([`things/`](../web/packages/atlas-react/src/playcanvas/things)). It reads the host's thing library
by digest: the list names every kind, look, container and the body plans catalog by the SHA-256 of
its bytes, and every answer is hashed again and refused by name when it is other bytes, so nothing
substituted or truncated is read. One figure draws each look kind:

| Look kind | Drawn as |
| --- | --- |
| `catalog_person` | One of the world's people, drawn from the thing's id by the people catalog's draw |
| `skinned` | The rigged container with its own clips; standing, walking and running blend by ground speed (`rig.ground_speed_mm_per_s`), a clip plays at most twice its pace, and a motion with no clip is drawn idle. A rig with no clips at all, as a creature sculpted for its own plan has, is posed by the same solved gait as `rigid_on_bones`, its skin following its joints; it must rest translation-only with each joint hung from its plan parent's, and is refused by name otherwise |
| `rigid_on_bones` | The container's `bone:<name>` nodes, each hung from its nearest dressed ancestor in the body plan's parent table, posed procedurally |
| `light` | An omni light of the look's colour, intensity and radius, a core and a glow, floating 1,250 mm over the thing's point and drifting within its radius (presentation only) |
| `static` | The container at the thing's place, turned by its placed yaw as an authored object is |
| `look_role` | The engine's box primitive in the kind's box: no style pack dresses a thing yet |
| `none` | Nothing; the thing keeps its place |

A body is drawn at its look's natural height kept inside its kind's height range, so a look never
makes a kind taller or shorter than the kind allows. No bone is named in the drawing: a skeleton's
limbs are read from its shape and its plan's sockets (a chain ending near the ground is a leg, one
carrying a socket an arm, the one ending highest the head), so any body plan's skeleton is read the
same way. Standing figures breathe and turn their heads; walking figures step in their skeleton's
gait, clocked by the distance walked so a planted foot never slides; under reduced motion they stand
still.

A version's placed things stand where it places them, in the frame their region is drawn in: the
region a saved world's people live in, or an authored object's region root. A thing in a region
the world does not draw, a document the library does not hold at its digest, a look kind the page
does not draw or a container that does not read is drawn as nothing, its reason kept by name
(`ThingLayer.misses`), never stood in for.

Where a society of things runs (`exulanica-society/v7`), its people are the society's crowd's, which
walks everyone along their recorded paths as it walks every society's people. A person whose look
is not the people catalog's is drawn by its own figure, in full wherever it is within the crowd's far
radius and ranked before the world's people for the full places of the measured budget; a placed
being's standing figure is then not drawn. A placed being faces as it was placed until it first
walks, by the same rule the layer turns it by before a society holds it: its yaw turns the look's
front from +Z, so at yaw 0 it faces +Z. Each object stands where the state puts it, its plan point
turned by its yaw, or is held in the socket the state names, its grip at the socket's place; an
object the state does not list is not drawn. A rigged look whose rig names a hold clip stands in it
while it holds something.

A thing wears the look chosen for it where one is, from the looks chosen for its version's society
(`GET /world/versions/{version_id}/thing-looks`): a person in the crowd, a placed thing in the layer; a
thing with none wears its kind's first look. The choices are read when a society of things is first
drawn and again when a state lists a thing no read has covered, as a visitor whose look its crossing
chose, at most once a minute; a person whose look changes is made again where they stand, and nobody
else is.

Who runs each person of a saved world's society is marked over them, by one decision the thing card
makes too ([`composition/thing-marks.ts`](../web/packages/app/src/composition/thing-marks.ts)): a
person whose model is asked (chosen for them, and refused neither by the host nor for them) wears an
`AI` pill with the first word of the model's served name; a visitor wears its bridge's mark as the
door lists it here, `from` and the bridge's label for a game a person plays, an outlined `AI` pill
for an outside agent, and `from outside` for a bridge the door does not list; everyone else, and every
object, wears none. The pills are part of the page, not the picture: a fixed pool of nodes placed each
frame over the box a person is drawn and picked by, read by a screen reader in the card's words and
picked by a click as by aiming. The model's short name and the person's kind show over the selected
person, a speaking one and the three nearest marked people within 12 m drawn on screen; no pill is
drawn beyond 60 m.

Aiming and pressing E picks the nearest drawn thing or person along the ray. A picked thing raises
one event on the shell, `exulanica:thing-pick`, whose detail names it by the version's id, the
society's thing id and its person id where each exists, and how it was picked; the same event with
no detail clears the pick. The picked thing wears a ring in the design tokens' signal colour.

## What is not built

These are material limits of the boundary above, not partial behaviour:

- The society of things ([society contract](synthetic-society-contract.md#the-society-of-things-v7))
  reads a placed thing's kind, places its beings, lets visitors cross in and leave, and says the lines
  its beings' deciders choose, but no ability module runs: its people walk, choose, stay and talk by
  the purposeful planner's rules, and the hands and following the abilities catalog names are not
  built. The routine says nothing; only a model chosen for a being, or a visitor's own program, does.
  A visitor the world decides for takes no person's direct request yet, and nobody in the app can
  take a being over and play it.
- No store holds a workspace's own kinds or looks: the library serves the shipped ones only, a
  placed thing names a shipped kind and a thing wears a shipped look. The world's owner has no
  route to choose a look, and a look is recorded only where a door records its crossing's.
- The browser draws no hand-over between two people as it happens (a thing is drawn in the hand
  the state names at each minute), no line a person says (the bubble that draws one, opening with
  its speaker's pill, is built; nothing carries lines to it). An outside agent's pill says `agent`
  rather than the name it gives itself, which no read serves the page yet, and a person in flight
  wears no pill: the flock draws them, not the crowd.
- No crossing writes a translation manifest yet; the look importer writes one for each look it
  makes.
- No route drafts a creature or keeps its documents. The drafter is measured and bound to its own
  manifest role, `creature_drafter` (see [model and service selection](model-and-service-selection.md)),
  and is reached by tests and the measurement only.
- No creature flies, swims, climbs or burrows: the grammar states those movements and refuses them
  in words. A floating body therefore cannot move at all yet.
- No creature wears a sculpted look: its sketch is its only look. The route that makes one (route C
  of [generated appearance](generated-appearance.md)) is built. In its pre-registered rig trial one
  body of eight counted, against the five the rule needed, so the sketch stays every creature's
  default. Nothing in the product asks for a sculpted look yet. A look request is written by
  [`creature_looks.py`](../exulanica/things/creature_looks.py) from a creature's body and sketch.

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
| Look choices | [`thing_looks.py`](../exulanica/world/thing_looks.py), [`world_things.py`](../exulanica/api/routes/world_things.py) (the read), migration 0156 | `tests/test_thing_looks.py` (a shipped look fit for the kind, each refusal by name), `tests/test_thing_looks_postgres.py` (as the deployed writer: one look per crossing, the newest per thing, no change or removal; the table's shape and its append-only trigger; another workspace sees nothing; the route) |
| Placed things | [`placed_things.py`](../exulanica/world/placed_things.py), the object repository, [`world_things.py`](../exulanica/api/routes/world_things.py), migration 0152 | `tests/test_placed_things.py`, `tests/test_placed_things_postgres.py` (as the deployed writer: place, move, remove, undo and place again; the kind fixed by the table; another workspace sees nothing; a branch keeps them; the routes' refusals by name), `tests/test_edit_kind_undo_postgres.py` |
| The society of things | [`society_things.py`](../exulanica/world/society_things.py), [`society_thing_inputs.py`](../exulanica/world/society_thing_inputs.py), [`crossings.py`](../exulanica/world/crossings.py), the things composition in [`society_authored_ground.py`](../exulanica/world/society_authored_ground.py), migration 0151 | `tests/test_society_things.py` (genesis, a minute equal to the planner's, placed beings, crossings, the state check), `tests/test_society_thing_inputs.py` (the composition and its shape), `tests/test_society_things_postgres.py` (through the routes: made by name, an edit reaching it, a visitor crossing in and out, replay), `tests/test_outside_deciders_postgres.py` (a visitor decided for by its own program), `tests/test_traveller_choices_postgres.py` (a visitor the world decides for, by its gate's travellers' choice), `tests/test_society_request_rule_parity.py` |
| Creatures: recipes, plans, sketches, assembly | [`bodies.py`](../exulanica/things/bodies.py), [`sketch.py`](../exulanica/things/sketch.py), [`creatures.py`](../exulanica/things/creatures.py), [`body-grammar.v1.json`](../assets/catalogs/things/body-grammar.v1.json) | `tests/test_creature_bodies.py` (thirteen hand-written creatures: each body where its recipe says, a left limb the mirror of its right, each limb of a lying body hung from the stretch of spine beside it, the bone count the recipe's own sum, each refusal by name, the sketch read back from its bytes) |
| The creature drafter | [`creature_drafting.py`](../exulanica/selection/creature_drafting.py), [`creature-drafting.v1.json`](../exulanica/selection/creature-drafting.v1.json) | `tests/test_creature_drafting.py` (scripted replies: a pass with its provenance, a refusal repaired with its check's sentence, two refusals, a form outside the schema, a reply cut off in blank space), `tests/test_hosted_boundary.py` (its request carries no saved name) |
| The skinned container | [`skinned.py`](../exulanica_pieces/skinned.py) | `tests/test_skinned_glb.py` (containers built in the test from struct packing: a positive control, then each rule broken alone and refused by name) |
| A creature's look request and its sculpted look | [`creature_looks.py`](../exulanica/things/creature_looks.py), `ml/appearance/exulanica_appearance/creatures/` | `tests/test_creature_sculpt.py` (each development creature's sketch filled, rigged, written and read back against its plan's tree; the creature job end to end with stand-in models, a body that is not its plan's refused by the rig with its measures in the receipt), `ml/appearance/tests/test_creature_rig.py` and `test_creature_route.py` (a box figure: every check against a positive control, fused legs refused with every measure, a missing leg, a turn undone to the degree, a stretched body refused with the fit it refused); the rig trial on Nebius AI Cloud, [record](evaluation/2026-10-07-creature-rig-trial.json) |
| No creature in code | | `tests/test_no_creature_code.py` (with a planted name the scan finds) |
| Purity | The import contract "Things are pure data" in `pyproject.toml`: no database, store, evidence, pipeline, world, traffic, movement step, model or numeric stack | `lint-imports` |
| Drawing | [`things/`](../web/packages/atlas-react/src/playcanvas/things), [`composition/things.ts`](../web/packages/app/src/composition/things.ts), [`things-library.ts`](../web/packages/app/src/things-library.ts) | `web/packages/atlas-react/test/things-*.test.ts` (the shipped documents read, digests refused, skeletons read by shape with a ten-legged plan, planted feet, placement, misses, picking, a society's things through the crowd, a held thing in its holder's hand, the marks and lines overlay), `web/packages/atlas-react/test/society-crowd-things.test.ts`, `web/packages/atlas-react/test/society-crowd-anchors.test.ts`, `web/packages/atlas-react/test/society-crowd-refresh.test.ts`, `web/packages/atlas-react/test/things-placed-facing.test.ts`, `web/packages/app/test/things-composition.test.ts`, `web/packages/app/test/environment-selection-things.test.ts`, `web/packages/app/test/environment-selection-marks.test.ts`, `web/packages/app/test/thing-marks.test.ts`, `web/packages/app/test/door-bridges-api.test.ts`, `web/packages/app/test/thing-looks-api.test.ts`, `web/packages/app/test/things-composition-looks.test.ts`, `web/packages/app/test/environment-selection-looks.test.ts`, `web/packages/app/test/things-composition-facing.test.ts` |
