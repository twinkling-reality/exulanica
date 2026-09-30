import { describe, expect, it } from 'vitest';
import { resolveCompanionPlacement } from '../src/ui/companion-placement.js';

describe('Companion encounter placement', () => {
  it('keeps the supplied visual-novel composition independent of a saved side', () => {
    expect(resolveCompanionPlacement({
      viewport: { width: 1280, height: 720 },
      memoryBounds: null,
      preferredSide: 'left',
    })).toEqual({
      presenceSide: 'center',
      speechSide: 'center',
      choicesSide: 'center',
      basis: 'reference-fixed',
    });
  });

  it('treats the memory as backdrop rather than mirroring the reading order around it', () => {
    const placement = resolveCompanionPlacement({
      viewport: { width: 1440, height: 900 },
      memoryBounds: { left: 0, top: 0, width: 1440, height: 900 },
      preferredSide: 'right',
    });
    expect(placement).toMatchObject({
      presenceSide: 'center',
      speechSide: 'center',
      choicesSide: 'center',
      basis: 'reference-fixed',
    });
  });
});
