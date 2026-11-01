/* Local simulation controls; server evidence is always rendered as text. */
"use strict";
const ChaosUI = (() => {
  const el = id => document.getElementById(id);
  const names = {heavy_rain:"Heavy rain",metro_strike:"Metro strike",restaurant_outage:"Restaurant outage",courier_offline:"Courier offline",demand_surge:"Demand surge"};
  const districts = {chamberi:"Chamberí",retiro:"Retiro",vallecas:"Puente de Vallecas"};
  const safe = value => String(value ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const time = s => `${String(10+Math.floor(s/3600)).padStart(2,"0")}:${String(Math.floor(s%3600/60)).padStart(2,"0")}`;
  let locations = [], layer, current, sending = false, targetKey = "", evidenceKey = "", lastRun, selectedEvent;
  function scope() {
    const kind = el("chaos-kind").value, targeted = ["restaurant_outage","courier_offline"].includes(kind);
    el("chaos-target-label").hidden = !targeted;
    el("chaos-district-label").hidden = targeted;
    el("chaos-district").lastElementChild.disabled = ["metro_strike","demand_surge"].includes(kind);
    if(el("chaos-district").selectedOptions[0].disabled) el("chaos-district").value = "retiro";
    const options = kind === "courier_offline" ? (current?.couriers || []).map(c=>[c.id,`${c.id} · ${c.status.replaceAll("_"," ")}`]) : locations.filter(l=>l.kind==="store").map(l=>[l.id,l.name]);
    const key = JSON.stringify([kind,options.map(o=>o[0])]);
    if(key !== targetKey) {
      targetKey = key;
      el("chaos-target").replaceChildren(new Option("Choose active target","auto"),...options.map(o=>new Option(o[1],o[0])));
    }
  }
  function hull(points) {
    const sorted = [...new Map(points.map(p=>[p.join(","),p])).values()].sort((a,b)=>a[0]-b[0]||a[1]-b[1]);
    const cross = (o,a,b)=>(a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0]);
    const half = rows => {const result=[];for(const p of rows){while(result.length>1&&cross(result.at(-2),result.at(-1),p)<=0)result.pop();result.push(p);}return result.slice(0,-1);};
    return [...half(sorted),...half([...sorted].reverse())].map(([lon,lat])=>[lat,lon]);
  }
  function overlays(events) {
    if(!layer)return;
    layer.clearLayers();
    for(const event of events.filter(e=>e.state==="active")) {
      const style={color:"#efad3f",weight:2,opacity:.85,fillOpacity:.09,interactive:false};
      if(event.target) {
        const target = locations.find(l=>l.id===event.target) || current.couriers.find(c=>c.id===event.target);
        if(target)L.circle([target.lat,target.lon],{...style,radius:250}).addTo(layer);
      } else {
        for(const district of event.district ? [districts[event.district]] : Object.values(districts)) {
          const points = locations.filter(l=>l.district===district).map(l=>[l.lon,l.lat]);
          if(points.length>2)L.polygon(hull(points),style).addTo(layer);
        }
      }
    }
  }
  async function runOptions() {
    const mode=el("chaos-mode").value;
    if(mode==="demo")return {chaos:await api("/api/chaos/demo"),duration:7200,wall_seconds:60};
    if(mode==="manual")return {chaos:{}};
    if(mode==="random")return {chaos:{random_events:5}};
    return {};
  }
  function update(next) {
    current=next;
    const replay=Boolean(next.replay?.read_only);
    const chaos=next.chaos, run=next.run, open=Boolean(!replay&&chaos&&["ready","running"].includes(run?.status));
    el("chaos-trigger").disabled=!open||sending;
    el("chaos-demo").disabled=run?.status==="running";
    if(lastRun!==run?.id){
      lastRun=run?.id;
      selectedEvent=null;
      el("chaos-feedback").textContent=open?"Events begin at the next simulation minute.":"Start a Chaos session to enable event controls.";
      if(chaos)el("chaos-panel").open=true;
      el("chaos-controls-disclosure").open=Boolean(chaos&&!chaos.events.length);
    }
    if(chaos&&["complete","failed"].includes(run?.status))el("chaos-feedback").textContent="This run has ended. Start a new Chaos session to trigger events.";
    if(replay) {
      el("chaos-feedback").textContent="Recorded shift · events and agent decisions are read-only.";
      el("chaos-demo").disabled=true;
      el("chaos-controls-disclosure").hidden=true;
    }
    scope();
    const events=chaos?.events||[], active=events.filter(e=>e.state==="active").length;
    el("chaos-status").textContent=chaos?`${active} active · ${events.length} events · ${run.status}`:"Off · enable in simulation controls";
    const modes=new Set((chaos?.replans||[]).map(w=>w.result?.mode).filter(Boolean));
    el("chaos-mode-note").textContent=(modes.has("scripted-offline")?"Scripted demo · ":modes.has("model")?"Model decisions · ":"")+"Customer messages stay inside this simulation.";
    overlays(events);
    const key=JSON.stringify(chaos);
    if(key===evidenceKey)return;
    evidenceKey=key;
    const selectedId=selectedEvent||events.find(e=>e.state==="active")?.id||events[0]?.id;
    el("chaos-timeline").innerHTML=events.length?'<div class="chaos-markers">'+events.map(e=>`<button type="button" data-event="${safe(e.id)}" aria-pressed="${e.id===selectedId}" class="${safe(e.state)}"><time>${time(e.start_sim)}</time><strong>${names[e.kind]}</strong><span>${safe(e.state)}</span></button>`).join("")+'</div><ol>'+events.filter(e=>e.id===selectedId).map(event=>{
      const m=chaos.metrics.find(row=>row.id===event.id);
      const recovery=m.time_to_recover_seconds===null?"Pending":`${Math.ceil(m.time_to_recover_seconds/60)} min`;
      return `<li class="chaos-event ${safe(event.state)}"><time>${time(event.start_sim)}</time><div><strong>${names[event.kind]}</strong> <span class="badge">${safe(event.state)}</span><p>${safe(event.target||districts[event.district]||"All service areas")} · until ${time(event.end_sim)}</p><dl><div><dt>Recovered in</dt><dd>${recovery}</dd></div><div><dt>Saved / lost</dt><dd>${m.orders_saved} / ${m.orders_lost}</dd></div><div><dt>Late</dt><dd>${m.late_deliveries}</dd></div><div><dt>Refunds</dt><dd>€${m.refund_cost_eur.toFixed(2)}</dd></div><div><dt>Extra tokens</dt><dd>${m.extra_tokens}</dd></div><div><dt>Extra model cost</dt><dd>$${m.extra_token_cost_usd.toFixed(4)}</dd></div></dl>${m.failed_replans?`<p class="chaos-error">${m.failed_replans} recovery turns need review.</p>`:""}</div></li>`;
    }).join("")+'</ol><p class="chaos-map-note">Saved means affected orders delivered. Overlapping event totals are not additive. Recovery includes the disruption ending and affected orders settling.</p>':'<p>No disruptions recorded. Trigger an event or start the demo.</p>';
    el("chaos-replan-count").textContent=chaos?.replans.length||0;
    el("chaos-decisions").innerHTML=(chaos?.replans||[]).map(w=>`<article><strong>${safe(w.agent)}</strong> <span class="badge">${safe(w.state)}</span><p>${safe(w.order_id)} · ${safe(w.disruption)} · ${safe(w.result?.mode||"Awaiting decision")}</p><p>${safe(w.result?.plan?.action?.replaceAll("_"," ")||w.result?.error||"Agent has not responded yet.")}${w.result?.plan?.reason?" · "+safe(w.result.plan.reason):""}</p><code>${safe((w.result?.tool_calls||[]).map(c=>c.name).join(" → "))}</code></article>`).join("")+(chaos?.contacts||[]).map(c=>`<article><strong>Customer message · ${safe(c.order_id)}</strong><p>${safe(c.message)}</p><small>${time(c.sim_time)} · ${safe(c.approval_status.replaceAll("_"," "))} · refund €${c.refund_eur.toFixed(2)}</small></article>`).join("");
  }
  el("chaos-kind").addEventListener("change",scope);
  el("chaos-timeline").addEventListener("click",event=>{const button=event.target.closest("[data-event]");if(button){selectedEvent=button.dataset.event;evidenceKey="";update(current);el("chaos-timeline").querySelector(`[data-event="${selectedEvent}"]`).focus();}});
  el("chaos-demo").addEventListener("click",()=>{el("chaos-mode").value="demo";el("start").click();});
  el("chaos-form").addEventListener("submit",async event=>{
    event.preventDefault();
    if(sending||!current?.chaos)return;
    sending=true;el("chaos-trigger").disabled=true;
    const kind=el("chaos-kind").value;
    const payload={id:crypto.randomUUID(),kind,duration:Number(el("chaos-minutes").value)*60,severity:Number(el("chaos-severity").value)};
    if(["restaurant_outage","courier_offline"].includes(kind))payload.target=el("chaos-target").value;
    else payload.district=el("chaos-district").value||null;
    try {
      const response=await fetch(`/api/runs/${current.run.id}/chaos`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
      const result=await response.json();
      if(!response.ok)throw new Error(typeof result.detail==="string"?result.detail:"Check the event duration and target, then try again.");
      el("chaos-feedback").textContent=`${names[kind]} scheduled for the next simulation minute.`;
      await poll();
    } catch(e){el("chaos-feedback").textContent=e.message;}
    finally{sending=false;update(current);}
  });
  return {runOptions,update,setWorld(city,map){locations=city.locations;layer=L.layerGroup().addTo(map);scope();}};
})();
