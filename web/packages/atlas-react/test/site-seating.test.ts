// @vitest-environment happy-dom
import * as pc from 'playcanvas';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { readStylePackManifest, resolveStylePack, type LookFamily } from '@exulanica/atlas-core';
import { fetchPackPieces, uploadPackPieces } from '../src/playcanvas/style-pack/pieces.js';
import { dressSlots } from '../src/playcanvas/style-pack/dresser.js';
import { describe, expect, it } from 'vitest';
import { drawnSiteSeats, seatGeometry } from '../src/playcanvas/generated-site/site-seating.js';
import { drawSiteSlots, parseStructuredSiteDrawing } from '../src/playcanvas/generated-site/index.js';
import { fixtureSeatDrawing, placeDrawing, type FixtureSeat } from '../src/playcanvas/society/seating.js';

const plane = (y: number) => [0,y,0, 2,y,0, 0,y,2];
const normals = [0,1,0, 0,1,0, 0,1,0];
const seat = (triangles = plane(.45), n = normals): FixtureSeat => ({ objectId: 'bench', triangles, normals: n, heightHintM: .225, maximumHeightM: .46, facing: Math.PI / 2 });
describe('declared fixture contact', () => {
  it('uses the admitted original rounded seat after rotation/scale, with exactly the triangles rendered', async () => {
    const folder = '../assets/style-packs/kits/original.tide-garden';
    const raw = JSON.parse(readFileSync(`${folder}/manifest.json`,'utf8'));
    const catalog = readFileSync('../assets/catalogs/world-kinds/look-family.v2.json');
    const entries = JSON.parse(catalog.toString()).entries as {key:string;fit:LookFamily['fit'];dressing:LookFamily['dressing'];fill_minimum_permille:number;fill_maximum_permille:number}[];
    const families = new Map<string,LookFamily>(entries.map(e => [e.key,{fit:e.fit,dressing:e.dressing,fillMinimumPermille:e.fill_minimum_permille,fillMaximumPermille:e.fill_maximum_permille}]));
    const context = {families,textureSets:new Set(['cc0.float-glazing']),familyCatalogs:new Map([[2,{families,sha256:createHash('sha256').update(catalog).digest('hex')} ]])};
    const pack = resolveStylePack([readStylePackManifest(raw,context)]);
    const table = JSON.parse(readFileSync('../assets/colour/srgb8-linear16.v1.json','utf8')).values;
    const fetched = await fetchPackPieces(pack,['fixture.bench'],table,async file=>new Uint8Array(readFileSync(`${folder}/${file.path}`)));
    const canvas=document.createElement('canvas'), device=new pc.NullGraphicsDevice(canvas);
    const app=new pc.Application(canvas,{graphicsDevice:device}), root=new pc.Entity('site'); app.root.addChild(root);
    const pieces=uploadPackPieces(device,fetched);
    let captured = seatGeometry([],[]);
    const slots = [{identity:'bench',lookRole:'fixture.bench',positionMm:[5000,6000,0] as const,front:[1,0] as const,boxMm:[3000,750,450] as const}];
    const dressed=dressSlots(root,slots,pack,families,pieces,{model:'pbr',toon:null,ink:null},{identities:new Set(['bench']),maximumVertices:100000,triangles:(_id,p,n)=>{captured=seatGeometry(p,n);}});
    const contact=fixtureSeatDrawing({...seat(),...captured},[5100,-6600]);
    expect(contact).toMatchObject({kind:'place',drawing:{seat:{position:[5.1,expect.closeTo(.45,5),-6.6]}}});
    const rendered: number[]=[];
    for(const instance of (root.findByName('style-pack:pieces') as pc.Entity).render!.meshInstances){const p:number[]=[];instance.mesh.getPositions(p);rendered.push(...p);}
    expect([...captured.triangles].map(x=>Math.fround(x)).sort()).toEqual(rendered.sort());
    // Rounded corners have no contact, despite the canonical rectangular slot's envelope.
    expect(fixtureSeatDrawing({...seat(),...captured},[5374,-7499]).kind).toBe('miss');
    dressed.dispose();
    const bounded=dressSlots(root,slots,pack,families,pieces,{model:'pbr',toon:null,ink:null},{identities:new Set(['bench']),maximumVertices:1,triangles:(_id,p,n)=>{captured=seatGeometry(p,n);}});
    expect(fixtureSeatDrawing({...seat(),...captured},[5100,-6600]).kind).toBe('miss');
    expect(bounded.triangles).toBeGreaterThan(0);
    bounded.dispose(); pieces.dispose(); app.destroy();
  });
  it('keeps canonical object and recorded XY, taking visible top above hidden legs', () => {
    const geometry = seat([...plane(.38), ...plane(.45)], [...normals,...normals]);
    const result = placeDrawing({uses:new Map(),objects:[],targets:new Map([['rest-a','bench']]),fixtureSeats:[geometry]}, 'rest-a',[500,500]);
    expect(result).toMatchObject({kind:'place', drawing:{objectId:'bench',facing:Math.PI / 2,seat:{position:[.5,.45,.5]}}});
    expect(placeDrawing({uses:new Map(),objects:[],targets:new Map([['rest-b','other']]),fixtureSeats:[geometry]},'rest-b',[500,500])).toEqual({kind:'miss',reason:'object-not-drawn'});
  });
  it('refuses a hole, missing geometry, tall occluder and sloping occluder without hidden-seat fallback', () => {
    for (const [geometry,point] of [
      [seat(),[1800,1800]], [seat([],[]),[500,500]],
      [seat([...plane(.45),...plane(.9)],[...normals,...normals]),[500,500]],
      [seat([...plane(.4),0,.42,0,2,.5,0,0,.5,2],[...normals,0,.8,0,0,.8,0,0,.8,0]),[500,500]],
      [seat([...plane(.4),0,.42,0,2,1.2,0,0,1.2,2],[...normals,...normals]),[500,500]],
      [seat([...plane(.45),...plane(.45)],[...normals,...normals.map(n=>-n)]),[500,500]],
    ] as const) expect(fixtureSeatDrawing(geometry,point)).toEqual({kind:'miss',reason:'fixture-seat-contact-unavailable'});
  });
  it.each([0,1,2,3])('reads the actual primitive after quarter-turn %s and root rebasing', yaw => {
    const app = new pc.Application(document.createElement('canvas'),{graphicsDevice:new pc.NullGraphicsDevice(document.createElement('canvas'))});
    const drawing = parseStructuredSiteDrawing({profile:'exulanica.site-drawing/v1',world_id:'world-a',receipt_sha256:'a'.repeat(64),kind:{kind:'test_yard',version:1,label:'Yard'},extent:{widthMm:10000,depthMm:12000,enclosure:'open'},arrival:{positionMm:[4000,4000,0],facingMm:[0,1]},slots:[{identity:'bench',part:'bench',label:'Bench',lookRole:'fixture.bench',positionMm:[5000,6000,0],yawQuarterTurns:yaw,boxMm:[2000,500,450],front:'+y',fit:'contain',primitive:'box'}],walk:{floorMm:[0,0,10000,12000],blockersMm:[],keepOutMm:[]},seats:[{identity:'bench',seatHeightMm:225}]});
    const drawn=drawSiteSlots(app.graphicsDevice,drawing);
    app.root.addChild(drawn.root); drawn.root.setPosition(100,30,-200);
    expect(fixtureSeatDrawing(drawnSiteSeats(drawing,drawn)[0]!,[5000,-6000])).toMatchObject({kind:'place',drawing:{seat:{position:[5,expect.closeTo(.45,5),-6]}}});
    const shape = drawn.entities.get('bench')!;
    shape.enabled=false;
    expect(fixtureSeatDrawing(drawnSiteSeats(drawing,drawn)[0]!,[5000,-6000]).kind).toBe('miss');
    // A module's actual missing corner wins over the primitive hidden below it.
    expect(fixtureSeatDrawing(drawnSiteSeats(drawing,drawn,new Map([['bench',seatGeometry([],[])]]))[0]!,[5000,-6000]).kind).toBe('miss');
    drawn.destroy(); app.destroy();
  });
});
