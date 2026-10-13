import { COMPARISON_FIGURE as FIGURE, COMPARISON_LANES } from '../content/comparison-figure.js';
import { comparisonPose } from './comparison-sequence.js';

export type Point3 = readonly [number, number, number];
type Point2 = readonly [number, number];
export interface RecorderPart {
  id: string; x: number; y: number; z: number; w: number; d: number; h: number;
  material: string; motion?: 'source' | 'head' | 'reader'; lane?: number;
}
export interface RecorderFace { id: string; points: Point2[]; depth: number[]; shade: number; material: string; dynamic: boolean; opacity?: number }
const radians = (value: number) => value * Math.PI / 180;
const azimuth = radians(52), elevation = radians(43);
const camera: Point3 = [Math.cos(azimuth) * Math.cos(elevation), Math.sin(azimuth) * Math.cos(elevation), Math.sin(elevation)];
const light: Point3 = [-.25, -.35, .9];
const dot = (a: Point3, b: Point3) => a.reduce((sum, value, index) => sum + value * b[index]!, 0);
const cross = (a: Point3, b: Point3): Point3 => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
const subtract = (a: Point3, b: Point3): Point3 => [a[0]-b[0],a[1]-b[1],a[2]-b[2]];

/** A recorder's hardware. One shared source, four independent strips, two control lanes.
 * Rails support the readers; sockets support the model heads; every detail belongs to a mount.
 */
export const RECORDER_PARTS: readonly RecorderPart[] = (() => {
  const parts: RecorderPart[] = [];
  const add = (id: string, x: number, y: number, z: number, w: number, d: number, h: number,
    material = 'metal', motion?: RecorderPart['motion'], lane?: number) => parts.push({id,x,y,z,w,d,h,material,...(motion ? {motion}:{}),...(lane!==undefined?{lane}:{})});
  for (const x of [-154,142]) for (const y of [-106,114]) add(`foot-${x}-${y}`,x,y,-15,18,15,7,'dark');
  add('base',-168,-120,-8,338,252,8);
  add('source-spine',-131,-110,0,14,222,7,'source');
  add('source-socket',-161,-26,0,30,66,9);
  add('source-card',-161,-23,9,27,60,4,'source','source');
  add('source-grip',-161,-5,13,4,24,3,'dark','source');
  // A small engraved plan identifies the cartridge as world state, without invented world data.
  for (const [index, x, y] of [[0,-151,-15],[1,-141,-15],[2,-151,13],[3,-141,13]])
    add(`source-relief-${index}`,x!,y!,13,6,12,1.3,'paper','source');
  COMPARISON_LANES.forEach((lane, index) => {
    const y = lane.y;
    add(`${lane.key}-mount`,-110,y-22,0,268,44,3);
    add(`${lane.key}-socket`,-109,y-18,3,42,36,6,'dark');
    add(`${lane.key}-hinge`,-109,y-19,9,5,38,5);
    add(`${lane.key}-dock`,-104,y-16,9,34,32,5,'metal');
    add(`${lane.key}-model`,-104,y-17,14,34,34,9,lane.model,'head',index);
    add(`${lane.key}-model-inlay`,-99,y-12,23,23,24,1.1,'paper','head',index);
    add(`${lane.key}-feed`,-117,y-3,3,8,6,4,'source');
    for (const offset of [-19,16]) add(`${lane.key}-rail-${offset}`,-62,y+offset,3,215,3,4,'dark');
    for (const x of [-65,153]) add(`${lane.key}-stop-${x}`,x,y-20,3,3,40,7);
    add(`${lane.key}-strip`,-60,y-12,3,210,24,1,'paper');
    for (const offset of [-19,14]) add(`${lane.key}-shoe-${offset}`,-54,y+offset,7,12,5,4,'metal','reader',index);
    add(`${lane.key}-reader`,-54,y-19,11,12,38,3,'metal','reader',index);
    add(`${lane.key}-lens`,-51,y-10,14,6,20,1.2,'dark','reader',index);
  });
  return parts;
})();

