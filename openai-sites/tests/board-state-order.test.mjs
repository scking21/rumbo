import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {JSDOM} from 'jsdom';
import {dispatch} from '../worker/protocol.js';
import {subjectActor} from '../worker/storage.js';
import {fixture as storageFixture} from './support.mjs';

const tick = () => new Promise(resolve=>setImmediate(resolve));
const selection = {project_selection_required:true,projects:[{alias:'Project A',role:'owner',project_key:'a'},{alias:'Project B',role:'owner',project_key:'b'}]};
const snapshot = (project,revision=1) => ({version:1,project_id:project,hosted_project_key:project.toLowerCase(),goal:'Goal '+project,contract_revision:revision,decision_owner:'Synthetic owner',integrity:{valid:true},tasks:[{id:'task',title:'Task '+project,status:'produced',acceptance:[],evidence:[],decisions:[]}]});
async function fixture(source,initial=snapshot('A')) {
  const messages=[];let send;
  // jsdom exercises real board code and DOM state with a synthetic MCP parent.
  // It does not supply native browser focus, layout or transport verification.
  const dom=new JSDOM(source,{url:'https://board.test/board',runScripts:'dangerously',beforeParse(w){
    const parent={postMessage(message){
      messages.push(message);
      if(message.method==='ui/initialize')queueMicrotask(()=>send({id:message.id,result:{protocolVersion:'2026-01-26',hostCapabilities:{serverTools:{}},hostContext:{theme:'light'}}}));
      if(message.method==='ui/notifications/initialized' && initial!==null)queueMicrotask(()=>send({method:'ui/notifications/tool-result',params:{structuredContent:initial}}));
    }};
    Object.defineProperty(w,'parent',{value:parent});
    send=(data,origin='https://host.test',source=parent)=>w.dispatchEvent(new w.MessageEvent('message',{source,origin,data:{jsonrpc:'2.0',...data}}));
  }});
  await tick();
  return {dom,d:dom.window.document,send,calls:()=>messages.filter(message=>message.method==='tools/call')};
}
const hostedURL=new URL('../web/board.html',import.meta.url);
const boards=[['hosted board',hostedURL]];
const localURL=new URL('../../rumbo/web/board.html',import.meta.url);
if(fs.existsSync(localURL))boards.push(['local board',localURL]);

