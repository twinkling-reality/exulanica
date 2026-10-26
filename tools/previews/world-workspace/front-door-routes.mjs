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

/**
 * Whether a first run lands on Create a world in place of the front door (aha item 3): the only saved world is the
 * starter an empty workspace is given, never changed (authored, no edit since it was made, no photograph added or
 * removed, its first revision) and never opened in this browser (`pictured`: no picture kept of it), and the person
 * did not come back here from a world (`remembered`). Once any world is opened or made, the front door is the landing.
 */
export function leadsWithCreate(entries, { remembered = null, pictured = () => false } = {}) {
  if (remembered || entries.length !== 1) return false;
  const [only] = entries;
  return only.sourceKind === 'authored' && only.currentAuthoredEditSeq === 0 && only.revision === 1
    && (only.sourceAttachments ?? []).length === 0 && (only.previousSourceAttachments ?? []).length === 0 && !pictured(only);
}

/**
 * The showcase world a link names (`/?world=<key>`, the public site's links), or null: a key is lowercase words joined
 * by hyphens, and an address that also names a saved world (`entry`) opens that world instead.
 */
export function showcaseKey(url) {
  const target = url instanceof URL ? url : new URL(url, 'http://127.0.0.1/');
  const key = target.searchParams.get('world');
  return key !== null && !target.searchParams.has('entry') && /^[a-z][a-z0-9-]{0,63}$/.test(key) ? key : null;
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

/**
 * Where the address goes once the workspace's world view has opened the saved world `entryId` on the
 * page at `href`: that world's own address, so a reload opens it again, or null where the address
 * already names it. A scene preview's address never changes.
 */
export function openWorldAddress(href, entryId) {
  const current = new URL(href);
  if (isScenePreview(current) || current.searchParams.get('entry') === entryId) return null;
  return worldAddress(entryId, current.origin);
}

/**
 * A History moment drawn for its picture: the saved world `entryId`, read-only as a scene preview,
 * its people placed as the moment `key` (in this tab's session storage) recorded them.
 */
export function momentPreviewAddress(entryId, key, origin) {
  const target = new URL(worldAddress(entryId, origin));
  target.searchParams.set('capture', '1');
  target.searchParams.set('moment', key);
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
