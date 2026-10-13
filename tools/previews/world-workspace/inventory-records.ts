// Adapt the authoritative backend read for the review UI. No local semantic enumeration.
export function inventoryReferenceKey(reference){return JSON.stringify([reference.source,reference.role_key??null,reference.id]);}
export function buildInventoryRows(inventory,site=null){
  if(inventory?.profile!=='exulanica.world-inventory/v1'||!Array.isArray(inventory.entities)||!Array.isArray(inventory.roles)||!Array.isArray(inventory.coverage)||!Array.isArray(inventory.representations))throw Error('The world list is unavailable.');
  const rows=[],seen=new Set();
  for(const entity of inventory.entities){
    const ref=entity.reference;if(!ref?.source||!ref.id)throw Error('The world list is unavailable.');
    const key=inventoryReferenceKey(ref);if(seen.has(key))throw Error('The world list is unavailable.');seen.add(key);
    const references=[ref,...(entity.aliases??[])];
    const being=entity.category==='being'?references.find(x=>x.source==='society-being'):null;
    const object=ref.source==='authored-object'?ref:null;
    const label=entity.label??ref.id;
    const kind=entity.category==='being'?'being':entity.category==='system'?'system':object?'object':entity.category==='environment'?'environment':'thing';
    rows.push({key,id:ref.id,domain:ref.source,label,category:kind==='system'?'systems':'entities',kind,record:entity,sources:entity.sources??[],reference:ref,aliases:entity.aliases??[],roleInstances:entity.role_instances??[],availability:entity.availability,detail:entity.detail,source:'Backend world inventory',scene:being?{type:'being',id:being.id}:object?{type:'object',id:object.id}:null,roleKey:ref.role_key});
  }
  for(const representation of inventory.representations){const ref=representation.reference;if(!ref?.source||!ref.id)throw Error('The scenery list is unavailable.');rows.push({key:'representation:'+inventoryReferenceKey(ref),id:ref.id,domain:ref.source,label:representation.source?.label??ref.id,category:'representations',kind:'representation',record:representation.source,reference:ref,source:'Backend drawing representation',availability:representation.availability,roleInstances:[],scene:null});}
  // Existing site slots provide drawing-only context, never semantic entities or role membership.
  for(const slot of site?.slots??[])if(slot.identity)rows.push({key:JSON.stringify(['site-drawing',slot.identity]),id:slot.identity,domain:'site-drawing',label:slot.label||slot.lookRole||slot.part||'Scenery',category:'representations',kind:'representation',record:slot,source:'Existing site drawing slot',roleInstances:[],scene:null});
  return rows;
}
export function rowForSceneSelection(rows,selection){return selection?rows.find(row=>row.scene?.type===selection.type&&row.scene?.id===selection.id)??null:null;}
export function inventoryRoleLinks(inventory,row){return (row.roleInstances??[]).map(link=>({link,role:inventory.roles.find(role=>role.key===link.role_key)})).filter(x=>x.role);}
export function systemCoverage(inventory){
  const roles=(inventory?.roles??[]).filter(role=>role.subject!=='person');
  const states=roles.map(role=>inventory.coverage.find(c=>c.source==='role.'+role.key+'.instances')??{source:'role.'+role.key+'.instances',state:'not_enumerated',code:null});
  return {readable:inventory!=null&&roles.length>0&&states.every(c=>c.state==='complete'),listed:(inventory?.entities??[]).filter(e=>e.category==='system').length,reasons:states.filter(c=>c.state!=='complete')};
}
export function inventoryDetailPath(inventory,row){const d=row.detail;if(!d)return null;if(d.route!=='GET /world/versions/{version_id}/subjects/{ref}'||d.bind?.version_id!==inventory.version_id||d.query?.world_id!==inventory.world_id||typeof d.bind?.ref!=='string')throw Error('Details are unavailable for this item.');return '/world/versions/'+encodeURIComponent(d.bind.version_id)+'/subjects/'+encodeURIComponent(d.bind.ref)+'?world_id='+encodeURIComponent(d.query.world_id);}
export function mayReviewAssignment(inventory,row,role,offer){const link=(row.roleInstances??[]).find(x=>x.role_key===role.key);if(!link||!role.available||!role.capability?.permitted)return false;if(role.subject==='signal')return true;if(role.subject!=='person')return false;return offer?.profile==='exulanica.subject-offer/v1'&&offer.world_id===inventory.world_id&&offer.version_id===inventory.version_id&&offer.subject?.ref===row.detail?.bind?.ref&&(offer.actions??[]).some(a=>a.id==='minds.choose'&&a.permitted&&a.state==='available'&&a.runs_by?.bind?.role_key===role.key&&a.runs_by?.bind?.subject_id===link.subject_id);}
