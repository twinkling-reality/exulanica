/**
 * The thing card mounted as Selected's view of a person: the card's words made from what Selected
 * already knows about them (the inspector's words, and who runs them from Who decides' read), and
 * its mind changed through Who decides' own choose, so the card and the panel never disagree.
 */

import { buildThingCard, type CardMark, type CardMind, type CardMindChoice, type ThingCardModel } from '../ui/thing-card.js';
import { costWords, modelLine } from '../ui/society-models.js';
import type { ModelRef, SocietyModel } from '../society-models-api.js';
import type { InhabitantView, MountedEnvironmentSelection, SelectedPerson } from './environment-selection.js';
import { markLabel, markOf, type ThingMark } from './thing-marks.js';
import '../ui/thing-card.css';

const ROUTINE_KEY = 'routine';
const ROUTINE_NAME = 'Their own routine';
const ROUTINE_LINE = 'What they would do anyway. No AI is asked.';

/** The card's pill for a mark: "AI" beside a title and a mind, or where a visitor came from. */
export function cardMark(mark: ThingMark): CardMark {
  return { kind: mark.kind, text: mark.kind === 'ai' ? 'AI' : mark.label, label: markLabel(mark) };
}

const modelKey = (model: ModelRef): string => `${model.provider} ${model.modelId}`;

/** A person's card from what Selected knows about them and the models offered for people here. */
export function personCard(
  subjectId: string,
  about: SelectedPerson,
  models: readonly SocietyModel[] | null,
): ThingCardModel {
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
    summary: about.note.description,
    now: about.note.activity.trim() === '' ? null : about.note.activity,
    mind,
    cameFrom: 'One of the people who live in this world.',
  };
}

export interface MountedThingCard {
  /** Selected's view of a person; hand it to `useInhabitantView`. */
  readonly view: InhabitantView;
}

export function mountThingCard(options: {
  readonly selection: Pick<MountedEnvironmentSelection, 'decide' | 'models' | 'openDecides'>;
  /** Open Compare, or null where this world offers no comparison. */
  readonly compare: (() => void) | null;
}): MountedThingCard {
  const { selection } = options;
  let subject: string | null = null;
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
        card.render(personCard(subjectId, about, selection.models()));
        return true;
      },
      hide() {
        subject = null;
      },
    },
  };
}
