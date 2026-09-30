export type CompanionSide = 'left' | 'right';

export interface ScreenRect {
  readonly left: number;
  readonly top: number;
  readonly width: number;
  readonly height: number;
}

export interface CompanionPlacementInput {
  readonly viewport: { readonly width: number; readonly height: number };
  readonly memoryBounds: ScreenRect | null;
  readonly preferredSide: CompanionSide;
}

/** The supplied dialogue reference is a fixed composition, not a mirrored card layout. */
export interface CompanionPlacement {
  readonly presenceSide: 'center';
  readonly speechSide: 'center';
  readonly choicesSide: 'center';
  readonly basis: 'reference-fixed';
}

/**
 * Return the authored encounter composition.
 *
 * The world remains the backdrop. Speech and responses share one lower-centre reading path;
 * projected world objects do not move them or reorder the answers.
 */
export function resolveCompanionPlacement(_input: CompanionPlacementInput): CompanionPlacement {
  return Object.freeze({
    presenceSide: 'center',
    speechSide: 'center',
    choicesSide: 'center',
    basis: 'reference-fixed',
  });
}
