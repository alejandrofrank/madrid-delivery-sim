/** UI integration checks against a local isolated server and existing free test runs. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const args=process.argv.slice(2),arg=(key,fallback)=>args.includes(key)?args[args.indexOf(key)+1]:fallback;
const base=arg('--url','http://127.0.0.1:8021'),runFile=arg('--runs','artifacts/ui-runs.json');
(async()=>{
 const runs=JSON.parse(await fs.readFile(runFile,'utf8')),browser=await chromium.launch({headless:true});
 const results=[],errors=[];
 try{
 const page=await browser.newPage({viewport:{width:1280,height:800},reducedMotion:'reduce'});
 page.on('pageerror',error=>errors.push(String(error)));
 async function check(name,work){await work();results.push({name,passed:true});console.log('PASS '+name);}
 await check('Delivery roster filters, map selection and trace navigation',async()=>{
  await page.goto(base+'/delivery-lab?run='+runs.flow);
  await page.waitForFunction(()=>window.deliverySnapshot?.run?.status);
  await page.locator('#live-agents .roster-role').selectOption('inventory');
  await page.locator('#live-agents .roster-row').first().click();
  await page.waitForFunction(()=>document.getElementById('context').hidden===false);
  assert(await page.locator('#agent-content').textContent());
  const href=await page.locator('#agent-trace-link').getAttribute('href');
  assert(href.includes('source=delivery'));
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
 await check('Restaurant selection, filters, trace and separate definitions',async()=>{
  await page.goto(base+'/restaurant-lab?run='+runs.supply);
  await page.waitForFunction(()=>document.getElementById('map-source').textContent.includes('Frozen'));
  assert(await page.locator('#supply-controls').isHidden());
  await page.locator('#supply-agents .roster-role').selectOption('restaurant');
  await page.locator('#supply-agents .roster-row').first().click();
  assert(await page.locator('#supply-inspector').isVisible());
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
 });
 await check('Inventory checkpoint selection and store inspection',async()=>{
  await page.goto(base+'/lab?run='+runs.lab);
  await page.waitForFunction(()=>!document.getElementById('store').disabled);
  assert(await page.locator('#inventory-empty').isHidden());
  assert(await page.locator('#stock tr').count()>0);
  await page.waitForFunction(()=>document.getElementById('checkpoint').options.length>1);
  await page.locator('#checkpoint').selectOption('0');
  assert((await page.locator('#clock').innerText()).includes('checkpoint'));
  assert(await page.locator('#city g[role=button]').count()>0);
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
  await page.locator('#open-search').click();
  await page.locator('#search-input').fill('memory');
  await page.waitForSelector('#search-results a');
  await page.keyboard.press('Escape');
  await page.locator('#search-dialog').waitFor({state:'hidden'});
 });
 await check('Madrid roster, selection and map after switching views',async()=>{
  await page.goto(base+'/?run='+runs.madrid);
  await page.waitForSelector('.fleet-row');
  await page.locator('#agent-role').selectOption('bike');
  await page.locator('.fleet-row').first().click();
  assert(await page.locator('.fleet-row[aria-pressed=true]').count()===1);
  await page.locator('#view-simulation').click();
  await page.locator('#view-operations').click();
  await page.waitForTimeout(300);
  assert(await page.locator('.leaflet-marker-icon').count()>0);
  assert(await page.locator('#map').evaluate(el=>el.clientWidth>100));
  await page.locator('#open-agent-details').click();
  assert(await page.locator('#agent-details').isVisible());
 });
 await check('All pages fit narrow screens and expose current navigation',async()=>{
  for(const route of ['/','/delivery-lab','/restaurant-lab','/lab','/health','/agent-traces','/architecture']){
   await page.goto(base+route);
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
