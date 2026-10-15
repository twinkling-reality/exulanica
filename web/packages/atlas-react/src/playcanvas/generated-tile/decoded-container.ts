import { decodeOwd, type DecodedOwd } from '@exulanica/loom-tess/core';

/**
 * A baked tile container decoded once on a page, however many readers read it.
 *
 * Opening a town reads each container several times: the tile runtime draws it, and its street
 * furniture, doors, sight blockers and a look's window slots are read from its records. Each used to
 * parse the same bytes again. One decode is kept per bytes, by identity: a page never changes a
 * container's bytes once it has them, and no reader changes what it decodes. A decode goes when its
 * bytes do. A container whose layout does not decode is not kept, so every reader is refused it, as
 * each was before.
 */
const decoded = new WeakMap<Uint8Array, DecodedOwd>();

/** `bytes` decoded by tess's own decoder, once for as long as the page holds them. */
export function decodedContainer(bytes: Uint8Array): DecodedOwd {
  const known = decoded.get(bytes);
  if (known !== undefined) return known;
  const read = decodeOwd(bytes);
  decoded.set(bytes, read);
  return read;
}
