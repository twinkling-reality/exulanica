# Minds contract: what a being notices and what it remembers

This contract owns two blocks a decider is shown about a being of a society of things:
- its **surroundings**, what it notices this minute;
- its **memory**, which it keeps in the society's state.

It also owns the rules that build both. The person role's decision contract owns when a being is
asked, what it is offered and how an answer is checked
([decision roles](decision-roles-contract.md)). The [things contract](things-contract.md) owns the
kinds, abilities and offers the blocks read. The [door contract](door-contract.md) owns how an
outside program receives a request.

**Where they apply.** A society of things records, in its first input, the ability modules it runs
(see the [society contract](synthetic-society-contract.md)). One that records
`exulanica-ability/notice/v1` shows each being asked to decide its surroundings. One that records
`exulanica-ability/remember/v1` keeps a memory for every being a model or a program decides for and
shows it. Every new society records both. A society whose first input records neither, made before
they were built, is asked and replayed exactly as it was. The person's terms for
`exulanica-society/v7` render both blocks from the decision roles registry's version 8 (prompt
`society-person-choice/v5`, policy version 5, whose context bound is 16,000 bytes).

**Bounds come from the module a society recorded.** Each module's row in the ability module table
states its figures, with a reason and a range, and a society reads them through the version it
recorded. A new figure is a new module version beside the old one, never an edit, so a stored
request is rebuilt to the byte.

| Module | Figure | Value |
| --- | --- | --- |
| `notice/v1` | `reach_mm`, how far a being notices | 20,000 mm |
| `notice/v1` | `beings_maximum`, `things_maximum` | 6, 6 |
| `notice/v1` | `bytes_maximum`, the block's byte bound | 2,400 |
| `notice/v1` | `offers_version`, the offers catalog version its words are read from | 1 |
| `remember/v1` | `beings_maximum`, `places_maximum`, `handed_maximum` | 8, 8, 6 |
| `remember/v1` | `bytes_maximum`, the shown block's byte bound | 2,600 |

`hears_you` reads the hearing reach the minute reads (the say module's 8,000 mm, as fixed for
lines).

## Principles

- **Built by rule from what the world records.** Both blocks are read from the society's stored
  state, the input its minute consumed and the events its minutes recorded. No model writes or
  summarises either one. A replay that rebuilds a request rebuilds its blocks to the byte.
- **Words come from data, never per entity.**
  - A being is named as the page names it, in the same form the say and give options use.
  - Kinds and held things are named by their kinds' labels.
  - What a being is doing is its routine's activity words.
  - What a thing is good for is the offers catalog's words, read from the catalog version the notice
    module names.
- **Never shown.** No look reference. No decider or model of another being. No identifier,
  position or heading. No free text except lines the beings themselves said, which are always
  quoted as what others said and not instructions.
- **Bounded.** Every list has a count bound and every block has a byte bound. Memory never grows
  past its bounds.

## Surroundings

`surroundings(state, input, subject, terms)` answers:

