/**
 * The look a person has chosen, with a revision history they can reset or restore from.
 *
 * Both stores keep the server's revision rules: every save or reset appends a revision, a write
 * names the revision it was based on and is refused if another write came first, and a reset
 * either returns to the default or restores an earlier revision without rewriting history.
 *
 * The preview keeps its history in this browser. A signed-in world keeps catalog looks on the
 * server as recipes over one body's family, per world version (`/world/versions/{version}/characters
 * /avatar/{actor}/appearance?world_id={world}`); the abstract figure and stylized examples are not
 * recipes, so they are worn without being saved there.
 */
import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';
import {
  CHARACTER_CATALOG,
  validateLook,
  type CharacterCatalog,
  type CharacterLook,
} from '@exulanica/atlas-react/playcanvas';
import type { CharacterSelection } from './character-catalog.js';

export type SavedChoice =
  | { readonly kind: 'catalog'; readonly look: CharacterLook }
  | { readonly kind: 'abstract' }
  | { readonly kind: 'stylized'; readonly selection: CharacterSelection };

export interface SavedRevision {
  readonly revision: number;
  readonly operation: 'save' | 'reset';
  readonly restoredFromRevision: number | null;
  readonly choice: SavedChoice;
  readonly savedAt: string;
}

export interface SavedLooks {
  readonly revision: number;
  readonly current: SavedRevision | null;
}

export class StaleLookError extends Error {
  constructor() {
    super('Your look changed somewhere else. Reload it before saving.');
    this.name = 'StaleLookError';
  }
}

export interface LookStore {
  /** Whether this store keeps a choice of this kind; one it does not keep is worn unsaved. */
  keeps(choice: SavedChoice): boolean;
  read(): Promise<SavedLooks>;
  /** Newest first. */
  history(): Promise<readonly SavedRevision[]>;
  save(choice: SavedChoice, baseRevision: number): Promise<SavedLooks>;
  /** Without `restoreRevision`, returns to the default: the designed look for the current body. */
  reset(baseRevision: number, restoreRevision?: number): Promise<SavedLooks>;
}

/** Parameters of the recipe a catalog look saves as, over the family of its body. */
export function recipeParameters(look: CharacterLook): Readonly<Record<string, string | number>> {
  const parameters: Record<string, string | number> = {};
  for (const record of [look.parts, look.materials, look.colours, look.parameters]) {
    for (const [key, value] of Object.entries(record)) parameters[key] = value ?? 'none';
  }
  return parameters;
}

/** The recipe family a look over one body belongs to. */
export function recipeFamilyId(look: CharacterLook): string {
  return `${look.familyId}/${look.baseId}`;
}

/** The look a saved recipe names, validated against the catalog; null when it is not one. */
export function lookFromRecipe(
  catalog: CharacterCatalog,
  familyId: string,
  parameters: Readonly<Record<string, unknown>>,
): CharacterLook | null {
  const cut = familyId.lastIndexOf('/');
  const family = catalog.families.find((candidate) => candidate.familyId === familyId.slice(0, cut));
  if (!family) return null;
  const look = {
    profile: 'exulanica.character-look/v1' as const,
    familyId: family.familyId,
    baseId: familyId.slice(cut + 1),
    parts: {} as Record<string, string | null>,
    materials: {} as Record<string, string>,
    colours: {} as Record<string, string>,
    parameters: {} as Record<string, number>,
  };
  for (const slot of family.slots) {
    const value = parameters[slot.slot];
    if (typeof value !== 'string') return null;
    if (slot.kind === 'part') look.parts[slot.slot] = value === 'none' ? null : value;
    else if (slot.kind === 'material') look.materials[slot.slot] = value;
    else look.colours[slot.slot] = value;
  }
  for (const parameter of family.parameters) {
    const value = parameters[parameter.key];
    if (typeof value !== 'number') return null;
    look.parameters[parameter.key] = value;
  }
  try {
    validateLook(catalog, look);
    return look;
  } catch {
    return null;
  }
}

interface StoredHistory {
  readonly profile: 'exulanica.character-look-history/v1';
  readonly revisions: readonly SavedRevision[];
}

const PREVIEW_KEY = 'exulanica.character-looks.preview/v1';
const HISTORY_LIMIT = 50;

