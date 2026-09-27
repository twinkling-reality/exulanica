/**
 * What the page says of each kind of activity a society's people do, read from the catalogs the
 * server reads, never restated here.
 *
 * `assets/catalogs/society/society-affordance.v*.json` states each kind of activity a purposeful
 * routine offers (rest, visit, stand, talk) and where it happens; `society-words/
 * society-activity-words.v1.json` states the word keys of each stage and, for an activity at an
 * object, the words for directing somebody to it. `society-activity.v1.json` and
 * `society-purposeful-activity.v*.json` state each activity's label. The server's planner, its
 * Companion words and its action route read the same files, so an activity added there is one the
 * page can name without a change here.
 */

import livingText from '../../../../assets/catalogs/society/society-activity.v1.json?raw';
import wordsText from '../../../../assets/catalogs/society-words/society-activity-words.v1.json?raw';

const AFFORDANCES: Readonly<Record<string, string>> = import.meta.glob<string>(
  '../../../../assets/catalogs/society/society-affordance.v*.json',
  { query: '?raw', import: 'default', eager: true },
);
const PURPOSEFUL: Readonly<Record<string, string>> = import.meta.glob<string>(
  '../../../../assets/catalogs/society/society-purposeful-activity.v*.json',
  { query: '?raw', import: 'default', eager: true },
);

/** The catalogs' word for nothing of that kind: an activity at no object has no words to direct. */
const NONE = 'none';

/** What is said of one kind of activity. The words for directing somebody are null off an object. */
export interface ActivityKindWords {
  readonly key: string;
  readonly setting: string;
  readonly headingDoing: string;
  readonly underWayDoing: string;
  readonly finishedDoing: string;
  /** "Inhabitants can {verb} here." */
  readonly verb: string | null;
  /** "Asked to {verbAtPlace}.", with `{place}` filled. */
  readonly verbAtPlace: string | null;
  /** A directed-action button's words, with `{place}` filled. */
  readonly directLabel: string | null;
  /** A directed-action button's words when no place is named. */
  readonly directDefault: string | null;
  /** A place marker's words, with `{node}` filled. */
  readonly markerLabel: string | null;
}

interface CatalogEntry {
  readonly key: string;
  readonly label?: string;
  readonly setting?: string;
  readonly affordance?: string;
  readonly [field: string]: unknown;
}

function entriesOf(text: string, catalogId: string): readonly CatalogEntry[] {
  const document = JSON.parse(text) as { readonly catalog_id?: unknown; readonly entries?: unknown };
  if (document.catalog_id !== catalogId || !Array.isArray(document.entries)) {
    throw new Error(`not the ${catalogId} catalog`);
  }
  return document.entries as readonly CatalogEntry[];
}

const text = (entry: CatalogEntry, field: string): string => {
  const value = entry[field];
  if (typeof value !== 'string' || value.length === 0) throw new Error(`${entry.key} states no ${field}`);
  return value;
};
const optional = (entry: CatalogEntry, field: string): string | null => {
  const value = text(entry, field);
  return value === NONE ? null : value;
};

function kindsOf(): ReadonlyMap<string, ActivityKindWords> {
  // Where each kind happens, from every published version of the codes catalog.
  const settings = new Map<string, string>();
  const files = Object.values(AFFORDANCES);
  if (files.length === 0) throw new Error('no society-affordance catalog is published');
  for (const file of files) {
    for (const entry of entriesOf(file, 'society-affordance')) {
      const setting = text(entry, 'setting');
      if ((settings.get(entry.key) ?? setting) !== setting) {
        throw new Error(`two society-affordance versions set ${entry.key} differently`);
      }
      settings.set(entry.key, setting);
    }
  }
  const kinds = new Map<string, ActivityKindWords>();
  for (const entry of entriesOf(wordsText, 'society-activity-words')) {
    const setting = settings.get(entry.key);
    if (setting === undefined) throw new Error(`words for ${entry.key}, which no activity catalog states`);
    kinds.set(entry.key, {
      key: entry.key,
      setting,
      headingDoing: text(entry, 'heading_doing'),
      underWayDoing: text(entry, 'under_way_doing'),
      finishedDoing: text(entry, 'finished_doing'),
      verb: optional(entry, 'verb'),
      verbAtPlace: optional(entry, 'verb_at_place'),
      directLabel: optional(entry, 'direct_label'),
      directDefault: optional(entry, 'direct_default'),
      markerLabel: optional(entry, 'marker_label'),
    });
  }
  const missing = [...settings.keys()].filter((key) => !kinds.has(key));
  if (missing.length > 0) throw new Error(`no words for the activities ${missing.join(', ')}`);
  return kinds;
}

function labelsOf(): ReadonlyMap<string, string> {
  const labels = new Map<string, string>();
  const add = (key: string, label: string): void => {
    const held = labels.get(key);
    if (held !== undefined && held !== label) throw new Error(`two catalogs label ${key} differently`);
    labels.set(key, label);
  };
  for (const entry of entriesOf(livingText, 'society-activity')) add(entry.key, text(entry, 'label'));
  for (const file of Object.values(PURPOSEFUL)) {
    for (const entry of entriesOf(file, 'society-purposeful-activity')) {
      // An activity at an object is named by its affordance's own entry, the one for any kind.
      if (entry['object_kind'] === 'any' || entry.setting !== 'object') {
        add(entry.setting === 'object' ? text(entry, 'affordance') : entry.key, text(entry, 'label'));
      }
    }
  }
  return labels;
}

/** Each kind of activity a purposeful routine offers, by its key (an object's by its affordance). */
export const ACTIVITY_KINDS: ReadonlyMap<string, ActivityKindWords> = kindsOf();

/** Each catalogued activity's label, by its key: the living society's and the purposeful ones. */
export const ACTIVITY_LABELS: ReadonlyMap<string, string> = labelsOf();

/** Whether `value` is an activity people do at an object, which somebody can be directed to. */
export function isObjectActivity(value: unknown): value is string {
  return typeof value === 'string' && ACTIVITY_KINDS.get(value)?.setting === 'object';
}

/** The words of an activity at an object, or a refusal naming one no catalog states. */
export function objectActivity(key: string): ActivityKindWords & {
  readonly verb: string;
  readonly verbAtPlace: string;
  readonly directLabel: string;
  readonly directDefault: string;
  readonly markerLabel: string;
} {
  const kind = ACTIVITY_KINDS.get(key);
  if (kind === undefined || kind.setting !== 'object' || kind.verb === null || kind.verbAtPlace === null
    || kind.directLabel === null || kind.directDefault === null || kind.markerLabel === null) {
    throw new Error(`no catalog states an activity at an object named ${key}`);
  }
  return kind as ReturnType<typeof objectActivity>;
}

/** A catalog's words with its placeholders filled. */
export function filled(words: string, values: Readonly<Record<string, string>>): string {
  return words.replace(/\{([a-z_]+)\}/g, (whole, name: string) => values[name] ?? whole);
}

/**
 * The page's labels for what a person is doing that is no catalogued activity: waiting, and
 * walking between activities. Held to the action kinds the page reads
 * (`ACTION_KINDS` in society-api.ts) by society-activity-words.test.ts.
 */
export const ACTION_LABELS: Readonly<Record<string, string>> = { idle: 'waiting', move: 'walking' };
