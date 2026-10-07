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

  constructor(readonly list: ThingLibraryList, private readonly bytes: LibraryBytes) {
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
    this.kindEntry(named);
    return readKindDrawing(await this.json(named.sha256));
  }

  async look(named: Named): Promise<LookDrawing> {
    this.lookEntry(named);
    return readLookDrawing(await this.json(named.sha256));
  }

  async bodyPlans(): Promise<ReadonlyMap<string, BodyPlanEntry>> {
    this.plans ??= this.json(this.list.bodyPlansSha256).then(readBodyPlans);
    return this.plans;
  }

  async container(reference: ContainerReference): Promise<ArrayBuffer> {
    return this.fetch(reference.sha256, reference.bytes);
  }

  private async json(sha256: string): Promise<unknown> {
    return JSON.parse(new TextDecoder().decode(await this.fetch(sha256, null)));
  }

  private fetch(sha256: string, length: number | null): Promise<ArrayBuffer> {
    let held = this.held.get(sha256);
    if (held === undefined) {
      held = this.bytes(sha256, length).then(async (bytes) => {
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
