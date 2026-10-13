import type { SavedWorldEntry } from '../world-entry-api.js';
import type { AlternateVersion } from '../world-objects-api.js';

/** A mount loses its proof as soon as either authored client observes another source or state. */
export function holdTerrainVersion(entry: SavedWorldEntry | null): {
  readonly observe: (version: AlternateVersion | null) => void;
  readonly current: () => boolean;
} {
  let current = true;
  return Object.freeze({
    observe(version: AlternateVersion | null): void {
      if (entry?.generatedTerrain != null && (version === null || version.worldId !== entry.worldId
          || version.versionId !== entry.authoredVersionId || version.stateSha256 !== entry.authoredStateSha256
          || version.editSeq !== entry.authoredEditSeq
          || version.sourceSnapshotId !== entry.sourceSnapshotId || version.sourceInvalidated)) current = false;
    },
    current: () => current,
  });
}

import type { TerrainOccupancyProof } from '@exulanica/atlas-core';

export const TERRAIN_PROOF_LEASE_MS = 5000;
export const TERRAIN_PROOF_REFRESH_MS = 2000;
export const TERRAIN_PROOF_TIMEOUT_MS = 1500;
export interface TerrainOccupancyLease {
  readonly read: () => TerrainOccupancyProof;
  readonly attach: () => () => void;
}

/** A bounded read-time lease. Expiry or a failed observation requires a fresh mount. */
export async function holdTerrainOccupancy(
  readProof: (signal: AbortSignal) => Promise<TerrainOccupancyProof>,
  currentSource: () => boolean,
): Promise<TerrainOccupancyLease> {
  const unavailable: TerrainOccupancyProof = Object.freeze({status: 'unavailable'});
  let held: TerrainOccupancyProof = unavailable, expires = Infinity, revoked = false, users = 0, generation = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | null = null;
  const stop = (): void => { if (timer !== undefined) clearTimeout(timer); timer = undefined; };
  const revoke = (): void => { revoked = true; held = unavailable; stop(); controller?.abort(); };
  const read = (): TerrainOccupancyProof => {
    if (!currentSource() || performance.now() >= expires) revoke();
    return revoked ? unavailable : held;
  };
  const refresh = async (): Promise<void> => {
    if (revoked || !currentSource()) { revoke(); return; }
    const serial = generation, request = new AbortController(); controller = request;
    let deadline: ReturnType<typeof setTimeout> | undefined;
    let aborted: (() => void) | undefined;
    try {
      const timeout = new Promise<TerrainOccupancyProof>(resolve => {
        aborted = () => { if (deadline !== undefined) clearTimeout(deadline); resolve(unavailable); };
        request.signal.addEventListener('abort', aborted, {once: true});
        deadline = setTimeout(() => { if (serial === generation) revoke(); resolve(unavailable); }, TERRAIN_PROOF_TIMEOUT_MS);
      });
      const proof = await Promise.race([readProof(request.signal), timeout]);
      if (serial !== generation) return;
      if (revoked || !currentSource() || performance.now() >= expires || proof.status !== 'verified') { revoke(); return; }
      held = proof; expires = performance.now() + TERRAIN_PROOF_LEASE_MS;
    } catch { if (serial === generation) revoke(); }
    finally { if (aborted !== undefined) request.signal.removeEventListener('abort', aborted); if (deadline !== undefined) clearTimeout(deadline); if (controller === request) controller = null; }
  };
  const schedule = (): void => {
    if (users === 0 || revoked || timer !== undefined) return;
    timer = setTimeout(() => { timer = undefined; void refresh().then(schedule); }, TERRAIN_PROOF_REFRESH_MS);
  };
  await refresh();
  return Object.freeze({read, attach(): () => void {
    read(); users += 1;
    if (users === 1) schedule();
    let disposed = false;
    return () => { if (disposed) return; disposed = true; users -= 1;
      if (users === 0) { generation += 1; stop(); controller?.abort(); controller = null; }
    };
  }});
}
