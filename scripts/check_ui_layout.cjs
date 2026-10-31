/** Focused regression checks for reviewed map and responsive layout defects. */
const {chromium}=require('playwright');
const fs=require('node:fs/promises');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1536,height:1024},reducedMotion:'reduce'});
  const runs=JSON.parse(await fs.readFile('artifacts/ui-runs.json','utf8')),checks=[];
  await page.goto('http://localhost:8010/?run='+runs.madrid);
  await page.waitForFunction(()=>document.getElementById('map').dataset.basemap==='ready');
  for(const [width,height] of [[1536,1024],[1280,800],[390,844],[1536,1024],[1036,850]]){
   await page.setViewportSize({width,height});
   await page.locator('#fit-map').click();
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   const result=await page.evaluate(()=>{
    const gl=window.madridBasemap,c=map.getContainer().getBoundingClientRect(),r=gl.getCanvas().getBoundingClientRect(),p=map.latLngToContainerPoint([40.415,-3.685]),q=gl.project([-3.685,40.415]);
    return {width:innerWidth,errorX:q.x+r.left-c.left-p.x,errorY:q.y+r.top-c.top-p.y};
   });
   assert(Math.abs(result.errorX)<1&&Math.abs(result.errorY)<1,'Map projections align after resize: '+JSON.stringify(result));
   await page.waitForFunction(()=>window.madridBasemap.areTilesLoaded()&&window.madridBasemap.queryRenderedFeatures().length>100);
   checks.push({check:'projection after two frames and visible cartography',...result});
  }
  await page.locator('#view-simulation').click();await page.locator('#view-operations').click();
  await page.waitForFunction(()=>{
   const gl=window.madridBasemap,c=map.getContainer().getBoundingClientRect(),r=gl.getCanvas().getBoundingClientRect(),p=map.latLngToContainerPoint([40.415,-3.685]),q=gl.project([-3.685,40.415]);
   return Math.abs(q.x+r.left-c.left-p.x)<1&&Math.abs(q.y+r.top-c.top-p.y)<1;
  });
  checks.push({check:'simulation / operations projection',pass:true});
  await page.setViewportSize({width:1536,height:1024});await page.locator('#fit-map').click();await page.waitForTimeout(600);
  await page.evaluate(()=>{document.activeElement?.blur();scrollTo(0,0);});
  const ledger=await page.evaluate(()=>({sixthRowBottom:document.querySelectorAll('#orders tr')[5].getBoundingClientRect().bottom,mapHeight:document.getElementById('map').getBoundingClientRect().height}));
  assert(ledger.sixthRowBottom<=1024&&ledger.mapHeight>=458,'Six readable order rows and full map: '+JSON.stringify(ledger));
  checks.push({check:'native ledger density',...ledger});
  await page.screenshot({path:'docs/media/correction/verified/completed-1536.png',fullPage:true});
  await fs.writeFile('docs/media/correction/verified/layout-checks.json',JSON.stringify({capturedAt:new Date().toISOString(),checks},null,2));
  console.log('Passed '+checks.length+' reviewed layout checks');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