function parseChoice(value: unknown, catalog: CharacterCatalog): SavedChoice | null {
  if (!value || typeof value !== 'object') return null;
  const choice = value as { kind?: unknown; look?: unknown; selection?: unknown };
  if (choice.kind === 'abstract') return { kind: 'abstract' };
  if (choice.kind === 'stylized') {
    const selection = choice.selection as { lookId?: unknown; appearance?: unknown } | undefined;
    return selection && typeof selection.lookId === 'string' && selection.appearance && typeof selection.appearance === 'object'
      ? { kind: 'stylized', selection: selection as CharacterSelection }
      : null;
  }
  if (choice.kind === 'catalog') {
    try {
      validateLook(catalog, choice.look as CharacterLook);
      return { kind: 'catalog', look: choice.look as CharacterLook };
    } catch {
      return null;
    }
  }
  return null;
}

/**
 * The development preview's store: this browser's local storage, which the page may not have.
 * An unreadable or foreign entry is dropped rather than trusted; storage that refuses writes
 * keeps the history for this page only.
 */
export class PreviewLookStore implements LookStore {
  private memory: SavedRevision[] = [];

  constructor(
    private readonly defaultLook: (current: SavedChoice | null) => SavedChoice,
    private readonly storage: Pick<Storage, 'getItem' | 'setItem'> | null = PreviewLookStore.browserStorage(),
    private readonly catalog: CharacterCatalog = CHARACTER_CATALOG,
    private readonly now: () => Date = () => new Date(),
  ) {
    this.memory = this.load();
  }

  private static browserStorage(): Pick<Storage, 'getItem' | 'setItem'> | null {
    try {
      return globalThis.localStorage ?? null;
    } catch {
      return null;
    }
  }

  private load(): SavedRevision[] {
    try {
      const raw = this.storage?.getItem(PREVIEW_KEY);
      if (!raw) return [];
      const stored = JSON.parse(raw) as StoredHistory;
      if (stored.profile !== 'exulanica.character-look-history/v1' || !Array.isArray(stored.revisions)) return [];
      const revisions: SavedRevision[] = [];
      for (const entry of stored.revisions) {
        const choice = parseChoice(entry.choice, this.catalog);
        if (!choice || !Number.isSafeInteger(entry.revision)) return [];
        revisions.push({ ...entry, choice });
      }
      return revisions.sort((a, b) => b.revision - a.revision);
    } catch {
      return [];
    }
  }

  private persist(): void {
    try {
      const stored: StoredHistory = { profile: 'exulanica.character-look-history/v1', revisions: this.memory.slice(0, HISTORY_LIMIT) };
      this.storage?.setItem(PREVIEW_KEY, JSON.stringify(stored));
    } catch {
      // Storage refused the write; this page still holds the history.
    }
  }

  private view(): SavedLooks {
    const current = this.memory[0] ?? null;
    return { revision: current?.revision ?? 0, current };
  }

  keeps(): boolean {
    return true;
  }

  private append(choice: SavedChoice, baseRevision: number, operation: SavedRevision['operation'], restoredFromRevision: number | null): SavedLooks {
    // Another tab may have written since this page loaded.
    const stored = this.load();
    if (stored.length > 0) this.memory = stored;
    if (this.view().revision !== baseRevision) throw new StaleLookError();
    this.memory = [{ revision: baseRevision + 1, operation, restoredFromRevision, choice, savedAt: this.now().toISOString() }, ...this.memory];
    this.persist();
    return this.view();
  }

  async read(): Promise<SavedLooks> {
    return this.view();
  }

  async history(): Promise<readonly SavedRevision[]> {
    return this.memory.slice(0, HISTORY_LIMIT);
  }

  async save(choice: SavedChoice, baseRevision: number): Promise<SavedLooks> {
    return this.append(choice, baseRevision, 'save', null);
  }

  async reset(baseRevision: number, restoreRevision?: number): Promise<SavedLooks> {
    if (restoreRevision === undefined) return this.append(this.defaultLook(this.view().current?.choice ?? null), baseRevision, 'reset', null);
    const target = this.memory.find((entry) => entry.revision === restoreRevision);
    if (!target) throw new Error('That saved look is no longer in this browser.');
    return this.append(target.choice, baseRevision, 'reset', restoreRevision);
  }
}

interface WireRevision {
  readonly revision: number;
  readonly operation: 'save' | 'reset';
  readonly restored_from_revision: number | null;
  readonly document: { readonly recipe: { readonly family_id: string; readonly parameters: Readonly<Record<string, unknown>> } };
  readonly created_at: string;
  readonly render_status: string;
}

interface WireFamily {
  readonly family_sha256: string;
  readonly family: { readonly family_id: string; readonly default_seed: number };
}

