import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import type { CharacterSubject } from '@exulanica/atlas-core';
import { previewInhabitantSelection, type CharacterLook } from '../src/character-catalog.js';

const catalog = ['look-a', 'look-b', 'look-c', 'look-d'].map(lookId => ({
  lookId, defaultColors: { skin: '#ba9988', cloth: '#554466' }, variationSlots: ['cloth'],
})) as unknown as readonly CharacterLook[];
const subject = (id: string, branchId = 'one'): CharacterSubject => ({
  kind: 'synthetic-inhabitant', societyId: 'society', branchId, inhabitantId: id,
});

describe('fictional catalog defaults', () => {
  it('retains appearance across branch, ordering and repeated residency changes', () => {
    const chosen = previewInhabitantSelection(catalog, subject('person'));
    expect(previewInhabitantSelection([...catalog].reverse(), subject('person', 'two'))).toEqual(chosen);
    expect(previewInhabitantSelection(catalog, subject('person'))).toEqual(chosen);
  });
  it('varies the population while preserving undeclared source surfaces and catalog data', () => {
    const before = JSON.stringify(catalog);
    const choices = Array.from({ length: 24 }, (_, index) => previewInhabitantSelection(catalog, subject(String(index)))!);
    expect(new Set(choices.map(choice => choice.lookId)).size).toBe(4);
    expect(new Set(choices.map(choice => JSON.stringify(choice))).size).toBeGreaterThan(4);
    for (const choice of choices) {
      expect(Object.keys(choice.appearance.colors!)).toEqual(['cloth']);
      expect(choice.appearance.colors!.cloth).toMatch(/^#[a-f0-9]{6}$/);
    }
    expect(JSON.stringify(catalog)).toBe(before);
  });
  it('does not assign fictional appearance to the player or a scene person', () => {
    expect(previewInhabitantSelection(catalog, { kind: 'player', playerId: 'viewer' })).toBeNull();
    expect(previewInhabitantSelection(catalog, { kind: 'scene-person' } as CharacterSubject)).toBeNull();
    expect(previewInhabitantSelection([], subject('person'))).toBeNull();
  });
  it('faces imported preview characters along the world forward axis', () => {
    const looks = JSON.parse(readFileSync(
      new URL('../public/fixtures/characters/catalog.json', import.meta.url),
      'utf8',
    )) as CharacterLook[];
    expect(looks.length).toBeGreaterThan(0);
    for (const look of looks) expect(look.descriptor.forwardYawDegrees).toBe(180);
  });
});
