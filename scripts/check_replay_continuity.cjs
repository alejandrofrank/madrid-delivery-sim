/* Test perceived motion, not merely animation-frame counts. No live run writes. */
const {chromium}=require("playwright"),assert=require("node:assert/strict"),fs=require("node:fs/promises");
(async()=>{
 const browser=await chromium.launch({headless:true,args:["--enable-unsafe-swiftshader","--use-angle=swiftshader"]});
 const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:"reduce"});
 const errors=[];page.on("pageerror",e=>errors.push(String(e)));
 try{
  await fs.mkdir("artifacts/product-check",{recursive:true});
  await page.goto("http://localhost:8010/watch");await page.waitForSelector("#fleet .fleet-row");
  const slider=page.getByRole("slider",{name:"Replay position in seconds"});
  await slider.fill("20");await slider.dispatchEvent("input");await page.waitForTimeout(1100);
  assert.equal(await slider.inputValue(),"20");
  // Delay state snapshots. The buffered route must keep moving without them.
  await page.route("**/api/recorded/state?**",async route=>{await new Promise(r=>setTimeout(r,1500));await route.continue().catch(()=>{});});
  const id=await page.evaluate(()=>{
   const ranked=state.couriers.map(c=>{const a=replayMotion.position(c.id,20),b=replayMotion.position(c.id,22);return [c.id,Math.hypot(a[0]-b[0],a[1]-b[1])];}).sort((a,b)=>b[1]-a[1]);
   return ranked[0][0];
  });
  await page.getByRole("button",{name:"Play replay",exact:true}).click();
  const samples=await page.evaluate(id=>new Promise(resolve=>{
   const values=[],start=performance.now();
   function sample(now){
    const p=courierMarkers.get(id).getLatLng();
    values.push({time:now,lat:p.lat,lon:p.lng,slider:Number(document.querySelector(".ui-replay-controls input").value)});
    if(now-start<2600)requestAnimationFrame(sample);else resolve(values);
   }
   requestAnimationFrame(sample);
  }),id);
  assert(samples.length>20,"Enough visible frames to assess movement");
  const positions=new Set(samples.map(p=>p.lat.toFixed(8)+":"+p.lon.toFixed(8)));
  const times=new Set(samples.map(p=>p.slider.toFixed(3)));
  assert(positions.size>samples.length*.8,"Couriers move between HTTP snapshots");
  assert(times.size>samples.length*.8,"The slider moves between whole seconds");
  assert(samples.some(p=>p.slider%1>.1&&p.slider%1<.9),"Presentation time is fractional");
  await page.getByRole("button",{name:"Pause replay",exact:true}).click();
  const paused=await slider.inputValue();await page.waitForTimeout(400);assert.equal(await slider.inputValue(),paused);
  await page.unrouteAll({behavior:"wait"});
  // The loading state must be visible before either data request finishes.
  await page.addInitScript(()=>localStorage.setItem("mds-anatomy-tour-v1","seen"));
  await page.route("**/api/documentation",async r=>{await new Promise(done=>setTimeout(done,1600));await r.continue();});
  await page.goto("http://localhost:8010/agents",{waitUntil:"domcontentloaded"});
  await page.locator("#loading .ui-loading-network").waitFor();
  assert(await page.locator("#loading").isVisible());
  if(!process.env.CI)await page.screenshot({path:"artifacts/product-check/agents-loading.png"});
  await page.waitForSelector(".delivery-scene-canvas");
  await page.waitForFunction(()=>Number(document.querySelector(".delivery-scene-canvas").dataset.frames)>0);
  assert.equal(await page.locator(".delivery-scene-canvas").getAttribute("data-rooms"),"7");
  assert(await page.locator(".story-legend").isVisible());
  if(!process.env.CI)await page.screenshot({path:"artifacts/product-check/agents-rooms.png",fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  const viewport=page.locator(".delivery-scene-viewport");
  assert(await viewport.evaluate(el=>el.scrollWidth>el.clientWidth),"Mobile has legible rooms in a local panorama");
  const cdp=await page.context().newCDPSession(page);
  await cdp.send("Emulation.setTouchEmulationEnabled",{enabled:true});
  const bounds=await viewport.boundingBox(),y=Math.min(700,bounds.y+200);
  await cdp.send("Input.dispatchTouchEvent",{type:"touchStart",touchPoints:[{x:320,y}]});
  for(let x=300;x>=70;x-=20)await cdp.send("Input.dispatchTouchEvent",{type:"touchMove",touchPoints:[{x,y}]});
  await cdp.send("Input.dispatchTouchEvent",{type:"touchEnd",touchPoints:[]});
  await page.waitForTimeout(200);
  assert(await viewport.evaluate(el=>el.scrollLeft>80),"Actual touch swipe reaches the offscreen rooms");
  await page.locator('.story-step[data-step="5"] button').click();
  await page.waitForFunction(()=>document.querySelector(".delivery-scene-viewport").scrollLeft>400);
  await page.locator(".delivery-scene-canvas").focus();await page.keyboard.press("Home");
  assert.equal(await viewport.evaluate(el=>el.scrollLeft),0);
  if(!process.env.CI)await page.screenshot({path:"artifacts/product-check/agents-rooms-mobile.png",fullPage:true});
  await page.locator(".delivery-scene-canvas").evaluate(c=>c.dispatchEvent(new Event("webglcontextlost",{cancelable:true})));
  assert(await page.locator(".scene-plan").isVisible());
  assert(await viewport.evaluate(el=>el.scrollWidth===el.clientWidth),"Mobile fallback fits without sideways scrolling");
  assert.deepEqual(errors,[]);
  const result={samples:samples.length,positions:positions.size,sliderValues:times.size,slowResponses:true,pausedSeek:true,loading:true,mobilePanorama:true};
  await fs.writeFile("artifacts/product-check/continuity.json",JSON.stringify(result,null,2));console.log(result);
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
