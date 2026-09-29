import { describe, expect, it } from 'vitest';
import { ACTION_KINDS } from '../src/society-api.js';
import { ACTION_LABELS, ACTIVITY_KINDS, ACTIVITY_LABELS } from '../src/society-activity-words.js';

/**
 * The page names every kind of action a person's recorded state may name (`ACTION_KINDS` in
 * society-api.ts): a catalogued activity by its catalog's label, and waiting and walking between
 * activities by `ACTION_LABELS`, which names nothing else.
 */
describe('the words for what a person is doing', () => {
  it('name every action kind the page reads, each once', () => {
    const catalogued = ACTION_KINDS.filter((kind) => ACTIVITY_KINDS.has(kind));
    const others = ACTION_KINDS.filter((kind) => !ACTIVITY_KINDS.has(kind));
    // A positive control: the page reads both kinds of action.
    expect(catalogued.length).toBeGreaterThan(0);
    expect(others.length).toBeGreaterThan(0);
    for (const kind of catalogued) expect(ACTIVITY_LABELS.get(kind), kind).toBeTruthy();
    expect(Object.keys(ACTION_LABELS).sort()).toEqual([...others].sort());
    for (const kind of Object.keys(ACTION_LABELS)) expect(ACTIVITY_LABELS.has(kind), kind).toBe(false);
  });
});
