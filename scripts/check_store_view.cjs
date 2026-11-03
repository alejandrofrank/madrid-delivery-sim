const {chromium}=require('playwright');
const fs=require('node:fs/promises');
const assert=require('node:assert/strict');
const base=process.env.STORE_UI_BASE||'http://localhost:8010';
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--enable-unsafe-swiftshader','--use-angle=swiftshader']});
 const path='artifacts/dark-store';await fs.mkdir(path,{recursive:true});
 const page=await browser.newPage({viewport:{width:1916,height:1244}});
 // CI asserts rendered geometry and behavior. Routine screenshots are local
 // review evidence, not image comparisons; software-GPU readback can stall CI.
 const capture=(tab,options)=>process.env.CI?Promise.resolve():tab.screenshot(options);
 let checking=page;
 const errors=[],requests=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
 try{
  await page.goto(base+'/engineers/operations?live=1');await page.locator('#store-demo').waitFor();
  assert(!requests.some(r=>r.includes('/simready/')||r.includes('/three/')),'3D must stay lazy');
  await page.locator('#store-demo-chaos').check();
  // Give the inspection run time to show real motion on software GPUs. Its
  // business clock still advances normally; only the supported playback rate changes.
  await page.route('**/api/stores/demo',async route=>{
   const body=route.request().postDataJSON();assert.equal(body.wall_seconds,60);
   await route.continue({postData:JSON.stringify({...body,wall_seconds:300})});
  },{times:1});
  await page.locator('#store-demo').click();
  // Inspect without automatic camera departure; a separate fresh run below
  // verifies live handoff. Screenshots must not race a successful delivery.
  await page.locator('#store-follow[aria-pressed="true"]').click();
  await page.waitForFunction(()=>document.querySelector('#store-render-status').textContent.includes('3D cutaway'),{},{timeout:60000});
  // The live inspector changes height while orders advance. Do not wait for the
  // entire container to be stable before scrolling; actual controls remain checked.
  await page.locator('#store-view').evaluate(el=>el.scrollIntoView({behavior:'instant',block:'start'}));
  assert(await page.locator('#store-stage canvas').isVisible());
  assert(!(await page.locator('#store-floor').isVisible()));
  assert.match(await page.locator('#store-order-title').innerText(),/DS-0001/);
  await page.locator('#store-track').uncheck();await page.locator('#store-fit').click();
  const canvas=page.locator('#store-stage canvas');
  const inspectionRun=new URL(page.url()).searchParams.get('run');assert(inspectionRun);
  await page.waitForFunction(()=>Number(document.querySelector('#store-stage canvas')?.dataset.drawCalls)>0);
  const stats=await canvas.evaluate(el=>({calls:Number(el.dataset.drawCalls),triangles:Number(el.dataset.triangles)}));
  assert(stats.calls<100,'Repeated shelves must be batched for laptop GPUs: '+JSON.stringify(stats));
  assert(stats.triangles<1000000);
  const support=JSON.parse(await canvas.getAttribute('data-shelf-support'));
  assert.equal(support.slots,120);assert.equal(support.errors,0,'Stock must fit inside real rack geometry');
  assert(support.maxGap<.01,'Product bottoms must touch the visible deck');
  assert.equal(await page.locator('.store-worker-label').count(),3);
  const initialWorkers=await page.locator('.store-worker-label').evaluateAll(rows=>Object.fromEntries(rows.map(r=>[r.dataset.worker,[r.dataset.x,r.dataset.z]])));
  await page.waitForFunction(before=>[...document.querySelectorAll('.store-worker-label')].some(r=>r.dataset.state==='working'&&JSON.stringify(before[r.dataset.worker])!==JSON.stringify([r.dataset.x,r.dataset.z])),initialWorkers,{timeout:30000});
  const workerLabel=page.locator('.store-worker-label').first();
  await workerLabel.focus();await page.keyboard.press('Enter');
  assert.equal(await workerLabel.getAttribute('aria-pressed'),'true');
  await page.locator('#store-fit').click();
  await capture(page,{path:path+'/store-desktop.png',fullPage:false});
  await canvas.focus();await page.keyboard.press('ArrowLeft');await page.keyboard.press('+');

  // Losing a graphics context must retain the live floor plan and order controls.
  await canvas.dispatchEvent('webglcontextlost');
  await page.locator('#store-floor').waitFor({state:'visible'});
  assert.equal(await page.locator('#store-stage canvas').count(),0);
  await page.locator('#store-back').click();await page.locator('#store-open').click();
  await page.waitForFunction(()=>document.querySelector('#store-render-status').textContent.includes('3D cutaway'));
  await page.locator('#store-fit').click();
  // Responsive inspection remains valid after the basket leaves the building.
  await page.setViewportSize({width:390,height:844});
  // The live inspector changes height while orders advance. Do not wait for the
  // entire container to be stable before scrolling; actual controls remain checked.
  await page.locator('#store-view').evaluate(el=>el.scrollIntoView({behavior:'instant',block:'start'}));
  await page.waitForFunction(()=>{const el=document.querySelector('#store-stage canvas');if(!el?.dataset.overviewBounds)return false;const bounds=JSON.parse(el.dataset.overviewBounds);return bounds.x<=.91&&bounds.y<=.91;});
  await capture(page,{path:path+'/store-mobile.png',fullPage:false});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert(await page.evaluate(()=>document.querySelector('#store-incident').getBoundingClientRect().bottom<=document.querySelector('.store-footer').getBoundingClientRect().top),'Mobile disruption action must remain above the footer');
  await page.setViewportSize({width:1280,height:900});
  assert(await page.evaluate(()=>document.querySelector('#store-incident').getBoundingClientRect().bottom<=document.querySelector('.store-footer').getBoundingClientRect().top),'Laptop disruption action must remain above the footer');
  await page.setViewportSize({width:1916,height:1244});
  await page.locator('#store-fit').click();
  // Dispose the completed 3D inspection before opening another page. Keeping
  // its software renderer active can starve the fallback page's initialization
  // on CI, leaving Open store disabled even though the API is healthy.
  await page.locator('#store-back').click();
  const fallback=await browser.newPage({viewport:{width:390,height:844},reducedMotion:'reduce'});
  checking=fallback;
  await fallback.goto(base+'/?run='+inspectionRun+'&store-fallback=1');
  await fallback.locator('#store-open').click();
  await fallback.locator('#store-floor').waitFor({state:'visible'});
  assert.equal(await fallback.locator('#store-stage canvas').count(),0);
  await capture(fallback,{path:path+'/store-fallback.png'});
  await fallback.locator('#store-back').focus();await fallback.keyboard.press('Escape');
  assert(!(await fallback.locator('#store-view').isVisible()));
  await fallback.close();
  const missing=await browser.newPage();checking=missing;
  await missing.route('**/simready/*.glb',route=>route.abort());
  await missing.goto(base+'/?run='+inspectionRun);await missing.locator('#store-open').click();
  await missing.getByText('Some models unavailable; simple shapes shown.',{exact:true}).waitFor();
  assert(await missing.locator('#store-stage canvas').isVisible());
  await missing.close();checking=page;
  // A separate, untouched 60-second demo checks automatic handoff. All heavy
  // screenshots and resizing are finished before following this fresh live order.
  // Hold an old run response across selection of the new run. It must not
  // reset order following or replace the newly selected run's store data.
  const oldPending=page.waitForRequest(request=>request.url()===base+'/api/state?run='+inspectionRun);
  let releaseOld;
  const holdOld=new Promise(resolve=>{releaseOld=resolve;});
  await page.route('**/api/state?run='+inspectionRun,async route=>{
   const response=await route.fetch();await holdOld;
   await route.fulfill({response});
  },{times:1});
  await oldPending;
  const started=page.waitForResponse(response=>response.url().endsWith('/api/stores/demo')&&response.request().method()==='POST');
  await page.locator('#store-demo').click();await started;releaseOld();
  await page.locator('#store-follow[aria-pressed="true"]').waitFor();
  const run=new URL(page.url()).searchParams.get('run');assert(run&&run!==inspectionRun);
  const beforeHandoff=await (await page.request.get(base+'/api/runs/'+run+'/stores')).json();
  assert.notEqual(beforeHandoff.stores[0].orders.find(o=>o.order_id==='DS-0001').stage,'handed_off');
  // The live order must leave the store through its actual courier handoff.
  await page.waitForFunction(()=>document.querySelector('#store-view').hidden,{},{timeout:180000});
  await page.waitForFunction(()=>document.querySelector('#store-follow-note').textContent.includes('Delivered'),{},{timeout:180000});
  const state=await (await page.request.get(base+'/api/state?run='+run)).json();
  const order=state.orders.find(o=>o.id==='DS-0001');assert.equal(order.status,'delivered');
  const stores=await (await page.request.get(base+'/api/runs/'+run+'/stores')).json();
  assert.equal(stores.stores[0].orders.find(o=>o.order_id==='DS-0001').stage,'handed_off');
  if(await page.locator('#chaos-panel').getAttribute('open')===null)await page.locator('#chaos-panel > summary').click();
  await page.locator('#chaos-timeline').getByText('Robot breakdown',{exact:true}).first().waitFor();
  const timeline=await page.locator('#chaos-timeline').innerText();
  assert(timeline.includes('Robot breakdown'),'Store incidents must have readable city timeline labels');
  assert(!timeline.includes('undefined'));
  await capture(page,{path:path+'/store-delivered.png',fullPage:false});
  const trace=await browser.newPage();checking=trace;
  await trace.goto(base+'/agent-traces?source=madrid&run='+run+'&order=DS-0001');
  await trace.getByText('Order DS-0001',{exact:false}).first().waitFor();
  await trace.close();checking=page;
  assert.deepEqual(errors,[]);
  await fs.writeFile(path+'/browser-checks.json',JSON.stringify({passed:true,run,inspectionRun,lazy:true,keyboard:true,mobile:true,fallback:true,delivered:true,shelfSupport:support,workersMoving:true,render:stats,errors},null,2));
  console.log('Store browser checks passed: lazy 3D, keyboard, mobile, fallback, real courier handoff and delivery.');
 }catch(error){
  const detail=await checking.evaluate(()=>({url:location.href,connection:document.querySelector('#connection-text')?.textContent,storeOptions:document.querySelector('#store-select')?.textContent,stage:document.querySelector('#store-order-state')?.textContent,render:document.querySelector('#store-render-status')?.textContent,view:document.querySelector('#store-view')?.getBoundingClientRect().toJSON(),hidden:document.querySelector('#store-view')?.hidden})).catch(()=>null);
  await fs.writeFile(path+'/browser-failure.json',JSON.stringify({error:String(error),detail},null,2));
  await checking.screenshot({path:path+'/browser-failure.png',fullPage:true,timeout:15000}).catch(()=>{});
  throw error;
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
