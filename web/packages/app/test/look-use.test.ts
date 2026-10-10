// @vitest-environment happy-dom
// Use in the Look sheet, through the page's wiring: the real sheet tells which card was pressed,
// and what is asked of the host follows the card, not the pack, since a pack offered at a later
// version than the world wears has two cards naming one pack.
import { afterEach, describe, expect, it } from 'vitest';
import { lookToUse, type LookUse } from '../src/composition/look-use.js';
import { buildLookSheet, type LookOption } from '../src/ui/look-sheet.js';
import type { WorldStylePackBinding } from '../src/world-style-api.js';

const pack = (packId: string, title: string, version: number): LookOption => ({
  packId, title, description: `${title}, in its own words.`, authors: ['Exulanica'],
  licence: { id: 'CC0-1.0', attribution: null }, picture: null, version, changes: null,
});
// The host offers Cozy town at version 3 and Finished town at version 1.
const OFFERED = [pack('cozy', 'Cozy town', 3), pack('finished', 'Finished town', 1)];
const LISTED: Record<string, WorldStylePackBinding> = {
  cozy: { packId: 'cozy', version: 3, manifestSha256: '3'.repeat(64) },
  finished: { packId: 'finished', version: 1, manifestSha256: 'f'.repeat(64) },
};
// The world wears Cozy town version 2, with a setting of its own.
const WORN: WorldStylePackBinding = { packId: 'cozy', version: 2, manifestSha256: '2'.repeat(64) };
const SETTINGS = {
  axes: [{ key: 'sky', title: 'Hour and sky' }, { key: 'ground', title: 'Ground and beyond' }],
  parts: [
    { axis: 'sky', key: 'dusk', title: 'Dusk', description: 'Evening.' },
    { axis: 'sky', key: 'night', title: 'Night', description: 'Night.' },
    { axis: 'ground', key: 'sea', title: 'By the sea', description: 'Sea.' },
  ],
};

/** The sheet wired as the page wires it (`main.ts`), with what each Use asked for kept. */
function wired(worn: WorldStylePackBinding | null, setting: boolean) {
  const asked: LookUse[] = [];
  const sheet = buildLookSheet({
    worldTitle: 'Saturday market',
    onUse: async (option, _say, parts, isNow) => {
      const use = lookToUse({
        option, isNow: isNow === true, setting: parts, worn, listed: LISTED[option.packId]!,
        earlierPackId: worn !== null && worn.version !== LISTED[worn.packId]!.version ? worn.packId : null,
      });
      asked.push(use);
      return `The world is now drawn in ${use.named}.`;
    },
    onClose: () => undefined,
  });
  document.body.replaceChildren(sheet.root);
  const earlier = worn !== null && worn.version !== LISTED[worn.packId]!.version
    ? { earlier: { packId: worn.packId, version: worn.version, picture: null } } : {};
  sheet.show(OFFERED, worn?.packId ?? null, earlier, setting ? { offered: SETTINGS, chosen: { sky: 'dusk' } } : null);
  const card = (caption: string): HTMLButtonElement => [...sheet.root.querySelectorAll<HTMLButtonElement>('button.look-sheet-card')]
    .find((button) => button.querySelector('.look-sheet-caption')!.textContent === caption)!;
  const use = sheet.root.querySelector<HTMLButtonElement>('[data-action="look.use"]')!;
  const pick = (axis: string, key: string): void => {
    const select = sheet.root.querySelector<HTMLSelectElement>(`select[data-setting-axis="${axis}"]`)!;
    select.value = key;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const pressUse = async (): Promise<LookUse> => {
    const before = asked.length;
    use.click();
    await expect.poll(() => asked.length).toBe(before + 1);
    return asked[before]!;
  };
  return { sheet, card, use, pick, pressUse, status: () => sheet.root.querySelector('p.look-sheet-status')!.textContent };
}

afterEach(() => document.body.replaceChildren());

describe('the two cards of one pack, where the world wears an earlier version', () => {
  it('moves the world to the current version from the Version card, keeping the setting it has', async () => {
    const { card, use, pressUse, status } = wired(WORN, true);
    card('Version 3').click();
    expect(use.querySelector('span')!.textContent).toBe('Use version 3');
    const asked = await pressUse();
    expect(asked.binding).toEqual({ ...LISTED['cozy'], settingParts: { sky: 'dusk' } });
    expect(asked.named).toBe('version 3 of Cozy town');
    expect(asked.settingOnly).toBe(false);
    await expect.poll(status).toBe('The world is now drawn in version 3 of Cozy town.');
  });

  it('keeps the version the world names from the Now card, which only a changed setting can use', async () => {
    const { card, use, pick, pressUse } = wired(WORN, true);
    card('Now · version 2').click();
    expect(use.hidden).toBe(true);
    pick('ground', 'sea');
    expect(use.querySelector('span')!.textContent).toBe('Use this setting');
    const asked = await pressUse();
    expect(asked.binding).toEqual({ ...WORN, settingParts: { sky: 'dusk', ground: 'sea' } });
    expect(asked.named).toBe('Cozy town, in its new setting');
    expect(asked.settingOnly).toBe(true);
  });

  it('moves to the current version from the Version card with a setting changed on the way', async () => {
    const { card, pick, pressUse } = wired(WORN, true);
    card('Version 3').click();
    pick('sky', 'night');
    const asked = await pressUse();
    expect(asked.binding).toEqual({ ...LISTED['cozy'], settingParts: { sky: 'night' } });
    expect(asked.named).toBe('version 3 of Cozy town');
  });

  it('moves to the current version on a host that lists no setting, as it always did', async () => {
    const { card, pressUse } = wired(WORN, false);
    card('Version 3').click();
    const asked = await pressUse();
    expect(asked.binding).toEqual(LISTED['cozy']);
    expect(asked.named).toBe('version 3 of Cozy town');
  });
});

describe('any other card', () => {
  it('asks for another pack as the host lists it, with the parts chosen', async () => {
    const { card, pressUse } = wired(WORN, true);
    card('Look 2').click();
    const asked = await pressUse();
    expect(asked.binding).toEqual({ ...LISTED['finished'], settingParts: { sky: 'dusk' } });
    expect(asked.named).toBe('Finished town');
  });

  it('keeps the current version a world already wears when only its setting changes', async () => {
    const { pick, pressUse } = wired(LISTED['cozy']!, true);
    pick('sky', '');
    const asked = await pressUse();
    // No part left: the look as it states, at the version worn.
    expect(asked.binding).toEqual(LISTED['cozy']);
    expect(asked.named).toBe('Cozy town, in its new setting');
  });

  it('names the listed pack for a world wearing its workspace\'s own look, never the look\'s version', () => {
    const own = { ...WORN, own: { live: true } } as unknown as WorldStylePackBinding;
    const asked = lookToUse({ option: OFFERED[0]!, isNow: true, setting: { sky: 'dusk' }, worn: own, listed: LISTED['cozy']!, earlierPackId: null });
    expect(asked.binding).toEqual({ ...LISTED['cozy'], settingParts: { sky: 'dusk' } });
    expect(asked.settingOnly).toBe(false);
  });
});
