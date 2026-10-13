import { el } from './dom.js';
import { USE_CASES, type UseCase } from '../content/use-cases.js';
import { withSectionAtmosphere } from './ambient-field.js';
import { buildComparisonFigure } from './comparison-figure.js';
import { USE_CASE_ORBS } from '../content/use-case-orbs.js';
import { mountUseCaseOrbs, type OrbChoice } from './use-case-orbs.js';
import '../site-pages.css';
import '../feature-pages.css';
import '../use-cases.css';

export function buildUseCases(): HTMLElement {
  const host = el('section', {id:'use-cases',class:'pane site-pane feature-pane use-cases-pane',tabindex:'-1','aria-labelledby':'use-cases-title'});
  const choices: OrbChoice[] = [];
  const directory = el('nav', {class:'use-case-directory','aria-label':'Use case journeys'}, USE_CASES.map(item => {
    const recipe = USE_CASE_ORBS[item.key];
    const orb = el('span', {class:'use-case-orb','aria-hidden':'true'});
    recipe.fallback.forEach((color,index) => orb.style.setProperty(`--orb-color-${index}`,color));
    const titleId = `use-case-link-${item.key}`;
    const link = el('a', {class:'use-case-destination',href:`/use-cases/${item.key}`,'aria-labelledby':titleId}, [
      orb,
      el('span',{class:'use-case-audience',text:item.audience}),
      el('div',{class:'use-case-link-heading'},[el('h2',{id:titleId,text:item.title}),el('span',{'aria-hidden':'true',text:'↗'})]),
      el('p',{text:item.summary}),
    ]);
    choices.push({ link, orb, recipe });
    return link;
  }));
  host.append(
    el('article',{class:'site-page use-case-index'},[
      el('header',{class:'use-case-index-heading'},[
        el('h1',{id:'use-cases-title',text:'Use Cases'}),
        el('p',{class:'use-case-introduction',text:'A saved world is a starting point for experiments, creation, and outside agents.'}),
      ]),
      directory,
      el('div',{class:'use-case-index-context'},[el('a',{class:'use-case-context',href:'/product/capabilities',text:'Product Capabilities ↗'})]),
    ]),
  );
  mountUseCaseOrbs(host,directory,choices);
  return withSectionAtmosphere(host,'use-cases');
}

function guideLinks(item: UseCase): HTMLElement {
  return el('nav',{class:'use-case-guides','aria-label':`${item.title} documentation`},[
    el('a',{class:'use-case-guide',href:item.href,text:`${item.action} ↗`}),
    ...item.guides.map(guide=>el('a',{class:'use-case-related-guide',href:guide.href,text:`${guide.title} ↗`})),
  ]);
}

export function buildUseCase(item: UseCase): HTMLElement {
  const id=`use-case-${item.key}`;
  const host=el('section',{id,class:`pane site-pane feature-pane use-case-pane use-case-${item.key}-pane`,tabindex:'-1','aria-labelledby':`${id}-title`});
  const copy=el('div',{class:'use-case-content'},[
    el('a',{class:'use-case-back',href:'/use-cases',text:'← Use Cases'}),
    el('header',{},[
      el('h1',{id:`${id}-title`,text:item.title}),
      el('p',{class:'use-case-audience',text:item.audience}),
      el('p',{class:'use-case-introduction',text:item.introduction}),
    ]),
    el('section',{class:'use-case-workflow','aria-labelledby':`${id}-workflow`},[
      el('h2',{id:`${id}-workflow`,text:item.workflowTitle}),
      el('ol',{},item.steps.map(step=>el('li',{},[el('h3',{text:step.title}),el('p',{text:step.copy})]))),
    ]),
    guideLinks(item),
    el('section',{class:'use-case-scope','aria-labelledby':`${id}-scope`},[
      el('h2',{id:`${id}-scope`,text:'Availability and Scope'}),
      el('p',{text:item.availability}),
      ...(item.planned?[el('p',{class:'use-case-planned',text:item.planned})]:[]),
    ]),
  ]);
  const visual=item.key==='model-comparison'?buildComparisonFigure(host):item.image?el('figure',{class:'use-case-world-capture'},[
    el('img',{src:item.image,alt:item.alt,width:'1280',height:'860',loading:'lazy'}),
    el('figcaption',{text:item.caption}),
  ]):el('aside',{class:'use-case-integration','aria-labelledby':`${id}-paths`},[
    el('h2',{id:`${id}-paths`,text:'Integration Paths'}),
    el('p',{text:'One turn interface, two ways to connect.'}),
    ...item.guides.map(guide=>el('a',{href:guide.href},[
      el('h3',{text:`${guide.title} ↗`}),
      el('p',{text:guide.title==='Python'?'Connect your own model call.':'Use an existing agent client.'}),
    ])),
    el('p',{class:'use-case-integration-note',text:'Decisions remain recorded for replay after the agent disconnects.'}),
  ]);
  host.append(el('article',{class:'site-page use-case-sheet'},[copy,visual]));
  return withSectionAtmosphere(host,'use-cases');
}
