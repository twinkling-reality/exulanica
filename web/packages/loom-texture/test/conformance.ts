import { canonicalBytes } from '../src/canonical-json.js';
import {
  type MakerKind,
  type MapDescriptor,
  type MaterialClass,
  SET_PROFILE_V1,
  SET_PROFILE_V2,
  V1_LAYOUT,
  channelsOf,
  classLayout,
  classParameters,
  coveragePermille,
  NORMAL_XY,
  ORM,
  BASE_COLOR,
} from '../src/classes.js';
import {
  type FramedMap,
  GENERATOR,
  MEDIA_TYPE,
  TEXEL_LAYOUT,
  TILING,
  TRUTH,
  frameContainer,
  placement,
} from '../src/container.js';
import { sha256Hex } from '../src/digest.js';
import { LICENCE_ID, licenceBytes } from '../src/licence.js';
import { MANIFEST_PROFILE_V2 } from '../src/manifest-reader.js';

/**
 * THE SHARED CONFORMANCE CASES FOR TEXTURE SET READERS, AND THE FIXTURES THEY READ.
 *
 * Every file this writes is a function of this module alone. `test/texture-set-cases.test.ts` holds
 * the committed files to it byte for byte and runs every case against this package's reader;
 * `tests/test_texture_set_cases.py` runs them against the backend's; `atlas-core` runs them against
 * the browser's. The fixtures are not published sets. They are small (16 x 16 texels) containers
 * with synthetic texels, one for each kind of container a reader must accept, and then single
 * mutations of those, each with exactly one defect, so which check a reader happens to run first
 * cannot change the reason it gives.
 *
 * Run `node_modules/.bin/tsx packages/loom-texture/test/write-conformance.ts` from `web/` to write
 * them.
 */
export const CASES_FILE = 'texture-set-cases.json';
export const FIXTURE_DIRECTORY = 'conformance';

const SIZE = 16;
const TEXELS = SIZE * SIZE;

type Header = Record<string, unknown>;

interface Fixture {
  readonly setId: string;
  readonly header: Header;
  readonly maps: readonly FramedMap[];
}

function texels(components: number, value: (i: number, j: number, c: number) => number): Uint8Array {
  const out = new Uint8Array(TEXELS * components);
  for (let j = 0; j < SIZE; j += 1) {
    for (let i = 0; i < SIZE; i += 1) {
      for (let c = 0; c < components; c += 1) out[(j * SIZE + i) * components + c] = value(i, j, c) & 0xff;
    }
  }
  return out;
}

/** Synthetic texels per map name, so each map's bytes differ and none is constant. */
function mapBytes(descriptor: MapDescriptor): Uint8Array {
  switch (descriptor.name) {
    case 'base_color':
      return texels(3, (i, j, c) => [i * 17, j * 17, (i + j) * 8][c]!);
    case 'base_color_coverage':
      return texels(4, (i, j, c) => [i * 17, j * 13, (i + j) * 8, (i + j) % 3 === 0 ? 64 : 200][c]!);
    case 'normal':
      return descriptor.components === 2
        ? texels(2, (i, j, c) => [120 + i, 120 + j][c]!)
        : texels(3, (i, j, c) => [120 + i, 120 + j, 250][c]!);
    case 'orm':
      return texels(3, (i, j, c) => [255 - i, 128 + j, (i * j) % 7][c]!);
    case 'transmission_roughness':
      return texels(2, (i, j, c) => [240 - i, 20 + j][c]!);
    case 'height':
      return texels(1, (i, j) => (i * j) % 256);
    default:
      throw new Error(`no synthetic texels for ${descriptor.name}`);
  }
}

const framed = (layout: readonly MapDescriptor[]): FramedMap[] =>
  layout.map((descriptor) => ({ descriptor, bytes: mapBytes(descriptor) }));

const LICENCE_SHA256 = sha256Hex(licenceBytes());

