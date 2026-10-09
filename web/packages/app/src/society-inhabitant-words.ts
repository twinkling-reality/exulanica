/**
 * Who a simulated person is and what they are doing, in words, read from the one data file the
 * server's Companion reads too: `assets/catalogs/society-words/society-inhabitant-words.v1.json`.
 *
 * The choice of sentence for a state is code here and in `exulanica/selection/inhabitant_words.py`,
 * and both run the same cases (`tests/fixtures/society-inhabitant-words/cases.json`), so the
 * inspector and the Companion say the same thing of the same person. Talking has no content: no
 * sentence here says what anybody talked about.
 */

import catalogText from '../../../../assets/catalogs/society-words/society-inhabitant-words.v1.json?raw';
import livingNeedsText from '../../../../assets/catalogs/society/society-need.v1.json?raw';
import { ACTIVITY_KINDS } from './society-activity-words.js';
import { societyEngine } from './society-engines.js';

/** The entry kinds the catalog holds; a kind outside these is refused when the page loads. */
const KINDS = ['reason', 'phrase', 'doing', 'outcome', 'event_reason', 'line', 'decision_reason'] as const;
type Kind = (typeof KINDS)[number];

interface CatalogEntry {
  readonly key: string;
  readonly kind: string;
  readonly code: string;
  readonly words: string;
}

function readCatalog(text: string): Readonly<Record<Kind, Readonly<Record<string, string>>>> {
  const document = JSON.parse(text) as { readonly catalog_id?: unknown; readonly entries?: readonly CatalogEntry[] };
  if (document.catalog_id !== 'society-inhabitant-words' || !Array.isArray(document.entries)) {
    throw new Error('not the society inhabitant words catalog');
  }
  return readTables(document.entries);
}

/** The engines the catalog has words for, as it states them; anything else is refused on load. */
function readProfiles(text: string): ReadonlySet<string> {
  const { profiles } = JSON.parse(text) as { readonly profiles?: unknown };
  if (!Array.isArray(profiles) || profiles.length === 0 || !profiles.every((profile) => typeof profile === 'string' && profile)) {
    throw new Error('the society inhabitant words catalog names no profiles');
  }
  return new Set(profiles as readonly string[]);
}

function readTables(entries: readonly CatalogEntry[]): Readonly<Record<Kind, Readonly<Record<string, string>>>> {
  const tables = Object.fromEntries(KINDS.map((kind) => [kind, {} as Record<string, string>])) as Record<Kind, Record<string, string>>;
  for (const entry of entries) {
    const kind = KINDS.find((known) => known === entry.kind);
    if (kind === undefined) throw new Error(`entry ${entry.key} has an unknown kind ${entry.kind}`);
    if (entry.key !== `${kind}.${entry.code}` || !entry.words) throw new Error(`entry ${entry.key} is malformed`);
    if (entry.code in tables[kind]) throw new Error(`entry ${entry.key} is stated twice`);
    tables[kind][entry.code] = entry.words;
  }
  return tables;
}

const TABLES = readCatalog(catalogText);
const PROFILES = readProfiles(catalogText);
const LIVING_NEED_LABELS: Readonly<Record<string, string>> = (() => {
  const catalog = JSON.parse(livingNeedsText) as {
    readonly catalog_id?: string;
    readonly entries?: readonly { readonly key: string; readonly label: string }[];
  };
  if (catalog.catalog_id !== 'society-need' || !Array.isArray(catalog.entries)) {
    throw new Error('not the living society need catalog');
  }
  return Object.fromEntries(catalog.entries.map(({ key, label }) => [key, label]));
})();

/** A living need's own catalog label, or a neutral phrase for a code this catalog does not name. */
export function livingNeedLabel(code: string): string {
  return LIVING_NEED_LABELS[code] ?? 'another need';
}

/**
 * Whether a society's engine has words: the catalog's own `profiles`, the list the server's
 * Companion refuses by (`society_profile_has_no_words`), so the inspector never offers words or
 * questions the Companion would refuse. A stored society of a retired engine can share a state
 * family with one that has words and still have none.
 */
export function hasInhabitantWords(profile: string | null | undefined): boolean {
  return profile != null && PROFILES.has(profile);
}

/** One entry's words; a missing one is a defect of the catalog. */
function words(kind: Kind, code: string): string {
  const found = TABLES[kind][code];
  if (found === undefined) throw new Error(`the words catalog has no ${kind} ${code}`);
  return found;
}

const fill = (template: string, values: Readonly<Record<string, string | number>>): string =>
  template.replace(/\{([a-z_]+)\}/g, (whole, name: string) => (name in values ? String(values[name]) : whole));

/**
 * Why a person is doing what they do, by the engine's reason code: exactly the codes
 * `REASON_CODES` in `society_planner.py` states, held to it by society-words-parity.test.ts.
 */
export const REASON_WORDS: Readonly<Record<string, string>> = TABLES.reason;