/** Where a signed-in person's saved looks live: one world version, as one actor. */
export interface WorkspaceLookTarget {
  readonly worldId: string;
  readonly versionId: string;
  readonly actor: string;
}

/**
 * Where saved looks live in a signed-in world: the open world's version, as the account's avatar.
 * A world opened without a saved entry has no version the client can name, and a session opened
 * without an account names no avatar; both keep looks for the visit and say which.
 */
export function worldLookTarget(
  entry: { readonly worldId: string; readonly authoredVersionId: string } | null,
  actor: string | null,
): { readonly target: WorkspaceLookTarget } | { readonly target: null; readonly missing: 'version' | 'account' } {
  if (entry === null) return { target: null, missing: 'version' };
  if (actor === null) return { target: null, missing: 'account' };
  return { target: { worldId: entry.worldId, versionId: entry.authoredVersionId, actor } };
}

/** A signed-in person's catalog looks, saved through the authenticated appearance routes. */
export class WorkspaceLookStore implements LookStore {
  private readonly transport: Transport;
  private readonly path: string;
  private readonly world: string;
  private families: Promise<readonly WireFamily[]> | null = null;

  constructor(
    options: TransportOptions,
    target: WorkspaceLookTarget,
    private readonly catalog: CharacterCatalog = CHARACTER_CATALOG,
  ) {
    this.transport = new Transport(options);
    this.path = `/world/versions/${encodeURIComponent(target.versionId)}/characters/avatar/${encodeURIComponent(target.actor)}/appearance`;
    // Every operation names the world its version belongs to; a workspace holds several.
    this.world = `world_id=${encodeURIComponent(target.worldId)}`;
  }

  private at(suffix = ''): string {
    return `${this.path}${suffix}?${this.world}`;
  }

  /** The server keeps recipes over catalog bodies; the abstract figure and examples are not recipes. */
  keeps(choice: SavedChoice): boolean {
    return choice.kind === 'catalog';
  }

  private revision(wire: WireRevision): SavedRevision | null {
    const look = lookFromRecipe(this.catalog, wire.document.recipe.family_id, wire.document.recipe.parameters);
    return look === null ? null : {
      revision: wire.revision,
      operation: wire.operation,
      restoredFromRevision: wire.restored_from_revision,
      choice: { kind: 'catalog', look },
      savedAt: wire.created_at,
    };
  }

  private async family(look: CharacterLook): Promise<WireFamily> {
    this.families ??= this.transport.getJson<readonly WireFamily[]>(this.at('/families')).catch((error: unknown) => {
      this.families = null;
      throw error;
    });
    const family = (await this.families).find((entry) => entry.family.family_id === recipeFamilyId(look));
    if (!family) throw new Error('This body is not offered for saved looks here yet.');
    return family;
  }

  private looks(response: { readonly revision: number; readonly current: WireRevision | null }): SavedLooks {
    return { revision: response.revision, current: response.current === null ? null : this.revision(response.current) };
  }

  async read(): Promise<SavedLooks> {
    return this.looks(await this.transport.getJson(this.at()));
  }

  async history(): Promise<readonly SavedRevision[]> {
    const rows = await this.transport.getJson<readonly WireRevision[]>(this.at('/history'));
    return rows.flatMap((row) => {
      const revision = this.revision(row);
      return revision === null ? [] : [revision];
    });
  }

  async save(choice: SavedChoice, baseRevision: number): Promise<SavedLooks> {
    if (choice.kind !== 'catalog') throw new Error('Only people from the catalog are saved to your world.');
    const family = await this.family(choice.look);
    try {
      return this.looks(await this.transport.putJson(this.at(), {
        base_revision: baseRevision,
        recipe: {
          family_id: family.family.family_id,
          family_sha256: family.family_sha256,
          parameters: recipeParameters(choice.look),
          seed: family.family.default_seed,
        },
      }));
    } catch (error) {
      throw error instanceof ApiError && error.status === 409 ? new StaleLookError() : error;
    }
  }

  async reset(baseRevision: number, restoreRevision?: number): Promise<SavedLooks> {
    try {
      return this.looks(await this.transport.postJson(this.at('/reset'), {
        base_revision: baseRevision,
        ...(restoreRevision === undefined ? {} : { restore_revision: restoreRevision }),
      }));
    } catch (error) {
      throw error instanceof ApiError && error.status === 409 ? new StaleLookError() : error;
    }
  }
}
