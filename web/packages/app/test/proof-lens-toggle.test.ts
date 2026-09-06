// @vitest-environment happy-dom
/**
 * P10-A-a's last criterion: "toggling the lens changes no scene, no rung and no receipt".
 *
 * It was unticked and marked untestable, for a good reason: there was no toggle, so there was
 * nothing to toggle and nothing for a test to observe. There is one now, and this file is what
 * makes the criterion a result rather than a hope.
 *
 * WHAT "CHANGES NOTHING" HAS TO MEAN HERE. Rungs and receipts are backend facts; a browser test
 * cannot assert on a database. What it can assert on is every proxy for them the browser holds:
 * the rung disclosures handed to the panel, the DOM those disclosures render to, and the calls the
 * lens makes. If a toggle left all three identical and only pushed a colour at the renderer, then
 * nothing it did could have reached a scene, a rung or a receipt, because nothing it did reached
 * anything but a uniform.
 *
 * The colour resolution is checked here too, in the direction that matters: a tier's colour is a
 * pure function of the theme and the tier, and a region drawing nothing gets the `unavailable`
 * row rather than a shade of `reconstructed`.
 */
import { describe, expect, it } from 'vitest';
import { DAWN_THEME, PROOF_TIERS, proofLensPalette, proofTierIndex } from '@exulanica/presentation';
import { islandId as toIslandId } from '@exulanica/atlas-core';
import { buildStatus, proofTierDisclosure, type ReconstructionRungDisclosure } from '../src/ui/status.js';
import { proofLensIslandColors, proofTierForScene } from '../src/ui/proof-lens.js';

/** The retained bowl collection's actual shape: one trained scene drawn, one passed over. */
const SCENES: readonly ReconstructionRungDisclosure[] = Object.freeze([
  Object.freeze({
    sceneId: '851ca35b-31c3-560c-84f9-4e142962755b',
    recordedRung: 3 as const,
    displayedRung: 3 as const,
    registeredMemberCount: 51,
    memberCount: 51,
    renderingSubstrate: 'gaussian_splats' as const,
    reasons: Object.freeze(['Rung 2 withheld: no physically validated scale receipt is available.']),
    drawn: true,
  }),
  Object.freeze({
    sceneId: '52ec40fd-4b9d-5898-b897-41107e240332',
    recordedRung: 3 as const,
    displayedRung: 4 as const,
    registeredMemberCount: 40,
    memberCount: 40,
    renderingSubstrate: 'source_photographs' as const,
    reasons: Object.freeze(['Not drawn: its region displays a more complete reconstruction of the same photographs.']),
    drawn: false,
  }),
]);

const ISLAND = toIslandId('region-bowl');
const islandOfScene = (): typeof ISLAND => ISLAND;

function statusWith(enabled: boolean, onToggle: (next: boolean) => void): HTMLElement {
  return buildStatus({
    omittedRegionCount: 0,
    undrawable: new Map(),
    reconstructionScenes: SCENES,
    proofLens: { enabled, theme: DAWN_THEME, onToggle },
  });
}

/** Everything the panel says about rungs, which is every rung fact this surface holds. */
function rungMarkup(status: HTMLElement): readonly string[] {
  return [...status.querySelectorAll('.reconstruction-rung')].map((node) => node.outerHTML);
}

