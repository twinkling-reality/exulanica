// Adapt the authoritative backend read for the review UI. No local semantic enumeration.
/** What this adapter reads of the backend's world inventory (exulanica.world-inventory/v1); the read checks its own shape. */
interface InventoryReference { readonly source: string; readonly id: string; readonly role_key?: string | null }
interface RoleInstance { readonly role_key: string; readonly subject_id?: string }
interface SubjectDetail { readonly route: string; readonly bind?: { readonly version_id?: string; readonly ref?: unknown }; readonly query?: { readonly world_id?: string } }
interface InventoryEntity {
  readonly reference: InventoryReference; readonly aliases?: readonly InventoryReference[]; readonly category: string; readonly label?: string;
  readonly sources?: readonly unknown[]; readonly role_instances?: readonly RoleInstance[]; readonly availability?: string; readonly detail?: SubjectDetail;
}
interface InventoryRole { readonly key: string; readonly subject: string; readonly available?: boolean; readonly capability?: { readonly permitted?: boolean } }
interface Coverage { readonly source: string; readonly state: string; readonly code: string | null }
interface WorldInventory {
  readonly profile: string; readonly world_id: string; readonly version_id: string; readonly entities: readonly InventoryEntity[];
  readonly roles: readonly InventoryRole[]; readonly coverage: readonly Coverage[];
  readonly representations: readonly { readonly reference: InventoryReference; readonly source?: { readonly label?: string }; readonly availability?: string }[];
}
interface SceneSelection { readonly type: string; readonly id: string }
/** A site drawing's slots: drawing-only context. */
interface SiteSlots { readonly slots?: readonly { readonly identity: string; readonly label?: string; readonly lookRole?: string; readonly part?: string }[] }
export interface InventoryRow {
  readonly key: string; readonly id: string; readonly domain: string; readonly label: string; readonly category: string; readonly kind: string;
  readonly record: unknown; readonly sources?: readonly unknown[]; readonly reference?: InventoryReference; readonly aliases?: readonly InventoryReference[];
  readonly roleInstances: readonly RoleInstance[]; readonly availability?: string | undefined; readonly detail?: SubjectDetail | undefined;
  readonly source: string; readonly scene: SceneSelection | null; readonly roleKey?: string | null | undefined;
}
interface SubjectOffer {
  readonly profile?: string; readonly world_id?: string; readonly version_id?: string; readonly subject?: { readonly ref?: unknown };
  readonly actions?: readonly { readonly id: string; readonly permitted?: boolean; readonly state?: string; readonly runs_by?: { readonly bind?: { readonly role_key?: string; readonly subject_id?: string } } }[];
}
export function inventoryReferenceKey(reference: InventoryReference): string {return JSON.stringify([reference.source,reference.role_key??null,reference.id]);}
export function buildInventoryRows(inventory: WorldInventory | null | undefined, site: SiteSlots | null = null): InventoryRow[] {
  if(inventory?.profile!=='exulanica.world-inventory/v1'||!Array.isArray(inventory.entities)||!Array.isArray(inventory.roles)||!Array.isArray(inventory.coverage)||!Array.isArray(inventory.representations))throw Error('The world list is unavailable.');
  const rows: InventoryRow[]=[],seen=new Set<string>();
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
export function rowForSceneSelection(rows: readonly InventoryRow[], selection: SceneSelection | null): InventoryRow | null {return selection?rows.find(row=>row.scene?.type===selection.type&&row.scene?.id===selection.id)??null:null;}
export function inventoryRoleLinks(inventory: WorldInventory, row: InventoryRow) {return (row.roleInstances??[]).map(link=>({link,role:inventory.roles.find(role=>role.key===link.role_key)})).filter(x=>x.role);}
export function systemCoverage(inventory: WorldInventory | null | undefined) {
  const roles=(inventory?.roles??[]).filter(role=>role.subject!=='person');
  const states=roles.map(role=>inventory!.coverage.find(c=>c.source==='role.'+role.key+'.instances')??{source:'role.'+role.key+'.instances',state:'not_enumerated',code:null});
  return {readable:inventory!=null&&roles.length>0&&states.every(c=>c.state==='complete'),listed:(inventory?.entities??[]).filter(e=>e.category==='system').length,reasons:states.filter(c=>c.state!=='complete')};
}
export function inventoryDetailPath(inventory: WorldInventory, row: InventoryRow): string | null {const d=row.detail;if(!d)return null;if(d.route!=='GET /world/versions/{version_id}/subjects/{ref}'||d.bind?.version_id!==inventory.version_id||d.query?.world_id!==inventory.world_id||typeof d.bind?.ref!=='string')throw Error('Details are unavailable for this item.');return '/world/versions/'+encodeURIComponent(d.bind.version_id)+'/subjects/'+encodeURIComponent(d.bind.ref)+'?world_id='+encodeURIComponent(d.query.world_id);}
export function mayReviewAssignment(inventory: WorldInventory, row: InventoryRow, role: InventoryRole, offer: SubjectOffer | null | undefined): boolean {const link=(row.roleInstances??[]).find(x=>x.role_key===role.key);if(!link||!role.available||!role.capability?.permitted)return false;if(role.subject==='signal')return true;if(role.subject!=='person')return false;return offer?.profile==='exulanica.subject-offer/v1'&&offer.world_id===inventory.world_id&&offer.version_id===inventory.version_id&&offer.subject?.ref===row.detail?.bind?.ref&&(offer.actions??[]).some(a=>a.id==='minds.choose'&&a.permitted&&a.state==='available'&&a.runs_by?.bind?.role_key===role.key&&a.runs_by?.bind?.subject_id===link.subject_id);}
