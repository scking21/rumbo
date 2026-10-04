import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync,readdirSync} from 'node:fs';
import {fixture} from './support.mjs';
import {subjectActor} from '../worker/storage.js';
import {sha256,utf8} from '../worker/codec.js';
const contract=async(subject='owner',alias='private')=>({project_id:alias,goal:'Synthetic private content',original_request:'Delete synthetic content only',decision_owner:await subjectActor(subject),constraints:[],tasks:[{id:'one',title:'One',dependencies:[],acceptance:[{id:'text',kind:'file_contains',value:'hello'}]}]});
async function project(f,subject='owner',alias='private'){return f.storage.createProject(subject,alias,await contract(subject,alias));}
async function upload(storage,key,content='hello'){const io=await storage.projectIO('owner',key),bytes=utf8(content),digest=await sha256(bytes);await io.artifacts.put(digest,bytes);return {io,bytes,digest};}
function pauseRun(db,match){const prepare=db.prepare.bind(db);let ready,resume;const paused=new Promise(r=>ready=r),gate=new Promise(r=>resume=r);db.prepare=sql=>{const st=prepare(sql);if(match(sql)){const run=st.run.bind(st);st.run=async()=>{ready();await gate;return run();};}return st;};return {paused,resume:()=>resume(),restore:()=>db.prepare=prepare};}
const rejectClosed=e=>['PROJECT_DELETING','PROJECT_DELETED','FORBIDDEN'].includes(e.code);

test('owner deletion requires exact alias confirmation and refuses other tenants and all member roles',async()=>{
 const f=fixture(),{project_key:key}=await project(f);
 for(const role of ['worker','reviewer','viewer']){await f.storage.setMember('owner',key,role,role);await assert.rejects(()=>f.storage.deleteProject(role,key,'private'),e=>e.code==='FORBIDDEN');}
 await assert.rejects(()=>f.storage.deleteProject('outsider',key,'private'),e=>e.code==='FORBIDDEN');
 for(const confirmation of ['',key,'Private','private ',null])await assert.rejects(()=>f.storage.deleteProject('owner',key,confirmation),e=>e.code==='CONFIRMATION_REQUIRED');
 assert.equal((await f.storage.engine('owner',key)).role,'viewer');
});

test('deletion replaces artifacts with permanent empty guards and removes every project row and owner identifier',async()=>{
 const f=fixture(),{project_key:key}=await project(f);const {digest}=await upload(f.storage,key);
 await f.storage.setMember('owner',key,'colleague','worker');await f.storage.openWorker('colleague',key,'sensitive worker label');
 const other=await project(f,'other-owner');await f.storage.openWorker('owner',key,'owner worker');
 assert.deepEqual(await f.storage.deleteProject('owner',key,'private'),{project_key:key,status:'deleted'});
 for(const table of ['events','artifacts','memberships','workers'])assert.equal(f.db.prepare(`SELECT count(*) AS n FROM ${table} WHERE project_key=?`).get(key).n,0);
 assert.equal(f.db.prepare('SELECT count(*) AS n FROM projects WHERE key=?').get(key).n,0);
 assert.deepEqual({...f.db.prepare('SELECT * FROM deleted_projects WHERE key=?').get(key)},{key});
 assert.deepEqual(f.objects.get(key+'/'+digest),new Uint8Array());assert.equal((await f.storage.listProjects('owner')).length,0);
 assert.equal((await f.storage.engine('other-owner',other.project_key)).role,'viewer');
 assert.deepEqual(await f.storage.deleteProject('owner',key,'private'),{project_key:key,status:'deleted'});
 await assert.rejects(()=>f.storage.deleteProject('outsider',key,'private'),e=>e.code==='FORBIDDEN');
 await assert.rejects(()=>project(f),e=>e.code==='PROJECT_DELETED');
});

