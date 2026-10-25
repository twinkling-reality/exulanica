// The Integrations page's words and rules (DESIGN's build sheet of 24 October, BUILD-SHEETS-1024.md's last section;
// WORDS.md "The Integrations page"): the page's own words here, each row's in integrations.v1.json, and each row's
// state read from what the server serves, as data in and data out. integrations.ts draws them, and
// verify-integration-words.mjs holds them to the sheet.
import catalog from './integrations.v1.json' with { type: 'json' };

/** The catalog of what a person's worlds connect to (integrations.v1.json). */
export const INTEGRATIONS = catalog;

export const INTEGRATION_WORDS = Object.freeze({
  button: 'Integrations',
  overLabel: 'Integrations',
  title: 'What your worlds connect to',
  sub: 'Each one says what it connects, what it reads and where anything goes. Nothing connects until you set it up, and you can end it.',
  small: "A person's model is chosen on their card. This page is where the models and the outside programs come from.",
  connects: 'Connects',
  reads: 'Reads',
  goesTo: 'Goes to',
  choose: 'Choose',
  /** Enter leaves the page for the row's guide, so its key says so with G2's mark for a page that opens elsewhere. */
  setUp: 'How to set it up ↗',
  back: 'Back',
  end: 'End this grant',
});

/** The shapes a row's mark may draw, and the attributes each may carry: a plain line drawing, never a picture. */
const MARK_SHAPES = Object.freeze({
  rect: ['x', 'y', 'width', 'height', 'rx'],
  circle: ['cx', 'cy', 'r'],
  path: ['d'],
});

/** `template` with each `{name}` in it replaced by `values[name]`. */
export const fill = (template, values) => template.replace(/\{(\w+)\}/gu, (_, name) => String(values[name]));

/**
 * Names as a row's one-line state says them: "Uma Sorrel", "Uma Sorrel and Esme Oak", and from three on two names
 * with the rest counted, "Uma Sorrel, Esme Oak and 1 more", so a list never squeezes the row's own words.
 */
export function joinNames(names) {
  if (names.length < 3) return names.join(' and ');
  return `${names.slice(0, 2).join(', ')} and ${names.length - 2} more`;
}

/** Every row of the catalog, in its order, each with its group's key. */
export const catalogRows = (catalog) => catalog.groups.flatMap(group => group.rows.map(row => Object.freeze({ ...row, group: group.key })));

/** The anchor a heading of a document has where the guides are read: its words in lower case, joined by hyphens. */
export const headingAnchor = (heading) => heading.trim().toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, '').replace(/\s/gu, '-');

/** Where Enter opens a row's guide: the catalog's guides address, the document, and the heading in it. */
export const guideAddress = (catalog, guide) => `${catalog.guides}${guide.document}#${headingAnchor(guide.heading)}`;

/** A row's mark as shapes to draw, each `{ tag, attributes }`; a shape or attribute it may not draw is refused by name. */
export function markShapes(mark) {
  return mark.map((shape) => {
    const [tag, ...more] = Object.keys(shape);
    if (more.length || !Object.hasOwn(MARK_SHAPES, tag)) throw new TypeError(`A mark draws ${Object.keys(MARK_SHAPES).join(', ')}, one to a shape`);
    const attributes = Object.entries(shape[tag]).map(([name, value]) => {
      if (!MARK_SHAPES[tag].includes(name)) throw new TypeError(`A mark's ${tag} has no ${name}`);
      return [name, String(value)];
    });
    return Object.freeze({ tag, attributes: Object.freeze(attributes) });
  });
}

/**
 * Where models run: a provider's row from the models read (GET /models), each model with its provider's refusal here.
 * On where one of its models is not refused (with the first such model's name), off where each is refused for the
 * row's own reason (no key; no runner answering), and null, the row left out, where this install does not ask it at
 * all (not admitted here, or no model of it listed).
 */
function providerState(row, models) {
  const own = models.filter(model => model.provider === row.from.provider);
  const asked = own.find(model => !model.runtime?.provider_refusal);
  if (asked) return Object.freeze({ words: fill(row.states.on, { model: asked.name }), on: true });
  if (own.length && own.every(model => model.runtime?.provider_refusal === row.from.off_when)) return Object.freeze({ words: row.states.off, on: false });
  return null;
}

/**
 * Outside programs: a row counting the bridges this install admits of its kind (GET /door/bridges), or the grants of
 * its kind that stand now, `standing` (standingGrants): one says whom it decides for, nobody yet included, and
 * several are counted.
 */
