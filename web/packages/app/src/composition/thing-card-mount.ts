/**
 * The thing card mounted as Selected's view of what a person picks in a world.
 *
 * For a person, the card's words come from what Selected already knows about them (the
 * inspector's words, and who runs them from Who decides' read), and their mind is changed
 * through Who decides' own choose, so the card and the panel never disagree. A person of a society
 * of things also reads its kind's summary, the look it wears, what it holds and how it came; a
 * visitor is decided for from outside, by the program it came with, so its card offers no Change.
 * For a placed thing that is nobody, the words come from its kind's and its worn look's documents
 * in the host's thing library and the version's look choices. Closing the card takes the drawn
 * ring away.
 */

import type { ThingLibrary } from '@exulanica/atlas-react/things';
import { buildThingCard, type CardLine, type CardLookOutcome, type CardLooks, type CardMark, type CardMind, type CardMindChoice, type ThingCardModel } from '../ui/thing-card.js';
import { cameWords, costWords, modelLine, outsideLatestWords, outsideShort } from '../ui/society-models.js';
import type { ModelRef, SocietyModel } from '../society-models-api.js';
import type { Credentials } from '../config.js';
import { openThingLibrary } from '../things-library.js';
import { fetchThingLooks, readKindFacts, readLookFacts, type KindFacts, type LookFacts, type LookReference } from '../thing-card-api.js';
import type { InhabitantView, MountedEnvironmentSelection, SelectedBeing, SelectedPerson, SelectedThing } from './environment-selection.js';
import { creditOf, kindCameWords, lookLine, lookOptionLine, sourceLink, withArticle } from './thing-origin-words.js';
import { chooseThingLook, fetchThingCardRoute, sameLook, type CardLookReference, type LookChoiceOutcome, type ThingCardRoute } from '../thing-card-route-api.js';
import { lineMarkOf, markLabel, markOf, type ThingMark } from './thing-marks.js';
import { carriedWords, type KindReference } from './visitor-notices.js';
import type { BeingLine } from './being-lines.js';
import { fetchCrossingManifest, type CrossingManifest, type CrossingRows } from '../crossing-manifest-api.js';
import { THING_LOOK_CHOSEN_EVENT, THING_PICK_EVENT, type ThingLookChosenDetail, type ThingPickDetail } from './things.js';
import '../ui/thing-card.css';

const ROUTINE_KEY = 'routine';
const ROUTINE_NAME = 'Their own routine';
const ROUTINE_LINE = 'What they would do anyway. No AI is asked.';

/** The card's pill for a mark: "AI" beside a title and a mind, or where a visitor came from. */
export function cardMark(mark: ThingMark): CardMark {
  return { kind: mark.kind, text: mark.kind === 'ai' ? 'AI' : mark.label, label: markLabel(mark) };
}

const modelKey = (model: ModelRef): string => `${model.provider} ${model.modelId}`;

/** What the card reads about a being of a society of things, once read. */
export interface BeingFacts {
  readonly kind: KindFacts;
  /** The look it is drawn in, or null where it is drawn as one of the world's people. */
  readonly look: LookFacts | null;
  /** What it holds, in words ("a sword"), or null for nothing. */
  readonly holding: string | null;
  /** For a visitor: what came across and what stayed behind, or null where its manifest is unread or unreadable. */
  readonly crossing?: CrossingRows | null;
  /** Its card as the server serves it, or null where none is served (no society of things here, or not read yet). */
  readonly route?: ThingCardRoute | null;
}

/**
 * A visitor's mind before Who decides' read names who runs it: the program it came with decides,
 * said only as far as the door's entry goes. A program-decided grant says nothing about a person,
 * so no person is claimed; an AI is named only where the door's entry says an AI runs the bridge.
 */
function outsideMind(mark: ThingMark | null, entry: SelectedBeing['crossing']): CardMind {
  const bridge = entry?.entry ?? null;
  const line = bridge === null
    ? 'Decided from outside this world.'
    : bridge.ai
      ? `Decided from outside by an AI agent, through ${bridge.label}. It is not one of this world's own minds.`
      : `Decided from outside, through ${bridge.label}.`;
  return { name: bridge?.label ?? 'From outside', line, mark: mark === null ? null : cardMark(mark), choices: [], ask: '', when: '' };
}

