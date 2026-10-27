import * as pc from 'playcanvas';
import { dataViewRgb, type DataViewHex, type DataViewStyle } from '@exulanica/atlas-core';

/**
 * Skinned surfaces in the data view, such as walkers' bodies: each one's own vertices, every `stride`-th of them,
 * drawn as points through its own bones and shapes, so a walker walks as points.
 *
 * THE WALKER'S OWN DRAW, AS POINTS. The points read the source's vertex buffer and share its skin and morph instances
 * (the same bone texture and shape weights it is drawn with this frame); only an index buffer of the vertices drawn is
 * the group's own, one for each vertex count. Nothing of the source is copied, moved or changed, and letting go of the
 * points lets go of nothing of the source: the shared skin and morph instances are handed back untouched, since the
 * engine's mesh instance would otherwise destroy them with itself. A walker who goes (out of the town, or to the far
 * body they are drawn with from afar) takes their skin with them: just before every frame is drawn the group looks,
 * and lets go of a source's points the moment it is no longer drawn by that skin, before the engine could draw a skin
 * that is gone.
 *
 * One standard material draws every source in the group, so skinning and morphing are the engine's own: unlit, the
 * group's colour, added to what is behind it, and from the end of its vertex stage drawn `pullMetres` toward the eye
 * (so a point is not hidden by the darkened surface it stands on) at a width of `sizeMetres` seen through the camera,
 * between the style's `minPixels` and `maxPixels` (or the narrower `maxPixels` given), each a soft round dot, at
 * `gain` of the style's brightness.
 */
export interface DataViewSkinnedPoints {
  readonly pointCount: number;
  /** Whether the points are let go of: destroyed, or their source gone. */
  readonly gone: boolean;
  /** Whether the source is drawn now: its points are drawn only while it is. */
  setShown(shown: boolean): void;
  destroy(): void;
}

export interface DataViewSkinnedGroup {
  /** A skinned source's points, or null for a source with no skin or no vertices. */
  add(source: pc.MeshInstance): DataViewSkinnedPoints | null;
  /** The slider's weight for every source in the group: 0 hides them all. */
  setWeight(weight: number): void;
  destroy(): void;
}

export interface DataViewSkinnedGroupOptions {
  readonly app: pc.AppBase;
  readonly device: pc.GraphicsDevice;
  /** The layer the points are drawn in: the sources' own. */
  readonly layer: pc.Layer;
  readonly colour: DataViewHex;
  readonly style: DataViewStyle;
  /** The camera's pixels to a radian on the drawing buffer, as the point shader counts them. */
  readonly pixels: number;
  readonly stride?: number;
  readonly sizeMetres?: number;
  readonly maxPixels?: number;
  readonly pullMetres?: number;
  /** How bright the points are beside the style's own, 0 to 1. */
  readonly gain?: number;
}

/** The uniform the points' vertex stage reads: x pull in metres, y width in metres times pixels, z and w its limits. */
export const DATA_VIEW_SKIN_UNIFORM = 'uDataViewSkin';

const DECLARATION_GLSL = `
uniform vec3 view_position;
uniform vec4 ${DATA_VIEW_SKIN_UNIFORM};
`;

const MAIN_END_GLSL = `
#if !defined(SHADOW_PASS) && !defined(PICK_PASS) && !defined(SCREENSPACE) && !defined(UV1LAYOUT) && !defined(PIXELSNAP)
	float skinAway = max(length(view_position - vPositionW), 0.001);
	vPositionW += (view_position - vPositionW) * (${DATA_VIEW_SKIN_UNIFORM}.x / skinAway);
	gl_Position = matrix_viewProjection * vec4(vPositionW, 1.0);
	gl_PointSize = clamp(${DATA_VIEW_SKIN_UNIFORM}.y / skinAway, ${DATA_VIEW_SKIN_UNIFORM}.z, ${DATA_VIEW_SKIN_UNIFORM}.w);
#endif
`;

/** Each point a soft round dot, as the town's are: brightest at its middle, nothing past its edge. */
const MAIN_END_PS_GLSL = `
#if !defined(SHADOW_PASS) && !defined(PICK_PASS) && !defined(PREPASS_PASS)
	vec2 skinDot = gl_PointCoord * 2.0 - 1.0;
	float skinR2 = dot(skinDot, skinDot);
	if (skinR2 > 1.0) discard;
	gl_FragColor.rgb *= smoothstep(1.0, 0.15, skinR2);
#endif
`;

