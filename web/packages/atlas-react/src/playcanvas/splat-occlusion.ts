/**
 * THE LAYOUT AS DEPTH ONLY. A painted world is a gaussian splat drawn over an invisible layout: the
 * town's ordinary meshes, which people walk on and pick. Splats are blended and write no depth, so
 * without help a person behind a painted wall shows through the wall's thin splats, and a pass that
 * tests the scene's depth (the ring at a chosen person's feet) finds no wall there.
 *
 * - Every opaque mesh instance under the roots draws with a depth-only copy of its material: colour
 *   writes off, depth tested and written, in the opaque pass. People (opaque, writing depth) and the
 *   splats (blended, depth tested) both test against it, so the wall covers what stands behind it.
 * - It draws before the rest of its layer's opaque surfaces. A person drawn before a depth-only wall
 *   keeps its colour, since the wall writes none to cover it. Which bucket draws first depends on the
 *   layer's sort: the engine's material-and-mesh and back-to-front sorts draw the highest bucket first,
 *   its front-to-back sort the lowest.
 * - The copy is pushed a little back from the eye (`SPLAT_OCCLUSION`), so splats lying on the wall's
 *   own surface are not hidden by the wall they paint. A splat is drawn at its gaussian's centre, and
 *   a centre may sit its own size behind the face it paints, so the push is in metres: each vertex
 *   moves `pushMetres` away from the eye along its view ray, at the end of the vertex stage, where the
 *   world position is final (skinned and instanced pieces included). The depth bias adds its steps.
 * - The push applies in the forward pass and the prepass, so the linear depth a prepass writes is the
 *   depth the copy tests with. It does not apply in the shadow pass, whose eye is the light, nor in
 *   the pick pass, so a pick lands on the surface itself. GLSL only; the app draws with WebGL.
 * - One copy per distinct source material, shared by every instance that used it. The source
 *   material, often shared with a library, is never changed.
 * - Transparent materials (glass, water, decals: blended, or writing no depth) are left as they are:
 *   they write no depth now and do not start.
 * - A frame's depth prepass draws the copy too, and it must write the scene's linear depth as a
 *   colour. The copies write colour from the start of every frame until a scene layer is drawn, and
 *   again after each, so a prepass leaves the layout's depth (contact shadows and the ring see it)
 *   and no scene layer shows its colour.
 * - The sky draws before the world (`skyFirst`): it writes no depth and lies at the far plane, so
 *   drawn after the layout it would be hidden wherever the layout stands, and a hole in the splat
 *   would show the clear colour. Drawn first, everything after covers it and a hole shows sky. The
 *   cost is a sky drawn under every pixel. A camera frame that grabs the scene's colour (refraction)
 *   grabs at the end of the sky's layer, which would then hold the sky alone.
 * - Shadow casting is left as it was; the shadow pass sets its own colour writes.
 * - The app is the one the roots' render components belong to, unless given.
 */
import * as pc from 'playcanvas';

/** How the layout draws: how far back it is pushed, and where it draws among opaque surfaces. */
export interface SplatOcclusionLook {
  readonly pushMetres: number;
  readonly depthBias: number;
  readonly slopeDepthBias: number;
  readonly drawBucket: number | 'first';
}

/** The layout's defaults, each one a caller may replace for its world. */
export const SPLAT_OCCLUSION: SplatOcclusionLook = Object.freeze({
  /** Metres, about a painted gaussian's size, so splats whose centres sit just behind a wall's face still draw. */
  pushMetres: 0.3,
  /** Depth-buffer steps, so a splat whose centre sits on the wall's face, or a hair behind it, still draws. */
  depthBias: 4,
  /** Times the wall's depth slope across a pixel, so a splat a few pixels wide on a wall seen at an angle is not cut. */
  slopeDepthBias: 8,
  /** The bucket its layer's sort draws first, so no opaque surface keeps colour that a wall in front should hide. */
  drawBucket: 'first',
});

export interface LayoutDepthOnly {
  /** How many mesh instances draw depth only now. */
  readonly instances: number;
  /** Makes mesh instances added under the roots since (a tile streamed in) depth only too. */
  refresh(): void;
  /** Gives every mesh instance its own material and bucket back, destroys the copies and puts the sky back. */
  dispose(): void;
}

