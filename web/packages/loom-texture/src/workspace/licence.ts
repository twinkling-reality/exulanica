import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { sha256Hex } from '../digest.js';
import { packageRoot } from '../library.js';

/**
 * The licence a workspace's own bake is under, which says the bytes are private to that workspace.
 *
 * A published set is CC0 because this repository generated it for publication. A workspace bake is
 * a person's variant, made for them, and publishing it is not this package's to decide. So it
 * carries a licence id no publishing path accepts (`publish.ts`, the library, the dataset plan, the
 * backend's manifest reader and its exports), and the text says what the id means. The text is a
 * file rather than a string so the backend can pin the same bytes by digest.
 */
export const WORKSPACE_LICENCE_ID = 'LicenseRef-Exulanica-Workspace-Private';
export const WORKSPACE_LICENCE_FILE = 'licences/workspace-private.txt';

export interface WorkspaceLicence {
  readonly id: typeof WORKSPACE_LICENCE_ID;
  readonly bytes: Uint8Array;
  readonly sha256: string;
}

export function workspaceLicence(root: string = packageRoot()): WorkspaceLicence {
  const bytes = new Uint8Array(readFileSync(join(root, ...WORKSPACE_LICENCE_FILE.split('/'))));
  return { id: WORKSPACE_LICENCE_ID, bytes, sha256: sha256Hex(bytes) };
}
