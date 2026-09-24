import { describe, expect, it } from 'vitest';

import type { AnswerProvenance } from '../src/companion-ask-api.js';
import { provenanceSentence } from '../src/ui/companion-speech.js';

const refusal: AnswerProvenance = {
  composed: 'refused',
  servedModel: null,
  plannedBy: null,
  latencyMs: 1200,
  usedFallback: false,
};

describe('the provenance line under a proposal or a refusal', () => {
  it('names the classifier when a refusal came before any model drew anything', () => {
    const line = provenanceSentence({ ...refusal, plannedBy: 'classifier-model' });
    expect(line).toContain('classifier-model');
    expect(line).not.toContain('No model was asked');
    expect(line).not.toContain('search');
  });

  it('says no model was asked, and nothing about a search, when none read the request', () => {
    const line = provenanceSentence(refusal);
    expect(line).toBe('No model was asked.');
  });

  it('credits a proposal to the model that drew it, not the classifier', () => {
    const line = provenanceSentence({
      ...refusal,
      composed: 'proposed',
      servedModel: 'drafting-model',
      plannedBy: 'classifier-model',
    });
    expect(line).toContain('drafting-model');
    expect(line).not.toContain('classifier-model');
  });

  it('never credits the classifier with drawing a change', () => {
    const line = provenanceSentence({ ...refusal, composed: 'proposed', plannedBy: 'classifier-model' });
    expect(line).not.toContain('classifier-model');
  });
});
