import {sha256} from './codec.js';import {fail} from './engine.js';
export function rejectToolTransport(request){if(request.headers.has('authorization')||request.headers.has('oai-sites-authorization')||request.headers.has('mcp-protocol-version')||request.headers.has('mcp-session-id'))fail('FORBIDDEN','Owner actions require the signed-in browser session');}
export async function createBrowserSession(request,storage,subject){
 rejectToolTransport(request);if(request.headers.get('sec-fetch-mode')!=='navigate'||request.headers.get('sec-fetch-dest')!=='document')fail('FORBIDDEN','Open the owner page in your browser');
 const now=Math.floor(Date.now()/1000),id=crypto.randomUUID()+crypto.randomUUID(),csrf=crypto.randomUUID()+crypto.randomUUID(),expires=now+3600;
 // Expired browser credentials have no ledger/provenance role. Worker records
 // are intentionally separate and remain until their owner deletes the project.
 await storage.db.prepare('DELETE FROM browser_sessions WHERE expires_at<=?').bind(now).run();
 await storage.db.prepare('INSERT INTO browser_sessions (id_hash,subject,csrf_hash,expires_at) VALUES (?,?,?,?)').bind(await sha256(id),subject,await sha256(csrf),expires).run();
 return {csrf,cookie:'__Host-rumbo_owner='+id+'; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600'};
}
export async function requireBrowserSession(request,storage,subject){
 rejectToolTransport(request);const origin=new URL(request.url).origin;
 if(request.headers.get('origin')!==origin||request.headers.get('sec-fetch-site')!=='same-origin'||!['cors','same-origin'].includes(request.headers.get('sec-fetch-mode')))fail('FORBIDDEN','Use the same-origin owner browser');
 const token=(request.headers.get('cookie')??'').split(';').map(v=>v.trim()).find(v=>v.startsWith('__Host-rumbo_owner='))?.slice('__Host-rumbo_owner='.length),csrf=request.headers.get('x-rumbo-csrf');
 if(!token||!csrf)fail('FORBIDDEN','Owner browser session is missing; reload while keeping your draft');
 const row=await storage.db.prepare('SELECT subject,csrf_hash FROM browser_sessions WHERE id_hash=? AND expires_at>?').bind(await sha256(token),Math.floor(Date.now()/1000)).first();
 if(!row||row.subject!==subject||row.csrf_hash!==await sha256(csrf))fail('FORBIDDEN','Owner session expired or changed; keep your draft and reload');
}
