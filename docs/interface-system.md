# Interface system

This contract owns how the browser application looks, where its surfaces sit, how its actions are
declared and offered, and how it speaks. It covers the design tokens, the components, the icon set,
the layout regions and their stacking order, the action registry and its availability, and the words
(the voice guide, the glossary and how a refusal is said). What a person does in a world, and how
the Atlas draws it, is the [interaction model](interaction-model.md); what each operation does is its
domain contract; which operations a world offers is [world capability discovery](capabilities/world-api.md).

## 1. One home for each decision

| Part | Home | What it decides |
| --- | --- | --- |
| Tokens | `web/packages/app/src/ui/system/tokens.css` | every colour role, space, type size, radius, shadow, focus ring, duration and stacking layer |
| Components | `web/packages/app/src/ui/system/components.ts`, `components.css` | Button, IconButton, Toolbar, Panel, Dialog, StateChip, StatusLine, Toast, Tabs, Tooltip, Field, EmptyState, ErrorState |
| Icons | `web/packages/app/src/ui/system/icon.ts` | the one table from interface meanings to lucide glyphs |
| Layout | `web/packages/app/src/ui/system/layout.ts`, `layout.css` | the named regions, which surface sits in which, and the stacking order |
| Actions | `web/packages/app/src/ui/actions/registry.ts` | every action, its words, icon, group, placement, shortcut, operation and refusal words |
| Words | `web/packages/app/src/ui/copy.ts`, `ui/words/`, `assets/catalogs/society-words/` | what a person reads |

A change to the look is an edit to a token; a change to a word is an edit to its catalog; a new
action is one registry entry and one binding. `web/packages/app/src/ui/system/bridge.css` dresses
surfaces written before the system in its tokens and only shrinks as they move onto the components.

## 2. Tokens

Components and layout read semantic roles and never write a literal of their own.

- Colour roles: surface (with raised, sunken, hover, pressed, selected, scrim), text (muted, faint,
  disabled, on accent, on status), border, one accent, one signal (with its own ink), the brand
  blend, and the status roles positive, caution, danger and info, each with hover, pressed,
  disabled, soft and text variants. Light is the default; `data-ui-scheme="dark"` on the root
  element chooses the dark scheme and `"system"` follows the operating system. The Settings choice
  "Light or dark" (Light, Dark, Follow the system; Light unless changed) writes that attribute, and
  the page sets it before its first paint. Reduced transparency and high contrast make surfaces
  opaque.
- Space, type, radius, elevation, control and region sizes, and motion durations, which are zero
  under `prefers-reduced-motion` or `data-motion="reduced"`.
- Two retuning switches: `--panel-tilt` (0deg keeps panels flat; the earlier plates used -10deg) and
  `--panel-header-fill` (transparent keeps headers plain; the earlier look used `--chromatic-head`).
- The stacking table, the only z-index source in application CSS: world 0, shell 1, vignette 5,
  heads-up 10, chrome 20, panel 30, dock 40, overlay 60, sheet 70, toast 80, boundary 95, boot 100,
  and local-0 to local-4 for layers inside one component.

**DECISION**: one accent hue, with status colours reserved for status. The alternative, a palette
per surface, is what made the same role look different in each panel.

### The brand colours

A calm light base and two signature colours, the blue (`#c6e1ff`) and the yellow (`#f4ff91`) of
the spheres on the landing page (`web/packages/landing/src/ui/gradient-forms/presets.ts`). They are
used sparingly and by rule, so that a colour on screen always means something:

| Colour | Role | Where |
| --- | --- | --- |
| Deep blue (`--color-accent`, `--color-accent-text`) | words that act, links, primary actions | primary buttons, quiet buttons and links, the focus ring, a selected tab's rule, icons in a panel header |
| Yellow (`--color-signal`, with `--color-signal-ink`) | what is selected, live or actionable | a selected rail item, panel tab or Search row, a running state such as the playing clock, the hover and press of a control |
| The blend (`--brand-blend`) | a brand moment | under the wordmark at the way in, and above "Opening your world"; nowhere else |