/**
 * Why a person's model was or was not followed, by the reason code the receipt or the minute
 * records: exactly `DECISION_REASONS` in `society_decision_contract.py`, held to it by
 * society-models-words-parity.test.ts.
 */
export const DECISION_WORDS: Readonly<Record<string, string>> = TABLES.decision_reason;

/** What an outcome code a state or an event records says happened, from the words catalog. */
export function outcomeWords(code: string): string | undefined {
  return TABLES.outcome[code];
}

/** Why, for any code a state or an event records, or the named sentence for one with no words. */
export function reasonWords(code: string): string {
  return TABLES.reason[code] ?? TABLES.event_reason[code] ?? fill(words('phrase', 'reason_unknown'), { code });
}

/** A person's own words at the top of the inspector: who, what they are doing now, and why. */
export interface InhabitantWords {
  readonly who: string;
  readonly what: string;
  readonly doing: string;
  readonly why: string;
}

/** What the words read of one person's recorded state. */
export interface WordedPerson {
  readonly display_name?: string | null;
  readonly role?: string | null;
  readonly goal?: unknown;
  readonly action?: {
    readonly kind: string;
    readonly status: string;
    readonly target_id?: string | null;
    readonly remaining_ticks?: number | null;
    readonly reason: string;
  } | null;
  /** How they came to be here (a society of things): `crossed` for one who came in from outside. */
  readonly came_by?: string | null;
  /** For one who came in from outside, their arrival's record: the bridge, and `decided_by: world` where this world decides. */
  readonly crossing?: { readonly bridge: string; readonly decided_by?: string | null } | null;
}

/** The label the door lists for a bridge, or null where it lists none. */
export type BridgeLabel = (bridge: string) => string | null;

interface WordedGoal {
  readonly kind: string;
  readonly reason: string;
  readonly partner_id?: string | null;
}

/**
 * Who a simulated person is and what they are doing. `place` writes a target the person uses, or
 * gives null for one the world no longer holds; `partner` writes another person, or null for one
 * not in the society. Talking has no content, so nothing here says what about.
 */
export function inhabitantWordsFrom(
  person: WordedPerson,
  place: (targetId: string) => string | null,
  partner: (inhabitantId: string) => string | null,
  profile: string | null = null,
  placeWords: PlaceWords | null = null,
  /**
   * Set where a program from outside the world decides for this person: their choices are recorded
   * as any decider's are (`chosen_by_their_model`), but no model was asked, so the words say their
   * own program chose. The server's Companion does not pass it.
   */
  decidedFromOutside = false,
  /**
   * Writes the label the door lists for a bridge. A person who came in from outside is never called
   * invented for this world: their arrival's record says where they came from (this label, or
   * "outside this world" where there is none) and who decides for them here.
   */
  bridgeLabel: BridgeLabel | null = null,
): InhabitantWords {
  const living = person as unknown as {
    readonly ordinal?: number;
    readonly role?: { readonly label?: string } | null;
    readonly home?: unknown;
    readonly work?: unknown;
    readonly action?: { readonly kind: string; readonly reason: string } | null;
    readonly goal?: { readonly activity: string; readonly reason?: string } | null;
  };
  if (profile !== null && societyEngine(profile).stateFamily === 'living') {
    if (typeof living.ordinal !== 'number' || !Number.isSafeInteger(living.ordinal)) {
      throw new Error('a living resident has no ordinal');
    }
    return livingInhabitantWords({
      role: living.role?.label ?? null,
      has_home: living.home != null,
      has_work: living.work != null,
      action: living.action ?? null,
      goal: living.goal ?? null,
    }, living.ordinal, placeWords);
  }
  const who = person.display_name ?? words('phrase', 'who_unnamed');
  const role = person.role ?? words('phrase', 'role_unknown');
  const crossing = person.came_by === 'crossed' ? person.crossing ?? null : null;
  const what = crossing === null
    ? fill(words('phrase', 'what'), { role })
    : fill(words('phrase', crossing.decided_by === 'world' ? 'what_crossed_world' : 'what_crossed_program'), {
      role, from: bridgeLabel?.(crossing.bridge) ?? words('phrase', 'from_outside'),
    });
  const action = person.action ?? undefined;
  const goal = person.goal !== null && typeof person.goal === 'object' && 'kind' in person.goal ? (person.goal as WordedGoal) : null;
  if (action === undefined) return { who, what, doing: words('doing', 'nothing_recorded'), why: '' };
  const where = (targetId: string | null | undefined): string =>
    targetId ? place(targetId) ?? words('phrase', 'place_gone') : words('phrase', 'place_none');
  const remaining = action.remaining_ticks ?? 0;
  const still = !remaining ? '' : remaining === 1 ? words('phrase', 'still_one') : fill(words('phrase', 'still_many'), { count: remaining });
  const met = (goal?.partner_id ? partner(goal.partner_id) : null) ?? words('phrase', 'partner_unknown');
  const completed = action.status === 'completed';
  let chosen: string;
  // What each kind of activity is called at each stage is its catalog's (society-affordance), as
  // the server's words read it; making room, waiting and deciding are the planner's own.
  const heading = goal?.kind === undefined ? undefined : ACTIVITY_KINDS.get(goal.kind);
  const under = ACTIVITY_KINDS.get(action.kind);
  if (action.status === 'blocked') chosen = 'waiting';
  else if (action.kind === 'move') {
    chosen = heading !== undefined && heading.setting !== 'object'
      ? heading.headingDoing
      : goal?.kind === 'make_room' || action.target_id == null
        ? 'walking_to_free_spot'
        // A goal no kind of activity states: nothing is said of it rather than a guess.
        : heading?.headingDoing ?? 'nothing_recorded';
  } else if (under !== undefined) {
    // Only a pair activity waits for the other person, by the planner's own code.
    chosen = completed
      ? under.finishedDoing
      : action.reason === 'waiting_for_partner' ? 'waiting_to_talk' : under.underWayDoing;
  } else chosen = completed ? 'standing_aside' : 'deciding';
  const doing = fill(words('doing', chosen), { place: where(action.target_id), partner: met, still });
  // The goal says why a person set out. Once they are blocked, the action says why; so it does for
  // standing and talking when it records news since they set out (the other person is still on the
  // way, has gone, or the time is up), but not the reason that only restates the activity under
  // way, which would hide why they set out (a model's choice, say).
  const acting = action.status === 'blocked'
    || (under !== undefined && under.setting !== 'object' && action.reason !== under.underWayReason);
  const code = !acting && goal !== null ? goal.reason : action.reason;
  const reason = decidedFromOutside && code === 'chosen_by_their_model' ? words('phrase', 'chosen_by_their_program') : reasonWords(code);
  return { who, what, doing, why: fill(words('phrase', 'because'), { reason }) };
}