/** Whether `material` writes depth as an opaque surface does; transparent ones are left as they are. */
function writesOpaqueDepth(material: pc.Material): boolean {
  return material.blendType === pc.BLEND_NONE && material.depthWrite;
}

function writeColour(material: pc.Material, on: boolean): void {
  material.redWrite = on;
  material.greenWrite = on;
  material.blueWrite = on;
  material.alphaWrite = on;
}

/** The uniform holding the push in metres. */
export const SPLAT_OCCLUSION_PUSH_UNIFORM = 'splatOcclusion_pushMetres';

/** Declares the push and the eye's position for the vertex stage. */
const PUSH_DECLARATION_GLSL = `
uniform vec3 view_position;
uniform float ${SPLAT_OCCLUSION_PUSH_UNIFORM};
`;

/** Moves the finished world position away from the eye and projects it again, outside shadow and pick passes. */
const PUSH_MAIN_END_GLSL = `
#if !defined(SHADOW_PASS) && !defined(PICK_PASS) && !defined(SCREENSPACE) && !defined(UV1LAYOUT) && !defined(PIXELSNAP)
	vPositionW += normalize(vPositionW - view_position) * ${SPLAT_OCCLUSION_PUSH_UNIFORM};
	gl_Position = matrix_viewProjection * vec4(vPositionW, 1.0);
	#ifdef LINEAR_DEPTH
		vLinearDepth = -(matrix_view * vec4(vPositionW, 1.0)).z;
	#endif
#endif
`;

/** Adds the push to `material`'s vertex stage, after any user code it already has there. */
function pushBack(material: pc.Material, metres: number): void {
  if (metres === 0) return;
  const chunks = material.getShaderChunks(pc.SHADERLANGUAGE_GLSL);
  chunks.set('litUserDeclarationVS', (chunks.get('litUserDeclarationVS') ?? '') + PUSH_DECLARATION_GLSL);
  chunks.set('litUserMainEndVS', (chunks.get('litUserMainEndVS') ?? '') + PUSH_MAIN_END_GLSL);
  material.setParameter(SPLAT_OCCLUSION_PUSH_UNIFORM, metres);
}

/** The depth-only copy of `source`: no colour, depth tested and written, opaque, pushed back by `look`. */
function depthOnlyMaterial(source: pc.Material, look: SplatOcclusionLook): pc.Material {
  const material = source.clone();
  material.name = `${source.name}:depth-only`;
  writeColour(material, false);
  material.depthTest = true;
  material.depthWrite = true;
  material.blendType = pc.BLEND_NONE;
  material.depthBias = look.depthBias;
  material.slopeDepthBias = look.slopeDepthBias;
  pushBack(material, look.pushMetres);
  material.update();
  return material;
}

/** The bucket `render`'s first layer draws first among its opaque surfaces. */
function firstBucket(render: pc.RenderComponent, app: pc.AppBase): number {
  const layer = app.scene.layers.getLayerById(render.layers[0] ?? pc.LAYERID_WORLD);
  return layer?.opaqueSortMode === pc.SORTMODE_FRONT2BACK ? 0 : 255;
}

/** Each layer composition's sky moved before its world, held while any layout asks for it. */
const skyMoves = new WeakMap<pc.LayerComposition, { holders: number; restore: () => void }>();

/** Tells every camera its layers changed, so a camera frame lays out its passes in the new order. */
function relayCameras(app: pc.AppBase): void {
  for (const camera of app.systems.camera?.cameras ?? []) camera.layers = [...camera.layers];
}

