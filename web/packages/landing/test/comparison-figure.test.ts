// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { buildComparisonFigure } from '../src/ui/comparison-figure.js';
import { comparisonPose, createComparisonSequence } from '../src/ui/comparison-sequence.js';
import { RECORDER_PARTS, recorderFaces, recorderOrder, recorderVertices } from '../src/ui/comparison-geometry.js';

let intersection: ((entries: IntersectionObserverEntry[])=>void) | undefined;
const disconnect=vi.fn();
beforeEach(()=> {
  vi.useFakeTimers({toFake:['requestAnimationFrame','cancelAnimationFrame','performance']});
  vi.stubGlobal('IntersectionObserver',class {
    constructor(callback: (entries: IntersectionObserverEntry[])=>void) {intersection=callback;}
    observe() {} disconnect=disconnect;
  });
});
afterEach(async ()=> {
  document.body.replaceChildren();await Promise.resolve();
  Reflect.deleteProperty(document,'visibilityState');delete document.documentElement.dataset.reducedMotion;
  vi.clearAllTimers();vi.useRealTimers();vi.unstubAllGlobals();vi.restoreAllMocks();disconnect.mockClear();
});
const visible=(...states: boolean[])=>intersection?.(states.map(isIntersecting=>({isIntersecting}) as IntersectionObserverEntry));
const mount=async ()=> {
  const host=document.createElement('section');host.append(buildComparisonFigure(host));document.body.append(host);await Promise.resolve();visible(true);return host;
};
const figure=(host: HTMLElement)=>host.querySelector<HTMLElement>('.comparison-figure')!;
const position=(host: HTMLElement)=>Number(figure(host).dataset.position);
const selected=(host: HTMLElement)=>host.querySelector<HTMLButtonElement>('[role="tab"][aria-selected="true"]')!;
const play=(host: HTMLElement)=>host.querySelector<HTMLButtonElement>('.recorder-play')!;

describe('comparison recorder',()=> {
  it('keeps keyboard selection, range, readout and real depth motion together',async ()=> {
    const host=await mount();
    selected(host).dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true}));
    const range=host.querySelector<HTMLInputElement>('.recorder-range')!;
    expect(document.activeElement).toBe(selected(host));
    expect(selected(host).textContent).toBe('Outcome and Replay');
    expect(host.querySelector('[role="tabpanel"]')?.getAttribute('aria-labelledby')).toBe(selected(host).id);
    expect(range.getAttribute('aria-valuetext')).toBe('Outcome and Replay');
    expect(host.querySelector('.recorder-readout')?.textContent).toBe(comparisonPose(Number(range.value)/100).readout);
    const headPose=()=>Array.from(host.querySelectorAll<SVGPathElement>('[data-face^="candidate-a-model-"]')).filter(path=>path.style.display!=='none').map(path=>path.getAttribute('d')).join(':');
    const replayHead=headPose();
    range.value='150';range.dispatchEvent(new Event('input',{bubbles:true}));
    expect(selected(host).textContent).toBe('Recorded Decisions');
    expect(headPose()).not.toBe(replayHead);
    vi.advanceTimersByTime(3000);expect(position(host)).toBe(1.5);
    expect(host.querySelectorAll('[role="tab"][tabindex="0"]')).toHaveLength(1);
    // The explanatory figure cannot call a provider or read synthetic results as live output.
    expect(host.querySelector('canvas,svg text')).toBeNull();
  });

  it('suspends on the newest intersection, routed inactivity, background and document visibility',async ()=> {
    const host=await mount();vi.advanceTimersByTime(300);
    for(const suspend of ['intersection','inert','hidden','visibility','blur'] as const) {
      const before=position(host);
      if(suspend==='intersection') visible(true,false);
      if(suspend==='inert'||suspend==='hidden') host.setAttribute(suspend,'');
      if(suspend==='visibility') {Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});document.dispatchEvent(new Event('visibilitychange'));}
      if(suspend==='blur') window.dispatchEvent(new Event('blur'));
      await Promise.resolve();vi.advanceTimersByTime(6000);expect(position(host)).toBe(before);
      if(suspend==='intersection') visible(false,true);
      if(suspend==='inert'||suspend==='hidden') host.removeAttribute(suspend);
      if(suspend==='visibility') {Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});document.dispatchEvent(new Event('visibilitychange'));}
      if(suspend==='blur') window.dispatchEvent(new Event('focus'));
      await Promise.resolve();vi.advanceTimersByTime(32);
      expect(position(host)).toBeGreaterThan(before);expect(position(host)-before).toBeLessThan(.01);
    }
  });

  it('keeps reduced motion manually explorable, preserves the pose, and disposes when removed',async ()=> {
    document.documentElement.dataset.reducedMotion='true';
    const host=await mount(),start=position(host);
    vi.advanceTimersByTime(6000);expect(position(host)).toBe(start);expect(play(host).disabled).toBe(true);
    selected(host).dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
    expect(position(host)).toBe(1.65);expect(selected(host).textContent).toBe('Recorded Decisions');
    const held=figure(host).innerHTML;
    vi.advanceTimersByTime(6000);expect(figure(host).innerHTML).toBe(held);
    host.remove();await Promise.resolve();expect(disconnect).toHaveBeenCalledOnce();
    delete document.documentElement.dataset.reducedMotion;window.dispatchEvent(new Event('focus'));
    vi.advanceTimersByTime(6000);expect(position(host)).toBe(1.65);expect(vi.getTimerCount()).toBe(0);
  });

  it('stops at the end of its illustration and restarts explicitly',async ()=> {
    const host=await mount();
    // Avoid rendering every demonstration frame in a DOM test; advance from its final instant.
    const range=host.querySelector<HTMLInputElement>('.recorder-range')!;range.value='299';range.dispatchEvent(new Event('input'));
    play(host).click();vi.advanceTimersByTime(160);
    expect(position(host)).toBe(3);expect(play(host).textContent).toBe('Play Figure');
    const held=figure(host).innerHTML;vi.advanceTimersByTime(1000);expect(figure(host).innerHTML).toBe(held);
    play(host).click();vi.advanceTimersByTime(32);expect(position(host)).toBeLessThan(.01);
  });
});