test('R2 partial failure fences reads and stale writes, hides pending projects from members and permits owner retry',async()=>{
 const f=fixture(),{project_key:key}=await project(f),{io,digest}=await upload(f.storage,key);await upload(f.storage,key,'second');
 await f.storage.setMember('owner',key,'member','worker');const worker=await f.storage.openWorker('member',key,'worker');
 const staleWorker=await f.storage.workerEngine('member',key,worker.worker_id),staleOwner=await f.storage.engine('owner',key,'human');
 const put=f.env.ARTIFACTS.put.bind(f.env.ARTIFACTS);let guardCount=0;f.env.ARTIFACTS.put=async(k,v,o)=>{if(v.byteLength===0&&++guardCount===2)throw new Error('synthetic R2 unavailable');return put(k,v,o);};
 assert.deepEqual(await f.storage.deleteProject('owner',key,'private'),{project_key:key,status:'deleting',retry:true});
 assert.equal((await f.storage.listProjects('owner'))[0].lifecycle,'deleting');assert.deepEqual(await f.storage.listProjects('member'),[]);
 for(const action of [()=>io.store.read(),()=>io.artifacts.get(digest),()=>io.artifacts.put(digest,utf8('hello')),()=>staleWorker.execute('claim_task',{task_id:'one',contract_revision:1,lease_seconds:300}),()=>staleOwner.snapshot(),()=>f.storage.openWorker('owner',key,'later'),()=>f.storage.setMember('owner',key,'later','viewer')])await assert.rejects(action,rejectClosed);
 assert.equal(f.db.prepare('SELECT count(*) AS n FROM events WHERE project_key=?').get(key).n,1);
 f.env.ARTIFACTS.put=put;assert.equal((await f.storage.deleteProject('owner',key,'private')).status,'deleted');
 assert.ok([...f.objects.values()].every(v=>v.byteLength===0));
});

test('paused conditional artifact put cannot restore content after guard and completed cleanup',async()=>{
 const f=fixture(),{project_key:key}=await project(f),io=await f.storage.projectIO('owner',key),bytes=utf8('paused upload'),digest=await sha256(bytes);
 const put=f.env.ARTIFACTS.put.bind(f.env.ARTIFACTS);let ready,resume;const paused=new Promise(r=>ready=r),gate=new Promise(r=>resume=r);
 f.env.ARTIFACTS.put=async(k,v,o)=>{if(v.byteLength){ready();await gate;}return put(k,v,o);};
 const uploading=io.artifacts.put(digest,bytes);await paused;assert.equal((await f.storage.deleteProject('owner',key,'private')).status,'deleted');resume();
 await assert.rejects(uploading,rejectClosed);assert.equal(f.objects.get(key+'/'+digest).byteLength,0);
});

test('upload that wins before the guard is overwritten, including the empty-file digest',async()=>{
 const f=fixture(),{project_key:key}=await project(f);const first=await upload(f.storage,key,'already uploaded'),empty=await upload(f.storage,key,'');
 const io=first.io;assert.equal((await f.storage.deleteProject('owner',key,'private')).status,'deleted');
 assert.equal(f.objects.get(key+'/'+first.digest).byteLength,0);assert.equal(f.objects.get(key+'/'+empty.digest).byteLength,0);
 await assert.rejects(()=>io.artifacts.put(empty.digest,empty.bytes),rejectClosed);
});

test('reservations paused before execution cannot add upload keys after the deletion fence',async()=>{
 const f=fixture(),{project_key:key}=await project(f),io=await f.storage.projectIO('owner',key),bytes=utf8('never reserved'),digest=await sha256(bytes);
 const pause=pauseRun(f.storage.db,sql=>sql.startsWith('INSERT OR IGNORE INTO artifacts'));const pending=io.artifacts.put(digest,bytes);await pause.paused;
 await f.storage.deleteProject('owner',key,'private');pause.resume();await assert.rejects(pending,rejectClosed);assert.equal(f.objects.size,0);
});

test('worker and membership statements recheck lifecycle after prior authorization',async()=>{
 for(const kind of ['worker','member']){
  const f=fixture(),{project_key:key}=await project(f);const pause=pauseRun(f.storage.db,sql=>sql.startsWith(kind==='worker'?'INSERT INTO workers':'INSERT INTO memberships'));
  const pending=kind==='worker'?f.storage.openWorker('owner',key,'paused'):f.storage.setMember('owner',key,'new-member','viewer');await pause.paused;
  await f.storage.deleteProject('owner',key,'private');pause.resume();await assert.rejects(pending,rejectClosed);
  assert.equal(f.db.prepare(`SELECT count(*) AS n FROM ${kind==='worker'?'workers':'memberships'}`).get().n,0);
 }
});

test('event CAS paused after read cannot append after the fence',async()=>{
 const f=fixture(),{project_key:key}=await project(f),io=await f.storage.projectIO('owner',key),rows=await io.store.read();
 const pause=pauseRun(f.storage.db,sql=>sql.startsWith('INSERT INTO events'));const pending=io.store.append({count:rows.length,head:rows.at(-1).digest},{seq:2,payload:'{}',previous:rows.at(-1).digest,digest:'a'.repeat(64)});await pause.paused;
 // Synthetic D1 has one connection; apply the fence inside the paused transaction.
 f.db.prepare("UPDATE projects SET lifecycle='deleting' WHERE key=?").run(key);pause.resume();await assert.rejects(pending,rejectClosed);
 assert.equal(f.db.prepare('SELECT count(*) AS n FROM events').get().n,1);
});

