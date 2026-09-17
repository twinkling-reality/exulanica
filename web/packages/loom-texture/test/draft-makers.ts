import { canonicalBytes } from '../src/canonical-json.js';
import { DRAFT_MAKERS } from '../src/makers/index.js';

/**
 * THE DRAFT MAKERS' MANIFESTS, AS FILES THE BACKEND CAN READ.
 *
 * A draft maker's manifest exists only in TypeScript until its first set is published, when it
 * becomes an object under `assets/textures/objects/` that the backend checks. Until then the
 * backend would first see a draft manifest, and the draft recipes made from it, inside the commit
 * that pins them, too late to disagree cheaply. So each draft manifest is written here as
 * canonical JSON, `tests/test_texture_drafts.py` holds the manifests and the entries in
 * `library-drafts/` to the backend's checks, and `draft-makers.test.ts` holds the committed files
 * to this module byte for byte.
 *
 * Run `node_modules/.bin/tsx packages/loom-texture/test/write-draft-makers.ts` from `web/` to write
 * them.
 */
export const DRAFT_MAKER_DIRECTORY = 'draft-makers';

/** Each draft maker's manifest as canonical JSON, by path relative to this directory. */
export function draftMakerFiles(): Map<string, Uint8Array> {
  const files = new Map<string, Uint8Array>();
  for (const maker of DRAFT_MAKERS) {
    const { maker_id: id, version } = maker.manifest;
    files.set(`${DRAFT_MAKER_DIRECTORY}/${id}.v${version}.json`, canonicalBytes(maker.manifest));
  }
  return files;
}
