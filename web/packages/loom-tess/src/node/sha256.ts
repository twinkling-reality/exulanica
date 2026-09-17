import { createHash } from 'node:crypto';
import type { Sha256Hex } from '../core/bake.js';

/** Node's SHA-256, synchronous underneath, in the shape core takes. */
export const nodeSha256: Sha256Hex = (bytes) =>
  Promise.resolve(createHash('sha256').update(bytes).digest('hex'));