for(const [name,url] of boards){
  const source=fs.readFileSync(url,'utf8');
  for(const initialOrder of ['before','after'])test(name+': a delayed initial host result cannot supersede a refresh ('+initialOrder+' its response)',async()=>{
    const {dom,d,calls,send}=await fixture(source,null);try{
      assert.equal(d.getElementById('refresh').disabled,false);
      d.getElementById('refresh').click();const refresh=calls()[0];
      const deliverInitial=()=>send({method:'ui/notifications/tool-result',params:{structuredContent:snapshot('A',1)}});
      if(initialOrder==='before'){
        deliverInitial();await tick();
        assert.equal(d.getElementById('refresh').disabled,true,'The initial result must not finish the current refresh');
      }
      send({id:refresh.id,result:{structuredContent:snapshot('A',2)}});await tick();
      if(initialOrder==='after'){deliverInitial();await tick();}
      assert.equal(d.getElementById('goal').textContent,'Goal A');
      assert.equal(d.getElementById('contract-revision').textContent,'2');
      assert.equal(d.getElementById('refresh').disabled,false);
      assert.equal(d.getElementById('error').hidden,true);
      // Only the initial delivery is obsolete. Later host updates still win.
      send({method:'ui/notifications/tool-result',params:{structuredContent:snapshot('B',3)}});await tick();
      assert.equal(d.getElementById('goal').textContent,'Goal B');
      assert.equal(d.getElementById('contract-revision').textContent,'3');
    }finally{dom.window.close();}
  });
  for(const initialOrder of ['before','after'])test(name+': a delayed initial host error cannot spoil a refresh ('+initialOrder+' its response)',async()=>{
    const {dom,d,calls,send}=await fixture(source,null);try{
      d.getElementById('refresh').click();const refresh=calls()[0];
      const deliverInitial=()=>send({method:'ui/notifications/tool-result',params:{isError:true}});
      if(initialOrder==='before'){deliverInitial();await tick();}
      send({id:refresh.id,result:{structuredContent:snapshot('A',2)}});await tick();
      if(initialOrder==='after'){deliverInitial();await tick();}
      assert.equal(d.getElementById('contract-revision').textContent,'2');
      assert.equal(d.getElementById('error').hidden,true);
      assert.equal(d.getElementById('refresh').disabled,false);
    }finally{dom.window.close();}
  });
  for(const project of ['A','B'])test(name+': a newer host '+(project==='A'?'revision':'project')+' survives an earlier refresh response',async()=>{
    const {dom,d,calls,send}=await fixture(source);try{
      d.getElementById('refresh').click();const refresh=calls()[0];
      send({method:'ui/notifications/tool-result',params:{structuredContent:snapshot(project,3)}});await tick();
      send({id:refresh.id,result:{structuredContent:snapshot('A',2)}});await tick();
      assert.equal(d.getElementById('goal').textContent,'Goal '+project);
      assert.equal(d.getElementById('contract-revision').textContent,'3');
      assert.equal(d.getElementById('error').hidden,true);
    }finally{dom.window.close();}
  });
  test(name+': a stale refresh failure does not mark the newer host snapshot as failed',async()=>{
    const {dom,d,calls,send}=await fixture(source);try{
      d.getElementById('refresh').click();const refresh=calls()[0];
      send({method:'ui/notifications/tool-result',params:{structuredContent:snapshot('B')}});await tick();
      send({id:refresh.id,error:{message:'Old request failed'}});await tick();
      assert.equal(d.getElementById('goal').textContent,'Goal B');
      assert.equal(d.getElementById('error').hidden,true);
      assert.match(d.getElementById('connection').textContent,/MCP host snapshot/);
    }finally{dom.window.close();}
  });
  test(name+': only the latest refresh owns results after a host update permits another refresh',async()=>{
    const {dom,d,calls,send}=await fixture(source);try{
      d.getElementById('refresh').click();const first=calls()[0];
      send({method:'ui/notifications/tool-result',params:{structuredContent:snapshot('A',2)}});await tick();
      d.getElementById('refresh').click();const second=calls()[1];
      send({id:first.id,result:{structuredContent:snapshot('A',1)}});await tick();
      assert.equal(d.getElementById('contract-revision').textContent,'2');
      assert.equal(d.getElementById('refresh').disabled,true);
      send({id:second.id,result:{structuredContent:snapshot('A',3)}});await tick();
      assert.equal(d.getElementById('contract-revision').textContent,'3');
      assert.equal(d.getElementById('refresh').disabled,false);
    }finally{dom.window.close();}
  });
  test(name+': unrelated and untrusted messages do not invalidate a current refresh',async()=>{
    const {dom,d,calls,send}=await fixture(source);try{
      d.getElementById('refresh').click();const refresh=calls()[0];
      send({method:'ui/notifications/host-context-changed',params:{theme:'dark'}});
      send({id:'host-ping',method:'ping'});
      send({method:'ui/notifications/unrelated'});
      send({method:'ui/notifications/tool-result',params:{structuredContent:snapshot('FORGED')}},'https://wrong.test');
      send({method:'ui/notifications/tool-result',params:{structuredContent:snapshot('FORGED')}},'https://host.test',dom.window);
      send({id:refresh.id,result:{structuredContent:snapshot('A',2)}});await tick();
      assert.equal(d.getElementById('contract-revision').textContent,'2');
      assert.equal(d.getElementById('goal').textContent,'Goal A');
      assert.equal(d.documentElement.dataset.theme,'dark');
      assert.equal(d.getElementById('refresh').disabled,false);
    }finally{dom.window.close();}
  });
  test(name+': a current failed refresh still warns and a retry succeeds',async()=>{
    const {dom,d,calls,send}=await fixture(source);try{
      d.getElementById('refresh').click();
      send({id:calls()[0].id,error:{message:'Current request failed'}});await tick();
      assert.equal(d.getElementById('error').hidden,false);
      assert.match(d.getElementById('error').textContent,/Current request failed/);
      d.getElementById('refresh').click();
      send({id:calls()[1].id,result:{structuredContent:snapshot('A',2)}});await tick();
      assert.equal(d.getElementById('contract-revision').textContent,'2');
      assert.equal(d.getElementById('error').hidden,true);
    }finally{dom.window.close();}
  });
  test(name+': teardown does not let pending state rejection replace the final view',async()=>{
    const {dom,d,calls,send}=await fixture(source);try{
      d.getElementById('refresh').click();const refresh=calls()[0];
      const before=d.getElementById('connection').textContent;
      send({id:'teardown',method:'ui/resource-teardown'});await tick();
      send({id:refresh.id,result:{structuredContent:snapshot('B')}});await tick();
      assert.equal(d.getElementById('goal').textContent,'Goal A');
      assert.equal(d.getElementById('error').hidden,true);
      assert.equal(d.getElementById('connection').textContent,before);
    }finally{dom.window.close();}
  });
}