export function recorderVertices(part: RecorderPart, position: number): Point3[][] {
  const pose = comparisonPose(position);
  const {x,y,z,w,d,h} = part;
  // Chamfered corners give the machined plates real bevels and keep every primitive convex.
  const r = Math.min(1.6,w/4,d/4);
  const ring: Point2[] = [[x+r,y],[x+w-r,y],[x+w,y+r],[x+w,y+d-r],[x+w-r,y+d],[x+r,y+d],[x,y+d-r],[x,y+r]];
  const transform = (p: Point3): Point3 => {
    if (part.motion === 'source') return [p[0]-(1-pose.source)*13,p[1],p[2]];
    if (part.motion === 'reader') return [p[0] + pose.reader * (FIGURE.railEnd-FIGURE.railStart),p[1],p[2]];
    if (part.motion !== 'head') return p;
    // Rigid rotation about the actual socket hinge, including its mounted inlay.
    const angle = radians(pose.headAngle), px=p[0]+104, pz=p[2]-14;
    return [-104+px*Math.cos(angle)+pz*Math.sin(angle),p[1],14-px*Math.sin(angle)+pz*Math.cos(angle)];
  };
  const bottom=ring.map(([px,py])=>transform([px,py,z]));
  const top=ring.map(([px,py])=>transform([px,py,z+h]));
  return [top, ...ring.map((_,index)=>[bottom[index]!,bottom[(index+1)%ring.length]!,top[(index+1)%ring.length]!,top[index]!])];
}

const rawProject = ([x,y,z]: Point3): Point2 => [x*Math.sin(azimuth)-y*Math.cos(azimuth),
  (x*Math.cos(azimuth)+y*Math.sin(azimuth))*Math.sin(elevation)-z*Math.cos(elevation)];
const extremes = RECORDER_PARTS.flatMap(part=>[0,2.3,3].flatMap(at=>recorderVertices(part,at).flat().map(rawProject)));
const bounds = [Math.min(...extremes.map(p=>p[0])),Math.min(...extremes.map(p=>p[1])),Math.max(...extremes.map(p=>p[0])),Math.max(...extremes.map(p=>p[1]))];
const scale = Math.min((FIGURE.width-100)/(bounds[2]!-bounds[0]!), (FIGURE.height-90)/(bounds[3]!-bounds[1]!));
export function recorderProject(point: Point3): Point2 {
  const raw=rawProject(point);
  return [FIGURE.width/2 + (raw[0]-(bounds[0]!+bounds[2]!)/2)*scale,
    FIGURE.height/2 + (raw[1]-(bounds[1]!+bounds[3]!)/2)*scale];
}
export const recorderPath = (points: readonly Point2[]) => points.map(([x,y],index)=>`${index?'L':'M'}${x.toFixed(3)} ${y.toFixed(3)}`).join('')+'Z';

export function recorderFaces(position: number): RecorderFace[] {
  const parts = RECORDER_PARTS.flatMap(part=>recorderVertices(part,position).flatMap((vertices,index)=> {
    const normal=cross(subtract(vertices[1]!,vertices[0]!),subtract(vertices[2]!,vertices[0]!));
    const length=Math.hypot(...normal);
    const unit=normal.map(value=>value/length) as unknown as Point3;
    if(dot(unit,camera)<1e-7) return [];
    return [{id:`${part.id}-${index}`,points:vertices.map(recorderProject),depth:vertices.map(p=>dot(p,camera)),
      shade: Math.max(0,Math.min(3,(dot(unit,light)+1)*1.5)),material:part.material,dynamic:!!part.motion}];
  }));
  const pose=comparisonPose(position);
  const marks: RecorderFace[]=COMPARISON_LANES.flatMap(lane=>Array.from({length:FIGURE.recordMarks},(_,index)=> {
    const x=-57+index*17;
    const vertices: Point3[]=[[x,lane.y-7,4.02],[x+11,lane.y-7,4.02],[x+11,lane.y+7,4.02],[x,lane.y+7,4.02]];
    return {id:`${lane.key}-record-${index}`,points:vertices.map(recorderProject),depth:vertices.map(p=>dot(p,camera)),
      shade:3,material:'record',dynamic:true,opacity:Math.max(0,Math.min(1,(pose.recorded*FIGURE.recordMarks-index)*2))};
  }));
  const screws: RecorderFace[]=RECORDER_PARTS.filter(part=>part.id==='base'||part.id.endsWith('-mount')||part.id==='source-socket').flatMap(part=> {
    const margin=part.id==='base'?10:4;
    return [part.x+margin,part.x+part.w-margin].flatMap(x=>[part.y+margin,part.y+part.d-margin].map(y=> {
      const vertices: Point3[]=[[x-1,y-1,part.z+part.h+.02],[x+1,y-1,part.z+part.h+.02],[x+1,y+1,part.z+part.h+.02],[x-1,y+1,part.z+part.h+.02]];
      return {id:`${part.id}-screw-${x}-${y}`,points:vertices.map(recorderProject),depth:vertices.map(p=>dot(p,camera)),shade:3,material:'dark',dynamic:false};
    }));
  });
  return [...parts,...marks,...screws];
}

