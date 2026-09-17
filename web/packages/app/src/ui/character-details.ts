import type { NativeCharacterRuntime } from '@exulanica/atlas-react/playcanvas';

/** Report the representation actually drawn, not the fallback retained for stable selection. */
export function characterDisplayDetails(
  native: ReturnType<NativeCharacterRuntime['inspect']> | undefined,
  fallbackId: string | undefined,
  nearBudget?: number,
): readonly (readonly [string, string])[] {
  if (native?.status === 'ready') return [
    ['Character appearance', 'Imported character with authored appearance. Not measured traits or a real person’s likeness.'],
    ['Character rig', native.rigId ?? 'Unavailable'],
    ['Character asset', native.asset?.assetKey ?? 'Source reference unavailable'],
    ['Character version', native.asset?.contentSha256 ?? 'Content version unavailable'],
    ['Character source status', 'Available to the current renderer'],
  ];
  if (native?.status === 'hidden') return [
    ['Character appearance', 'Hidden by current availability or permission.'],
    ['Character version', 'No character is drawn'],
  ];
  return [
    ['Character appearance', native?.status === 'loading'
      ? 'Loading imported appearance; an abstract fallback is shown.'
      : 'Abstract authored appearance. Not measured traits or a real person’s likeness.'],
    ['Character version', fallbackId ?? 'Outside the nearby rendering cap'],
    ...(native?.status === 'fallback' ? [['Character source status', native.error ?? 'Imported source unavailable; abstract fallback shown.'] as const] : []),
    ...(native?.status === 'far' ? [['Character detail', `Far form: only the nearest ${nearBudget ?? 'few'} people are drawn in full at once.`] as const] : []),
  ];
}
