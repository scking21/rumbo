/** D1 owns authorization, CAS and storage quotas; R2 owns immutable artifact bytes. */
import {Engine,fail,identifier,validateContract,MAX_LEDGER_BYTES,MAX_EVENTS,MAX_INGEST} from './engine.js';
import {canonical,sha256} from './codec.js';
const ZERO='0'.repeat(64),MAX_UPLOAD_TOTAL=64*1024*1024;
export const subjectActor=async subject=>'u'+(await sha256(subject)).slice(0,63);
const randomId=()=>crypto.randomUUID().replaceAll('-','');
export class Storage {
 constructor(env){if(!env.DB||!env.ARTIFACTS)fail('STORAGE_UNAVAILABLE','Persistent storage is not configured');this.env=env;this.db=env.DB;this.bucket=env.ARTIFACTS;}
 async projectKey(subject,reference){return /^[a-f0-9]{64}$/.test(reference)?reference:sha256(subject+'\0'+identifier(reference,'project reference'));}
 async authorize(subject,reference){
  const key=await this.projectKey(subject,reference);
  const project=await this.db.prepare('SELECT p.*, m.role AS member_role FROM projects p LEFT JOIN memberships m ON m.project_key=p.key AND m.subject=? WHERE p.key=?').bind(subject,key).first();
  if(!project||(project.owner_subject!==subject&&!['worker','reviewer','viewer'].includes(project.member_role)))fail('FORBIDDEN','Project is not authorized for this signed-in user');
  return {...project,role:project.owner_subject===subject?'owner':project.member_role};
 }
 async owner(subject,reference){const p=await this.authorize(subject,reference);if(p.role!=='owner')fail('FORBIDDEN','The project owner must use the owner browser');return p;}
 async listProjects(subject){return (await this.db.prepare("SELECT p.key AS project_key,p.alias,p.owner_actor,CASE WHEN p.owner_subject=? THEN 'owner' ELSE m.role END AS role FROM projects p LEFT JOIN memberships m ON m.project_key=p.key AND m.subject=? WHERE p.owner_subject=? OR m.subject=? ORDER BY p.created_at,p.key").bind(subject,subject,subject,subject).all()).results;}
 async createProject(subject,alias,contract){
  identifier(alias,'project_id');const actor=await subjectActor(subject);validateContract(contract,actor);if(contract.project_id!==alias)fail('BAD_INPUT','Project alias must match the contract');const key=await sha256(subject+'\0'+alias),now=Math.floor(Date.now()/1000);
  if(await this.db.prepare('SELECT key FROM projects WHERE key=?').bind(key).first())fail('CONTRACT_EXISTS');
  const payload=canonical({action:'create_contract',data:{...contract,contract_revision:1,contract_change_reason:'Initial owner-approved contract'},actor,role:'human',at:now}),digest=await sha256(ZERO+'\n'+payload);
  try{await this.db.batch([
   this.db.prepare('INSERT INTO projects (key,alias,owner_subject,owner_actor,head_seq,head_digest,event_bytes,created_at) VALUES (?,?,?,?,1,?,?,?)').bind(key,alias,subject,actor,digest,payload.length,now),
   this.db.prepare('INSERT INTO events (project_key,seq,payload,previous,digest) VALUES (?,1,?,?,?)').bind(key,payload,ZERO,digest)
  ]);}catch(e){if(await this.db.prepare('SELECT key FROM projects WHERE key=?').bind(key).first())fail('CONTRACT_EXISTS');throw e;}
  return {project_key:key,alias,owner_actor:actor};
 }
 async projectIO(subject,reference){
  const p=await this.authorize(subject,reference),db=this.db,bucket=this.bucket,key=p.key;
  return {
   store:{
    async read(){return (await db.prepare('SELECT seq,payload,previous,digest FROM events WHERE project_key=? ORDER BY seq').bind(key).all()).results;},
    async append(expected,event){
     // D1 batches are transactions. Both statements require the same expected
     // head, and the head update must refer to this exact newly inserted event.
     const result=await db.batch([
      db.prepare('INSERT INTO events (project_key,seq,payload,previous,digest) SELECT ?,?,?,?,? WHERE EXISTS (SELECT 1 FROM projects WHERE key=? AND head_seq=? AND head_digest=? AND head_seq<? AND event_bytes+?<=?)').bind(key,event.seq,event.payload,event.previous,event.digest,key,expected.count,expected.head,MAX_EVENTS,event.payload.length,MAX_LEDGER_BYTES),
      db.prepare('UPDATE projects SET head_seq=?,head_digest=?,event_bytes=event_bytes+? WHERE key=? AND head_seq=? AND head_digest=? AND EXISTS (SELECT 1 FROM events WHERE project_key=? AND seq=? AND digest=?)').bind(event.seq,event.digest,event.payload.length,key,expected.count,expected.head,key,event.seq,event.digest)
     ]);return result[0].meta.changes===1&&result[1].meta.changes===1;
    }
   },
   artifacts:{
    async get(digest){if(!/^[a-f0-9]{64}$/.test(digest))fail('ARTIFACT_CORRUPT');const meta=await db.prepare('SELECT size FROM artifacts WHERE project_key=? AND digest=?').bind(key,digest).first();if(!meta)fail('PATH_UNSAFE','Uploaded artifact is missing');const object=await bucket.get(key+'/'+digest);if(!object)fail('PATH_UNSAFE','Uploaded artifact is missing');const bytes=new Uint8Array(await object.arrayBuffer());if(bytes.length!==meta.size||bytes.length>MAX_INGEST)fail('ARTIFACT_CORRUPT');return bytes;},
    async put(digest,bytes){
     if(bytes.length>MAX_INGEST||await sha256(bytes)!==digest)fail('ARTIFACT_CORRUPT');
     // Reserve quota before uploading. Failed uploads remain bounded reservations;
     // retries refill the same content-addressed key. No unbounded orphan uploads.
     await db.prepare('INSERT OR IGNORE INTO artifacts (project_key,digest,size) SELECT ?,?,? WHERE COALESCE((SELECT sum(size) FROM artifacts WHERE project_key=?),0)+?<=?').bind(key,digest,bytes.length,key,bytes.length,MAX_UPLOAD_TOTAL).run();
     const meta=await db.prepare('SELECT size FROM artifacts WHERE project_key=? AND digest=?').bind(key,digest).first();if(!meta)fail('STORAGE_LIMIT','Uploaded artifacts are limited to 64 MiB per project; ask its owner to manage retention');if(meta.size!==bytes.length)fail('ARTIFACT_CORRUPT');
     const existing=await bucket.get(key+'/'+digest);if(existing){const old=new Uint8Array(await existing.arrayBuffer());if(old.length!==bytes.length||await sha256(old)!==digest)fail('ARTIFACT_CORRUPT','Existing uploaded digest does not match bytes');return;}
     await bucket.put(key+'/'+digest,bytes,{onlyIf:{etagDoesNotMatch:'*'},httpMetadata:{contentType:'application/octet-stream'}});
     const saved=await bucket.get(key+'/'+digest);if(!saved||await sha256(new Uint8Array(await saved.arrayBuffer()))!==digest)fail('ARTIFACT_CORRUPT','Upload verification failed');
    }
   }
  };
 }
 async engine(subject,reference,mode='viewer'){
  const p=mode==='human'?await this.owner(subject,reference):await this.authorize(subject,reference);
  if(mode!=='human'&&mode!=='viewer')fail('FORBIDDEN');return new Engine({...await this.projectIO(subject,p.key),actor:await subjectActor(subject),role:mode});
 }
 async openWorker(subject,reference,label){
  const p=await this.authorize(subject,reference);if(!['owner','worker'].includes(p.role))fail('FORBIDDEN','A worker membership is required');
  if(typeof label!=='string'||!label.trim()||label.length>80)fail('BAD_INPUT','Worker label is required (max 80)');
  const now=Math.floor(Date.now()/1000),id=randomId(),actor='w'+id;
  const result=await this.db.prepare("INSERT INTO workers (id,project_key,subject,actor,label,expires_at) SELECT ?,?,?,?,?,? WHERE (SELECT count(*) FROM workers WHERE project_key=? AND subject=? AND expires_at>?)<100 AND EXISTS (SELECT 1 FROM projects p LEFT JOIN memberships m ON m.project_key=p.key AND m.subject=? WHERE p.key=? AND (p.owner_subject=? OR m.role='worker'))").bind(id,p.key,subject,actor,label,now+86400,p.key,subject,now,subject,p.key,subject).run();
  if(!result.meta.changes){const current=await this.authorize(subject,p.key);if(!['owner','worker'].includes(current.role))fail('FORBIDDEN');fail('WORKER_LIMIT','At most 100 active worker sessions per project and user');}return {project_key:p.key,worker_id:id,actor,label,expires_at:now+86400,notice:'Coordination identity bound to your signed-in account. This does not prove independent people or organizations.'};
 }
 async workerEngine(subject,reference,workerId){
  const p=await this.authorize(subject,reference);if(!['owner','worker'].includes(p.role))fail('FORBIDDEN');
  const worker=await this.db.prepare('SELECT actor FROM workers WHERE id=? AND project_key=? AND subject=? AND expires_at>?').bind(workerId,p.key,subject,Math.floor(Date.now()/1000)).first();
  if(!worker)fail('FORBIDDEN','Open a worker session for this project and authenticated account');
  return new Engine({...await this.projectIO(subject,p.key),actor:worker.actor,role:'worker'});
 }
 async reviewerEngine(subject,reference){const p=await this.authorize(subject,reference);if(p.role!=='reviewer')fail('FORBIDDEN','A separately authorized reviewer account is required');return new Engine({...await this.projectIO(subject,p.key),actor:await subjectActor(subject),role:'reviewer'});}
 async setMember(subject,reference,memberSubject,role){
  const p=await this.owner(subject,reference);if(typeof memberSubject!=='string'||!memberSubject.trim()||memberSubject.length>512||memberSubject===subject)fail('BAD_INPUT','Use a distinct verified Site user ID');if(!['worker','reviewer','viewer'].includes(role))fail('BAD_INPUT','Invalid member role');
  // An account which has produced work cannot acquire reviewer authority for
  // that project. Historical makers remain distinct even after role changes.
  if(role==='reviewer'&&await this.db.prepare('SELECT id FROM workers WHERE project_key=? AND subject=? LIMIT 1').bind(p.key,memberSubject).first())fail('FORBIDDEN','A worker account cannot become this project’s reviewer');
  const result=await this.db.prepare("INSERT INTO memberships (project_key,subject,role) SELECT ?,?,? WHERE (?!='reviewer' OR NOT EXISTS (SELECT 1 FROM workers WHERE project_key=? AND subject=?)) ON CONFLICT(project_key,subject) DO UPDATE SET role=excluded.role WHERE (excluded.role!='reviewer' OR NOT EXISTS (SELECT 1 FROM workers WHERE project_key=? AND subject=?))").bind(p.key,memberSubject,role,role,p.key,memberSubject,p.key,memberSubject).run();if(!result.meta.changes)fail('FORBIDDEN','A worker account cannot become this project’s reviewer');return {project_key:p.key,subject:memberSubject,role};
 }
}