/**
 * A being's lines in the card's words: to whom (or from whom, for what it heard), the model that
 * wrote it where the line's record names one, and its mark by the one rule the world's bubbles use
 * (`lineMarkOf`).
 */
function cardLines(lines: readonly BeingLine[], subjectId: string, models: readonly SocietyModel[] | null, own: boolean): CardLine[] {
  return lines.map((said) => {
    const toWhom = said.toId === subjectId ? 'it' : said.to ?? 'everyone near';
    const written = said.model;
    const model = written === null ? null
      : models?.find((one) => one.provider === written.provider && one.modelId === written.modelId) ?? null;
    const mark = lineMarkOf({ decider: said.decider, model, speaker: said.speaker });
    const who = own ? `To ${toWhom}` : `${said.speakerName}, to ${toWhom}`;
    return { mark: mark === null ? null : cardMark(mark), who: model === null ? who : `${who} · ${model.name}`, line: said.line, minute: said.tick };
  });
}

/** How a being came to be here, in words. */
function beingCameWords(being: SelectedBeing, kind: KindFacts | null): string {
  switch (being.cameBy) {
    case 'crossed':
      return `Came in from ${being.crossing?.entry?.label ?? 'outside this world'}.`;
    case 'placed':
      return kind === null ? 'You placed it here.' : `You placed it here. ${kindCameWords(kind.label, kind.origin)}`;
    case 'populated':
      return 'One of the people who live in this world.';
  }
}

/** A person's card from what Selected knows about them and the models offered for people here. */
export function personCard(
  subjectId: string,
  about: SelectedPerson,
  models: readonly SocietyModel[] | null,
  facts: BeingFacts | null = null,
): ThingCardModel {
  const being = about.being ?? null;
  const crossing = being?.crossing ?? null;
  // Who runs it from outside, as Who decides' read names it (a visitor its program decides for, or
  // one of the world's own people a grant lets a program run); before that read names it, a visitor
  // whose arrival did not say the world decides is taken as its program's.
  const outsideEntry = about.mind?.outside ?? null;
  if (being !== null && (outsideEntry !== null || (crossing !== null && crossing.decidedBy === 'program'))) {
    const outside = markOf(being.mark) ?? (crossing === null ? null : markOf({ running: null, crossing, bridge: crossing.entry }));
    const mind: CardMind = outsideEntry !== null && about.mind !== null
      // Who decides' own words for it, never a copy: an outside program decides, so no Change; and
      // what became of its program's latest answer where it was not taken (Who decides' Lately).
      ? { name: outsideShort(outsideEntry), line: about.mind.words, lately: outsideLatestWords(outsideEntry), mark: outside === null ? null : cardMark(outside), choices: [], ask: '', when: '' }
      : outsideMind(outside, crossing);
    return {
      subject: subjectId,
      title: about.note.title,
      mark: outside === null ? null : cardMark(outside),
      summary: facts?.kind.summary ?? about.note.description,
      now: about.note.activity.trim() === '' ? null : about.note.activity,
      mind,
      looks: routeLooks(facts?.route ?? null) ?? looksOf(facts?.look ?? null),
      holding: routeHolding(facts?.route ?? null) ?? facts?.holding ?? null,
      ...routeWords(facts?.route ?? null),
      crossing: facts?.crossing ?? null,
      said: cardLines(being.said, subjectId, models, true),
      heard: cardLines(being.heard, subjectId, models, false),
      cameFrom: outsideEntry !== null ? cameWords(outsideEntry) : beingCameWords(being, facts?.kind ?? null),
    };
  }
  const running = about.mind?.running ?? null;
  // A visitor the world decides for is marked by its mind and where it came from, as in the world.
  const mark = being === null ? markOf({ running }) : markOf({ ...being.mark, running });
  const offered = running === null ? undefined : models?.find((model) => modelKey(model) === modelKey(running));
  const choices: CardMindChoice[] = about.mind === null || models === null ? [] : [
    { key: ROUTINE_KEY, name: ROUTINE_NAME, line: ROUTINE_LINE, badge: null, now: running === null, refused: null },
    ...models.map((model) => ({
      key: modelKey(model),
      name: model.name,
      line: modelLine(model),
      badge: costWords(model, models),
      now: running !== null && modelKey(model) === modelKey(running),
      refused: model.refusal === null ? null : 'Not asked on this server.',
    })),
  ];
  // While a person plays them, the person decides and their own mind rests: Who decides' words for
  // it, and nothing to change here until they are given back.
  const played = about.mind?.played ?? null;
  const mind: CardMind = played !== null && about.mind !== null ? {
    name: played.byYou ? 'You' : 'Another person',
    line: about.mind.words,
    mark: mark === null ? null : cardMark(mark),
    choices: [],
    ask: '',
    when: '',
  } : {
    name: running?.name ?? ROUTINE_NAME,
    line: running !== null
      ? (offered === undefined ? 'An open model.' : modelLine(offered))
      : about.mind === null
        ? 'The people of this world follow their own routine. No AI is asked.'
        // Who decides' words, which say why a chosen model is not asked here.
        : about.mind.words === `${ROUTINE_NAME}.` ? ROUTINE_LINE : about.mind.words,
    mark: mark === null ? null : cardMark(mark),
    choices,
    ask: 'Choose who decides what they do.',
    when: 'A new mind takes over at their next choice, within a minute of world time.',
  };
  return {
    subject: subjectId,
    title: about.note.title,
    mark: mark === null ? null : cardMark(mark),
    summary: facts?.kind.summary ?? about.note.description,
    now: about.note.activity.trim() === '' ? null : about.note.activity,
    mind,
    ...(being === null ? {} : {
      looks: routeLooks(facts?.route ?? null) ?? looksOf(facts?.look ?? null),
      holding: routeHolding(facts?.route ?? null) ?? facts?.holding ?? null,
      ...routeWords(facts?.route ?? null),
      said: cardLines(being.said, subjectId, models, true),
      heard: cardLines(being.heard, subjectId, models, false),
    }),
    cameFrom: being === null ? 'One of the people who live in this world.' : beingCameWords(being, facts?.kind ?? null),
  };
}

