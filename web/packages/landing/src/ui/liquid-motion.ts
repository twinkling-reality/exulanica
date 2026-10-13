import type { OrbitPose } from './world-orbit-geometry.js';

export interface LiquidMotion { index: number; strength: number; x: number; y: number }

/** Project travel into the lens's local plane; deformation follows visible motion. */
export function lensMotions(current: readonly OrbitPose[], next: readonly OrbitPose[], seconds: number): LiquidMotion[] {
  return current.map((pose,index) => {
    const dx=(next[index]!.x-pose.x)/seconds, dy=(next[index]!.y-pose.y)/seconds;
    const det=pose.ax*pose.by-pose.ay*pose.bx;
    const x=(pose.by*dx-pose.bx*dy)/det, y=(-pose.ay*dx+pose.ax*dy)/det;
    const speed=Math.hypot(x,y);
    const radius=Math.min(Math.hypot(pose.ax,pose.ay),Math.hypot(pose.bx,pose.by));
    const visibleSpeed=Math.hypot(dx,dy)/radius;
    return { index,x:speed ? x/speed : 0,y:speed ? y/speed : 0,strength:Math.max(0,(visibleSpeed-.6)/.3) };
  });
}

/** The two strongest motion responses ease in; replacements wait for the old lens to settle. */
export class LiquidMotionState {
  readonly active: LiquidMotion[] = [{index:-1,strength:0,x:0,y:0},{index:-1,strength:0,x:0,y:0}];
  update(motions: readonly LiquidMotion[], delta: number, resting: boolean): boolean {
    const desired=resting ? [] : [...motions].filter(m=>m.strength>.1).sort((a,b)=>b.strength-a.strength).slice(0,2);
    let settling=false;
    for(const lens of this.active) {
      const retained=desired.find(m=>m.index===lens.index);
      const target=Math.min(1,retained?.strength ?? 0);
      lens.strength+=(target-lens.strength)*(1-Math.exp(-delta/.28));
      if(Math.abs(target-lens.strength)<.005) lens.strength=target;
      const travel=motions[lens.index];
      if(travel) { lens.x=travel.x; lens.y=travel.y; }
      if(!retained && lens.strength===0) {
        const replacement=desired.find(m=>!this.active.some(other=>other!==lens && other.index===m.index));
        lens.index=replacement?.index ?? -1;
        lens.x=replacement?.x ?? 0; lens.y=replacement?.y ?? 0;
      }
      if(lens.strength!==target || lens.index>=0 && lens.strength===0) settling=true;
    }
    return settling;
  }
}
