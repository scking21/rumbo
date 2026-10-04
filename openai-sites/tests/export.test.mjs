import test from 'node:test';import assert from 'node:assert/strict';import {fixture} from './support.mjs';import {subjectActor} from '../worker/storage.js';import {exportProject} from '../worker/export.js';import {spawnSync} from 'node:child_process';
test('owner export streams verified ledger and all historical immutable artifacts',async()=>{
 const {storage}=fixture(),owner=await subjectActor('owner');const p=await storage.createProject('owner','demo',{project_id:'demo',goal:'Test',original_request:'Synthetic only',decision_owner:owner,constraints:[],tasks:[{id:'one',title:'One',dependencies:[],acceptance:[{id:'ok',kind:'file_contains',value:'hello'}]}]});
 const w=await storage.openWorker('owner',p.project_key,'maker'),engine=await storage.workerEngine('owner',p.project_key,w.worker_id);
 await engine.execute('claim_task',{task_id:'one',contract_revision:1,lease_seconds:300});for(const content of ['hello first','hello second'])await engine.execute('ingest_artifact',{task_id:'one',contract_revision:1,filename:'x.txt',content});
 const response=await exportProject(storage,'owner',p.project_key),text=await response.text();const lines=text.trim().split('\n').map(JSON.parse);assert.equal(lines.filter(x=>x.type==='artifact').length,2);assert.equal(lines.at(-1).complete,true);
 const checked=spawnSync('python3',['scripts/verify-export.py'],{input:text,encoding:'utf8'});assert.equal(checked.status,0,checked.stderr);assert.equal(JSON.parse(checked.stdout).verified,true);
 const truncated=spawnSync('python3',['scripts/verify-export.py'],{input:text.split('\n').slice(0,-2).join('\n'),encoding:'utf8'});assert.notEqual(truncated.status,0);
 await assert.rejects(()=>exportProject(storage,'outsider',p.project_key),e=>e.code==='FORBIDDEN');
});

