import { describe, expect, it } from 'vitest';
import {
  commandForKeystroke,
  initialWorldShell,
  updateWorldShell,
} from '../src/world-shell.js';

describe('the Atlas shell', () => {
  it('allows one primary surface and clears Index detail when switching', () => {
    const index = updateWorldShell(initialWorldShell(), { type: 'toggle-index' });
    const detail = updateWorldShell(index, { type: 'show-detail', id: 'entity-1' });
    expect(detail).toMatchObject({ primary: 'index', detailId: 'entity-1' });

    const options = updateWorldShell(detail, { type: 'toggle-options' });
    expect(options).toMatchObject({ primary: 'options', camera: 'ground', detailId: null });
    expect(updateWorldShell(options, { type: 'toggle-options' })).toEqual(detail);
  });

  it('models Map as a camera presentation and restores the exact prior Index context', () => {
    const index = updateWorldShell(initialWorldShell(), { type: 'toggle-index' });
    const detail = updateWorldShell(index, { type: 'show-detail', id: 'entity-1' });
    const map = updateWorldShell(detail, { type: 'toggle-map' });
    expect(map).toMatchObject({ primary: 'world', camera: 'map', detailId: null });
    expect(updateWorldShell(map, { type: 'toggle-map' })).toEqual(detail);
  });

  it('models Map as a camera presentation of the live world from the ground', () => {
    const map = updateWorldShell(initialWorldShell(), { type: 'toggle-map' });
    expect(map).toMatchObject({ primary: 'world', camera: 'map', detailId: null });
    expect(updateWorldShell(map, { type: 'toggle-map' })).toEqual(initialWorldShell());
  });

  it('unwinds a system surface to Map and then to the Index context below it', () => {
    const index = updateWorldShell(initialWorldShell(), { type: 'toggle-index' });
    const detail = updateWorldShell(index, { type: 'show-detail', id: 'entity-1' });
    const map = updateWorldShell(detail, { type: 'toggle-map' });
    const controls = updateWorldShell(map, { type: 'toggle-controls' });
    expect(updateWorldShell(controls, { type: 'toggle-controls' })).toEqual(map);
    expect(updateWorldShell(map, { type: 'toggle-map' })).toEqual(detail);
  });

  it('refuses to create an orphaned detail outside the Index', () => {
    expect(
      updateWorldShell(initialWorldShell(), { type: 'show-detail', id: 'entity-1' }),
    ).toEqual(initialWorldShell());
  });

  it('returns from Character to the exact prior library selection', () => {
    const index = updateWorldShell(initialWorldShell(), { type: 'toggle-index' });
    const detail = updateWorldShell(index, { type: 'show-detail', id: 'person-1' });
    const character = updateWorldShell(detail, { type: 'toggle-character' });
    expect(character.primary).toBe('character');
    expect(character.detailId).toBeNull();
    expect(updateWorldShell(character, { type: 'toggle-character' })).toEqual(detail);
  });

  it('has an unconditional complete-Index recovery transition for renderer loss', () => {
    const map = updateWorldShell(initialWorldShell(), { type: 'toggle-map' });
    // Recovery is unconditional, so it clears the return stack rather than leaving somewhere to
    // step back to: there is no longer a surface behind this one to return into.
    expect(updateWorldShell(map, { type: 'show-index' })).toEqual({
      primary: 'index', camera: 'ground', detailId: null, returnTo: null, returnStack: [],
    });
  });
});

describe('shell command ownership', () => {
  const stroke = (over: Partial<Parameters<typeof commandForKeystroke>[0]> = {}) => ({
    code: 'KeyI',
    key: 'i',
    modified: false,
    typing: false,
    ...over,
  });

  it.each([
    ['KeyI', 'i', 'toggle-index'],
    ['KeyM', 'm', 'toggle-map'],
    ['KeyO', 'o', 'toggle-options'],
    ['KeyK', 'k', 'toggle-character'],
    ['Slash', '?', 'toggle-controls'],
    ['Backspace', 'Backspace', 'selection-back'],
  ])('maps %s to its one shell command', (code, key, command) => {
    expect(commandForKeystroke(stroke({ code, key }))).toBe(command);
  });

  it('never takes a shortcut while the user types or holds a modifier', () => {
    expect(commandForKeystroke(stroke({ typing: true }))).toBeNull();
    expect(commandForKeystroke(stroke({ modified: true }))).toBeNull();
  });

  it('never binds Escape', () => {
    expect(commandForKeystroke(stroke({ code: 'Escape', key: 'Escape' }))).toBeNull();
  });
});
