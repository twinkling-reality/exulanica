/** Pilot viewers read the copied records; execution stays with the bounded driver. */
export function observerRequestGuard(req, res, next) {
  if (req.method === 'GET' || req.method === 'HEAD') { next(); return; }
  res.statusCode = 405;
  res.setHeader('Allow', 'GET, HEAD');
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify({ detail: 'This viewer can only read world records.' }));
}
