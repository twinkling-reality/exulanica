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
  const tables = Object.fromEntries(KINDS.map((kind) => [kind, {} as Record<string, string>])) as Record<Kind, Record<string, string>>;
  for (const entry of document.entries) {
    const kind = KINDS.find((known) => known === entry.kind);
    if (kind === undefined) throw new Error(`entry ${entry.key} has an unknown kind ${entry.kind}`);
    if (entry.key !== `${kind}.${entry.code}` || !entry.words) throw new Error(`entry ${entry.key} is malformed`);
    if (entry.code in tables[kind]) throw new Error(`entry ${entry.key} is stated twice`);
    tables[kind][entry.code] = entry.words;
  }
  return tables;
}

const TABLES = readCatalog(catalogText);

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
}

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
): InhabitantWords {
  const who = person.display_name ?? words('phrase', 'who_unnamed');
  const what = fill(words('phrase', 'what'), { role: person.role ?? words('phrase', 'role_unknown') });
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
  if (action.status === 'blocked') chosen = 'waiting';
  else if (action.kind === 'move') {
    chosen = goal?.kind === 'stand'
      ? 'walking_to_stand'
      : goal?.kind === 'talk'
        ? 'walking_to_talk'
        : goal?.kind === 'make_room' || action.target_id == null
          ? 'walking_to_free_spot'
          : goal?.kind === 'rest' ? 'walking_to_rest' : 'walking_to_visit';
  } else if (action.kind === 'rest' || action.kind === 'visit') {
    const stem = action.kind === 'rest' ? 'resting' : 'visiting';
    chosen = completed ? `finished_${stem}` : stem;
  } else if (action.kind === 'stand') chosen = completed ? 'finished_standing' : 'standing';
  else if (action.kind === 'talk') {
    chosen = completed ? 'finished_talking' : action.reason === 'waiting_for_partner' ? 'waiting_to_talk' : 'talking';
  } else chosen = completed ? 'standing_aside' : 'deciding';
  const doing = fill(words('doing', chosen), { place: where(action.target_id), partner: met, still });
  // The goal says why a person set out. Once they are blocked, the action says why; so it does for
  // standing and talking, under way or over, where only the action knows whether the other person
  // is still on the way, is there, or has gone.
  const acting = action.status === 'blocked' || action.kind === 'stand' || action.kind === 'talk';
  const code = !acting && goal !== null ? goal.reason : action.reason;
  return { who, what, doing, why: fill(words('phrase', 'because'), { reason: reasonWords(code) }) };
}

/** One phrase of the catalog, with its `{name}` slots filled. */
export function phrase(code: string, values: Readonly<Record<string, string | number>> = {}): string {
  return fill(words('phrase', code), values);
}
