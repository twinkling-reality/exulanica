import type { SiteDrawing } from '@exulanica/atlas-react/generated-site';
import type { PlacedThingRecord, PlacedThingSupportReference } from '@exulanica/atlas-react/things';
import type { AlternateVersion } from '../world-objects-api.js';
import type { ThingSupportAvailability } from '../thing-support-api.js';

export const SUPPORT_LEASE_MS = 5000;
export const SUPPORT_REFRESH_MS = 2000;
export const SUPPORT_TIMEOUT_MS = 1500;
export const SUPPORT_READ_CONCURRENCY = 4;
const versionKey = (v: AlternateVersion): string => [v.worldId, v.versionId, v.sourceSnapshotId, v.stateSha256, v.editSeq, v.sourceInvalidated].join('|');
const observationKey = (v: AlternateVersion): string => `${versionKey(v)}|${JSON.stringify((v.things ?? []).filter(t => t.gone).map(t => t.thingId).sort())}`;
const sameReference = (a: PlacedThingSupportReference, b: PlacedThingSupportReference): boolean =>
  a.profile === b.profile && a.worldId === b.worldId && a.sourceSnapshotId === b.sourceSnapshotId
  && a.receiptSha256 === b.receiptSha256 && a.networkSha256 === b.networkSha256
  && a.regionId === b.regionId && a.surfaceId === b.surfaceId;
const sameThing = (a: PlacedThingRecord, b: PlacedThingRecord): boolean => a.thingId === b.thingId
  && a.regionId === b.regionId && !a.removed && !b.removed && JSON.stringify(a.kind) === JSON.stringify(b.kind)
  && a.support !== undefined && b.support !== undefined && sameReference(a.support, b.support)
  && a.transform.xMm === b.transform.xMm && a.transform.yMm === b.transform.yMm && a.transform.zMm === b.transform.zMm
  && a.transform.yawMicroradians === b.transform.yawMicroradians && a.transform.scaleMilli === b.transform.scaleMilli;

/** One mounted page's two authored clients report before awaiting their paint callbacks. */
export function observeSupportVersions() {
  let observed: AlternateVersion | null | undefined;
  let latest: AlternateVersion | null = null;
  const listeners = new Set<() => void>();
  return Object.freeze({
    observe(version: AlternateVersion | null): void {
      // A late read from the other client cannot reverse an already observed edit, even after a failed read.
      if (version !== null && latest !== null && version.versionId === latest.versionId) {
        if (version.editSeq < latest.editSeq) return;
        if (latest.sourceInvalidated) return;
        if (version.editSeq === latest.editSeq && (latest.things ?? []).some(t => t.gone
            && !(version!.things ?? []).some(next => next.thingId === t.thingId && next.gone))) return;
        if (version.editSeq === latest.editSeq && !version.sourceInvalidated && versionKey(version) !== versionKey(latest)) version = null;
      }
      if (version !== null) latest = version;
      const changed = observed === undefined || (observed === null ? version !== null
        : version === null || observationKey(observed) !== observationKey(version));
      observed = version;
      if (changed) for (const listen of listeners) listen();
    },
    matches(version: AlternateVersion): boolean { return observed === undefined || (observed !== null && observationKey(observed) === observationKey(version)); },
    subscribe(listen: () => void): () => void { listeners.add(listen); return () => { listeners.delete(listen); }; },
  });
}
export type SupportVersionObservations = ReturnType<typeof observeSupportVersions>;

/** Check source identity and height, without turning a person navigation envelope into an object test. */
export function supportMatchesSource(thing: PlacedThingRecord, version: AlternateVersion, drawing: SiteDrawing | null): boolean {
  const support = thing.support;
  if (support === undefined || thing.removed || version.sourceInvalidated || drawing?.profile !== 'exulanica.site-drawing/v2'
      || drawing.support === undefined || support.worldId !== version.worldId || drawing.worldId !== version.worldId
      || support.sourceSnapshotId !== version.sourceSnapshotId || support.regionId !== thing.regionId
      || support.regionId !== drawing.support.document.frame.name || support.receiptSha256 !== drawing.receiptSha256
      || support.networkSha256 !== drawing.support.document.document_sha256 || thing.transform.scaleMilli !== 1000) return false;
  const surface = drawing.support.surfaces.get(support.surfaceId);
  return surface !== undefined && thing.transform.yMm === surface.support_z_mm;
}

