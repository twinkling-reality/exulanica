/**
 * The host's thing library, as the drawing reads it: kinds, looks, the body plans and every look's
 * container, each fetched by the SHA-256 of its bytes and held to it before it is read.
 *
 * The page names nothing by path: the list (`exulanica.thing-library/v1`) names every document by
 * digest, and the caller's `bytes` fetches one digest from the host
 * (`GET /things/library/{content_sha256}`) with the page's own credentials. Every answer is hashed
 * here again and refused by name when it is not the digest asked for, so a substituted or truncated
 * answer is never parsed. Answers are kept by digest for the page's life: a digest names the same
 * bytes for ever.
 *
 * A kind or look the shipped list does not hold may be one the workspace keeps (its own thing store,
 * `HeldThings`): asked by the same digest, held to it the same way, and its document must name the
 * key and version asked for. A held look's container is fetched by the look's digest and held to
 * the container digest the look's own document names.
 */

import {
  readBodyPlans,
  readKindDrawing,
  readLookDrawing,
  type ContainerReference,
  type KindDrawing,
  type LibraryKind,
  type LibraryLook,
  type LookDrawing,
  type ThingLibraryList,
} from './documents.js';
import type { BodyPlanEntry } from './skeleton.js';

/** Fetch one digest's bytes from the host; `expectedBytes` is the length the list states, if any. */
export type LibraryBytes = (sha256: string, expectedBytes: number | null) => Promise<ArrayBuffer>;

/**
 * The kinds and looks a workspace keeps for itself, each by the SHA-256 of its document; null where
 * the workspace holds none at that digest (absent, withdrawn or another workspace's).
 */
export interface HeldThings {
  kind(sha256: string): Promise<ArrayBuffer | null>;
  look(sha256: string): Promise<ArrayBuffer | null>;
  /** A held look's container, by the look's digest. */
  container(lookSha256: string): Promise<ArrayBuffer | null>;
}

export type LibraryRefusal = 'not_in_library' | 'digest_mismatch' | 'length_mismatch' | 'no_digest_check';

export class LibraryRefused extends Error {
  override readonly name = 'LibraryRefused';
  constructor(readonly reason: LibraryRefusal, message: string) {
    super(message);
  }
}

/** A kind or look reference as a placed thing or a kind names it. */
export interface Named {
  readonly key: string;
  readonly version: number;
  readonly sha256: string;
}

