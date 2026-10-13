import { mountNativeWorldOrbit } from './world-native-orbit.js';
import { ORBIT_PALETTES } from './world-materials.js';
import { ORBIT_COUNT, ORBIT_OUTER_COUNT, ORBIT_PERIOD, orbitPose } from './world-orbit-geometry.js';
import type { OrbitPose } from './world-orbit-geometry.js';
import { lensMotions, LiquidMotionState } from './liquid-motion.js';

const shaderColor = (hex: string): string => `vec3(${[1, 3, 5].map(start => (parseInt(hex.slice(start, start + 2), 16) / 255).toFixed(4)).join(',')})`;
const paletteSource = ORBIT_PALETTES.map(([a, b, c], index) => `${index ? 'else ' : ''}if(kind<${index + .5}) { light=${shaderColor(a)}; middle=${shaderColor(b)}; shade=${shaderColor(c)}; }`).join('\n');

const vertexSource = `attribute vec2 position;
varying vec2 uv;
void main(){uv=position*.5+.5;gl_Position=vec4(position,0.,1.);}`;
const fragmentSource = `precision highp float;
varying vec2 uv;
uniform vec2 resolution;
uniform float fieldFade;
uniform vec4 poses[${ORBIT_COUNT}];
uniform vec4 bases[${ORBIT_COUNT}];
uniform vec4 liquidMotionA;
uniform vec4 liquidMotionB;
uniform sampler2D captures;
uniform vec2 captureGrid;
vec3 liquidTravel(vec4 pose){
 float id=pose.w*${ORBIT_COUNT-1}.;
 float a=1.-step(.25,abs(id-liquidMotionA.x));
 float b=1.-step(.25,abs(id-liquidMotionB.x));
 return vec3(liquidMotionA.zw,liquidMotionA.y)*a+vec3(liquidMotionB.zw,liquidMotionB.y)*b;
}
float liquidActivity(vec4 pose){return liquidTravel(pose).z;}
vec2 localPoint(vec2 p,vec4 pose,vec4 b){
 vec2 d=p-pose.xy;
 return vec2(b.w*d.x-b.z*d.y,-b.y*d.x+b.x*d.y)/(b.x*b.w-b.y*b.z);
}
float disc(vec2 p,vec4 pose,vec4 b){
 vec2 q=localPoint(p,pose,b);
 vec3 motion=liquidTravel(pose);
 // Fade toward a defined droplet silhouette so partial activity is visible too.
 float primary=length(q)-1.;
 float tail=length(q+motion.xy*1.2)-.45;
 float width=.8;
 float share=clamp(.5+.5*(tail-primary)/width,0.,1.);
 float droplet=mix(tail,primary,share)-width*share*(1.-share);
 return mix(primary,droplet,motion.z)*min(length(b.xy),length(b.zw));
}
float blendDistance(float a,float b,float k){
 float h=clamp(.5+.5*(b-a)/k,0.,1.);
 return mix(b,a,h)-k*h*(1.-h);
}
float surface(vec2 p,vec4 pose,vec4 basis){
 float wall=min(min(p.x,resolution.x-p.x),min(p.y,resolution.y-p.y))+4.;
 float radius=min(length(basis.xy),length(basis.zw));
 return blendDistance(disc(p,pose,basis),wall,radius*3.6);
}
float edgeActivation(vec4 pose,vec4 basis){
 // Ellipse support gives surface clearance rather than guessing from its center.
 vec2 support=vec2(length(vec2(basis.x,basis.z)),length(vec2(basis.y,basis.w)));
 vec2 gap=min(pose.xy,resolution-pose.xy)-support;
 float radius=min(length(basis.xy),length(basis.zw));
 return (1.-smoothstep(0.,radius*2.,min(gap.x,gap.y)))*liquidActivity(pose);
}
float orbSurface(vec2 p,vec4 pose,vec4 basis){
 return mix(disc(p,pose,basis),surface(p,pose,basis),edgeActivation(pose,basis));
}
vec3 material(vec2 q,float kind,float crop){
 vec2 tex=clamp(q*.5+.5,0.,1.);
 tex.x=tex.x*.58+.12+crop*.12;
 if(kind>5.5) {
  float index=kind-6.;
  vec2 cell=vec2(mod(index,captureGrid.x),floor(index/captureGrid.x));
  return texture2D(captures,(cell+clamp(tex,0.002,0.998))/captureGrid).rgb;
 }
 vec3 light=vec3(1.),middle=vec3(.7),shade=vec3(.5);
 ${paletteSource}
 float angle=crop*5.8;
 vec2 rotated=mat2(cos(angle),-sin(angle),sin(angle),cos(angle))*q;
 float sweep=smoothstep(-1.1,1.3,rotated.x*.65+rotated.y*.8);
 vec3 color=mix(middle,shade,sweep);
 float glow=1.-smoothstep(0.,1.9,length(q-vec2(-.45+crop*.5,-.6)));
 return mix(color,light,glow*.92);
}
vec3 refracted(vec2 q,float kind,float crop,float blur){
 vec3 color=material(q,kind,crop)*.4;
 color+=material(q+vec2(blur,0.),kind,crop)*.15;
 color+=material(q-vec2(blur,0.),kind,crop)*.15;
 color+=material(q+vec2(0.,blur),kind,crop)*.15;
 color+=material(q-vec2(0.,blur),kind,crop)*.15;
 return color;
}
void main(){
 vec2 p=vec2(uv.x,1.-uv.y)*resolution;
 float nearest=10000.;vec4 chosen=vec4(0.);vec4 basis=vec4(1.,0.,0.,1.);
 for(int i=0;i<${ORBIT_COUNT};i++){
  vec2 delta=abs(p-poses[i].xy);
  float reach=max(length(bases[i].xy),length(bases[i].zw))*5.;
  if(delta.x>reach||delta.y>reach) continue;
  float d=orbSurface(p,poses[i],bases[i]);
  if(d<nearest){nearest=d;chosen=poses[i];basis=bases[i];}
 }
 if(nearest>9999.) {gl_FragColor=vec4(0.);return;}
 float edge=min(min(p.x,resolution.x-p.x),min(p.y,resolution.y-p.y));
 float radius=min(length(basis.xy),length(basis.zw));
 float distance=nearest;
 if(distance>6.){
  gl_FragColor=vec4(0.);return;
 }
 vec2 normal=normalize(vec2(
  orbSurface(p+vec2(.5,0.),chosen,basis)-orbSurface(p-vec2(.5,0.),chosen,basis),
  orbSurface(p+vec2(0.,.5),chosen,basis)-orbSurface(p-vec2(0.,.5),chosen,basis)));
 vec2 q=localPoint(p,chosen,basis);
 float neck=max(liquidActivity(chosen),edgeActivation(chosen,basis)*(1.-smoothstep(0.,radius*4.5,edge)))*smoothstep(.84,1.12,length(q));
 float rim=exp(-abs(distance)*.17);
 // Refraction follows the boundary normal, including the narrowing bridge.
 vec2 bend=normal*neck*(.12+rim*.16);
 vec2 dispersion=normal*neck*(.006+rim*.018);
 vec3 color=vec3(
  refracted(q+bend+dispersion,chosen.z,chosen.w,neck*.02).r,
  refracted(q+bend,chosen.z,chosen.w,neck*.02).g,
  refracted(q+bend-dispersion,chosen.z,chosen.w,neck*.02).b);
 float softness=mix(.7,1.,neck);
 float coverage=1.-smoothstep(-softness,softness,distance);
 float edgeReveal=mix(1.,smoothstep(0.,24.,edge),fieldFade);
 // Premultiplied alpha lets the interface canvas show through without tinting the artwork.
 gl_FragColor=vec4(color*coverage*edgeReveal,coverage*edgeReveal);
}`;