/** Per-item read-time availability, scoped to one mounted source. It grants no navigation authority. */
export function holdSupportedThings(options: {
  readonly read: (versionId: string, thingId: string, signal: AbortSignal) => Promise<ThingSupportAvailability>;
  readonly source: () => SiteDrawing | null;
  readonly versions: SupportVersionObservations;
  readonly changed: () => void;
}) {
  let version: AlternateVersion | null = null, drawing: SiteDrawing | null = null, generation = 0, disposed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const requests = new Set<AbortController>();
  const grants = new Map<string, {thing: PlacedThingRecord; expires: number; timer: ReturnType<typeof setTimeout>}>();
  const clear = (): void => {
    generation += 1;
    if (timer !== undefined) clearTimeout(timer); timer = undefined;
    for (const request of requests) request.abort(); requests.clear();
    for (const grant of grants.values()) clearTimeout(grant.timer); grants.clear();
    options.changed();
  };
  const current = (): boolean => !disposed && version !== null && !version.sourceInvalidated
    && options.versions.matches(version) && drawing !== null && options.source() === drawing;
  const stopObserving = options.versions.subscribe(() => {
    if (!current()) { clear(); version = null; drawing = null; }
  });
  const forget = (id: string): void => {
    const held = grants.get(id); if (held !== undefined) { clearTimeout(held.timer); grants.delete(id); options.changed(); }
  };
  async function readOne(thing: PlacedThingRecord, serial: number, askedVersion: AlternateVersion): Promise<void> {
    if (serial !== generation || !current()) return;
    const started = performance.now(), controller = new AbortController(); requests.add(controller);
    let timeout: ReturnType<typeof setTimeout> | undefined;
    let aborted: (() => void) | undefined;
    try {
      const cancelled = new Promise<null>(resolve => {
        aborted = () => resolve(null); controller.signal.addEventListener('abort', aborted, {once: true});
        timeout = setTimeout(() => { controller.abort(); resolve(null); }, SUPPORT_TIMEOUT_MS);
      });
      const answer = await Promise.race([options.read(askedVersion.versionId, thing.thingId, controller.signal), cancelled]);
      if (serial !== generation || !current()) return;
      if (answer === null || performance.now() >= started + SUPPORT_LEASE_MS || answer.availability !== 'available'
          || answer.versionId !== askedVersion.versionId || answer.stateSha256 !== askedVersion.stateSha256
          || answer.thingId !== thing.thingId || answer.support === null || !sameReference(answer.support, thing.support!)) {
        forget(thing.thingId); return;
      }
      const old = grants.get(thing.thingId); if (old !== undefined) clearTimeout(old.timer);
      const expires = started + SUPPORT_LEASE_MS;
      const expiry = setTimeout(() => { if (serial === generation) forget(thing.thingId); }, Math.max(0, expires - performance.now()));
      grants.set(thing.thingId, {thing, expires, timer: expiry}); options.changed();
    } catch { if (serial === generation) forget(thing.thingId); }
    finally {
      if (timeout !== undefined) clearTimeout(timeout);
      if (aborted !== undefined) controller.signal.removeEventListener('abort', aborted);
      requests.delete(controller);
    }
  }
  async function refresh(serial: number): Promise<void> {
    if (serial !== generation || !current()) return;
    const requested = version!;
    const things = (requested.things ?? []).filter(t => t.support !== undefined && !t.gone && supportMatchesSource(t, requested, drawing));
    if (things.length === 0) return;
    let cursor = 0;
    await Promise.all(Array.from({length: Math.min(SUPPORT_READ_CONCURRENCY, things.length)}, async () => {
      while (serial === generation && current() && cursor < things.length) await readOne(things[cursor++]!, serial, requested);
    }));
    if (serial === generation && current()) timer = setTimeout(() => { timer = undefined; void refresh(serial); }, SUPPORT_REFRESH_MS);
  }
  return Object.freeze({
    setVersion(next: AlternateVersion | null): void {
      const source = options.source();
      if (version !== null && next !== null && observationKey(version) === observationKey(next) && source === drawing) return;
      clear(); version = next; drawing = source; void refresh(generation);
    },
    available(thing: PlacedThingRecord): boolean {
      const grant = grants.get(thing.thingId);
      return current() && grant !== undefined && performance.now() < grant.expires && sameThing(thing, grant.thing)
        && supportMatchesSource(thing, version!, drawing);
    },
    destroy(): void { disposed = true; stopObserving(); clear(); version = null; drawing = null; },
  });
}
