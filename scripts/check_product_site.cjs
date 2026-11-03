/* Browser contracts for the public story and the shared product shell. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const args=process.argv.slice(2),arg=(name,fallback)=>args.includes(name)?args[args.indexOf(name)+1]:fallback;
const base=arg('--url','http://127.0.0.1:8010'),out=arg('--output','artifacts/product-check');
(async()=>{
 await fs.mkdir(out,{recursive:true});const browser=await chromium.launch({headless:true});const checks=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],apiCalls=[];
  page.on('pageerror',e=>errors.push(String(e)));page.on('request',r=>{if(new URL(r.url()).pathname.startsWith('/api/'))apiCalls.push(r.url());});
  await page.goto(base+'/');await page.waitForSelector('#story-robots canvas');await page.waitForFunction(()=>Number(document.getElementById('story-canvas').dataset.simTime)>1440);
  assert.equal(await page.locator('#workspace-navigation a').count(),3);assert.equal(apiCalls.length,0);
  await page.waitForTimeout(600);const work=await page.locator('#story-canvas').evaluate(c=>({draws:Number(c.dataset.draws),routes:Number(c.dataset.routeBuilds)}));assert(work.draws>work.routes*3,'Route geometry is cached between recorded snapshots');
  await page.getByRole('button',{name:'Pause recorded shift',exact:true}).click();
  const time=await page.locator('#story-canvas').getAttribute('data-sim-time');await page.waitForTimeout(300);assert.equal(await page.locator('#story-canvas').getAttribute('data-sim-time'),time);
  await page.screenshot({path:out+'/landing-desktop.png'});checks.push('recorded map, real robot models, three destinations, no API requests, pause');
  await page.getByRole('button',{name:'Play recorded shift',exact:true}).click();
  await page.locator('.workspace-footer').scrollIntoViewIfNeeded();await page.waitForTimeout(200);
  const hiddenTime=await page.locator('#story-canvas').getAttribute('data-sim-time');await page.waitForTimeout(300);assert.equal(await page.locator('#story-canvas').getAttribute('data-sim-time'),hiddenTime);checks.push('offscreen playback stops');
  await page.evaluate(()=>scrollTo(0,0));await page.getByRole('button',{name:'Use dark appearance',exact:true}).click();assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');
  await page.screenshot({path:out+'/landing-dark.png'});await page.reload();assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');await page.getByRole('button',{name:'Use light appearance',exact:true}).click();checks.push('theme persists');
  await page.setViewportSize({width:390,height:844});await page.reload();await page.waitForSelector('#story-robots canvas');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.getByRole('button',{name:'Open navigation',exact:true}).click();assert(await page.getByRole('link',{name:'Watch it live',exact:true}).isVisible());
  await page.keyboard.press('Escape');assert.equal(await page.getByRole('button',{name:'Open navigation',exact:true}).getAttribute('aria-expanded'),'false');
  await page.screenshot({path:out+'/landing-mobile.png'});checks.push('mobile fits and keyboard menu closes');
  const still=await browser.newPage({viewport:{width:1280,height:800},reducedMotion:'reduce'});await still.goto(base+'/');await still.waitForFunction(()=>document.getElementById('story-canvas').dataset.simTime);
  const stillTime=await still.locator('#story-canvas').getAttribute('data-sim-time');await still.waitForTimeout(350);assert.equal(await still.locator('#story-canvas').getAttribute('data-sim-time'),stillTime);checks.push('reduced motion uses a still frame');await still.close();
  const fallback=await browser.newPage();await fallback.route('**/landing-robots.js*',r=>r.abort());await fallback.goto(base+'/');await fallback.waitForFunction(()=>document.getElementById('story-handoff').hidden);assert(await fallback.locator('#story-canvas').isVisible());checks.push('robot asset failure leaves the recorded map usable');await fallback.close();
  await page.setViewportSize({width:1440,height:1000});
  for(const path of ['/watch','/agents','/engineers/operations','/engineers/restaurants','/engineers/inventory','/engineers/health','/engineers/traces','/engineers/architecture']){
   await page.goto(base+path);await page.waitForSelector('.workspace-header');assert.equal(await page.locator('#workspace-navigation a').count(),3);assert.equal(await page.locator('.workspace-environment').count(),new URL(page.url()).pathname.startsWith('/engineers/')?1:0);
   assert.equal(await page.locator('.workspace-engineer-links a[href="/engineers/inventory"]').count(),1);assert.equal(await page.getByRole('link',{name:'Operations',exact:true}).count(),0);
  }
  checks.push('every workspace keeps the shared header and environment stays in engineer pages');assert.deepEqual(errors,[]);
  await fs.writeFile(out+'/results.json',JSON.stringify({passed:true,checks},null,2));console.log(checks.map(x=>'PASS '+x).join('\n'));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