function commonHeader(setId: string, title: string): Header {
  return {
    media_type: MEDIA_TYPE,
    generator: GENERATOR,
    set_id: setId,
    version: 1,
    seed: 1,
    family: 'fixture',
    title,
    summary: 'Synthetic texels for reader conformance. Not a published set.',
    truth: TRUTH,
    licence: { id: LICENCE_ID, sha256: LICENCE_SHA256 },
    resolution: { width: SIZE, height: SIZE },
    extent_mm: { u: 1000, v: 1000 },
    placement: placement('vertical'),
    layout: TEXEL_LAYOUT,
    tiling: TILING,
    parameters: {},
  };
}

const RELIEF = { height_range_mm: 4, cavity: { radius_mm: 4, depth_mm: 2, strength_permille: 500 } };
const FILM = { srgb: [150, 144, 132], roughnessPermille: 650 } as const;

function v2Fixture(
  setId: string,
  materialClass: MaterialClass,
  makerKind: MakerKind,
  produced = { normal: false, height: false },
): Fixture {
  const layout = classLayout(materialClass, makerKind, produced);
  const maps = framed(layout);
  const colour = maps.find((map) => map.descriptor.name === 'base_color_coverage');
  const relief = makerKind === 'procedural'
    ? (materialClass === 'glazing' ? {} : RELIEF)
    : (produced.height ? { height_range_mm: 8 } : {});
  return {
    setId,
    header: {
      ...commonHeader(setId, `Conformance fixture, ${makerKind} ${materialClass}`),
      profile: SET_PROFILE_V2,
      material_class: materialClass,
      maker_kind: makerKind,
      class: classParameters(
        materialClass,
        colour === undefined ? null : coveragePermille(colour.bytes),
        materialClass === 'glazing' ? FILM : null,
      ),
      ...relief,
    },
    maps,
  };
}

/** The six containers every reader must accept, by set id. */
export function baseFixtures(): Fixture[] {
  const legacy: Fixture = {
    setId: 'fixture.legacy-opaque',
    header: {
      ...commonHeader('fixture.legacy-opaque', 'Conformance fixture, a v1 opaque set'),
      profile: SET_PROFILE_V1,
      ...RELIEF,
    },
    maps: framed(V1_LAYOUT),
  };
  return [
    legacy,
    v2Fixture('fixture.opaque', 'opaque', 'procedural'),
    v2Fixture('fixture.cutout', 'cutout', 'procedural'),
    v2Fixture('fixture.decal', 'decal', 'procedural'),
    v2Fixture('fixture.glazing', 'glazing', 'procedural'),
    v2Fixture('fixture.model-opaque', 'opaque', 'model', { normal: true, height: true }),
  ];
}

function entryFor(fixture: Fixture, bytes: Uint8Array): Record<string, unknown> {
  const header = fixture.header;
  return {
    set_id: fixture.setId,
    version: header.version,
    content_sha256: sha256Hex(bytes),
    byte_size: bytes.length,
    resolution: header.resolution,
    channels: channelsOf(fixture.maps.map((map) => map.descriptor)),
    extent_mm: header.extent_mm,
    licence_id: LICENCE_ID,
    licence_sha256: LICENCE_SHA256,
    container_profile: header.profile,
    material_class: header.profile === SET_PROFILE_V1 ? 'opaque' : header.material_class,
  };
}

type Change = { readonly path: readonly (string | number)[]; readonly value?: unknown; readonly remove?: true };

function applyChanges(document: unknown, changes: readonly Change[]): unknown {
  const copy = JSON.parse(JSON.stringify(document)) as unknown;
  for (const change of changes) {
    let parent = copy as Record<string | number, unknown>;
    for (const step of change.path.slice(0, -1)) parent = parent[step] as Record<string | number, unknown>;
    const last = change.path.at(-1)!;
    if (change.remove) {
      if (Array.isArray(parent)) parent.splice(last as number, 1);
      else delete parent[last];
    } else {
      parent[last] = change.value;
    }
  }
  return copy;
}

