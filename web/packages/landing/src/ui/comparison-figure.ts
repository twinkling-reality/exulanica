import { COMPARISON_FIGURE, COMPARISON_LANES, COMPARISON_STAGES } from '../content/comparison-figure.js';
import { el } from './dom.js';
import { recorderFaces, recorderOrder, recorderPath, type RecorderFace } from './comparison-geometry.js';
import { comparisonPose, createComparisonSequence } from './comparison-sequence.js';
import '../comparison-figure.css';

const NS='http://www.w3.org/2000/svg';
const svgNode = <K extends keyof SVGElementTagNameMap>(tag: K,attrs: Record<string,string>={}) => {
  const node=document.createElementNS(NS,tag);
  for(const [key,value] of Object.entries(attrs)) node.setAttribute(key,value);
  return node;
};

/** One state drives the SVG, phase, range, readout and playback. No API, inference or run data. */
export function buildComparisonFigure(host: HTMLElement): HTMLElement {
  const id='model-comparison-figure';
  const sequence=createComparisonSequence();
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
  const events=new AbortController(), {signal}=events;
  const svg=svgNode('svg',{viewBox:`0 0 ${COMPARISON_FIGURE.width} ${COMPARISON_FIGURE.height}`,class:'recorder-svg',role:'img',
    'aria-label':'A comparison recorder. One saved-world cartridge feeds four separate strips: models A and B, and a separate A/A control. Raised model heads disconnect during stored replay.'});
  const shadow=svgNode('ellipse',{cx:'320',cy:'342',rx:'218',ry:'52',class:'recorder-shadow'});
  const art=svgNode('g'); svg.append(shadow,art);
  const paths=new Map<string,SVGPathElement>();
  const readout=el('span',{class:'recorder-readout','aria-hidden':'true'});
  const description=el('p',{class:'recorder-description',id:`${id}-description`});
  const panel=el('div',{class:'recorder-detail',id:`${id}-detail`,role:'tabpanel',tabindex:'0'},[
    description,
    ...COMPARISON_STAGES.map(stage=>el('p',{class:'recorder-measure','aria-hidden':'true',inert:'',text:stage.detail})),
  ]);
  const buttons=COMPARISON_STAGES.map((stage,index)=>el('button',{id:`${id}-stage-${index}`,class:'recorder-stage',type:'button',role:'tab',
    'aria-controls':panel.id,'aria-selected':'false',tabindex:'-1',text:stage.title}));
  const tabs=el('div',{class:'recorder-stages',role:'tablist','aria-label':'Model comparison process'},buttons);
  const playback=el('button',{class:'recorder-play',type:'button',text:'Play Figure'});
  const range=el('input',{id:`${id}-sequence`,class:'recorder-range',type:'range',min:'0',max:'300',step:'1',value:'65',
    'aria-label':'Figure sequence','aria-describedby':`${id}-description`});
  const root=el('figure',{class:'comparison-figure','aria-labelledby':`${id}-title`},[
    el('div',{class:'recorder-card'},[
      el('div',{class:'recorder-heading'},[el('span',{text:'Figure 1'}),el('h2',{id:`${id}-title`,text:'Model Comparison'})]),
      el('div',{class:'recorder-stage-art'},[svg]),
      el('div',{class:'recorder-status'},[el('span',{text:'Explore the Process'}),readout]),
      tabs,panel,
      el('div',{class:'recorder-controls'},[playback,range]),
    ]),
    el('figcaption',{},[
      el('div',{class:'recorder-legend'},COMPARISON_LANES.map(lane=>el('span',{'data-model':lane.model},[
        el('i',{'aria-hidden':'true'}),`${lane.label} · ${lane.purpose}`]))),
      el('p',{text:'An illustrative recorder, not run data. Marks represent stored decisions, not their number or outcome. Routine and waiting baselines and repeated seeds are part of scoring.'}),
    ]),
  ]);
  let raf=0, wanted=true, running=false, intersecting=typeof IntersectionObserver==='undefined', background=false;
  let disposed=false, mounted=false, stage=-1, drawn=-1, cachedOrder='';
  const motionOff=()=>reduced.matches||document.documentElement.dataset.reducedMotion==='true';
  const available=()=>host.isConnected&&!host.inert&&!host.hidden&&intersecting&&!background&&document.visibilityState!=='hidden';
  const palettes: Record<string,string[]>={
    metal:['#c7cfcd','#d4dcda','#e2e8e5','#eef1ed'],dark:['#566361','#657471','#768783','#8d9a95'],
    source:['#93a8a0','#a4b6ad','#becbc0','#d2ddd0'],a:['#829ea6','#99b0b5','#b1c6c9','#d0dddd'],
    b:['#a58d9f','#b79eae','#cbb8c4','#e4d9df'],paper:['#d6dcd5','#e2e7df','#edf0e7','#fafbf4'],
    record:['#a6b1aa','#a6b1aa','#a6b1aa','#a6b1aa'],
  };
  const color=(face: RecorderFace)=> {
    const palette=palettes[face.material]!;
    const lower=Math.floor(face.shade),t=face.shade-lower;
    const a=palette[lower]!,b=palette[Math.min(3,lower+1)]!;
    const channels=[1,3,5].map(start=>Math.round(parseInt(a.slice(start,start+2),16)*(1-t)+parseInt(b.slice(start,start+2),16)*t));
    return `rgb(${channels.join(' ')})`;
  };
  function paint() {
    const pose=comparisonPose(sequence.position);
    root.dataset.position=String(pose.position);
    if(pose.position!==drawn) {
      const faces=recorderOrder(recorderFaces(pose.position));
      const visible=new Set(faces.map(face=>face.id));
      for(const [id,path] of paths) if(!visible.has(id)) path.style.display='none';
      for(const face of faces) {
        let path=paths.get(face.id);
        const retained=!!path;
        if(!path) {path=svgNode('path',{'data-face':face.id});paths.set(face.id,path);art.append(path);}
        if(retained&&!face.dynamic) continue;
        path.style.display='';path.setAttribute('d',recorderPath(face.points));
        path.setAttribute('fill',color(face));path.setAttribute('opacity',String(face.opacity??1));
        path.setAttribute('class',face.material==='record'?'recorder-record':'recorder-face');
      }
      const order=faces.map(face=>face.id).join(':');
      if(order!==cachedOrder) { const fragment=document.createDocumentFragment();for(const face of faces) fragment.append(paths.get(face.id)!);art.append(fragment);cachedOrder=order; }
      drawn=pose.position;
    }
    if(stage!==pose.stage) {
      stage=pose.stage;
      buttons.forEach((button,index)=> {button.setAttribute('aria-selected',String(index===stage));button.tabIndex=index===stage?0:-1;});
      panel.setAttribute('aria-labelledby',buttons[stage]!.id);
      description.textContent=COMPARISON_STAGES[stage]!.detail;
      readout.textContent=pose.readout;
      range.setAttribute('aria-valuetext',COMPARISON_STAGES[stage]!.title);
    }
    range.value=String(Math.round(pose.position*100));
    // Announce user navigation, never every frame of automatic motion.
  }
  function playbackState() {
    root.dataset.playback=running?'playing':'paused';
    playback.textContent=wanted&&!motionOff()&&sequence.position<3?'Pause Figure':'Play Figure';
    playback.disabled=motionOff();
    playback.setAttribute('aria-label',motionOff()?'Automatic playback disabled for reduced motion':playback.textContent);
  }
  function tick(now: number) {
    raf=0;
    if(!available()||motionOff()||!wanted) {sync();return;}
    sequence.advance(now);paint();
    if(sequence.position>=3) {wanted=false;sync();} else raf=requestAnimationFrame(tick);
  }
  function sync() {
    if(disposed) return;
    const next=available()&&wanted&&!motionOff()&&sequence.position<3;
    if(next!==running) { sequence.suspend();running=next; }
    if(!next&&raf) {cancelAnimationFrame(raf);raf=0;}
    if(next&&!raf) raf=requestAnimationFrame(tick);
    playbackState();
  }
  function seek(position: number) {
    wanted=false;sequence.seek(position);paint();
    range.setAttribute('aria-valuetext',COMPARISON_STAGES[comparisonPose(position).stage]!.title);
    sync();
  }
  buttons.forEach((button,index)=> {
    button.addEventListener('click',()=>seek(index+.65),{signal});
    button.addEventListener('keydown',event=> {
      const next=event.key==='ArrowRight'? (index+1)%buttons.length:event.key==='ArrowLeft'?(index+buttons.length-1)%buttons.length:event.key==='Home'?0:event.key==='End'?buttons.length-1:null;
      if(next===null) return;
      event.preventDefault();buttons[next]!.focus();seek(next+.65);
    },{signal});
  });
  range.addEventListener('input',()=>seek(Number(range.value)/100),{signal});
  playback.addEventListener('click',()=> {
    if(motionOff()) return;
    wanted=!wanted;
    if(wanted&&sequence.position>=3) sequence.seek(0);
    paint();sync();
  },{signal});
  root.addEventListener('focusin',event=> {if(event.target!==playback) {wanted=false;sync();}},{signal});
  root.addEventListener('pointerenter',event=> {if(event.pointerType==='mouse') {wanted=false;sync();}},{signal});
  document.addEventListener('visibilitychange',sync,{signal});
  window.addEventListener('blur',()=>{background=true;sync();},{signal});
  window.addEventListener('focus',()=>{background=false;sync();},{signal});
  window.addEventListener('pagehide',()=>{background=true;sync();},{signal});
  window.addEventListener('pageshow',()=>{background=false;sync();},{signal});
  reduced.addEventListener('change',()=>{sequence.suspend();sync();},{signal});
  const intersection=typeof IntersectionObserver==='undefined'?null:new IntersectionObserver(entries=> {
    intersecting=entries[entries.length-1]?.isIntersecting??false;sync();
  },{threshold:.15});
  intersection?.observe(root);
  const hostObserver=new MutationObserver(sync);hostObserver.observe(host,{attributes:true,attributeFilter:['inert','hidden']});
  const preferenceObserver=new MutationObserver(sync);preferenceObserver.observe(document.documentElement,{attributes:true,attributeFilter:['data-reduced-motion']});
  const connectionObserver=new MutationObserver(()=> {
    if(host.isConnected) {if(!mounted) {mounted=true;sync();}}
    else if(mounted) {
      disposed=true;cancelAnimationFrame(raf);events.abort();intersection?.disconnect();hostObserver.disconnect();preferenceObserver.disconnect();connectionObserver.disconnect();
    }
  });
  connectionObserver.observe(document.body,{childList:true,subtree:true});
  range.setAttribute('aria-valuetext',COMPARISON_STAGES[0].title);
  paint();queueMicrotask(sync);
  return root;
}
