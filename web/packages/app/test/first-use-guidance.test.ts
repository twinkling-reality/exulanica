import { describe, expect, it } from 'vitest';
import {
  FIRST_USE_GUIDANCE_KEY,
  RETIRED_FIRST_USE_GUIDANCE_KEY,
  createFirstUseGuidance,
} from '../src/ui/first-use-guidance.js';

class MemoryStorage {
  readonly values = new Map<string, string>();
  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

describe('what the product says to somebody who has just arrived', () => {
  it('greets an empty world once, in the plain words it is written in', () => {
    const guidance = createFirstUseGuidance(new MemoryStorage());
    expect(guidance.phase()).toBe('new');
    expect(guidance.prompt('converse')).toEqual({
      kind: 'welcome',
      statement: 'This is your world. Nothing is in it yet.',
      actions: [
        { label: 'Start building', activate: 'summon-companion' },
        { key: 'Esc', label: 'Dismiss' },
      ],
    });
  });

  it('says nothing at all once the greeting has been dealt with, including after a reload', () => {
    const storage = new MemoryStorage();
    const guidance = createFirstUseGuidance(storage);
    expect(guidance.complete()).toBe(true);
    expect(guidance.prompt('converse')).toBeNull();
    expect(guidance.prompt('traverse')).toBeNull();

    // The defect this replaces: a fresh page kept an in-memory arrival flag that outranked the
    // saved phase, so the welcome came back on every load for somebody who had finished it.
    const afterReload = createFirstUseGuidance(storage);
    expect(afterReload.phase()).toBe('done');
    expect(afterReload.prompt('converse')).toBeNull();
    expect(afterReload.prompt('traverse')).toBeNull();
  });

  it('does not greet somebody whose world already holds something, on any device', () => {
    const guidance = createFirstUseGuidance(new MemoryStorage(), { worldHasContent: () => true });
    expect(guidance.phase()).toBe('new');
    expect(guidance.prompt('converse')).toBeNull();
    // The same untouched device greets a world that is still empty.
    expect(createFirstUseGuidance(new MemoryStorage(), { worldHasContent: () => false })
      .prompt('converse')).not.toBeNull();
  });

  it('offers one prompt at a time, and moving ends the orientation for good', () => {
    const storage = new MemoryStorage();
    const guidance = createFirstUseGuidance(storage);
    // Entering the world answers the greeting rather than stacking a second prompt on it.
    expect(guidance.observeMode('traverse')).toBe(true);
    expect(guidance.phase()).toBe('greeted');
    expect(guidance.prompt('converse')).toBeNull();
    expect(guidance.prompt('traverse')).toEqual({
      kind: 'orientation',
      statement: 'Look around with the mouse.',
      actions: [
        { key: 'W A S D', label: 'Walk' },
        { key: 'X', label: 'Call your Companion' },
        { key: 'Esc', label: 'Dismiss' },
      ],
    });

    expect(guidance.observeMovement()).toBe(true);
    expect(guidance.phase()).toBe('done');
    expect(guidance.prompt('traverse')).toBeNull();
    expect(storage.getItem(FIRST_USE_GUIDANCE_KEY)).toBe('done');
  });

  it('never greets a device that finished the retired four-state orientation', () => {
    const storage = new MemoryStorage();
    storage.setItem(RETIRED_FIRST_USE_GUIDANCE_KEY, 'complete');
    expect(createFirstUseGuidance(storage).phase()).toBe('done');

    // A device that was partway through it is not finished, so it is greeted by the new system.
    const partway = new MemoryStorage();
    partway.setItem(RETIRED_FIRST_USE_GUIDANCE_KEY, 'traversal');
    expect(createFirstUseGuidance(partway).phase()).toBe('new');
  });

  it('falls back safely when storage is unavailable or holds a value it does not know', () => {
    const future = new MemoryStorage();
    future.setItem(FIRST_USE_GUIDANCE_KEY, 'future-phase');
    expect(createFirstUseGuidance(future).phase()).toBe('new');

    const blocked = createFirstUseGuidance({
      getItem: () => { throw new Error('blocked'); },
      setItem: () => { throw new Error('blocked'); },
    });
    expect(blocked.phase()).toBe('new');
    expect(() => blocked.observeMode('traverse')).not.toThrow();
    expect(() => blocked.complete()).not.toThrow();
  });
});