interface ContainerCase {
  readonly name: string;
  readonly base: string;
  /** Build the defective bytes from the base fixture. */
  readonly bytes: (fixture: Fixture, good: Uint8Array) => Uint8Array;
  readonly entryChanges?: readonly Change[];
  readonly reason: 'byte-size' | 'digest' | 'container' | 'header';
  /** Whether the entry pins the defective bytes (true) or the base fixture's (false). */
  readonly pinDefective?: boolean;
}

const headerLengthOf = (bytes: Uint8Array): number => new DataView(bytes.buffer, bytes.byteOffset).getUint32(4, true);

/** Re-frame a fixture with its header changed. Offsets are recomputed, so the change is the defect. */
const reframed = (changes: readonly Change[]) => (fixture: Fixture): Uint8Array =>
  frameContainer(applyChanges(fixture.header, changes) as Header, fixture.maps);

/** Re-frame a fixture with other maps under its header. */
const withMaps = (layout: readonly MapDescriptor[], header: readonly Change[] = []) => (fixture: Fixture): Uint8Array =>
  frameContainer(applyChanges(fixture.header, header) as Header, framed(layout));

/** Frame the header's text as given, recomputing only where the maps start. */
function withHeaderText(fixture: Fixture, text: string): Uint8Array {
  const header = new TextEncoder().encode(text);
  const start = Math.ceil((8 + header.length) / 16) * 16;
  let total = start;
  for (const map of fixture.maps) total += map.bytes.length;
  const out = new Uint8Array(total);
  out.set(new TextEncoder().encode('LTX1'), 0);
  new DataView(out.buffer).setUint32(4, header.length, true);
  out.set(header, 8);
  out.fill(0x20, 8 + header.length, start);
  let cursor = start;
  for (const map of fixture.maps) {
    out.set(map.bytes, cursor);
    cursor += map.bytes.length;
  }
  return out;
}

function headerText(bytes: Uint8Array): string {
  return new TextDecoder().decode(bytes.subarray(8, 8 + headerLengthOf(bytes)));
}

