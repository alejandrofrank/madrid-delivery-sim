/* All dynamic strings enter the DOM as text. LLM replies are untrusted content. */
"use strict";
const $ = (id) => document.getElementById(id);
const colors = {bike: "#63d5c5", moto: "#63d5c5", van: "#63d5c5"};
const serviceBounds = L.latLngBounds([[40.375,-3.73],[40.455,-3.64]]);
const navigationBounds = serviceBounds.pad(.12);
const map = L.map("map", {
  preferCanvas:true, zoomControl:true, zoomSnap:.25, zoomDelta:.5,
  minZoom:11, maxZoom:17, maxBounds:navigationBounds, maxBoundsViscosity:1,
  dragging:false, inertia:false, scrollWheelZoom:false, doubleClickZoom:false,
  touchZoom:false, boxZoom:false, keyboard:false
}).setView([40.416, -3.687], 13);
map.attributionControl.addAttribution('<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>');
const roads = L.layerGroup().addTo(map), hubs = L.layerGroup().addTo(map);
const stores = L.layerGroup().addTo(map), ordersLayer = L.layerGroup().addTo(map);
const courierMarkers = new Map();
let routeLine = null, state = null, selected = null, runId = new URLSearchParams(location.search).get("run") || "", lastPacket = 0, traceRows = [];
let tab = "decisions", busy = false, pollCount = 0, traceBusy = false;
let exploringMap = false;

