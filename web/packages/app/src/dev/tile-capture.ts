/**
 * DEVELOPMENT ONLY: hand a capture driver a way to step the running tile a stated frame at a time.
 *
 * The two guards are the ones the tile evaluation itself sits behind, and they are the whole of the
 * safety argument: this module is imported only from `composition/generated-tile.ts`, which runs only
 * when `import.meta.env.DEV` is true AND the page is the synthetic preview route. A production build
 * drops the branch, the import and this file with it, which
 * `test/generated-tile-evaluation.test.ts` proves by building the app.
 *
 * It is on `window` because the driver is outside the page: a headless browser evaluating an
 * expression cannot reach a module's exports, only what the page has put somewhere it can name.
 */

declare global {
  interface Window {
    __exulanicaTileCapture?: () => unknown;
  }
}

export async function exposeTileCapture(preview: boolean): Promise<void> {
  if (!import.meta.env.DEV || !preview) return;
  const { beginTileCapture } = await import('@exulanica/atlas-react/generated-tile');
  window.__exulanicaTileCapture = beginTileCapture;
}