const hostedSource=fs.readFileSync(hostedURL,'utf8');
for(const projects of [selection.projects,[]])test('hosted project selection clears the task empty state; projects='+projects.length,async()=>{
  const {dom,d,send}=await fixture(hostedSource);try{
    const filter=d.getElementById('status-filter');filter.value='accepted';
    filter.dispatchEvent(new dom.window.Event('change'));
    assert.equal(d.getElementById('list-empty').hidden,false);
    send({method:'ui/notifications/tool-result',params:{structuredContent:{...selection,projects}}});await tick();
    assert.equal(d.getElementById('goal').textContent,'Choose your project');
    assert.equal(d.getElementById('list-empty').hidden,true);
    assert.equal(d.querySelectorAll('#task-list button').length,projects.length);
    assert.match(d.getElementById('task-detail').textContent,projects.length?/Select an authorized project/:/No authorized projects yet/);
    // The task filter preference returns with task navigation, including its empty state.
    send({method:'ui/notifications/tool-result',params:{structuredContent:snapshot('A')}});await tick();
    assert.equal(filter.value,'accepted');
    assert.equal(d.getElementById('list-empty').hidden,false);
  }finally{dom.window.close();}
});
for(const order of [[1,0],[0,1]])test('hosted project selection: last click wins, response order '+order.join(','),async()=>{
  const {dom,d,calls,send}=await fixture(hostedSource,selection);try{
    const choices=d.querySelectorAll('#task-list button');choices[0].click();choices[1].click();
    assert.deepEqual(calls().map(call=>call.params.arguments.project_key),['a','b']);
    for(const index of order){
      send({id:calls()[index].id,result:{structuredContent:snapshot(index===0?'A':'B')}});await tick();
      assert.notEqual(d.getElementById('goal').textContent,'Goal A','The obsolete A response must not appear even while B is pending');
    }
    assert.equal(d.getElementById('goal').textContent,'Goal B');
  }finally{dom.window.close();}
});
test('hosted project selection: an old failure cannot label the newer project as stale',async()=>{
  const {dom,d,calls,send}=await fixture(hostedSource,selection);try{
    const choices=d.querySelectorAll('#task-list button');choices[0].click();choices[1].click();
    send({id:calls()[1].id,result:{structuredContent:snapshot('B')}});await tick();
    send({id:calls()[0].id,error:{message:'A was revoked'}});await tick();
    assert.equal(d.getElementById('goal').textContent,'Goal B');
    assert.equal(d.getElementById('error').hidden,true);
  }finally{dom.window.close();}
});
test('hosted project selection: a newer host selector invalidates an old selection',async()=>{
  const {dom,d,calls,send}=await fixture(hostedSource,selection);try{
    d.querySelector('#task-list button').click();const old=calls()[0];
    send({method:'ui/notifications/tool-result',params:{structuredContent:{...selection,projects:selection.projects.slice(1)}}});await tick();
    send({id:old.id,result:{structuredContent:snapshot('A')}});await tick();
    assert.equal(d.getElementById('goal').textContent,'Choose your project');
    assert.equal(d.querySelectorAll('#task-list button').length,1);
    assert.equal(d.querySelector('#task-list button').textContent,'Project B · owner');
  }finally{dom.window.close();}
});
test('hosted project selection: a current failure still allows a successful retry',async()=>{
  const {dom,d,calls,send}=await fixture(hostedSource,selection);try{
    d.querySelector('#task-list button').click();
    send({id:calls()[0].id,error:{message:'Current selection failed'}});await tick();
    assert.equal(d.getElementById('error').hidden,false);
    assert.match(d.getElementById('error').textContent,/Current selection failed/);
    d.querySelectorAll('#task-list button')[1].click();
    send({id:calls()[1].id,result:{structuredContent:snapshot('B')}});await tick();
    assert.equal(d.getElementById('goal').textContent,'Goal B');
    assert.equal(d.getElementById('error').hidden,true);
  }finally{dom.window.close();}
});

for(const [name,url] of boards)test(name+': an opt-in receipt cannot replace full board context or imply acceptance',async()=>{
  const {dom,d,send,calls}=await fixture(fs.readFileSync(url,'utf8'));try{
    const receipt={kind:'rumbo.mutation_receipt.v1',complete:false,observation:'operation_response_only',project_id:'A',contract_revision:2,task_id:'task',task_status:'accepted',human_decision_recorded:false,recovery:{tool:'rumbo_state',arguments:{project_key:'a'}}};
    send({method:'ui/notifications/tool-result',params:{structuredContent:receipt}});await tick();
    assert.equal(d.getElementById('goal').textContent,'Goal A');assert.equal(d.getElementById('contract-revision').textContent,'1');
    assert.equal(d.getElementById('accepted-count').textContent,'0');assert.equal(d.getElementById('error').hidden,false);
    assert.match(d.getElementById('error').textContent,/Unsupported or malformed project snapshot/);
    d.getElementById('refresh').click();const refresh=calls().at(-1);
    assert.equal(refresh.params.name,'rumbo_state');assert.equal(Object.hasOwn(refresh.params.arguments,'response_mode'),false);
    send({id:refresh.id,result:{structuredContent:snapshot('A',2)}});await tick();
    assert.equal(d.getElementById('error').hidden,true);assert.equal(d.getElementById('contract-revision').textContent,'2');
  }finally{dom.window.close();}
});

