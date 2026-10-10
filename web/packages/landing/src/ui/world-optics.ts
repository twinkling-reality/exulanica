import { ORBIT_COUNT, ORBIT_PERIOD, orbitPose } from './world-orbit-geometry.js';

const vertexSource = `attribute vec2 position;
varying vec2 uv;
void main(){uv=position*.5+.5;gl_Position=vec4(position,0.,1.);}`;
const fragmentSource = `precision highp float;
varying vec2 uv;
uniform vec2 resolution;
uniform float fieldFade;
uniform vec4 selection;
uniform vec4 poses[24];
uniform vec4 bases[24];
uniform sampler2D market;
uniform sampler2D town;
vec2 localPoint(vec2 p,vec4 pose,vec4 b){
 vec2 d=p-pose.xy;
 return vec2(b.w*d.x-b.z*d.y,-b.y*d.x+b.x*d.y)/(b.x*b.w-b.y*b.z);
}
float disc(vec2 p,vec4 pose,vec4 b){
 vec2 q=localPoint(p,pose,b);
 return (length(q)-1.)*min(length(b.xy),length(b.zw));
}
float blendDistance(float a,float b,float k){
 float h=clamp(.5+.5*(b-a)/k,0.,1.);
 return mix(b,a,h)-k*h*(1.-h);
}
float surface(vec2 p,vec4 pose,vec4 basis){
 float wall=min(p.x,resolution.x-p.x)+4.;
 float radius=min(length(basis.xy),length(basis.zw));
 return blendDistance(disc(p,pose,basis),wall,radius*2.2);
}
vec3 material(vec2 q,float kind,float crop){
 vec2 tex=clamp(q*.5+.5,0.,1.);
 tex.x=tex.x*.58+.12+crop*.12;
 if(kind>3.5) return texture2D(town,tex).rgb;
 if(kind>2.5) return texture2D(market,tex).rgb;
 vec3 a=kind<.5?vec3(.77,.88,1.):kind<1.5?vec3(.81,.98,.59):vec3(.96,1.,.57);
 vec3 b=kind<.5?vec3(.22,.42,.58):kind<1.5?vec3(.17,.36,.25):vec3(.48,.57,.27);
 float sweep=smoothstep(-1.2,1.3,q.x*.65+q.y*.8);
 return mix(mix(vec3(1.),a,.8),b,sweep*.55);
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
 for(int i=0;i<24;i++){
  vec2 delta=abs(p-poses[i].xy);
  float reach=max(length(bases[i].xy),length(bases[i].zw))*5.;
  if(delta.x>reach||delta.y>reach) continue;
  float d=disc(p,poses[i],bases[i]);
  if(d<nearest){nearest=d;chosen=poses[i];basis=bases[i];}
 }
 float edge=min(p.x,resolution.x-p.x);
 float radius=min(length(basis.xy),length(basis.zw));
 float activation=1.-smoothstep(radius*1.5,radius*4.,min(chosen.x,resolution.x-chosen.x));
 float distance=mix(nearest,surface(p,chosen,basis),activation);
 if(distance>6.){
  float halo=abs(length((p-selection.xy)/max(selection.z,1.))-1.25);
  float ink=(1.-smoothstep(.012,.045,halo))*selection.w;
  gl_FragColor=vec4(mix(vec3(1.),vec3(.37,.49,.42),ink*.65),1.);return;
 }
 vec2 normal=normalize(vec2(
  surface(p+vec2(.5,0.),chosen,basis)-surface(p-vec2(.5,0.),chosen,basis),
  surface(p+vec2(0.,.5),chosen,basis)-surface(p-vec2(0.,.5),chosen,basis)));
 float neck=activation*(1.-smoothstep(0.,radius*3.,edge));
 float rim=exp(-abs(distance)*.17);
 vec2 q=localPoint(p,chosen,basis);
 // Refraction follows the boundary normal, including the narrowing bridge.
 vec2 bend=normal*neck*(.3+rim*.5);
 vec2 dispersion=normal*neck*(.035+rim*.11);
 vec3 color=vec3(
  refracted(q+bend+dispersion,chosen.z,chosen.w,neck*.17).r,
  refracted(q+bend,chosen.z,chosen.w,neck*.17).g,
  refracted(q+bend-dispersion,chosen.z,chosen.w,neck*.17).b);
 float softness=mix(.7,3.2,neck);
 vec3 coverage=vec3(
  1.-smoothstep(-softness,softness,distance+neck*rim*2.5),
  1.-smoothstep(-softness,softness,distance),
  1.-smoothstep(-softness,softness,distance-neck*rim*2.5));
 float edgeReveal=mix(1.,smoothstep(0.,24.,edge),fieldFade);
 gl_FragColor=vec4(mix(vec3(1.),color,coverage*edgeReveal),1.);
}`;

