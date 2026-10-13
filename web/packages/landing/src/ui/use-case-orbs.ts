import { USE_CASE_ORBS } from '../content/use-case-orbs.js';
import { createOrbState } from './use-case-orb-state.js';
import { ORB_FRAGMENT, ORB_VERTEX } from './use-case-orb-shader.js';

type OrbRecipe = typeof USE_CASE_ORBS[keyof typeof USE_CASE_ORBS];
export interface OrbChoice { link: HTMLAnchorElement; orb: HTMLElement; recipe: OrbRecipe }

/** A single WebGL context and clock paint the gallery. Native links own all interaction. */
export function mountUseCaseOrbs(host: HTMLElement, gallery: HTMLElement, choices: readonly OrbChoice[]): void {
  const canvas = document.createElement('canvas');
  canvas.className = 'use-case-orb-canvas';
  canvas.setAttribute('aria-hidden', 'true');
  gallery.append(canvas);
  const state = createOrbState(choices.map(choice => choice.recipe.phase));
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const events = new AbortController();
  const { signal } = events;
  const visible = new Set<HTMLElement>();
  let gl: WebGLRenderingContext | null = null;
  let program: WebGLProgram | null = null;
  let buffer: WebGLBuffer | null = null;
  const shaders: WebGLShader[] = [];
  let locations: { resolution: WebGLUniformLocation; origin: WebGLUniformLocation; time: WebGLUniformLocation;
    amplitude: WebGLUniformLocation; palette: WebGLUniformLocation; material: WebGLUniformLocation } | null = null;
  let frame = 0, lastDraw = -Infinity, mounted = false, disposed = false, attempted = false, lost = false, background = false;
  let hovered = -1, focused = -1;
  const motionOff = () => reduced.matches || document.documentElement.dataset.reducedMotion === 'true';
  const available = () => host.isConnected && !host.inert && !host.hidden && visible.size > 0 && !document.hidden && !background;

  function release() {
    if (gl) {
      shaders.forEach(shader => gl?.deleteShader(shader));
      if (buffer) gl.deleteBuffer(buffer);
      if (program) gl.deleteProgram(program);
    }
    shaders.length = 0; buffer = null; program = null; locations = null; gl = null;
    gallery.classList.remove('has-category-orbs');
    gallery.dataset.orbRenderer = 'fallback';
  }
  function initialize(): boolean {
    if (attempted || lost) return !!program;
    attempted = true;
    if (typeof WebGLRenderingContext === 'undefined') return false;
    gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: false, antialias: false, depth: false,
      stencil: false, powerPreference: 'low-power' });
    if (!gl) return false;
    const context = gl;
    const candidate = context.createProgram();
    if (!candidate) { release(); return false; }
    program = candidate;
    for (const [type, source] of [[context.VERTEX_SHADER, ORB_VERTEX], [context.FRAGMENT_SHADER, ORB_FRAGMENT]] as const) {
      const shader = context.createShader(type);
      if (!shader) { release(); return false; }
      shaders.push(shader); context.shaderSource(shader, source); context.compileShader(shader);
      if (!context.getShaderParameter(shader, context.COMPILE_STATUS)) {
        console.error(context.getShaderInfoLog(shader) ?? 'Category orb shader compilation failed');
        release(); return false;
      }
      context.attachShader(candidate, shader);
    }
    context.linkProgram(candidate);
    if (!context.getProgramParameter(candidate, context.LINK_STATUS)) {
      console.error(context.getProgramInfoLog(candidate) ?? 'Category orb program link failed');
      release(); return false;
    }
    const resolution = context.getUniformLocation(candidate, 'uResolution'), origin = context.getUniformLocation(candidate, 'uOrigin');
    const time = context.getUniformLocation(candidate, 'uTime'), amplitude = context.getUniformLocation(candidate, 'uAmplitude');
    const palette = context.getUniformLocation(candidate, 'uPalette'), material = context.getUniformLocation(candidate, 'uMaterial');
    const position = context.getAttribLocation(candidate, 'position');
    const triangle = context.createBuffer();
    if (!resolution || !origin || !time || !amplitude || !palette || !material || position < 0 || !triangle) {
      if (triangle) context.deleteBuffer(triangle);
      release(); return false;
    }
    locations = { resolution, origin, time, amplitude, palette, material }; buffer = triangle;
    context.useProgram(candidate); context.bindBuffer(context.ARRAY_BUFFER, triangle);
    context.bufferData(context.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), context.STATIC_DRAW);
    context.enableVertexAttribArray(position); context.vertexAttribPointer(position, 2, context.FLOAT, false, 0, 0);
    context.clearColor(0, 0, 0, 0);
    gallery.classList.add('has-category-orbs'); gallery.dataset.orbRenderer = 'webgl';
    return true;
  }
  function paint(all = false) {
    if (!host.isConnected || !initialize() || !gl || !locations) return;
    const rect = gallery.getBoundingClientRect();
    const density = Math.min(window.devicePixelRatio || 1, 1.5);
    const width = Math.round(rect.width * density), height = Math.round(rect.height * density);
    if (!width || !height) return;
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
    gl.clear(gl.COLOR_BUFFER_BIT);
    choices.forEach((choice, index) => {
      if (!all && !visible.has(choice.orb)) return;
      const orb = choice.orb.getBoundingClientRect();
      const x = Math.round((orb.left - rect.left) * density), y = Math.round((rect.bottom - orb.bottom) * density);
      const w = Math.round(orb.width * density), h = Math.round(orb.height * density);
      if (!w || !h || !gl || !locations) return;
      gl.viewport(x, y, w, h);
      // Locations belong to a program: always write the dimensions, even without a resize.
      gl.uniform2f(locations.resolution, w, h); gl.uniform2f(locations.origin, x, y);
      const value = state.values[index];
      if (!value) return;
      gl.uniform1f(locations.time, value.phase);
      gl.uniform1f(locations.amplitude, motionOff() ? 0 : value.emphasis * .18);
      gl.uniform1f(locations.palette, choice.recipe.palette);
      gl.uniform1f(locations.material, choice.recipe.material === 'halftone' ? 1 : 0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    });
  }
  function tick(now: number) {
    frame = 0;
    if (!available() || motionOff() || disposed || lost) { sync(); return; }
    // One gentle 30 Hz presentation clock, independent of the display's refresh rate.
    if (now - lastDraw >= 1000 / 30 - .5) { state.advance(now); paint(); lastDraw = now; }
    if (program) frame = requestAnimationFrame(tick);
  }
  function sync() {
    if (disposed) return;
    if (!available() || motionOff() || lost) {
      if (frame) cancelAnimationFrame(frame);
      frame = 0; lastDraw = -Infinity; state.suspend();
      // A still is also painted on a background mount and preference changes.
      paint(true); return;
    }
    if (!frame) { paint(); if (program) frame = requestAnimationFrame(tick); }
  }
  const select = () => { state.select(focused >= 0 ? focused : hovered); sync(); };
  choices.forEach((choice, index) => {
    choice.link.addEventListener('pointerenter', event => { if (event.pointerType !== 'touch') { hovered = index; select(); } }, { signal });
    choice.link.addEventListener('pointerleave', () => { hovered = -1; select(); }, { signal });
    choice.link.addEventListener('focus', () => { focused = index; select(); }, { signal });
    choice.link.addEventListener('blur', () => { focused = -1; select(); }, { signal });
  });
  const intersection = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver(entries => {
    for (const entry of entries) { if (entry.isIntersecting) visible.add(entry.target as HTMLElement); else visible.delete(entry.target as HTMLElement); }
    sync();
  });
  choices.forEach(choice => { if (intersection) intersection.observe(choice.orb); else visible.add(choice.orb); });
  const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => { paint(true); sync(); });
  resize?.observe(gallery);
  const hostObserver = new MutationObserver(sync);
  hostObserver.observe(host, { attributes: true, attributeFilter: ['inert', 'hidden'] });
  const preferenceObserver = new MutationObserver(sync);
  preferenceObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-reduced-motion'] });
  document.addEventListener('visibilitychange', sync, { signal });
  reduced.addEventListener('change', sync, { signal });
  window.addEventListener('blur', () => { background = true; sync(); }, { signal });
  window.addEventListener('focus', () => { background = false; sync(); }, { signal });
  window.addEventListener('pagehide', () => { background = true; sync(); }, { signal });
  window.addEventListener('pageshow', () => { background = false; sync(); }, { signal });
  canvas.addEventListener('webglcontextlost', event => { event.preventDefault(); lost = true; release(); sync(); }, { signal });
  canvas.addEventListener('webglcontextrestored', () => { lost = false; attempted = false; sync(); }, { signal });
  const connection = new MutationObserver(() => {
    if (host.isConnected && !mounted) { mounted = true; sync(); }
    else if (!host.isConnected && mounted) {
      disposed = true; cancelAnimationFrame(frame); events.abort(); intersection?.disconnect(); resize?.disconnect();
      const context = gl;
      hostObserver.disconnect(); preferenceObserver.disconnect(); connection.disconnect(); release();
      context?.getExtension('WEBGL_lose_context')?.loseContext(); canvas.remove();
    }
  });
  connection.observe(document.body, { childList: true, subtree: true });
  gallery.dataset.orbRenderer = 'fallback';
  queueMicrotask(sync);
}