const CONTAINER_CASES: readonly ContainerCase[] = [
  // Framing.
  {
    name: 'the magic is not LTX1',
    base: 'fixture.cutout',
    bytes: (_fixture, good) => { const bad = good.slice(); bad[3] = 0x32; return bad; },
    reason: 'container',
  },
  {
    name: 'the header length runs past the end of the file',
    base: 'fixture.opaque',
    bytes: (_fixture, good) => { const bad = good.slice(); new DataView(bad.buffer).setUint32(4, good.length, true); return bad; },
    reason: 'container',
  },
  {
    name: 'a padding byte is not a space',
    base: 'fixture.glazing',
    bytes: (fixture) => {
      // Lengthen the title until the header leaves padding, so the case never depends on where a
      // header's length happens to fall; then break the first padding byte.
      for (let dots = 0; dots < 16; dots += 1) {
        const title = `${String(fixture.header.title)}${'.'.repeat(dots)}`;
        const bad = reframed([{ path: ['title'], value: title }])(fixture);
        const at = 8 + headerLengthOf(bad);
        if (bad[at] === 0x20) {
          bad[at] = 0x00;
          return bad;
        }
      }
      throw new Error('no title length leaves padding');
    },
    reason: 'container',
  },
  {
    name: 'a byte follows the last map',
    base: 'fixture.decal',
    bytes: (_fixture, good) => { const bad = new Uint8Array(good.length + 1); bad.set(good); return bad; },
    reason: 'container',
  },
  {
    name: 'the last map is one byte short',
    base: 'fixture.model-opaque',
    bytes: (_fixture, good) => good.slice(0, good.length - 1),
    reason: 'container',
  },
  // What the header says.
  {
    name: 'the profile is one no reader was written for',
    base: 'fixture.opaque',
    bytes: reframed([{ path: ['profile'], value: 'exulanica.texture-set/v3' }]),
    reason: 'header',
  },
  {
    name: 'the header is valid JSON but not canonical',
    base: 'fixture.cutout',
    bytes: (fixture, good) => {
      const parsed = JSON.parse(headerText(good)) as Header;
      return withHeaderText(fixture, JSON.stringify({ version: parsed.version, ...parsed }));
    },
    reason: 'header',
  },
  {
    name: 'the header writes an integer with a fraction',
    base: 'fixture.glazing',
    bytes: (fixture, good) => withHeaderText(fixture, headerText(good).replace('"seed":1,', '"seed":1.0,')),
    reason: 'header',
  },
  {
    name: 'the material class is not one of the four',
    base: 'fixture.opaque',
    bytes: reframed([{ path: ['material_class'], value: 'emissive' }]),
    reason: 'header',
  },
  {
    name: 'the maker kind is not procedural or model',
    base: 'fixture.opaque',
    bytes: reframed([{ path: ['maker_kind'], value: 'scanned' }]),
    reason: 'header',
  },
  {
    name: 'the header has a key no header has',
    base: 'fixture.decal',
    bytes: reframed([{ path: ['comment'], value: 'not part of any profile' }]),
    reason: 'header',
  },
  {
    name: 'a procedural glazing set states a height range',
    base: 'fixture.glazing',
    bytes: reframed([{ path: ['height_range_mm'], value: 4 }]),
    reason: 'header',
  },
  {
    name: 'a procedural opaque set does not state its cavity',
    base: 'fixture.opaque',
    bytes: reframed([{ path: ['cavity'], remove: true }]),
    reason: 'header',
  },
  {
    name: 'a cutout set states a cutoff of 127',
    base: 'fixture.cutout',
    bytes: reframed([{ path: ['class', 'alpha_cutoff'], value: 127 }]),
    reason: 'header',
  },
  {
    name: 'a cutout set states a coverage its texels do not have',
    base: 'fixture.cutout',
    bytes: (fixture) => {
      const stated = (fixture.header.class as { coverage_permille: number }).coverage_permille;
      return reframed([{ path: ['class', 'coverage_permille'], value: stated + 1 }])(fixture);
    },
    reason: 'header',
  },
  {
    name: 'a cutout set says it has one side',
    base: 'fixture.cutout',
    bytes: reframed([{ path: ['class', 'double_sided'], value: false }]),
    reason: 'header',
  },
  {
    name: 'a decal set states a cutoff',
    base: 'fixture.decal',
    bytes: reframed([{ path: ['class', 'alpha_cutoff'], value: 128 }]),
    reason: 'header',
  },
  {
    name: 'a glazing set states another index of refraction',
    base: 'fixture.glazing',
    bytes: reframed([{ path: ['class', 'ior_millionths'], value: 1_520_000 }]),
    reason: 'header',
  },
  {
    name: 'an opaque set states a class parameter',
    base: 'fixture.opaque',
    bytes: reframed([{ path: ['class', 'double_sided'], value: true }]),
    reason: 'header',
  },
  {
    name: 'a cutout set stores its colour without coverage',
    base: 'fixture.cutout',
    bytes: withMaps([BASE_COLOR, NORMAL_XY, ORM], [{ path: ['class'], value: { alpha_cutoff: 128, coverage_permille: 0, double_sided: true } }]),
    reason: 'header',
  },
  {
    name: 'the normal map states another decode',
    base: 'fixture.opaque',
    bytes: withMaps([BASE_COLOR, { ...NORMAL_XY, decode: 'n = 2 * b / 255 - 1 per component' }, ORM]),
    reason: 'header',
  },
  {
    name: 'the normal map states another convention',
    base: 'fixture.decal',
    bytes: (fixture) => withMaps(
      fixture.maps.map((map) => (map.descriptor.name === 'normal'
        ? { ...map.descriptor, convention: 'DirectX: +Y toward the last row' }
        : map.descriptor)),
    )(fixture),
    reason: 'header',
  },
  {
    name: 'a model-made set stores a two-component normal',
    base: 'fixture.model-opaque',
    bytes: (fixture) => withMaps(fixture.maps.map((map) => (map.descriptor.name === 'normal' ? NORMAL_XY : map.descriptor)))(fixture),
    reason: 'header',
  },
  {
    name: 'a model-made set stores its maps out of order',
    base: 'fixture.model-opaque',
    bytes: (fixture) => {
      const [colour, normal, surface, height] = fixture.maps.map((map) => map.descriptor);
      return withMaps([colour!, surface!, normal!, height!])(fixture);
    },
    reason: 'header',
  },
  {
    name: 'a map states an offset that is not where it starts',
    base: 'fixture.legacy-opaque',
    bytes: (fixture, good) => {
      const text = headerText(good);
      const parsed = JSON.parse(text) as { maps: { byte_offset: number }[] };
      const last = parsed.maps.at(-1)!;
      const moved = text.replace(`"byte_offset":${last.byte_offset}`, `"byte_offset":${last.byte_offset + 1}`);
      if (moved.length !== text.length && Math.ceil((8 + moved.length) / 16) !== Math.ceil((8 + text.length) / 16)) {
        throw new Error('moving the offset changed where the maps start');
      }
      return withHeaderText(fixture, moved);
    },
    reason: 'header',
  },
  // Where the header and the manifest entry disagree.
  {
    name: 'the header names another set than the entry',
    base: 'fixture.glazing',
    bytes: reframed([{ path: ['set_id'], value: 'fixture.other-glazing' }]),
    reason: 'header',
  },
  {
    name: 'the header states another licence digest than the entry',
    base: 'fixture.opaque',
    bytes: reframed([{ path: ['licence', 'sha256'], value: '0'.repeat(64) }]),
    reason: 'header',
  },
  {
    name: 'the header states another media type',
    base: 'fixture.cutout',
    bytes: reframed([{ path: ['media_type'], value: 'image/png' }]),
    reason: 'header',
  },
  {
    name: 'the entry lists a model-made layout for a procedural container',
    base: 'fixture.glazing',
    bytes: (_fixture, good) => good,
    entryChanges: [{
      path: ['channels'],
      value: channelsOf(classLayout('glazing', 'model', { normal: false, height: true })),
    }],
    reason: 'header',
  },
  {
    name: 'the entry says decal for a cutout container',
    base: 'fixture.cutout',
    bytes: (_fixture, good) => good,
    entryChanges: [{ path: ['material_class'], value: 'decal' }],
    reason: 'header',
  },
  // The pins.
  {
    name: 'the entry pins one byte fewer',
    base: 'fixture.decal',
    bytes: (_fixture, good) => good,
    entryChanges: [{ path: ['byte_size'], value: -1 }],
    reason: 'byte-size',
  },
  {
    name: 'the entry pins another digest',
    base: 'fixture.model-opaque',
    bytes: (_fixture, good) => good,
    entryChanges: [{ path: ['content_sha256'], value: 'f'.repeat(64) }],
    reason: 'digest',
  },
  // A glazing set's declared film: checked for shape and range, never recomputed. Appended
  // after the first cases so their files keep their numbers.
  {
    name: 'a glazing set does not declare its film colour',
    base: 'fixture.glazing',
    bytes: reframed([{ path: ['class', 'film_srgb'], remove: true }]),
    reason: 'header',
  },
  {
    name: 'a glazing set declares a film colour of two channels',
    base: 'fixture.glazing',
    bytes: reframed([{ path: ['class', 'film_srgb'], value: [150, 144] }]),
    reason: 'header',
  },
  {
    name: 'a glazing set declares a film colour channel above 255',
    base: 'fixture.glazing',
    bytes: reframed([{ path: ['class', 'film_srgb'], value: [150, 256, 132] }]),
    reason: 'header',
  },
  {
    name: 'a glazing set does not declare its film roughness',
    base: 'fixture.glazing',
    bytes: reframed([{ path: ['class', 'film_roughness_permille'], remove: true }]),
    reason: 'header',
  },
  {
    name: 'a glazing set declares a film roughness above 1000',
    base: 'fixture.glazing',
    bytes: reframed([{ path: ['class', 'film_roughness_permille'], value: 1001 }]),
    reason: 'header',
  },
  {
    name: 'a glazing set declares its film roughness as text',
    base: 'fixture.glazing',
    bytes: reframed([{ path: ['class', 'film_roughness_permille'], value: '650' }]),
    reason: 'header',
  },
  {
    name: 'a cutout set declares a film colour',
    base: 'fixture.cutout',
    bytes: reframed([{ path: ['class', 'film_srgb'], value: [150, 144, 132] }]),
    reason: 'header',
  },
];

