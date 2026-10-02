/** Synthetic-only CI server. NEVER deployed or included in the Worker bundle. */
import http from 'node:http';import worker from '../worker/index.js';import {fixture} from '../tests/support.mjs';
if(process.env.RUMBO_SYNTHETIC_BROWSER_TESTS!=='1')throw new Error('Explicit synthetic test mode required');
const {env}=fixture();
const server=http.createServer(async(req,res)=>{try{const body=[];for await(const chunk of req)body.push(chunk);const headers=new Headers(req.headers);headers.set('oai-authenticated-user-id','owner');headers.set('oai-authenticated-user-email','owner@example.test');const request=new Request('http://localhost:8766'+req.url,{method:req.method,headers,...(!['GET','HEAD'].includes(req.method)?{body:Buffer.concat(body)}:{})});const response=await worker.fetch(request,env);res.writeHead(response.status,Object.fromEntries(response.headers));res.end(Buffer.from(await response.arrayBuffer()));}catch{res.writeHead(500);res.end('Synthetic server error');}});
server.listen(8766,'127.0.0.1',()=>console.log('Synthetic Rumbo browser fixture ready'));
process.on('SIGTERM',()=>server.close());
