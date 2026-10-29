/** Verifies genuine local cartography, selected routes, responsive states and keyboard/touch. */
const {chromium}=require('playwright');
const fs=require('node:fs/promises');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const out='docs/media/correction/verified';await fs.mkdir(out,{recursive:true});
 const failures=[],external=[],checks=[];
 try{
 const page=await browser.newPage({viewport:{width:1536,height:1024}});
 page.on('pageerror',e=>failures.push(String(e)));
 page.on('response',r=>{if(r.status()>=400)failures.push(r.status()+' '+r.url());});
 page.on('request',r=>{if(!r.url().startsWith('http://localhost:8021')&&!r.url().startsWith('blob:')&&!r.url().startsWith('data:'))external.push(r.url());});
 const runs=JSON.parse(await fs.readFile('artifacts/ui-runs.json','utf8'));
 await page.goto('http://localhost:8021/?run='+runs.madrid);
 await page.waitForFunction(()=>document.getElementById('map').dataset.basemap==='ready');
 await page.waitForSelector('.fleet-row');
 const initial=await page.evaluate(()=>({features:window.madridBasemap.queryRenderedFeatures().length,run:state.run.id,status:state.run.status}));
 assert(initial.features>100);
 await page.screenshot({path:out+'/completed-1536.png'});
 assert.equal(await page.locator('#order-filter').inputValue(),'all');
 await page.locator('#order-search').fill('unmatched-search');
 assert(await page.locator('#orders-empty').isVisible());
 await page.setViewportSize({width:320,height:740});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 assert(await page.locator('#orders-empty').evaluate(el=>el.scrollWidth<=el.clientWidth));
 await page.locator('#order-search').fill('');
 await page.setViewportSize({width:1036,height:850});
 await page.screenshot({path:out+'/supplied-image-width-1036.png',fullPage:true});
 await page.setViewportSize({width:1536,height:1024});
 await page.locator('#fit-map').click();
 const initialCenter=await page.evaluate(()=>window.madridBasemap.getCenter().toArray());
 await page.locator('#map').focus();await page.keyboard.press('ArrowRight');await page.waitForTimeout(400);
 assert.notDeepEqual(await page.evaluate(()=>window.madridBasemap.getCenter().toArray()),initialCenter);
 await page.locator('#fit-map').click();
 checks.push('Local city cartography has rendered features; no external resources; completed orders and 320px empty state; keyboard map pan');
 await page.locator('#view-simulation').click();await page.locator('#duration').selectOption('60');await page.locator('#start').click();
 await page.waitForFunction(()=>state?.couriers.some(c=>c.route?.points?.length>1&&['to_pickup','delivering'].includes(c.status)),null,{timeout:30000});
 const active=await page.evaluate(()=>state.couriers.find(c=>c.route?.points?.length>1&&['to_pickup','delivering'].includes(c.status)).id);
 await page.locator('[data-courier="'+active+'"]').click();
 const before=await page.evaluate(id=>courierMarkers.get(id).getLatLng(),active);
 const positions=[JSON.stringify(before)];
 for(let i=0;i<12;i++){await page.waitForTimeout(150);positions.push(JSON.stringify(await page.evaluate(id=>courierMarkers.get(id).getLatLng(),active)));}
 assert(new Set(positions).size>1,'A real route moves its selected courier across updates');
 assert(await page.evaluate(()=>routeLayer.getLayers().length>0));
 assert((await page.locator('#selected-trace').getAttribute('href')).includes(encodeURIComponent(active)));
 await page.waitForTimeout(2200);
 for(const [name,width,height] of [['1536',1536,1024],['laptop',1280,800],['mobile',390,844]]){
  await page.setViewportSize({width,height});await page.locator('#fit-map').click();await page.waitForTimeout(400);
  await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:out+'/running-'+name+'.png',fullPage:true});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 }
 checks.push('Free live session: selected row, real route animation, trace link, observed history, desktop/laptop/mobile');
 const liveRun=await page.evaluate(()=>state.run.id);
 const touch=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 await touch.goto('http://localhost:8021/?run='+liveRun);await touch.waitForFunction(()=>document.getElementById('map').dataset.basemap==='ready');
 await touch.locator('#map').scrollIntoViewIfNeeded();
 const rect=await touch.locator('#map').boundingBox(),x=rect.x+80,y=rect.y+180;
 const center=await touch.evaluate(()=>window.madridBasemap.getCenter().toArray());
 const session=await touch.context().newCDPSession(touch);
 await session.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});
 for(let i=1;i<=5;i++){await session.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x+i*10,y}]});await touch.waitForTimeout(40);}
 await session.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await touch.waitForTimeout(300);
 assert.notDeepEqual(await touch.evaluate(()=>window.madridBasemap.getCenter().toArray()),center,'Emulated touch pans the map');
 await touch.locator('.map-key summary').tap();assert(await touch.locator('#map-symbols').isVisible());
 await touch.close();checks.push('Chromium emulated touch: pan and legend toggle (physical device not tested)');
 assert.deepEqual(failures,[]);assert.deepEqual(external,[]);
 await fs.writeFile(out+'/map-checks.json',JSON.stringify({capturedAt:new Date().toISOString(),initial,liveRun,checks,failures,external},null,2)+'\n');
 console.log(checks.join('\n'));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});