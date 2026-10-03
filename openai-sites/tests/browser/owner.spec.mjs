import {test,expect} from '@playwright/test';
async function create(page,alias){await page.goto('/');await expect(page.locator('#identity')).toContainText('Owner ID:');const me=await (await page.request.get('/api/me')).json();const contract={project_id:alias,goal:'Ship exact synthetic artifact',original_request:'Synthetic browser test only',decision_owner:me.actor,constraints:['No external effects'],tasks:[{id:'one',title:'Synthetic output',dependencies:[],acceptance:[{id:'contains',kind:'file_contains',value:'hello'}]}]};await page.getByText('Create or revise a contract',{exact:true}).click();await page.locator('#contract').fill(JSON.stringify(contract));await page.locator('#create').click();await expect(page.locator('#confirmation')).toBeVisible();await expect(page.locator('#confirm-submit')).toBeEnabled();await page.locator('#confirm-submit').click();await expect(page.locator('#goal')).toHaveText(contract.goal);return (await (await page.request.get('/api/projects')).json()).projects.find(p=>p.alias===alias).project_key;}
async function call(page,name,args){const r=await page.request.post('/mcp',{data:{jsonrpc:'2.0',id:1,method:'tools/call',params:{name,arguments:args}}});expect(r.ok()).toBeTruthy();const value=await r.json();expect(value.result?.isError,JSON.stringify(value)).toBe(false);return value.result.structuredContent;}
test('owner cancels, retries, inspects exact bytes and accepts only the checked revision',async({page})=>{
 const key=await create(page,'browser-main');const session=await call(page,'rumbo_open_worker',{project_key:key,label:'browser test maker'}),args={project_key:key,worker_id:session.worker_id};
 await call(page,'rumbo_claim_task',{...args,task_id:'one',contract_revision:1,lease_seconds:300});await call(page,'rumbo_ingest_artifact',{...args,task_id:'one',contract_revision:1,filename:'test.txt',content:'hello <script>window.bad=true</script>'});await call(page,'rumbo_run_checks',{...args,task_id:'one',contract_revision:1,artifact_revision:1});
 await page.locator('#refresh').click();await page.getByRole('button',{name:'Inspect exact bytes'}).click();await expect(page.locator('#artifact-text')).toHaveText('hello <script>window.bad=true</script>');expect(await page.evaluate(()=>window.bad)).toBeUndefined();await page.locator('#decision-reason').fill('Owner inspected synthetic bytes');await page.locator('#accept').click();await page.getByRole('button',{name:'Cancel',exact:true}).click();await expect(page.locator('#decision-reason')).toHaveValue('Owner inspected synthetic bytes');
 await page.locator('#accept').click();await page.locator('#confirm-submit').click();await expect(page.locator('#tasks')).toContainText('accepted');await page.screenshot({path:'qa-artifacts/owner-accepted-desktop.png',fullPage:true});
 const download=page.waitForEvent('download');await page.locator('#export').click();expect((await download).suggestedFilename()).toBe('rumbo-browser-main-export.ndjson');
 await page.goto('/board?project_key='+key);await expect(page.locator('#goal')).toHaveText('Ship exact synthetic artifact');await expect(page.locator('#accepted-count')).toHaveText('1');await page.locator('#status-filter').selectOption('attention');await expect(page.locator('#list-empty')).toHaveText('No tasks match this filter');await page.screenshot({path:'qa-artifacts/board-filter-desktop.png',fullPage:true});
});
test('mobile owner layout keeps controls in bounds and preserves invalid drafts',async({page})=>{
 await page.setViewportSize({width:390,height:844});await create(page,'browser-mobile');await page.locator('#contract').fill('{invalid');await page.locator('#create').click();await expect(page.locator('#message')).toContainText('draft has been kept');await expect(page.locator('#contract')).toHaveValue('{invalid');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:'qa-artifacts/owner-mobile-error.png',fullPage:true});
});

