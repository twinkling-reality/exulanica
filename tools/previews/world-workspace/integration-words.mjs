// The Integrations page's words and rows (ROOT's mock, integrations-owner.html and -guest.html, and the user's yes of
// 27 October): one row per service this server reads, its name, its one plain line and its mark from the served
// catalog (GET /integrations, exulanica/models/integrations.v1.json), its state and its one action from the live reads.
// Nothing about a service is written here: only the page's own words for a state and an action. integrations.ts draws
// the rows, and verify-integration-words.mjs holds them.

export const INTEGRATION_WORDS = Object.freeze({
  button: 'Integrations',
  title: 'Integrations',
  keySet: 'Key set',
  hostKey: 'Host’s key',
  noKey: 'No key',
  budgetSpent: 'Budget spent',
  running: 'Running',
  notRunning: 'Not running',
  notHere: 'Not on this server',
  off: 'Off',
  notConnected: 'Not connected',
  deciding: 'Deciding',
  playing: 'Playing',
  ended: 'Ended',
  noneGranted: 'None granted',
  models: 'Models',
  guide: 'Guide',
  connect: 'Connect',
  end: 'End',
  endRefused: 'It could not be ended. Try again.',
  connectRefused: 'It could not be asked. Try again.',
  /** After Connect: the chosen world's follower is asked to keep it in a project, which it takes on its next look. */
  asked: world => `Asked to keep ${world}`,
});

/** The shapes a mark may draw, and the attributes each may carry: a plain line drawing, never a picture. */
const MARK_SHAPES = Object.freeze({
  rect: ['x', 'y', 'width', 'height', 'rx'],
  circle: ['cx', 'cy', 'r'],
  path: ['d'],
});

/** The models read's refusals that say the host's money for models is spent. */
const BUDGET_SPENT = Object.freeze(['process_budget_spent', 'process_share_spent']);

/** A dollar figure as the page says it: "$3.20", under a cent "$0.0042". */
export function dollars(usd) {
  const value = Number(usd);
  if (!Number.isFinite(value) || value < 0) return null;
  return value >= 0.01 || value === 0 ? `$${value.toFixed(2)}` : `$${value.toFixed(4)}`;
}

/**
 * Names as a row's line says them: "Ada", "Ada and Theo", and from three on two names with the rest counted, "Ada, Theo
 * and 1 more".
 */
export function joinNames(names) {
  if (names.length < 3) return names.join(' and ');
  return `${names.slice(0, 2).join(', ')} and ${names.length - 2} more`;
}

/** A mark as shapes to draw, each `{ tag, attributes }`; a shape or attribute it may not draw is refused by name. */
export function markShapes(mark) {
  return (mark ?? []).map((shape) => {
    const [tag, ...more] = Object.keys(shape);
    if (more.length || !Object.hasOwn(MARK_SHAPES, tag)) throw new TypeError(`A mark draws ${Object.keys(MARK_SHAPES).join(', ')}, one to a shape`);
    const attributes = Object.entries(shape[tag]).map(([name, value]) => {
      if (!MARK_SHAPES[tag].includes(name)) throw new TypeError(`A mark's ${tag} has no ${name}`);
      return [name, String(value)];
    });
    return Object.freeze({ tag, attributes: Object.freeze(attributes) });
  });
}

/** The anchor a heading of a document has where the guides are read: its words in lower case, joined by hyphens. */
export const headingAnchor = (heading) => heading.trim().toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, '').replace(/\s/gu, '-');

/** Where a row's Guide opens: the catalog's guides address, the document, and the heading in it. */
export const guideAddress = (catalog, guide) => `${catalog.guides}${guide.document}#${headingAnchor(guide.heading)}`;

/**
 * The grants of a world's grants read (GET /door/grants, as door-grants-api.ts parses it) that stand now, each as the
 * page keeps it: its id, world, version, bridge, its program's own name, whether its program is an AI's, and whom it
 * decides for by id (`things`); names are added from the society (namesFor).
 */
export function standingGrants(grants) {
  return (grants ?? []).filter(grant => grant.ended === null).map(grant => Object.freeze({
    grantId: grant.grantId, worldId: grant.worldId, versionId: grant.versionId, bridge: grant.bridge,
    named: grant.declared?.name ?? null, ai: grant.ai, things: grant.things,
  }));
}

