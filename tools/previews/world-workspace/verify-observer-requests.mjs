import assert from 'node:assert/strict';
import { observerRequestGuard } from './observer-request-guard.mjs';

for (const method of ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']) {
  let calls = 0, body = null;
  const headers = {};
  const response = { statusCode: 200, setHeader: (key, value) => { headers[key] = value; }, end: value => { body = value; } };
  observerRequestGuard({ method }, response, () => { calls++; });
  if (method === 'GET' || method === 'HEAD') { assert.equal(calls, 1); assert.equal(body, null); }
  else { assert.equal(calls, 0); assert.equal(response.statusCode, 405); assert.equal(headers.Allow, 'GET, HEAD'); assert.equal(JSON.parse(body).detail, 'This viewer can only read world records.'); }
}
const result = { verified_at_utc: new Date().toISOString(), pass: true, scope: 'Observer API middleware passes only GET/HEAD and stops unsafe verbs before native proxy dispatch. Mocked request/response boundary; no observer runtime launched.' };
console.log(JSON.stringify(result));
