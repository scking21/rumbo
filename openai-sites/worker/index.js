import {exportProject} from './export.js';
import {Storage,subjectActor} from './storage.js';
import {parseJSON,canonical} from './codec.js';
import {fields,RumboError,fail} from './engine.js';
import {dispatch,rpcError} from './protocol.js';
import {createBrowserSession,requireBrowserSession} from './owner-auth.js';
import {OWNER_HTML,OWNER_JS,OWNER_CSS,BOARD_HTML} from './assets.js';
const BASE_HEADERS={'cache-control':'no-store','x-content-type-options':'nosniff','referrer-policy':'no-referrer'};
const CSP="default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'none'; font-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'";
function response(value,status=200,headers={}){return new Response(typeof value==='string'?value:canonical(value),{status,headers:{...BASE_HEADERS,'content-type':'application/json; charset=utf-8',...headers}});}
function user(request){const id=request.headers.get('oai-authenticated-user-id'),email=request.headers.get('oai-authenticated-user-email');return id&&email&&id.length<=512&&email.length<=320?id:null;}
async function bodyJSON(request){
 if(!request.headers.get('content-type')?.split(';')[0].trim().match(/^application\/json$/i))fail('CONTENT_TYPE','Use application/json');
 const reader=request.body?.getReader();if(!reader)fail('BAD_INPUT','Missing JSON body');let length=0;const chunks=[];
 while(true){const {done,value}=await reader.read();if(done)break;length+=value.length;if(length>1048576){await reader.cancel();fail('REQUEST_TOO_LARGE');}chunks.push(value);}
 const bytes=new Uint8Array(length);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
 try{return parseJSON(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{fail('INVALID_JSON');}
}
function statusFor(code){return code==='FORBIDDEN'?403:code==='REQUEST_TOO_LARGE'?413:code==='CONTENT_TYPE'?415:['STORAGE_UNAVAILABLE','LEDGER_UNREADABLE','ARTIFACT_CORRUPT','PATH_UNSAFE','LEDGER_CORRUPT'].includes(code)?503:code?.startsWith('STALE_')||['LEASE_CONFLICT','CONTRACT_EXISTS','CONCURRENT_MODIFICATION'].includes(code)?409:400;}
export default {async fetch(request,env){
 const url=new URL(request.url),path=url.pathname,subject=user(request);
 try{
  if(path==='/healthz'&&request.method==='GET')return response({status:'alive',candidate:true});
  if(path==='/mcp'){
   if(request.method!=='POST')return response({error:'Stateless MCP requires POST'},405,{allow:'POST'});
   const origin=request.headers.get('origin');if(origin&&origin!==url.origin)return response({error:'Untrusted Origin'},403);
   let payload;try{payload=await bodyJSON(request);}catch(e){if(e.code==='INVALID_JSON')return response(rpcError(null,-32700,'Invalid JSON'));throw e;}
   if(payload?.method==='tools/call'&&!subject)return response({error:'Sign in through the managed Site connection'},401);
   const result=await dispatch(payload,{storage:subject?new Storage(env):null,subject,origin:url.origin});return result===null?new Response(null,{status:202,headers:BASE_HEADERS}):response(result);
  }
  if(request.method==='GET'&&['/owner.js','/owner.css'].includes(path))return response(path==='/owner.js'?OWNER_JS:OWNER_CSS,200,{'content-type':path.endsWith('.js')?'text/javascript; charset=utf-8':'text/css; charset=utf-8'});
  if(!subject)return response({error:'Sign in with ChatGPT to access this private project'},401);
  const storage=new Storage(env);
  if(path==='/'&&request.method==='GET'){
   const session=await createBrowserSession(request,storage,subject);return response(OWNER_HTML.replace('__CSRF__',session.csrf),200,{'content-type':'text/html; charset=utf-8','content-security-policy':CSP,'set-cookie':session.cookie});
  }
  if(path==='/board'&&request.method==='GET'){await storage.authorize(subject,url.searchParams.get('project_key')??'');return response(BOARD_HTML,200,{'content-type':'text/html; charset=utf-8'});}
  if(path==='/api/me'&&request.method==='GET')return response({subject,actor:await subjectActor(subject)});
  if(path==='/api/projects'&&request.method==='GET')return response({projects:await storage.listProjects(subject)});
  if(path==='/api/state'&&request.method==='GET'){
   const key=url.searchParams.get('project_key')??'';return response({...await (await storage.engine(subject,key)).snapshot(),hosted_project_key:key});
  }
  if(path==='/api/artifact'&&request.method==='GET')return response(await (await storage.engine(subject,url.searchParams.get('project_key')??'')).artifactView({task_id:url.searchParams.get('task_id'),contract_revision:Number(url.searchParams.get('contract_revision')),artifact_revision:Number(url.searchParams.get('artifact_revision'))}));
  if(path.startsWith('/owner/api/')&&request.method==='POST'){
   await requireBrowserSession(request,storage,subject);const args=await bodyJSON(request);
   if(path==='/owner/api/create'){fields(args,['contract']);return response(await storage.createProject(subject,args.contract.project_id,args.contract));}
   if(path==='/owner/api/export'){fields(args,['project_key']);return exportProject(storage,subject,args.project_key);}
   if(path==='/owner/api/member'){fields(args,['project_key','subject','role']);return response(await storage.setMember(subject,args.project_key,args.subject,args.role));}
   if(path==='/owner/api/revise'||path==='/owner/api/decide'){
    const expected=path.endsWith('revise')?['project_key','contract','expected_revision','reason']:['project_key','task_id','contract_revision','artifact_revision','outcome','reason'];fields(args,expected);const {project_key,...action}=args;const engine=await storage.engine(subject,project_key,'human');return response(await engine.execute(path.endsWith('revise')?'revise_contract':'decide',action));
   }
  }
  return response({error:'Not found'},404);
 }catch(e){if(e instanceof RumboError)return response({error:e.message,code:e.code},statusFor(e.code));console.error('rumbo operation failed',{name:e?.name??'Error'});return response({error:'Persistent operation unavailable; refresh before retrying an uncertain write'},503);}
}};
