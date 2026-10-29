/** Records the actual local operations UI. Creates a free local run; never enables AI. */
const {chromium}=require('playwright');
const fs=require('node:fs/promises');
const args=process.argv.slice(2),arg=(key,fallback)=>args.includes(key)?args[args.indexOf(key)+1]:fallback;
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:960},reducedMotion:'no-preference'});
 await page.goto(arg('--url','http://127.0.0.1:8021')+'/');
 await page.waitForSelector('.fleet-row');
 await page.locator('#view-simulation').click();
 await page.locator('#duration').selectOption('60');
 if(await page.locator('#start').isEnabled()) await page.locator('#start').click();
 else await page.locator('#view-operations').click();
 await page.waitForFunction(()=>!document.getElementById('operations-panel').hidden);
 await page.waitForTimeout(2500);
 const working=page.locator('.fleet-row:has(.status-pill.working)');
 if(await working.count())await working.first().click();else await page.locator('.fleet-row').first().click();
 await page.evaluate(()=>window.scrollTo(0,0));
 const out=arg('--out','artifacts/ui-demo-frames');await fs.mkdir(out,{recursive:true});
 const start=Date.now();
 for(let i=0;i<48;i++){
  if(i===24&&await working.count()>1)await working.nth(1).click();
  await page.screenshot({path:out+'/frame-'+String(i).padStart(3,'0')+'.png'});
  await page.waitForTimeout(120);
 }
 await fs.writeFile(out+'/metadata.json',JSON.stringify({capturedAt:new Date().toISOString(),source:'Actual running local UI, deterministic simulation, no paid calls',frames:48,durationMs:Date.now()-start,viewport:{width:1440,height:960}},null,2));
 console.log('Recorded 48 actual UI frames in '+out);
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
