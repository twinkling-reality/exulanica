// @vitest-environment happy-dom
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';
import type { IslandId } from '@exulanica/atlas-core';
import {
  flatNormalGeometry,
  giveFlatNormalsWhereUnusable,
  normalsUsable,
} from '../src/playcanvas/object-normals.js';
import { AUTHORED_OBJECT_MEDIA_TYPE, SceneObjectRuntime } from '../src/playcanvas/scene-objects.js';

/**
 * Flat normals for an authored mesh whose own normals light nothing, on the reviewed bytes.
 *
 * The marker plate is read from the same committed fixture `scene-objects.test.ts` checks against
 * the published digests, and its normals are made the way `playcanvas@2.21.4` makes them for a
 * container with none (`calculateNormals`), so the defect is the engine's own, reproduced here.
 */

// A path, not a URL: this file runs under happy-dom, whose URL the file system does not take.
const FIXTURES = join(dirname(fileURLToPath(import.meta.url)), '../../graph-client/test/fixtures');

interface Triangles { readonly positions: Float32Array; readonly indices: Uint16Array }

/** The one indexed primitive the reviewed marker containers hold (`exulanica/world/assets.py`). */
function readMarker(key: string): Triangles {
  const bytes = readFileSync(join(FIXTURES, `${key}.glb`));
  const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const jsonLength = data.getUint32(12, true);
  const gltf = JSON.parse(new TextDecoder().decode(bytes.subarray(20, 20 + jsonLength)));
  const binStart = 20 + jsonLength + 8;
  const primitive = gltf.meshes[0].primitives[0];
  const view = (accessorIndex: number) => {
    const accessor = gltf.accessors[accessorIndex];
    const bufferView = gltf.bufferViews[accessor.bufferView];
    return { accessor, start: bytes.byteOffset + binStart + (bufferView.byteOffset ?? 0) };
  };
  const position = view(primitive.attributes.POSITION);
  const index = view(primitive.indices);
  expect(primitive.attributes.NORMAL).toBeUndefined();
  return {
    positions: new Float32Array(bytes.buffer.slice(position.start, position.start + position.accessor.count * 12)),
    indices: new Uint16Array(bytes.buffer.slice(index.start, index.start + index.accessor.count * 2)),
  };
}

const vertexCount = (mesh: Triangles): number => mesh.positions.length / 3;

function world() {
  const canvas = document.createElement('canvas');
  document.body.appendChild(canvas);
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  return { app, device };
}

/** A placed entity holding one mesh, normals made the way the engine makes them for none. */
function placedEntity(app: pc.AppBase, device: pc.GraphicsDevice, marker: Triangles) {
  const mesh = new pc.Mesh(device);
  mesh.setPositions(marker.positions);
  mesh.setNormals(pc.calculateNormals(Array.from(marker.positions), Array.from(marker.indices)));
  mesh.setIndices(marker.indices);
  mesh.update(pc.PRIMITIVE_TRIANGLES);
  const instance = new pc.MeshInstance(mesh, new pc.StandardMaterial());
  const entity = new pc.Entity('authored-object', app);
  entity.addComponent('render', { meshInstances: [instance] });
  return { entity, instance, mesh };
}

describe('the marker plate has no normal to light it by', () => {
  it('as the engine makes normals for a container with none', () => {
    const plate = readMarker('cc0.marker-plate');
    const engine = pc.calculateNormals(Array.from(plate.positions), Array.from(plate.indices));
    // Every vertex sits in an upward and a downward face, so every average is zero.
    expect(engine.every((component) => Number.isNaN(component))).toBe(true);
    expect(normalsUsable(engine, vertexCount(plate))).toBe(false);
  });

  it('while a closed box keeps directions the engine can light', () => {
    for (const key of ['cc0.marker-cube', 'cc0.marker-pillar']) {
      const box = readMarker(key);
      const engine = pc.calculateNormals(Array.from(box.positions), Array.from(box.indices));
      expect(normalsUsable(engine, vertexCount(box))).toBe(true);
    }
  });
});

