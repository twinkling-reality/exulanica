/**
 * Rebuild the landing package and compare it, file by file, with what the public origin serves.
 *
 * The public site is deployed by hand from a local build, and the waitlist endpoint reaches the
 * bundle from the environment rather than from any file in `src/`. Those two facts together mean a
 * well-meaning rebuild can ship a page that looks correct and quietly collects nothing, so the
 * question "does what I have here still produce what is live" has to be answerable mechanically
 * rather than from memory. This answers it.
 *
 *   VITE_WAITLIST_URL=... pnpm run landing:verify
 *
 * A mismatch is not by itself a fault. It says the working tree and the deployment have diverged,
 * and the report names which files differ so the reader can decide which way the divergence should
 * be resolved. Run it before deploying, and read it as the thing that decides whether the deploy is
 * a republish of something known or a change.
 *
 * **Every asset filename carries a content hash, so a changed file is a file the origin has never
 * heard of.** The deployment answers an unknown path with the index page and a 200 rather than a
 * 404, which is right for a page whose surfaces are hash links and wrong for anything that reads
 * the status alone: an earlier version of this script reported a bundle the origin does not hold as
 * a 2,874 byte content mismatch, which is the size of the index page and says nothing about the
 * bundle. The content type therefore decides whether a file was served, and the report separates
 * "the origin does not have this" from "the origin has a different version of this", because those
 * two send the reader to different places.
 */
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const ORIGIN = process.env.LANDING_ORIGIN ?? 'https://exulanica.com';
const PACKAGE = new URL('../packages/landing/', import.meta.url).pathname;
const DIST = join(PACKAGE, 'dist');

/*
 * There is no default for the endpoint here, for the same reason `resolveWaitlistDestination` has
 * none: a build without it is a valid build of a page whose waitlist is shut, and comparing one of
 * those against a live page whose waitlist is open reports a mismatch whose cause is this variable
 * rather than anything in the source. Refusing is the only answer that cannot mislead.
 */
const waitlist = process.env.VITE_WAITLIST_URL?.trim();
if (!waitlist) {
  console.error(
    'VITE_WAITLIST_URL is not set. A build without it resolves the waitlist to nothing and shuts\n' +
      'the field, so its bundle cannot match a deployment whose waitlist is open. Set it to the\n' +
      'endpoint the deployment uses and run this again.',
  );
  process.exit(2);
}

function sha256(bytes: Buffer): string {
  return createHash('sha256').update(bytes).digest('hex');
}

function builtFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...builtFiles(full));
    else out.push(relative(DIST, full));
  }
  return out.sort();
}

console.log(`building with VITE_WAITLIST_URL=${waitlist}`);
console.log(`  and VITE_ATLAS_URL=${process.env.VITE_ATLAS_URL ?? '(unset)'}`);
execFileSync('pnpm', ['run', 'landing:build'], {
  cwd: new URL('..', import.meta.url).pathname,
  stdio: 'inherit',
  env: process.env,
});

const files = builtFiles(DIST).filter((f) => !f.endsWith('.map'));
if (files.length === 0) throw new Error(`the build produced no files in ${DIST}`);

/*
 * Assert the fetched page is the application before comparing anything to it. A Cloudflare error
 * page, a parked domain or a redirect all return bytes, and every one of them would differ from the
 * build in a way that reads like a source divergence.
 */
const indexResponse = await fetch(`${ORIGIN}/`, { redirect: 'follow' });
if (!indexResponse.ok) throw new Error(`${ORIGIN}/ answered ${indexResponse.status}`);
const liveIndex = Buffer.from(await indexResponse.arrayBuffer());
const bundleReference = /<script[^>]+src="(\/assets\/[^"]+\.js)"/.exec(liveIndex.toString('utf8'));
if (!bundleReference) {
  throw new Error(
    `${ORIGIN}/ did not serve a page referencing a built bundle, so there is nothing here to ` +
      'compare against. Check what that origin is actually serving before reading any verdict.',
  );
}

/** What the origin must answer with for a file of this kind to have been served at all. */
const EXPECTED_TYPE: Readonly<Record<string, string>> = Object.freeze({
  '.html': 'text/html',
  '.js': 'javascript',
  '.css': 'text/css',
  '.png': 'image/png',
  '.svg': 'image/svg',
  '.webmanifest': 'manifest',
  '.json': 'json',
  '.ico': 'image/',
  '.txt': 'text/plain',
});

const same: string[] = [];
const differs: string[] = [];
const absent: string[] = [];
for (const file of files) {
  const built = readFileSync(join(DIST, file));
  const response = await fetch(`${ORIGIN}/${file}`);
  const extension = file.slice(file.lastIndexOf('.'));
  const expected = EXPECTED_TYPE[extension];
  const served = Buffer.from(await response.arrayBuffer());
  const type = response.headers.get('content-type') ?? '';
  if (!response.ok) {
    absent.push(`${file} (${ORIGIN} answered ${response.status})`);
  } else if (expected !== undefined && !type.includes(expected)) {
    absent.push(`${file} (answered 200 with ${type || 'no content type'}, not ${expected})`);
  } else if (sha256(built) === sha256(served)) {
    same.push(file);
  } else {
    differs.push(`${file} (built ${built.length} bytes, served ${served.length} bytes)`);
  }
}

/*
 * The other direction. A hashed asset the origin holds and this tree no longer produces is
 * invisible to the loop above, and it is the signature of a deployment made from a source state
 * that is not this one, which is the case this script exists to name.
 */
const builtPaths = new Set(files.map((f) => `/${f}`));
const referenced = [...liveIndex.toString('utf8').matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map(
  (m) => m[1],
);
const stale = referenced.filter((r) => !builtPaths.has(r));

console.log(`\ncomparing ${files.length} built files against ${ORIGIN}`);
for (const file of same) console.log(`  same           ${file}`);
for (const file of differs) console.log(`  DIFFERS        ${file}`);
for (const file of absent) console.log(`  NOT DEPLOYED   ${file}`);
for (const file of stale) console.log(`  ONLY DEPLOYED  ${file} (the live page loads this and this tree does not build it)`);

const reproduced = differs.length === 0 && absent.length === 0 && stale.length === 0;
console.log(
  reproduced
    ? `\nThis tree rebuilds ${ORIGIN} exactly. A deploy from here republishes what is already live.`
    : `\nThis tree does NOT rebuild ${ORIGIN}. ${differs.length} file(s) differ, ` +
        `${absent.length} are not deployed, ${stale.length} are deployed and not built here. ` +
        'A deploy from here would change the site.',
);
process.exit(reproduced ? 0 : 1);
