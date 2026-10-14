// The front door's addresses, shared by the page (front-door.ts, front-door-preview.ts), the
// workspace server (front-door-server.mjs) and verify-front-door.mjs. Plain JavaScript, so all
// three use the same rule.

/**
 * Whether `url` is a scene preview: the chooser's live background, the app drawing one saved world
 * in an inert frame. A preview only reads, and the workspace's world view never mounts in one.
 */
export function isScenePreview(url) {
  const target = url instanceof URL ? url : new URL(url, 'http://127.0.0.1/');
  return target.searchParams.get('capture') === '1' || target.searchParams.get('livePreview') === '1';
}

/** The front door itself, on `origin`. */
export function frontDoorAddress(origin) {
  return new URL('/', origin).href;
}

/** Where Open goes: the workspace's own world view of the saved world `entryId`, on `origin`. */
export function worldAddress(entryId, origin) {
  const target = new URL('/', origin);
  target.searchParams.set('entry', entryId);
  return target.href;
}

/** The live background for the chosen world: the same saved world, drawn read-only. */
export function scenePreviewAddress(entryId, origin) {
  const target = new URL(worldAddress(entryId, origin));
  target.searchParams.set('capture', '1');
  target.searchParams.set('livePreview', '1');
  return target.href;
}

/** Where the server serves the private captures a capture catalog names. */
export const CAPTURE_ROUTE = '/review-world-previews/';

/**
 * The private capture of `entry` that `catalog` names, as an address the page can load, or null.
 * A capture is only shown while every identity it was taken of still holds: the entry, its world,
 * its authored version and state, and its appearance version. Anything else is a different picture.
 */
export function capturedPicture(catalog, entry) {
  const capture = catalog?.captures?.find((one) => one.entry_id === entry.entryId
    && one.world_id === entry.worldId
    && one.version_id === entry.authoredVersionId
    && one.authored_state_sha256 === entry.authoredStateSha256
    && one.style_version_id === entry.styleVersionId);
  return capture === undefined ? null : CAPTURE_ROUTE + encodeURIComponent(capture.file);
}