/** A look's row: its name, who made it under which licence, its source, and any credit owed. */
function looksOf(look: LookFacts | null): CardLooks | null {
  return look === null ? null : {
    name: title(look.label),
    line: lookLine(look.origin),
    source: sourceLink(look.origin),
    credit: creditOf(look.origin),
  };
}

/** A label as a title: "blocky knight" reads "Blocky knight". */
const title = (label: string): string => label.charAt(0).toUpperCase() + label.slice(1);

/** The key the card's look choices go by: the look's own reference, never its position in the list. */
export const lookKey = (ref: CardLookReference): string =>
  ref.source === 'workspace' ? `workspace/${ref.sha256}` : `shipped/${ref.key}/${ref.version}/${ref.sha256}`;

/** The look it wears, as its served card names it, and every look it may wear; null where no card is served. */
function routeLooks(route: ThingCardRoute | null): CardLooks | null {
  if (route === null) return null;
  const origin = route.look.origin;
  return {
    name: title(route.look.label),
    line: origin === null ? '' : lookLine(origin),
    source: origin === null ? null : sourceLink(origin),
    credit: origin === null ? null : creditOf(origin),
    choices: route.looks.map((option) => ({
      key: lookKey(option.ref),
      name: title(option.label),
      line: lookOptionLine(option.authors, option.licence),
      now: sameLook(option.ref, route.look.ref),
    })),
  };
}

/** What it holds, from its served card, or null where the card states no hands (the card then keeps today's words). */
const routeHolding = (route: ThingCardRoute | null): string | null | undefined =>
  route === null || route.holding === null ? undefined : carriedWords(route.holding);

/** What it can do and what others can do with it, from its served card. */
const routeWords = (route: ThingCardRoute | null): { can?: readonly string[]; offers?: readonly string[] } =>
  route === null ? {} : { can: route.can, offers: route.offers };

/** The first twelve characters of a record's digest: enough to compare by eye. */
const short = (sha256: string): string => sha256.slice(0, 12);

/**
 * The proof that a look changed nothing else: the world's record as the swap read it, and as read
 * again after, compared. A differing record at the same minute is said, never hidden.
 */
