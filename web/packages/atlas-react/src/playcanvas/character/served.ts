/**
 * Character catalogs as the host serves them, held per application.
 *
 * The host publishes each catalog as one canonical document named by its SHA-256
 * (`GET /world/character-catalogs/{digest}`); nothing about people is compiled into this bundle.
 * A served document is believed only after its bytes hash to the digest it was asked for and it
 * passes the same rules its kind's validator applies, so a catalog the host publishes reaches the
 * page as data and a new option or family needs no rebuild.
 *
 * Two kinds are read, each by a fixed reader chosen by the document's profile: layered people
 * (a catalog and its designed looks) and parametric bodies (declared controls whose bodies are
 * prepared per recipe). The current layered catalog that declares the inhabitant draw domain is the
 * one the player's default look and every inhabitant are drawn from, so both always agree.
 */
import type * as pc from 'playcanvas';
import { validateCharacterCatalog, type CharacterCatalog } from './catalog.js';
import { sha256Hex } from './digest.js';
import { validateDesignedLooks, type DesignedLooks } from './look.js';
import { validateParametricCatalog, type ParametricCatalog } from './parametric.js';

export const LAYERED_PROFILE = 'exulanica.character-catalog-bundle/v1';
export const PARAMETRIC_PROFILE = 'exulanica.parametric-character-catalog/v1';
/** The draw domain inhabitants' looks come from, as the population profile names it. */
export const INHABITANT_DRAW_DOMAIN = 'street-population/v1';

/** One entry of `GET /world/character-catalogs`, as the host lists a publication. */
export interface CatalogPublicationEntry {
  readonly catalog_sha256: string;
  readonly catalog_id: string;
  readonly revision: number;
  readonly profile: string;
  readonly kind: string;
  readonly state: 'current' | 'retained';
}

interface ServedIdentity {
  readonly catalogSha256: string;
  readonly catalogId: string;
  readonly revision: number;
  readonly state: 'current' | 'retained';
}

export interface ServedLayeredCatalog extends ServedIdentity {
  readonly kind: 'layered-people';
  readonly catalog: CharacterCatalog;
  readonly looks: DesignedLooks;
}

export interface ServedParametricCatalog extends ServedIdentity {
  readonly kind: 'parametric-body';
  readonly document: ParametricCatalog;
}

export type ServedCharacterCatalog = ServedLayeredCatalog | ServedParametricCatalog;

function refuse(why: string): never {
  throw new TypeError(`Served character catalog: ${why}`);
}

/**
 * A served publication from its exact bytes, or a refusal: bytes that do not hash to the digest
 * the entry names, a profile no reader knows, an identity the document does not state, or a
 * document its kind's rules refuse.
 */
export function readServedCatalog(entry: CatalogPublicationEntry, bytes: Uint8Array): ServedCharacterCatalog {
  if (!/^[0-9a-f]{64}$/.test(entry.catalog_sha256)) refuse('the digest is malformed');
  if (sha256Hex(bytes) !== entry.catalog_sha256) refuse(`${entry.catalog_id} bytes do not hash to ${entry.catalog_sha256}`);
  let document: { readonly profile?: unknown; readonly [key: string]: unknown };
  try {
    document = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) as typeof document;
  } catch {
    return refuse('the document is not JSON');
  }
  const identity = { catalogSha256: entry.catalog_sha256, catalogId: entry.catalog_id, revision: entry.revision, state: entry.state };
  if (document.profile === LAYERED_PROFILE && entry.kind === 'layered-people') {
    const catalog = validateCharacterCatalog(document.catalog as CharacterCatalog);
    const looks = validateDesignedLooks(catalog, document.looks as DesignedLooks);
    if (catalog.catalogId !== entry.catalog_id || catalog.revision !== entry.revision) refuse('the document names another catalog or revision');
    return { kind: 'layered-people', ...identity, catalog, looks };
  }
  if (document.profile === PARAMETRIC_PROFILE && entry.kind === 'parametric-body') {
    const parsed = validateParametricCatalog(document as unknown as ParametricCatalog);
    if (parsed.catalogId !== entry.catalog_id || parsed.revision !== entry.revision) refuse('the document names another catalog or revision');
    return { kind: 'parametric-body', ...identity, document: parsed };
  }
  return refuse(`no reader for profile ${String(document.profile)} as ${entry.kind}`);
}

const APPLICATIONS = new WeakMap<pc.AppBase, CharacterCatalogs>();

/** The served catalogs one application holds, by digest, and the ones it draws people from. */
export class CharacterCatalogs {
  private readonly served = new Map<string, ServedCharacterCatalog>();
  private readonly listeners = new Set<() => void>();

  static forApp(app: pc.AppBase): CharacterCatalogs {
    let catalogs = APPLICATIONS.get(app);
    if (!catalogs) APPLICATIONS.set(app, (catalogs = new CharacterCatalogs()));
    return catalogs;
  }

  /** Hold a served catalog. Holding the same digest again changes nothing. */
  add(catalog: ServedCharacterCatalog): void {
    const held = this.served.get(catalog.catalogSha256);
    if (held && held.state === catalog.state) return;
    this.served.set(catalog.catalogSha256, catalog);
    for (const listener of [...this.listeners]) listener();
  }

  byDigest(catalogSha256: string): ServedCharacterCatalog | null {
    return this.served.get(catalogSha256) ?? null;
  }

  /**
   * The current layered catalog whose population declares the inhabitant draw domain: what the
   * player's default and every inhabitant are drawn from. Null until the host has served one.
   */
  get people(): ServedLayeredCatalog | null {
    let chosen: ServedLayeredCatalog | null = null;
    for (const catalog of this.served.values()) {
      if (catalog.kind !== 'layered-people' || catalog.state !== 'current') continue;
      if (!catalog.catalog.population.some((profile) => profile.domain === INHABITANT_DRAW_DOMAIN)) continue;
      if (chosen === null || catalog.catalogId < chosen.catalogId) chosen = catalog;
    }
    return chosen;
  }

  /** Every current parametric catalog, by catalog id. */
  get parametric(): readonly ServedParametricCatalog[] {
    return [...this.served.values()]
      .filter((catalog): catalog is ServedParametricCatalog => catalog.kind === 'parametric-body' && catalog.state === 'current')
      .sort((a, b) => (a.catalogId < b.catalogId ? -1 : a.catalogId > b.catalogId ? 1 : 0));
  }

  /** Called whenever a catalog is added; returns its unsubscription. */
  onChange(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}
