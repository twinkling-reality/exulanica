/** Local presentation fixtures for the development preview. They execute no model or write. */
import type { Turn } from '@exulanica/companion-runtime';
import { AskUnavailable, type CompanionAnswer } from '../companion-ask-api.js';
import type { CompanionEncounter } from '../ui/companion-encounter.js';

export type CompanionPreviewScenario = 'greeting' | 'caption' | 'long' | 'waiting' | 'failure';

export function companionPreviewScenario(search: string): CompanionPreviewScenario | null {
  const value = new URLSearchParams(search).get('companionScene');
  return value === 'greeting' || value === 'caption' || value === 'long' || value === 'waiting' || value === 'failure'
    ? value
    : null;
}

const caption: Turn = {
  turnId: 'preview-caption',
  intent: 'acknowledge',
  subjectEntityId: null,
  subjectAnchorId: null,
  utteranceKey: 'utterance.acknowledge',
  utterance: 'This is a local caption fixture. The world remains visible while we speak.',
  evidence: [],
  choiceSet: null,
  freeTextAllowed: false,
  escapes: [],
  stateVersion: 0,
};

const longAnswer: CompanionAnswer = {
  question: 'What belongs in the reading surface?',
  clauses: [
    { text: 'The conversation stays in view while the world remains around it.', type: 'meta', citations: [] },
    { text: 'A longer answer can name several distinct facts. Each line keeps its full wording in the expanded reading area, where a person can read at their own pace without the ordinary caption turning into a tall panel.', type: 'meta', citations: [] },
    { text: 'Sources, model attribution and any uncertainty belong with those details when an actual answer supplies them. This local fixture contains no model result or cited photograph.', type: 'meta', citations: [] },
  ],
  text: 'The conversation stays in view while the world remains around it.',
  abstained: null,
  deterministic: true,
  repaired: false,
  evidence: [],
  provenance: {
    composed: 'outcome', servedModel: null, servedModelName: null,
    plannedBy: null, plannedByName: null, latencyMs: 0, usedFallback: false,
  },
  promptVersion: 'local-display-fixture',
  calls: [],
};

export function showCompanionPreviewScenario(
  panel: CompanionEncounter,
  scenario: CompanionPreviewScenario,
): void {
  panel.root.dataset['previewScenario'] = scenario;
  if (scenario === 'greeting') panel.showGreeting();
  else if (scenario === 'caption') panel.render(caption);
  else if (scenario === 'long') panel.restoreAnswer(longAnswer);
  else if (scenario === 'waiting') panel.askStarted('What do these sources show?');
  else {
    panel.askStarted('What do these sources show?');
    panel.reportAskFailure(new AskUnavailable(
      'unreachable',
      'This is a local failure fixture. No question was sent to a model.',
    ));
  }
}
