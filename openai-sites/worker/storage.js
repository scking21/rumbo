/** D1 owns authorization, CAS and storage quotas; R2 owns immutable artifact bytes. */
import {Engine,fail,identifier,validateContract,MAX_LEDGER_BYTES,MAX_EVENTS,MAX_INGEST} from './engine.js';
import {canonical,sha256} from './codec.js';
const ZERO='0'.repeat(64),MAX_UPLOAD_TOTAL=64*1024*1024,DELETE_GUARD_PAGE=64;
export const subjectActor=async subject=>'u'+(await sha256(subject)).slice(0,63);
const randomId=()=>crypto.randomUUID().replaceAll('-','');
// Authorization belongs in the statement that takes effect, as well as at the
// API boundary: a previously returned Engine/IO object is not an access grant.
function accessCondition(subject,key,mode,workerId){
 const role=mode==='human'?"p.owner_subject=?":mode==='reviewer'?"p.owner_subject!=? AND m.role='reviewer'":mode==='worker'?"(p.owner_subject=? OR m.role='worker')":"(p.owner_subject=? OR m.role IN ('worker','reviewer','viewer'))";
 const worker=workerId?' AND EXISTS (SELECT 1 FROM workers w WHERE w.id=? AND w.project_key=p.key AND w.subject=? AND w.expires_at>unixepoch())':'';
 return {sql:`EXISTS (SELECT 1 FROM projects p LEFT JOIN memberships m ON m.project_key=p.key AND m.subject=? WHERE p.key=? AND p.lifecycle='active' AND ${role}${worker})`,args:[subject,key,subject,...(workerId?[workerId,subject]:[])]};
}
export class Storage {
 constructor(env){if(!env.DB||!env.ARTIFACTS)fail('STORAGE_UNAVAILABLE','Persistent storage is not configured');this.env=env;this.db=env.DB;this.bucket=env.ARTIFACTS;}
 async projectKey(subject,reference){return /^[a-f0-9]{64}$/.test(reference)?reference:sha256(subject+'\0'+identifier(reference,'project reference'));}
 async authorize(subject,reference){
  const key=await this.projectKey(subject,reference);
  const project=await this.db.prepare('SELECT p.*, m.role AS member_role FROM projects p LEFT JOIN memberships m ON m.project_key=p.key AND m.subject=? WHERE p.key=?').bind(subject,key).first();
  if(!project||(project.owner_subject!==subject&&!['worker','reviewer','viewer'].includes(project.member_role)))fail('FORBIDDEN','Project is not authorized for this signed-in user');
  if(project.lifecycle!=='active')fail('PROJECT_DELETING','Project deletion is pending; its owner can continue cleanup');
  return {...project,role:project.owner_subject===subject?'owner':project.member_role};
 }
 async owner(subject,reference){const p=await this.authorize(subject,reference);if(p.role!=='owner')fail('FORBIDDEN','The project owner must use the owner browser');return p;}
 async listProjects(subject){return (await this.db.prepare("SELECT p.key AS project_key,p.alias,p.owner_actor,p.lifecycle,CASE WHEN p.owner_subject=? THEN 'owner' ELSE m.role END AS role FROM projects p LEFT JOIN memberships m ON m.project_key=p.key AND m.subject=? WHERE p.owner_subject=? OR (m.subject=? AND p.lifecycle='active') ORDER BY p.created_at,p.key").bind(subject,subject,subject,subject).all()).results;}
 async createProject(subject,alias,contract){
  identifier(alias,'project_id');const actor=await subjectActor(subject);validateContract(contract,actor);if(contract.project_id!==alias)fail('BAD_INPUT','Project alias must match the contract');const key=await sha256(subject+'\0'+alias),now=Math.floor(Date.now()/1000);
  if(await this.db.prepare('SELECT key FROM deleted_projects WHERE key=?').bind(key).first())fail('PROJECT_DELETED','This owner’s deleted project alias cannot be reused; choose a new alias');
  if(await this.db.prepare('SELECT key FROM projects WHERE key=?').bind(key).first())fail('CONTRACT_EXISTS');
  const payload=canonical({action:'create_contract',data:{...contract,contract_revision:1,contract_change_reason:'Initial owner-approved contract'},actor,role:'human',at:now}),digest=await sha256(ZERO+'\n'+payload);
  let result;
  try{result=await this.db.batch([
   this.db.prepare('INSERT INTO projects (key,alias,owner_subject,owner_actor,head_seq,head_digest,event_bytes,created_at) SELECT ?,?,?,?,1,?,?,? WHERE NOT EXISTS (SELECT 1 FROM deleted_projects WHERE key=?)').bind(key,alias,subject,actor,digest,payload.length,now,key),
   this.db.prepare("INSERT INTO events (project_key,seq,payload,previous,digest) SELECT ?,1,?,?,? WHERE EXISTS (SELECT 1 FROM projects WHERE key=? AND lifecycle='active') AND NOT EXISTS (SELECT 1 FROM deleted_projects WHERE key=?)").bind(key,payload,ZERO,digest,key,key)
  ]);}catch(e){if(await this.db.prepare('SELECT key FROM deleted_projects WHERE key=?').bind(key).first())fail('PROJECT_DELETED','This owner’s deleted project alias cannot be reused; choose a new alias');if(await this.db.prepare('SELECT key FROM projects WHERE key=?').bind(key).first())fail('CONTRACT_EXISTS');throw e;}
  if(result[0].meta.changes!==1||result[1].meta.changes!==1)fail('PROJECT_DELETED','This owner’s deleted project alias cannot be reused; choose a new alias');
  return {project_key:key,alias,owner_actor:actor};
 }
 async deleteProject(subject,reference,confirmation){
  const key=await this.projectKey(subject,reference),pending={project_key:key,status:'deleting',retry:true},deleted={project_key:key,status:'deleted'};
  const project=await this.db.prepare('SELECT alias,owner_subject FROM projects WHERE key=?').bind(key).first();
  // The completed guard retains no owner ID. The host-authenticated subject and
  // exact alias reproduce the key and authorize an idempotent completion reply.
  if(project&&project.owner_subject!==subject)fail('FORBIDDEN','Only the project owner can delete this project');
  if(!project){
   if(typeof confirmation!=='string'||await sha256(subject+'\0'+confirmation)!==key)fail('FORBIDDEN','Project is not authorized for this signed-in user');
   if(await this.db.prepare('SELECT key FROM deleted_projects WHERE key=?').bind(key).first())return deleted;
   fail('FORBIDDEN','Project is not authorized for this signed-in user');
  }
  if(confirmation!==project.alias||await sha256(subject+'\0'+confirmation)!==key)fail('CONFIRMATION_REQUIRED','Type the exact project alias to confirm permanent deletion');
  // This statement linearizes deletion against every write/reservation. No
  // R2 key can appear unless its reservation precedes this fence.
  await this.db.prepare("UPDATE projects SET lifecycle='deleting' WHERE key=? AND owner_subject=? AND alias=?").bind(key,subject,confirmation).run();
  try{
   const page=(await this.db.prepare('SELECT digest FROM artifacts WHERE project_key=? AND guard_written=0 ORDER BY digest LIMIT ?').bind(key,DELETE_GUARD_PAGE).all()).results;
   for(const {digest} of page){
    // Never delete this zero-byte object: a paused conditional upload must find
    // the key occupied forever. The project/digest key itself is retained data.
    await this.bucket.put(key+'/'+digest,new Uint8Array(),{httpMetadata:{contentType:'application/octet-stream'}});
    const guard=await this.bucket.get(key+'/'+digest);if(!guard||(await guard.arrayBuffer()).byteLength!==0)return pending;
    await this.db.prepare("UPDATE artifacts SET guard_written=1 WHERE project_key=? AND digest=? AND EXISTS (SELECT 1 FROM projects WHERE key=? AND lifecycle='deleting')").bind(key,digest,key).run();
   }
   if(await this.db.prepare('SELECT digest FROM artifacts WHERE project_key=? AND guard_written=0 LIMIT 1').bind(key).first())return pending;
   // A failed batch rolls back every deletion and preserves owner authorization
   // and the manifest. The permanent key guard and cleanup commit together.
   const ready="EXISTS (SELECT 1 FROM projects WHERE key=? AND lifecycle='deleting') AND NOT EXISTS (SELECT 1 FROM artifacts WHERE project_key=? AND guard_written=0)";
   await this.db.batch([
    this.db.prepare(`INSERT OR IGNORE INTO deleted_projects (key) SELECT ? WHERE ${ready}`).bind(key,key,key),
    ...['events','memberships','workers','artifacts'].map(table=>this.db.prepare(`DELETE FROM ${table} WHERE project_key=? AND EXISTS (SELECT 1 FROM deleted_projects WHERE key=?)`).bind(key,key)),
    this.db.prepare("DELETE FROM projects WHERE key=? AND lifecycle='deleting' AND EXISTS (SELECT 1 FROM deleted_projects WHERE key=?)").bind(key,key)
   ]);
   return await this.db.prepare('SELECT key FROM deleted_projects WHERE key=?').bind(key).first()?deleted:pending;
  }catch{return pending;}
 }
 async projectIO(subject,reference,mode='viewer',workerId){
  const p=await this.authorize(subject,reference),db=this.db,bucket=this.bucket,key=p.key,storage=this,access=accessCondition(subject,key,mode,workerId);
  const check=async()=>{
   const current=await storage.authorize(subject,key);
   if(mode==='human'&&current.role!=='owner'||mode==='reviewer'&&current.role!=='reviewer'||mode==='worker'&&!['owner','worker'].includes(current.role))fail('FORBIDDEN');
   if(workerId&&!await db.prepare('SELECT id FROM workers WHERE id=? AND project_key=? AND subject=? AND expires_at>unixepoch()').bind(workerId,key,subject).first())fail('FORBIDDEN','Worker session is no longer authorized');
  };
  await check();
  return {
   store:{
    async read(){await check();const rows=(await db.prepare(`SELECT seq,payload,previous,digest FROM events WHERE project_key=? AND ${access.sql} ORDER BY seq`).bind(key,...access.args).all()).results;await check();return rows;},
    async append(expected,event){
     await check();
     // D1 batches are transactions. Authorization linearizes at insertion.
     // The head update relies on that exact inserted event; rechecking wall
     // time there could let expiry commit an event without advancing its head.
     const result=await db.batch([
      db.prepare(`INSERT INTO events (project_key,seq,payload,previous,digest) SELECT ?,?,?,?,? WHERE EXISTS (SELECT 1 FROM projects WHERE key=? AND lifecycle='active' AND head_seq=? AND head_digest=? AND head_seq<? AND event_bytes+?<=?) AND ${access.sql}`).bind(key,event.seq,event.payload,event.previous,event.digest,key,expected.count,expected.head,MAX_EVENTS,event.payload.length,MAX_LEDGER_BYTES,...access.args),
      db.prepare(`UPDATE projects SET head_seq=?,head_digest=?,event_bytes=event_bytes+? WHERE key=? AND lifecycle='active' AND head_seq=? AND head_digest=? AND EXISTS (SELECT 1 FROM events WHERE project_key=? AND seq=? AND digest=?)`).bind(event.seq,event.digest,event.payload.length,key,expected.count,expected.head,key,event.seq,event.digest)
     ]);await check();return result[0].meta.changes===1&&result[1].meta.changes===1;
    }
   },
   artifacts:{
    async get(digest){
     await check();if(!/^[a-f0-9]{64}$/.test(digest))fail('ARTIFACT_CORRUPT');const meta=await db.prepare(`SELECT size FROM artifacts WHERE project_key=? AND digest=? AND ${access.sql}`).bind(key,digest,...access.args).first();await check();if(!meta)fail('PATH_UNSAFE','Uploaded artifact is missing');
     const object=await bucket.get(key+'/'+digest);if(!object){await check();fail('PATH_UNSAFE','Uploaded artifact is missing');}const bytes=new Uint8Array(await object.arrayBuffer());await check();if(bytes.length!==meta.size||bytes.length>MAX_INGEST)fail('ARTIFACT_CORRUPT');return bytes;
    },
    async put(digest,bytes){
     await check();if(bytes.length>MAX_INGEST||await sha256(bytes)!==digest)fail('ARTIFACT_CORRUPT');
     // Every possible upload key is atomically reserved while active. Failed
     // uploads retain bounded reservations so deletion can guard them as well.
     await db.prepare(`INSERT OR IGNORE INTO artifacts (project_key,digest,size) SELECT ?,?,? WHERE ${access.sql} AND COALESCE((SELECT sum(size) FROM artifacts WHERE project_key=?),0)+?<=?`).bind(key,digest,bytes.length,...access.args,key,bytes.length,MAX_UPLOAD_TOTAL).run();
     await check();const meta=await db.prepare('SELECT size FROM artifacts WHERE project_key=? AND digest=?').bind(key,digest).first();await check();if(!meta)fail('STORAGE_LIMIT','Uploaded artifacts are limited to 64 MiB per project; ask its owner to manage retention');if(meta.size!==bytes.length)fail('ARTIFACT_CORRUPT');
     const existing=await bucket.get(key+'/'+digest);await check();if(existing){const old=new Uint8Array(await existing.arrayBuffer());await check();if(old.length!==bytes.length||await sha256(old)!==digest)fail('ARTIFACT_CORRUPT','Existing uploaded digest does not match bytes');return;}
     await bucket.put(key+'/'+digest,bytes,{onlyIf:{etagDoesNotMatch:'*'},httpMetadata:{contentType:'application/octet-stream'}});await check();
     const saved=await bucket.get(key+'/'+digest);const savedBytes=saved?new Uint8Array(await saved.arrayBuffer()):null;await check();if(!savedBytes||await sha256(savedBytes)!==digest)fail('ARTIFACT_CORRUPT','Upload verification failed');
    }
   }
  };
 }
 async engine(subject,reference,mode='viewer'){
  const p=mode==='human'?await this.owner(subject,reference):await this.authorize(subject,reference);
  if(mode!=='human'&&mode!=='viewer')fail('FORBIDDEN');return new Engine({...await this.projectIO(subject,p.key,mode),actor:await subjectActor(subject),role:mode});
 }
 async openWorker(subject,reference,label){
  const p=await this.authorize(subject,reference);if(!['owner','worker'].includes(p.role))fail('FORBIDDEN','A worker membership is required');
  if(typeof label!=='string'||!label.trim()||label.length>80)fail('BAD_INPUT','Worker label is required (max 80)');
  const now=Math.floor(Date.now()/1000),id=randomId(),actor='w'+id;
  const result=await this.db.prepare("INSERT INTO workers (id,project_key,subject,actor,label,expires_at) SELECT ?,?,?,?,?,? WHERE (SELECT count(*) FROM workers WHERE project_key=? AND subject=? AND expires_at>?)<100 AND EXISTS (SELECT 1 FROM projects p LEFT JOIN memberships m ON m.project_key=p.key AND m.subject=? WHERE p.key=? AND p.lifecycle='active' AND (p.owner_subject=? OR m.role='worker'))").bind(id,p.key,subject,actor,label,now+86400,p.key,subject,now,subject,p.key,subject).run();
  if(!result.meta.changes){const current=await this.authorize(subject,p.key);if(!['owner','worker'].includes(current.role))fail('FORBIDDEN');fail('WORKER_LIMIT','At most 100 active worker sessions per project and user');}return {project_key:p.key,worker_id:id,actor,label,expires_at:now+86400,notice:'Coordination identity bound to your signed-in account. This does not prove independent people or organizations.'};
 }
 async workerEngine(subject,reference,workerId){
  const p=await this.authorize(subject,reference);if(!['owner','worker'].includes(p.role))fail('FORBIDDEN');
  const worker=await this.db.prepare('SELECT actor FROM workers WHERE id=? AND project_key=? AND subject=? AND expires_at>?').bind(workerId,p.key,subject,Math.floor(Date.now()/1000)).first();
  if(!worker)fail('FORBIDDEN','Open a worker session for this project and authenticated account');
  return new Engine({...await this.projectIO(subject,p.key,'worker',workerId),actor:worker.actor,role:'worker'});
 }
 async reviewerEngine(subject,reference){const p=await this.authorize(subject,reference);if(p.role!=='reviewer')fail('FORBIDDEN','A separately authorized reviewer account is required');return new Engine({...await this.projectIO(subject,p.key,'reviewer'),actor:await subjectActor(subject),role:'reviewer'});}
 async setMember(subject,reference,memberSubject,role){
  const p=await this.owner(subject,reference);if(typeof memberSubject!=='string'||!memberSubject.trim()||memberSubject.length>512||memberSubject===subject)fail('BAD_INPUT','Use a distinct verified Site user ID');if(!['worker','reviewer','viewer'].includes(role))fail('BAD_INPUT','Invalid member role');
  // Historical makers remain distinct even after role changes.
  if(role==='reviewer'&&await this.db.prepare('SELECT id FROM workers WHERE project_key=? AND subject=? LIMIT 1').bind(p.key,memberSubject).first())fail('FORBIDDEN','A worker account cannot become this project’s reviewer');
  const active="EXISTS (SELECT 1 FROM projects WHERE key=? AND owner_subject=? AND lifecycle='active')";
  const result=await this.db.prepare(`INSERT INTO memberships (project_key,subject,role) SELECT ?,?,? WHERE ${active} AND (?!='reviewer' OR NOT EXISTS (SELECT 1 FROM workers WHERE project_key=? AND subject=?)) ON CONFLICT(project_key,subject) DO UPDATE SET role=excluded.role WHERE ${active} AND (excluded.role!='reviewer' OR NOT EXISTS (SELECT 1 FROM workers WHERE project_key=? AND subject=?))`).bind(p.key,memberSubject,role,p.key,subject,role,p.key,memberSubject,p.key,subject,p.key,memberSubject).run();if(!result.meta.changes){await this.owner(subject,p.key);fail('FORBIDDEN','A worker account cannot become this project’s reviewer');}return {project_key:p.key,subject:memberSubject,role};
 }
}
