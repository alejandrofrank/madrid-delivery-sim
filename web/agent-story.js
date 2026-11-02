/* One illustrated order. All role and handoff descriptions come from the API. */
window.AgentStory=(()=>{
 const make=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
 function mount(host,data,choose,machine){
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  const section=make('section',undefined,'anatomy-team-panel');section.setAttribute('aria-label','How one order moves');
  const tools=make('div',undefined,'anatomy-team-toolbar');
  const caption=make('p','Click a robot to see how it works.','story-caption');
  const replay=make('button',reduced.matches?'Next step':'Play order');replay.id='story-play';
  tools.append(caption,replay);section.append(tools);
  const flow=make('ol',undefined,'anatomy-flow');flow.setAttribute('aria-label','Order journey');
  const cards=new Map();
  function actor(agent,cls){
   const button=make('button',undefined,cls);button.dataset.agent=agent.id;
   const portrait=make('span',undefined,'story-portrait');portrait.append(machine(agent,null,true));
   button.append(portrait);button.setAttribute('aria-label','Inspect '+agent.name+' agent');
   button.onclick=()=>{pause();choose(agent.id,button);};
   const entries=cards.get(agent.id)||[];entries.push(portrait);cards.set(agent.id,entries);
   return button;
  }
  const steps=data.story.steps.map((step,index)=>{
   const agent=data.agents.find(a=>a.id===step.agent),li=make('li',undefined,'story-step');
   li.dataset.step=index;li.dataset.kind=step.kind;
   const button=agent?actor(agent,'team-diagram-agent'):make('div',undefined,'team-diagram-agent story-order-input');
   if(!agent){
    const portrait=make('span',undefined,'story-portrait story-bag');portrait.setAttribute('aria-hidden','true');
    portrait.innerHTML='<svg viewBox="0 0 100 110"><path d="M25 38h50l6 55H19z M35 38V26a15 15 0 0 1 30 0v12 M36 59h28 M36 70h20" fill="none" stroke="currentColor" stroke-width="2"/></svg>';button.append(portrait);
   }
   const text=make('span',undefined,'story-step-copy');
   text.append(make('span',String(index+1).padStart(2,'0'),'story-number'),make('strong',step.label),make('span',agent?agent.name:'Demo input','story-role'),make('span',step.summary,'story-description'));
   button.append(text);li.append(button);
   if(step.handoff){
    const link=make('div',undefined,'story-handoff');link.dataset.kind=step.kind;
    const track=make('span',undefined,'story-track');track.setAttribute('aria-hidden','true');
    track.append(make('span',undefined,'story-order'));
    link.append(track,make('span',step.handoff));li.append(link);
   }
   flow.append(li);return li;
  });
  section.append(flow);
  const state=make('p',undefined,'story-current');state.setAttribute('role','status');section.append(state);
  const legend=make('dl',undefined,'story-legend');
  for(const entry of data.story.legend){
   const row=make('div'),term=make('dt'),sample=make('i',undefined,'story-legend-line');sample.dataset.kind=entry.kind;sample.setAttribute('aria-hidden','true');
   term.append(sample,document.createTextNode(entry.label));row.append(term,make('dd',entry.detail));legend.append(row);
  }
  section.append(legend,make('p',data.story.note,'story-note'));
  const support=make('section',undefined,'story-support');support.setAttribute('aria-label','Other agents in the team');
  support.append(make('h3','Other parts of the team'));
  const supportList=make('div',undefined,'story-support-list');
  for(const entry of data.story.support){
   const agent=data.agents.find(a=>a.id===entry.agent),button=actor(agent,'story-specialist');
   const copy=make('span');copy.append(make('strong',agent.name),make('span',entry.summary));button.append(copy);supportList.append(button);
  }
  support.append(supportList);section.append(support);host.append(section);
  let current=0,timer=null,playing=false,shown=false;
  function update(){
   steps.forEach((li,index)=>{li.classList.toggle('is-current',index===current);li.classList.toggle('is-travelling',index===current&&playing&&!reduced.matches);if(index===current)li.setAttribute('aria-current','step');else li.removeAttribute('aria-current');});
   const step=data.story.steps[current];state.textContent=(current+1)+' of '+steps.length+' \u00b7 '+step.label+': '+step.summary+'.';
   replay.textContent=reduced.matches?'Next step':playing?'Pause order':current===steps.length-1?'Replay order':'Play order';
   replay.setAttribute('aria-pressed',String(playing));
  }
  function pause(){clearTimeout(timer);timer=null;playing=false;update();}
  function schedule(){
   clearTimeout(timer);
   if(!playing||!shown||reduced.matches||document.hidden)return;
   timer=setTimeout(()=>{if(current===steps.length-1){pause();return;}current++;update();schedule();},2800);
  }
  replay.onclick=()=>{
   if(reduced.matches){current=(current+1)%steps.length;update();return;}
   if(playing){pause();return;}if(current===steps.length-1)current=0;playing=true;update();schedule();
  };
  const change=()=>pause();reduced.addEventListener('change',change);
  const visibility=()=>{if(document.hidden)pause();};document.addEventListener('visibilitychange',visibility);
  const observer=new IntersectionObserver(entries=>{if(!entries[0]?.isIntersecting)pause();});observer.observe(section);
  update();
  return {section,pause,
   show(value){shown=value;section.hidden=!value;if(!value)pause();},
   portraits(render){for(const agent of data.agents){const source=render(agent);for(const place of cards.get(agent.id)||[]){const image=make('img');image.src=source;image.alt='';image.width=180;image.height=210;place.replaceChildren(image);}}},
   focus(id){section.querySelector('[data-agent="'+id+'"]')?.focus({preventScroll:true});},
   dispose(){pause();observer.disconnect();reduced.removeEventListener('change',change);document.removeEventListener('visibilitychange',visibility);}
  };
 }
 return {mount};
})();
