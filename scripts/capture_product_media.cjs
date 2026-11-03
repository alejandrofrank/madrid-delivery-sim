/* Capture actual local product pages; no synthesized UI or data. */
const {chromium}=require('playwright'),fs=require('node:fs/promises'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--enable-unsafe-swiftshader','--use-angle=swiftshader']});
 const out='.impeccable/review',media='docs/media',frames='artifacts/product-frames';
 await Promise.all([out,media,frames].map(p=>fs.mkdir(p,{recursive:true})));
 const page=await browser.newPage({viewport:{width:1487,height:1058},reducedMotion:'reduce'});
 await page.addInitScript(()=>localStorage.setItem('mds-anatomy-tour-v1','seen'));
 try{
  await page.goto('http://localhost:8010/');await page.waitForSelector('#story-robots canvas');await page.evaluate(()=>document.fonts.ready);
  await page.screenshot({path:out+'/product-desktop.png',fullPage:true});await page.screenshot({path:out+'/product-comp.png'});
  await page.screenshot({path:media+'/product-story.png'});
  await page.setViewportSize({width:1916,height:1244});await page.screenshot({path:out+'/product-user-1916.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:out+'/product-mobile.png',fullPage:true});
  const paths={watch:'/watch',agents:'/agents',inventory:'/engineers/inventory',restaurants:'/engineers/restaurants',traces:'/engineers/traces',health:'/engineers/health',chapters:'/engineers/architecture'};
  for(const [name,path] of Object.entries(paths)){
   for(const [size,viewport] of Object.entries({desktop:{width:1440,height:1000},mobile:{width:390,height:844}})){
    await page.setViewportSize(viewport);await page.goto('http://localhost:8010'+path);await page.waitForTimeout(300);
    if(name==='agents')await page.waitForSelector('.delivery-scene-canvas',{timeout:60000});
    else if(name==='watch'){await page.waitForSelector('#fleet .fleet-row');await page.waitForFunction(()=>document.getElementById('map').dataset.basemap==='ready');await page.waitForTimeout(600);}
    else if(name==='inventory'||name==='restaurants')await page.waitForSelector('#recorded-example-banner');
    else if(name==='traces')await page.waitForSelector('#live-timeline .timeline-step');
    else if(name==='chapters')await page.waitForSelector('#chapter-body h2',{timeout:60000});
    else await page.waitForFunction(()=>!document.body.innerText.includes('Loading local evidence'),{},{timeout:60000});
    await page.evaluate(()=>document.fonts.ready);
    const skip=page.getByRole('button',{name:'Skip tour',exact:true});if(await skip.isVisible())await skip.click();
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),name+' '+size+' overflows');
    await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:out+'/product-'+name+'-'+size+'.png'});
   }
  }
  await page.setViewportSize({width:1440,height:1000});await page.goto('http://localhost:8010/');await page.getByRole('button',{name:'Use dark appearance'}).click();await page.waitForSelector('#story-robots canvas');await page.screenshot({path:out+'/product-dark.png',fullPage:true});
  await page.getByRole('button',{name:'Use light appearance'}).click();
  const motion=await browser.newPage({viewport:{width:1000,height:760}});await motion.goto('http://localhost:8010/');await motion.waitForSelector('#story-robots canvas');
  for(let i=0;i<30;i++){await motion.screenshot({path:frames+'/'+String(i).padStart(3,'0')+'.png'});await motion.waitForTimeout(200);}
  await motion.locator('.story-flow').scrollIntoViewIfNeeded();await motion.waitForTimeout(900);
  await motion.screenshot({path:frames+'/030.png'});await motion.close();
  console.log('Captured product pages, mobile layouts, dark appearance and real replay frames');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