describe('flat normals follow each face’s winding', () => {
  it('give the plate one face up and one face down, every normal a unit direction', () => {
    const plate = readMarker('cc0.marker-plate');
    const flat = flatNormalGeometry(plate.positions, plate.indices);
    expect(flat.positions.length).toBe(plate.indices.length * 3);
    expect(normalsUsable(flat.normals, plate.indices.length)).toBe(true);
    const faces: number[] = [];
    for (let triangle = 0; triangle < plate.indices.length / 3; triangle += 1) {
      const y = flat.normals[triangle * 9 + 1]!;
      expect(Math.abs(y)).toBeCloseTo(1, 6);
      faces.push(Math.sign(y));
    }
    // The first quad is wound to face down, the second to face up (`_plate`'s two windings).
    expect(faces).toEqual([-1, -1, 1, 1]);
    expect(Array.from(flat.indices)).toEqual(Array.from({ length: plate.indices.length }, (_, i) => i));
  });

  it('carry a texture channel with its vertices', () => {
    const flat = flatNormalGeometry([0, 0, 0, 1, 0, 0, 0, 0, 1], [0, 2, 1], [0, 0, 1, 0, 0, 1]);
    expect(Array.from(flat.uvs!)).toEqual([0, 0, 0, 1, 1, 0]);
    expect(Array.from(flat.normals)).toEqual([0, 1, 0, 0, 1, 0, 0, 1, 0]);
  });
});

describe('a placed object is repaired only where its normals light nothing', () => {
  it('rebuilds the plate for this placement alone', () => {
    const { app, device } = world();
    const placed = placedEntity(app, device, readMarker('cc0.marker-plate'));
    expect(giveFlatNormalsWhereUnusable(device, placed.entity)).toEqual({ rebuilt: 1, unrepairable: 0 });
    expect(placed.instance.mesh).not.toBe(placed.mesh);
    const positions: number[] = [];
    const normals: number[] = [];
    const count = placed.instance.mesh.getPositions(positions);
    placed.instance.mesh.getNormals(normals);
    expect(count).toBe(12);
    expect(normalsUsable(normals, count)).toBe(true);
    // The container's own mesh is not changed under any other placement of the same asset.
    const original: number[] = [];
    placed.mesh.getNormals(original);
    expect(original.every((component) => Number.isNaN(component))).toBe(true);
    app.destroy();
  });

  it('leaves a box exactly as it arrived', () => {
    const { app, device } = world();
    const placed = placedEntity(app, device, readMarker('cc0.marker-cube'));
    expect(giveFlatNormalsWhereUnusable(device, placed.entity)).toEqual({ rebuilt: 0, unrepairable: 0 });
    expect(placed.instance.mesh).toBe(placed.mesh);
    app.destroy();
  });
});

describe('placing an authored object applies the repair', () => {
  it('draws the reviewed plate with the rebuilt mesh, and says nothing about it', async () => {
    const { app, device } = world();
    const bytes = readFileSync(join(FIXTURES, 'cc0.marker-plate.glb'));
    const container = Uint8Array.from(bytes).buffer;
    const drawn = placedEntity(app, device, readMarker('cc0.marker-plate'));
    const registry = { fire: vi.fn(), _loader: { clearCache: vi.fn() } };
    // The container decoder is the engine's; what it hands back is the plate as it decodes it.
    const assets = {
      add: vi.fn((asset: pc.Asset) => { (asset as { registry: unknown }).registry = registry; }),
      remove: vi.fn(),
      load: vi.fn((asset: pc.Asset) => {
        asset.resource = { instantiateRenderEntity: () => drawn.entity, destroy: vi.fn() } as never;
        asset.fire('load', asset);
      }),
    };
    const island = 'region-a' as IslandId;
    const runtime = new SceneObjectRuntime(
      { assets, graphicsDevice: device } as unknown as pc.AppBase,
      new Map([[island, new pc.Entity('region', app)]]),
    );
    const outcome = await runtime.place({
      objectId: 'object:plate',
      islandId: island,
      asset: {
        assetKey: 'cc0.marker-plate',
        mediaType: AUTHORED_OBJECT_MEDIA_TYPE,
        contentSha256: createHash('sha256').update(bytes).digest('hex'),
        byteSize: bytes.byteLength,
      },
      transform: { xMm: 0, yMm: 0, zMm: 0, yawMicroradians: 0, scaleMilli: 1000 },
      behaviour: null,
    }, container);
    expect(outcome.notices).toEqual([]);
    expect(drawn.instance.mesh).not.toBe(drawn.mesh);
    const normals: number[] = [];
    const count = drawn.instance.mesh.getNormals(normals);
    expect(normalsUsable(normals, count)).toBe(true);
    runtime.destroy();
    app.destroy();
  });
});
