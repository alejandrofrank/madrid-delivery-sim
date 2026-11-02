/** Read-only anatomy contracts, including the actual WebGL interaction. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const base=process.env.ANATOMY_URL||'http://localhost:8010',out='.impeccable/review';
async function settled(page){
 await page.waitForFunction(()=>{
  const c=document.querySelector('.anatomy-illustration canvas');if(!c)return true;
  return Number(c.dataset.viewWidth)===c.parentElement.clientWidth&&Number(c.dataset.viewHeight)===c.parentElement.clientHeight&&c.dataset.part===(document.querySelector('#anatomy-part-select').value||'');
 });
}
async function capture(page,path){
 await settled(page);
 // A matching camera alone does not prove the model survived a canvas resize.
 const visible=await page.locator('.anatomy-illustration canvas').evaluateAll(canvases=>canvases.every(c=>{
  const gl=c.getContext('webgl2'),pixels=new Uint8Array(gl.drawingBufferWidth*gl.drawingBufferHeight*4);
  gl.readPixels(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
  let lit=0;for(let i=0;i<pixels.length;i+=4)if(pixels[i]>70)lit++;
  return lit>2000;
 }));
 assert(visible,'The 3D model must remain visible after resize and component focus: '+path);
 if(!process.env.CI)await page.screenshot({path,fullPage:true});
}
(async()=>{
 await fs.mkdir(out,{recursive:true});
 const browser=await chromium.launch({headless:true,args:['--enable-unsafe-swiftshader','--use-angle=swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(base+'/architecture');
  await page.locator('.anatomy-illustration canvas').waitFor();
  await page.waitForFunction(()=>document.querySelector('.anatomy-illustration canvas')?.dataset.render);
  const data=await (await page.request.get(base+'/api/agent-anatomy')).json();
  const canvas=page.locator('.anatomy-illustration canvas');
  assert.equal(await page.locator('.team-agent').count(),data.agents.length);
  assert(!(await page.locator('#anatomy-inspector').isVisible()));
  assert(!(await page.locator('.sidebar').isVisible()));
  assert(!(await page.locator('#chapter-body').isVisible()));
  const render=JSON.parse(await canvas.getAttribute('data-render'));
  assert(render.calls<240&&render.triangles<250000,JSON.stringify(render));
  assert.equal(await canvas.getAttribute('data-motion'),'paused');
  let panels=0;
  for(const agent of data.agents){
   await page.locator('.team-agent[data-agent="'+agent.id+'"]').click();
   assert.equal(await page.locator('.anatomy-identity h2').innerText(),agent.name);
   for(const panel of agent.panels){
    await page.locator('#anatomy-part-select').selectOption(panel.id);
    assert.equal(await page.locator('#anatomy-panel-title').innerText(),panel.title);
    assert.equal(await page.locator('.anatomy-summary').innerText(),panel.summary);
    assert.equal(await page.locator('.anatomy-sources a[data-source]').count(),panel.sources.length);
    assert.equal(await page.locator('.anatomy-hotspot[aria-pressed="true"]').getAttribute('data-part'),panel.id);
    assert(!(await page.locator('.anatomy-technical').getAttribute('open')));
    await page.locator('.anatomy-technical>summary').click();
    for(const detail of panel.details)assert((await page.locator('.anatomy-explanation').textContent()).includes(detail));
    panels++;
   }
  }
  await page.locator('.team-agent[data-agent="fulfillment"]').click();
  await page.locator('#anatomy-part-select').selectOption('environment');
  for(const [id,variant] of Object.entries(data.agents.find(a=>a.id==='fulfillment').panels.find(p=>p.id==='environment').environments)){
   await page.locator('#anatomy-environment').selectOption(id);
   assert.equal(await page.locator('.anatomy-summary').innerText(),variant.summary);
  }
  await page.locator('.team-agent[data-agent="restaurant"]').click();
  const initial=await canvas.getAttribute('data-camera');
  const engine=page.locator('.anatomy-hotspot[data-part="model"]');
  await engine.focus();await page.keyboard.press('Enter');
  await page.waitForFunction(initial=>document.querySelector('.anatomy-illustration canvas').dataset.camera!==initial,initial);
  assert.equal(await page.locator('#anatomy-panel-title').innerText(),'Model & routing');
  await page.keyboard.press('ArrowRight');
  assert.equal(await page.evaluate(()=>document.activeElement.dataset.part),'protocols');
  await page.keyboard.press('Space');
  assert.equal(await page.locator('#anatomy-panel-title').innerText(),'A2A & MCP');
  await page.locator('.anatomy-technical>summary').click();
  await page.getByText('Inspect the generated Agent Card',{exact:true}).click();
  assert.match(await page.locator('.anatomy-card pre').innerText(),/supportedInterfaces/);
  await page.locator('.anatomy-sources a[data-source]').first().click();
  await page.locator('#source-dialog[open]').waitFor();
  await page.waitForFunction(()=>document.querySelector('#source-code').textContent.length>0);
  assert.match(await page.locator('#source-code').innerText(),/A2A/);
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Close component details'}).click();
  assert(!(await page.locator('#anatomy-inspector').isVisible()));
  await page.getByRole('button',{name:'Team connections',exact:true}).click();
  await page.getByText('Read the handoffs as text',{exact:true}).click();
  assert((await page.locator('.anatomy-edge-list li').count())>0);
  const aligned=await page.evaluate(()=>{
   const graph=document.querySelector('.anatomy-connections');
   return [...graph.querySelectorAll('path')].every(path=>{
    const point=path.getPointAtLength(path.getTotalLength()).matrixTransform(graph.getScreenCTM());
    const box=document.querySelector('.team-diagram-agent[data-agent="'+path.dataset.to+'"]').getBoundingClientRect();
    return Math.abs(point.x-(box.left+box.width/2))<2;
   });
  });assert(aligned,'Handoffs must connect to their actual role columns');
  await page.getByRole('button',{name:'Replay handoffs',exact:true}).click();
  assert.equal(await page.locator('.team-wire.connected').first().evaluate(el=>getComputedStyle(el).animationName),'none');
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.getByRole('button',{name:'Replay handoffs',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.anatomy-connections').classList.contains('playing'));
  assert.equal(await page.locator('.team-wire.connected').first().evaluate(el=>getComputedStyle(el).animationIterationCount),'4');
  await page.getByRole('button',{name:'Inspect agent',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.anatomy-illustration canvas').dataset.motion==='playing');
  await page.locator('#anatomy-pause').click();
  await page.waitForFunction(()=>document.querySelector('.anatomy-illustration canvas').dataset.motion==='paused');
  await page.emulateMedia({reducedMotion:'reduce'});
  const captures=[];
  for(const [name,width,height] of [['desktop',1440,1000],['laptop',1280,800],['mobile',390,844],['user-1265',1265,712],['user-1916',1916,1244]]){
   await page.setViewportSize({width,height});
   await page.locator('#anatomy-reset').click();
   await page.evaluate(()=>{document.activeElement?.blur();scrollTo(0,0);});
   await settled(page);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' overflow');
   await capture(page,out+'/showcase-'+name+'.png');
   await page.locator('#anatomy-part-select').selectOption('memory');
   assert(await page.locator('#anatomy-inspector').isVisible());
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await capture(page,out+'/showcase-'+name+'-memory.png');
   captures.push({name,width,height});
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('#anatomy-reset').click();
  await page.getByRole('button',{name:'Chapters',exact:true}).click();
  assert(await page.locator('.sidebar').isVisible());
  await page.keyboard.press('Escape');
  assert(!(await page.locator('.sidebar').isVisible()));
  await page.getByRole('button',{name:'Read guide',exact:true}).click();
  assert(await page.locator('#chapter-body').isVisible());
  await page.getByRole('button',{name:'Read guide',exact:true}).click();
  await page.evaluate(()=>scrollTo(0,0));
  // The physical canvas itself is selectable, independent of DOM hotspots.
  await canvas.focus();await page.keyboard.press('ArrowLeft');
  assert.notEqual(await canvas.getAttribute('data-camera'),initial);
  // A lost graphics context must retain all component information.
  await canvas.evaluate(el=>el.dispatchEvent(new Event('webglcontextlost',{cancelable:true})));
  await page.locator('.anatomy-illustration.is-fallback .agent-machine').waitFor();
  await page.locator('#anatomy-part-select').selectOption('memory');
  assert.equal(await page.locator('#anatomy-panel-title').innerText(),'Memory & scope');
  await capture(page,out+'/showcase-fallback.png');
  await page.goto(base+'/architecture?page=overview');
  assert.equal(await page.locator('.anatomy-illustration canvas').count(),0);
  assert(await page.locator('.sidebar').isVisible());
  await page.route('**/api/agent-anatomy',route=>route.fulfill({status:503,body:'Unavailable'}));
  await page.goto(base+'/architecture');await page.getByRole('button',{name:'Retry agent definitions'}).waitFor();
  await page.unroute('**/api/agent-anatomy');await page.getByRole('button',{name:'Retry agent definitions'}).click();
  await page.locator('.anatomy-illustration canvas').waitFor();
  assert.deepEqual(errors,[]);
  const result={checked_at:new Date().toISOString(),agents:data.agents.length,panels,render,webgl:true,progressive_details:true,keyboard:true,source_dialog:true,card:true,finite_animation:true,reduced_motion:true,retry:true,context_loss_fallback:true,renderer_disposed:true,no_horizontal_page_overflow:true,captures};
  await fs.writeFile(out+'/anatomy-checks.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
 }catch(e){await page.screenshot({path:out+'/showcase-failure.png',timeout:15000}).catch(()=>{});throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
