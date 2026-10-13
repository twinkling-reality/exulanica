import type { CapabilityConcept } from '../content/product.js';
import { CAPABILITY_PARTICLES, CAPABILITY_SCENES } from '../content/capability-scenes.js';
import { CAPABILITY_MOTION, capabilityEase } from './capability-sequence.js';
import '../concept-diagrams.css';

const SVG_NS = 'http://www.w3.org/2000/svg';
export type CapabilityPointer = { x: number; y: number } | null;
export type CapabilityPose = ReadonlyArray<{ x: number; y: number; radius: number; opacity: number; color: string }>;
type Renderer = (elapsed: number, reduced: boolean, pointer?: CapabilityPointer, origin?: CapabilityPose) => void;
const renderers = new WeakMap<SVGSVGElement, Renderer>();
const clamp = (n: number, min = 0, max = 1) => Math.max(min,Math.min(max,n));
const mix = (a: number,b: number,t: number) => a + (b - a) * t;
const rgb = (color: string): number[] => color.startsWith('#')
  ? [1,3,5].map(start => parseInt(color.slice(start,start + 2),16))
  : color.match(/[\d.]+/g)!.map(Number);
const rotate = (x: number,y: number,z: number, yaw: number,pitch: number): [number,number,number] => {
  const xx = x * Math.cos(yaw) + z * Math.sin(yaw);
  const zz = z * Math.cos(yaw) - x * Math.sin(yaw);
  return [xx,y * Math.cos(pitch) - zz * Math.sin(pitch),y * Math.sin(pitch) + zz * Math.cos(pitch)];
};