test('failed final D1 transaction rolls back removed rows and retains retry authorization after guards succeeded',async()=>{
 const f=fixture(),{project_key:key}=await project(f);const {digest}=await upload(f.storage,key);await f.storage.setMember('owner',key,'member','worker');await f.storage.openWorker('member',key,'retained until commit');
 const prepare=f.storage.db.prepare.bind(f.storage.db);let failed=false;f.storage.db.prepare=sql=>{const st=prepare(sql);if(sql.startsWith('DELETE FROM projects')){const run=st.run.bind(st);st.run=async()=>{if(!failed){failed=true;throw new Error('synthetic final-statement failure');}return run();};}return st;};
 assert.equal((await f.storage.deleteProject('owner',key,'private')).status,'deleting');assert.equal(f.objects.get(key+'/'+digest).byteLength,0);
 assert.equal(f.db.prepare('SELECT owner_subject FROM projects WHERE key=?').get(key).owner_subject,'owner');
 for(const table of ['events','artifacts','memberships','workers'])assert.equal(f.db.prepare(`SELECT count(*) AS n FROM ${table} WHERE project_key=?`).get(key).n,1);
 assert.equal(f.db.prepare('SELECT count(*) AS n FROM deleted_projects').get().n,0);assert.equal((await f.storage.deleteProject('owner',key,'private')).status,'deleted');
});

test('deletion bounds each call and makes progress across more than one guard page',async()=>{
 const f=fixture(),{project_key:key}=await project(f);for(let i=0;i<65;i++)await upload(f.storage,key,'content '+i);
 const put=f.env.ARTIFACTS.put.bind(f.env.ARTIFACTS);let count=0;f.env.ARTIFACTS.put=async(...args)=>{count++;return put(...args);};
 assert.equal((await f.storage.deleteProject('owner',key,'private')).status,'deleting');assert.ok(count>0&&count<=64);assert.equal((await f.storage.deleteProject('owner',key,'private')).status,'deleted');assert.equal(count,65);
});

test('creation paused after empty prechecks cannot bypass a later permanent project key guard',async()=>{
 const f=fixture(),batch=f.storage.db.batch.bind(f.storage.db);let ready,resume,once=true;const paused=new Promise(r=>ready=r),gate=new Promise(r=>resume=r);
 f.storage.db.batch=async statements=>{if(once){once=false;ready();await gate;}return batch(statements);};
 const creating=project(f);await paused;const {project_key:key}=await project(f);await f.storage.deleteProject('owner',key,'private');resume();
 await assert.rejects(creating,e=>e.code==='PROJECT_DELETED');assert.equal(f.db.prepare('SELECT count(*) AS n FROM projects').get().n,0);assert.equal(f.db.prepare('SELECT count(*) AS n FROM events').get().n,0);
});

test('a byte read paused before the fence cannot return captured content after deletion',async()=>{
 const f=fixture(),{project_key:key}=await project(f),{io,digest}=await upload(f.storage,key);
 const get=f.env.ARTIFACTS.get.bind(f.env.ARTIFACTS);let ready,resume,once=true;const paused=new Promise(r=>ready=r),gate=new Promise(r=>resume=r);
 f.env.ARTIFACTS.get=async k=>{const object=await get(k);if(once){once=false;return {async arrayBuffer(){const bytes=await object.arrayBuffer();ready();await gate;return bytes;}};}return object;};
 const reading=io.artifacts.get(digest);await paused;await f.storage.deleteProject('owner',key,'private');resume();await assert.rejects(reading,rejectClosed);
});

test('stale member and worker handles recheck role, removal and expiry at execution',async()=>{
 const f=fixture(),{project_key:key}=await project(f);await f.storage.setMember('owner',key,'member','worker');const worker=await f.storage.openWorker('member',key,'worker'),engine=await f.storage.workerEngine('member',key,worker.worker_id);
 await f.storage.setMember('owner',key,'member','viewer');await assert.rejects(()=>engine.execute('claim_task',{task_id:'one',contract_revision:1,lease_seconds:300}),e=>e.code==='FORBIDDEN');
 const viewer=await f.storage.engine('member',key);f.db.prepare('DELETE FROM memberships WHERE project_key=? AND subject=?').run(key,'member');await assert.rejects(()=>viewer.snapshot(),e=>e.code==='FORBIDDEN');
 const own=await f.storage.openWorker('owner',key,'expires'),expired=await f.storage.workerEngine('owner',key,own.worker_id);f.db.prepare('UPDATE workers SET expires_at=0 WHERE id=?').run(own.worker_id);await assert.rejects(()=>expired.execute('claim_task',{task_id:'one',contract_revision:1,lease_seconds:300}),e=>e.code==='FORBIDDEN');
});

