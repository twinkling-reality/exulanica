import * as pc from 'playcanvas';
import {
  dataViewRgb,
  dataViewKindColour,
  type DataViewStyle,
  type RepresentationSubject,
} from '@exulanica/atlas-core';
import type { RepresentationReport } from '../representation-runtime.js';
import { DATA_VIEW_TIME_UNIFORM } from './points.js';
import {
  BOX_EDGES,
  TOP_CORNERS,
  planDataViewOverlay,
  type DataViewOverlayPlan,
  type OverlayTag,
  type WorldCorners,
} from './overlay-plan.js';

/**
 * The data view's non-pickable overlay: thin boxes, links and tags, and the dark ground.
 *
 * Nothing here is a pick target or a scene record. Boxes and links are immediate lines, rebuilt
 * only on frames the host actually draws and cleared by the engine after them. Tags are text on a
 * 2D canvas laid over the world canvas with `pointer-events: none`, so selection stays in the
 * panel's subject list, which is also the only route an agent without pointer lock can reach.
 *
 * The dark ground is one full-screen triangle at the far plane, depth-tested, drawn first among
 * transparent draws. It therefore lands only where nothing opaque stands and before any fading
 * surface or point, so it darkens the sky and whatever a faded surface shows through, and never
 * a surface that keeps its own appearance. At the rendered end it is switched off entirely.
 */

export interface DataViewOverlayHost {
  readonly device: pc.GraphicsDevice;
  readonly app: pc.AppBase;
  readonly camera: pc.Entity;
  report(): RepresentationReport;
  worldBounds(subject: RepresentationSubject): WorldCorners | null;
  reducedMotion(): boolean;
  /** Ask for the next frame to be drawn. */
  invalidate(): void;
}

const VEIL_VERTEX_GLSL = /* glsl */ `
attribute vec3 aPosition;
void main(void) {
    gl_Position = vec4(aPosition.xy, 1.0, 1.0);
}
`;
const VEIL_FRAGMENT_GLSL = /* glsl */ `
precision highp float;
uniform vec4 uGround;
void main(void) {
    gl_FragColor = uGround;
}
`;
const VEIL_VERTEX_WGSL = /* wgsl */ `
attribute aPosition : vec3f;
@vertex
fn vertexMain(input : VertexInput) -> VertexOutput {
    var output : VertexOutput;
    output.position = vec4f(aPosition.xy, 1.0, 1.0);
    return output;
}
`;
const VEIL_FRAGMENT_WGSL = /* wgsl */ `
uniform uGround : vec4f;
@fragment
fn fragmentMain(input : FragmentInput) -> FragmentOutput {
    var output : FragmentOutput;
    output.color = uniform.uGround;
    return output;
}
`;

/** Ahead of every real distance and below the draw bucket step, so the veil sorts first. */
const VEIL_SORT_DISTANCE = 1e8;

interface Veil { entity: pc.Entity; mesh: pc.Mesh; material: pc.ShaderMaterial; colour: Float32Array }
interface TagSurface { canvas: HTMLCanvasElement; context: CanvasRenderingContext2D }

export class DataViewOverlay {
  readonly #host: DataViewOverlayHost;
  readonly #style: DataViewStyle;
  #veil: Veil | null = null;
  #tags: TagSurface | null = null;
  #tagsShown = false;
  #plan: DataViewOverlayPlan | null = null;
  #destroyed = false;
  readonly #positions: number[] = [];
  readonly #colours: number[] = [];
  readonly #onPrerender = (): void => this.frame();

