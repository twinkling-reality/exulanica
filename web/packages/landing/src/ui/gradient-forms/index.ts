import './style.css';
import { layoutForms, type FormSpec } from './geometry.js';

/** An independently shaped patch of light, in circle-local coordinates (-1 to 1). */
export interface ColorField {
  readonly color: 0 | 1 | 2;
  readonly center: readonly [number, number];
  readonly spread: readonly [number, number];
  readonly rotation: number;
  readonly opacity: number;
  readonly falloff: readonly { readonly at: number; readonly opacity: number }[];
}
export interface GradientFormsOptions {
  /** Optional per-form material; each color has its own geometry and fade, without a shared rim. */
  readonly materials?: Readonly<Record<string, readonly ColorField[]>>;
  readonly forms: readonly FormSpec[];
  /** Three color stops arranged along the illuminated edge. Any valid CSS color is accepted. */
  readonly palette: readonly [string, string, string];
  readonly alternatePalette?: readonly [string, string, string];
  readonly strength?: number;
  readonly texture?: number;
  /** Grain cycles per local unit; each circle has a diameter of two units. */
  readonly textureFrequency?: number;
  /** Fraction of the diameter that remains transparent before the rim fades in. */
  readonly fadeStart?: number;
  /** Transparent inner radius as a fraction of the circle radius. */
  readonly rimStart?: number;
  readonly seed?: number;
  /** Seconds for one full color cycle. Geometry never moves or intersects. */
  readonly duration?: number;
  /**
   * How the artwork lives.
   *
   * `still` renders one palette and never moves. `color` cross-fades a second palette over the
   * same geometry, which is an opacity change on an already-rasterized layer.
   *
   * Motion that moves anything inside a form was tried and removed. This artwork is painted at
   * 120vw and the informational surfaces scale it by 2.5, so the composition reaches about 93
   * megapixels of device pixels; invalidating that region every frame, through a clip path, an
   * alpha mask and a soft-light grain, is not something a browser can keep up with. The artwork
   * is a poster. Motion on this page belongs on the small elements.
   */
  readonly motion?: 'still' | 'color';
}
export interface GradientForms {
  readonly element: SVGSVGElement;
  /** Atomic replacement: invalid configurations leave the existing art untouched. */
  update(options: GradientFormsOptions): void;
}
const NS = 'http://www.w3.org/2000/svg';
let instance = 0;
function svg<K extends keyof SVGElementTagNameMap>(tag: K, attributes: Record<string, string | number> = {}): SVGElementTagNameMap[K] {
  const node = document.createElementNS(NS, tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
  return node;
}
function unit(value: number, name: string): number {
  if (!Number.isFinite(value) || value < 0 || value > 1) throw new Error(`${name} must be between zero and one.`);
  return value;
}

/** Resolution-independent decorative artwork. No canvas loop, external images, or page coordinates. */
export function createGradientForms(initial: GradientFormsOptions): GradientForms {
  const id = `gradient-forms-${++instance}`;
  const element = svg('svg', { class: 'gradient-forms', 'aria-hidden': 'true', focusable: 'false' });
  function update(options: GradientFormsOptions): void {
    const layout = layoutForms(options.forms);
    const strength = unit(options.strength ?? 0.8, 'Strength');
    const texture = unit(options.texture ?? 0.04, 'Texture');
    const fadeStart = unit(options.fadeStart ?? 0.47, 'Fade start');
    const rimStart = unit(options.rimStart ?? 0.55, 'Rim start');
    const frequency = options.textureFrequency ?? 180;
    if (!Number.isFinite(frequency) || frequency <= 0) throw new Error('Texture frequency must be positive.');
    const duration = options.duration ?? 24;
    if (!Number.isFinite(duration) || duration <= 0) throw new Error('Duration must be positive.');
    if (!Number.isFinite(options.seed ?? 1)) throw new Error('Texture seed must be finite.');
    const palettes = [options.palette, options.alternatePalette ?? options.palette];
    if (palettes.some((palette) => palette.length !== 3 || palette.some((color) => !CSS.supports('color', color)))) {
      throw new Error('Each palette needs three valid CSS colors.');
    }
    for (const [formId, fields] of Object.entries(options.materials ?? {})) {
      if (!options.forms.some((form) => form.id === formId) || !fields.length) throw new Error('Material needs an existing form and at least one field.');
      for (const field of fields) {
        if (![0, 1, 2].includes(field.color) || !field.center.every(Number.isFinite) ||
            !field.spread.every((value) => Number.isFinite(value) && value > 0) || !Number.isFinite(field.rotation)) {
          throw new Error('Invalid color field geometry.');
        }
        unit(field.opacity, 'Field opacity');
        if (field.falloff.length < 2) throw new Error('A color field needs at least two falloff stops.');
        let last = -1;
        for (const stop of field.falloff) {
          unit(stop.at, 'Falloff position');
          unit(stop.opacity, 'Falloff opacity');
          if (stop.at < last) throw new Error('Falloff stops must be ordered.');
          last = stop.at;
        }
      }
    }
    const defs = svg('defs');
    const artwork = svg('g', { opacity: strength });
    // A small deterministic vector tile avoids re-evaluating turbulence during camera scaling.
    const tileSize = 12 / frequency;
    const noise = svg('pattern', { id: `${id}-grain`, width: tileSize, height: tileSize, patternUnits: 'userSpaceOnUse' });
    let randomState = (options.seed ?? 1) >>> 0;
    const random = (): number => {
      randomState = (Math.imul(randomState, 1664525) + 1013904223) >>> 0;
      return randomState / 4294967296;
    };
    for (let dot = 0; dot < 64; dot += 1) {
      noise.append(svg('circle', { cx: random() * tileSize, cy: random() * tileSize,
        r: (0.16 + random() * 0.2) / frequency, fill: dot % 2 ? '#fff' : '#173427' }));
    }
    defs.append(noise);
    layout.forms.forEach((form, index) => {
      const key = `${id}-${index}`;
      // Every form uses the same local [-1, 1] coordinate system, independent of its radius.
      const clip = svg('clipPath', { id: `${key}-clip`, clipPathUnits: 'userSpaceOnUse' });
      clip.append(svg('circle', { r: 1 }));
      const fields = options.materials?.[form.id];
      if (fields) {
        defs.append(clip);
        const positioned = svg('g', { transform: `translate(${form.x} ${form.y}) scale(${form.radius})` });
        const material = svg('g', { 'clip-path': `url(#${key}-clip)` });
        const grainMask = svg('mask', { id: `${key}-field-alpha`, x: -1, y: -1, width: 2, height: 2, maskUnits: 'userSpaceOnUse', style: 'mask-type:alpha' });
        const variants = (options.motion ?? 'color') === 'still' ? [options.palette] : palettes;
        variants.forEach((palette, variant) => {
          const layer = svg('g', { class: variant ? 'gradient-forms-shift' : 'gradient-forms-base' });
          fields.forEach((field, fieldIndex) => {
            const gradientId = `${key}-field-${variant}-${fieldIndex}`;
            const gradient = svg('radialGradient', { id: gradientId, gradientUnits: 'userSpaceOnUse', cx: 0, cy: 0, r: 1,
              gradientTransform: `translate(${field.center.join(' ')}) rotate(${field.rotation}) scale(${field.spread.join(' ')})` });
            for (const stop of field.falloff) gradient.append(svg('stop', { offset: `${stop.at * 100}%`, 'stop-color': palette[field.color], 'stop-opacity': stop.opacity * field.opacity }));
            defs.append(gradient);
            layer.append(svg('circle', { r: 1, fill: `url(#${gradientId})` }));
            if (!variant) grainMask.append(svg('circle', { r: 1, fill: `url(#${gradientId})` }));
          });
          material.append(layer);
        });
        defs.append(grainMask);
        if (texture > 0) material.append(svg('circle', { r: 1, fill: `url(#${id}-grain)`, opacity: texture, mask: `url(#${key}-field-alpha)`, class: 'gradient-forms-grain' }));
        positioned.append(material);
        artwork.append(positioned);
        return;
      }
      const fade = svg('linearGradient', { id: `${key}-fade`, x1: '-1', y1: '0', x2: '1', y2: '0', gradientUnits: 'userSpaceOnUse' });
      fade.append(svg('stop', { offset: '0%', 'stop-color': 'white', 'stop-opacity': 0 }), svg('stop', { offset: `${fadeStart * 100}%`, 'stop-color': 'white', 'stop-opacity': 0.02 }), svg('stop', { offset: '100%', 'stop-color': 'white', 'stop-opacity': 1 }));
      const mask = svg('mask', { id: `${key}-mask`, x: -1, y: -1, width: 2, height: 2, maskUnits: 'userSpaceOnUse', style: 'mask-type:alpha' });
      mask.append(svg('circle', { r: 1, fill: `url(#${key}-fade)` }));
      const radial = svg('radialGradient', { id: `${key}-radial` });
      for (const [offset, opacity] of [[rimStart, 0], [rimStart + (1 - rimStart) * 0.48, 0.08], [rimStart + (1 - rimStart) * 0.82, 0.48], [1, 1]]) {
        radial.append(svg('stop', { offset: `${offset! * 100}%`, 'stop-color': 'white', 'stop-opacity': opacity! }));
      }
      const radialMask = svg('mask', { id: `${key}-rim`, x: -1, y: -1, width: 2, height: 2, maskUnits: 'userSpaceOnUse', style: 'mask-type:alpha' });
      radialMask.append(svg('circle', { r: 1, fill: `url(#${key}-radial)` }));
      defs.append(clip, fade, mask, radial, radialMask);
      const positioned = svg('g', { transform: `translate(${form.x} ${form.y}) scale(${form.radius}) rotate(${form.light})` });
      const rim = svg('g', { 'clip-path': `url(#${key}-clip)`, mask: `url(#${key}-mask)` });
      palettes.forEach((palette, variant) => {
        const gradient = svg('linearGradient', { id: `${key}-color-${variant}`, x1: '0', y1: '-1', x2: '0', y2: '1', gradientUnits: 'userSpaceOnUse' });
        palette.forEach((color, stop) => gradient.append(svg('stop', { offset: `${stop * 50}%`, 'stop-color': color })));
        defs.append(gradient);
        rim.append(svg('circle', { r: 1, fill: `url(#${key}-color-${variant})`, class: variant === 1 ? 'gradient-forms-shift' : 'gradient-forms-base', style: `animation-delay: -${index * duration / 5}s` }));
      });
      // Grain shares the rim mask, so the dissolving interior stays clean rather than gray.
      if (texture > 0) rim.append(svg('rect', { x: -1, y: -1, width: 2, height: 2, fill: `url(#${id}-grain)`, opacity: texture, class: 'gradient-forms-grain' }));
      const edge = svg('g', { mask: `url(#${key}-rim)` });
      edge.append(rim);
      positioned.append(edge);
      artwork.append(positioned);
    });
    const { x, y, width, height } = layout.bounds;
    // Relative padding makes equivalent layouts identical at any choice of art units.
    const padding = Math.max(width, height) * 0.001;
    element.setAttribute('viewBox', `${x - padding} ${y - padding} ${width + padding * 2} ${height + padding * 2}`);
    element.style.setProperty('--forms-duration', `${duration}s`);
    element.dataset['motion'] = options.motion ?? 'color';
    element.replaceChildren(defs, artwork);
  }
  update(initial);
  return { element, update };
}
