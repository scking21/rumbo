import {canonical,utf8,sha256} from './codec.js';import {fail} from './engine.js';
export async function exportProject(storage,subject,reference){
 const project=await storage.owner(subject,reference),io=await storage.projectIO(subject,project.key),engine=await storage.engine(subject,project.key,'human');
 const events=await io.store.read();await engine.replay(events);const meta=(await storage.db.prepare('SELECT digest,size FROM artifacts WHERE project_key=? ORDER BY digest').bind(project.key).all()).results;
 const head=events.at(-1)?.digest??'0'.repeat(64);let index=-1;
 const stream=new ReadableStream({async pull(controller){try{
  let record;
  if(index===-1)record={type:'header',format:'rumbo-sites-export-v1',project_key:project.key,alias:project.alias,events:events.length,artifacts:meta.length,ledger_head:head};
  else if(index<events.length)record={type:'event',...events[index]};
  else if(index<events.length+meta.length){const item=meta[index-events.length],bytes=await io.artifacts.get(item.digest);if(await sha256(bytes)!==item.digest)fail('ARTIFACT_CORRUPT');let binary='';for(const byte of bytes)binary+=String.fromCharCode(byte);record={type:'artifact',digest:item.digest,size:item.size,base64:btoa(binary)};}
  else {record={type:'end',complete:true,events:events.length,artifacts:meta.length,ledger_head:head};controller.enqueue(utf8(canonical(record)+'\n'));controller.close();return;}
  controller.enqueue(utf8(canonical(record)+'\n'));index++;
 }catch(error){controller.error(error);}}});
 return new Response(stream,{headers:{'content-type':'application/x-ndjson; charset=utf-8','content-disposition':'attachment; filename="rumbo-'+project.alias+'-export.ndjson"','cache-control':'no-store','x-content-type-options':'nosniff'}});
}
