/** UI integration checks against a local isolated server and existing free test runs. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const args=process.argv.slice(2),arg=(key,fallback)=>args.includes(key)?args[args.indexOf(key)+1]:fallback;
const base=arg('--url','http://127.0.0.1:8010'),runFile=arg('--runs','artifacts/ui-runs.json');
(async()=>{
 const runs=JSON.parse(await fs.readFile(runFile,'utf8')),browser=await chromium.launch({headless:true});
 const results=[],errors=[];
 try{
 const page=await browser.newPage({viewport:{width:1280,height:800},reducedMotion:'reduce'});
 page.on('pageerror',error=>errors.push(String(error)));
 async function check(name,work){await work();results.push({name,passed:true});console.log('PASS '+name);}
 await check('Retired Delivery links open Operations',async()=>{
  await page.goto(base+'/delivery-lab?run='+runs.flow);
  assert.equal(new URL(page.url()).pathname,'/watch');
  assert.equal(new URL(page.url()).search,'');
  assert.equal(await page.locator('#workspace-navigation a[href="/delivery-lab"]').count(),0);
 });
 await check('Restaurant selection, filters, trace and separate definitions',async()=>{
  await page.goto(base+'/restaurant-lab?run='+runs.supply);
  await page.waitForFunction(()=>document.getElementById('entity-source').textContent.includes('Frozen'));
  assert(await page.locator('#supply-controls').isHidden());
  await page.locator('#supply-agents .roster-role').selectOption('restaurant');
  await page.locator('#supply-agents .roster-search').fill('Pizza Kitchen');
  assert.equal(await page.locator('#supply-agents .roster-row').count(),1);
  assert(await page.locator('#supply-agents .roster-id').innerText());
  await page.locator('#supply-agents .roster-row').first().click();
  assert(await page.locator('#supply-inspector').isVisible());
  assert.equal(await page.locator('#city-map').count(),0);
  assert(await page.locator('#inspection-panel').isVisible());
  const href=await page.locator('#supply-trace-link').getAttribute('href');assert(href.includes('source=supply'));
  await page.locator('#supply-agents .roster-search').fill('no-such-agent');
  assert.equal(await page.locator('#supply-agents .roster-row').count(),0);
  assert((await page.locator('#supply-agents .roster-empty').innerText()).includes('No agents'));
  await page.locator('#supply-simulation').click();
  assert(await page.locator('#supply-controls').isVisible());
  assert(await page.locator('#definition-panel').isVisible());
  await page.locator('#supply-operations').click();
  assert(await page.locator('#supply-controls').isHidden());
  await page.goto(base+href);
  await page.waitForSelector('#live-timeline .timeline-step');
  assert(await page.locator('#live-timeline [data-kind=decision]').count()>0);
  await page.locator('#trace-kind').selectOption('tool');
  assert(await page.locator('#live-timeline [data-kind=tool]').count()>0);
  assert.equal(await page.locator('#live-timeline [data-kind=decision]').count(),0);
  assert.equal(await page.locator('#live-timeline pre:visible').count(),0);
  await page.locator('#live-timeline details summary').first().click();
  assert(await page.locator('#live-timeline pre:visible').count()>0);
 });
 await check('Inventory checkpoint selection and store inspection',async()=>{
  await page.goto(base+'/lab?run='+runs.lab);
  await page.waitForFunction(()=>!document.getElementById('store').disabled);
  assert(await page.locator('#inventory-empty').isHidden());
  assert(await page.locator('#stock tr').count()>0);
  await page.waitForFunction(()=>document.getElementById('checkpoint').options.length>1);
  await page.locator('#checkpoint').selectOption('0');
  assert((await page.locator('#clock').innerText()).includes('checkpoint'));
  const stores=await page.locator('#store option').evaluateAll(options=>options.map(option=>option.value));
  assert(stores.length>1);
  const original=await page.locator('#agent-scope').innerText();
  for (const store of stores) {
   await page.locator('#store').selectOption(store);
   if ((await page.locator('#agent-scope').innerText())!==original) break;
  }
  assert.notEqual(await page.locator('#agent-scope').innerText(),original);
  assert(await page.locator('#stock tr').count()>0);
  assert.equal(await page.locator('#city').count(),0);
 });
 await check('Architecture flow, component links and reduced motion',async()=>{
  await page.goto(base+'/architecture');
  await page.waitForSelector('#document:not([hidden])');
  await page.locator('#request-flow [data-component=postgres]').first().click();
  assert((await page.locator('#component-inspector h3').innerText()).includes('Postgres'));
  const animation=await page.locator('.flow-stage-icon').first().evaluate(el=>getComputedStyle(el).animationName);
  assert.equal(animation,'none');
  const links=await page.locator('#component-inspector a').evaluateAll(nodes=>nodes.map(el=>el.getBoundingClientRect().height));
  assert(links.every(h=>h>=24));
  const diagramBounds=await page.locator('.diagram-render').evaluateAll(nodes=>nodes.map(el=>({height:el.clientHeight,scroll:el.scrollHeight,width:el.clientWidth,scrollWidth:el.scrollWidth})));
  assert(diagramBounds.length>0);
  assert(diagramBounds.every(d=>d.scroll<=d.height+1&&d.scrollWidth<=d.width+1));
  await page.locator('#open-search').click();
  await page.locator('#search-input').fill('memory');
  await page.waitForSelector('#search-results a');
  await page.keyboard.press('Escape');
  await page.locator('#search-dialog').waitFor({state:'hidden'});
 });
 await check('Madrid roster, selection and map after switching views',async()=>{
  await page.goto(base+'/?run='+runs.madrid);
  await page.waitForSelector('.fleet-row');
  await page.waitForFunction(()=>document.getElementById('map').dataset.basemap==='ready');
  assert(await page.evaluate(()=>window.madridBasemap.queryRenderedFeatures().length>100),'Real cartographic features are rendered');
  assert.equal(await page.locator('#order-filter').inputValue(),'all','Completed sessions show recorded orders');
  assert(await page.locator('#orders tr').count()>0);
  await page.locator('#order-search').fill('no-such-order');
  assert(await page.locator('#orders-empty').isVisible());
  await page.locator('#order-search').fill('');
  await page.locator('#agent-role').selectOption('bike');
  await page.locator('.fleet-row').first().click();
  assert(await page.locator('.fleet-row[aria-pressed=true]').count()===1);
  await page.locator('#view-simulation').click();
  await page.locator('#view-operations').click();
  await page.waitForTimeout(300);
  assert(await page.locator('.leaflet-marker-icon').count()>0);
  assert(await page.locator('#map').evaluate(el=>el.clientWidth>100));
  assert((await page.locator('#session-state').innerText()).includes('complete'));
  assert((await page.locator('#history-scope').innerText()).includes('History unavailable'));
  await page.setViewportSize({width:1440,height:960});
  assert(await page.locator('.ledger thead').evaluate(el=>el.getBoundingClientRect().bottom<960),'Order headings remain in the first viewport');
  await page.locator('#open-agent-details').click();
  assert(await page.locator('#agent-details').isVisible());
 });
 await check('All pages fit narrow screens and expose current navigation',async()=>{
  for(const route of ['/','/restaurant-lab','/lab','/health','/agent-traces','/architecture']){
   const run = route === '/restaurant-lab' ? runs.supply : route === '/lab' ? runs.lab : '';
   await page.goto(base+route+(run?'?run='+run:''));
   await page.setViewportSize({width:390,height:844});
   await page.waitForTimeout(300);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,route+' overflow');
   assert.equal(await page.locator('#workspace-shell a[aria-current=page]').count(),1,route+' current navigation');
  }
 });
 assert.deepEqual(errors,[]);
 await fs.mkdir('docs/media/after',{recursive:true});
 await fs.writeFile('docs/media/after/interactions.json',JSON.stringify({results,errors},null,2)+'\n');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