export interface WorldOptics { redraw(): void; dispose(): void }

/** Dependency-free rendering; native buttons remain the interaction surface. */
export function mountWorldOptics(root: HTMLElement, images: readonly string[]): WorldOptics | undefined {
  if (typeof WebGLRenderingContext === 'undefined') return undefined;
  const canvas = document.createElement('canvas');
  canvas.className = 'world-optics'; canvas.setAttribute('aria-hidden', 'true');
  const gl = canvas.getContext('webgl', { alpha: false, antialias: false, depth: false, stencil: false });
  if (!gl) return undefined;
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
    console.warn('World optics unavailable; retaining native previews.', error); return undefined;
  }
  gl.useProgram(program);
  const buffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]), gl.STATIC_DRAW);
  const position = gl.getAttribLocation(program, 'position'); gl.enableVertexAttribArray(position); gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
  const poseLocation = gl.getUniformLocation(program, 'poses[0]'), basisLocation = gl.getUniformLocation(program, 'bases[0]'), resolutionLocation = gl.getUniformLocation(program, 'resolution'), fadeLocation = gl.getUniformLocation(program, 'fieldFade');
  const poses = new Float32Array(ORBIT_COUNT * 4), bases = new Float32Array(ORBIT_COUNT * 4);
  const textures: WebGLTexture[] = [];
  let disposed = false, frame = 0, elapsed = 2, previous = 0, width = 0, height = 0;
  let hovered = false, focused = false, visible = true;
  let emphasis = 0, loaded = 0;
  const selectionLocation = gl.getUniformLocation(program, 'selection');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const choices = [...root.querySelectorAll<HTMLElement>('.world-choice')];
  const originalStyles = choices.map(button => button.style.cssText);
  const active = () => visible && !document.hidden && (!document.documentElement.dataset.surface || document.documentElement.dataset.surface === 'title');
  const paused = () => reduced.matches || hovered || focused || root.dataset.selected !== undefined;
  const draw = (now: number) => {
    frame = 0;
    if (disposed || !width || !height || !active()) { previous = 0; return; }
    if (previous && !paused()) elapsed += Math.min((now - previous) / 1000, .05);
    previous = now;
    const selected = root.dataset.selected;
    const target = selected === undefined ? 0 : 1;
    emphasis = reduced.matches ? target : emphasis + (target - emphasis) * .2;
    if (Math.abs(target - emphasis) < .002) emphasis = target;
    gl.uniform4f(selectionLocation, 0, 0, 0, 0);
    for (let index = 0; index < ORBIT_COUNT; index += 1) {
      const pose = orbitPose(index, elapsed, width, height);
      if ((selected === '0' && index === 7) || (selected === '1' && index === 14)) {
        const scale = 1 + emphasis * .08;
        pose.ax *= scale; pose.ay *= scale; pose.bx *= scale; pose.by *= scale;
        gl.uniform4f(selectionLocation, pose.x, pose.y, Math.max(Math.hypot(pose.ax, pose.ay), Math.hypot(pose.bx, pose.by)), emphasis);
      }
      poses.set([pose.x, pose.y, pose.material, index % 4 / 3], index * 4);
      bases.set([pose.ax, pose.ay, pose.bx, pose.by], index * 4);
      const button = index === 7 ? choices[0] : index === 14 ? choices[1] : undefined;
      if (button && root.classList.contains('has-optics')) {
        const rx = Math.hypot(pose.ax, pose.bx), ry = Math.hypot(pose.ay, pose.by);
        button.style.cssText = `left:${pose.x-rx}px;top:${pose.y-ry}px;width:${rx*2}px;height:${ry*2}px`;
      }
    }
    gl.uniform1f(fadeLocation, width < window.innerWidth - 1 ? 1 : 0); gl.uniform2f(resolutionLocation, width, height); gl.uniform4fv(poseLocation, poses); gl.uniform4fv(basisLocation, bases);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    if (!paused() || emphasis !== target) frame = requestAnimationFrame(draw);
  };
  const redraw = () => { previous = 0; if (!disposed && !frame) frame = requestAnimationFrame(draw); };
  images.slice(0,2).forEach((source, index) => {
    const texture = gl.createTexture()!; textures.push(texture);
    gl.activeTexture(gl.TEXTURE0 + index); gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([198,225,255,255]));
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.uniform1i(gl.getUniformLocation(program, index ? 'town' : 'market'), index);
    const image = new Image(); image.onload = () => {
      if (disposed) return;
      gl.activeTexture(gl.TEXTURE0 + index); gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image); loaded += 1;
      if (loaded === 2) root.classList.add('has-optics');
      redraw();
    }; image.onerror = () => dispose(); image.src = source;
  });
  const resize = new ResizeObserver(entries => {
    const bounds = entries[0]?.contentRect; if (!bounds) return;
    width = bounds.width; height = bounds.height;
    const density = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(width * density); canvas.height = Math.round(height * density);
    gl.viewport(0,0,canvas.width,canvas.height); redraw();
  });
  const intersection = new IntersectionObserver(entries => { visible = entries[0]?.isIntersecting ?? false; redraw(); });
  const mutation = new MutationObserver(redraw);
  const enter = () => { hovered = true; redraw(); }, leave = () => { hovered = false; redraw(); };
  const focus = (event: FocusEvent) => {
    focused = true;
    const index = event.currentTarget === choices[0] ? 7 : 14;
    const pose = orbitPose(index, elapsed, width, height);
    // A keyboard target that has passed beyond the viewport returns along its
    // own circular track before the field holds for selection.
    if (pose.x < 32 || pose.x > width - 32) {
      const direction = index < 12 ? 1 : -1;
      elapsed = ((.25 - index % 12 / 12) * ORBIT_PERIOD / direction + ORBIT_PERIOD) % ORBIT_PERIOD;
    }
    redraw();
  }, blur = () => { focused = false; redraw(); };
  for (const button of choices) { button.addEventListener('pointerenter',enter); button.addEventListener('pointerleave',leave); button.addEventListener('focus',focus); button.addEventListener('blur',blur); }
  root.prepend(canvas);
  resize.observe(root); intersection.observe(root); mutation.observe(document.documentElement,{attributes:true,attributeFilter:['data-surface']}); mutation.observe(root,{subtree:true,attributes:true,attributeFilter:['data-selected']});
  document.addEventListener('visibilitychange',redraw); reduced.addEventListener('change',redraw);
  const dispose = () => {
    if (disposed) return;
    disposed = true; cancelAnimationFrame(frame); resize.disconnect(); intersection.disconnect(); mutation.disconnect();
    document.removeEventListener('visibilitychange',redraw); reduced.removeEventListener('change',redraw);
    for (const button of choices) { button.removeEventListener('pointerenter',enter); button.removeEventListener('pointerleave',leave); button.removeEventListener('focus',focus); button.removeEventListener('blur',blur); }
    for (const texture of textures) gl.deleteTexture(texture); for (const shader of shaders) gl.deleteShader(shader);
    gl.deleteProgram(program); gl.deleteBuffer(buffer); canvas.remove(); root.classList.remove('has-optics');
    choices.forEach((button, index) => { button.style.cssText = originalStyles[index]!; });
  };
  canvas.addEventListener('webglcontextlost', dispose, { once: true });
  return { redraw, dispose };
}