/** Actual overlap depths determine painter's order. Centre sorting can hide a far reader
 * behind the large base. Planar face clipping catches that error and motion through depth.
 */
const side = (a: Point2,b: Point2,p: Point2) => (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]);
function overlap(one: Point2[],two: Point2[]): Point2[] {
  let polygon=one;
  const sign=Math.sign(two.reduce((sum,p,i)=>sum+p[0]*two[(i+1)%two.length]![1]-p[1]*two[(i+1)%two.length]![0],0));
  for(let index=0;index<two.length && polygon.length;index++) {
    const a=two[index]!,b=two[(index+1)%two.length]!;
    const output: Point2[]=[];
    polygon.forEach((p,i)=> {
      const q=polygon[(i+1)%polygon.length]!;
      const sp=side(a,b,p)*sign,sq=side(a,b,q)*sign;
      if(sp>=0) output.push(p);
      if((sp>=0)!==(sq>=0)) { const t=sp/(sp-sq); output.push([p[0]+(q[0]-p[0])*t,p[1]+(q[1]-p[1])*t]); }
    });
    polygon=output;
  }
  return polygon;
}
function depthAt(face: RecorderFace,p: Point2) {
  const [a,b,c]=face.points as [Point2,Point2,Point2];
  const determinant=side(a,b,c);
  const u=((p[0]-a[0])*(c[1]-a[1])-(p[1]-a[1])*(c[0]-a[0]))/determinant;
  const v=((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]))/determinant;
  return face.depth[0]!+u*(face.depth[1]!-face.depth[0]!)+v*(face.depth[2]!-face.depth[0]!);
}
export function recorderOrder(faces: readonly RecorderFace[]): RecorderFace[] {
  const boxes=faces.map(face=>[Math.min(...face.points.map(p=>p[0])),Math.min(...face.points.map(p=>p[1])),Math.max(...face.points.map(p=>p[0])),Math.max(...face.points.map(p=>p[1]))]);
  const edges=faces.map(()=>new Set<number>()),incoming=faces.map(()=>0);
  for(let i=0;i<faces.length;i++) for(let j=i+1;j<faces.length;j++) {
    const a=boxes[i]!,b=boxes[j]!;
    if(a[0]!>=b[2]!-1e-4||b[0]!>=a[2]!-1e-4||a[1]!>=b[3]!-1e-4||b[1]!>=a[3]!-1e-4) continue;
    const points=overlap(faces[i]!.points,faces[j]!.points);
    if(points.length<3) continue;
    const area=Math.abs(points.reduce((sum,p,k)=>sum+p[0]*points[(k+1)%points.length]![1]-p[1]*points[(k+1)%points.length]![0],0))/2;
    if(area<.001) continue;
    const center: Point2=[points.reduce((sum,p)=>sum+p[0],0)/points.length,points.reduce((sum,p)=>sum+p[1],0)/points.length];
    const difference=depthAt(faces[i]!,center)-depthAt(faces[j]!,center);
    if(Math.abs(difference)<1e-5) continue;
    const from=difference<0?i:j,to=difference<0?j:i;
    edges[from]!.add(to); incoming[to]!++;
  }
  const ready=incoming.flatMap((count,i)=>count===0?[i]:[]),ordered: RecorderFace[]=[];
  for(let index=0;index<ready.length;index++) {
    const next=ready[index]!;
    ordered.push(faces[next]!);
    for(const to of edges[next]!) { incoming[to]=incoming[to]!-1; if(incoming[to]===0) ready.push(to); }
  }
  if(ordered.length!==faces.length) throw new Error('Recorder geometry has an occlusion cycle');
  return ordered;
}