export function lookProof(before: ThingCardRoute['society'], after: ThingCardRoute['society']): string {
  if (before.tick !== after.tick) {
    return `The world moved on from minute ${before.tick} to minute ${after.tick} between the two reads, so the two records are of different minutes. A look is kept beside a thing, never in what it does.`;
  }
  if (before.stateSha256 === after.stateSha256) {
    return `This world's record at minute ${before.tick}, read as the look changed and again after: ${short(before.stateSha256)} and ${short(after.stateSha256)}, the same. A look is kept beside a thing, never in what it does.`;
  }
  return `This world's record at minute ${before.tick} read ${short(before.stateSha256)} as the look changed and ${short(after.stateSha256)} after.`;
}

/** Why a look was not changed, in words, from the route's refusal code. */
export function lookRefusalWords(code: string): string {
  switch (code) {
    case 'look_unfit':
      return 'That look is made for another body, so it cannot be drawn in it.';
    case 'look_not_shipped':
      return 'That look is no longer offered here. Choose another.';
    case 'http_403':
      return 'Only this world\'s owner can change how its things are drawn.';
    default:
      return 'The look was not changed. Try again in a moment.';
  }
}

/** A placed thing's card, from its kind's and its worn look's facts. */
export function placedThingCard(thing: SelectedThing, kind: KindFacts, look: LookFacts | null, route: ThingCardRoute | null = null): ThingCardModel {
  const mind: CardMind = kind.class === 'object'
    ? { name: 'None', line: 'It decides nothing.', mark: null, choices: [], ask: '', when: '' }
    // A being placed in a world whose people do not take things yet stands where it was placed.
    : { name: 'Nothing yet', line: 'It stands where you placed it. Nothing runs it in this world yet.', mark: null, choices: [], ask: '', when: '' };
  const placedByYou = thing.placed.origin.kind === 'authored';
  return {
    subject: thing.placed.thingId,
    title: title(kind.label),
    mark: null,
    summary: kind.summary,
    now: null,
    mind,
    looks: routeLooks(route) ?? looksOf(look),
    ...routeWords(route),
    cameFrom: `${placedByYou ? 'You placed it here. ' : ''}${kindCameWords(kind.label, kind.origin)}`,
  };
}

/** What the card says while a thing's facts are read, and when they cannot be. */
const pendingCard = (thing: SelectedThing, heading: string, summary: string): ThingCardModel => ({
  subject: thing.placed.thingId, title: heading, mark: null,
  summary, now: null, mind: null, looks: null, cameFrom: thing.placed.origin.kind === 'authored' ? 'You placed it here.' : '',
});

export interface MountedThingCard {
  /** Selected's view of a person; hand it to `useInhabitantView`. */
  readonly view: InhabitantView;
}

