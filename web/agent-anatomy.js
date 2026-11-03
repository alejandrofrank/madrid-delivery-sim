/* The server owns every agent fact. This file supplies geometry and interaction only. */
(() => {
  const NS = "http://www.w3.org/2000/svg";
  const order = ["household", "restaurant", "market", "inventory", "fulfillment", "dispatcher", "courier", "customer_service", "judge"];
  const shapes = {
    mission: '<path d="M169 100h122l13 40v54H156v-54z"/><path d="M177 111h106l9 31H166z" class="machine-glass"/>',
    persona: '<rect x="185" y="151" width="90" height="31" rx="5"/><circle cx="207" cy="165" r="4"/><circle cx="253" cy="165" r="4"/><path d="M222 171h16"/>',
    tools: '<path d="M156 204h-25v58h-21m194-58h25v58h21"/><path d="M100 250v24h20m240-24v24h-20"/><circle cx="131" cy="224" r="8"/><circle cx="329" cy="224" r="8"/>',
    memory: '<rect x="152" y="211" width="34" height="89" rx="14"/><path d="M159 230h20m-20 15h20m-20 15h20m-20 15h20"/>',
    policy: '<path d="M143 194h174v119H143zM149 200l14 14m148-14-14 14m-148 93 14-14m148 14-14-14" class="machine-cage"/>',
    limits: '<rect x="276" y="211" width="27" height="64" rx="3"/><path d="M283 220h13m-13 11h13m-13 11h13m-13 11h13m-13 11h13"/>',
    model: '<rect x="198" y="214" width="65" height="61" rx="5"/><circle cx="230" cy="244" r="18"/><circle cx="230" cy="244" r="7"/><path d="M230 222v7m0 30v7m-22-22h7m30 0h7"/>',
    protocols: '<path d="M249 99V68h38V49"/><circle cx="287" cy="43" r="6"/><path d="M273 32a19 19 0 0 1 28 0M267 24a28 28 0 0 1 40 0"/>',
    events: '<path d="M156 124h-26v-18h-19m193 18h26v-18h19"/><path d="m113 99 10 7-10 7m231-14 10 7-10 7"/>',
    evals: '<rect x="209" y="283" width="53" height="23" rx="3"/><path d="m219 294 5 5 8-10m8 3h14m-14 7h14"/>',
    environment: '<rect x="137" y="326" width="186" height="38" rx="19"/><circle cx="159" cy="345" r="11"/><circle cx="206" cy="345" r="11"/><circle cx="254" cy="345" r="11"/><circle cx="301" cy="345" r="11"/><path d="M180 313v13m100-13v13"/>',
  };
  const labels = {
    mission: [42, 145, "M100 141h48"],
    persona: [355, 173, "M278 167h69"],
    tools: [40, 243, "M78 239h37"],
    memory: [40, 289, "M103 285h42"],
    policy: [350, 312, "M320 304h23"],
    limits: [355, 218, "M309 214h38"],
    model: [355, 264, "M266 260h81"],
    protocols: [338, 59, "M299 48h32"],
    events: [40, 86, "M101 82h29v17"],
    evals: [40, 318, "M85 314h35l10-12h72"],
    environment: [195, 393, "M230 367v11"],
  };
  function node(tag, text, cls) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }
  function svgNode(tag, attrs = {}) {
    const el = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, value));
    return el;
  }
  function machine(agent, select, small = false) {
    const svg = svgNode("svg", {viewBox: small ? "90 20 280 355" : "0 0 460 420", class: "agent-machine"});
    if (small) svg.setAttribute("aria-hidden", "true");
    else {
      svg.setAttribute("role", "group");
      svg.setAttribute("aria-label", agent.name+" agent components");
    }
    const body = svgNode("path", {d: "M151 194h158v120H151z", class: "machine-body"});
    svg.append(body);
    // The safety cage is drawn first so it never covers the individual controls.
    ["policy", ...Object.keys(shapes).filter(key => key !== "policy")].forEach(key => {
      const g = svgNode("g", {class: "machine-part", "data-part": key});
      g.innerHTML = shapes[key]; // Fixed, authored SVG only; no server text enters markup.
      if (!small) {
        const panel = agent.panels.find(p => p.id === key);
        g.setAttribute("role", "button");
        g.setAttribute("tabindex", "0");
        g.setAttribute("aria-label", panel.label+" - "+panel.technical_label);
        g.setAttribute("aria-controls", "anatomy-inspector");
        const [x, y, line] = labels[key];
        g.append(svgNode("path", {d: line, class: "part-leader"}));
        const label = svgNode("text", {x, y, class: "part-label"});
        label.textContent = panel.technical_label;
        g.append(label);
        g.addEventListener("click", () => select(key));
        g.addEventListener("keydown", event => {
          if (["Enter", " "].includes(event.key)) { event.preventDefault(); select(key); }
          if (["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(event.key)) {
            event.preventDefault();
            const parts = [...svg.querySelectorAll('[role="button"]')];
            const direction = ["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1;
            parts[(parts.indexOf(g) + direction + parts.length) % parts.length].focus();
          }
        });
      }
      svg.append(g);
    });
    return svg;
  }
  function sourceLink(path) {
    const a = node("a", path);
    const url = new URL(location.href);
    url.searchParams.set("source", path);
    a.href = url.pathname + url.search;
    a.dataset.source = path;
    return a;
  }
  let generation = 0, disposeCurrent = null, pendingData = null;
  function preload(){
    if(!pendingData)pendingData=fetch("/api/agent-anatomy",{cache:"no-store",credentials:"same-origin"})
      .then(response=>{if(!response.ok)throw new Error("Unavailable");return response.json();});
    return pendingData;
  }
  function unmount() { generation++; disposeCurrent?.(); disposeCurrent=null; }
  async function mount(host) {
    unmount(); const version=generation;
    host.replaceChildren(ProductUI.loading("Assembling the agent team"));
    host.setAttribute("aria-busy","true");
    try {
      const data=await preload();
      host.removeAttribute("aria-busy");
      if(version!==generation||host.hidden)return;
      render(host,data,version);
    } catch {
      if(version!==generation)return;
      pendingData=null;host.removeAttribute("aria-busy");
      const error=node("p","Agent definitions could not be loaded. Retry after the local service is ready.");
      error.setAttribute("role","alert");
      const retry=node("button","Retry agent definitions");retry.onclick=()=>mount(host);
      host.replaceChildren(error,retry);
    }
  }
  function render(host,data,version) {
    host.replaceChildren();host.dataset.fingerprint=data.input_fingerprint;
    const agents=[...data.agents].sort((a,b)=>order.indexOf(a.id)-order.indexOf(b.id));
    const params=new URLSearchParams(location.search);
    let selected=agents.find(a=>a.id===params.get("agent"))||agents.find(a=>a.id==="restaurant")||agents[0];
    let part=null,environment="all",scene=null,teamMode=false,paused=false,disposed=false,lastTrigger=null;
    const reduced=matchMedia('(prefers-reduced-motion: reduce)');
    let tourTimer=null,tourIndex=-1,tourPaused=false,autoTimer=null;
    const tourKey='mds-anatomy-tour-v1';
    const header=node("div",undefined,"anatomy-heading");
    const identity=node("div",undefined,"anatomy-identity");
    const name=node("h2"),mission=node("p");identity.append(name,mission);
    const actions=node("nav",undefined,"anatomy-actions");actions.setAttribute("aria-label","Anatomy views");
    const teamToggle=node("button","Back to team");
    const tourReplay=node("button","Replay tour");tourReplay.id="anatomy-tour-replay";
    const options=node("details",undefined,"anatomy-options");options.append(node("summary","View options"));
    const chapters=node("button","Chapters");chapters.setAttribute("aria-expanded","false");chapters.setAttribute("aria-controls","topics");
    const guide=node("button","Read guide");guide.setAttribute("aria-expanded","false");guide.setAttribute("aria-controls","chapter-body");
    const optionItems=node("div",undefined,"anatomy-option-items");options.append(optionItems);optionItems.append(guide,chapters);actions.append(teamToggle,tourReplay,options);header.append(identity,actions);host.append(header);
    chapters.onclick=()=>{
      const open=document.body.classList.toggle("anatomy-topics-open");chapters.setAttribute("aria-expanded",String(open));
    };
    guide.onclick=()=>{
      const open=document.body.classList.toggle("anatomy-reading");guide.setAttribute("aria-expanded",String(open));
      if(open)document.getElementById("chapter-body").scrollIntoView({behavior:"instant",block:"start"});
    };
    const workbench=node("div",undefined,"anatomy-workbench");
    const drawing=node("div",undefined,"anatomy-drawing");
    const illustration=node("div",undefined,"anatomy-illustration");
    illustration.setAttribute("aria-label","Inspect the agent's physical components");
    const hotspots=node("div",undefined,"anatomy-hotspots"),buttons={};
    Object.keys(shapes).forEach(key=>{
      const button=node("button",undefined,"anatomy-hotspot");button.dataset.part=key;
      button.setAttribute("tabindex", "0");button.setAttribute("aria-controls","anatomy-inspector");
      const marker=node("span",undefined,"hotspot-dot"),label=node("span",undefined,"hotspot-label");
      marker.setAttribute("aria-hidden","true");button.append(marker,label);
      button.onclick=()=>{stopTour();lastTrigger=button;choose(selected.id,key);};
      button.onpointerenter=()=>scene?.hover(key);button.onpointerleave=()=>scene?.hover(null);
      button.addEventListener("keydown",event=>{
        if(["ArrowRight","ArrowDown","ArrowLeft","ArrowUp"].includes(event.key)){
          event.preventDefault();const list=Object.values(buttons),direction=["ArrowRight","ArrowDown"].includes(event.key)?1:-1;
          list[(list.indexOf(button)+direction+list.length)%list.length].focus();
        }
        if(event.key==="Enter"){event.preventDefault();button.click();}
      });
      buttons[key]=button;hotspots.append(button);
    });
    hotspots.hidden=true;illustration.append(hotspots);drawing.append(illustration);
    const stageControls=node("div",undefined,"anatomy-stage-controls");
    const picker=node("label","Component","anatomy-part-picker");
    const select=node("select");select.id="anatomy-part-select";picker.append(select);
    const reset=node("button","Reset view");reset.id="anatomy-reset";
    const pause=node("button","Pause motion");pause.id="anatomy-pause";pause.setAttribute("aria-pressed","false");
    stageControls.append(picker);optionItems.append(reset,pause);drawing.append(stageControls);
    const hint=node("p","Click any part to see how it works","anatomy-hint");drawing.append(hint);
    const inspector=node("section",undefined,"anatomy-inspector");inspector.id="anatomy-inspector";inspector.hidden=true;
    inspector.setAttribute("aria-labelledby","anatomy-panel-title");
    const status=node("span","","sr-only");status.setAttribute("role", "status");
    const idle=node("div",undefined,"anatomy-inspector-idle");
    idle.append(node("p","Select a component"),node("p","Explore the code behind each part."));
    workbench.append(drawing,idle,inspector);host.append(workbench,status);
    select.onchange=()=>{stopTour();lastTrigger=select;choose(selected.id,select.value||null);};
    reset.onclick=()=>{stopTour();choose(selected.id,null);scene?.reset();};
    pause.onclick=()=>{paused=!paused;if(paused){story.pause();tourPaused=true;scheduleTour();}scene?.pause(paused);pause.textContent=paused?"Play motion":"Pause motion";pause.setAttribute("aria-pressed",String(paused));};
    const roster=node("nav",undefined,"anatomy-roster");roster.setAttribute("aria-label","Choose an agent");
    agents.forEach(agent=>{
      const button=node("button",agent.name,"team-agent");button.dataset.agent=agent.id;
      button.onclick=()=>{stopTour();setTeam(false);choose(agent.id,null);};roster.append(button);
    });
    host.append(roster);
    const story=window.AgentStory.mount(host,data,(id,trigger)=>{
      stopTour();lastTrigger=trigger;setTeam(false);choose(id,'mission');
      select.focus({preventScroll:true});
    });
    host.insertBefore(story.section,workbench);
    function setTeam(show,updateURL=true){
      teamMode=show;story.show(show);workbench.hidden=show;roster.hidden=show;
      teamToggle.hidden=show;name.textContent=show?data.story.title:selected.name;
      mission.textContent=show?data.story.summary:selected.introduction;
      if(!show){scene?.wake();if(!reduced.matches&&workbench.animate)workbench.animate([{opacity:.65},{opacity:1}],{duration:220,easing:'cubic-bezier(.16,1,.3,1)'});}
      if(updateURL){
        const url=new URL(location.href);
        if(show){url.searchParams.delete('agent');url.searchParams.delete('part');}
        else{url.searchParams.set('agent',selected.id);if(part)url.searchParams.set('part',part);}
        history.replaceState({},'',url.pathname+url.search);
      }
    }
    teamToggle.onclick=()=>{stopTour();setTeam(true);story.focus(selected.id);};
    const tour=node('aside',undefined,'anatomy-tour');tour.hidden=true;tour.setAttribute('aria-label','Agent tour');
    const tourCaption=node('p');tourCaption.setAttribute('role','status');
    const tourControls=node('div'),tourPause=node('button','Pause tour'),tourNext=node('button','Next'),tourSkip=node('button','Skip tour');
    tourPause.id='tour-pause';tourNext.id='tour-next';tourSkip.id='tour-skip';
    tourControls.append(tourPause,tourNext,tourSkip);tour.append(tourCaption,tourControls);host.insertBefore(tour,story.section);
    function rememberTour(){try{localStorage.setItem(tourKey,'seen');}catch{/* Private browsing still permits this visit. */}}
    function stopTour(){clearTimeout(autoTimer);clearTimeout(tourTimer);if(tourIndex>=0)rememberTour();tourIndex=-1;tour.hidden=true;}
    function scheduleTour(){
      clearTimeout(tourTimer);tourPause.textContent=tourPaused?'Resume tour':'Pause tour';tourPause.hidden=reduced.matches;
      if(tourIndex>=0&&!tourPaused&&!reduced.matches&&!document.hidden)tourTimer=setTimeout(nextTour,5500);
    }
    function showTourStep(){
      const step=data.tour[tourIndex];setTeam(false);choose(selected.id,step.part);
      tourCaption.textContent=(tourIndex+1)+' of '+data.tour.length+' \u00b7 '+step.caption;
      tourNext.textContent=tourIndex===data.tour.length-1?'Finish tour':'Next';
      tour.hidden=false;scheduleTour();
    }
    function nextTour(){if(tourIndex===data.tour.length-1){stopTour();setTeam(true);tourReplay.focus({preventScroll:true});return;}tourIndex++;showTourStep();}
    function startTour(){stopTour();story.pause();tourIndex=0;tourPaused=reduced.matches;showTourStep();}
    tourNext.onclick=nextTour;tourSkip.onclick=()=>{stopTour();setTeam(true);tourReplay.focus({preventScroll:true});};
    tourPause.onclick=()=>{tourPaused=!tourPaused;scheduleTour();};tourReplay.onclick=startTour;
    const motionChanged=()=>{if(reduced.matches)tourPaused=true;scheduleTour();};
    const visibilityChanged=()=>{if(document.hidden){tourPaused=true;scheduleTour();}};
    reduced.addEventListener('change',motionChanged);document.addEventListener('visibilitychange',visibilityChanged);
    const provenance=node("p","Built from the agents' real configuration files and test results.","anatomy-provenance");
    host.append(provenance);
    function closePanel(){stopTour();choose(selected.id,null);if(lastTrigger?.isConnected)lastTrigger.focus();else select.focus();}
    const keydown=event=>{
      if(event.key!=="Escape")return;
      if(document.querySelector("dialog[open]"))return;
      if(tourIndex>=0){stopTour();tourReplay.focus();return;}
      if(document.body.classList.contains("anatomy-topics-open")){
        document.body.classList.remove("anatomy-topics-open");chapters.setAttribute("aria-expanded","false");chapters.focus();
      }else if(part)closePanel();
      else if(!teamMode){setTeam(true);story.focus(selected.id);}
    };
    host.addEventListener("keydown",keydown);
    function choose(id,key,updateURL=true){
      const changed=selected.id!==id;selected=agents.find(a=>a.id===id)||selected;
      if(changed)environment="all";
      part=selected.panels.some(p=>p.id===key)?key:null;
      name.textContent=teamMode?data.story.title:selected.name;mission.textContent=teamMode?data.story.summary:selected.introduction;
      roster.querySelectorAll("button").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.agent===selected.id)));
      const placeholder=node("option","Inspect a component");placeholder.value="";
      select.replaceChildren(placeholder,...selected.panels.map(p=>{const option=node("option",p.label);option.value=p.id;return option;}));select.value=part||"";
      for(const [id,button] of Object.entries(buttons)){
        const p=selected.panels.find(p=>p.id===id);button.setAttribute("aria-label",p.label+" \u2014 "+p.technical_label);
        button.setAttribute("aria-pressed",String(id===part));
        const label=button.querySelector('.hotspot-label');label.replaceChildren(node('strong',p.label),node('small',p.technical_label));
      }
      illustration.querySelectorAll(".agent-machine").forEach(svg=>svg.remove());
      if(illustration.classList.contains("is-fallback")){
        const svg=machine(selected,key=>{stopTour();choose(selected.id,key);});illustration.append(svg);
        svg.querySelectorAll("[data-part]").forEach(p=>p.setAttribute("aria-pressed",String(p.dataset.part===part)));
      }
      if(changed)scene?.agent(selected);
      scene?.focus(part);
      inspector.hidden=!part;idle.hidden=!!part;workbench.classList.toggle("has-selection",!!part);illustration.classList.toggle("has-part",!!part);
      if(part)renderPanel();
      status.textContent=part?selected.name+": "+selected.panels.find(p=>p.id===part).title:selected.name;
      if(updateURL){
        const url=new URL(location.href);url.searchParams.set("agent",selected.id);
        if(part)url.searchParams.set("part",part);else url.searchParams.delete("part");
        history.replaceState({},"",url.pathname+url.search);
      }
    }
    function renderPanel(){
      const basePanel=selected.panels.find(p=>p.id===part),variant=basePanel.environments?.[environment];
      const panel=variant?{...basePanel,...variant}:basePanel;
      const panelHeader=node("div",undefined,"anatomy-panel-heading");
      const title=node("h3",panel.part);title.id="anatomy-panel-title";
      const close=node("button","Close");close.setAttribute("aria-label","Close component details");close.onclick=closePanel;
      const heading=node("div");
      heading.append(title,node("p",panel.label,"anatomy-panel-topic"),node("small",panel.technical_label,"anatomy-panel-term"));
      panelHeader.append(heading,close);inspector.replaceChildren(panelHeader,node("p",panel.summary,"anatomy-summary"));
      const headline=node('section',undefined,'anatomy-headline');headline.append(node('h4',panel.headline.text));
      const value=node('p',undefined,'anatomy-headline-value');value.append(node('strong',String(panel.headline.value)),node('span',panel.headline.unit));
      const bullets=node('ul');panel.headline.bullets.forEach(text=>bullets.append(node('li',text)));headline.append(value,bullets);inspector.append(headline);
      if(basePanel.environments){
        const label=node("label","Environment","anatomy-part-picker"),choice=node("select");choice.id="anatomy-environment";
        const all=node("option","All environments");all.value="all";choice.append(all);
        Object.entries(basePanel.environments).forEach(([id,view])=>{const option=node("option",view.label);option.value=id;choice.append(option);});
        choice.value=environment;choice.onchange=()=>{environment=choice.value;renderPanel();};label.append(choice);inspector.append(label);
      }
      function numbers(entries){
        const dl=node("dl",undefined,"anatomy-numbers");
        entries.forEach(([label,value])=>{const row=node("div");row.append(node("dt",label),node("dd",String(value)));dl.append(row);});return dl;
      }
      const entries=(variant?Object.entries(panel.numbers):panel.number_rows.map(row=>[row.label,row.value]));
      if(panel.reference){const memory=node("div");inspector.append(memory);window.AgentMemory.mount(memory,panel.reference);}

      const technical=node("details",undefined,"anatomy-technical");technical.append(node("summary","Details & source"));
      technical.append(numbers(entries));
      const details=node("div",undefined,"anatomy-explanation");panel.details.forEach(text=>details.append(node("p",text)));technical.append(details);
      if(panel.results?.length){
        const tableWrap=node("div",undefined,"anatomy-results"),table=node("table");
        table.append(node("caption","Recorded held-out results \u00b7 scripted offline ADK"));
        const head=node("thead"),tr=node("tr");
        ["Test group","Cases / attempts each","All-attempt pass rate (pass^k) / 95% interval","Cost per success (USD)","95th-percentile time (p95)"].forEach(text=>{const th=node("th",text);th.scope="col";tr.append(th);});head.append(tr);
        const body=node("tbody");
        panel.results.forEach(result=>{
          const row=node("tr");
          [panel.result_labels[result.arm]||result.arm,result.cases+" \u00d7 "+result.repeat,Math.round(result.pass_power_k*100)+"% / ["+result.pass_power_k_ci95.map(n=>Math.round(n*100)+"%").join(", ")+"]",result.cost_per_success_usd===null?"Unmeasured":"$"+result.cost_per_success_usd.toFixed(4),result.p95_latency_ms.toFixed(1)+" ms"].forEach(text=>row.append(node("td",text)));body.append(row);
        });table.append(head,body);tableWrap.append(table,node('p','pass^k: cases that pass every attempt. The 95% bootstrap interval shows variation across these cases, not certainty on future work. p95: 95% of recorded attempts finished within this time.','anatomy-eval-key'));technical.append(tableWrap);
      }
      if(panel.card){
        const disclosure=node("details",undefined,"anatomy-card");
        disclosure.append(node("summary","Inspect the generated Agent Card"));
        const card=node('dl',undefined,'anatomy-card-fields');
        for(const row of panel.card_fields){const field=node('div');field.append(node('dt',row.label),node('dd',row.value));card.append(field);}
        disclosure.append(card);technical.append(disclosure);
      }
      const links=node("nav",undefined,"anatomy-sources");links.setAttribute("aria-label","Evidence for this part");
      panel.sources.forEach(path=>{const link=sourceLink(path);link.textContent=path.split("/").slice(-2).join("/");link.title=path;links.append(link);});
      technical.append(links);
      const reference=node("details",undefined,"anatomy-full-reference");
      reference.append(node("summary","Full reference \u00b7 read here"));
      const article=node("div");reference.append(article);
      reference.ontoggle=()=>{if(reference.open&&!article.childElementCount)window.AgentReference.mount(article,panel.chapter);};
      inspector.append(technical,reference);
    }
    function fallback(){
      if(disposed)return;
      scene=null;hotspots.hidden=true;illustration.classList.add("is-fallback");
      pause.hidden=true;hint.textContent="3D unavailable \u00b7 Select a labelled part or use the component menu.";
      choose(selected.id,part,false);
    }
    choose(selected.id,params.get("part"),false);
    setTeam(!params.has('agent')&&!params.has('part'),false);
    let seen=false;try{seen=localStorage.getItem(tourKey)==='seen';}catch{}
    if(teamMode&&!seen)autoTimer=setTimeout(startTour,2400);
    import('./agent-anatomy-3d.js?v=0f21cabb011a').then(({createAgentScene,createAgentModel})=>{
      if(disposed||version!==generation)return;
      try{
        story.attachFactory(createAgentModel);
        scene=createAgentScene(illustration,{buttons,onPart:key=>{stopTour();choose(selected.id,key);},onFailure:fallback});
        scene.agent(selected);scene.focus(part);scene.pause(paused);hotspots.hidden=false;
      }catch{fallback();}
    }).catch(()=>{story.fallback();fallback();});
    disposeCurrent=()=>{
      disposed=true;stopTour();story.dispose();scene?.dispose();scene=null;
      reduced.removeEventListener("change",motionChanged);document.removeEventListener("visibilitychange",visibilityChanged);
      host.removeEventListener("keydown",keydown);
      document.body.classList.remove("anatomy-topics-open","anatomy-reading");
    };
  }
  window.AgentAnatomy={mount,unmount,preload};
})();
