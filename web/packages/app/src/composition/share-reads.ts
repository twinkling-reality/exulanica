/**
 * Reads that open a world, within the workspace's request share.
 *
 * The server admits a workspace's requests up to its share and answers the rest 429
 * `workspace_capacity_exhausted` with a `Retry-After` (exulanica/api/admission.py). A world opens
 * through many reads at once (its drawing, its landscape, every land chunk, every tile's bytes), so
 * left alone they pass the share on a busy server while a quiet one never sees it. Here at most
 * `MOST_IN_FLIGHT` of them are asked at a time, and one the server still turns away for its share
 * is asked again after the seconds it states, a second at least, for as long as the caller's own
 * wait allows; past it, the 429 is the answer and the caller refuses by name as before.
 */

/** The most world-opening reads asked at once, well under any workspace's share. */
export const MOST_IN_FLIGHT = 4;
/** How long a read the share turns away is asked again when its caller states no wait of its own. */
export const SHARE_WAIT_MS = 30_000;

let inFlight = 0;
const queued: (() => void)[] = [];

async function turn(): Promise<() => void> {
  if (inFlight >= MOST_IN_FLIGHT) await new Promise<void>((go) => { queued.push(go); });
  inFlight += 1;
  let done = false;
  return () => {
    if (done) return;
    done = true;
    inFlight -= 1;
    queued.shift()?.();
  };
}

/**
 * `fetch(input, init)` in its turn among the world-opening reads, asked again while the server turns
 * it away for the workspace's share (429) and the wait it states still ends before `until`.
 */
export async function readWithinShare(input: string, init: RequestInit, until: number = Date.now() + SHARE_WAIT_MS): Promise<Response> {
  for (;;) {
    const release = await turn();
    let response: Response;
    try {
      response = await fetch(input, init);
    } finally {
      release();
    }
    if (response.status !== 429) return response;
    const stated = Number(response.headers.get('Retry-After') ?? Number.NaN);
    const ms = Math.max(1, Number.isFinite(stated) ? stated : 1) * 1000;
    if (Date.now() + ms > until) return response;
    await response.body?.cancel().catch(() => {});
    await new Promise((done) => { setTimeout(done, ms); });
  }
}
