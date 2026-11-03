/* An illustrated order in one shared place; role and handoff copy comes from the API. */
window.AgentStory=(()=>{
 const make=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
 function mount(host,data,choose){
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  const section=make('section',undefined,'anatomy-team-panel');section.setAttribute('aria-label','How one order moves');
  const tools=make('div',undefined,'anatomy-team-toolbar');
  const caption=make('p','Click a robot to see how it works.','story-caption');
  const replay=make('button',reduced.matches?'Next step':'Play order');replay.id='story-play';
  const reset=make('button','Reset scene');reset.className='story-reset';
  const actions=make('div');actions.append(reset,replay);tools.append(caption,actions);section.append(tools);
  const viewport=make('div',undefined,'delivery-scene-viewport');viewport.tabIndex=0;viewport.setAttribute('aria-label','Agent workspaces. Scroll sideways on a small screen.');
  const place=make('div',undefined,'delivery-scene');viewport.append(place);section.append(viewport);
  const mobileHint=make('p','Swipe sideways to explore the rooms.','scene-mobile-hint');section.append(mobileHint);
  const loading=ProductUI.loading('Building the shared workspace','Placing the robots and their work areas.');place.append(loading);
  const flow=make('ol',undefined,'anatomy-flow');flow.setAttribute('aria-label','Order journey');
  const steps=data.story.steps.map((step,index)=>{
   const li=make('li',undefined,'story-step');li.dataset.step=index;
   const button=make('button');button.append(make('span',String(index+1).padStart(2,'0'),'story-number'),make('span',step.label));
   button.onclick=()=>{pause();current=index;progress=1;update();};li.append(button);flow.append(li);return li;
  });
  section.append(flow);
  const state=make('p',undefined,'story-current');state.setAttribute('role','status');section.append(state);
  const roles=make('div',undefined,'story-roles');roles.setAttribute('role','group');roles.setAttribute('aria-label','Inspect an agent');
  const buttons=new Map();
  for(const agent of data.agents){
   const button=make('button',undefined,'story-role-button');button.dataset.agent=agent.id;button.style.setProperty('--role-color',agent.visual.color);
   button.setAttribute('aria-label','Inspect '+agent.name+' agent');button.append(window.AgentRoleSymbols.icon(agent.visual),make('span',agent.name));
   button.onclick=()=>open(agent.id);button.onmouseenter=button.onfocus=()=>scene?.highlight(agent.id);button.onmouseleave=button.onblur=()=>scene?.highlight(null);
   buttons.set(agent.id,button);roles.append(button);
  }
  section.append(roles);
  const explanation=make('details',undefined,'story-explanation');explanation.append(make('summary','How agents communicate'));
  const legend=make('dl',undefined,'story-legend');
  for(const entry of data.story.legend){
   const row=make('div'),term=make('dt'),sample=make('i',undefined,'story-legend-line');sample.dataset.kind=entry.kind;sample.setAttribute('aria-hidden','true');
   term.append(sample,document.createTextNode(entry.label));row.append(term,make('dd',entry.detail));legend.append(row);
  }
  const handoffs=make('ol',undefined,'story-handoffs');
  for(const step of data.story.steps.filter(s=>s.handoff)){const li=make('li');li.append(make('strong',step.label+': '),document.createTextNode(step.handoff));handoffs.append(li);}
  const communication=make('div',undefined,'story-communication');communication.append(make('strong','One bag. Separate messages.'),make('p','Blue requests go through the controller. Green tracks carry the bag; purple dots carry review evidence.'));
  section.insertBefore(communication,viewport);
  section.insertBefore(legend,flow);
  explanation.append(make('p','Each work handoff is recorded in a durable queue so it can be retried. The green track shows the physical bag, not the queue.'),handoffs,make('p',data.story.note,'story-note'));section.append(explanation);host.append(section);
  let current=0,progress=0,playing=false,shown=false,disposed=false,scene=null,raf=0,last=0,factory=null,loadingScene=false,fallback=null;
  function open(id){pause();choose(id,buttons.get(id));}
  function drawState(){scene?.setState(current,progress,playing);if(fallback){fallback.dataset.step=String(current);fallback.querySelectorAll('[data-agent]').forEach(el=>el.classList.toggle('is-owner',el.dataset.agent===data.story.steps[current].agent));}}
  function update(){
   steps.forEach((li,index)=>{li.classList.toggle('is-current',index===current);if(index===current)li.setAttribute('aria-current','step');else li.removeAttribute('aria-current');});
   const step=data.story.steps[current];state.textContent=(current+1)+' of '+steps.length+' · '+step.label+': '+step.summary+'.';
   if(step.handoff&&current<steps.length-1){const next=data.story.steps[current+1];state.textContent+=' '+(step.agent?data.agents.find(a=>a.id===step.agent).name:'Order')+' → '+data.agents.find(a=>a.id===next.agent).name+': '+step.handoff.replace(/\s+(to|for)$/, '')+'.';}
   replay.textContent=reduced.matches?'Next step':playing?'Pause order':current===steps.length-1?'Replay order':'Play order';
   replay.setAttribute('aria-pressed',String(playing));drawState();
  }
  function pause(){playing=false;last=0;cancelAnimationFrame(raf);update();}
  function tick(now){
   if(!playing||!shown||disposed||reduced.matches||document.hidden)return;
   if(last)progress+=(now-last)/2800;last=now;
   if(progress>=1){if(current===steps.length-1){progress=1;pause();return;}current++;progress=0;update();}else drawState();
   raf=requestAnimationFrame(tick);
  }
  replay.onclick=()=>{
   if(reduced.matches){current=(current+1)%steps.length;progress=1;update();return;}
   if(playing){pause();return;}if(current===steps.length-1){current=0;progress=0;}else if(progress>=1){progress=0;}
   playing=true;last=0;update();raf=requestAnimationFrame(tick);
  };
  reset.onclick=()=>{scene?.reset();viewport.scrollTo({left:0,behavior:'instant'});};
  function flatScene(){
   scene=null;place.replaceChildren();place.classList.add('is-fallback');reset.hidden=true;
   const message=make('p','3D is unavailable. Explore the same team on this floor plan.','scene-fallback-note');place.append(message);
   fallback=make('div',undefined,'scene-plan');
   const zones=[['Stock & packing',['inventory','fulfillment','market','restaurant']],['Delivery',['dispatcher','courier','household']],['Review & support',['judge','customer_service']]];
   for(const [title,ids]of zones){const zone=make('section');zone.append(make('h3',title));
    for(const id of ids){const a=data.agents.find(a=>a.id===id),b=make('button');b.dataset.agent=id;b.style.setProperty('--role-color',a.visual.color);
     b.append(window.AgentRoleSymbols.icon(a.visual),document.createTextNode(a.name));b.onclick=()=>open(id);zone.append(b);}fallback.append(zone);}
   place.append(fallback);drawState();
  }
  async function loadScene(){
   if(!factory||loadingScene||scene||disposed)return;loadingScene=true;
   try{
    const {createDeliveryScene}=await import('./agent-delivery-scene.js?v=9fa99a7cc090');
    if(disposed)return;
    scene=createDeliveryScene(place,data,{createAgentModel:factory,onAgent:open,onFailure:flatScene});
    loading.remove();scene.show(shown);drawState();
   }catch(error){console.warn('Delivery scene unavailable',error);flatScene();}
   finally{loadingScene=false;}
  }
  const change=()=>pause();reduced.addEventListener('change',change);
  const visibility=()=>{if(document.hidden)pause();};document.addEventListener('visibilitychange',visibility);
  const observer=new IntersectionObserver(entries=>{if(!entries[0]?.isIntersecting)pause();});observer.observe(section);
  update();
  return {section,pause,attachFactory(value){factory=value;loadScene();},fallback:flatScene,
   show(value){shown=value;section.hidden=!value;scene?.show(value);if(!value)pause();},
   focus(id){buttons.get(id)?.focus({preventScroll:true});},
   dispose(){disposed=true;pause();scene?.dispose();observer.disconnect();reduced.removeEventListener('change',change);document.removeEventListener('visibilitychange',visibility);}
  };
 }
 return {mount};
})();