interface ManifestCase {
  readonly name: string;
  readonly changes: readonly Change[];
  readonly reason: 'manifest' | null;
}

const MANIFEST_CASES = (entries: readonly Record<string, unknown>[]): ManifestCase[] => {
  const legacy = entries.findIndex((entry) => entry.set_id === 'fixture.legacy-opaque');
  const cutout = entries.findIndex((entry) => entry.set_id === 'fixture.cutout');
  const glazing = entries.findIndex((entry) => entry.set_id === 'fixture.glazing');
  const legacyV1 = Object.fromEntries(
    Object.entries(entries[legacy]!).filter(([key]) => key !== 'container_profile' && key !== 'material_class'),
  );
  return [
    { name: 'the fixture manifest is accepted', changes: [], reason: null },
    {
      name: 'a v1 manifest listing a v1 container is accepted',
      changes: [
        { path: ['profile'], value: 'exulanica.texture-manifest/v1' },
        { path: ['sets'], value: [legacyV1] },
      ],
      reason: null,
    },
    {
      name: 'a glazing entry may list a model-made layout with a height map',
      changes: [{ path: ['sets', glazing, 'channels'], value: channelsOf(classLayout('glazing', 'model', { normal: true, height: true })) }],
      reason: null,
    },
    { name: 'the manifest profile is one no reader was written for', changes: [{ path: ['profile'], value: 'exulanica.texture-manifest/v3' }], reason: 'manifest' },
    { name: 'a v2 entry does not state its class', changes: [{ path: ['sets', cutout, 'material_class'], remove: true }], reason: 'manifest' },
    { name: 'a v2 entry has a key no entry has', changes: [{ path: ['sets', cutout, 'maker_kind'], value: 'procedural' }], reason: 'manifest' },
    { name: 'a v2 entry names a class that is not one of the four', changes: [{ path: ['sets', cutout, 'material_class'], value: 'emissive' }], reason: 'manifest' },
    { name: 'a v2 entry names a container profile no reader was written for', changes: [{ path: ['sets', cutout, 'container_profile'], value: 'exulanica.texture-set/v3' }], reason: 'manifest' },
    { name: 'a v1 container is never a cutout', changes: [{ path: ['sets', legacy, 'material_class'], value: 'cutout' }], reason: 'manifest' },
    {
      name: 'a cutout entry lists the opaque layout',
      changes: [{ path: ['sets', cutout, 'channels'], value: channelsOf(classLayout('opaque', 'procedural')) }],
      reason: 'manifest',
    },
    { name: 'a channel is marked linear where the layout says sRGB', changes: [{ path: ['sets', glazing, 'channels', 0, 'srgb'], value: false }], reason: 'manifest' },
    { name: 'a v1 manifest lists v2 entries', changes: [{ path: ['profile'], value: 'exulanica.texture-manifest/v1' }], reason: 'manifest' },
    { name: 'the sets are not sorted by id', changes: [{ path: ['sets', 0], value: entries[1] }, { path: ['sets', 1], value: entries[0] }], reason: 'manifest' },
    { name: 'a set is listed twice', changes: [{ path: ['sets', 1], value: entries[0] }], reason: 'manifest' },
    { name: 'a set is under another licence', changes: [{ path: ['sets', glazing, 'licence_id'], value: 'CC-BY-4.0' }], reason: 'manifest' },
    { name: 'the manifest lists no sets', changes: [{ path: ['sets'], value: [] }], reason: 'manifest' },
  ];
};

