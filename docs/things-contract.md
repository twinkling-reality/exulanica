# Things contract

Status: **THING KINDS, BODY PLANS, ABILITIES, OFFERS, LOOKS, THE ORIGIN RECORD AND TRANSLATION
MANIFESTS ARE DATA HELD TO THEIR CHECKS, AND A WORLD'S AUTHOR PLACES THINGS BY THEIR KIND; NO
SOCIETY ENGINE OR RENDERER READS A THING KIND**.

A thing is anything addressable in a world: a knight, a lantern spirit, a sword, a well, a gate, a
visitor that came in from another program. What a kind of thing is and can do is one typed,
versioned, fingerprinted record, its **thing kind**. How it is drawn is a separate record, a
**look**, any look of its body may be chosen, and nothing the thing does depends on which. Where a
kind, a look or a crossing came from is one **origin record**. A new kind of thing is data held to
deterministic checks, never code of its own.

This contract owns the thing kind and its checks, the four catalogs a kind is read against (body
plans, abilities, offers and look kinds), the look, the origin record and the readers that turn
each existing origin vocabulary into it, translation manifests, and the kinds and looks this
repository ships. Who decides for a thing, including an outside program, is the
[decision roles contract](decision-roles-contract.md)'s; walking is the
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
- [The kinds and looks this repository ships](#the-kinds-and-looks-this-repository-ships)
- [What is not built](#what-is-not-built)
- [Implementation and evidence](#implementation-and-evidence)

</details>

## Names

| Term | Meaning | Not to be confused with |
| --- | --- | --- |
| thing | Anything addressable in a world | the evidence graph's `entity` |
| thing kind | What a kind of thing is and can do, `exulanica.thing-kind/v1` | a world kind, which is a kind of world |
| body plan | The semantic shape of a body: bones, sockets, size and motions, named `<key>/v<version>` | a vehicle's body family in traffic |
| ability | Something a thing can do, served by one ability module (`exulanica-ability/<name>/v<N>`) | a model's answering mechanism |
| offer | Something a thing lets others do to it | the society's affordances (rest, visit, stand, talk), which offers map onto |
| look | One way a thing of a body plan is drawn, `exulanica.look/v1` | a character look, which is a recipe over one catalog body |
| look kind | How a look is drawn, and which plans it fits | a style pack's look role, which one look kind draws |
| origin record | Where a piece came from, `exulanica.origin/v1` | an assertion's provenance, which says who supports a claim |
| translation manifest | What an import or a crossing kept and lost, `exulanica.translation-manifest/v1` | |

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
([world objects contract, section 14](world-objects-contract.md#14-placed-things)). What a society
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
spirit is refused it by name. No four-legged, winged or wheeled plan is stated: a wolf has no body
here.

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
| `rig` | where its look kind is rigged: every bone of the plan it maps to one of the rig's joints, each joint once, all the plan's required bones mapped, and the rig's clip for each motion it has |
| `height_mm` | its natural height, within the plan's bounds, for a body with a height; none otherwise |
| `sampling` | `linear`, or `nearest` for pixel art |
| `light` | where its look kind is a light: an sRGB colour, an intensity and a radius |
| `role` | where its look kind is dressed by a style pack: the look role, `family.leaf` |
| `origin` | its [origin record](#the-origin-record) |

[`look-kinds.v1.json`](../assets/catalogs/things/look-kinds.v1.json) states how looks are drawn:

| Look kind | Plans | What it is |
| --- | --- | --- |
| `catalog_person` | humanoid | A person drawn from the published people catalog by the street population draw, as every society's people are drawn |
| `skinned` | humanoid | A rigged glTF figure admitted as a reviewed component, with its own clips; its rig maps every required bone |
| `rigid_on_bones` | humanoid | One `exulanica.static-glb/v1` container with one node per dressed bone, named `bone:<VRM name>`, each a direct child of the scene root at that joint's rest position with no rotation or scale, its rigid parts as children; joint nodes for all 15 required bones; posed by procedural motion on the bones |
| `light` | bodiless | No file: a light, a glow and a slow drift, in the colour and radius the look states |
| `static` | rigid | One `exulanica.static-glb/v1` container inside the thing's box: a reviewed object, a person's prepared asset or a generated piece |
| `look_role` | rigid | A look role the world's style pack dresses, fitted to the thing's box |
| `none` | all | Nothing is drawn; the thing is still there |

**Requirement:** no look reference enters a society's input, state or decision context. Looks are
records apart from what a thing is, a kind is given to a society only through its semantics, and
a crossing's look rides beside its arrival, never in it. Swapping a thing's look therefore changes
no state and no decision.

The looks this repository authors are recipes in [`authored.py`](../exulanica/things/authored.py),
written by [`pieces.py`](../exulanica/things/pieces.py) into a binary glTF the same on any machine:
every vertex a whole number of millimetres turned into metres by one float32 division, a cylinder's
corners from a table of square roots. Their containers are not committed. Each look document pins
its container's digest and length, and a test writes each container again, compares it and passes
it through the product's static glTF admission (`inspect_static_glb`). A blocky figure stands its
joints where a 1,700 mm figure's stand in the T-pose, with an upper arm, a lower arm and a hand as
three boxes, so its elbow bends.

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
what it read), the thing kind and look it became, and every field of the source exactly once:

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

## The kinds and looks this repository ships

[`scripts/things/shipped_things.py`](../scripts/things/shipped_things.py) writes every shipped look
and the first version of every shipped kind, and `--check` exits non-zero when a committed one
differs. A later version of a kind is data: its committed document is the source, which the script
reads, checks against the things catalogs and formats, and never writes from figures of its own.
The script keeps the lock, adding a line for each new version and refusing to change one already
there. The six pieces of furniture are derived from the world object catalog, their places, seats,
perches and hosted flyers as that catalog derives them, so no figure is stated twice. The kinds are
this project's own, under the repository's licence.

| Kind | Class | Body | Abilities | Offers | Deciders | Look |
| --- | --- | --- | --- | --- | --- | --- |
| `knight` | being | humanoid, 1,700 to 1,900 mm | wait, stand, talk, rest, visit, pick_up, put_down, give, take, follow, say | talk_to, hear, receive, be_followed | the routine by default; a model, the owner or an outside program | `blocky-knight` |
| `traveller` | being | humanoid, 1,550 to 1,800 mm | as the knight | as the knight | as the knight | `blocky-traveller` |
| `lantern_spirit` | being | bodiless, radius 200 mm | wait, follow, say, pick_up, put_down, give, take | talk_to, hear, receive, be_followed | as the knight; its routine follows whoever carries a lantern | `spirit-light` |
| `visitor` | being | humanoid, 1,500 to 2,000 mm | wait, stand, talk, say, pick_up, put_down, give, take, follow, leave after 5 quiet minutes | talk_to, hear, receive, be_followed | an outside program only | none: its crossing brings one |
| `villager` | being | humanoid, 1,500 to 1,950 mm | wait, stand, talk, rest, visit | talk_to, hear | the routine; a model or the owner | `people-catalog` |
| `sword` | object | version 2: 240 x 80 x 1,000 mm, as wide and deep as a sword's guard and pommel; version 1: 120 x 40 x 1,000 mm | | holdable, one hand, 150 mm up its length | | `primitive-sword` |
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

## What is not built

These are material limits of the boundary above, not partial behaviour:

- No society engine reads a thing kind, and no ability module runs: the abilities catalog names
  modules no registry states. A world's people are the society's own, drawn as today.
- No store holds a workspace's own kinds or looks, or the look chosen for a thing, and no route
  serves a kind, a look or a look's container. A placed thing names a shipped kind.
- The browser draws no thing by its look kind.
- No importer or crossing writes a translation manifest; the reader and its accounting check exist.

## Implementation and evidence

| Part | Source | Tests |
| --- | --- | --- |
| Catalogs | [`catalogs.py`](../exulanica/things/catalogs.py), [`assets/catalogs/things`](../assets/catalogs/things) | `tests/test_thing_kinds.py`, `tests/test_catalog_provenance.py` (every entry says why it exists) |
| Thing kinds | [`kinds.py`](../exulanica/things/kinds.py) | `tests/test_thing_kinds.py` (each refusal by name, against a positive control) |
| Looks | [`looks.py`](../exulanica/things/looks.py), [`authored.py`](../exulanica/things/authored.py), [`pieces.py`](../exulanica/things/pieces.py) | `tests/test_thing_kinds.py`, `tests/test_thing_looks_and_origins.py` (each authored container written again and admitted, a blocky figure's joints, a static look inside its box) |
| Origin record and vocabularies | [`origin.py`](../exulanica/things/origin.py), [`vocabularies.py`](../exulanica/things/vocabularies.py) | `tests/test_thing_looks_and_origins.py` |
| Translation manifests | [`manifests.py`](../exulanica/things/manifests.py) | `tests/test_thing_looks_and_origins.py` |
| Shipped kinds and looks | [`shipped_things.py`](../scripts/things/shipped_things.py), the lock `kinds.lock.json` | `tests/test_thing_kinds.py` (`--check`), `tests/test_placed_things.py` (every shipped version at its locked digest; a changed, unlocked or missing file refused) |
| Placed things | [`placed_things.py`](../exulanica/world/placed_things.py), the object repository, [`world_things.py`](../exulanica/api/routes/world_things.py), migration 0152 | `tests/test_placed_things.py`, `tests/test_placed_things_postgres.py` (as the deployed writer: place, move, remove, undo and place again; the kind fixed by the table; another workspace sees nothing; a branch keeps them; the routes' refusals by name), `tests/test_edit_kind_undo_postgres.py` |
| Purity | The import contract "Things are pure data" in `pyproject.toml`: no database, store, evidence, pipeline, world, traffic, movement step, model or numeric stack | `lint-imports` |