test('Escape after an earlier confirmation cancels a revision without writing',async({page})=>{
 const key=await create(page,'browser-escape');await page.locator('#change-reason').fill('This revision is canceled');
 await page.locator('#revise').click();await expect(page.locator('#confirmation')).toBeVisible();await page.keyboard.press('Escape');
 await expect(page.locator('#confirmation')).not.toBeVisible();await expect(page.locator('#revise')).toBeEnabled();
 const state=await (await page.request.get('/api/state?project_key='+key)).json();expect(state.contract_revision).toBe(1);
 await expect(page.locator('#change-reason')).toHaveValue('This revision is canceled');
});
test('new project selection survives reload and interrupted refresh recovers cleanly',async({page})=>{
 const key=await create(page,'browser-reload');await expect(page).toHaveURL(new RegExp('project_key='+key));
 await page.reload();await expect(page.locator('#projects')).toHaveValue(key);await expect(page.locator('#goal')).toHaveText('Ship exact synthetic artifact');
 await page.route('**/api/state?*',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Synthetic interrupted refresh'})}));
 await page.locator('#refresh').click();await expect(page.locator('#message')).toContainText('Synthetic interrupted refresh');await expect(page.locator('#project-panel')).not.toBeVisible();
 await page.getByText('Create or revise a contract',{exact:true}).click();await page.locator('#change-reason').fill('Draft survives a failed refresh');await page.locator('#revise').click();await expect(page.locator('#message')).toContainText('Choose a project first');await expect(page.locator('#confirmation')).not.toBeVisible();
 await page.unroute('**/api/state?*');await page.locator('#refresh').click();await expect(page.locator('#goal')).toHaveText('Ship exact synthetic artifact');await expect(page.locator('#change-reason')).toHaveValue('Draft survives a failed refresh');
});

test('failed project switch hides old context and retry loads the selected project',async({page})=>{
 const first=await create(page,'browser-switch-first'),second=await create(page,'browser-switch-second');
 await page.route('**/api/state?project_key='+first,route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Synthetic failed project switch'})}));
 await page.locator('#projects').selectOption(first);await expect(page.locator('#message')).toContainText('Synthetic failed project switch');await expect(page.locator('#project-panel')).not.toBeVisible();await expect(page.locator('#projects')).toHaveValue(first);
 await page.locator('#change-reason').fill('Preserved retry draft');await page.locator('#revise').click();await expect(page.locator('#confirmation')).not.toBeVisible();await expect(page.locator('#message')).toContainText('Choose a project first');
 await page.unroute('**/api/state?project_key='+first);await page.locator('#refresh').click();await expect(page.locator('#project-panel')).toBeVisible();await expect(page.locator('#board-link')).toHaveAttribute('href','/board?project_key='+first);await expect(page.locator('#change-reason')).toHaveValue('Preserved retry draft');
 expect((await (await page.request.get('/api/state?project_key='+second)).json()).contract_revision).toBe(1);
});
test('project picker stays disabled during refresh without stealing a newer input focus',async({page})=>{
 await create(page,'browser-pending');let release,entered;const pending=new Promise(r=>entered=r),gate=new Promise(r=>release=r);
 await page.route('**/api/state?*',async route=>{entered();await gate;await route.continue();});
 await page.locator('#refresh').click();await pending;try{await expect(page.locator('#projects')).toBeDisabled();await page.locator('#contract').focus();}finally{release();}
 await expect(page.locator('#projects')).toBeEnabled();await expect(page.locator('#project-panel')).toBeVisible();await expect(page.locator('#contract')).toBeFocused();
});

test('keyboard focus returns to the initiating control after Cancel and native Escape',async({page})=>{
 await create(page,'browser-focus-cancel');await page.locator('#change-reason').fill('Keep this revision draft');
 const trigger=page.locator('#revise');
 await page.evaluate(()=>{window.dialogFocusTrace=[];const record=phase=>{const active=document.activeElement;window.dialogFocusTrace.push({phase,tag:active?.tagName,id:active?.id,text:active?.textContent?.slice(0,40),dialogOpen:active?.closest('dialog')?.open});};document.getElementById('confirmation').addEventListener('close',()=>{record('close');queueMicrotask(()=>{record('close microtask');queueMicrotask(()=>record('settled microtask'));});setTimeout(()=>record('close timeout'),0);});});
 for(const cancel of ['button','escape']){
  await page.locator('#change-reason').focus();await page.keyboard.press('Tab');await page.keyboard.press('Tab');await expect(trigger).toBeFocused();
  await page.keyboard.press('Enter');await expect(page.locator('#confirmation')).toBeVisible();
  await expect(page.getByRole('button',{name:'Cancel',exact:true})).toBeFocused();
  if(cancel==='escape')await page.keyboard.press('Escape');else await page.keyboard.press('Enter');
  await expect(page.locator('#confirmation')).not.toBeVisible();await expect(trigger).toBeEnabled();
  const focus=await page.evaluate(()=>{const active=document.activeElement,dialog=active?.closest('dialog');return {tag:active?.tagName,id:active?.id,text:active?.textContent?.slice(0,100),visible:active?.checkVisibility(),dialog:dialog?.id,dialogOpen:dialog?.open,trace:window.dialogFocusTrace};});
  await expect(trigger,'Focus after '+cancel+': '+JSON.stringify(focus)).toBeFocused();
 }
 await expect(page.locator('#change-reason')).toHaveValue('Keep this revision draft');
});

test('keyboard focus recovers after failed refresh and successful retry',async({page})=>{
 await create(page,'browser-focus-retry');const trigger=page.locator('#refresh');
 await page.route('**/api/state?*',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Synthetic keyboard retry'})}));
 await page.locator('#projects').focus();await page.keyboard.press('Tab');await expect(trigger).toBeFocused();
 await page.keyboard.press('Enter');await expect(page.locator('#message')).toContainText('Synthetic keyboard retry');
 await expect(trigger).toBeEnabled();await expect(trigger).toBeFocused();
 await page.unroute('**/api/state?*');await page.keyboard.press('Enter');
 await expect(page.locator('#project-panel')).toBeVisible();await expect(trigger).toBeEnabled();await expect(trigger).toBeFocused();
});

for(const outcome of ['accept','reject'])test('keyboard '+outcome+' recovers focus on the project when its decision panel is hidden',async({page})=>{
 const key=await create(page,'browser-focus-'+outcome),session=await call(page,'rumbo_open_worker',{project_key:key,label:'keyboard decision test'}),args={project_key:key,worker_id:session.worker_id};
 await call(page,'rumbo_claim_task',{...args,task_id:'one',contract_revision:1,lease_seconds:300});await call(page,'rumbo_ingest_artifact',{...args,task_id:'one',contract_revision:1,filename:'keyboard.txt',content:'hello keyboard'});await call(page,'rumbo_run_checks',{...args,task_id:'one',contract_revision:1,artifact_revision:1});
 await page.locator('#refresh').click();await page.getByRole('button',{name:'Inspect exact bytes'}).click();await page.locator('#decision-reason').fill('Keyboard-reviewed exact bytes');
 await page.keyboard.press('Tab');if(outcome==='reject')await page.keyboard.press('Tab');await expect(page.locator('#'+outcome)).toBeFocused();await page.keyboard.press('Enter');
 await expect(page.locator('#confirmation')).toBeVisible();await page.keyboard.press('Tab');await expect(page.locator('#confirm-submit')).toBeFocused();await page.keyboard.press('Enter');
 await expect(page.locator('#artifact-panel')).not.toBeVisible();await expect(page.locator('#tasks')).toContainText(outcome==='accept'?'accepted':'rejected');await expect(page.locator('#goal')).toBeFocused();await expect(page.locator('#goal')).toHaveAttribute('tabindex','-1');
});