- The deep blue is the spheres' hue made dark enough to read as words (at least 4.5:1); the pale
  sphere blue itself is 1.3:1 on white and so is never used for words or lines on a light surface.
  In the dark scheme the sphere blue is the accent as it is.
- Yellow is a fill, never a word or a line on a light surface, and it always carries dark ink. In
  the dark scheme the signal is a dark olive fill with yellow ink.
- What never takes colour: running text, panel surfaces and borders, panel headers (plain, with
  `--panel-header-fill` transparent), the world itself, and status meanings, which keep the status
  roles. A panel header, a card or a list row never wears the blend.

`web/packages/app/test/ui-system-contrast.test.ts` holds every text role, the signal's ink and the
accent's words on the signal at AA in both schemes, and holds "Follow the system" to exactly the
dark values. The dark scheme recolours the surfaces this file's tokens dress (the top bar, the tool
rail, the inspector panels, the confirmation, Search and notices); the World menu, the major
surfaces on the overlay layer and the Companion's speech strip still take the world profile's
design.

## 3. Layout regions

`createLayout(shell)` makes the regions and is the only code that puts a surface into one. A
surface keeps its own open and close behaviour; the layout watches its `hidden` attribute.

| Region | Holds | Rule |
| --- | --- | --- |
| `top-bar` | the world's title, the world clock, Add object, Add photos, Search, World menu | always present in a world |
| `tool-rail` | the registry's rail actions, grouped | always present |
| `inspector` | the objects panel, People here, Build, About this place, Selected, the reconstruction inspector | exclusive: a newly shown surface closes the one before through its own close handler |
| `sheet` | the confirmation before a write | exclusive; drawn over the inspector column, which it dims, so the placement mark in the world stays visible |
| `dock` | the Companion | centred in the free part of the world |
| `toast` | short notices and receipts | newest first, at most three |
| `hud` | progress and notes about the world (forming, tile progress, traffic note, scene segments, the Map caption) | stacked at the top left of the world |
| `overlay` | the command palette | modal |

The World menu, Library, Character, Compare, Design, Settings, Make a world and Photos are major
surfaces that the shell state (`web/packages/app/src/world-shell.ts`) opens one at a time; they sit
on the overlay layer. While one is open every region except `toast` is inert
(`MODAL_BACKGROUND_REGIONS`), so Tab stays in the open surface; the Library is inert whenever it is
not the one open. While anything is visible in `inspector` or `sheet`, `#shell` carries
`data-inspector-open` and the dock, toasts and heads-up stack centre themselves in what is left.

Compare and the recorded-result reader load when first opened
(`web/packages/app/src/composition/lazy-panel.ts`): until then a stand-in says "Opening Compare."
and a load that fails says so with Try again.

Below 60rem the application shows its narrow-window notice; the region rules for narrow screens
(a bottom bar and a bottom sheet) exist in `layout.css` for when that notice is lifted.

## 4. Actions

Each action is declared once in `ACTIONS`: label, hint, icon, group, placements (`rail`, `top-bar`,
`palette`, a panel), keyboard shortcut, the route key of the operation it performs (the descriptor's
`operation`, as in `tests/snapshots/api-routes.json`), and words for each refusal code it can meet.
The composition root binds each one to the call its older control makes, so a rail button, a palette
row, a panel button and the Companion's starter offer are one action with one result.

Availability is the server's. An action with an operation takes its descriptor's state from
`GET /world/versions/{version_id}/capabilities`, read in the order unsupported, not permitted,
unavailable, unknown, available. Make a world needs no open world: it reads the generated town's
create from `GET /worlds/capabilities` (`exulanica.world-creation/v1`), read when a world mounts and
again with every refresh. Where the workspace refuses it (the world limit, a server that builds no
towns, a role that registers no worlds) the World menu entry says why in place of its detail and
stays reachable, choosing it shows the two sentences, and the Make a world surface never opens. Before the first read it is unknown, never assumed available. An
action with no operation (opening a panel, the map) is local and available. A world that never
supports an action leaves it out of the rail and lists it in the palette with why.

