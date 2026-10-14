import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Writable } from 'node:stream';
import { capturedPicture, frontDoorAddress, isScenePreview, scenePreviewAddress, worldAddress } from './front-door-routes.mjs';
import { CAPTURE_CATALOG_PROFILE, capturePictures, capturesModule, checkedCaptureCatalog, scenePreviewWriteGuard } from './front-door-server.mjs';

const origin = 'http://127.0.0.1:19974';

// Open goes to this workspace's own world view; the live background is the same world, read only.
assert.equal(worldAddress('01a1-shore', origin), origin + '/?entry=01a1-shore');
assert.equal(new URL(worldAddress('a b&c', origin)).searchParams.get('entry'), 'a b&c');
assert.equal(frontDoorAddress(origin), origin + '/');
const preview = new URL(scenePreviewAddress('01a1-shore', origin));
assert.equal(preview.origin, origin);
assert.equal(preview.searchParams.get('entry'), '01a1-shore');
// capture=1 hides the app around the world; livePreview=1 asks for the camera's motion.
assert.equal(preview.searchParams.get('capture'), '1');
assert.equal(preview.searchParams.get('livePreview'), '1');
assert.equal(isScenePreview(preview), true);
assert.equal(isScenePreview(worldAddress('01a1-shore', origin)), false);
assert.equal(isScenePreview(frontDoorAddress(origin)), false);
assert.equal(isScenePreview(origin + '/?entry=x&capture=1'), true);
assert.equal(isScenePreview(origin + '/?entry=x&livePreview=1'), true);
assert.equal(isScenePreview(origin + '/?entry=x&capture=0'), false);

// A capture is shown only while every identity it was taken of still holds.
const entry = { entryId: 'e', worldId: 'w', authoredVersionId: 'v', authoredStateSha256: 's', styleVersionId: 'a' };
const capture = { entry_id: 'e', world_id: 'w', version_id: 'v', authored_state_sha256: 's', style_version_id: 'a', file: 'garden.jpg' };
const catalog = { profile: CAPTURE_CATALOG_PROFILE, captures: [capture] };
assert.equal(capturedPicture(catalog, entry), '/review-world-previews/garden.jpg');
for (const key of ['entryId', 'worldId', 'authoredVersionId', 'authoredStateSha256', 'styleVersionId']) {
  assert.equal(capturedPicture(catalog, { ...entry, [key]: 'other' }), null, key);
}
assert.equal(capturedPicture({ captures: [] }, entry), null);
assert.equal(capturedPicture(undefined, entry), null);

// A catalog is refused whole when a capture names no picture file or lacks an identity.
assert.deepEqual(checkedCaptureCatalog({ ...catalog, captures: [{ ...capture, basis: 'kept private' }] }), catalog);
assert.throws(() => checkedCaptureCatalog({ profile: 'other', captures: [] }), /not a capture catalog/u);
for (const file of ['../garden.jpg', 'nested/garden.jpg', 'garden.html', '.hidden.jpg', '']) {
  assert.throws(() => checkedCaptureCatalog({ ...catalog, captures: [{ ...capture, file }] }), /no picture or no identity/u, file);
}
assert.throws(() => checkedCaptureCatalog({ ...catalog, captures: [{ ...capture, style_version_id: '' }] }), /no picture or no identity/u);

// The page receives the checked catalog as a module, and nothing else under that name.
const hooks = capturesModule(catalog);
const id = hooks.resolveId('virtual:front-door-captures');
assert.equal(hooks.resolveId('./front-door.ts'), null);
assert.equal(hooks.load(id), `export default ${JSON.stringify(catalog)};\n`);
assert.equal(hooks.load('virtual:front-door-captures'), null);

/** A response as the middleware sees one; what is piped into it is kept as `received`. */
function response() {
  const res = new Writable({ write(chunk, _encoding, done) { res.received += chunk; done(); } });
  Object.assign(res, { statusCode: 200, headers: {}, body: null, received: '' });
  res.setHeader = (key, value) => { res.headers[key] = value; };
  const finish = res.end.bind(res);
  res.end = (value) => { if (value !== undefined && value !== null) res.body = value; return finish(); };
  return res;
}

// A scene preview only reads; any other page's requests pass to the app as before.
const previewPage = scenePreviewAddress('e', origin);
for (const method of ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE']) {
  for (const referer of [previewPage, worldAddress('e', origin), frontDoorAddress(origin), undefined]) {
    let passed = 0;
    const res = response();
    scenePreviewWriteGuard({ method, headers: referer === undefined ? {} : { referer } }, res, () => { passed++; });
    const refused = referer === previewPage && method !== 'GET' && method !== 'HEAD';
    assert.equal(passed, refused ? 0 : 1, `${method} from ${referer}`);
    if (refused) {
      assert.equal(res.statusCode, 405);
      assert.equal(res.headers.Allow, 'GET, HEAD');
      assert.equal(JSON.parse(res.body).detail, 'The world preview is read-only.');
    }
  }
}

// Only the catalog's own pictures are served from the private directory.
const directory = mkdtempSync(join(tmpdir(), 'front-door-'));
try {
  writeFileSync(join(directory, 'garden.jpg'), 'picture');
  writeFileSync(join(directory, 'secret.jpg'), 'not listed');
  const serve = capturePictures(catalog, directory);
  const status = async (method, url, from = serve) => {
    const res = response();
    const finished = new Promise(resolve => res.on('finish', resolve));
    from({ method, url }, res);
    await finished;
    return res;
  };
  const served = await status('GET', '/garden.jpg');
  assert.equal(served.statusCode, 200);
  assert.equal(served.headers['Content-Type'], 'image/jpeg');
  assert.equal(served.received, 'picture');
  assert.equal((await status('HEAD', '/garden.jpg')).statusCode, 200);
  for (const [method, url] of [['GET', '/secret.jpg'], ['GET', '/..%2Fsecret.jpg'], ['GET', '/catalog.json'], ['POST', '/garden.jpg']]) {
    const refused = await status(method, url);
    assert.equal(refused.statusCode, 404, `${method} ${url}`);
    assert.equal(refused.received, '', `${method} ${url}`);
  }
  assert.equal((await status('GET', '/garden.jpg', capturePictures(catalog, null))).statusCode, 404);
} finally {
  rmSync(directory, { recursive: true, force: true });
}

const result = { verified_at_utc: new Date().toISOString(), pass: true, scope: 'Front door addresses, capture identity matching, catalog checks, served pictures and the scene preview read-only guard. Mocked request/response boundary; no server started.' };
console.log(JSON.stringify(result));