/** Draws the sky's opaque layer before the world's, until the returned function is called. */
function holdSkyFirst(app: pc.AppBase): () => void {
  const layers = app.scene.layers;
  const held = skyMoves.get(layers);
  const release = (): void => {
    const move = skyMoves.get(layers);
    if (move === undefined || (move.holders -= 1) > 0) return;
    skyMoves.delete(layers);
    move.restore();
  };
  if (held !== undefined) {
    held.holders += 1;
    return release;
  }
  const sky = layers.getLayerById(pc.LAYERID_SKYBOX);
  const world = layers.getLayerById(pc.LAYERID_WORLD);
  const from = sky === null ? -1 : layers.getOpaqueIndex(sky);
  const to = world === null ? -1 : layers.getOpaqueIndex(world);
  if (sky === null || from < 0 || to < 0 || from < to) {
    skyMoves.set(layers, { holders: 1, restore: () => {} });
    return release;
  }
  // The sublayer the sky followed, so it goes back after it even if layers were added since.
  const after = { layer: layers.layerList[from - 1], transparent: layers.subLayerList[from - 1] };
  layers.removeOpaque(sky);
  layers.insertOpaque(sky, to);
  relayCameras(app);
  skyMoves.set(layers, {
    holders: 1,
    restore: () => {
      if (layers.getOpaqueIndex(sky) < 0) return;
      layers.removeOpaque(sky);
      const at = layers.layerList.findIndex((layer, index) =>
        layer === after.layer && layers.subLayerList[index] === after.transparent);
      layers.insertOpaque(sky, at < 0 ? Math.min(from, layers.layerList.length) : at + 1);
      relayCameras(app);
    },
  });
  return release;
}

/**
 * Makes every opaque render mesh instance under `root` (one entity or several) draw depth only, until
 * disposed. `filter` leaves out the instances it returns false for.
 */
export function layoutDepthOnly(
  root: pc.Entity | readonly pc.Entity[],
  { look = SPLAT_OCCLUSION, filter, app: given, skyFirst = true }: {
    readonly look?: SplatOcclusionLook;
    readonly filter?: (instance: pc.MeshInstance) => boolean;
    readonly app?: pc.AppBase;
    readonly skyFirst?: boolean;
  } = {},
): LayoutDepthOnly {
  const roots: readonly pc.Entity[] = Array.isArray(root) ? root : [root as pc.Entity];
  const copies = new Map<pc.Material, pc.Material>();
  const ownCopies = new Set<pc.Material>();
  const originals = new Map<pc.MeshInstance, { readonly material: pc.Material; readonly bucket: number }>();
  let app: pc.AppBase | null = null;
  let releaseSky: (() => void) | null = null;
  let disposed = false;

  // Colour on while no scene layer is drawn (a prepass writes linear depth as colour), off while one is.
  const colour = (on: boolean) => (): void => { for (const copy of ownCopies) writeColour(copy, on); };
  const on = colour(true);
  const off = colour(false);
  const attach = (to: pc.AppBase): void => {
    if (app !== null) return;
    app = to;
    app.on('prerender', on);
    app.scene.on(pc.EVENT_PRERENDER_LAYER, off);
    app.scene.on(pc.EVENT_POSTRENDER_LAYER, on);
    app.on('postrender', off);
    if (skyFirst) releaseSky = holdSkyFirst(app);
  };
  if (given !== undefined) attach(given);

  const refresh = (): void => {
    if (disposed) return;
    for (const render of roots.flatMap((one) => one.findComponents('render') as pc.RenderComponent[])) {
      attach(render.system.app);
      for (const instance of render.meshInstances) {
        const source = instance.material;
        if (source === null || ownCopies.has(source) || !writesOpaqueDepth(source)) continue;
        if (filter !== undefined && !filter(instance)) continue;
        let copy = copies.get(source);
        if (copy === undefined) {
          copy = depthOnlyMaterial(source, look);
          copies.set(source, copy);
          ownCopies.add(copy);
        }
        originals.set(instance, { material: source, bucket: instance.drawBucket });
        instance.drawBucket = look.drawBucket === 'first' ? firstBucket(render, app!) : look.drawBucket;
        instance.material = copy;
      }
    }
  };

  refresh();
  return {
    get instances() { return originals.size; },
    refresh,
    dispose() {
      if (disposed) return;
      disposed = true;
      if (app !== null) {
        app.off('prerender', on);
        app.scene.off(pc.EVENT_PRERENDER_LAYER, off);
        app.scene.off(pc.EVENT_POSTRENDER_LAYER, on);
        app.off('postrender', off);
      }
      releaseSky?.();
      for (const [instance, { material, bucket }] of originals) {
        if (instance.material === null || !ownCopies.has(instance.material)) continue;
        instance.drawBucket = bucket;
        instance.material = material;
      }
      originals.clear();
      for (const copy of ownCopies) copy.destroy();
      ownCopies.clear();
      copies.clear();
    },
  };
}
