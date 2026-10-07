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
import { buildThingCard, type CardLooks, type CardMark, type CardMind, type CardMindChoice, type ThingCardModel } from '../ui/thing-card.js';
import { costWords, modelLine } from '../ui/society-models.js';
import type { ModelRef, SocietyModel } from '../society-models-api.js';
import type { Credentials } from '../config.js';
import { openThingLibrary } from '../things-library.js';
import { fetchThingLooks, readKindFacts, readLookFacts, type KindFacts, type LookFacts, type LookReference } from '../thing-card-api.js';
import type { InhabitantView, MountedEnvironmentSelection, SelectedBeing, SelectedPerson, SelectedThing } from './environment-selection.js';
import { creditOf, kindCameWords, lookLine, sourceLink } from './thing-origin-words.js';
import { markLabel, markOf, type ThingMark } from './thing-marks.js';
import { carriedWords, type KindReference } from './visitor-notices.js';
import { THING_PICK_EVENT, type ThingPickDetail } from './things.js';
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
}

/** A visitor's mind: the program it came with decides for it, in words from the door's entry alone. */
function outsideMind(mark: ThingMark, entry: SelectedBeing['crossing']): CardMind {
  const bridge = entry?.entry ?? null;
  const line = bridge === null
    ? 'Decided from outside this world.'
    : bridge.ai
      ? `Decided from outside, through ${bridge.label}. It is not one of this world's own minds.`
      : `Decided from outside, through ${bridge.label}. It is not an AI.`;
  return { name: mark.full, line, mark: cardMark(mark), choices: [], ask: '', when: '' };
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
  if (being !== null && crossing !== null) {
    const outside = markOf({ running: null, crossing, bridge: crossing.entry, declared: null })!;
    return {
      subject: subjectId,
      title: about.note.title,
      mark: cardMark(outside),
      summary: facts?.kind.summary ?? about.note.description,
      now: about.note.activity.trim() === '' ? null : about.note.activity,
      mind: outsideMind(outside, crossing),
      looks: looksOf(facts?.look ?? null),
      holding: facts?.holding ?? null,
      cameFrom: beingCameWords(being, facts?.kind ?? null),
    };
  }
  const running = about.mind?.running ?? null;
  const mark = markOf({ running });
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
  const mind: CardMind = {
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
    ...(being === null ? {} : { looks: looksOf(facts?.look ?? null), holding: facts?.holding ?? null }),
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

/** A placed thing's card, from its kind's and its worn look's facts. */
export function placedThingCard(thing: SelectedThing, kind: KindFacts, look: LookFacts | null): ThingCardModel {
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
    looks: looksOf(look),
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

  // A being's card is drawn again every minute, so what it reads is kept: kinds and looks by their
  // digests (they never change), the version's look choices for a minute at a time.
  let opened: ThingLibrary | null = null;
  const kinds = new Map<string, KindFacts>();
  const looks = new Map<string, LookFacts | null>();
  let choices: { readonly version: string; readonly at: number; readonly worn: ReadonlyMap<string, LookReference> } | null = null;
  const refKey = (ref: { readonly version: number; readonly sha256: string }, key: string): string => `${key}/${ref.version}/${ref.sha256}`;
  const listed = (kind: KindReference) =>
    opened?.list.kinds.find((one) => one.kind === kind.kind && one.version === kind.version && one.sha256 === kind.sha256);
  /** The look a being is drawn in: the one chosen for it, or its kind's first. */
  const wornLook = (subjectId: string, being: SelectedBeing): LookReference | null =>
    choices?.worn.get(being.placedId ?? subjectId) ?? listed(being.kind)?.looks[0] ?? null;
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
    const kind = kinds.get(refKey(being.kind, being.kind.kind));
    const worn = wornLook(subjectId, being);
    const look = worn === null ? null : looks.get(refKey(worn, worn.key));
    if (kind === undefined || look === undefined) return null;
    return { kind, look, holding: carriedWords(being.holding.flatMap((held) => listed(held.kind)?.label ?? [])) };
  };
  const readBeing = async (subjectId: string, being: SelectedBeing): Promise<void> => {
    const library = await openLibrary();
    opened = library;
    if (being.world !== null && !choicesFresh(being)) {
      const { worldId, versionId } = being.world;
      choices = { version: versionId, at: performance.now(), worn: await readLooks(worldId, versionId) };
    }
    const named = { key: being.kind.kind, version: being.kind.version, sha256: being.kind.sha256 };
    const kindKey = refKey(being.kind, being.kind.kind);
    if (!kinds.has(kindKey)) kinds.set(kindKey, readKindFacts(await library.kindDocument(named)));
    const worn = wornLook(subjectId, being);
    if (worn !== null && !looks.has(refKey(worn, worn.key))) {
      const listed = library.list.looks.find((one) => one.look === worn.key && one.version === worn.version && one.sha256 === worn.sha256);
      // A look from the people catalog draws the being as one of the world's people: no look row.
      looks.set(refKey(worn, worn.key), listed?.lookKind === 'catalog_person' ? null : readLookFacts(await library.lookDocument(worn)));
    }
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
  });
  return {
    view: {
      root: card.root,
      show(subjectId, about) {
        subject = subjectId;
        shownThing = null;
        const being = about.being ?? null;
        card.render(personCard(subjectId, about, selection.models(), being === null ? null : factsNow(subjectId, being)));
        if (being !== null && (factsNow(subjectId, being) === null || !choicesFresh(being))) {
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
        watchPanel();
        card.render(pendingCard(thing, 'Reading what this is', ''));
        void (async () => {
          try {
            const things = await openLibrary();
            const named = { key: thing.placed.kind.kind, version: thing.placed.kind.version, sha256: thing.placed.kind.sha256 };
            const entry = things.kindEntry(named);
            const kind = readKindFacts(await things.kindDocument(named));
            const worn = (await readLooks(thing.worldId, thing.versionId)).get(thing.placed.thingId);
            const first = entry.looks[0];
            const lookNamed = worn ?? first ?? null;
            const look = lookNamed === null ? null : readLookFacts(await things.lookDocument(lookNamed));
            if (shownThing === thing.placed.thingId) card.render(placedThingCard(thing, kind, look));
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
        letGo();
      },
    },
  };
}
