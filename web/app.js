/* All dynamic strings enter the DOM as text. LLM replies are untrusted content. */
"use strict";
const $ = (id) => document.getElementById(id);
const serviceBounds = L.latLngBounds([[40.375,-3.73],[40.455,-3.64]]);
const navigationBounds = L.latLngBounds([[40.32,-3.83],[40.52,-3.54]]);
const map = L.map("map", {
  preferCanvas:true, zoomControl:true, zoomSnap:.25, zoomDelta:.5,
  minZoom:11, maxZoom:17, maxBounds:navigationBounds, maxBoundsViscosity:1,
  dragging:true, inertia:false, scrollWheelZoom:true, doubleClickZoom:true,
  touchZoom:true, boxZoom:true, keyboard:true
}).setView([40.416, -3.687], 13);
map.zoomControl.setPosition("topright");
L.control.scale({imperial:false,position:"bottomleft",maxWidth:90}).addTo(map);
const roads = L.layerGroup().addTo(map), hubs = L.layerGroup().addTo(map);
const stores = L.layerGroup().addTo(map), ordersLayer = L.layerGroup().addTo(map);
const courierMarkers = new Map();
const {createDisplayClock, courierPosition} = CourierMotion;
const displayClock = createDisplayClock();
let state = null, selected = null, runId = new URLSearchParams(location.search).get("run") || "", traceRows = [];
let tab = "decisions", pollTask = null, pollCount = 0, traceBusy = false;
let runtime = {mode:"local"}, replayStarted = performance.now();
const narrowMap = matchMedia("(max-width:850px)");
document.querySelector(".map-key").open = !narrowMap.matches;
narrowMap.addEventListener("change",event=>{document.querySelector(".map-key").open=!event.matches;});
let exploringMap = true, orderFilterTouched = false, orderViewRun = null;
let basemapReady = false, mapResizeFrame;
const mapResizeObserver=new ResizeObserver(()=>{
  if(!$("map").clientWidth||!$("map").clientHeight)return;
  cancelAnimationFrame(mapResizeFrame);
  mapResizeFrame=requestAnimationFrame(()=>{
    map.invalidateSize({pan:false});
    requestAnimationFrame(()=>{
      const gl=window.madridBasemap;if(!gl)return;
      gl.resize();
      const center=map.getCenter();
      gl.jumpTo({center:[center.lng,center.lat],zoom:map.getZoom()-1});
      placeSelectedLabel();
    });
  });
});
mapResizeObserver.observe($("map"));
try {
  const base = L.maplibreGL({style:"/static/map/style.json", attributionControl:false, transformRequest:url=>({url:new URL(url,location.href).href})}).addTo(map);
  window.madridBasemap = base.getMaplibreMap();
  window.madridBasemap.on("idle", () => {
    if (!window.madridBasemap.queryRenderedFeatures().length) return;
    basemapReady = true;
    // The local street graph adds fine service-area roads above the basemap.
    $("map").dataset.basemap = "ready";
    $("map-loading").hidden = true;
  });
  window.madridBasemap.on("error", () => {
    if (basemapReady) return;
    $("map").dataset.basemap = "fallback";
    $("map-loading").textContent = "Basemap unavailable · showing the routing network";
  });
} catch {
  $("map").dataset.basemap = "fallback";
  $("map-loading").textContent = "Basemap unavailable · showing the routing network";
}
map.attributionControl.addAttribution('<a href="https://openfreemap.org/">OpenFreeMap</a> · <a href="https://openmaptiles.org/">OpenMapTiles</a> · <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap</a>');


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
$("agent-fleet").addEventListener("change",()=>{
  if(!state?.run)return;
  if(selected?.kind==="courier"&&!fleetCouriers().some(c=>c.id===selected.id)){selected=null;traceRows=[];}
  renderInspector();renderCouriers();renderRoute();
});
$("fleet").addEventListener("click",event=>{const row=event.target.closest("[data-courier]");if(row)choose("courier",row.dataset.courier);});
$("open-agent-details").onclick=()=>{
  const open=$("agent-details").hidden;$("agent-details").hidden=!open;$("open-agent-details").setAttribute("aria-expanded",String(open));
  if(open)$("agent-details").scrollIntoView({behavior:reducedMotion.matches?"instant":"smooth",block:"nearest"});
};
map.on("zoomend",()=>{if(state?.run)renderCouriers();});
function agentStatus(c){return ["to_pickup","delivering","returning","repositioning"].includes(c.status)?"working":["off_shift","offline"].includes(c.status)?c.status:"idle";}
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
function courierTask(c){return c.status==="offline"?"Offline · unavailable":c.order_id || (c.status==="off_shift"?"Off shift":c.status==="repositioning"?"Moving toward expected demand":c.status==="returning"?"Returning to hub":"Available for assignment");}
$("map-symbols").innerHTML='<span class="legend-working">'+Ops.icon("bike")+'Courier · working</span><span class="legend-idle">'+Ops.icon("van")+'Courier · available</span><span class="legend-pickup">'+Ops.icon("store")+'Pickup</span><span class="legend-destination">'+Ops.icon("household")+'Destination</span><span><i class="planned-route"></i>Planned route</span><span><i class="observed-route"></i>Traveled · fading</span>';
function courierName(c){return c.id.replace(/^castellana-/,"Castellana · ").replace(/^sol-/,"Sol · ").replace("chamberi","Chamberí").replace("retiro","Retiro").replace("vallecas","Vallecas").replaceAll("-"," ");}
function fleetCouriers(){return state.couriers.filter(c=>$("agent-fleet").value==="all"||(c.fleet_id||"regular")===$("agent-fleet").value);}
function renderFleetControl(){
  const fleets=state.fleets||[{id:"regular",name:"Bakiano",operator:"regular",couriers:state.couriers.length,coverage:"network"}];
  const select=$("agent-fleet"),signature=fleets.map(f=>f.id+":"+f.couriers).join("|");
  if(select.dataset.roster!==signature){
    const prior=select.value;
    select.replaceChildren(new Option("All fleets","all"),...fleets.map(f=>new Option(f.name+" · "+f.couriers,f.id)));
    select.value=fleets.some(f=>f.id===prior)?prior:"all";select.dataset.roster=signature;
  }
  const fleet=fleets.find(f=>f.id===select.value),contractors=state.couriers.filter(c=>c.operator==="contractor").length;
  $("fleet-summary").textContent=fleet?(fleet.operator==="contractor"?"Independent contractor":"Regular fleet")+" · "+(fleet.coverage==="home_district"?"Home district only":"Full service area"):(state.couriers.length-contractors)+" regular · "+contractors+" contractors · roster + map";
}
function lastDecision(kind,id){
  return [...traceRows,...(state?.decisions||[])].filter(d=>kind==="courier"?d.courier_id===id:d.order_id===id).sort((a,b)=>b.sim_time-a.sim_time)[0];
}
function taskDetails(c){
  const order=state.orders.find(o=>o.id===c.order_id);
  if(c.status==="offline")return {title:"Offline · unavailable",note:"Not accepting assignments"};
  return {title:c.order_id|| (c.status==="off_shift"?"Off shift":c.status==="repositioning"?"Moving toward demand":c.status==="returning"?"Return to hub":"Awaiting order"),
    note:order?.store || (c.status==="off_shift"?"Not accepting work":c.status==="repositioning"?"No active order":c.status==="returning"?human(c.hub):"Ready for dispatch")};
}
function agentTraceLink(id){return "/agent-traces?source=madrid&run="+encodeURIComponent(state.run.id)+"&agent="+encodeURIComponent(id);}

