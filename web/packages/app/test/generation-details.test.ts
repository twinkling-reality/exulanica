// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest';
import { buildGenerationDetails } from '../src/ui/generation-details.js';

afterEach(() => document.body.replaceChildren());

it('shows every recorded value without consulting current defaults, labels or providers', () => {
  const createFrom = vi.fn();
  const original = { historical_unknown_key: 17, street_mix: 'old-schema-choice' };
  const entry = { title: 'Saved place', generatedGround: {
    recipeLabel: 'Recorded recipe', specification: 'world-specification.v2', values: original,
  } };
  const { root, show } = buildGenerationDetails({ entry, createFrom });
  show();
  expect([...root.querySelectorAll('[data-saved-key]')].map(row => [row.getAttribute('data-saved-key'), row.querySelector('dd')?.textContent]))
    .toEqual([['historical_unknown_key', '17'], ['street_mix', 'old-schema-choice']]);
  expect(root.querySelector('input, select, textarea')).toBeNull();
  expect(original).toEqual({ historical_unknown_key: 17, street_mix: 'old-schema-choice' });
  expect(createFrom).not.toHaveBeenCalled();
});

it('restores focus on dismissal and never offers creation when values were not recorded', () => {
  const prior = document.createElement('button');
  document.body.append(prior); prior.focus();
  const entry = { title: 'Old place', generatedGround: {
    recipeLabel: 'Old recipe', specification: null, values: null,
  } };
  const createFrom = vi.fn();
  const { root, show } = buildGenerationDetails({ entry, createFrom });
  show();
  expect(root.querySelectorAll('button')).toHaveLength(1);
  root.dispatchEvent(new Event('cancel', { cancelable: true }));
  expect(root.isConnected).toBe(false);
  expect(document.activeElement).toBe(prior);
  expect(createFrom).not.toHaveBeenCalled();
});