export function mountThingCard(options: {
  readonly selection: Pick<MountedEnvironmentSelection, 'decide' | 'models' | 'openDecides'>;
  /** Open Compare, or null where this world offers no comparison. */
  readonly compare: (() => void) | null;
  /** The shell the drawn ring listens on: closing the card raises the pick event with nothing. */
  readonly shell: HTMLElement;
  readonly credentials: Credentials;
  /** The host's thing library; read with the credentials when left out. */
  readonly library?: () => Promise<ThingLibrary>;
  /** A version's look choices by placed id; read with the credentials when left out. */
  readonly looks?: (worldId: string, versionId: string) => Promise<ReadonlyMap<string, LookReference>>;
  /** A visitor's crossing manifest; read with the credentials when left out. */
  readonly manifest?: (worldId: string, arrivalId: string) => Promise<CrossingManifest>;
  /** A thing's served card by its society id (null where none is served); read with the credentials when left out. */
  readonly card?: (worldId: string, versionId: string, thingId: string) => Promise<ThingCardRoute | null>;
  /** Choose the look a thing is drawn in; sent with the credentials when left out. */
  readonly chooseLook?: (worldId: string, versionId: string, thingId: string, look: CardLookReference) => Promise<LookChoiceOutcome>;
}): MountedThingCard {
  const { selection } = options;
  let subject: string | null = null;
  /** The placed thing shown now, so an answer for another one that arrives late is dropped. */
  let shownThing: string | null = null;
  let library: Promise<ThingLibrary> | null = null;
  const openLibrary = (): Promise<ThingLibrary> => {
    library ??= (options.library ?? (() => openThingLibrary(options.credentials)))();
    library.catch(() => { library = null; });
    return library;
  };
  const readLooks = options.looks ?? ((worldId: string, versionId: string) => fetchThingLooks(options.credentials, worldId, versionId));
  const readManifest = options.manifest ?? ((worldId: string, arrivalId: string) => fetchCrossingManifest(options.credentials, worldId, arrivalId));
  const readCard = options.card ?? ((worldId: string, versionId: string, thingId: string) => fetchThingCardRoute(options.credentials, worldId, versionId, thingId));
  const sendLook = options.chooseLook
    ?? ((worldId: string, versionId: string, thingId: string, look: CardLookReference) => chooseThingLook(options.credentials, worldId, versionId, thingId, look));
  /**
   * Each thing's served card by version and society id, read at most once a minute: a failed read
   * keeps the card last read and is asked again after a minute; null where none is served.
   */
  const routes = new Map<string, { readonly at: number; readonly card: ThingCardRoute | null }>();
  const routeKey = (versionId: string, thingId: string): string => `${versionId}/${thingId}`;
  const routeOf = (versionId: string, thingId: string): ThingCardRoute | null => routes.get(routeKey(versionId, thingId))?.card ?? null;
  const routeDue = (versionId: string, thingId: string): boolean => {
    const held = routes.get(routeKey(versionId, thingId));
    return held === undefined || performance.now() - held.at >= 60_000;
  };
  const readRoute = async (worldId: string, versionId: string, thingId: string): Promise<void> => {
    const key = routeKey(versionId, thingId);
    const card = await readCard(worldId, versionId, thingId).catch(() => routes.get(key)?.card ?? null);
    routes.set(key, { at: performance.now(), card });
  };
  /** What the card shows now with a served card, so a look chosen on it reaches the right thing; redrawn after a swap. */
  let target: { readonly worldId: string; readonly versionId: string; readonly thingId: string; readonly redraw: () => void } | null = null;
  /** Each crossing's rows by its arrival, read once (a manifest never changes); null where unreadable. */
  const manifests = new Map<string, CrossingRows | null>();
  /** When a manifest read last failed, by arrival: asked again at most once a minute, quietly. */
  const manifestFailedAt = new Map<string, number>();
  const manifestDue = (arrival: string): boolean => {
    if (!manifests.has(arrival)) return true;
    const failed = manifestFailedAt.get(arrival);
    return failed !== undefined && performance.now() - failed >= 60_000;
  };
  const crossingOf = (being: SelectedBeing): string | null => (being.world === null ? null : being.crossing?.arrivalId ?? null);

  // A being's card is drawn again every minute, so what it reads is kept: kinds and looks by their
  // digests (they never change), the version's look choices for a minute at a time.
  let opened: ThingLibrary | null = null;
  const kinds = new Map<string, KindFacts>();
  const looks = new Map<string, LookFacts | null>();
  let choices: { readonly version: string; readonly at: number; readonly worn: ReadonlyMap<string, LookReference> } | null = null;
  const refKey = (ref: { readonly version: number; readonly sha256: string }, key: string): string => `${key}/${ref.version}/${ref.sha256}`;
  /** A kind's facts once read, by its reference: a shipped kind or one the workspace keeps alike. */
  const kindRead = (kind: KindReference): KindFacts | undefined => kinds.get(refKey(kind, kind.kind));
  /** The look a being is drawn in: the one chosen for it, or its kind's first (from the kind's document). */
  const wornLook = (subjectId: string, being: SelectedBeing): LookReference | null =>
    choices?.worn.get(being.placedId ?? subjectId) ?? kindRead(being.kind)?.firstLook ?? null;
  const choicesRead = (being: SelectedBeing): boolean =>
    being.world === null || (choices !== null && choices.version === being.world.versionId);
  const choicesFresh = (being: SelectedBeing): boolean =>
    being.world === null || (choicesRead(being) && performance.now() - choices!.at < 60_000);
  /**
   * What is known of a being now, or null while something it needs was never read; the look
   * choices last read for its version stand while they are read again.
   */
  const factsNow = (subjectId: string, being: SelectedBeing): BeingFacts | null => {
    if (opened === null || !choicesRead(being)) return null;
    const kind = kindRead(being.kind);
    if (kind === undefined) return null;
    const worn = wornLook(subjectId, being);
    const look = worn === null ? null : looks.get(refKey(worn, worn.key));
    if (look === undefined) return null;
    const arrival = crossingOf(being);
    return {
      kind, look,
      holding: carriedWords(being.holding.flatMap((held) => kindRead(held.kind)?.label ?? [])),
      crossing: arrival === null ? null : manifests.get(arrival) ?? null,
      route: being.world === null ? null : routeOf(being.world.versionId, subjectId),
    };
  };
  const readBeing = async (subjectId: string, being: SelectedBeing): Promise<void> => {
    // Its served card is read beside the rest; a server without it leaves the card as it was.
    const route = being.world !== null && routeDue(being.world.versionId, subjectId)
      ? readRoute(being.world.worldId, being.world.versionId, subjectId)
      : Promise.resolve();
    const library = await openLibrary();
    opened = library;
    if (being.world !== null && !choicesFresh(being)) {
      const { worldId, versionId } = being.world;
      choices = { version: versionId, at: performance.now(), worn: await readLooks(worldId, versionId) };
    }
    const readKind = async (kind: KindReference): Promise<void> => {
      if (kindRead(kind) !== undefined) return;
      kinds.set(refKey(kind, kind.kind), readKindFacts(await library.kindDocument({ key: kind.kind, version: kind.version, sha256: kind.sha256 })));
    };
    await readKind(being.kind);
    // What it holds is named by each held thing's own kind; one that cannot be read is left unnamed.
    await Promise.allSettled(being.holding.map((held) => readKind(held.kind)));
    const arrival = crossingOf(being);
    if (arrival !== null && manifestDue(arrival) && being.world !== null) {
      // A server without the route answers no manifest, and a first-profile manifest states no words:
      // no rows, and a failed read is asked again at most once a minute.
      manifests.set(arrival, await readManifest(being.world.worldId, arrival).then((read) => {
        manifestFailedAt.delete(arrival);
        return read.rows;
      }, () => {
        manifestFailedAt.set(arrival, performance.now());
        return null;
      }));
    }
    const worn = wornLook(subjectId, being);
    if (worn !== null && !looks.has(refKey(worn, worn.key))) {
      // A look from the people catalog draws the being as one of the world's people, and one that
      // cannot be read is left out: either way, no look row, and the rest of the card still shows.
      const look = await library.lookDocument(worn).then(readLookFacts, () => null);
      looks.set(refKey(worn, worn.key), look === null || look.peopleCatalog ? null : look);
    }
    await route;
  };
  /** The thing's ring goes when the card stops showing it: hidden, or its panel closed. */
  const letGo = (): void => {
    if (shownThing === null) return;
    shownThing = null;
    options.shell.dispatchEvent(new CustomEvent<ThingPickDetail>(THING_PICK_EVENT, { bubbles: true, detail: null }));
  };
  // Selected's panel closes by its own Close, Escape or another panel opening, all of which hide
  // it; the card watches for that rather than asking the panel to call it.
  let watched: Element | null = null;
  const panelWatch = new MutationObserver(() => {
    if (watched instanceof HTMLElement && watched.hidden) letGo();
  });
  const watchPanel = (): void => {
    const panel = card.root.closest('.world-panel');
    if (panel === watched) return;
    panelWatch.disconnect();
    watched = panel;
    if (panel !== null) panelWatch.observe(panel, { attributes: true, attributeFilter: ['hidden'] });
  };
  /**
   * Draw the shown thing in another look: the server records the choice beside it and answers its
   * card; the world is asked to redraw it at once, and its record is read again so the card can
   * show that nothing it does changed.
   */
  async function chooseLookFor(key: string): Promise<CardLookOutcome> {
    const shown = target;
    const route = shown === null ? null : routeOf(shown.versionId, shown.thingId);
    const option = route?.looks.find((one) => lookKey(one.ref) === key) ?? null;
    if (shown === null || route === null || option === null) return { words: 'That look is no longer offered here. Choose another.', proof: null };
    const outcome = await sendLook(shown.worldId, shown.versionId, shown.thingId, option.ref);
    if (!outcome.chosen) return { words: lookRefusalWords(outcome.code), proof: null };
    routes.set(routeKey(shown.versionId, shown.thingId), { at: performance.now(), card: outcome.card });
    // Raised on the shell, which stays in the page however the card is closed meanwhile.
    options.shell.dispatchEvent(new CustomEvent<ThingLookChosenDetail>(THING_LOOK_CHOSEN_EVENT, { bubbles: true, detail: { thingId: shown.thingId } }));
    if (target === shown) shown.redraw();
    const after = await readCard(shown.worldId, shown.versionId, shown.thingId).catch(() => null);
    return {
      words: `Now drawn as ${withArticle(outcome.card.look.label)}. Only its look changed: what it does, says and decides is exactly the same.`,
      proof: after === null ? null : lookProof(outcome.card.society, after.society),
    };
  }

  const card = buildThingCard({
    async onChoose(key) {
      const chosen = subject;
      if (chosen === null) return 'Nobody is selected.';
      const model = key === ROUTINE_KEY ? null : selection.models()?.find((held) => modelKey(held) === key) ?? null;
      if (key !== ROUTINE_KEY && model === null) return 'That model is no longer offered here. Choose another.';
      const outcome = await selection.decide({
        role: 'people',
        subjectIds: [chosen],
        model: model === null ? null : { provider: model.provider, modelId: model.modelId },
      });
      return outcome.words;
    },
    onAllMinds() {
      if (subject !== null) selection.openDecides({ role: 'people', subjectIds: [subject] });
    },
    onCompare: options.compare,
    onLook: chooseLookFor,
  });
  return {
    view: {
      root: card.root,
      show(subjectId, about) {
        subject = subjectId;
        shownThing = null;
        const being = about.being ?? null;
        const world = being?.world ?? null;
        const redraw = (): void => {
          if (subject === subjectId && being !== null) card.render(personCard(subjectId, about, selection.models(), factsNow(subjectId, being)));
        };
        target = world === null ? null : { worldId: world.worldId, versionId: world.versionId, thingId: subjectId, redraw };
        card.render(personCard(subjectId, about, selection.models(), being === null ? null : factsNow(subjectId, being)));
        const arrival = being === null ? null : crossingOf(being);
        const routeStale = world !== null && routeDue(world.versionId, subjectId);
        if (being !== null && (factsNow(subjectId, being) === null || !choicesFresh(being) || routeStale || (arrival !== null && manifestDue(arrival)))) {
          void readBeing(subjectId, being).then(() => {
            // Shown again from what Selected knows now, unless the card moved on meanwhile.
            if (subject === subjectId && factsNow(subjectId, being) !== null) {
              card.render(personCard(subjectId, about, selection.models(), factsNow(subjectId, being)));
            }
          }, () => undefined);
        }
        return true;
      },
      showThing(thing) {
        subject = null;
        shownThing = thing.placed.thingId;
        target = null;
        watchPanel();
        card.render(pendingCard(thing, 'Reading what this is', ''));
        void (async () => {
          try {
            // Its served card, by the id its society gives it, read beside the rest.
            const societyId = thing.societyThingId ?? null;
            const route = societyId === null ? Promise.resolve() : readRoute(thing.worldId, thing.versionId, societyId);
            const things = await openLibrary();
            const named = { key: thing.placed.kind.kind, version: thing.placed.kind.version, sha256: thing.placed.kind.sha256 };
            const kind = readKindFacts(await things.kindDocument(named));
            const worn = (await readLooks(thing.worldId, thing.versionId)).get(thing.placed.thingId);
            const lookNamed = worn ?? kind.firstLook;
            const look = lookNamed === null ? null : readLookFacts(await things.lookDocument(lookNamed));
            await route;
            const redraw = (): void => {
              if (shownThing === thing.placed.thingId) {
                card.render(placedThingCard(thing, kind, look, societyId === null ? null : routeOf(thing.versionId, societyId)));
              }
            };
            if (shownThing === thing.placed.thingId && societyId !== null) {
              target = { worldId: thing.worldId, versionId: thing.versionId, thingId: societyId, redraw };
            }
            redraw();
          } catch {
            if (shownThing === thing.placed.thingId) {
              card.render(pendingCard(thing, 'Not read', 'What this is could not be read. Close it and pick it again in a moment.'));
            }
          }
        })();
        return true;
      },
      hide() {
        subject = null;
        target = null;
        letGo();
      },
    },
  };
}