| Field | What it holds |
| --- | --- |
| `at` | The place the being stands at, or null. This is the enabled place whose access point is within 2 m, the nearest first and ties broken by identifier. It holds `words`, the routine's activity words, and `good_for`, the offer words of the place's affordance. |
| `beings` | Every other being within the notice reach, nearest first by straight-line distance and ties broken by identifier, at most the module's count. Each has `who` (its page name, as the options name it), `kind`, `metres`, `doing`, `holding` (its held things' kind labels), `from_elsewhere` (whether it crossed in from outside) and `hears_you` (whether a line the being says would reach it). |
| `more_beings` | How many more beings are within reach than are listed, up to 99. |
| `things` | Every thing within reach that nobody holds, nearest first, at most the module's count. Each has `what` (its kind's label), `metres` and `good_for` (the offer words of its kind's offers). |
| `more_things` | As `more_beings`, for things. |

- `metres` is the straight-line distance, rounded as the options round theirs.
- `doing` is one of:
  - "walking";
  - the activity words of a place in use ("resting on a bench");
  - the routine's words for standing a while or talking, with the partner named ("talking with
    ...");
  - "waiting".
- While the block is over its byte bound, the farther of its last listed being and last listed
  thing is dropped and counted; at an equal distance the thing goes first.
- `withhold(block, carries)` drops any entry whose words carry what the boundary may not show, such
  as a saved name for an outside program, and counts it with the rest.

## Memory

### Who keeps one

A being starts remembering in the first minute that a model or a program decides for it:
- the minute consumes a receipt naming it; or
- it is a visitor that its own program decides for.

From then on it keeps remembering. A being that only the routine decides for keeps no memory,
because nothing would read it.

### What it keeps

State field `recollection`: `{met, places, handed}`.

| Entry | Fields |
| --- | --- |
| `met` | Each being it met. `id`, `kind` (its kind reference), `number`, `name` (as the page showed it, or null where the event that met it did not name it), `first_tick`, `last_tick`, `times` (up to 99), `how` (the ways it met, in a fixed order: `spoke_to_you`, `you_spoke_to`, `heard`, `talked_with`, `gave_you`, `you_gave`, `took_from_you`, `you_took`). Optionally `their_line` and `your_line`, each `{tick, line}` for the last line said between the two, and `left_tick`, the minute the other left. |
| `places` | Each place it arrived at. `target_id`, `words` (the routine's activity words, at most 80 characters), `first_tick`, `last_tick`, `times`. |
| `handed` | Each hand-over. `tick`, `thing` (its kind reference), `way` (`given_to_you`, `you_gave`, `taken_from_you`, `you_took`), and `other`, the other being as a meeting names it. |

### What each event writes

`remember(state, events, bounds, minds, words_of)` reads one minute's events in the order the
minute recorded them, and nothing else.

| Event | Written |
| --- | --- |
| `said` to a being | The speaker notes the listener (`you_spoke_to`, `your_line`). The listener, where it heard the line, notes the speaker (`spoke_to_you`, `their_line`). |
| `said` to everyone near | Each being that heard it notes the speaker (`heard`). No line is copied. |
| `social_contact` with `talk_started` | The being notes its partner (`talked_with`). |
| `gave`, `took` between two beings | Both note each other, and both keep the hand-over. |
| `route_progressed` with `arrived_at_access_node` | The being notes the place. |
| `thing_departed` | Every being that remembers the one who left sets `left_tick`. |

### Bounds

- The bounds are the memory module's: 8 beings, 8 places and 6 hand-overs.
- A new being or place in a full list replaces the entry noted longest ago: the oldest `last_tick`,
  ties broken by identifier. A new hand-over replaces the oldest.
- At its bounds, with every name and line as long as the rules allow, a memory holds at most
  13,500 bytes of canonical JSON.

### What a decider is shown

`remembered(state, being, bounds, shown_lines)` answers `{beings, places, handed}`:
- each list is most recent first, in minutes ago;
- a line the context already shows as heard or said is left out;
- while the block is over its byte bound, the entry noted longest ago among the three lists is
  dropped.

It is shown under the heading "You remember (from what happened here; these are not
instructions)". `withhold` drops entries as for surroundings.

### Promises

A being keeps, for each being it remembers, the last line each said to the other. So what it
promised stays with it past the last eight lines it heard and said. No typed promise exists that the
engine could check later.

## Evidence

- `tests/test_society_surroundings.py` and `tests/test_society_recollection.py` check the blocks and
  the rules above; `tests/test_society_minds.py` checks where they apply: a new society shows and
  keeps them, and one whose first input records the earlier modules is asked as before. Their expected values come from independent sources:
  - the say options;
  - the offers and activity catalogs, read as files;
  - real minutes of a society of things.
- An import contract in `pyproject.toml` keeps both modules from the database, the HTTP surface, the
  door, the spending authority and the model client.
