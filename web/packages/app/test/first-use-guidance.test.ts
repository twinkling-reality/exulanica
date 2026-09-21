import { describe, expect, it } from 'vitest';
import {
  FIRST_USE_GUIDANCE_KEY,
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

describe('first-use Atlas guidance', () => {
  it('explains the world before asking for an entry gesture', () => {
    const guidance = createFirstUseGuidance(new MemoryStorage());
    expect(guidance.phase()).toBe('arrival');
    expect(guidance.prompt('converse')).toEqual({
      statement: 'Welcome to Exulanica',
      actions: [{ label: 'Start building', activate: 'summon-companion' }],
    });
  });

  it('presents movement and Companion actions immediately after entering', () => {
    const storage = new MemoryStorage();
    const guidance = createFirstUseGuidance(storage);
    expect(guidance.observeMode('converse')).toBe(false);
    expect(guidance.observeMode('traverse')).toBe(true);
    expect(guidance.prompt('traverse')).toEqual({
      statement: 'Welcome to Exulanica',
      actions: [
        { key: 'W A S D', label: 'Move' },
        { key: 'X', label: 'Call your Unnamed Companion' },
        { key: 'Esc', label: 'Dismiss' },
      ],
    });
    expect(guidance.observeMovement()).toBe(true);
    expect(guidance.prompt('traverse')).toEqual({
      statement: 'Welcome to Exulanica',
      actions: [
        { key: 'X', label: 'Call your Unnamed Companion' },
        { key: 'Esc', label: 'Dismiss' },
      ],
    });
    expect(storage.getItem(FIRST_USE_GUIDANCE_KEY)).toBe('companion');
  });

  it('persists completion only after an answer path completes it', () => {
    const storage = new MemoryStorage();
    storage.setItem(FIRST_USE_GUIDANCE_KEY, 'companion');
    const guidance = createFirstUseGuidance(storage);
    expect(guidance.complete()).toBe(true);
    expect(guidance.phase()).toBe('complete');
    expect(guidance.prompt('converse')).toBeNull();
    const nextVisit = createFirstUseGuidance(storage);
    expect(nextVisit.phase()).toBe('complete');
    expect(nextVisit.prompt('converse')).toEqual({
      statement: 'Welcome to Exulanica',
      actions: [{ label: 'Start building', activate: 'summon-companion' }],
    });
    nextVisit.observeMode('traverse');
    expect(nextVisit.prompt('converse')).toBeNull();
  });

  it('falls back safely when storage is unavailable or contains a future value', () => {
    const future = new MemoryStorage();
    future.setItem(FIRST_USE_GUIDANCE_KEY, 'future-phase');
    expect(createFirstUseGuidance(future).phase()).toBe('arrival');

    const blocked = createFirstUseGuidance({
      getItem: () => { throw new Error('blocked'); },
      setItem: () => { throw new Error('blocked'); },
    });
    expect(blocked.phase()).toBe('arrival');
    expect(() => blocked.observeMode('traverse')).not.toThrow();
  });
});
