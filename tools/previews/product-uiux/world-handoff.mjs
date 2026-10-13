export const WORLD_WORKSPACE_ORIGIN = 'http://127.0.0.1:19974';

/** Scene captures stay inert on the chooser origin; interactive worlds have one owner. */
export function isScenePreview(url) {
  const target = url instanceof URL ? url : new URL(url, 'http://127.0.0.1:19972');
  return target.searchParams.get('capture') === '1' || target.searchParams.get('livePreview') === '1';
}
export function worldEntryDestination(entryId) {
  const target = new URL('/', WORLD_WORKSPACE_ORIGIN);
  target.searchParams.set('entry', entryId);
  return target.href;
}
export function interactiveEntryRedirect(url) {
  const target = url instanceof URL ? url : new URL(url, 'http://127.0.0.1:19972');
  const entryId = target.searchParams.get('entry');
  return target.pathname === '/' && entryId && !isScenePreview(target) ? worldEntryDestination(entryId) : null;
}