describe('the proof lens toggle', () => {
  it('changes no scene, no rung and no receipt', () => {
    const before = structuredClone(SCENES) as ReconstructionRungDisclosure[];
    const changes: boolean[] = [];
    const status = statusWith(false, (next) => changes.push(next));
    const rungsAtRest = rungMarkup(status);
    const tiersAtRest = SCENES.map((scene) => proofTierDisclosure(scene));

    const toggle = status.querySelector<HTMLButtonElement>('.proof-lens-toggle')!;
    toggle.click();
    toggle.click();
    toggle.click();

    // The switch reported three changes and did nothing else.
    expect(changes).toEqual([true, false, true]);
    // No scene record was touched, by value.
    expect(SCENES).toEqual(before);
    // No rung disclosure changed, in the panel or in the sentence the lens itself prints.
    expect(rungMarkup(status)).toEqual(rungsAtRest);
    expect(SCENES.map((scene) => proofTierDisclosure(scene))).toEqual(tiersAtRest);
    // And no receipt digest, member count or reason was rewritten: the disclosures are the only
    // carrier of those in this surface, and they are identical above.
    expect(SCENES[0]!.registeredMemberCount).toBe(51);
    expect(SCENES[0]!.recordedRung).toBe(3);
  });

  it('restates only itself, so the panel around it is untouched', () => {
    const status = statusWith(false, () => {});
    const toggle = status.querySelector<HTMLButtonElement>('.proof-lens-toggle')!;
    expect(toggle.textContent).toBe('Proof lens off');
    expect(toggle.getAttribute('aria-pressed')).toBe('false');

    toggle.click();
    expect(toggle.textContent).toBe('Proof lens on');
    expect(toggle.getAttribute('aria-pressed')).toBe('true');
    expect(status.querySelector<HTMLElement>('.proof-lens')!.dataset.proofLens).toBe('on');

    toggle.click();
    expect(toggle.textContent).toBe('Proof lens off');
    expect(status.querySelector<HTMLElement>('.proof-lens')!.dataset.proofLens).toBe('off');
  });

  it('names every tier in the legend whether or not a region is at it', () => {
    const status = statusWith(true, () => {});
    const named = [...status.querySelectorAll<HTMLElement>('.proof-lens-legend li')]
      .map((item) => item.dataset.proofTier);
    expect(named).toEqual([...PROOF_TIERS]);
    // A colour with no name is a claim nobody can check, so each one carries its own sentence.
    for (const item of status.querySelectorAll('.proof-lens-legend li')) {
      expect(item.textContent!.length).toBeGreaterThan(20);
    }
  });

  it('resolves a region that draws nothing to the unavailable row, not to reconstructed', () => {
    const palette = proofLensPalette(DAWN_THEME);
    const row = (tier: (typeof PROOF_TIERS)[number]): readonly number[] =>
      [...palette.slice(proofTierIndex(tier) * 4, proofTierIndex(tier) * 4 + 4)];

    expect(proofTierForScene(SCENES[0]!)).toBe('reconstructed');
    expect(proofTierForScene(SCENES[1]!)).toBe('unavailable');

    // Both scenes name one region, and the drawn one wins: reporting an absence over a surface
    // that is being drawn is exactly the lie the lens exists to prevent.
    const colors = proofLensIslandColors(SCENES, islandOfScene, DAWN_THEME);
    expect([...colors.get(ISLAND)!]).toEqual(row('reconstructed'));

    const nothingDrawn = proofLensIslandColors([SCENES[1]!], islandOfScene, DAWN_THEME);
    expect([...nothingDrawn.get(ISLAND)!]).toEqual(row('unavailable'));
  });

  it('is a pure function of its arguments, called any number of times', () => {
    const first = proofLensIslandColors(SCENES, islandOfScene, DAWN_THEME);
    const second = proofLensIslandColors(SCENES, islandOfScene, DAWN_THEME);
    expect([...second.get(ISLAND)!]).toEqual([...first.get(ISLAND)!]);
    // A region the caller cannot resolve contributes nothing rather than a default, because a
    // default would be this layer inventing an answer about where a surface came from.
    expect(proofLensIslandColors(SCENES, () => undefined, DAWN_THEME).size).toBe(0);
  });

  it('is absent entirely when no caller supplies it', () => {
    // A surface with no lens to offer shows no switch, rather than a disabled one that implies a
    // capability this page does not have.
    const status = buildStatus({ omittedRegionCount: 0, undrawable: new Map(), reconstructionScenes: SCENES });
    expect(status.querySelector('.proof-lens')).toBeNull();
    expect(status.querySelector('.proof-lens-legend')).toBeNull();
  });
});