const escape = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const clock = (seconds) => `${String(10 + Math.floor(seconds / 3600)).padStart(2,"0")}:${String(Math.floor(seconds % 3600 / 60)).padStart(2,"0")}`;
const human = (s) => String(s).replaceAll("_", " ");
const measured = (value, unit, digits = 1) => Number.isFinite(value) ? value.toFixed(digits) + unit : "—";
const activeRoute = (courier) => courier?.route || courier?.reposition_route;
async function api(path, options) {
  if(runtime.mode==="replay" && (path.startsWith("/api/state") || /\/trace\?|\/chaos$/.test(path))) {
    const url=new URL(path,location.origin);
    url.searchParams.set("t",String(Math.min(60,Math.floor((performance.now()-replayStarted)/1000))));
    path=url.pathname+url.search;
  }
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
}
function setMapExploration(active) {
  exploringMap = active;
  if (active) map.scrollWheelZoom.enable(); else map.scrollWheelZoom.disable();
  $("explore-map").setAttribute("aria-pressed", String(active));
  $("map-mode").textContent = active
    ? "Drag to pan; scroll to zoom. Press Escape to turn off scroll zoom."
    : "Drag to pan. Use plus and minus to zoom; scroll to move the page.";
}
setMapExploration(true);
$("explore-map").onclick = () => setMapExploration(!exploringMap);
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || !exploringMap) return;
  setMapExploration(false);
  if ($("map").contains(document.activeElement)) $("explore-map").focus();
});
$("fit-map").onclick = () => {
  updateMapMinZoom();
  map.fitBounds(serviceBounds, {paddingTopLeft:[20,52], paddingBottomRight:[20,20], animate:false});
};
map.on("resize", () => {
  if (!$("map").clientWidth || !$("map").clientHeight) return;
  updateMapMinZoom();
  map.panInsideBounds(navigationBounds, {animate:false});
});
$("frame-selection").onclick = () => {
  const bounds = selectedMapBounds();
  if (bounds) map.fitBounds(bounds, {paddingTopLeft:[90,90], paddingBottomRight:[90,64], maxZoom:16, animate:false});
  requestAnimationFrame(()=>placeSelectedLabel(true));
};
$("show-stores").onchange = (e) => e.target.checked ? stores.addTo(map) : map.removeLayer(stores);
$("show-complete").onchange = () => state && renderOrders();
$("order-filter").onchange = () => {orderFilterTouched=true;if(state)renderLedger();};
$("order-search").oninput = () => state && renderLedger();
$("clear-selection").onclick = () => { selected = null; traceRows = []; renderInspector(); renderCouriers(); renderRoute(); $("agent-details").hidden=true; $("open-agent-details").setAttribute("aria-expanded","false"); };
$("run-select").onchange = () => {
  replayStarted=performance.now();
  runId = $("run-select").value; selected = null; traceRows = [];
  renderRoute();
  for (const marker of courierMarkers.values()) marker.remove();
  courierMarkers.clear(); poll();
};
$("start").onclick = async () => {
  if(runtime.mode==="replay") {
    replayStarted=performance.now();state=null;observations=[];lastObservationTime=-1;
    await poll();setConsoleView("operations");return;
  }
  $("start").disabled = true;
  try {
    const result = await api("/api/runs", {method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({seed:Number($("seed").value), wall_seconds:Number($("duration").value),
        ...await ChaosUI.runOptions(),
        dispatch:{strategy:$("dispatch-strategy").value, reposition:$("reposition-policy").value}})});
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
  const courier=kind==="courier"?state.couriers.find(c=>c.id===id):state.couriers.find(c=>c.order_id===id);
  if(courier&&$("agent-fleet").value!=="all"&&$("agent-fleet").value!==(courier.fleet_id||"regular"))$("agent-fleet").value="all";
  selected = {kind, id}; traceRows = []; setTab("decisions");
  renderInspector(); renderCouriers(); renderRoute(); placeSelectedLabel(true); await refreshTrace();
}
async function refreshTrace() {
  if (!selected || !state?.run || traceBusy) return;
  const selection = selected;
  traceBusy = true;
  try {
    const data = await api(`/api/runs/${state.run.id}/trace?${selection.kind}=${encodeURIComponent(selection.id)}`);
    if (selected === selection) { traceRows = data.decisions; renderInspector(); }
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
  for (const point of activeRoute(courier)?.points || []) include(point[1], point[0]);
  if (courier) {
    const [lat, lon] = courierPosition(courier, displayClock.time(performance.now()));
    include(lat, lon);
  }
  if (order) include(order.lat, order.lon);
  return points.length ? L.latLngBounds(points) : null;
}
function renderRoute() {
  routeLayer.clearLayers();
  $("frame-selection").disabled=!selectedMapBounds();
  if(!state?.run)return;
  for(const courier of fleetCouriers()){
    const points=activeRoute(courier)?.points;if(!points?.length)continue;
    const chosen=selected?.kind==="courier"&&selected.id===courier.id||selected?.kind==="order"&&selected.id===courier.order_id;
    if(!chosen&&!["to_pickup","delivering","repositioning"].includes(courier.status))continue;
    const traveled=points.filter(p=>p[2]<=state.run.sim_time),planned=points.filter(p=>p[2]>state.run.sim_time);
    if(traveled.length&&planned.length)planned.unshift(traveled.at(-1));
    if(planned.length>1)L.polyline(planned.map(p=>[p[1],p[0]]),{color:"#23d8ce",weight:chosen?5:3,opacity:chosen?.95:.72,dashArray:"8 6",interactive:false}).addTo(routeLayer);
    for(let i=1;i<traveled.length;i++)L.polyline([[traveled[i-1][1],traveled[i-1][0]],[traveled[i][1],traveled[i][0]]],{color:"#23d8ce",weight:chosen?5:3,opacity:(chosen?.55:.4)+.4*(i/traveled.length),interactive:false}).addTo(routeLayer);
  }
}
function renderDispatchEvidence() {
  const m=state.metrics,policy=state.dispatch_policy||state.run.dispatch_policy;
  $("operating-cost").textContent=Number.isFinite(m.operating_cost_eur)?"€"+m.operating_cost_eur.toFixed(2):"—";
  $("empty-distance").textContent=measured(m.empty_km," km");
  $("reposition-distance").textContent=measured(m.reposition_km," km");
  const strategy=policy?.strategy==="min_cost"?"Deadline + cost":policy?.strategy==="legacy"||!policy?"Earliest completion (legacy)":human(policy.strategy);
  const reposition=policy?.reposition==="demand_aware"?"Move toward demand":"Stay at drop-off";
  $("dispatch-policy-summary").textContent="Run policy: "+strategy+" · "+reposition;
  $("dispatch-policy-evidence").textContent=JSON.stringify(policy||{strategy:"legacy",reposition:"stay"},null,2);
}
function renderCourierEconomics() {
  const facts=$("courier-economics");
  const courier=selected?.kind==="courier"?state.couriers.find(c=>c.id===selected.id):null;
  facts.hidden=!courier;
  if(!courier){facts.replaceChildren();return;}
  const c=courier;
  const rows=[
    ["Fleet",(c.fleet_name||"Bakiano")+" · "+(c.operator==="contractor"?"Independent contractor":"Regular fleet")],
    ["Service area",c.coverage==="home_district"?"Home district only":"Full service area"],
    ["Communication",human(c.communication_style||"direct")+" · deterministic courier"],
    ["Home base",human(c.hub||"Not recorded")],
    ["Current position","Node "+(c.node??"—")+" · "+measured(c.lat,"",5)+", "+measured(c.lon,"",5)],
    ["Completed jobs",measured(c.completed_jobs,"",0)],
    ["Distance",measured(c.distance_m/1000," km")],
    ["Empty travel",measured(Number.isFinite(c.empty_distance_m)?c.empty_distance_m/1000:null," km")],
    ["Repositioning",measured(Number.isFinite(c.reposition_distance_m)?c.reposition_distance_m/1000:null," km")],
    ["Operating cost",Number.isFinite(c.operating_cost_eur)?"€"+c.operating_cost_eur.toFixed(2):"—"],
  ];
  facts.replaceChildren(...rows.map(([label,value])=>{
    const row=document.createElement("div"),term=document.createElement("dt"),description=document.createElement("dd");
    term.textContent=label;description.textContent=value;row.append(term,description);return row;
  }));
}
function renderMetrics() {
  observeMetrics();
  renderDispatchEvidence();
  const {run,metrics:m,queue:q,complaints} = state;
  $("session-state").textContent=human(run.status);
  $("session-state").className="badge "+run.status;
  $("session-id").textContent=clock(run.sim_time)+" · "+run.id.slice(0,8);
  $("history-scope").textContent=observations.length<2 ? (["complete","failed"].includes(run.status) ? "History unavailable · completed session" : "Collecting history · this visit") : "Curves · deliveries / simulated min";
  $("history-scope").title="Agent totals are delivered orders. Curves show deliveries per simulated minute observed during this visit.";
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
  $("start").disabled = runtime.mode!=="replay" && (run.status === "running" || run.status === "ready");
  if (run.status === "failed") error(`Run stopped: ${run.error}. The state is preserved; resume from the CLI.`);
}
function renderCouriers() {
  clusterLayer.clearLayers();
  const visible=fleetCouriers(),visibleIds=new Set(visible.map(c=>c.id));
  for(const [id,marker] of courierMarkers){if(!visibleIds.has(id))map.removeLayer(marker);}
  const sim = displayClock.time(performance.now());
  const groups=[];
  for (const c of visible) {
    const isSelected=selected?.kind==="courier"&&selected.id===c.id;
    const status=agentStatus(c), color=status==="working"?"#23d8ce":status==="off_shift"?"#829fb4":"#8ec6df";
    const shape=Ops.icon(c.mode,"marker-symbol").replace('viewBox="0 0 24 24"','viewBox="-5 -5 34 34"').replace('fill="none"','style="color:'+color+'" fill="none"').replace('stroke-width="1.5"','stroke-width="1.6"');
    const svg=shape.replace(">",'><circle cx="12" cy="12" r="16" fill="#10232e" stroke="'+(isSelected?"#e7edf0":color)+'" stroke-width="'+(isSelected?2:1)+'"/>');
    const icon=L.divIcon({className:"courier-icon"+(isSelected?" selected":""),iconSize:[30,30],iconAnchor:[15,15],html:svg});
    const location=courierPosition(c,sim);
    let marker=courierMarkers.get(c.id);
    if(!marker){marker=L.marker(location,{icon,title:c.id,keyboard:true});marker.on("click",()=>choose("courier",c.id));courierMarkers.set(c.id,marker);}
    else marker.setIcon(icon).setLatLng(location);
    marker.setZIndexOffset(isSelected?1000:0);
    const last=lastDecision("courier",c.id);
    marker.unbindTooltip();
    marker.bindTooltip(isSelected?escape(courierName(c)):escape(c.id)+" · "+escape(human(c.status)),{permanent:isSelected,direction:"right",offset:[14,0],className:isSelected?"agent-map-label":""});
    const content='<div class="map-agent-card"><strong>'+escape(c.id)+'</strong><p>'+escape(c.fleet_name||"Bakiano")+' · '+escape(c.operator||"regular")+'</p><p>'+escape(human(c.status))+' · '+escape(c.mode)+'</p><p>Task: '+escape(courierTask(c))+'</p><p>Last decision: '+escape(last?human(last.action):"None recorded")+'</p><a href="'+agentTraceLink(c.id)+'">Open agent trace</a></div>';
    if(marker.getPopup())marker.setPopupContent(content);else marker.bindPopup(content,{minWidth:220,autoPan:false});
    const point=map.project(location,map.getZoom());
    const group=map.getZoom()<13.5&&!isSelected?groups.find(group=>!group.selected&&group.point.distanceTo(point)<38):null;
    if(group)group.items.push({c,marker,location});
    else groups.push({point,selected:isSelected,items:[{c,marker,location}]});
  }
  for(const {items:group} of groups){
    if(group.length===1){if(!map.hasLayer(group[0].marker))group[0].marker.addTo(map);continue;}
    group.forEach(({marker})=>map.removeLayer(marker));
    const lat=group.reduce((n,{location})=>n+location[0],0)/group.length,lon=group.reduce((n,{location})=>n+location[1],0)/group.length;
    const icon=L.divIcon({className:"cluster-marker",html:String(group.length),iconSize:[30,30]});
    L.marker([lat,lon],{icon,title:group.length+" agents. Zoom to inspect.",keyboard:true}).on("click",()=>map.setView([lat,lon],Math.min(17,map.getZoom()+1),{animate:!reducedMotion.matches})).addTo(clusterLayer);
  }
  placeSelectedLabel();
}
// Tooltip directions adapt to real control bounds; geographic coordinates stay untouched.
function placeSelectedLabel(allowPan=false) {
  if(selected?.kind!=="courier")return;
  const marker=courierMarkers.get(selected.id),tooltip=marker?.getTooltip();
  if(!marker?.getElement()||!tooltip)return;
  const area=$("map").getBoundingClientRect();
  const obstacles=[document.querySelector(".map-toolbar"),document.querySelector(".map-key"),document.querySelector(".leaflet-control-zoom")].map(el=>el.getBoundingClientRect());
  const overlaps=(a,b)=>a.left<b.right+6&&a.right>b.left-6&&a.top<b.bottom+6&&a.bottom>b.top-6;
  const safe=box=>box.left>=area.left+6&&box.right<=area.right-6&&box.top>=area.top+6&&box.bottom<=area.bottom-20&&!obstacles.some(obstacle=>overlaps(box,obstacle));
  for(const direction of ["right","left","bottom","top"]){
    tooltip.options.direction=direction;
    tooltip.options.offset=direction==="right"?[14,0]:direction==="left"?[-14,0]:direction==="top"?[0,-14]:[0,14];
    tooltip.update();
    const box=tooltip.getElement()?.getBoundingClientRect();
    if(box&&safe(box)&&safe(marker.getElement().getBoundingClientRect()))return;
  }
  if(allowPan){
    const point=map.latLngToContainerPoint(marker.getLatLng()),size=map.getSize();
    map.panBy([point.x-size.x/2,point.y-size.y/2],{animate:false});
    placeSelectedLabel(false);
  }
}
map.on("moveend zoomend",()=>placeSelectedLabel());
function renderOrders() {
  ordersLayer.clearLayers();
  for (const o of state.orders) {
    if (o.status === "delivered" && !$("show-complete").checked) continue;
    const late = o.status !== "delivered" && o.due_sim < state.run.sim_time;
    const color = o.status === "delivered" ? "#829fb4" : late ? "#f28e8e" : "#79b8ed";
    const icon=L.divIcon({className:"destination-icon",iconSize:[20,20],iconAnchor:[10,10],html:'<span style="color:'+color+'">'+Ops.icon("household")+'</span>'});
    L.marker([o.lat,o.lon],{icon,title:o.id,keyboard:true})
      .bindTooltip(escape(o.id)+" · "+escape(human(o.status)))
      .on("click",()=>choose("order",o.id)).addTo(ordersLayer);
  }
}
function renderLedger() {
  if(orderViewRun!==state.run.id){orderFilterTouched=false;orderViewRun=state.run.id;}
  if(!orderFilterTouched)$("order-filter").value=["complete","failed"].includes(state.run.status)?"all":"active";
  const filter=$("order-filter").value,query=$("order-search").value.trim().toLowerCase();
  const rows=state.orders.filter(o=>(filter==="all" || (filter==="active"
    ? ["pending","assigned","picked_up"].includes(o.status)
    : (o.delivered_sim??state.run.sim_time)>o.due_sim)) &&
    (!query || [o.id,o.store,o.courier].some(v=>String(v||"").toLowerCase().includes(query))));
  $("order-count").textContent=state.metrics.orders+" total · "+Math.min(rows.length,100)+" shown";
  $("orders").innerHTML=rows.slice(0,100).map(o=>{
    const late=o.status!=="delivered"&&o.due_sim<state.run.sim_time;
    const decision=state.decisions.find(d=>d.order_id===o.id);
    return '<tr><td><button class="order-link" data-order="'+escape(o.id)+'">'+escape(o.id)+'</button></td><td>'+escape(o.store)+'</td><td>'+escape(o.courier||"Awaiting dispatch")+'</td><td>'+clock(o.created_sim)+'</td><td>'+clock(o.due_sim)+'</td><td><span class="status-pill '+escape(late?"late":o.status)+'">'+escape(human(o.status))+(late?" · late":"")+'</span></td><td>'+escape(decision?human(decision.action):"—")+'</td></tr>';
  }).join("");
  $("orders-empty").hidden=rows.length>0;
  $("orders-empty").textContent=state.orders.length?"No orders match this view. Adjust the search or choose All orders.":"No orders yet. New requests will appear here during the session.";
  document.querySelector(".ledger .table-scroll").hidden=rows.length===0;
  document.querySelectorAll("[data-order]").forEach(b=>b.onclick=()=>{choose("order",b.dataset.order);StoreUI.selectOrder(b.dataset.order);});
}
function renderInspector() {
  if(!state?.run)return;
  renderFleetControl();
  renderCourierEconomics();
  $("agent-count").textContent=state.couriers.length;
  $("fleet-activity").textContent=fleetCouriers().filter(c=>agentStatus(c)==="working").length+" working · "+fleetCouriers().length+" / "+state.couriers.length+" agents";
  $("open-agent-details").disabled=!selected;
  $("selected-trace").hidden=runtime.mode==="replay" || selected?.kind!=="courier";
  if(selected?.kind==="courier"){
    const c=state.couriers.find(c=>c.id===selected.id);
    if(c){
      const task=taskDetails(c),last=lastDecision("courier",c.id);
      $("selection").innerHTML='<div><span class="evidence-label">Agent evidence</span><strong>'+escape(courierName(c))+' <span class="status-pill '+agentStatus(c)+'">'+escape(human(c.status))+'</span></strong><p>'+escape(c.fleet_name||'Bakiano')+' · '+escape(c.operator||'regular')+' · '+escape(c.mode)+' courier</p></div><div><span class="evidence-label">Current task</span><strong>'+escape(task.title)+'</strong><p>'+escape(task.note)+' · '+Math.round(c.energy)+'% energy</p></div><div><span class="evidence-label">Last decision</span><strong>'+escape(last?human(last.action):"No decision retained")+'</strong><p>'+(last?clock(last.sim_time)+' · '+escape(last.order_id||last.agent):"Select View decisions for available evidence")+'</p></div>';
      $("selected-trace").href=agentTraceLink(c.id);
    }
  }else if(selected?.kind==="order"){
    const o=state.orders.find(o=>o.id===selected.id),last=lastDecision("order",selected.id);
    $("selection").innerHTML='<div><span class="evidence-label">Order evidence</span><strong>'+escape(selected.id)+'</strong><p>'+escape(human(o?.status||"Recorded"))+'</p></div><div><span class="evidence-label">Pickup · courier</span><strong>'+escape(o?.store||"Delivery order")+'</strong><p>'+escape(o?.courier||"Awaiting assignment")+'</p></div><div><span class="evidence-label">Last decision</span><strong>'+escape(last?human(last.action):"No decision retained")+'</strong><p>'+(last?clock(last.sim_time):"See available decisions")+'</p></div>';
  }else $("selection").innerHTML='<div><span class="evidence-label">Agent evidence</span><strong>Choose an agent</strong><p>Select a roster row or map marker to inspect its work.</p></div>';
  const role=$("agent-role").value,status=$("agent-status").value,query=$("agent-search").value.trim().toLowerCase();
  const rows=fleetCouriers().filter(c=>(role==="all"||c.mode===role)&&(status==="all"||(status==="active"?agentStatus(c)==="working":agentStatus(c)===status))&&(c.id+" "+courierName(c)+" "+(c.fleet_name||"Bakiano")).toLowerCase().includes(query));
  Ops.liveHTML($("fleet"),rows.map(c=>{
    const task=taskDetails(c),rates=observations.map((s,i)=>i&&s.time>observations[i-1].time?(s.agents[c.id]-observations[i-1].agents[c.id])*60/(s.time-observations[i-1].time):null);
    const curve=observations.length>2?Ops.sparkline(rates,"Deliveries per simulated minute observed this visit"):'<span class="history-unavailable" title="No time series was recorded during this visit">—</span>';
    return '<button class="fleet-row '+(selected?.id===c.id?"active":"")+'" data-courier="'+escape(c.id)+'" aria-pressed="'+(selected?.id===c.id)+'"><span class="fleet-person">'+Ops.icon(c.mode)+'<span><strong>'+escape(courierName(c).replace(/^(Sol|Castellana) · /,''))+'</strong><small>'+escape(c.fleet_name||'Bakiano')+(c.operator==='contractor'?' · contractor':' · regular')+'</small></span></span><span class="agent-role-column">'+escape(human(c.mode))+'</span><span class="status-pill '+agentStatus(c)+' '+escape(c.status)+'">'+escape(human(c.status))+'</span><span class="fleet-task"><strong>'+escape(task.title)+'</strong><small>'+escape(task.note)+'</small></span><span class="fleet-total">'+deliveryCount(c.id)+'</span><span class="fleet-throughput">'+curve+'</span></button>';
  }).join("")||'<p class="empty">No agents match these filters.</p>');
  renderDecisions();
  $("service").innerHTML=state.complaints.map(c=>'<article class="complaint"><span class="badge">'+escape(human(c.status))+'</span><p>'+escape(c.text)+'</p>'+(c.response?'<blockquote>'+escape(c.response)+'</blockquote>':'')+'<small>'+escape(c.source||"pending")+' · approved refund €'+c.approved_refund_eur.toFixed(2)+'<br>'+escape(c.order_id)+'</small></article>').join("")||'<p class="empty">No service cases recorded.</p>';
}
function renderDecisions() {
  const rows = selected ? traceRows : state?.decisions || [];
  $("decisions").innerHTML = rows.map(d=>`<article class="decision"><div class="decision-top"><span>${escape(d.agent)}</span><time>${clock(d.sim_time)}</time></div><strong>${escape(human(d.action))}</strong><p>${escape(d.detail.message?.text || d.detail.rule || d.detail.reply || (d.detail.on_time !== undefined ? (d.detail.on_time?"Delivered within promised window":"Delivered after promised window") : d.detail.store || "State transition recorded"))}</p><code>${escape(d.order_id || "")}${d.courier_id?` / ${escape(d.courier_id)}`:""}</code><details><summary>Inspect recorded evidence</summary><pre>${escape(JSON.stringify(d.detail,null,2))}</pre></details></article>`).join("") || '<p class="empty">No decisions recorded for this selection yet.</p>';
}
function animate() {
  if(!document.hidden && !reducedMotion.matches && state?.run?.status==="running" && state.run.wall_seconds>0) {
    const sim=displayClock.time(performance.now());
    for(const c of state.couriers)
      courierMarkers.get(c.id)?.setLatLng(courierPosition(c,sim));
  }
  requestAnimationFrame(animate);
}
function poll() {
  if(pollTask)return pollTask;
  pollTask=readState().finally(()=>{pollTask=null;});
  return pollTask;
}
async function readState() {
  const requestedRun=runId;
  try {
    const next=await api(`/api/state${runId?`?run=${runId}`:""}`);
    if(runId!==requestedRun)return;
    if(next.run?.id!==state?.run?.id) {
      traceRows=[];
      $("agent-fleet").value="all";
      for(const marker of courierMarkers.values())marker.remove();
      courierMarkers.clear();
      const courier=next.couriers?.find(c=>["to_pickup","delivering","repositioning"].includes(c.status))||next.couriers?.[0];
      selected=courier?{kind:"courier",id:courier.id}:null;
    }
    state=next;
    displayClock.accept(runtime.mode==="replay"&&state.run?{...state.run,id:state.run.id+":"+replayStarted}:state.run, performance.now());
    ChaosUI.update(state);
    await StoreUI.update(state,runtime);
    $("connection").className="dot online"; $("connection-text").textContent=runtime.mode==="replay"?"Recorded replay · no model calls":"Local services connected";
    if(state.run) { renderFleetControl();renderMetrics();renderCouriers();renderOrders();renderLedger();renderInspector();renderRoute();await refreshTrace(); }
    else $("fleet").innerHTML='<div class="empty"><strong>No session loaded</strong><p>Start a session to see the fleet, routes and orders.</p><button data-open-simulation>Set up simulation</button></div>';
    if(++pollCount%10===0) await refreshRuns();
  } catch(e) { $("connection").className="dot offline";$("connection-text").textContent="Connection interrupted";error(e.message); }
}
async function initialize() {
  try {
    runtime=await api("/api/runtime");
    if(runtime.mode==="replay") {
      document.body.dataset.runtime="replay";
      $("start").textContent="Replay shift";
      for(const id of ["seed","duration","dispatch-strategy","reposition-policy","chaos-mode"])
        $(id).disabled=true;
      $("duration").value="60";$("chaos-mode").value="demo";
      document.querySelectorAll(".workspace-navigation a").forEach(a=>{if(new URL(a.href).pathname!=="/")a.hidden=true;});
      const label=document.querySelector(".workspace-local");if(label)label.textContent="Public replay · synthetic";
    }
    const [city,network]=await Promise.all([api("/api/world"),api("/api/roads")]);
    ChaosUI.setWorld(city, map);
    L.geoJSON(network,{style:{color:"#426078",weight:.65,opacity:.42},interactive:false}).addTo(roads);
    for(const loc of city.locations) {
      if(loc.kind==="hub") L.marker([loc.lat,loc.lon],{icon:L.divIcon({className:"hub-marker",html:escape(loc.district),iconSize:null,iconAnchor:[25,25]})}).addTo(hubs);
      else if(loc.kind==="store") L.marker([loc.lat,loc.lon],{icon:L.divIcon({className:"pickup-icon",html:Ops.icon("store"),iconSize:[22,22],iconAnchor:[11,11]}),title:loc.name}).bindTooltip(escape(loc.name)).addTo(stores);
    }
    $("graph-info").textContent=`${city.manifest.nodes.toLocaleString()} road nodes · ${city.manifest.edges.toLocaleString()} directed edges · OSM`;
    $("fit-map").click(); await refreshRuns(); await poll();
  } catch(e) { error(e.message); }
  setInterval(poll,1000); animate();
}
StoreUI.init({map,api,choose,locate:()=>$("frame-selection").click(),selectRun:async id=>{
 runId=id;$("run-select").value=id;setConsoleView("operations");
 history.replaceState(null,"","?run="+encodeURIComponent(id));await refreshRuns();await poll();
 // A joined poll may belong to the preceding run; wait for this selection.
 if(state?.run?.id!==id)await poll();
 if(state?.run?.id!==id)throw new Error("The new run could not be loaded. Try opening the store again.");
}});
initialize();
