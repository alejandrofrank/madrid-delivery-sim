/* Record the actual app; no fabricated animation or interpolated business outcomes. */
const {chromium}=require('playwright'),fs=require('node:fs/promises');
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1280,height:900}});
 const base=process.env.STORE_UI_BASE||'http://localhost:8010';
 const root='artifacts/dark-store/frames';await fs.mkdir(root,{recursive:true});
 await fs.mkdir('.impeccable/review',{recursive:true});
 try{
  await page.goto(base+'/');await page.locator('#store-demo').waitFor();
  await page.locator('#store-demo-chaos').check();
  await page.screenshot({path:root+'/000.png'});
  await page.locator('#store-demo').click();
  await page.waitForFunction(()=>!document.querySelector('#store-view').hidden,{},{timeout:60000});
  await page.waitForFunction(()=>document.querySelector('#store-render-status').textContent.includes('3D cutaway'),{},{timeout:60000});
  // Begin elevated, then track closer during packing and the trip to the dock.
  await page.locator('#store-track').uncheck();await page.locator('#store-fit').click();
  const frames=[];let delivered=false;
  for(let i=1;i<=120;i++){
   const status=await page.locator('#store-follow-note').innerText();
   if(/Packing|Moving to dock/.test(status)&&await page.locator('#store-view').isVisible())await page.locator('#store-track').check();
   const file=root+'/'+String(i).padStart(3,'0')+'.png';
   await page.screenshot({path:file});frames.push({file,status});
   if(status.includes('Delivered')){delivered=true;break;}
   await page.waitForTimeout(1000);
  }
  if(!delivered)throw new Error('Real delivery did not finish within the recording window');
  const run=new URL(page.url()).searchParams.get('run');
  await page.locator('#store-open').click();
  await page.waitForFunction(()=>document.querySelector('#store-render-status').textContent.includes('3D cutaway'));
  const captures=[];
  for(const [name,width,height] of [['desktop',1440,1000],['mobile',390,844],['user-1916',1916,1244],['laptop',1280,900]]){
   await page.setViewportSize({width,height});
   await page.locator('#store-track').uncheck();await page.locator('#store-fit').click();
   await page.evaluate(()=>window.scrollTo(0,0));await page.waitForTimeout(200);
   const path='.impeccable/review/dark-store-'+name+'.png';await page.screenshot({path,fullPage:true});captures.push(path);
  }
  const stats=await page.locator('#store-stage canvas').evaluate(el=>({calls:Number(el.dataset.drawCalls),triangles:Number(el.dataset.triangles)}));
  await page.goto(base+'/?run='+run+'&store-fallback=1');await page.locator('#store-open').click();
  await page.locator('#store-floor').waitFor({state:'visible'});await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:'.impeccable/review/dark-store-fallback.png',fullPage:true});
  await fs.writeFile('artifacts/dark-store/recording.json',JSON.stringify({run,delivered,frames,captures,stats},null,2));
  console.log(JSON.stringify({run,delivered,frames:frames.length,stats,captures}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