const hex = (digest: ArrayBuffer): string => [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');

export class ThingLibrary {
  private readonly kinds = new Map<string, LibraryKind>();
  private readonly looks = new Map<string, LibraryLook>();
  private readonly held = new Map<string, Promise<ArrayBuffer>>();
  private plans: Promise<ReadonlyMap<string, BodyPlanEntry>> | null = null;
  /** Each held look's container digest, to the look digest its container is fetched by. */
  private readonly heldContainers = new Map<string, string>();

  constructor(readonly list: ThingLibraryList, private readonly bytes: LibraryBytes, private readonly heldThings: HeldThings | null = null) {
    for (const kind of list.kinds) this.kinds.set(`${kind.kind}/${kind.version}`, kind);
    for (const look of list.looks) this.looks.set(`${look.look}/${look.version}`, look);
  }

  /** The library's entry for a kind, at exactly that digest. */
  kindEntry(named: Named): LibraryKind {
    const entry = this.kinds.get(`${named.key}/${named.version}`);
    if (entry === undefined || entry.sha256 !== named.sha256) {
      throw new LibraryRefused('not_in_library', `The library holds no kind ${named.key} version ${named.version} at that digest.`);
    }
    return entry;
  }

  /** The library's entry for a look, at exactly that digest. */
  lookEntry(named: Named): LibraryLook {
    const entry = this.looks.get(`${named.key}/${named.version}`);
    if (entry === undefined || entry.sha256 !== named.sha256) {
      throw new LibraryRefused('not_in_library', `The library holds no look ${named.key} version ${named.version} at that digest.`);
    }
    return entry;
  }

  /** Every look of the library that fits `bodyPlan`, for a look choice. */
  looksFor(bodyPlan: string): readonly LibraryLook[] {
    return [...this.looks.values()].filter((look) => look.bodyPlan === bodyPlan);
  }

  async kind(named: Named): Promise<KindDrawing> {
    return readKindDrawing(await this.kindDocument(named));
  }

  async look(named: Named): Promise<LookDrawing> {
    const drawing = readLookDrawing(await this.lookDocument(named));
    if (drawing.container !== null && !this.shipped(this.looks, named)) this.heldContainers.set(drawing.container.sha256, named.sha256);
    return drawing;
  }

  /**
   * A kind's whole document as its canonical JSON, held to its digest, for a reader that needs more
   * than drawing does (the thing card: its summary, abilities and origin).
   */
  async kindDocument(named: Named): Promise<unknown> {
    if (this.shipped(this.kinds, named)) return this.json(named.sha256);
    return this.heldDocument(named, 'kind', (sha256) => this.heldThings!.kind(sha256));
  }

  /** A look's whole document as its canonical JSON, held to its digest (the card reads its origin). */
  async lookDocument(named: Named): Promise<unknown> {
    if (this.shipped(this.looks, named)) return this.json(named.sha256);
    return this.heldDocument(named, 'look', (sha256) => this.heldThings!.look(sha256));
  }

  private shipped(entries: ReadonlyMap<string, { readonly sha256: string }>, named: Named): boolean {
    return entries.get(`${named.key}/${named.version}`)?.sha256 === named.sha256;
  }

  /** A document the workspace keeps, held to its digest and to the key and version it was asked by. */
  private async heldDocument(named: Named, field: 'kind' | 'look', get: (sha256: string) => Promise<ArrayBuffer | null>): Promise<unknown> {
    const refused = () => new LibraryRefused('not_in_library', `The library holds no ${field} ${named.key} version ${named.version} at that digest.`);
    if (this.heldThings === null) throw refused();
    const document = JSON.parse(new TextDecoder().decode(await this.fetchFrom(named.sha256, null, async () => {
      const bytes = await get(named.sha256);
      if (bytes === null) throw refused();
      return bytes;
    }))) as Record<string, unknown>;
    if (document[field] !== named.key || document['version'] !== named.version) throw refused();
    return document;
  }

  async bodyPlans(): Promise<ReadonlyMap<string, BodyPlanEntry>> {
    this.plans ??= this.json(this.list.bodyPlansSha256).then(readBodyPlans);
    return this.plans;
  }

  async container(reference: ContainerReference): Promise<ArrayBuffer> {
    const look = this.heldContainers.get(reference.sha256);
    if (look === undefined || this.heldThings === null) return this.fetch(reference.sha256, reference.bytes);
    const held = this.heldThings;
    return this.fetchFrom(reference.sha256, reference.bytes, async () => {
      const bytes = await held.container(look);
      if (bytes === null) throw new LibraryRefused('not_in_library', 'The workspace no longer holds that look\'s container.');
      return bytes;
    });
  }

  private async json(sha256: string): Promise<unknown> {
    return JSON.parse(new TextDecoder().decode(await this.fetch(sha256, null)));
  }

  private fetch(sha256: string, length: number | null): Promise<ArrayBuffer> {
    return this.fetchFrom(sha256, length, () => this.bytes(sha256, length));
  }

  /** `sha256`'s bytes from `source`, held to their length and digest, kept for the page's life. */
  private fetchFrom(sha256: string, length: number | null, source: () => Promise<ArrayBuffer>): Promise<ArrayBuffer> {
    let held = this.held.get(sha256);
    if (held === undefined) {
      held = source().then(async (bytes) => {
        if (length !== null && bytes.byteLength !== length) {
          throw new LibraryRefused('length_mismatch', `The library answered ${bytes.byteLength} bytes for a ${length}-byte file.`);
        }
        const subtle = globalThis.crypto?.subtle;
        if (subtle === undefined) throw new LibraryRefused('no_digest_check', 'This page cannot check content digests, so nothing from the library is read.');
        const got = hex(await subtle.digest('SHA-256', bytes));
        if (got !== sha256) throw new LibraryRefused('digest_mismatch', `The library answered other bytes than ${sha256.slice(0, 12)}.`);
        return bytes;
      });
      // A failed answer is not kept: the next ask fetches again.
      held.catch(() => this.held.delete(sha256));
      this.held.set(sha256, held);
    }
    return held;
  }
}