One run path: an action that is refused, or whose own precondition holds it back (pause before
advancing a minute), is not run and its words are shown. A running action's control is busy and
nothing is said to have happened. A refusal it meets is shown as the action's words; its code and
the server's detail go only into the technical details. The objects panel, the People panel and the
directed actions in the inspector take the same descriptors for their own buttons.

The interface keeps these states distinct and gives each one look and one default word: available,
unavailable, unsupported ("Not in this world"), not permitted ("Not allowed"), unknown ("Can't tell
yet"), queued ("Waiting"), running ("Working"), ready, failed, stale ("Out of date"), cancelled and
partial ("Partly done").

Every interactive control a driver needs carries a `data-action` name (`people.bring-in`,
`clock.advance`, `objects.place`, `objects.undo`, `object.remove`, `panel.people`, `confirm.accept`
and so on). The names do not change when words do; drivers select with `ACTION(id, scope)` from
`scripts/rehearsal/app.mjs`.

## 5. Voice and words

1. Plain, short, second person, present tense: "you", "this world".
2. Buttons are verbs in sentence case, two or three words, no closing full stop: "Add object",
   "Bring people in", "Take back". A shortcut is its own badge, never typed into the label.
3. One word for one thing (glossary below).
4. A failure is two sentences: what happened, then what to do next. "Nothing was added. This world
   changed while you were deciding; look at it again, then try once more."
5. A raw code, an id, a digest or a model's prompt version is never the message. Words are designed
   around `code` and `detail`, the two members the browser's transport keeps, and the code goes
   into the technical details (`ui/words/problems.ts` gives a surface the two sentences and the
   record for any refusal; a code without words gets the generic pair).
6. A status line says the state first: "Paused at minute 7".
7. The Companion speaks as "I" in its own speech; everything else is neutral or second person.
   Whether a model was used is the answer's `execution.calls`, never `deterministic`.
8. Everything an answer says is in view: every clause, the kind of silence an abstention is, and who
   answered or that no model was asked. Only supporting records sit behind a disclosure.
9. Numbers as digits, units spelled out ("1.8 metres"). No em dash.

| Thing | Say | Not |
| --- | --- | --- |
| a simulated person | person, people ("simulated" once where it matters) | inhabitant, resident, subject |
| the people of a world | people here | society, population |
| a placed thing | object | asset, instance, affordance |
| a change to a world | change | edit, authored edit, event |
| a simulated minute | minute | tick, step |
| the assistant | Companion | assistant, agent |
| a photograph | photo | capture, source |
| appearance editing | Design | Customize |
| the index | Library | Index |
| placing and arranging | Build | Create |
| making a new world | Make a world | Create |

## 6. What holds it

- `web/packages/app/test/ui-system-layout.test.ts`: the inspector and sheet keep one surface each,
  attachments are never closed, and surfaces appended to the shell are routed to their region.
- `web/packages/app/test/ui-system-geometry.test.ts`: the region boxes computed from the real tokens
  and `layout.css` stay apart at 1440x900, 1280x800 and 1024x700 with the inspector open and closed.
- `web/packages/app/test/ui-system-sources.test.ts`: no numeric z-index in application CSS or inline
  styles; every z token used is defined; the system stylesheets hold no colour literal; older
  stylesheets hold no more colour literals than their recorded ceilings; only `icon.ts` imports lucide.
- `web/packages/app/test/action-registry.test.ts` and `action-surfaces.test.ts`: every action has
  words, an icon and a placement; every operation exists in the API; refusal words carry no code;
  availability follows the descriptors; a refused action is not run; registry shortcuts are the
  shell's keys.
- The word parity tests (`society-words-parity`, `society-models-words-parity`,
  `society-comparison-words-parity`, `edit-words-parity`, `code-words-parity`) hold the catalogs to
  the server's codes.

Not covered by a test: visual quality, contrast of every pairing and the narrow-screen layout in use
(**OPEN** until the narrow-window notice is lifted).