// These recovery cases use the real hosted dispatcher and SQLite-backed storage:
// a synthetic success response must not hide a missing required project_key.
async function hostedRecoveryFixture(projectCount) {
  const f=storageFixture(),projects=[];
  for(let i=0;i<projectCount;i++){
    const project_id='project-'+i;
    projects.push(await f.storage.createProject('owner',project_id,{project_id,
      goal:'Goal '+i,original_request:'Synthetic recovery fixture',
      decision_owner:await subjectActor('owner'),constraints:[],
      tasks:[{id:'task',title:'Task '+i,dependencies:[],acceptance:[{id:'review',kind:'manual_review',prompt:'Inspect synthetic bytes'}]}]}));
  }
  const rpc=message=>dispatch(JSON.parse(JSON.stringify(message)),
    {storage:f.storage,subject:'owner',origin:'https://board.test'});
  const initial=await rpc({jsonrpc:'2.0',id:'initial',method:'tools/call',
    params:{name:'open_project_board',arguments:{}}});
  const board=await fixture(hostedSource,null);
  const changes=()=>f.db.prepare('SELECT total_changes() AS n').get().n;
  return {...board,projects,rpc,initial:initial.result,changes,before:changes(),
    close(){board.dom.window.close();f.db.close();}};
}
for(const projectCount of [0,1,2])for(const initialOrder of ['before','after'])
  test('hosted recovery: early refresh discovers '+projectCount+' authorized projects with initial result '+initialOrder,async()=>{
    const f=await hostedRecoveryFixture(projectCount);try{
      f.d.getElementById('refresh').click();const refresh=f.calls()[0];
      if(initialOrder==='before')f.send({method:'ui/notifications/tool-result',params:f.initial});
      const response=await f.rpc(refresh);
      assert.equal(response.result.isError,false,JSON.stringify(response));
      f.send(response);await tick();
      if(initialOrder==='after'){f.send({method:'ui/notifications/tool-result',params:f.initial});await tick();}
      assert.equal(f.d.getElementById('error').hidden,true);
      assert.equal(f.d.getElementById('refresh').textContent,'Refresh');
      if(projectCount===1){
        assert.equal(f.d.getElementById('goal').textContent,'Goal 0');
        f.d.getElementById('refresh').click();
      }else{
        assert.equal(f.d.getElementById('goal').textContent,'Choose your project');
        assert.equal(f.d.querySelectorAll('#task-list button').length,projectCount);
        if(projectCount===0)assert.match(f.d.getElementById('task-detail').textContent,/No authorized projects yet/);
        else f.d.querySelectorAll('#task-list button')[1].click();
      }
      if(projectCount>0){
        const selected=f.calls().at(-1);
        assert.equal(selected.params.name,'rumbo_state');
        assert.ok(f.projects.some(project=>project.project_key===selected.params.arguments.project_key));
        const result=await f.rpc(selected);assert.equal(result.result.isError,false);
        f.send(result);await tick();assert.equal(f.d.getElementById('error').hidden,true);
        assert.match(f.d.getElementById('goal').textContent,/^Goal [01]$/);
      }
      assert.equal(f.changes(),f.before,'Discovery, selection and refresh must remain read-only');
    }finally{f.close();}
  });
for(const projectCount of [1,2])for(const initialOrder of ['before','after'])
  test('hosted recovery: failed early refresh can retry after suppressed initial '+projectCount+'-project context '+initialOrder,async()=>{
    const f=await hostedRecoveryFixture(projectCount);try{
      f.d.getElementById('refresh').click();const first=f.calls()[0];
      if(initialOrder==='before')f.send({method:'ui/notifications/tool-result',params:f.initial});
      f.send({id:first.id,error:{message:'Synthetic transient host failure'}});await tick();
      if(initialOrder==='after'){f.send({method:'ui/notifications/tool-result',params:f.initial});await tick();}
      assert.equal(f.d.getElementById('error').hidden,false);
      assert.equal(f.d.getElementById('refresh').disabled,false);
      f.d.getElementById('refresh').click();const retry=f.calls().at(-1);
      const response=await f.rpc(retry);
      assert.equal(response.result.isError,false,JSON.stringify(response));
      f.send(response);await tick();
      assert.equal(f.d.getElementById('error').hidden,true);
      assert.equal(f.d.getElementById('refresh').textContent,'Refresh');
      assert.equal(f.d.getElementById('goal').textContent,projectCount===1?'Goal 0':'Choose your project');
      assert.equal(f.changes(),f.before,'Recovery must not mutate project or account state');
    }finally{f.close();}
  });