async function uploadedProject(){
 const f=fixture(),owner=await subjectActor('owner');
 const p=await f.storage.createProject('owner','export-workflow',{project_id:'export-workflow',goal:'Recover exact work',original_request:'Synthetic interrupted upload/export cases',decision_owner:owner,constraints:[],tasks:[{id:'one',title:'One',dependencies:[],acceptance:[{id:'ok',kind:'file_contains',value:'hello'}]}]});
 const w=await f.storage.openWorker('owner',p.project_key,'maker'),engine=await f.storage.workerEngine('owner',p.project_key,w.worker_id);
 await engine.execute('claim_task',{task_id:'one',contract_revision:1,lease_seconds:300});
 const upload=content=>engine.execute('ingest_artifact',{task_id:'one',contract_revision:1,filename:'x.txt',content});
 await upload('hello committed');return {...f,p,engine,upload};
}
function verifiedExport(text){const result=spawnSync('python3',['scripts/verify-export.py'],{input:text,encoding:'utf8'});assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout);}
test('an interrupted uncommitted upload does not prevent exporting committed history',async()=>{
 const {storage,p,env,engine,upload,db}=await uploadedProject(),put=env.ARTIFACTS.put;
 env.ARTIFACTS.put=async()=>{throw new Error('Synthetic interrupted R2 upload');};
 await assert.rejects(()=>upload('hello interrupted'),/Synthetic interrupted R2 upload/);
 env.ARTIFACTS.put=put;
 assert.equal(db.prepare('SELECT count(*) AS n FROM artifacts').get().n,2,'Failed upload remains a bounded reservation');
 assert.equal((await engine.snapshot()).tasks[0].artifact.revision,1,'Failed upload must not commit an event');
 const text=await (await exportProject(storage,'owner',p.project_key)).text();
 assert.equal(verifiedExport(text).artifacts,1,'Export includes committed history only');
 await upload('hello interrupted');
 assert.equal(verifiedExport(await (await exportProject(storage,'owner',p.project_key)).text()).artifacts,2,'Retry reuses reservation and exports committed bytes');
});
test('export captures one ledger snapshot while later uploads commit independently',async()=>{
 const {storage,p,upload}=await uploadedProject();const response=await exportProject(storage,'owner',p.project_key);
 await upload('hello later');const text=await response.text(),records=text.trim().split('\n').map(JSON.parse);
 assert.equal(verifiedExport(text).artifacts,1);assert.equal(records[0].events,3);assert.equal(records.at(-1).events,3);
 assert.equal(verifiedExport(await (await exportProject(storage,'owner',p.project_key)).text()).artifacts,2);
});
test('canceled export can be repeated without changing the ledger or historical uploads',async()=>{
 const {storage,p,engine,upload}=await uploadedProject();await upload('hello latest');const before=await engine.snapshot();
 const reader=(await exportProject(storage,'owner',p.project_key)).body.getReader();await reader.read();await reader.cancel('Synthetic interrupted download');
 const a=await (await exportProject(storage,'owner',p.project_key)).text(),b=await (await exportProject(storage,'owner',p.project_key)).text();
 assert.equal(a,b);assert.equal(verifiedExport(a).artifacts,2);assert.deepEqual(await engine.snapshot(),before);
});
test('historical upload corruption prevents a complete export even when the current upload is healthy',async()=>{
 const {storage,p,engine,upload,objects}=await uploadedProject(),historical=(await engine.snapshot()).tasks[0].artifact;
 await upload('hello latest');objects.set(p.project_key+'/'+historical.sha256,new TextEncoder().encode('wrong old bytes'));
 assert.equal((await engine.snapshot()).tasks[0].status,'produced');
 await assert.rejects(async()=>await (await exportProject(storage,'owner',p.project_key)).text(),e=>e.code==='ARTIFACT_CORRUPT');
});
test('export preserves exact empty, BOM, CRLF and multibyte UTF-8 uploads',async()=>{
 const {storage,p,upload}=await uploadedProject(),contents=['','\ufeffhello\r\nworld','hello café 😀'];
 for(const content of contents)await upload(content);
 const text=await (await exportProject(storage,'owner',p.project_key)).text();assert.equal(verifiedExport(text).artifacts,4);
 const decoded=text.trim().split('\n').map(JSON.parse).filter(x=>x.type==='artifact').map(x=>Buffer.from(x.base64,'base64').toString('utf8'));
 assert.deepEqual(new Set(decoded),new Set(['hello committed',...contents]));
});
test('offline verification accepts an export at the supported 10000-event ledger limit',async()=>{
 const {storage,p,engine,db,objects}=await uploadedProject();
 const {canonical,sha256,utf8}=await import('../worker/codec.js');const {MAX_EVENTS}=await import('../worker/engine.js');
 const snapshot=await engine.snapshot(),template=JSON.parse(db.prepare('SELECT payload FROM events ORDER BY seq DESC LIMIT 1').get().payload);
 let previous=snapshot.ledger_head,bytes=db.prepare('SELECT event_bytes AS n FROM projects').get().n;
 // Arrange a valid long persisted history directly to avoid quadratic repeated
 // replays while creating the fixture; the real exporter/replay/verifier run below.
 const insertEvent=db.prepare('INSERT INTO events(project_key,seq,payload,previous,digest) VALUES(?,?,?,?,?)');
 const insertArtifact=db.prepare('INSERT INTO artifacts(project_key,digest,size) VALUES(?,?,?)');
 db.exec('BEGIN');try{for(let seq=4;seq<=MAX_EVENTS;seq++){
  const content=utf8('hello history '+seq),digest=await sha256(content),event=structuredClone(template);
  Object.assign(event.data.artifact,{sha256:digest,size:content.length,revision:seq-2});
  const payload=canonical(event),head=await sha256(previous+'\n'+payload);
  insertEvent.run(p.project_key,seq,payload,previous,head);insertArtifact.run(p.project_key,digest,content.length);objects.set(p.project_key+'/'+digest,content);
  bytes+=payload.length;previous=head;
 }db.prepare('UPDATE projects SET head_seq=?,head_digest=?,event_bytes=? WHERE key=?').run(MAX_EVENTS,previous,bytes,p.project_key);db.exec('COMMIT');}catch(e){db.exec('ROLLBACK');throw e;}
 const text=await (await exportProject(storage,'owner',p.project_key)).text();assert.equal(verifiedExport(text).events,MAX_EVENTS);
 assert.equal(verifiedExport(text).artifacts,MAX_EVENTS-2);
});