/**
 * Whom a standing grant decides for, by name, in the society its version holds (GET /world/versions/{v}/society): the
 * people it names, in the grant's order, then the bodies that came in through the gate under it whose own program
 * decides for them, each by the name its record gives it.
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

/** Whether a refused end's code says the grant had already ended or run out, so the row says it ended. */
export const alreadyEnded = (code) => code === 'grant_ended';

const state = (words, kind) => Object.freeze({ words, kind });
const action = (kind, word, more = {}) => Object.freeze({ kind, word, ...more });
const notHere = () => state(INTEGRATION_WORDS.notHere, 'na');

/** What a provider's entry may spend now: the guest's allowance, or the owner's spending, by provider; null unread. */
function leftOf(entries, provider) {
  const entry = (entries ?? []).find(one => one.provider === provider);
  return entry ? dollars(entry.available_usd) : null;
}

/**
 * A model provider's row: on where one of its models is not refused here (a hosted one's key set, or the host's for a
 * guest, with what is left; a runner on this computer running), off where every one is refused, and not on this server
 * where no model of it is listed. A guest is shown only what they can use. Models lists a chosen world's models.
 */
function providerRow(entry, reads) {
  if (reads.models === null) return { state: null, action: null };
  const own = reads.models.filter(model => model.provider === entry.key);
  if (!own.length) return { state: notHere(), action: null };
  // A runner on this computer, as the catalog states it, is running or not; a hosted provider has a key or not.
  const local = entry.local === true;
  const asked = own.some(model => !(model.runtime?.provider_refusal ?? model.refusal));
  const guide = entry.guide ? action('guide', INTEGRATION_WORDS.guide, { guide: entry.guide }) : null;
  if (asked) {
    const left = local ? null : leftOf(reads.guest ? reads.allowance : reads.spending, entry.key);
    const words = local ? INTEGRATION_WORDS.running : [reads.guest ? INTEGRATION_WORDS.hostKey : INTEGRATION_WORDS.keySet, left && `${left} left`].filter(Boolean).join(' · ');
    return { state: state(words, 'on'), action: reads.chosen ? action('models', INTEGRATION_WORDS.models, { provider: entry.key }) : null };
  }
  if (reads.guest) return { state: notHere(), action: null };
  const codes = own.map(model => model.runtime?.provider_refusal ?? model.refusal);
  const words = codes.every(code => code === 'provider_credential_absent') ? INTEGRATION_WORDS.noKey
    : codes.every(code => code === 'provider_not_running') ? INTEGRATION_WORDS.notRunning
      : codes.every(code => BUDGET_SPENT.includes(code)) ? INTEGRATION_WORDS.budgetSpent
        : codes.every(code => code === 'provider_not_admitted') ? INTEGRATION_WORDS.notHere : INTEGRATION_WORDS.off;
  return { state: state(words, words === INTEGRATION_WORDS.notHere ? 'na' : 'off'), action: words === INTEGRATION_WORDS.notHere ? null : guide };
}

/**
 * The web source's row, from the drafts offer's web notes: on with how many searches one making sends, and for a guest
 * how many the host leaves them; off by its reason on the owner's install; not on this server where a guest cannot use
 * it.
 */
function webRow(entry, reads) {
  if (reads.notes === null) return { state: null, action: null };
  const guide = !reads.guest && entry.guide ? action('guide', INTEGRATION_WORDS.guide, { guide: entry.guide }) : null;
  if (reads.notes.offered) {
    const n = reads.notes.searches_at_most;
    const per = Number.isSafeInteger(n) ? `Up to ${n} ${n === 1 ? 'search' : 'searches'} a making` : null;
    const calls = reads.guest ? (reads.allowance ?? []).find(one => one.provider === entry.key)?.available_calls : undefined;
    const left = Number.isSafeInteger(calls) ? `${calls} left` : null;
    return { state: state([per, left].filter(Boolean).join(' · ') || INTEGRATION_WORDS.running, 'on'), action: guide };
  }
  if (reads.guest) return { state: notHere(), action: null };
  const code = reads.notes.code;
  const words = code === 'references_not_configured' ? INTEGRATION_WORDS.noKey : code === 'references_not_run_here' ? INTEGRATION_WORDS.notRunning
    : code === 'reference_budget_unavailable' ? INTEGRATION_WORDS.budgetSpent : INTEGRATION_WORDS.off;
  return { state: state(words, 'off'), action: guide };
}

/**
 * GitHub's row, from whether this server keeps worlds on GitHub and how many of this workspace's are (GET
 * /world/github-projects/kept): not on this server for a guest or where it keeps none; else how many are kept, with
 * Connect where a world is chosen to ask for.
 */
