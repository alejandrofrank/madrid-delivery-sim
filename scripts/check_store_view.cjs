const {chromium}=require('playwright');
const fs=require('node:fs/promises');
const assert=require('node:assert/strict');
const base=process.env.STORE_UI_BASE||'http://localhost:8010';
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--enable-unsafe-swiftshader','--use-angle=swiftshader']});
 const path='artifacts/dark-store';await fs.mkdir(path,{recursive:true});
 const page=await browser.newPage({viewport:{width:1916,height:1244}});
 const errors=[],requests=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
 try{
  await page.goto(base+'/');await page.locator('#store-demo').waitFor();
  assert(!requests.some(r=>r.includes('/simready/')||r.includes('/three/')),'3D must stay lazy');
  await page.locator('#store-demo-chaos').check();
  await page.locator('#store-demo').click();
  await page.waitForFunction(()=>document.querySelector('#store-render-status').textContent.includes('3D cutaway'),{},{timeout:60000});
  // The live inspector changes height while orders advance. Do not wait for the
  // entire container to be stable before scrolling; actual controls remain checked.
  await page.locator('#store-view').evaluate(el=>el.scrollIntoView({behavior:'instant',block:'start'}));
  assert(await page.locator('#store-stage canvas').isVisible());
  assert(!(await page.locator('#store-floor').isVisible()));
  assert.match(await page.locator('#store-order-title').innerText(),/DS-0001/);
  await page.locator('#store-track').uncheck();await page.locator('#store-fit').click();
  await page.screenshot({path:path+'/store-desktop.png',fullPage:false});
  const canvas=page.locator('#store-stage canvas');await canvas.focus();await page.keyboard.press('ArrowLeft');await page.keyboard.press('+');
  const run=new URL(page.url()).searchParams.get('run');assert(run);
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

  // Losing a graphics context must retain the live floor plan and order controls.
  await canvas.dispatchEvent('webglcontextlost');
  await page.locator('#store-floor').waitFor({state:'visible'});
  assert.equal(await page.locator('#store-stage canvas').count(),0);
  await page.locator('#store-back').click();await page.locator('#store-open').click();
  await page.waitForFunction(()=>document.querySelector('#store-render-status').textContent.includes('3D cutaway'));
  await page.locator('#store-follow').click();
  await page.locator('#store-fit').click();
  // Check narrow layout before the basket leaves the building.
  await page.setViewportSize({width:390,height:844});
  // The live inspector changes height while orders advance. Do not wait for the
  // entire container to be stable before scrolling; actual controls remain checked.
  await page.locator('#store-view').evaluate(el=>el.scrollIntoView({behavior:'instant',block:'start'}));
  await page.waitForFunction(()=>{const el=document.querySelector('#store-stage canvas');if(!el?.dataset.overviewBounds)return false;const bounds=JSON.parse(el.dataset.overviewBounds);return bounds.x<=.91&&bounds.y<=.91;});
  await page.screenshot({path:path+'/store-mobile.png',fullPage:false});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert(await page.evaluate(()=>document.querySelector('#store-incident').getBoundingClientRect().bottom<=document.querySelector('.store-footer').getBoundingClientRect().top),'Mobile disruption action must remain above the footer');
  await page.setViewportSize({width:1280,height:900});
  assert(await page.evaluate(()=>document.querySelector('#store-incident').getBoundingClientRect().bottom<=document.querySelector('.store-footer').getBoundingClientRect().top),'Laptop disruption action must remain above the footer');
  await page.setViewportSize({width:1916,height:1244});
  await page.locator('#store-fit').click();
  const fallback=await browser.newPage({viewport:{width:390,height:844},reducedMotion:'reduce'});
  await fallback.goto(base+'/?run='+run+'&store-fallback=1');
  await fallback.locator('#store-open').click();
  await fallback.locator('#store-floor').waitFor({state:'visible'});
  assert.equal(await fallback.locator('#store-stage canvas').count(),0);
  await fallback.screenshot({path:path+'/store-fallback.png'});
  await fallback.locator('#store-back').focus();await fallback.keyboard.press('Escape');
  assert(!(await fallback.locator('#store-view').isVisible()));
  await fallback.close();
  const missing=await browser.newPage();
  await missing.route('**/simready/*.glb',route=>route.abort());
  await missing.goto(base+'/?run='+run);await missing.locator('#store-open').click();
  await missing.getByText('Some models unavailable; simple shapes shown.',{exact:true}).waitFor();
  assert(await missing.locator('#store-stage canvas').isVisible());
  await missing.close();
  // The live order must leave the store through its actual courier handoff.
  await page.waitForFunction(()=>document.querySelector('#store-view').hidden,{},{timeout:180000});
  await page.waitForFunction(()=>document.querySelector('#store-follow-note').textContent.includes('Delivered'),{},{timeout:180000});
  const state=await (await page.request.get(base+'/api/state?run='+run)).json();
  const order=state.orders.find(o=>o.id==='DS-0001');assert.equal(order.status,'delivered');
  const stores=await (await page.request.get(base+'/api/runs/'+run+'/stores')).json();
  assert.equal(stores.stores[0].orders.find(o=>o.order_id==='DS-0001').stage,'handed_off');
  await page.screenshot({path:path+'/store-delivered.png',fullPage:false});
  const trace=await browser.newPage();
  await trace.goto(base+'/agent-traces?source=madrid&run='+run+'&order=DS-0001');
  await trace.getByText('Order DS-0001',{exact:false}).first().waitFor();
  await trace.close();
  assert.deepEqual(errors,[]);
  await fs.writeFile(path+'/browser-checks.json',JSON.stringify({passed:true,run,lazy:true,keyboard:true,mobile:true,fallback:true,delivered:true,shelfSupport:support,workersMoving:true,render:stats,errors},null,2));
  console.log('Store browser checks passed: lazy 3D, keyboard, mobile, fallback, real courier handoff and delivery.');
 }catch(error){
  const detail=await page.evaluate(()=>({url:location.href,stage:document.querySelector('#store-order-state')?.textContent,render:document.querySelector('#store-render-status')?.textContent,view:document.querySelector('#store-view')?.getBoundingClientRect().toJSON(),hidden:document.querySelector('#store-view')?.hidden})).catch(()=>null);
  await fs.writeFile(path+'/browser-failure.json',JSON.stringify({error:String(error),detail},null,2));
  await page.screenshot({path:path+'/browser-failure.png',fullPage:true,timeout:15000}).catch(()=>{});
  throw error;
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