const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
const clusterLayer = L.layerGroup().addTo(map);
const routeLayer = L.layerGroup().addTo(map);
let observations = [], observationRun = null, lastObservationTime = -1;
function setConsoleView(view) {
  $("simulation-panel").hidden=view!=="simulation";
  $("operations-panel").hidden=view!=="operations";
  document.querySelectorAll("[data-console-view]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.consoleView===view)));
  if(view==="operations") requestAnimationFrame(()=>{map.invalidateSize(); $("fit-map").click();});
}
document.querySelectorAll("[data-console-view]").forEach(b=>b.onclick=()=>setConsoleView(b.dataset.consoleView));
document.addEventListener("click",event=>{if(event.target.closest("[data-open-simulation]"))setConsoleView("simulation");});
["agent-role","agent-status","agent-search"].forEach(id=>$(id).addEventListener("input",()=>state&&renderInspector()));
$("fleet").addEventListener("click",event=>{const row=event.target.closest("[data-courier]");if(row)choose("courier",row.dataset.courier);});
$("open-agent-details").onclick=()=>{
  const open=$("agent-details").hidden;$("agent-details").hidden=!open;$("open-agent-details").setAttribute("aria-expanded",String(open));
  if(open)$("agent-details").scrollIntoView({behavior:reducedMotion.matches?"instant":"smooth",block:"nearest"});
};
map.on("zoomend",()=>{if(state?.run)renderCouriers();});
function agentStatus(c){return ["to_pickup","delivering","returning"].includes(c.status)?"working":c.status==="off_shift"?"off_shift":"idle";}
function deliveryCount(id){return state.orders.filter(o=>o.courier===id&&o.status==="delivered").length;}
function observeMetrics(){
 const run=state.run;
 if(observationRun!==run.id){observations=[];lastObservationTime=-1;observationRun=run.id;}
 if(run.sim_time===lastObservationTime)return;
 lastObservationTime=run.sim_time;
 observations.push({time:run.sim_time,orders:state.metrics.delivered,ontime:state.metrics.on_time_pct,cost:state.metrics.cost_per_delivery_eur,rate:run.sim_time>0?state.metrics.orders/(run.sim_time/60):null,agents:Object.fromEntries(state.couriers.map(c=>[c.id,deliveryCount(c.id)]))});
 if(observations.length>40)observations.shift();
 for(const key of ["orders","ontime","cost","rate"])$("chart-"+key).innerHTML=Ops.sparkline(observations.map(s=>s[key]),"Observed "+key+" during this visit");
}
function courierTask(c){return c.order_id || (c.status==="off_shift"?"Off shift":c.status==="returning"?"Returning to hub":"Available for assignment");}
$("map-symbols").innerHTML=["bike","moto","van"].map(role=>'<span>'+Ops.icon(role)+role[0].toUpperCase()+role.slice(1)+'</span>').join("")+'<span><i class="planned-route"></i>Planned</span><span><i class="observed-route"></i>Traveled · fading</span>';
function agentTraceLink(id){return "/agent-traces?source=madrid&run="+encodeURIComponent(state.run.id)+"&agent="+encodeURIComponent(id);}

const escape = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const clock = (seconds) => `${String(10 + Math.floor(seconds / 3600)).padStart(2,"0")}:${String(Math.floor(seconds % 3600 / 60)).padStart(2,"0")}`;
const human = (s) => String(s).replaceAll("_", " ");
async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`Request failed (${response.status}). Check the local services.`);
  return response.json();
}
function error(message) { $("error").textContent = message; $("error").hidden = !message; }
function setTab(next) {
  tab = next;
  document.querySelectorAll("[data-tab]").forEach(button => {
    const active = button.dataset.tab === tab;
    button.setAttribute("aria-selected", String(active));
    $(button.dataset.tab).hidden = !active;
  });
}
document.querySelectorAll("[data-tab]").forEach(button => button.onclick = () => setTab(button.dataset.tab));
function updateMapMinZoom() {
  map.setMinZoom(11);
  map.setMinZoom(Math.min(map.options.maxZoom, map.getBoundsZoom(serviceBounds, false, [24,24])));
}
function setMapExploration(active) {
  exploringMap = active;
  for (const handler of [map.dragging, map.scrollWheelZoom, map.doubleClickZoom, map.touchZoom, map.boxZoom, map.keyboard]) {
    if (active) handler.enable(); else handler.disable();
  }
  $("explore-map").setAttribute("aria-pressed", String(active));
  $("map-mode").textContent = active
    ? "Explore · Drag to pan; scroll to zoom. Press Esc or toggle off to exit."
    : "Overview · Use +/− to zoom. Scroll to move the page.";
}
$("explore-map").onclick = () => setMapExploration(!exploringMap);
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || !exploringMap) return;
  setMapExploration(false);
  if ($("map").contains(document.activeElement)) $("explore-map").focus();
});
$("fit-map").onclick = () => {
  updateMapMinZoom();
  map.fitBounds(serviceBounds, {padding:[12,12], animate:false});
};
map.on("resize", () => {
  if (!$("map").clientWidth || !$("map").clientHeight) return;
  updateMapMinZoom();
  map.panInsideBounds(navigationBounds, {animate:false});
});
$("frame-selection").onclick = () => {
  const bounds = selectedMapBounds();
  if (bounds) map.fitBounds(bounds, {padding:[28,28], maxZoom:16, animate:false});
};
$("show-stores").onchange = (e) => e.target.checked ? stores.addTo(map) : map.removeLayer(stores);
$("show-complete").onchange = () => state && renderOrders();
$("order-filter").onchange = () => state && renderLedger();
$("clear-selection").onclick = () => { selected = null; traceRows = []; renderInspector(); renderCouriers(); renderRoute(); $("agent-details").hidden=true; $("open-agent-details").setAttribute("aria-expanded","false"); };
$("run-select").onchange = () => {
  runId = $("run-select").value; selected = null; traceRows = [];
  renderRoute();
  for (const marker of courierMarkers.values()) marker.remove();
  courierMarkers.clear(); poll();
};
$("start").onclick = async () => {
  $("start").disabled = true;
  try {
    const result = await api("/api/runs", {method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({seed:Number($("seed").value), wall_seconds:Number($("duration").value)})});
    runId = result.id; selected = null; traceRows = []; renderRoute();
    await refreshRuns(); await poll(); setConsoleView("operations"); error("");
  } catch (e) { error(e.message); }
  finally { $("start").disabled = state?.run?.status === "running"; }
};
async function refreshRuns() {
  const rows = await api("/api/runs");
  $("run-select").replaceChildren(new Option("Latest run", ""), ...rows.map(r =>
    new Option(`${r.id.slice(0,8)} · ${r.status}`, r.id)));
  $("run-select").value = runId;
}
async function choose(kind, id) {
  selected = {kind, id}; traceRows = []; setTab("decisions");
  renderInspector(); renderCouriers(); renderRoute(); await refreshTrace();
}
async function refreshTrace() {
  if (!selected || !state?.run || traceBusy) return;
  const selection = selected;
  traceBusy = true;
  try {
    const data = await api(`/api/runs/${state.run.id}/trace?${selection.kind}=${encodeURIComponent(selection.id)}`);
    if (selected === selection) { traceRows = data.decisions; renderDecisions(); }
  } finally { traceBusy = false; }
}
function selectedMapBounds() {
  if (!state?.run || !selected) return null;
  const courier = selected.kind === "courier" ? state.couriers.find(c => c.id === selected.id)
    : state.couriers.find(c => c.order_id === selected.id);
  const order = selected.kind === "order" ? state.orders.find(o => o.id === selected.id) : null;
  const points = [];
  const include = (lat, lon) => {
    if (Number.isFinite(lat) && Number.isFinite(lon) && navigationBounds.contains([lat,lon])) points.push([lat,lon]);
  };
  for (const point of courier?.route?.points || []) include(point[1], point[0]);
  if (courier) include(courier.lat, courier.lon);
  if (order) include(order.lat, order.lon);
  return points.length ? L.latLngBounds(points) : null;
}
function renderRoute() {
  routeLayer.clearLayers();
  $("frame-selection").disabled=!selectedMapBounds();
  if(!state?.run)return;
  for(const courier of state.couriers){
    const points=courier.route?.points;if(!points?.length)continue;
    const chosen=selected?.kind==="courier"&&selected.id===courier.id||selected?.kind==="order"&&selected.id===courier.order_id;
    if(!chosen&&!["to_pickup","delivering"].includes(courier.status))continue;
    const traveled=points.filter(p=>p[2]<=state.run.sim_time),planned=points.filter(p=>p[2]>state.run.sim_time);
    if(traveled.length&&planned.length)planned.unshift(traveled.at(-1));
    if(planned.length>1)L.polyline(planned.map(p=>[p[1],p[0]]),{color:"#63d5c5",weight:chosen?3:1.5,opacity:chosen?.65:.22,dashArray:"4 6",interactive:false}).addTo(routeLayer);
    for(let i=1;i<traveled.length;i++)L.polyline([[traveled[i-1][1],traveled[i-1][0]],[traveled[i][1],traveled[i][0]]],{color:"#63d5c5",weight:chosen?3:1.5,opacity:(chosen?.8:.25)*(i/traveled.length),interactive:false}).addTo(routeLayer);
  }
}
function renderMetrics() {
  observeMetrics();
  const {run,metrics:m,queue:q,complaints} = state;
  $("session-state").textContent=human(run.status);
  $("session-state").className="badge "+run.status;
  $("session-id").textContent=clock(run.sim_time)+" · "+run.id.slice(0,8);
  $("history-scope").textContent=(observations.length<2 ? (["complete","failed"].includes(run.status) ? "History unavailable for this completed run." : "Collecting history.") : "Charts observed since opening.")+" Agent totals are delivered orders; curves show deliveries per simulated minute.";
  $("kpi-rate").textContent=run.sim_time>0?(m.orders/(run.sim_time/60)).toFixed(2):"—";
  $("clock").textContent = clock(run.sim_time);
  $("run-status").textContent = run.status.toUpperCase(); $("run-status").className = `badge ${run.status}`;
  $("kpi-delivered").innerHTML = `${m.delivered} <small>/ ${m.orders}</small>`;
  $("kpi-active").textContent = `${m.active} active · ${m.pending} pending · ${m.unserved} unserved`;
  $("kpi-ontime").textContent = m.on_time_pct === null ? "—" : `${m.on_time_pct}%`;
  $("kpi-cost").textContent = m.cost_per_delivery_eur === null ? "—" : `€${m.cost_per_delivery_eur.toFixed(2)}`;
  $("kpi-llm").textContent = `$${run.llm_cost_usd.toFixed(4)}`;
  $("kpi-tokens").textContent = `${run.llm_tokens.toLocaleString()} tokens · ${run.llm_calls} calls (est.)`;
  $("kpi-complaints").textContent = complaints.length;
  $("kpi-approvals").textContent = `${complaints.filter(c => c.status === "awaiting_approval").length} awaiting approval`;
  $("kpi-queue").textContent = (q.ready || 0) + (q.leased || 0);
  $("kpi-dead").textContent = `${q.dead || 0} dead letters · ${q.done || 0} acknowledged`;
  $("run-info").textContent = `Run ${run.id.slice(0,8)} · seed ${run.seed} · ${(run.sim_time / run.duration * 100).toFixed(0)}% complete`;
  $("start").disabled = run.status === "running" || run.status === "ready";
  if (run.status === "failed") error(`Run stopped: ${run.error}. The state is preserved; resume from the CLI.`);
}
function renderCouriers() {
  clusterLayer.clearLayers();
  const groups=new Map();
  for (const c of state.couriers) {
    const isSelected=selected?.kind==="courier"&&selected.id===c.id;
    const status=agentStatus(c), color=status==="working"?"#63d5c5":status==="off_shift"?"#81949f":"#b7c7cf";
    const shape=Ops.icon(c.mode,"marker-symbol").replace('viewBox="0 0 24 24"','viewBox="-5 -5 34 34"').replace('fill="none"','style="color:'+color+'" fill="none"').replace('stroke-width="1.5"','stroke-width="1.6"');
    const svg=shape.replace(">",'><circle cx="12" cy="12" r="16" fill="#172429" stroke="'+(isSelected?"#e7edf0":color)+'" stroke-width="'+(isSelected?2:1)+'"/>');
    const icon=L.divIcon({className:"courier-icon"+(isSelected?" selected":""),iconSize:[30,30],iconAnchor:[15,15],html:svg});
    let marker=courierMarkers.get(c.id);
    if(!marker){marker=L.marker([c.lat,c.lon],{icon,title:c.id,keyboard:true});marker.on("click",()=>choose("courier",c.id));courierMarkers.set(c.id,marker);}
    else marker.setIcon(icon).setLatLng([c.lat,c.lon]);
    const last=state.decisions.find(d=>d.courier_id===c.id);
    marker.bindTooltip(escape(c.id)+" · "+escape(human(c.status)));
    const content='<div class="map-agent-card"><strong>'+escape(c.id)+'</strong><p>'+escape(human(c.status))+' · '+escape(c.mode)+'</p><p>Task: '+escape(courierTask(c))+'</p><p>Last decision: '+escape(last?human(last.action):"None recorded")+'</p><a href="'+agentTraceLink(c.id)+'">Open agent trace</a></div>';
    if(marker.getPopup())marker.setPopupContent(content);else marker.bindPopup(content,{minWidth:220,autoPan:false});
    const point=map.project([c.lat,c.lon],map.getZoom());
    const key=map.getZoom()<13.5&&!isSelected?Math.floor(point.x/38)+":"+Math.floor(point.y/38):c.id;
    if(!groups.has(key))groups.set(key,[]);groups.get(key).push({c,marker});
  }
  for(const group of groups.values()){
    if(group.length===1){if(!map.hasLayer(group[0].marker))group[0].marker.addTo(map);continue;}
    group.forEach(({marker})=>map.removeLayer(marker));
    const lat=group.reduce((n,{c})=>n+c.lat,0)/group.length,lon=group.reduce((n,{c})=>n+c.lon,0)/group.length;
    const icon=L.divIcon({className:"cluster-marker",html:String(group.length),iconSize:[30,30]});
    L.marker([lat,lon],{icon,title:group.length+" agents. Zoom to inspect.",keyboard:true}).on("click",()=>map.setView([lat,lon],Math.min(17,map.getZoom()+1),{animate:!reducedMotion.matches})).addTo(clusterLayer);
  }
}
function renderOrders() {
  ordersLayer.clearLayers();
  for (const o of state.orders) {
    if (o.status === "delivered" && !$("show-complete").checked) continue;
    const late = o.status !== "delivered" && o.due_sim < state.run.sim_time;
    const color = o.status === "delivered" ? "#a2bdb1" : late ? "#c64d48" : "#daa340";
    L.circleMarker([o.lat,o.lon],{radius:o.status === "delivered"?3:5,color:"#fff",weight:1.5,
      fillColor:color,fillOpacity:.95}).bindTooltip(`${escape(o.id)} · ${escape(human(o.status))}`)
      .on("click",()=>choose("order",o.id)).addTo(ordersLayer);
  }
}
function renderLedger() {
  const filter = $("order-filter").value;
  const rows = state.orders.filter(o => filter === "all" || (filter === "active"
    ? ["pending","assigned","picked_up"].includes(o.status)
    : (o.delivered_sim ?? state.run.sim_time) > o.due_sim));
  $("order-count").textContent = `${state.metrics.orders} generated · ${rows.length} in view`;
  $("orders").innerHTML = rows.slice(0,100).map(o => {
    const late = o.status !== "delivered" && o.due_sim < state.run.sim_time;
    return `<tr><td><button class="order-link" data-order="${escape(o.id)}">${escape(o.id)}</button></td>
      <td>${escape(o.store)}</td><td>${escape(o.courier || "Awaiting dispatch")}</td>
      <td>${clock(o.created_sim)}</td><td>${clock(o.due_sim)}</td>
      <td><span class="status-pill ${escape(late?"late":o.status)}">${escape(human(o.status))}${late?" · late":""}</span></td></tr>`;
  }).join("") || '<tr><td colspan="6" class="empty">No orders match this view. Choose All orders to inspect completed deliveries.</td></tr>';
  document.querySelectorAll("[data-order]").forEach(b=>b.onclick=()=>choose("order",b.dataset.order));
}
function renderInspector() {
  if(!state?.run)return;
  $("agent-count").textContent=state.couriers.length;
  $("fleet-activity").textContent=state.couriers.filter(c=>agentStatus(c)==="working").length+" working";
  $("open-agent-details").disabled=!selected;
  if(selected?.kind==="courier"){
    const c=state.couriers.find(c=>c.id===selected.id);
    if(c)$("selection").innerHTML='<strong>'+escape(c.id)+'</strong><span class="status-pill '+agentStatus(c)+'">'+escape(human(c.status))+'</span><p>'+escape(courierTask(c))+'</p>';
  }else if(selected?.kind==="order"){
    const o=state.orders.find(o=>o.id===selected.id);
    $("selection").innerHTML='<strong>'+escape(selected.id)+'</strong><p>'+escape(o?.store||"Delivery order")+' · '+escape(human(o?.status||"Recorded"))+'</p>';
  }else $("selection").innerHTML='<strong>Choose an agent</strong><p>Select a roster row or map marker to see its current task.</p>';
  const role=$("agent-role").value,status=$("agent-status").value,query=$("agent-search").value.trim().toLowerCase();
  const rows=state.couriers.filter(c=>(role==="all"||c.mode===role)&&(status==="all"||(status==="active"?agentStatus(c)==="working":agentStatus(c)===status))&&c.id.toLowerCase().includes(query));
  Ops.liveHTML($("fleet"),rows.map(c=>'<button class="fleet-row '+(selected?.id===c.id?"active":"")+'" data-courier="'+escape(c.id)+'" aria-pressed="'+(selected?.id===c.id)+'"><span class="fleet-person">'+Ops.icon(c.mode)+'<span><strong>'+escape(c.id)+'</strong><small>'+escape(c.order_id||human(c.mode)+" courier")+'</small></span></span><span class="status-pill '+agentStatus(c)+'">'+escape(human(c.status))+'</span><span class="fleet-throughput">'+deliveryCount(c.id)+Ops.sparkline(observations.map((s,i)=>i&&s.time>observations[i-1].time?(s.agents[c.id]-observations[i-1].agents[c.id])*60/(s.time-observations[i-1].time):null),"Deliveries per simulated minute during this visit")+'</span></button>').join("")||'<p class="empty">No agents match these filters.</p>');
  renderDecisions();
  $("service").innerHTML=state.complaints.map(c=>'<article class="complaint"><span class="badge">'+escape(human(c.status))+'</span><p>'+escape(c.text)+'</p>'+(c.response?'<blockquote>'+escape(c.response)+'</blockquote>':'')+'<small>'+escape(c.source||"pending")+' · approved refund €'+c.approved_refund_eur.toFixed(2)+'<br>'+escape(c.order_id)+'</small></article>').join("")||'<p class="empty">No service cases recorded.</p>';
}
function renderDecisions() {
  const rows = selected ? traceRows : state?.decisions || [];
  $("decisions").innerHTML = rows.map(d=>`<article class="decision"><div class="decision-top"><span>${escape(d.agent)}</span><time>${clock(d.sim_time)}</time></div><strong>${escape(human(d.action))}</strong><p>${escape(d.detail.rule || d.detail.reply || (d.detail.on_time !== undefined ? (d.detail.on_time?"Delivered within promised window":"Delivered after promised window") : d.detail.store || "State transition recorded"))}</p><code>${escape(d.order_id || "")}${d.courier_id?` / ${escape(d.courier_id)}`:""}</code><details><summary>Inspect recorded evidence</summary><pre>${escape(JSON.stringify(d.detail,null,2))}</pre></details></article>`).join("") || '<p class="empty">No decisions recorded for this selection yet.</p>';
}
function pointAt(route, sim) {
  const ps=route.points;
  if(sim<=ps[0][2]) return [ps[0][1],ps[0][0]];
  for(let i=1;i<ps.length;i++) {
    const a=ps[i-1],b=ps[i];
    if(sim<=b[2]) { const f=Math.max(0,Math.min(1,(sim-a[2])/Math.max(.001,b[2]-a[2]))); return [a[1]+f*(b[1]-a[1]),a[0]+f*(b[0]-a[0])]; }
  }
  return [ps.at(-1)[1],ps.at(-1)[0]];
}
function animate() {
  if(!document.hidden && !reducedMotion.matches && state?.run?.status==="running" && state.run.wall_seconds>0) {
    const advance=Math.min(60,(performance.now()-lastPacket)/1000*state.run.duration/state.run.wall_seconds);
    for(const c of state.couriers) if(c.route && ["to_pickup","delivering"].includes(c.status))
      courierMarkers.get(c.id)?.setLatLng(pointAt(c.route,state.run.sim_time+advance));
  }
  requestAnimationFrame(animate);
}
async function poll() {
  if(busy) return;
  busy=true;
  try {
    const next=await api(`/api/state${runId?`?run=${runId}`:""}`);
    if(state?.run?.id && next.run?.id!==state.run.id) { selected=null;traceRows=[]; }
    state=next; lastPacket=performance.now();
    $("connection").className="dot online"; $("connection-text").textContent="Local services connected";
    if(state.run) { renderMetrics();renderCouriers();renderOrders();renderLedger();renderInspector();renderRoute();await refreshTrace(); }
    else $("fleet").innerHTML='<div class="empty"><strong>No session loaded</strong><p>Start a session to see the fleet, routes and orders.</p><button data-open-simulation>Set up simulation</button></div>';
    if(++pollCount%10===0) await refreshRuns();
  } catch(e) { $("connection").className="dot offline";$("connection-text").textContent="Connection interrupted";error(e.message); }
  finally { busy=false; }
}
async function initialize() {
  try {
    const [city,network]=await Promise.all([api("/api/world"),api("/api/roads")]);
    L.geoJSON(network,{style:{color:"#40535d",weight:1.1,opacity:.65},interactive:false}).addTo(roads);
    for(const loc of city.locations) {
      if(loc.kind==="hub") L.marker([loc.lat,loc.lon],{icon:L.divIcon({className:"hub-marker",html:escape(loc.district),iconSize:null,iconAnchor:[25,25]})}).addTo(hubs);
      else if(loc.kind==="store") L.circleMarker([loc.lat,loc.lon],{radius:3,color:"#92a7ad",weight:1,fillColor:"#1c2d33",fillOpacity:1}).bindTooltip(escape(loc.name)).addTo(stores);
    }
    $("graph-info").textContent=`${city.manifest.nodes.toLocaleString()} road nodes · ${city.manifest.edges.toLocaleString()} directed edges · OSM`;
    $("fit-map").click(); await refreshRuns(); await poll();
  } catch(e) { error(e.message); }
  setInterval(poll,1000); animate();
}
initialize();
