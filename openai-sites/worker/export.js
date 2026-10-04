import {canonical,parseJSON,utf8,sha256} from './codec.js';import {fail} from './engine.js';
export async function exportProject(storage,subject,reference){
 const project=await storage.owner(subject,reference),io=await storage.projectIO(subject,project.key),engine=await storage.engine(subject,project.key,'human');
 const events=await io.store.read();await engine.replay(events);
 // Export the immutable uploads referenced by this exact ledger snapshot. Quota
 // reservations may belong to interrupted or still-in-flight uploads and are not
 // committed project history; including them can poison an otherwise valid export.
 const committed=new Map();for(const row of events){const artifact=parseJSON(row.payload,128).data?.artifact;if(artifact?.source==='uploaded_text')committed.set(artifact.sha256,{digest:artifact.sha256,size:artifact.size});}
 const meta=[...committed.values()].sort((a,b)=>a.digest.localeCompare(b.digest));
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