function doorState(row, { bridges, standing }) {
  const ai = row.from.ai;
  if (row.from.door === 'bridges') {
    const n = bridges.filter(bridge => bridge.ai === ai).length;
    return Object.freeze(n ? { words: fill(row.states.some, { n }), on: true } : { words: row.states.none, on: false });
  }
  const grants = standing.filter(grant => grant.ai === ai);
  if (!grants.length) return Object.freeze({ words: row.states.none, on: false });
  if (grants.length > 1) return Object.freeze({ words: fill(row.states.some, { n: grants.length }), on: true });
  const names = grants[0].names;
  return Object.freeze({ words: names.length ? fill(row.states.deciding, { names: joinNames(names) }) : row.states.nobody, on: true });
}

/** The faint line under a focused row's three lines, where several of its grants stand and none is one to end. */
export const severalLine = (row, standing) => (row.several && standing.filter(grant => grant.ai === row.from.ai).length > 1 ? row.several : null);

/**
 * A row's state as the page says it, `{ words, on }` (on: the dot), from `reads` (`models`, `bridges` and the
 * `standing` grants); null where this install cannot give it, and the row is left out.
 */
export const rowState = (row, reads) => (row.from.provider ? providerState(row, reads.models) : doorState(row, reads));

/**
 * The grants of a world's grants read (GET /door/grants, as door-grants-api.ts parses it) that stand now, each as the
 * page keeps it: its id, world, version, whether its program is an AI's, and whom it decides for by id (`things`);
 * names are added from the society (namesFor).
 */
export function standingGrants(grants) {
  return (grants ?? []).filter(grant => grant.ended === null).map(grant => Object.freeze({
    grantId: grant.grantId, worldId: grant.worldId, versionId: grant.versionId, ai: grant.ai, things: grant.things,
  }));
}

/**
 * Whom a standing grant decides for, by name, in the society its version holds (GET /world/versions/{v}/society):
 * the people it names, in the grant's order, then the bodies that came in through the gate under it whose own program
 * decides for them, each by the name its record gives it (`display_name`; an agent's body is "Visitor", AG1d 9), as
 * the agent library names people.
 */
export function namesFor(society, grant) {
  const people = society?.state?.inhabitants ?? [];
  const crossed = people.filter(person => person.came_by === 'crossed' && person.crossing?.grant_id === grant.grantId && person.crossing?.decided_by !== 'world');
  return namesOf(society, [...grant.things, ...crossed.map(person => String(person.id))]);
}

/** The names the society gives the people `ids` names, in that order, leaving out anyone it does not hold or name. */
export function namesOf(society, ids) {
  const people = new Map((society?.state?.inhabitants ?? []).map(person => [String(person.id), person.display_name]));
  return Object.freeze(ids.map(id => people.get(id)).filter(name => typeof name === 'string' && name !== ''));
}

/**
 * Of `subjects`, those whose newest choice in the version's model history (GET .../society/models/history, newest
 * first) hands them to their routine: after a grant ends, the record that their own routine decides again.
 */
export function releasedSubjects(history, subjects) {
  const choices = history?.choices ?? [];
  return subjects.filter(subject => choices.find(choice => choice.subjects?.includes(subject))?.decider?.kind === 'routine');
}

/** What a row's state says once Del ended its grant (DESIGN's pass of 11:50, fold-in c). */
export const endedState = (row) => row.ends.ended;

/**
 * The faint line under a focused row whose grant Del ended: whose own routine the record shows deciding again, one
 * person by name, several with two names then the rest counted; null where the record shows nobody handed back.
 */
export function handedBackLine(row, names) {
  if (!names.length) return null;
  return names.length === 1 ? fill(row.ends.one, { name: names[0] }) : fill(row.ends.several, { names: joinNames(names) });
}

/** The faint line under a focused row whose end the server refused or did not answer: the grant still stands (fold-in b). */
export const refusedLine = (row) => row.ends.refused;

/** Whether a refused end's code says the grant had already ended or run out, so the row says it ended. */
export const alreadyEnded = (code) => code === 'grant_ended';

/** The grant Del ends on a row: its one standing grant, on a row that ends grants; null with none or several. */
export function endable(row, standing) {
  if (!row.ends) return null;
  const grants = standing.filter(grant => grant.ai === row.from.ai);
  return grants.length === 1 ? grants[0] : null;
}

/** The row ↑ or ↓ chooses from `index` among `count`, held at the first and the last. */
export const stepRow = (index, count, key) => Math.max(0, Math.min(count - 1, index + (key === 'ArrowUp' ? -1 : key === 'ArrowDown' ? 1 : 0)));