/** Every file the conformance fixtures and cases consist of, by path relative to `test/`. */
export function conformanceFiles(): Map<string, Uint8Array> {
  const files = new Map<string, Uint8Array>();
  const fixtures = new Map(baseFixtures().map((fixture) => [fixture.setId, fixture]));
  const good = new Map<string, Uint8Array>();
  const entries: Record<string, unknown>[] = [];
  for (const fixture of fixtures.values()) {
    const bytes = frameContainer(fixture.header, fixture.maps);
    good.set(fixture.setId, bytes);
    files.set(`${FIXTURE_DIRECTORY}/${fixture.setId}.ltex`, bytes);
    entries.push(entryFor(fixture, bytes));
  }
  entries.sort((a, b) => ((a.set_id as string) < (b.set_id as string) ? -1 : 1));
  const manifest = { profile: MANIFEST_PROFILE_V2, sets: entries };
  files.set(`${FIXTURE_DIRECTORY}/manifest.json`, canonicalBytes(manifest));

  const containers = [
    ...baseFixtures().map((fixture) => ({
      name: `${fixture.setId} is accepted`,
      container: `${FIXTURE_DIRECTORY}/${fixture.setId}.ltex`,
      entry: entries.find((entry) => entry.set_id === fixture.setId)!,
      reason: null,
    })),
    ...CONTAINER_CASES.map((testCase, index) => {
      const fixture = fixtures.get(testCase.base)!;
      const bytes = testCase.bytes(fixture, good.get(testCase.base)!);
      const base = entries.find((entry) => entry.set_id === testCase.base)!;
      const pinned = { ...base, content_sha256: sha256Hex(bytes), byte_size: bytes.length };
      const changes = (testCase.entryChanges ?? []).map((change) => (
        change.path[0] === 'byte_size' ? { ...change, value: bytes.length + (change.value as number) } : change
      ));
      const name = `${String(index + 1).padStart(2, '0')}-${testCase.base.replace('fixture.', '')}`;
      const same = bytes === good.get(testCase.base);
      const container = same ? `${FIXTURE_DIRECTORY}/${testCase.base}.ltex` : `${FIXTURE_DIRECTORY}/refused/${name}.ltex`;
      if (!same) files.set(container, bytes);
      return {
        name: testCase.name,
        container,
        entry: applyChanges(pinned, changes),
        reason: testCase.reason,
      };
    }),
  ];

  const cases = {
    about:
      'Cases every texture set reader runs: web/packages/loom-texture/test/texture-set-cases.test.ts, '
      + 'tests/test_texture_set_cases.py in the backend, and the browser reader in atlas-core. '
      + 'Paths are relative to this file. A manifest case applies its changes in order to the fixture '
      + 'manifest, serialises it as canonical JSON and reads it. A container case reads a manifest whose '
      + 'one set is its entry, then holds the container to that entry. reason is null for a case every '
      + 'reader accepts, and otherwise the one reason every reader refuses it for: manifest, byte-size, '
      + 'digest, container or header. Generated by test/conformance.ts; do not edit by hand.',
    manifest: `${FIXTURE_DIRECTORY}/manifest.json`,
    manifests: MANIFEST_CASES(entries),
    containers,
  };
  files.set(CASES_FILE, new TextEncoder().encode(`${JSON.stringify(cases, null, 2)}\n`));
  return files;
}