function githubRow(entry, reads) {
  if (reads.guest) return { state: notHere(), action: null };
  if (reads.keeping === null) return { state: null, action: null };
  if (!reads.keeping.kept_here) return { state: notHere(), action: null };
  const n = reads.keeping.on_github;
  const words = n > 0 ? `${n} ${n === 1 ? 'world' : 'worlds'} on GitHub` : INTEGRATION_WORDS.notConnected;
  return { state: state(words, n > 0 ? 'on' : 'off'), action: reads.chosen ? action('connect', INTEGRATION_WORDS.connect, { worldId: reads.chosen.worldId, versionId: reads.chosen.versionId }) : null };
}

/**
 * The door's rows: each grant that stands, named by its program's own name (else its bridge's), with whom it decides
 * for or plays and in which world, and End; with none, the door's own row, none granted where this server admits
 * programs, and not on this server where it admits none or for a guest.
 */
function doorRows(entry, reads, catalog) {
  const row = (state_, action_) => [Object.freeze({ key: entry.key, name: entry.name, line: entry.line, mark: entry.mark, state: state_, action: action_ })];
  if (reads.guest) return row(notHere(), null);
  if (reads.bridges === null || reads.standing === null) return row(null, null);
  if (!reads.standing.length) {
    return reads.bridges.length ? row(state(INTEGRATION_WORDS.noneGranted, 'off'), entry.guide ? action('guide', INTEGRATION_WORDS.guide, { guide: entry.guide }) : null) : row(notHere(), null);
  }
  const marks = new Map((catalog.entries ?? []).filter(one => one.kind === 'grant').map(one => [Boolean(one.ai), one.mark]));
  return reads.standing.map(grant => {
    const world = reads.worlds.get(grant.worldId) ?? null;
    const names = grant.names ?? [];
    const whom = names.length ? ` ${joinNames(names)}` : '';
    const where = world ? ` in ${world}` : '';
    const line = grant.ai ? `Decides${whom ? ` for${whom}` : ''}${where}.` : `Plays${whom}${where}.`;
    const ended = reads.ended?.get(grant.grantId);
    const now = ended === 'ended' ? state(INTEGRATION_WORDS.ended, 'off')
      : ended === 'refused' ? state(INTEGRATION_WORDS.endRefused, 'refused')
        : state(grant.ai ? INTEGRATION_WORDS.deciding : INTEGRATION_WORDS.playing, 'on');
    const label = reads.bridges.find(bridge => bridge.bridge === grant.bridge)?.label ?? null;
    return Object.freeze({
      key: `grant:${grant.grantId}`, name: grant.named ?? label ?? entry.name, line, mark: marks.get(grant.ai) ?? entry.mark,
      state: now, action: ended === 'ended' ? null : action('end', INTEGRATION_WORDS.end, { grantId: grant.grantId, worldId: grant.worldId }),
    });
  });
}

/**
 * The page's rows in the catalog's order. `reads`: the catalog (GET /integrations), `models` (GET /models' list),
 * `notes` (the drafts offer's web notes), `allowance` (a guest's, from GET /auth/session) or `spending` (the owner's
 * providers, GET /spending), `keeping` (GET /world/github-projects/kept), `bridges` and `standing` (the door's, each
 * standing grant with `names`), `worlds` (world id to title), `chosen` (the front door's world, `{ worldId, versionId }`,
 * or null), `ended` (grant id to 'ended' or 'refused'), `connected` (after Connect: the world's title it asked for, or
 * 'refused'), and `guest`.
 * A read not answered yet is null, and the row it decides draws no state.
 */
export function integrationRows(reads) {
  const catalog = reads.catalog;
  if (!catalog) return [];
  return catalog.entries.filter(entry => entry.kind !== 'grant').flatMap(entry => {
    if (entry.kind === 'door') return doorRows(entry, reads, catalog);
    const made = entry.kind === 'provider' ? providerRow(entry, reads) : entry.kind === 'web' ? webRow(entry, reads)
      : entry.kind === 'github' ? githubRow(entry, reads) : { state: null, action: null };
    const after = entry.kind === 'github' && reads.connected ? reads.connected : null;
    const now = after === 'refused' ? state(INTEGRATION_WORDS.connectRefused, 'refused') : after ? state(INTEGRATION_WORDS.asked(after), 'off') : made.state;
    return [Object.freeze({ key: entry.key, name: entry.name, line: entry.line, mark: entry.mark, state: now, action: after && after !== 'refused' ? null : made.action })];
  });
}