it('uses active time without jumping after suspension or a delayed frame',()=> {
  const clock=createComparisonSequence();clock.advance(0);clock.advance(100);
  const held=clock.position;clock.suspend();clock.advance(20000);expect(clock.position).toBe(held);
  clock.advance(40000);expect(clock.position-held).toBeCloseTo(100*3/18000);
});

it('keeps complete records through replay and physically isolates its model heads',()=> {
  const recording=comparisonPose(1.6),replay=comparisonPose(2.6);
  expect(recording.recorded).toBeCloseTo(.6);expect(recording.headAngle).toBeCloseTo(0);
  expect(replay.recorded).toBe(1);expect(replay.headAngle).toBeLessThan(-60);
  const head=RECORDER_PARTS.find(part=>part.id==='candidate-a-model')!;
  const closed=recorderVertices(head,1.6),opened=recorderVertices(head,2.6);
  const length=(points: readonly (readonly number[])[])=>Math.hypot(...points[1]!.map((v,i)=>v-points[0]![i]!));
  expect(length(opened[0]!)).toBeCloseTo(length(closed[0]!));
  expect(Math.min(...opened.flat().map(p=>p[2]))).toBeGreaterThanOrEqual(14);
});

it('keeps the actual faces ordered and inside the drawing across recording, replay and reversals',()=> {
  const path=[...Array.from({length:61},(_,i)=>i/20),...Array.from({length:61},(_,i)=>3-i/20)];
  for(const position of path) {
    const faces=recorderFaces(position),ordered=recorderOrder(faces);
    expect(ordered.length).toBe(faces.length);expect(new Set(ordered.map(face=>face.id)).size).toBe(faces.length);
    for(const face of faces) for(const [x,y] of face.points) {
      expect(Number.isFinite(x)&&Number.isFinite(y)).toBe(true);
      expect(x).toBeGreaterThan(0);expect(x).toBeLessThan(640);expect(y).toBeGreaterThan(0);expect(y).toBeLessThan(450);
    }
  }
});

it('keeps solid contacts flush and moving hardware clear through depth',()=> {
  type Vector=readonly [number,number,number];
  const sub=(a:Vector,b:Vector):Vector=>[a[0]-b[0],a[1]-b[1],a[2]-b[2]];
  const cross=(a:Vector,b:Vector):Vector=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const dot=(a:Vector,b:Vector)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
  const directions=(vectors:Vector[])=> {
    const unique=new Map<string,Vector>();
    for(const vector of vectors) {
      const length=Math.hypot(...vector);if(length<1e-8) continue;
      const unit=vector.map(v=>v/length) as unknown as Vector;
      const sign=unit.find(v=>Math.abs(v)>1e-8)!<0?-1:1;
      const normal=unit.map(v=>v*sign) as unknown as Vector;
      unique.set(normal.map(v=>v.toFixed(6)).join(','),normal);
    }
    return [...unique.values()];
  };
  // Independent convex-solid separating-axis check, including edge cross products.
  for(const position of [0,.3,.65,1,1.5,2,2.03,2.06,2.1,2.15,2.2,2.3,2.65,3]) {
    const solids=RECORDER_PARTS.map(part=> {
      const faces=recorderVertices(part,position),points=faces.flat();
      const normals=directions(faces.map(face=>cross(sub(face[1]!,face[0]!),sub(face[2]!,face[0]!))));
      const edges=directions(faces.flatMap(face=>face.map((p,i)=>sub(face[(i+1)%face.length]!,p))));
      return {id:part.id,points,normals,edges,bounds:[0,1,2].map(i=>[Math.min(...points.map(p=>p[i]!)),Math.max(...points.map(p=>p[i]!))])};
    });
    const collisions:string[]=[];
    for(let i=0;i<solids.length;i++) for(let j=i+1;j<solids.length;j++) {
      const a=solids[i]!,b=solids[j]!;
      if(a.bounds.some(([lo,hi],axis)=>hi!<=b.bounds[axis]![0]!+1e-7||b.bounds[axis]![1]!<=lo!+1e-7)) continue;
      const axes=[...a.normals,...b.normals,...directions(a.edges.flatMap(one=>b.edges.map(two=>cross(one,two))))];
      const separate=axes.some(axis=> {
        const one=a.points.map(p=>dot(p,axis)),two=b.points.map(p=>dot(p,axis));
        return Math.max(...one)<=Math.min(...two)+1e-7||Math.max(...two)<=Math.min(...one)+1e-7;
      });
      if(!separate) collisions.push(`${a.id} / ${b.id}`);
    }
    expect(collisions,`Solid intersections at ${position}`).toEqual([]);
  }
});
