const {chromium}=require('playwright'),fs=require('node:fs/promises');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const results=[];
 try{
  for(const robots of [true,false]){
   const page=await browser.newPage({viewport:{width:1440,height:1000}});
   if(!robots)await page.route('**/landing-robots.js*',r=>r.abort());
   await page.goto('http://localhost:8010/');await page.waitForFunction(()=>document.getElementById('story-canvas').dataset.simTime);
   if(robots)await page.waitForSelector('#story-robots canvas');
   await page.waitForTimeout(800);
   const timing=await page.evaluate(()=>new Promise(resolve=>{
    const frames=[];let last=0,start=0;
    function tick(now){if(last)frames.push(now-last);last=now;start||=now;if(now-start<5000)requestAnimationFrame(tick);else{const sorted=frames.slice().sort((a,b)=>a-b);resolve({frames:frames.length,fps:1000/(frames.reduce((a,b)=>a+b,0)/frames.length),p95_ms:sorted[Math.floor(sorted.length*.95)],over_50ms:frames.filter(x=>x>50).length});}}
    requestAnimationFrame(tick);
   }));
   const graphics=await page.evaluate(()=>{const canvas=document.querySelector('#story-robots canvas');if(!canvas)return null;const gl=canvas.getContext('webgl2'),ext=gl.getExtension('WEBGL_debug_renderer_info');return {renderer:ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):null,width:canvas.width,height:canvas.height,calls:canvas.dataset.drawCalls};});
   results.push({robots,...timing,graphics});await page.close();
  }
  await fs.writeFile(process.argv[2]||'artifacts/story-performance.json',JSON.stringify(results,null,2));console.log(JSON.stringify(results,null,2));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