export interface WorldOptics { redraw(): void; dispose(): void }

/** Dependency-free rendering; native buttons remain the interaction surface. */
export function mountWorldOptics(root: HTMLElement, images: readonly string[]): WorldOptics | undefined {
  if (typeof WebGLRenderingContext === 'undefined') return mountNativeWorldOrbit(root);
  const canvas = document.createElement('canvas');
  canvas.className = 'world-optics'; canvas.setAttribute('aria-hidden', 'true');
  const gl = canvas.getContext('webgl', { alpha: true, antialias: false, depth: false, stencil: false });
  if (!gl) return mountNativeWorldOrbit(root);
  const shaders: WebGLShader[] = [];
  const compile = (type: number, source: string) => {
    const shader = gl.createShader(type)!; shaders.push(shader);
    gl.shaderSource(shader, source); gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader) ?? 'World shader compilation failed');
    return shader;
  };
  const program = gl.createProgram()!;
  try {
    gl.attachShader(program, compile(gl.VERTEX_SHADER, vertexSource));
    gl.attachShader(program, compile(gl.FRAGMENT_SHADER, fragmentSource));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program) ?? 'World shader linking failed');
  } catch (error) {
    for (const shader of shaders) gl.deleteShader(shader); gl.deleteProgram(program);
    console.warn('World optics unavailable; retaining native previews.', error); return mountNativeWorldOrbit(root);
  }
  gl.useProgram(program);
  const buffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]), gl.STATIC_DRAW);
  const position = gl.getAttribLocation(program, 'position'); gl.enableVertexAttribArray(position); gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
  const poseLocation = gl.getUniformLocation(program, 'poses[0]'), basisLocation = gl.getUniformLocation(program, 'bases[0]'), resolutionLocation = gl.getUniformLocation(program, 'resolution'), fadeLocation = gl.getUniformLocation(program, 'fieldFade');
  const poses = new Float32Array(ORBIT_COUNT * 4), bases = new Float32Array(ORBIT_COUNT * 4);
  const liquid = new LiquidMotionState();
  const motionA = new Float32Array(4), motionB = new Float32Array(4);
  const motionALocation=gl.getUniformLocation(program,'liquidMotionA'), motionBLocation=gl.getUniformLocation(program,'liquidMotionB');
  const textures: WebGLTexture[] = [];
  let finalDisposed = false;
  let fallback: WorldOptics | undefined;
  let disposed = false, frame = 0, elapsed = 2, previous = 0, width = 0, height = 0;
  let hovered: number | undefined, focused = false, visible = true;
  let loaded = 0;
  const highlights = new Float32Array(ORBIT_COUNT);
  const tiltX = new Float32Array(ORBIT_COUNT), tiltY = new Float32Array(ORBIT_COUNT);
  let pointerX = 0, pointerY = 0;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const choices = [...root.querySelectorAll<HTMLElement>('.world-choice')].sort((a, b) => Number(a.dataset.sceneIndex) - Number(b.dataset.sceneIndex));
  const forms = [...root.querySelectorAll<HTMLElement>('.orbit-item')];
  const originalStyles = forms.map(form => form.style.cssText);
  const active = () => visible && !document.hidden && (!document.documentElement.dataset.surface || document.documentElement.dataset.surface === 'title');
  const paused = () => reduced.matches || hovered !== undefined || focused || root.dataset.selected !== undefined;
  const draw = (now: number) => {
    frame = 0;
    if (disposed || !width || !height || !active()) { previous = 0; return; }
    const delta = previous ? Math.min((now - previous) / 1000, .05) : 1/60;
    if (previous && !paused()) elapsed += delta;
    previous = now;
    const selected = root.dataset.selected;
    const selectedIndex = selected === undefined ? undefined : Number(choices[Number(selected)]?.dataset.orbitIndex);
    const current = hovered ?? selectedIndex;
    let settling = false;
    const projected: OrbitPose[] = [];
    for (let index = 0; index < ORBIT_COUNT; index += 1) {
      const target = index === current ? 1 : 0;
      const emphasis = reduced.matches ? target : highlights[index]! + (target - highlights[index]!) * .18;
      highlights[index] = Math.abs(target - emphasis) < .002 ? target : emphasis;
      const tx = index === hovered && !reduced.matches ? pointerX : 0;
      const ty = index === hovered && !reduced.matches ? pointerY : 0;
      tiltX[index] = reduced.matches ? 0 : tiltX[index]! + (tx - tiltX[index]!) * .15;
      tiltY[index] = reduced.matches ? 0 : tiltY[index]! + (ty - tiltY[index]!) * .15;
      if (highlights[index] !== target || Math.abs(tx - tiltX[index]!) > .002 || Math.abs(ty - tiltY[index]!) > .002) settling = true;
      const pose = orbitPose(index, elapsed, width, height);
      const textureIndex = choices.findIndex(choice => Number(choice.dataset.orbitIndex) === index);
      if (textureIndex >= 0) pose.material = 6 + textureIndex;
      const scale = 1 + highlights[index]! * .12;
      pose.ax *= scale; pose.ay = pose.ay * scale + tiltY[index]! * 3;
      pose.bx = pose.bx * scale + tiltX[index]! * 3; pose.by *= scale;
      projected.push(orbitPose(index,elapsed,width,height));
      poses.set([pose.x, pose.y, pose.material, index / (ORBIT_COUNT - 1)], index * 4);
      bases.set([pose.ax, pose.ay, pose.bx, pose.by], index * 4);
      const button = forms[index];
      if (button && root.classList.contains('has-optics')) {
        const minimum = textureIndex >= 0 ? 22 : 0;
        const rx = Math.max(minimum, Math.hypot(pose.ax, pose.bx)), ry = Math.max(minimum, Math.hypot(pose.ay, pose.by));
        button.style.left = `${pose.x-rx}px`; button.style.top = `${pose.y-ry}px`;
        button.style.width = `${rx*2}px`; button.style.height = `${ry*2}px`;
        // Project the ring with the rendered disc, independently of its rectangular hit area.
        button.style.setProperty('--world-ring-projection', `matrix(${pose.ax/32},${pose.ay/32},${pose.bx/32},${pose.by/32},0,0)`);
      }
    }
    const future=projected.map((_,index)=>orbitPose(index,elapsed+1/60,width,height));
    settling=liquid.update(lensMotions(projected,future,1/60),delta,paused()) || settling;
    const first=liquid.active[0]!, second=liquid.active[1]!;
    motionA.set([first.index,first.strength,first.x,first.y]); motionB.set([second.index,second.strength,second.x,second.y]);
    gl.uniform4fv(motionALocation,motionA); gl.uniform4fv(motionBLocation,motionB);
    if (selected !== undefined) root.dispatchEvent(new Event('worldpose'));
    gl.uniform1f(fadeLocation, width < window.innerWidth - 1 ? 1 : 0); gl.uniform2f(resolutionLocation, width, height); gl.uniform4fv(poseLocation, poses); gl.uniform4fv(basisLocation, bases);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    if (!paused() || settling) frame = requestAnimationFrame(draw);
  };
  const redraw = () => { previous = 0; if (!disposed && !frame) frame = requestAnimationFrame(draw); };
  // A single atlas supports every genuine world without a sampler limit per image.
  const columns = Math.min(4, Math.max(1, images.length));
  const rows = Math.ceil(images.length / columns);
  const atlas = document.createElement('canvas');
  const tileSize = Math.min(512, Math.floor(Number(gl.getParameter(gl.MAX_TEXTURE_SIZE)) / Math.max(columns, rows)));
  atlas.width = columns * tileSize; atlas.height = rows * tileSize;
  const context = atlas.getContext('2d');
  if (!context) {
    for (const shader of shaders) gl.deleteShader(shader);
    gl.deleteProgram(program); gl.deleteBuffer(buffer);
    return mountNativeWorldOrbit(root);
  }
  const texture = gl.createTexture()!; textures.push(texture);
  gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.uniform1i(gl.getUniformLocation(program, 'captures'), 0);
  gl.uniform2f(gl.getUniformLocation(program, 'captureGrid'), columns, rows);
  const resize = new ResizeObserver(entries => {
    const bounds = entries[0]?.contentRect; if (disposed || !bounds) return;
    width = bounds.width; height = bounds.height;
    const density = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(width * density); canvas.height = Math.round(height * density);
    gl.viewport(0,0,canvas.width,canvas.height); redraw();
  });
  const intersection = new IntersectionObserver(entries => { visible = entries[0]?.isIntersecting ?? false; redraw(); });
  const mutation = new MutationObserver(redraw);
  const enter = (event: PointerEvent) => {
    if (event.pointerType !== 'touch') { hovered = Number((event.currentTarget as HTMLElement).dataset.orbitIndex); redraw(); }
  }, leave = () => { hovered = undefined; redraw(); };
  const focus = (event: FocusEvent) => {
    focused = true;
    const index = Number((event.currentTarget as HTMLElement).dataset.orbitIndex);
    const pose = orbitPose(index, elapsed, width, height);
    // A keyboard target that has passed beyond the viewport returns along its
    // own circular track before the field holds for selection.
    if (pose.x < 32 || pose.x > width - 32 || pose.y < 32 || pose.y > height - 32) {
      elapsed = ((.125 - index / ORBIT_OUTER_COUNT) * ORBIT_PERIOD + ORBIT_PERIOD) % ORBIT_PERIOD;
    }
    redraw();
  }, blur = () => { focused = false; redraw(); };
  const move = (event: PointerEvent) => {
    const bounds = (event.currentTarget as HTMLElement).getBoundingClientRect();
    pointerX = (event.clientX - bounds.left) / bounds.width * 2 - 1;
    pointerY = (event.clientY - bounds.top) / bounds.height * 2 - 1; redraw();
  };
  for (const form of choices) { form.addEventListener('pointerenter',enter); form.addEventListener('pointerleave',leave); form.addEventListener('pointermove',move); }
  for (const button of choices) { button.addEventListener('focus',focus); button.addEventListener('blur',blur); }
  root.prepend(canvas);
  resize.observe(root); intersection.observe(root); mutation.observe(document.documentElement,{attributes:true,attributeFilter:['data-surface']}); mutation.observe(root,{subtree:true,attributes:true,attributeFilter:['data-selected']});
  document.addEventListener('visibilitychange',redraw); reduced.addEventListener('change',redraw);
  const disposeWebGL = () => {
    if (disposed) return;
    disposed = true; cancelAnimationFrame(frame); resize.disconnect(); intersection.disconnect(); mutation.disconnect();
    document.removeEventListener('visibilitychange',redraw); reduced.removeEventListener('change',redraw);
    for (const form of choices) { form.removeEventListener('pointerenter',enter); form.removeEventListener('pointerleave',leave); form.removeEventListener('pointermove',move); }
    for (const button of choices) { button.removeEventListener('focus',focus); button.removeEventListener('blur',blur); }
    for (const texture of textures) gl.deleteTexture(texture); for (const shader of shaders) gl.deleteShader(shader);
    canvas.removeEventListener('webglcontextlost', transitionToFallback);
    gl.deleteProgram(program); gl.deleteBuffer(buffer); canvas.remove(); root.classList.remove('has-optics');
    forms.forEach((button, index) => { button.style.cssText = originalStyles[index]!; });
  };
  const transitionToFallback = () => {
    if (finalDisposed || disposed) return;
    disposeWebGL();
    fallback = mountNativeWorldOrbit(root);
  };
  const dispose = () => {
    if (finalDisposed) return;
    finalDisposed = true;
    disposeWebGL();
    fallback?.dispose();
    fallback = undefined;
  };
  canvas.addEventListener('webglcontextlost', transitionToFallback);
  images.forEach((source, index) => {
    const image = new Image(); image.onload = () => {
      if (disposed) return;
      context.drawImage(image, index % columns * tileSize, Math.floor(index / columns) * tileSize, tileSize, tileSize);
      loaded += 1;
      if (loaded === images.length) {
        gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, atlas);
        root.classList.add('has-optics'); redraw();
      }
    }; image.onerror = transitionToFallback; image.src = source;
  });
  return { redraw: () => {
    if (finalDisposed) return;
    if (fallback) fallback.redraw(); else redraw();
  }, dispose };
}