/** Perspective projection of persistent 3D particles, driven by the carousel's stored time. */
export function buildCapabilityConcept(concept: CapabilityConcept): SVGSVGElement {
  const settings = CAPABILITY_PARTICLES;
  const svg = document.createElementNS(SVG_NS,'svg');
  svg.setAttribute('viewBox',`0 0 ${settings.width} ${settings.height}`);
  svg.setAttribute('class','capability-concept');
  svg.setAttribute('aria-hidden','true');
  svg.setAttribute('focusable','false');
  svg.dataset.concept = concept;
  const art = document.createElementNS(SVG_NS,'g');
  art.setAttribute('class','concept-art');
  svg.append(art);
  // Coarse depth layers preserve occlusion without sorting/reparenting every dot each frame.
  const layers = Array.from({length:settings.depthLayers},() => {
    const layer = document.createElementNS(SVG_NS,'g');
    art.append(layer);
    return layer;
  });
  const scene = CAPABILITY_SCENES[concept];
  const paired = scene.motion === 'divergence';
  const population = paired ? settings.count / 2 : settings.count;
  const dots = Array.from({length:settings.count},(_,id) => {
    const index = id % population;
    const arm = Math.floor(id / population);
    const latitude = 1 - 2 * (index + .5) / population;
    const radial = Math.sqrt(1 - latitude ** 2);
    const azimuth = index * Math.PI * (3 - Math.sqrt(5));
    // Deterministic density fills a volume rather than outlining a geometric shell.
    const radius = settings.radius * (.45 + .55 * ((index * .61803398875) % 1) ** .35);
    const dot = document.createElementNS(SVG_NS,'circle');
    const color = paired ? arm === 0 ? scene.color : scene.accent : scene.motion === 'convergence' && index % 2 ? scene.accent : scene.color;
    dot.setAttribute('fill',color);
    dot.dataset.particle = String(id);
    layers[0]!.append(dot);
    return {dot,id,index,arm,color,x:Math.cos(azimuth) * radial * radius * 1.25,y:latitude * radius * .64,z:Math.sin(azimuth) * radial * radius};
  });
  let previous = '';
  let previousOrigin: CapabilityPose | undefined;
  const paint: Renderer = (elapsed,reduced,pointer = null,origin) => {
    const time = reduced ? CAPABILITY_MOTION.phases.complete : Math.min(elapsed,CAPABILITY_MOTION.phases.complete);
    const cursor = reduced ? null : pointer;
    const signature = `${time}:${cursor?.x}:${cursor?.y}`;
    if (signature === previous && origin === previousOrigin) return;
    previous = signature;
    previousOrigin = origin;
    const entrance = reduced || !origin ? 1 : capabilityEase(elapsed / CAPABILITY_MOTION.transition);
    const progress = time / CAPABILITY_MOTION.phases.complete;
    const seconds = CAPABILITY_MOTION.phases.complete / 1000 * Math.sin(progress * Math.PI / 2);
    const action = capabilityEase((time - CAPABILITY_MOTION.phases.observe) / (CAPABILITY_MOTION.phases.complete - CAPABILITY_MOTION.phases.observe));
    const formation = Array.from({length:settings.bands},(_,band) => reduced ? 1 : capabilityEase((time - band * CAPABILITY_MOTION.stagger) / CAPABILITY_MOTION.assembly));
    const tiltX = cursor ? clamp((cursor.y - settings.height / 2) / (settings.height / 2),-1,1) * settings.pointerTilt : 0;
    const tiltY = cursor ? clamp((cursor.x - settings.width / 2) / (settings.width / 2),-1,1) * settings.pointerTilt : 0;
    svg.dataset.phase = progress === 1 ? 'settled' : 'movement';
    for (const particle of dots) {
      const {dot,id,index,arm,color} = particle;
      let {x,y,z} = particle;
      let yaw = seconds * .17;
      let pitch = -.28 + Math.sin(seconds * .55) * .13;
      if (scene.motion === 'organization') {
        const remaining = 1 - formation[index % settings.bands]!;
        [x,y,z] = rotate(x,y,z,Math.sin(index * 1.7) * .42 * remaining,Math.cos(index * 2.3) * .34 * remaining);
      } else if (scene.motion === 'flow') {
        [x,y,z] = rotate(x,y,z,seconds * (index % 3 - 1) * .16,0);
        y += Math.sin(seconds * 1.3 + index * .39) * 7;
      } else if (scene.motion === 'reconfiguration') {
        [x,y,z] = rotate(x,y,z,(index % 4 - 1.5) * action * .7,Math.sin(index * .2) * action * .18);
        x *= 1 + .08 * Math.sin(seconds * 1.1);
      } else if (scene.motion === 'divergence') {
        yaw += arm === 1 ? action * .65 : 0;
        if (arm === 1) y += Math.sin(index * .37 + seconds) * action * 8;
      } else {
        const startX = (index % 2 ? -1 : 1) * 80 + x * .5;
        x = mix(startX,x,action);
        y *= mix(.6,1,action);
        z *= mix(.6,1,action);
        yaw *= action;
      }
      [x,y,z] = rotate(x,y,z,yaw + tiltY,pitch + tiltX);
      const perspective = settings.cameraDistance / (settings.cameraDistance - z);
      const depth = clamp((z + settings.radius * 1.1) / (settings.radius * 2.2));
      const scale = paired ? .62 : 1;
      let sx = (paired ? arm === 0 ? 132 : 308 : settings.width / 2) + x * perspective * scale;
      let sy = settings.height / 2 + y * perspective * scale;
      let proximity = 0;
      if (cursor) {
        const dx = sx - cursor.x, dy = sy - cursor.y;
        const distance = Math.hypot(dx,dy);
        proximity = Math.max(0,1 - distance / settings.pointerRadius);
        const displacement = proximity ** 2 * settings.pointerDisplacement;
        sx += dx / Math.max(distance,1) * displacement;
        sy += dy / Math.max(distance,1) * displacement;
      }
      const layer = layers[Math.min(settings.depthLayers - 1,Math.floor(depth * settings.depthLayers))]!;
      if (dot.parentNode !== layer) layer.append(dot);
      let radius = (settings.dotRadius + settings.depthRadius * depth ** 1.5) * perspective * Math.sqrt(scale) + proximity * .45;
      let opacity = .16 + .8 * depth ** 1.3 + .04 * proximity;
      let fill = color as string;
      // A section changes by moving the existing particles into their next positions.
      // One visible field persists; descriptions and links never crossfade over each other.
      const start = origin?.[id];
      if (start && entrance < 1) {
        sx = mix(start.x,sx,entrance);
        sy = mix(start.y,sy,entrance);
        radius = mix(start.radius,radius,entrance);
        opacity = mix(start.opacity,opacity,entrance);
        const from = rgb(start.color), to = rgb(color);
        fill = `rgb(${from.map((value,channel) => mix(value,to[channel]!,entrance).toFixed(2)).join(',')})`;
      }
      dot.setAttribute('cx',sx.toFixed(3));
      dot.setAttribute('cy',sy.toFixed(3));
      dot.setAttribute('r',radius.toFixed(3));
      dot.setAttribute('opacity',opacity.toFixed(3));
      dot.setAttribute('fill',fill);
    }
  };
  renderers.set(svg,paint);
  paint(0,false);
  return svg;
}

export function capabilityConceptRenderer(svg: SVGSVGElement): Renderer {
  return renderers.get(svg)!;
}

/** Capture only at a section boundary, including a rapid selection mid-transition. */
export function capabilityConceptPose(svg: SVGSVGElement): CapabilityPose {
  return [...svg.querySelectorAll<SVGCircleElement>('circle')]
    .sort((a,b) => Number(a.dataset.particle) - Number(b.dataset.particle))
    .map(dot => ({
      x: Number(dot.getAttribute('cx')), y: Number(dot.getAttribute('cy')),
      radius: Number(dot.getAttribute('r')), opacity: Number(dot.getAttribute('opacity')),
      color: dot.getAttribute('fill')!,
    }));
}
