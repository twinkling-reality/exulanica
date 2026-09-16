import { createHash } from 'node:crypto';

/** The lowercase hex sha256 of `bytes`: every pin, blob name and object name in this package. */
export function sha256Hex(bytes: Uint8Array): string {
  return createHash('sha256').update(bytes).digest('hex');
}