test('failed guard verification never marks cleanup complete',async()=>{
 const f=fixture(),{project_key:key}=await project(f),{digest}=await upload(f.storage,key),put=f.env.ARTIFACTS.put;
 f.env.ARTIFACTS.put=async()=>({});assert.equal((await f.storage.deleteProject('owner',key,'private')).status,'deleting');assert.equal(f.db.prepare('SELECT guard_written FROM artifacts').get().guard_written,0);assert.equal(f.objects.get(key+'/'+digest).byteLength,5);
 f.env.ARTIFACTS.put=put;assert.equal((await f.storage.deleteProject('owner',key,'private')).status,'deleted');
});

test('new migration upgrades populated deployed baseline without losing existing data',()=>{
 const db=new DatabaseSync(':memory:');db.exec(readFileSync('drizzle/0000_initial.sql','utf8'));db.prepare('INSERT INTO projects (key,alias,owner_subject,owner_actor,created_at) VALUES (?,?,?,?,?)').run('key','alias','subject','actor',1);db.prepare('INSERT INTO artifacts VALUES (?,?,?)').run('key','digest',7);
 const migrations=readdirSync('drizzle').filter(n=>/^\d+.*\.sql$/.test(n)&&!n.startsWith('0000')).sort();assert.ok(migrations.length>0,'add a migration without rewriting deployed 0000');for(const migration of migrations)db.exec(readFileSync('drizzle/'+migration,'utf8'));
 assert.equal(db.prepare('SELECT lifecycle FROM projects').get().lifecycle,'active');assert.equal(db.prepare('SELECT size FROM artifacts').get().size,7);assert.equal(db.prepare('SELECT guard_written FROM artifacts').get().guard_written,0);assert.equal(db.prepare('SELECT count(*) AS n FROM deleted_projects').get().n,0);db.close();
});

test('worker expiry between CAS statements cannot commit an event without advancing the project head',async()=>{
 const f=fixture(),{project_key:key}=await project(f),session=await f.storage.openWorker('owner',key,'near expiry'),engine=await f.storage.workerEngine('owner',key,session.worker_id);
 let second=100;f.db.function('unixepoch',()=>second);f.db.prepare('UPDATE workers SET expires_at=101 WHERE id=?').run(session.worker_id);
 const prepare=f.storage.db.prepare.bind(f.storage.db);f.storage.db.prepare=sql=>{const st=prepare(sql);if(sql.startsWith('INSERT INTO events')){const run=st.run.bind(st);st.run=async()=>{const result=await run();second=101;return result;};}return st;};
 await assert.rejects(()=>engine.execute('claim_task',{task_id:'one',contract_revision:1,lease_seconds:300}),e=>e.code==='FORBIDDEN');
 const head=f.db.prepare('SELECT head_seq,head_digest FROM projects WHERE key=?').get(key),last=f.db.prepare('SELECT seq,digest FROM events WHERE project_key=? ORDER BY seq DESC LIMIT 1').get(key);
 assert.equal(head.head_seq,last.seq);assert.equal(head.head_digest,last.digest);assert.equal((await (await f.storage.engine('owner',key)).snapshot()).events_count,2);
});

test('database rejects a retired handler’s unconditional project insert after deletion',async()=>{
 const f=fixture(),{project_key:key}=await project(f);await f.storage.deleteProject('owner',key,'private');
 // A Worker from before the guarded-deletion release would not consult the
 // tombstone. The database must preserve this invariant across that cutover.
 assert.throws(()=>f.db.prepare('INSERT INTO projects (key,alias,owner_subject,owner_actor,head_seq,head_digest,event_bytes,created_at) VALUES (?,?,?,?,1,?,?,?)').run(key,'private','owner','owner-actor','a'.repeat(64),1,1),/PROJECT_DELETED/);
 assert.equal(f.db.prepare('SELECT count(*) AS n FROM projects WHERE key=?').get(key).n,0);await assert.rejects(()=>project(f),e=>e.code==='PROJECT_DELETED');
});
