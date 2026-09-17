/**
 * THE TRIANGLE DIGEST. Written before either build existed, so it describes a definition and not
 * whichever implementation came second. `README.md` states the same thing in prose.
 *
 * ONE DIGEST PER PROJECTION. A projection (`render_batch`, `nav_envelope`, and later
 * `collision_proxy` and `pick_geometry`) is a separate declared output, so each gets its own
 * digest and a change to one never moves another.
 *
 * WHAT ENTERS, in this order, and nothing else:
 *
 *   1. the domain `exulanica/owd-triangle-digest`, distinct from `exulanica/idempotency-key` so
 *      this digest can never be mistaken for a key;
 *   2. the digest format version, the decimal text `1`;
 *   3. the projection name;
 *   4. the number of entries, as a signed 64-bit integer. There is exactly one entry per record
 *      the tile document carries, drawn or not;
 *   5. for each entry, in the canonical record order below, exactly eight fields:
 *        a. the record kind, for example `city.terrain`;
 *        b. the record digest: lowercase hex SHA-256 of the record's canonical JSON payload
 *           `{"fields", "kind", "version"}`, which is `exulanica.grammar.records.canonical_record`;
 *        c. the identity the record states, as its canonical UUID text, or `not-stated` when the
 *           record kind carries no identity field. An identity is never minted here;
 *        d. the entry state: `drawn`, `unavailable`, `not_admitted` or `not_in_projection`;
 *        e. for a drawn entry in a projection that carries surfaces (`render_batch`), the
 *           material reference: the record digest of the `city.surface_material` record the
 *           range is bound to, or `not-carried` when the record kind has no material record shape
 *           at all. Empty otherwise;
 *        f. for a drawn entry in a projection that carries surfaces, the surface orientation,
 *           `horizontal` or `vertical`. Empty otherwise;
 *        g. for a drawn entry, the triangles: nine signed 64-bit big-endian integers per triangle,
 *           vertex a, b, c, each x, y, z, in the declared unit, in the order the expander emitted
 *           them. For an unavailable entry, the canonical JSON array of what the record kind
 *           lacks. Empty for `not_admitted` and `not_in_projection`;
 *        h. for a drawn entry in a projection that carries surfaces, the surface coordinates: six
 *           signed 64-bit big-endian integers per triangle, vertex a, b, c, each s, t, in
 *           millimetres. Empty otherwise.
 *
 * SURFACE COORDINATES are millimetres on the surface, in the frames the city vocabulary lane
 * fixed with this lane and the tile runtime on 2026-09-16, so a texture's physical extent scales
 * them with no guessed constant:
 *
 *   horizontal  t is always to the left of s. Terrain, lot and roof: s = x, t = y, in plan, a
 *               pitched plane included. Carriageway, gutter, kerb top, footway and crossing: s
 *               along the owning segment's centreline from its start node; a junction uses +x.
 *               An awning: s along its facade run. A part top: s is the part's local +x.
 *   vertical    s along the run from its start (a facade's edge run from its start vertex, the
 *               kerb face's along-centreline coordinate, a part's local +x); t = base - z,
 *               pointing down, from the building's base elevation, the gutter level, or the
 *               part's base.
 *
 * Only terrain draws today, so only the plan frame is exercised; the others are stated here so a
 * reader can rely on them before a record draws in them.
 *
 * WHAT DOES NOT ENTER: the float32 payload, the index buffer (triangles are digested
 * de-indexed, so how vertices are shared cannot move the digest), texture bytes, the container
 * header's layout and padding, section offsets, each projection's representation contract text
 * (the tessellator version covers it), the tile inputs digest (the bake key covers it), and any
 * time. Digesting the float32 bytes would make the digest a statement about a lossy rounding
 * rather than about the geometry, which is why they are payload and nothing more.
 *
 * THE UNIT is the records' own: millimetres, integers. Every coordinate is quantised before it
 * is a vertex, by the expander, in integer arithmetic; nothing is quantised after the fact.
 *
 * THE ORDER is total and comes from the records alone. Entries sort by record kind, then by
 * record digest, both compared as ASCII text. A tile document never carries one record twice (the
 * reader refuses it), so no two entries tie. Within a range the order is the expander's, which
 * is a loop over the record's own fields (a terrain grid is row-major over its cells). There is no
 * spatial sort anywhere, so no tie between two positions can flip an order.
 *
 * THE ENCODING. Every field, fixed width or not, is framed by its length as an unsigned 64-bit
 * big-endian integer, exactly as `exulanica.ingest.stages.idempotency_key` frames its fields and
 * for its reason: unframed concatenation is not injective. Text is printable ASCII, one byte a
 * character. SHA-256 is taken over the concatenation.
 *
 * Core cannot hash: it compiles against no host, and `crypto` is one. This module builds the
 * exact bytes, and each entry hashes them with its own host's SHA-256.
 */
import { asciiBytes } from './ascii.js';
import { canonicalJson } from './canonical-json.js';