  constructor(host: DataViewOverlayHost, style: DataViewStyle) {
    this.#host = host;
    this.#style = style;
    host.app.on('prerender', this.#onPrerender);
    // The tag surface lives in the document, outside the engine; it leaves with the app.
    host.app.once('destroy', () => this.destroy());
  }

  /** The last plan drawn, for the panel and for tests. */
  get plan(): DataViewOverlayPlan | null { return this.#plan; }

  /** Runs inside the host's render, before culling: everything drawn here is in this frame. */
  frame(): void {
    if (this.#destroyed) return;
    const report = this.#host.report();
    const plan = planDataViewOverlay(report, subject => this.#host.worldBounds(subject), this.#style);
    this.#plan = plan;
    this.#ground(plan.groundWeight);
    this.#lines(plan);
    this.#drawTags(plan.tags, report);
    const dashing = report.subjects.some(entry => entry.resolved.binary && entry.allocatedPoints > 0
      && entry.resolved.pointWeight > 0);
    const moving = dashing && this.#style.dashes.bandsPerSecond > 0 && !this.#host.reducedMotion();
    const time = moving ? (performance.now() / 1000) * this.#style.dashes.bandsPerSecond : 0;
    this.#host.device.scope.resolve(DATA_VIEW_TIME_UNIFORM).setValue(time % 1024);
    // A moving band needs the next frame drawn too; a still view draws only when something changes.
    if (moving) this.#host.invalidate();
  }

  destroy(): void {
    if (this.#destroyed) return;
    this.#destroyed = true;
    this.#host.app.off('prerender', this.#onPrerender);
    if (this.#veil !== null) {
      this.#veil.entity.destroy();
      this.#veil.mesh.destroy();
      this.#veil.material.destroy();
      this.#veil = null;
    }
    this.#tags?.canvas.remove();
    this.#tags = null;
  }

  #ground(weight: number): void {
    if (weight <= 0) {
      if (this.#veil !== null) this.#veil.entity.enabled = false;
      return;
    }
    const veil = this.#veil ?? this.#createVeil();
    const [r, g, b] = dataViewRgb(this.#style.ground.colour);
    veil.colour[0] = r; veil.colour[1] = g; veil.colour[2] = b; veil.colour[3] = Math.min(1, weight);
    veil.material.setParameter('uGround', veil.colour);
    veil.entity.enabled = true;
  }

  #createVeil(): Veil {
    const { device, app } = this.#host;
    const mesh = new pc.Mesh(device);
    mesh.setPositions([-1, -1, 0, 3, -1, 0, -1, 3, 0]);
    mesh.update(pc.PRIMITIVE_TRIANGLES);
    const material = new pc.ShaderMaterial({
      uniqueName: 'exulanica-data-view-ground',
      attributes: { aPosition: pc.SEMANTIC_POSITION },
      vertexGLSL: VEIL_VERTEX_GLSL,
      fragmentGLSL: VEIL_FRAGMENT_GLSL,
      vertexWGSL: VEIL_VERTEX_WGSL,
      fragmentWGSL: VEIL_FRAGMENT_WGSL,
    } as ConstructorParameters<typeof pc.ShaderMaterial>[0]);
    material.blendType = pc.BLEND_NORMAL;
    material.depthWrite = false;
    material.depthTest = true;
    material.cull = pc.CULLFACE_NONE;
    const colour = new Float32Array(4);
    material.setParameter('uGround', colour);
    material.update();
    const entity = new pc.Entity('data-view-ground');
    const instance = new pc.MeshInstance(mesh, material, entity);
    instance.cull = false;
    instance.pick = false;
    instance.castShadow = false;
    instance.receiveShadow = false;
    instance.calculateSortDistance = () => VEIL_SORT_DISTANCE;
    entity.addComponent('render', {
      meshInstances: [instance],
      castShadows: false,
      receiveShadows: false,
      layers: [pc.LAYERID_WORLD],
    });
    app.root.addChild(entity);
    this.#veil = { entity, mesh, material, colour };
    return this.#veil;
  }

  #lines(plan: DataViewOverlayPlan): void {
    if (plan.boxes.length === 0 && plan.links.length === 0) return;
    const positions = this.#positions;
    const colours = this.#colours;
    positions.length = 0;
    colours.length = 0;
    const boxes = this.#style.boxes;
    const fraction = boxes.cornerFraction;
    const [br, bg, bb] = dataViewRgb(boxes.colour);
    const [sr, sg, sb] = dataViewRgb(boxes.selectedColour);
    for (const box of plan.boxes) {
      const colour = box.selected ? [sr, sg, sb, boxes.selectedOpacity] : [br, bg, bb, boxes.opacity];
      for (const [from, to] of BOX_EDGES) {
        const a = box.corners[from]!;
        const b = box.corners[to]!;
        if (fraction >= 1) {
          positions.push(a[0], a[1], a[2], b[0], b[1], b[2]);
          colours.push(...colour, ...colour);
        } else {
          for (const [p, q] of [[a, b], [b, a]] as const) {
            positions.push(p[0], p[1], p[2],
              p[0] + (q[0] - p[0]) * fraction, p[1] + (q[1] - p[1]) * fraction, p[2] + (q[2] - p[2]) * fraction);
            colours.push(...colour, ...colour);
          }
        }
      }
    }
    const [lr, lg, lb] = dataViewRgb(this.#style.links.colour);
    for (const link of plan.links) {
      positions.push(...link.start, ...link.end);
      colours.push(lr, lg, lb, this.#style.links.opacity, lr, lg, lb, this.#style.links.opacity);
    }
    this.#host.app.drawLineArrays(positions, colours, true);
  }

  #drawTags(tags: readonly OverlayTag[], report: RepresentationReport): void {
    const canvas = this.#host.device.canvas;
    if (tags.length === 0 || typeof document === 'undefined' || !(canvas instanceof HTMLCanvasElement)
      || canvas.parentElement === null) {
      if (this.#tagsShown && this.#tags !== null) {
        this.#tags.canvas.hidden = true;
        this.#tagsShown = false;
      }
      return;
    }
    const surface = this.#tags ?? this.#createTagSurface(canvas);
    if (surface === null) return;
    const rect = canvas.getBoundingClientRect();
    const ratio = Math.min(2, globalThis.devicePixelRatio ?? 1);
    const width = Math.max(1, Math.round(rect.width * ratio));
    const height = Math.max(1, Math.round(rect.height * ratio));
    const element = surface.canvas;
    if (element.width !== width || element.height !== height) { element.width = width; element.height = height; }
    element.style.left = `${rect.left}px`;
    element.style.top = `${rect.top}px`;
    element.style.width = `${rect.width}px`;
    element.style.height = `${rect.height}px`;
    element.hidden = false;
    this.#tagsShown = true;
    const context = surface.context;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, rect.width, rect.height);
    const camera = this.#host.camera.camera;
    if (camera === undefined || camera === null) return;
    const viewProjection = new pc.Mat4().mul2(camera.projectionMatrix, camera.viewMatrix);
    const style = this.#style.tags;
    const size = style.fontSizePixels;
    context.font = `${size}px ${style.fontFamily}`;
    context.textBaseline = 'top';
    const placed: { x: number; y: number; w: number; h: number }[] = [];
    const candidates: { tag: OverlayTag; x: number; y: number; depth: number }[] = [];
    for (const tag of tags) {
      const anchor = topAnchor(tag.corners, viewProjection, rect.width, rect.height);
      if (anchor !== null) candidates.push({ tag, ...anchor });
    }
    candidates.sort((a, b) => Number(b.tag.selected) - Number(a.tag.selected) || a.depth - b.depth);
    const [tr, tg, tb] = dataViewRgb(style.textColour);
    const [gr, gg, gb] = dataViewRgb(style.backgroundColour);
    const palette = this.#style.palette;
    const selectedColour = this.#style.boxes.selectedColour;
    let drawn = 0;
    for (const { tag, x, y } of candidates) {
      if (drawn >= style.maxCount) break;
      const pad = 3;
      const lineHeight = Math.round(size * 1.3);
      const w = Math.ceil(Math.max(...tag.lines.map(line => context.measureText(line).width))) + pad * 2 + 3;
      const h = tag.lines.length * lineHeight + pad * 2 - (lineHeight - size);
      const left = Math.round(x);
      const top = Math.round(y - h - 2);
      if (left > rect.width || top > rect.height || left + w < 0 || top + h < 0) continue;
      if (!tag.selected && placed.some(box => left < box.x + box.w && left + w > box.x
        && top < box.y + box.h && top + h > box.y)) continue;
      placed.push({ x: left, y: top, w, h });
      drawn += 1;
      const key = tag.colourKey;
      const accent = tag.selected ? selectedColour
        : report.intent.colour === 'origin'
          ? palette.origin[key as keyof typeof palette.origin] ?? selectedColour
          : dataViewKindColour(this.#style, key) ?? selectedColour;
      context.fillStyle = `rgba(${gr * 255}, ${gg * 255}, ${gb * 255}, ${style.backgroundOpacity})`;
      context.fillRect(left, top, w, h);
      context.fillStyle = accent;
      context.fillRect(left, top, 2, h);
      context.fillRect(left, top + h, 1, 3);
      tag.lines.forEach((line, index) => {
        context.fillStyle = index === 0
          ? accent
          : `rgb(${tr * 255}, ${tg * 255}, ${tb * 255})`;
        context.fillText(line, left + pad + 3, top + pad + index * lineHeight);
      });
    }
  }

  #createTagSurface(worldCanvas: HTMLCanvasElement): TagSurface | null {
    const element = document.createElement('canvas');
    element.className = 'data-view-tags';
    element.setAttribute('aria-hidden', 'true');
    element.style.position = 'fixed';
    element.style.pointerEvents = 'none';
    element.style.zIndex = getComputedStyle(worldCanvas).zIndex;
    const context = element.getContext('2d');
    if (context === null) return null;
    worldCanvas.after(element);
    this.#tags = { canvas: element, context };
    return this.#tags;
  }
}

/** The highest on-screen top corner in front of the camera, in CSS pixels, or null. */
function topAnchor(
  corners: WorldCorners, viewProjection: pc.Mat4, width: number, height: number,
): { x: number; y: number; depth: number } | null {
  const m = viewProjection.data;
  let best: { x: number; y: number; depth: number } | null = null;
  for (const index of TOP_CORNERS) {
    const [px, py, pz] = corners[index]!;
    const w = m[3]! * px + m[7]! * py + m[11]! * pz + m[15]!;
    if (!(w > 0.05)) continue;
    const cx = (m[0]! * px + m[4]! * py + m[8]! * pz + m[12]!) / w;
    const cy = (m[1]! * px + m[5]! * py + m[9]! * pz + m[13]!) / w;
    const x = (cx + 1) * 0.5 * width;
    const y = (1 - cy) * 0.5 * height;
    if (best === null || y < best.y || (y === best.y && x < best.x)) best = { x, y, depth: w };
  }
  return best;
}