/** The living inspector reads the same activity and reason phrases as the Companion. */
export function livingInhabitantWords(
  person: {
    readonly role?: string | null;
    readonly has_home?: boolean;
    readonly has_work?: boolean;
    readonly action?: { readonly kind: string; readonly reason: string } | null;
    readonly goal?: { readonly activity: string; readonly reason?: string } | null;
  },
  ordinal: number,
  placeWords: PlaceWords | null = null,
): InhabitantWords {
  // A ground's own words (keyed `code@ground`) stand in for a town's, with the kind's words for
  // where its people are and walk put in as they are, in one pass.
  const grounded = (kind: Kind, code: string, values: Readonly<Record<string, string>> = {}): string => {
    const own = placeWords === null ? undefined : TABLES[kind][`${code}@${placeWords.ground}`];
    if (own !== undefined) return fill(own, { here: placeWords!.here, around: placeWords!.around, ...values });
    return fill(words(kind, code), values);
  };
  const kind = person.action?.kind ?? 'idle';
  const activity = person.goal?.activity;
  const heading = `living_heading_${activity}` in TABLES.doing ? `living_heading_${activity}` : 'living_heading_unknown';
  const doing = kind === 'move'
    ? grounded('doing', heading)
    : TABLES.doing[`living_${kind}`] ?? words('doing', 'living_unknown');
  const reason = person.goal?.reason ?? person.action?.reason;
  const home = person.has_home === true;
  const work = person.has_work === true;
  const whatKey = home && work ? 'living_what_home_work'
    : home ? 'living_what_home' : work ? 'living_what_work' : 'living_what_neither';
  const key = reason === 'shift_due' ? 'living_why_shift'
    : reason === 'most_pressing_need' ? 'living_why_need'
    : reason === 'waiting_a_minute' ? 'living_why_wait'
    : reason === 'starting_at_home' ? 'living_why_home'
    : 'living_why_other';
  return {
    who: fill(words('phrase', 'living_who'), { number: ordinal + 1 }),
    what: grounded('phrase', whatKey, { role: person.role ?? 'resident' }),
    doing,
    why: words('phrase', key),
  };
}

/**
 * Where a living person is, in their world's ground's own words: the society ground entry the
 * catalog keys those words by, and what is said of where its people are and walk, as the server
 * serves them for a world made from a world kind.
 */
export interface PlaceWords {
  readonly ground: string;
  readonly here: string;
  readonly around: string;
}

/** One phrase of the catalog, with its `{name}` slots filled. */
export function phrase(code: string, values: Readonly<Record<string, string | number>> = {}): string {
  return fill(words('phrase', code), values);
}

/** A phrase the catalog may or may not state (a per-use-class wording), or null where it states none. */
export function optionalPhrase(code: string, values: Readonly<Record<string, string | number>> = {}): string | null {
  const found = TABLES.phrase[code];
  return found === undefined ? null : fill(found, values);
}