/** A group of skinned sources drawn as points by one material. */
export function createDataViewSkinnedGroup(options: DataViewSkinnedGroupOptions): DataViewSkinnedGroup {
  const { app, device, layer, colour, style, pixels } = options;
  const stride = Math.max(1, Math.floor(options.stride ?? 3));
  const material = new pc.StandardMaterial();
  material.name = 'data-view-skinned-points';
  material.useLighting = false;
  material.useFog = false;
  material.useSkybox = false;
  material.diffuse.set(0, 0, 0);
  const [r, g, b] = dataViewRgb(colour);
  material.emissive.set(r, g, b);
  material.emissiveIntensity = 0;
  material.blendType = pc.BLEND_ADDITIVE;
  material.depthWrite = false;
  material.depthTest = true;
  material.cull = pc.CULLFACE_NONE;
  const chunks = material.getShaderChunks(pc.SHADERLANGUAGE_GLSL);
  chunks.set('litUserDeclarationVS', DECLARATION_GLSL);
  chunks.set('litUserMainEndVS', MAIN_END_GLSL);
  chunks.set('litUserMainEndPS', MAIN_END_PS_GLSL);
  const size = options.sizeMetres ?? style.points.sizeMetres;
  const most = Math.max(style.points.minPixels, Math.min(style.points.maxPixels, options.maxPixels ?? style.points.maxPixels));
  material.setParameter(DATA_VIEW_SKIN_UNIFORM, [options.pullMetres ?? 0.01, size * pixels, style.points.minPixels, most]);
  material.update();

  /** One index buffer for every source with the same vertex count. */
  const indexBuffers = new Map<number, { buffer: pc.IndexBuffer; count: number }>();
  const indicesFor = (vertexCount: number): { buffer: pc.IndexBuffer; count: number } => {
    const held = indexBuffers.get(vertexCount);
    if (held !== undefined) return held;
    const count = Math.ceil(vertexCount / stride);
    const indices = new Uint32Array(count);
    for (let at = 0; at < count; at += 1) indices[at] = at * stride;
    const made = { buffer: new pc.IndexBuffer(device, pc.INDEXFORMAT_UINT32, count, pc.BUFFER_STATIC, indices.buffer), count };
    indexBuffers.set(vertexCount, made);
    return made;
  };

  interface Member { readonly source: pc.MeshInstance; readonly skin: pc.SkinInstance; readonly mesh: pc.Mesh; readonly instance: pc.MeshInstance; shown: boolean; gone: boolean }
  const members = new Set<Member>();
  let weight = 0, destroyed = false;
  const visible = (member: Member): boolean => weight > 0 && member.shown;

  const release = (member: Member): void => {
    if (member.gone) return;
    member.gone = true;
    members.delete(member);
    layer.removeMeshInstances([member.instance]);
    // The skin and morph instances are the source's, and the index buffer the group's: handed back before the engine
    // would destroy them with this mesh instance and its mesh.
    const own = member.instance as unknown as { _skinInstance: unknown; _morphInstance: unknown };
    own._skinInstance = null;
    own._morphInstance = null;
    member.mesh.vertexBuffer = null as unknown as pc.VertexBuffer;
    member.mesh.indexBuffer.length = 0;
    member.mesh.morph = null;
    member.instance.destroy();
  };

  // Just before each frame is drawn: a source destroyed, or drawn by another skin, takes its points with it.
  const look = (): void => {
    for (const member of members) {
      if (member.source.mesh === null || member.source.skinInstance !== member.skin || member.skin.boneTexture === null) release(member);
    }
  };
  app.on('prerender', look);

  return {
    add(source) {
      const vertexBuffer = source.mesh?.vertexBuffer ?? null;
      const vertexCount = vertexBuffer?.numVertices ?? 0;
      const skin = source.skinInstance;
      if (destroyed || skin === null || skin === undefined || vertexBuffer === null || vertexCount < 1) return null;
      const indices = indicesFor(vertexCount);
      const mesh = new pc.Mesh(device);
      mesh.vertexBuffer = vertexBuffer;
      mesh.indexBuffer[0] = indices.buffer;
      mesh.primitive[0] = { type: pc.PRIMITIVE_POINTS, base: 0, baseVertex: 0, count: indices.count, indexed: true };
      mesh.skin = source.mesh.skin;
      mesh.morph = source.mesh.morph;
      mesh.aabb = source.mesh.aabb;
      const instance = new pc.MeshInstance(mesh, material, source.node);
      instance.skinInstance = skin;
      if (source.morphInstance) instance.morphInstance = source.morphInstance;
      // The source's bounds move with its bones; the points are drawn wherever it is.
      instance.cull = false;
      instance.pick = false;
      instance.castShadow = false;
      instance.receiveShadow = false;
      const member: Member = { source, skin, mesh, instance, shown: true, gone: false };
      instance.visible = visible(member);
      members.add(member);
      layer.addMeshInstances([instance]);
      return {
        pointCount: indices.count,
        get gone() { return member.gone; },
        setShown(next) {
          if (member.gone || next === member.shown) return;
          member.shown = next;
          member.instance.visible = visible(member);
        },
        destroy: () => release(member),
      };
    },
    setWeight(next) {
      if (destroyed || next === weight) return;
      weight = next;
      material.emissiveIntensity = Math.min(1, weight * style.points.rise) * style.points.intensity * Math.min(1, Math.max(0, options.gain ?? 1));
      material.update();
      for (const member of members) member.instance.visible = visible(member);
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      app.off('prerender', look);
      for (const member of [...members]) release(member);
      for (const { buffer } of indexBuffers.values()) buffer.destroy();
      indexBuffers.clear();
      material.destroy();
    },
  };
}