export const TRIANGLE_DIGEST_DOMAIN = 'exulanica/owd-triangle-digest';
export const TRIANGLE_DIGEST_VERSION = 1;
export const TRIANGLE_DIGEST_PROFILE = 'exulanica.owd-triangle-digest/v1';

/** The identity text of a record whose kind carries no identity field. */
export const IDENTITY_NOT_STATED = 'not-stated';
/** The material text of a range whose record kind has no material record shape. */
export const MATERIAL_NOT_CARRIED = 'not-carried';

export const ENTRY_STATES = ['drawn', 'unavailable', 'not_admitted', 'not_in_projection'] as const;
export const SURFACE_ORIENTATIONS = ['horizontal', 'vertical'] as const;
export type SurfaceOrientation = (typeof SURFACE_ORIENTATIONS)[number];
export type EntryState = (typeof ENTRY_STATES)[number];

/** Signed 64-bit integers take eight bytes, and a triangle is three vertices of three. */
const INT64_BYTES = 8;
export const COORDINATES_PER_TRIANGLE = 9;
export const SURFACE_COORDINATES_PER_TRIANGLE = 6;

interface EntryHead {
  readonly kind: string;
  readonly recordSha256: string;
  readonly identity: string;
}

export type DigestEntry =
  | (EntryHead & {
      readonly state: 'drawn';
      /** Absolute coordinates, nine per triangle, in emission order. */
      readonly triangles: ArrayLike<number>;
      /** Present exactly when the projection carries surfaces. */
      readonly surface?: {
        readonly material: string;
        readonly orientation: SurfaceOrientation;
        /** Absolute surface coordinates, six per triangle, in emission order. */
        readonly coordinates: ArrayLike<number>;
      };
    })
  | (EntryHead & { readonly state: 'unavailable'; readonly needs: readonly string[] })
  | (EntryHead & { readonly state: 'not_admitted' | 'not_in_projection' });

class Framer {
  private readonly parts: Uint8Array[] = [];
  private total = 0;

  field(bytes: Uint8Array): void {
    const length = new Uint8Array(INT64_BYTES);
    new DataView(length.buffer).setBigUint64(0, BigInt(bytes.length), false);
    this.parts.push(length, bytes);
    this.total += length.length + bytes.length;
  }

  text(value: string, where: string): void {
    this.field(asciiBytes(value, where));
  }

  integer(value: number, where: string): void {
    this.field(int64Bytes([value], where));
  }

  bytes(): Uint8Array {
    const out = new Uint8Array(this.total);
    let cursor = 0;
    for (const part of this.parts) {
      out.set(part, cursor);
      cursor += part.length;
    }
    return out;
  }
}

/** Signed 64-bit big-endian encodings of safe integers, one after another. */
export function int64Bytes(values: ArrayLike<number>, where: string): Uint8Array {
  const out = new Uint8Array(values.length * INT64_BYTES);
  const view = new DataView(out.buffer);
  for (let index = 0; index < values.length; index += 1) {
    const value = values[index]!;
    if (!Number.isSafeInteger(value)) {
      throw new RangeError(`${where}: coordinate ${index} is not a safe integer`);
    }
    view.setBigInt64(index * INT64_BYTES, BigInt(value), false);
  }
  return out;
}

/** The exact bytes whose SHA-256 is a projection's triangle digest. */
export function trianglePreimage(projection: string, entries: readonly DigestEntry[]): Uint8Array {
  const framer = new Framer();
  framer.text(TRIANGLE_DIGEST_DOMAIN, 'domain');
  framer.text(String(TRIANGLE_DIGEST_VERSION), 'version');
  framer.text(projection, 'projection');
  framer.integer(entries.length, 'entry count');
  entries.forEach((entry, index) => {
    const where = `${projection} entry ${index}`;
    framer.text(entry.kind, where);
    framer.text(entry.recordSha256, where);
    framer.text(entry.identity, where);
    framer.text(entry.state, where);
    switch (entry.state) {
      case 'drawn': {
        const triangles = entry.triangles.length / COORDINATES_PER_TRIANGLE;
        if (!Number.isInteger(triangles)) {
          throw new RangeError(`${where}: the triangle stream is not whole triangles`);
        }
        const surface = entry.surface;
        if (surface === undefined) {
          framer.text('', where);
          framer.text('', where);
          framer.field(int64Bytes(entry.triangles, where));
          framer.text('', where);
          return;
        }
        if (surface.coordinates.length !== triangles * SURFACE_COORDINATES_PER_TRIANGLE) {
          throw new RangeError(`${where}: the surface coordinates do not match the triangles`);
        }
        framer.text(surface.material, where);
        framer.text(surface.orientation, where);
        framer.field(int64Bytes(entry.triangles, where));
        framer.field(int64Bytes(surface.coordinates, where));
        return;
      }
      case 'unavailable':
        framer.text('', where);
        framer.text('', where);
        framer.text(canonicalJson(entry.needs), where);
        framer.text('', where);
        return;
      case 'not_admitted':
      case 'not_in_projection':
        framer.text('', where);
        framer.text('', where);
        framer.text('', where);
        framer.text('', where);
        return;
    }
  });
  return framer.bytes();
}
