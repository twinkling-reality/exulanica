import { el } from './dom.js';

/** Editorial material studies. These are abstract covers, never product screenshots. */
const vertex = `attribute vec2 position; varying vec2 uv;
void main(){uv=position*.5+.5;gl_Position=vec4(position,0.,1.);}`;
const fragment = `precision highp float;
varying vec2 uv;
uniform vec2 size;
uniform vec2 pointer;
uniform float study;
float field(vec2 p){
 p+=pointer*.025;
 if(study<.5) return p.x*.7+p.y*.25+.24*sin(p.y*3.2)+.09*sin(p.x*3.+p.y*2.);
 if(study<1.5) return length((p-vec2(1.4,-.8))*vec2(.85,1.))+.13*sin(p.y*3.);
 return p.y*.72+p.x*.25+.23*sin(p.x*2.4)+.06*cos(p.y*5.);
}
vec3 palette(float t){
 vec3 a=study<.5?vec3(.83,.94,.94):(study<1.5?vec3(.96,.86,.88):vec3(.94,.96,.78));
 vec3 b=study<.5?vec3(.40,.61,.74):(study<1.5?vec3(.62,.55,.74):vec3(.42,.64,.62));
 vec3 c=study<.5?vec3(.69,.63,.80):(study<1.5?vec3(.68,.81,.86):vec3(.66,.73,.88));
 return mix(mix(a,b,smoothstep(-.8,.8,t)),c,smoothstep(.15,1.4,t));
}
void main(){
 vec2 p=(uv-.5)*vec2(size.x/size.y,1.)*2.;
 float f=field(p);
 float phase=f*8.;
 float fold=sin(phase);
 float fine=sin(phase*2.+.3)*.04;
 vec3 color=palette(f+.15*fold);
 float shadow=pow(max(0.,.5+.5*cos(phase+.45)),10.);
 float highlight=pow(max(0.,.5+.5*cos(phase-.22)),32.);
 color=mix(color,color*vec3(.42,.53,.62),shadow*.5);
 color=mix(color,vec3(.99,.99,.94),highlight*.7);
 float broadLight=exp(-length(p-vec2(-.65,.65))*1.15);
 color=mix(color,vec3(.98,.97,.93),broadLight*.58);
 color+=fine*.2;
 gl_FragColor=vec4(color,1.);
}`;

/** Lazily render only visible covers; light movement follows the pointer, never an endless loop. */
export function editorialCover(index: number): HTMLElement {
  const root = el('div', { class: `editorial-cover editorial-cover-${index}`, 'aria-hidden': 'true' });
  if (typeof IntersectionObserver === 'undefined' || typeof WebGLRenderingContext === 'undefined') return root;
  const canvas = el('canvas', {});
  let gl: WebGLRenderingContext | null = null;
  let program: WebGLProgram | null = null;
  let buffer: WebGLBuffer | null = null;
  let visible = false, frame = 0, failed = false;
  let x = 0, y = 0, targetX = 0, targetY = 0;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const shaders: WebGLShader[] = [];
  const release = () => {
    cancelAnimationFrame(frame); frame = 0;
    if (gl) { shaders.forEach(shader => gl!.deleteShader(shader)); gl.deleteBuffer(buffer); gl.deleteProgram(program); }
    canvas.remove(); gl = null; program = null;
  };
  const init = () => {
    gl = canvas.getContext('webgl', { alpha: false, antialias: false, depth: false, stencil: false, powerPreference: 'low-power' });
    if (!gl) { failed = true; return; }
    program = gl.createProgram();
    for (const [type, source] of [[gl.VERTEX_SHADER, vertex], [gl.FRAGMENT_SHADER, fragment]] as const) {
      const shader = gl.createShader(type)!; shaders.push(shader);
      gl.shaderSource(shader, source); gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) { failed = true; release(); return; }
      gl.attachShader(program!, shader);
    }
    gl.linkProgram(program!);
    if (!gl.getProgramParameter(program!, gl.LINK_STATUS)) { failed = true; release(); return; }
    gl.useProgram(program);
    buffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]), gl.STATIC_DRAW);
    const location = gl.getAttribLocation(program!, 'position'); gl.enableVertexAttribArray(location); gl.vertexAttribPointer(location,2,gl.FLOAT,false,0,0);
    root.append(canvas);
  };
  const draw = () => {
    frame = 0;
    if (!visible || document.hidden || failed) return;
    if (!gl) init();
    if (!gl || !program) return;
    const bounds = root.getBoundingClientRect();
    const density = Math.min(window.devicePixelRatio || 1, 1.5, 1200 / bounds.width);
    const width = Math.round(bounds.width * density), height = Math.round(bounds.height * density);
    if (!width || !height) return;
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; gl.viewport(0,0,width,height); }
    x += (targetX-x)*.12; y += (targetY-y)*.12;
    gl.uniform2f(gl.getUniformLocation(program,'size'),width,height);
    gl.uniform2f(gl.getUniformLocation(program,'pointer'),reduced.matches?0:x,reduced.matches?0:y);
    gl.uniform1f(gl.getUniformLocation(program,'study'),index);
    gl.drawArrays(gl.TRIANGLES,0,6);
    if (!reduced.matches && Math.abs(targetX-x)+Math.abs(targetY-y)>.015) frame=requestAnimationFrame(draw);
  };
  const redraw = () => { if (!frame && visible && !failed) frame=requestAnimationFrame(draw); };
  const observer = new IntersectionObserver(entries => { visible=entries[0]?.isIntersecting??false; if (!visible) { cancelAnimationFrame(frame); frame=0; } else redraw(); });
  observer.observe(root);
  new ResizeObserver(redraw).observe(root);
  root.addEventListener('pointermove',event=> { if (event.pointerType==='touch'||reduced.matches) return; const b=root.getBoundingClientRect();targetX=(event.clientX-b.left)/b.width*2-1;targetY=(event.clientY-b.top)/b.height*2-1;redraw(); });
  root.addEventListener('pointerleave',()=> { targetX=0;targetY=0;redraw(); });
  canvas.addEventListener('webglcontextlost',event=> { event.preventDefault();failed=true;release(); });
  document.addEventListener('visibilitychange',redraw);
  reduced.addEventListener('change',redraw);
  return root;
}
