/** Read-only anatomy contracts, including the actual WebGL interaction. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const base=process.env.ANATOMY_URL||'http://localhost:8010',out='.impeccable/review';
async function settled(page){
 await page.waitForFunction(()=>{
  const c=document.querySelector('.anatomy-illustration canvas');if(!c||!c.offsetParent)return true;
  return Number(c.dataset.viewWidth)===c.parentElement.clientWidth&&Number(c.dataset.viewHeight)===c.parentElement.clientHeight&&c.dataset.part===(document.querySelector('#anatomy-part-select').value||'');
 });
}
async function options(page){await page.locator('.anatomy-options').evaluate(el=>el.open=true);}
async function capture(page,path){
 await page.evaluate(path=>{
  const target=path.includes('results-desktop')?document.querySelector('.anatomy-results'):path.includes('card-desktop')?document.querySelector('.anatomy-card'):null;
  const inspector=document.querySelector('#anatomy-inspector');
  if(target)inspector.scrollTo({top:inspector.scrollTop+target.getBoundingClientRect().top-inspector.getBoundingClientRect().top-20,behavior:'instant'});
  scrollTo({top:0,behavior:'instant'});document.activeElement?.blur();
 },path);
 await settled(page);
 await page.evaluate(()=>document.fonts.ready);
 // A matching camera alone does not prove the model survived a canvas resize.
 const visible=await page.locator('.anatomy-illustration canvas').evaluateAll(canvases=>canvases.every(c=>{
  if(!c.offsetParent)return true;
  const gl=c.getContext('webgl2'),pixels=new Uint8Array(gl.drawingBufferWidth*gl.drawingBufferHeight*4);
  gl.readPixels(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
  let lit=0;for(let i=0;i<pixels.length;i+=4)if(pixels[i]>70)lit++;
  return lit>2000;
 }));
 assert(visible,'The 3D model must remain visible after resize and component focus: '+path);
 if(!process.env.CI)await page.screenshot({path,fullPage:!path.includes('results-desktop')&&!path.includes('card-desktop')});
}
(async()=>{
 await fs.mkdir(out,{recursive:true});
 const browser=await chromium.launch({headless:true,args:['--enable-unsafe-swiftshader','--use-angle=swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(base+'/architecture');
  await page.locator('.anatomy-team-panel').waitFor();
  await page.locator('.anatomy-tour').waitFor();
  assert.equal(await page.locator('#anatomy-part-select').inputValue(),'mission');
  await page.waitForTimeout(6000);
  assert.equal(await page.locator('#anatomy-part-select').inputValue(),'mission','Reduced motion never advances the tour');
  for(const expected of ['tools','policy','evals']){
   await page.locator('#tour-next').click();
   assert.equal(await page.locator('#anatomy-part-select').inputValue(),expected);
  }
  await page.locator('#tour-next').click();
  assert(await page.locator('.anatomy-team-panel').isVisible());
  assert.equal(await page.evaluate(()=>localStorage.getItem('mds-anatomy-tour-v1')),'seen');
  await page.reload();await page.locator('.anatomy-team-panel').waitFor();
  await page.waitForTimeout(3000);
  assert(!(await page.locator('.anatomy-tour').isVisible()));
  await page.getByRole('button',{name:'Inspect Restaurant agent',exact:true}).click();
  await page.locator('.anatomy-illustration canvas').waitFor();
  await page.waitForFunction(()=>document.querySelector('.anatomy-illustration canvas')?.dataset.render);
  const data=await (await page.request.get(base+'/api/agent-anatomy')).json();
  const canvas=page.locator('.anatomy-illustration canvas');
  assert.equal(await page.locator('.team-agent').count(),data.agents.length);
  assert(await page.locator('#anatomy-inspector').isVisible());
  assert(!(await page.locator('.sidebar').isVisible()));
  assert(!(await page.locator('#chapter-body').isVisible()));
  await page.evaluate(()=>document.fonts.ready);
  assert(await page.evaluate(()=>document.fonts.check('600 24px Oxanium')));
  assert.match(await page.locator('.anatomy-identity h2').evaluate(el=>getComputedStyle(el).fontFamily),/Oxanium/);
  const render=JSON.parse(await canvas.getAttribute('data-render'));
  assert(render.calls<240&&render.triangles<250000,JSON.stringify(render));
  assert.equal(await canvas.getAttribute('data-motion'),'paused');
  let panels=0;
  for(const agent of data.agents){
   await page.locator('.team-agent[data-agent="'+agent.id+'"]').click();
   assert.equal(await page.locator('.anatomy-identity h2').innerText(),agent.name);
   assert.equal(await page.locator('.anatomy-identity p').innerText(),agent.introduction);
   assert.equal(await canvas.getAttribute('data-badge'),agent.badge);
   assert.equal(JSON.parse(await canvas.getAttribute('data-budget')).fraction,agent.budget.fraction);
   assert.deepEqual(JSON.parse(await canvas.getAttribute('data-tools')),agent.tool_badges.map(t=>t.id));
   for(const panel of agent.panels){
    await page.locator('#anatomy-part-select').selectOption(panel.id);
    assert.equal(await page.locator('#anatomy-panel-title').innerText(),panel.part);
    assert.equal(await page.locator('.anatomy-panel-topic').innerText(),panel.label);
    assert.equal(await page.locator('.anatomy-panel-term').innerText(),panel.technical_label);
    assert.equal(await page.locator('.anatomy-headline h4').innerText(),panel.headline.text);
    assert.equal(await page.locator('.anatomy-headline-value strong').innerText(),String(panel.headline.value));
    assert.deepEqual(await page.locator('.anatomy-headline li').allTextContents(),panel.headline.bullets);
    assert.equal(await page.locator('.anatomy-summary').innerText(),panel.summary);
    assert.equal(await page.locator('.anatomy-sources a[data-source]').count(),panel.sources.length);
    assert.equal(await page.locator('.anatomy-hotspot[aria-pressed="true"]').getAttribute('data-part'),panel.id);
    assert(!(await page.locator('.anatomy-technical').getAttribute('open')));
    await page.locator('.anatomy-technical>summary').click();
    assert.deepEqual(await page.locator('.anatomy-technical>.anatomy-numbers dt').allTextContents(),panel.number_rows.map(r=>r.label));
    if(agent.id==='restaurant'&&panel.id==='evals')await capture(page,out+'/results-desktop.png');
    if(agent.id==='customer_service'&&panel.id==='limits')await capture(page,out+'/budget-desktop.png');
    for(const detail of panel.details)assert((await page.locator('.anatomy-explanation').textContent()).includes(detail));
    await page.locator(".anatomy-full-reference>summary").click();
    await page.locator(".anatomy-inline-article").waitFor();
    assert((await page.locator(".anatomy-inline-article").innerText()).length>100);
    await page.locator(".anatomy-full-reference>summary").click();
    panels++;
   }
  }
  await require("./check_memory_reference.cjs")(page,data,capture,out);
  await page.locator('.team-agent[data-agent="fulfillment"]').click();
  await page.locator('#anatomy-part-select').selectOption('environment');
  for(const [id,variant] of Object.entries(data.agents.find(a=>a.id==='fulfillment').panels.find(p=>p.id==='environment').environments)){
   await page.locator('#anatomy-environment').selectOption(id);
   assert.equal(await page.locator('.anatomy-summary').innerText(),variant.summary);
  }
  await page.locator('.team-agent[data-agent="restaurant"]').click();
  await settled(page);
  const initial=await canvas.getAttribute('data-camera');
  const engine=page.locator('.anatomy-hotspot[data-part="model"]');
  await engine.focus();await page.keyboard.press('Enter');
  await settled(page);
  assert.equal(await canvas.getAttribute('data-camera'),initial,'Selecting a part must preserve framing');
  assert.equal(await page.locator('#anatomy-panel-title').innerText(),'Engine');
  await page.keyboard.press('ArrowRight');
  assert.equal(await page.evaluate(()=>document.activeElement.dataset.part),'protocols');
  await page.keyboard.press('Space');
  assert.equal(await page.locator('#anatomy-panel-title').innerText(),'Antenna');
  await page.locator('.anatomy-technical>summary').click();
  await page.getByText('Inspect the generated Agent Card',{exact:true}).click();
  assert.equal(await page.locator('.anatomy-card pre').count(),0);
  const cardFields=data.agents.find(a=>a.id==='restaurant').panels.find(p=>p.id==='protocols').card_fields;
  assert.deepEqual(await page.locator('.anatomy-card-fields dt').allTextContents(),cardFields.map(f=>f.label));
  assert.deepEqual(await page.locator('.anatomy-card-fields dd').allTextContents(),cardFields.map(f=>f.value));
  await capture(page,out+'/card-desktop.png');
  await page.locator('.anatomy-sources a[data-source]').first().click();
  await page.locator('#source-dialog[open]').waitFor();
  await page.waitForFunction(()=>document.querySelector('#source-code').textContent.length>0);
  assert.match(await page.locator('#source-code').innerText(),/A2A/);
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Close component details'}).click();
  assert(!(await page.locator('#anatomy-inspector').isVisible()));
  await page.getByRole('button',{name:'Back to team',exact:true}).click();
  assert.equal(await page.locator('.story-step').count(),data.story.steps.length);
  assert.deepEqual(await page.locator('.story-handoff>span:last-child').allTextContents(),data.story.steps.filter(s=>s.handoff).map(s=>s.handoff));
  assert.equal(await page.locator('.story-legend dt').count(),3);
  assert.equal(await page.locator('.anatomy-team-panel button[data-agent]').count(),9);
  assert.equal(await page.locator('.story-portrait img').count(),9);
  assert(await page.locator('.story-portrait img').evaluateAll(images=>images.every(img=>{
   const c=document.createElement('canvas');c.width=180;c.height=210;
   const ctx=c.getContext('2d');ctx.drawImage(img,0,0,180,210);
   const pixels=ctx.getImageData(0,0,180,150).data;let visible=0;
   for(let i=0;i<pixels.length;i+=4)if(pixels[i]>70)visible++;
   return visible>350;
  })),'Each miniature must contain the robot, not only its floor');
  await page.locator('#story-play').click();
  assert.equal(await page.locator('.story-step[aria-current]').getAttribute('data-step'),'1');
  assert.equal(await page.locator('.story-order').first().evaluate(el=>getComputedStyle(el).animationName),'none');
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.locator('#story-play').click();
  assert.equal(await page.locator('.story-step.is-travelling .story-order').evaluate(el=>getComputedStyle(el).animationIterationCount),'1');
  await page.waitForFunction(()=>document.querySelector('.story-step[aria-current]').dataset.step==='5',{},{timeout:20000});
  await page.waitForFunction(()=>document.querySelector('#story-play').textContent==='Replay order');
  await page.getByRole('button',{name:'Replay tour',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#anatomy-part-select').value==='tools',{},{timeout:10000});
  await page.locator('#tour-pause').click();
  await page.waitForTimeout(6000);assert.equal(await page.locator('#anatomy-part-select').inputValue(),'tools');
  await page.locator('#tour-skip').click();
  await page.getByRole('button',{name:'Inspect Restaurant agent',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.anatomy-illustration canvas').dataset.motion==='playing');
  await options(page);await page.locator('#anatomy-pause').click();
  await page.locator('.anatomy-options').evaluate(el=>el.open=false);
  await page.waitForFunction(()=>document.querySelector('.anatomy-illustration canvas').dataset.motion==='paused');
  await page.emulateMedia({reducedMotion:'reduce'});
  const captures=[];
  for(const [name,width,height] of [['desktop',1440,1000],['laptop',1280,800],['mobile',390,844],['user-1265',1265,712],['user-1916',1916,1244],['user-1463',1463,753]]){
   await page.setViewportSize({width,height});
   await options(page);await page.locator('#anatomy-reset').click();
   await page.locator('.anatomy-options').evaluate(el=>el.open=false);
   await page.getByRole('button',{name:'Back to team',exact:true}).click();
   await page.evaluate(()=>{document.activeElement?.blur();scrollTo(0,0);});
   await capture(page,out+'/story-'+name+'.png');
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' story overflow');
   await page.getByRole('button',{name:'Inspect Restaurant agent',exact:true}).click();
   await options(page);await page.locator('#anatomy-reset').click();
   await page.locator('.anatomy-options').evaluate(el=>el.open=false);
   await page.evaluate(()=>{document.activeElement?.blur();scrollTo(0,0);});
   await settled(page);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' overflow');
   const camera=await canvas.getAttribute('data-camera');
   const bodyInFrame=async()=>{
    const b=JSON.parse(await canvas.getAttribute('data-body-bounds'));
    assert(b.left>=.02&&b.top>=.02&&b.right<=.98&&b.bottom<=.98,name+' clipped body: '+JSON.stringify(b));
   };
   await bodyInFrame();
   await capture(page,out+'/inspection-'+name+'.png');
   // Direct clicks remain available in sequence: no selector or reset workaround.
   for(const panel of data.agents.find(a=>a.id==='restaurant').panels){
    const hotspot=page.locator('.anatomy-hotspot[data-part="'+panel.id+'"]');
    await hotspot.click();
    await settled(page);
    assert.equal(await page.locator('#anatomy-part-select').inputValue(),panel.id);
    assert.equal(await canvas.getAttribute('data-camera'),camera,name+' camera shifted on '+panel.id);
    await bodyInFrame();
    assert.equal(await page.locator('.anatomy-hotspot').evaluateAll(nodes=>nodes.filter(n=>getComputedStyle(n).opacity!=='0'&&getComputedStyle(n).pointerEvents!=='none').length),11);
   }
   for(const part of ['protocols','memory']){
    await page.locator('.anatomy-hotspot[data-part="'+part+'"]').click();
    await page.evaluate(()=>{document.activeElement?.blur();scrollTo(0,0);});
    assert(await page.locator('#anatomy-inspector').isVisible());
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await capture(page,out+'/inspection-'+name+'-'+part+'.png');
   }
   // Manual orbit survives selection, closing and viewport changes.
   await canvas.focus();await page.keyboard.press('ArrowLeft');
   await page.waitForFunction(before=>document.querySelector('.anatomy-illustration canvas').dataset.camera!==before,camera);
   const orbit=await canvas.getAttribute('data-camera');
   assert.notEqual(orbit,camera);
   await page.locator('#anatomy-part-select').selectOption('protocols');await settled(page);
   assert.equal(await canvas.getAttribute('data-camera'),orbit);
   await page.getByRole('button',{name:'Close component details'}).click();await settled(page);
   assert.equal(await canvas.getAttribute('data-camera'),orbit);
   await bodyInFrame();
   await page.locator('#anatomy-part-select').selectOption('memory');await settled(page);
   await page.setViewportSize({width:width-30,height:height-30});await settled(page);
   await bodyInFrame();
   const direction=values=>[0,1,2].map(i=>values[i]-values[i+3]);
   const before=direction(orbit.split(',').map(Number)),after=direction((await canvas.getAttribute('data-camera')).split(',').map(Number));
   const dot=before.reduce((sum,v,i)=>sum+v*after[i],0)/(Math.hypot(...before)*Math.hypot(...after));
   assert(dot>.9999,name+' changed orbit on resize');
   await canvas.focus();
   for(let i=0;i<20;i++)await page.keyboard.press('+');
   await settled(page);
   await bodyInFrame();
   captures.push({name,width,height});
  }
  await page.setViewportSize({width:1440,height:1000});
  await options(page);await page.locator('#anatomy-reset').click();
  await page.getByRole('button',{name:'Chapters',exact:true}).click();
  assert(await page.locator('.sidebar').isVisible());
  await page.keyboard.press('Escape');
  assert(!(await page.locator('.sidebar').isVisible()));
  await page.getByRole('button',{name:'Read guide',exact:true}).click();
  assert(await page.locator('#chapter-body').isVisible());
  await page.getByRole('button',{name:'Read guide',exact:true}).click();
  await page.evaluate(()=>scrollTo(0,0));
  // The physical canvas itself is selectable, independent of DOM hotspots.
  await canvas.focus();await page.keyboard.press('ArrowLeft');await settled(page);
  assert.notEqual(await canvas.getAttribute('data-camera'),initial);
  // A lost graphics context must retain all component information.
  await page.locator('.anatomy-options').evaluate(el=>el.open=false);
  await canvas.evaluate(el=>el.dispatchEvent(new Event('webglcontextlost',{cancelable:true})));
  await page.locator('.anatomy-illustration.is-fallback .agent-machine').waitFor();
  await page.locator('#anatomy-part-select').selectOption('memory');
  assert.equal(await page.locator('#anatomy-panel-title').innerText(),'Storage tank');
  await capture(page,out+'/inspection-fallback.png');
  await page.goto(base+'/architecture?page=overview');
  assert.equal(await page.locator('.anatomy-illustration canvas').count(),0);
  assert(await page.locator('.sidebar').isVisible());
  await page.route('**/api/agent-anatomy',route=>route.fulfill({status:503,body:'Unavailable'}));
  await page.goto(base+'/architecture');await page.getByRole('button',{name:'Retry agent definitions'}).waitFor();
  await page.unroute('**/api/agent-anatomy');await page.getByRole('button',{name:'Retry agent definitions'}).click();
  await page.locator('.anatomy-team-panel').waitFor();
  await page.getByRole('button',{name:'Inspect Restaurant agent',exact:true}).click();
  await page.locator('.anatomy-illustration canvas').waitFor();
  await page.getByRole('button',{name:'Replay tour',exact:true}).click();
  await capture(page,out+'/tour-desktop.png');
  await page.setViewportSize({width:390,height:844});
  await capture(page,out+'/tour-mobile.png');
  assert.deepEqual(errors,[]);
  const result={checked_at:new Date().toISOString(),agents:data.agents.length,panels,render,webgl:true,team_story:true,generated_labels:true,real_headlines:true,real_robot_badges:true,first_visit_tour:true,tour_remembered:true,full_body_framing:true,sequential_part_clicks:true,selection_preserves_orbit:true,progressive_details:true,keyboard:true,source_dialog:true,card:true,finite_animation:true,reduced_motion:true,retry:true,context_loss_fallback:true,renderer_disposed:true,no_horizontal_page_overflow:true,captures};
  await fs.writeFile(out+'/anatomy-checks.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
 }catch(e){console.error('Page errors:',errors);console.error(await page.locator('.anatomy-illustration canvas').evaluateAll(nodes=>nodes.map(c=>({data:{...c.dataset},hidden:document.hidden,rect:c.getBoundingClientRect().toJSON()}))));await page.screenshot({path:out+'/inspection-failure.png',timeout:15000}).catch(()=>{});throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
