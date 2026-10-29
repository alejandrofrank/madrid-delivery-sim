/* All dynamic strings enter the DOM as text. LLM replies are untrusted content. */
"use strict";
const $ = (id) => document.getElementById(id);
const colors = {bike: "#168570", moto: "#315f8b", van: "#7a638e"};
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
const {createDisplayClock, courierPosition, markerLabel} = CourierMotion;
const displayClock = createDisplayClock();
let routeLine = null, state = null, selected = null, runId = "", traceRows = [];
let tab = "fleet", busy = false, pollCount = 0, traceBusy = false;
let exploringMap = false;
const escape = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const clock = (seconds) => `${String(10 + Math.floor(seconds / 3600)).padStart(2,"0")}:${String(Math.floor(seconds % 3600 / 60)).padStart(2,"0")}`;
const human = (s) => String(s).replaceAll("_", " ");
const measured = (value, unit, digits = 1) => Number.isFinite(value) ? `${value.toFixed(digits)}${unit}` : "—";
const activeRoute = (courier) => courier?.route || courier?.reposition_route;
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
$("clear-selection").onclick = () => { selected = null; traceRows = []; renderInspector(); renderRoute(); if (state?.run) renderCouriers(); };
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
      body:JSON.stringify({seed:Number($("seed").value), wall_seconds:Number($("duration").value),
        dispatch:{strategy:$("dispatch-strategy").value, reposition:$("reposition-policy").value}})});
    runId = result.id; selected = null; traceRows = []; renderRoute();
    await refreshRuns(); await poll(); error("");
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
  renderInspector(); renderRoute(); renderCouriers(); await refreshTrace();
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
  for (const point of activeRoute(courier)?.points || []) include(point[1], point[0]);
  if (courier) {
    const [lat, lon] = courierPosition(courier, displayClock.time(performance.now()));
    include(lat, lon);
  }
  if (order) include(order.lat, order.lon);
  return points.length ? L.latLngBounds(points) : null;
}
function renderRoute() {
  if (routeLine) { routeLine.remove(); routeLine = null; }
  $("frame-selection").disabled = !selectedMapBounds();
  if (!state?.run || !selected) return;
  const courier = selected.kind === "courier" ? state.couriers.find(c => c.id === selected.id)
    : state.couriers.find(c => c.order_id === selected.id);
  const route = activeRoute(courier);
  if (route?.points?.length) routeLine = L.polyline(route.points.map(p => [p[1],p[0]]),
    {color:"#d08a25",weight:4,opacity:.8}).addTo(map);
}
function renderMetrics() {
  const {run,metrics:m,queue:q,complaints} = state;
  $("clock").textContent = clock(run.sim_time);
  $("run-status").textContent = run.status.toUpperCase(); $("run-status").className = `badge ${run.status}`;
  $("kpi-delivered").innerHTML = `${m.delivered} <small>/ ${m.orders}</small>`;
  $("kpi-active").textContent = `${m.active} active · ${m.pending} pending · ${m.unserved} unserved`;
  $("kpi-ontime").textContent = m.on_time_pct === null ? "—" : `${m.on_time_pct}%`;
  $("kpi-cost").textContent = m.cost_per_delivery_eur === null ? "—" : `€${m.cost_per_delivery_eur.toFixed(2)}`;
  $("operating-cost").textContent = Number.isFinite(m.operating_cost_eur) ? `€${m.operating_cost_eur.toFixed(2)}` : "—";
  $("empty-distance").textContent = measured(m.empty_km, " km");
  $("reposition-distance").textContent = measured(m.reposition_km, " km");
  const policy = state.dispatch_policy || run.dispatch_policy;
  const strategy = policy?.strategy === "min_cost" ? "Lowest estimated cost"
    : policy?.strategy === "legacy" || !policy ? "Earliest completion (legacy)" : human(policy.strategy);
  const reposition = policy?.reposition === "demand_aware" ? "Move toward demand" : "Stay at drop-off";
  $("dispatch-policy-summary").textContent = `Run policy: ${strategy} · ${reposition}`;
  $("dispatch-policy-evidence").textContent = JSON.stringify(policy || {strategy:"legacy", reposition:"stay"}, null, 2);
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
  const sim = displayClock.time(performance.now());
  for (const c of state.couriers) {
    const selectedClass = selected?.kind === "courier" && selected.id === c.id ? " selected" : "";
    const home = String(c.hub || c.id.split("-")[0]).slice(0,1).toUpperCase();
    const icon = L.divIcon({className: `courier-icon${selectedClass}`,iconSize:[54,24],iconAnchor:[27,12],
      html:`<span style="background:${colors[c.mode]}">${escape(home)}·${escape(markerLabel(c))}</span>`});
    const location = courierPosition(c, sim);
    let marker = courierMarkers.get(c.id);
    if (!marker) {
      marker = L.marker(location,{icon,title:c.id,keyboard:true}).addTo(map);
      marker.on("click",()=>choose("courier",c.id)); courierMarkers.set(c.id,marker);
    } else marker.setIcon(icon).setLatLng(location);
    marker.setZIndexOffset(selectedClass ? 1000 : 0);
    marker.bindTooltip(`${escape(c.id)} · ${escape(human(c.status))}<br>Home base: ${escape(human(c.hub))}`);
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
  if (!state?.run) return;
  if (selected?.kind === "courier") {
    const c = state.couriers.find(c => c.id === selected.id);
    if (c) $("selection").innerHTML = `<strong>${escape(c.id)} · ${escape(c.mode)}</strong><p>${escape(human(c.status))} · ${c.energy.toFixed(1)}% energy<br>${escape(c.order_id || (c.status === "repositioning" ? "Moving toward expected demand" : "No active order"))}</p><dl class="courier-facts"><div><dt>Home base</dt><dd>${escape(human(c.hub))}</dd></div><div><dt>Current position</dt><dd>Node ${escape(c.node ?? "—")}<br>${measured(c.lat,"",5)}, ${measured(c.lon,"",5)}</dd></div><div><dt>Completed jobs</dt><dd>${measured(c.completed_jobs,"",0)}</dd></div><div><dt>Distance</dt><dd>${measured(c.distance_m/1000," km")}</dd></div><div><dt>Empty travel</dt><dd>${measured(Number.isFinite(c.empty_distance_m) ? c.empty_distance_m/1000 : null," km")}</dd></div><div><dt>Repositioning</dt><dd>${measured(Number.isFinite(c.reposition_distance_m) ? c.reposition_distance_m/1000 : null," km")}</dd></div><div><dt>Operating cost</dt><dd>${Number.isFinite(c.operating_cost_eur) ? `€${c.operating_cost_eur.toFixed(2)}` : "—"}</dd></div></dl>`;
  } else if (selected?.kind === "order") {
    const o = state.orders.find(o=>o.id===selected.id);
    $("selection").innerHTML = `<span class="eyebrow">ORDER TRACE</span><strong>${escape(selected.id)}</strong><p>${escape(o?.store || "Delivery order")}<br>${escape(human(o?.status || "Recorded"))} · events correlate by order ID</p>`;
  } else $("selection").innerHTML = `<strong>${state.couriers.length} couriers / 3 home bases</strong><p>Select a courier to inspect its current position and work. Home base stays part of its name after it moves.</p>`;
  $("fleet").innerHTML = state.couriers.map(c => `<button class="fleet-row ${selected?.id===c.id?"active":""}" data-courier="${escape(c.id)}"><span class="mode" style="background:${colors[c.mode]}">${escape(markerLabel(c))}</span><span><strong>${escape(c.id)}</strong><small>${escape(human(c.status))}${c.order_id?` · ${escape(c.order_id)}`:""}</small></span><span class="energy">${c.energy.toFixed(0)}%</span></button>`).join("");
  document.querySelectorAll("[data-courier]").forEach(b=>b.onclick=()=>choose("courier",b.dataset.courier));
  renderDecisions();
  $("service").innerHTML = state.complaints.map(c=>`<article class="complaint"><span class="badge">${escape(human(c.status))}</span><p>${escape(c.text)}</p>${c.response?`<blockquote>${escape(c.response)}</blockquote>`:""}<small>${escape(c.source || "pending")} · approved refund €${c.approved_refund_eur.toFixed(2)}<br>${escape(c.order_id)}</small></article>`).join("") || '<p class="empty">Complaint events arrive during the simulated day.<br>Replies use the configured LLM; policy checks control refunds.</p>';
}
function renderDecisions() {
  const rows = selected ? traceRows : state?.decisions || [];
  $("decisions").innerHTML = rows.map(d=>`<article class="decision"><div class="decision-top"><span>${escape(d.agent)}</span><time>${clock(d.sim_time)}</time></div><strong>${escape(human(d.action))}</strong><p>${escape(d.detail.rule || d.detail.reply || (d.detail.on_time !== undefined ? (d.detail.on_time?"Delivered within promised window":"Delivered after promised window") : d.detail.store || "State transition recorded"))}</p><code>${escape(d.order_id || "")}${d.courier_id?` / ${escape(d.courier_id)}`:""}</code><details><summary>Inspect recorded evidence</summary><pre>${escape(JSON.stringify(d.detail,null,2))}</pre></details></article>`).join("") || '<p class="empty">No decisions recorded for this selection yet.</p>';
}
function animate() {
  if(state?.run?.status==="running") {
    const sim = displayClock.time(performance.now());
    for(const c of state.couriers)
      courierMarkers.get(c.id)?.setLatLng(courierPosition(c,sim));
  }
  requestAnimationFrame(animate);
}
async function poll() {
  if(busy) return;
  busy=true;
  try {
    const next=await api(`/api/state${runId?`?run=${runId}`:""}`);
    if(state?.run?.id && next.run?.id!==state.run.id) {
      selected=null;traceRows=[];
      for (const marker of courierMarkers.values()) marker.remove();
      courierMarkers.clear();
    }
    state=next; displayClock.accept(state.run, performance.now());
    $("connection").className="dot online"; $("connection-text").textContent="Local services connected";
    if(state.run) { renderMetrics();renderCouriers();renderOrders();renderLedger();renderInspector();renderRoute();await refreshTrace(); }
    else $("fleet").innerHTML='<p class="empty">Ready to simulate.<br>Start a day to activate the fleet.</p>';
    if(++pollCount%10===0) await refreshRuns();
  } catch(e) { $("connection").className="dot offline";$("connection-text").textContent="Connection interrupted";error(e.message); }
  finally { busy=false; }
}
async function initialize() {
  try {
    const [city,network]=await Promise.all([api("/api/world"),api("/api/roads")]);
    L.geoJSON(network,{style:{color:"#c5d0d6",weight:1.2,opacity:.8},interactive:false}).addTo(roads);
    for(const loc of city.locations) {
      if(loc.kind==="hub") L.marker([loc.lat,loc.lon],{icon:L.divIcon({className:"hub-marker",html:escape(loc.district),iconSize:null,iconAnchor:[25,25]})}).addTo(hubs);
      else if(loc.kind==="store") L.circleMarker([loc.lat,loc.lon],{radius:3,color:"#aa9369",weight:1,fillColor:"#fff",fillOpacity:1}).bindTooltip(escape(loc.name)).addTo(stores);
    }
    $("graph-info").textContent=`${city.manifest.nodes.toLocaleString()} road nodes · ${city.manifest.edges.toLocaleString()} directed edges · OSM`;
    $("fit-map").click(); await refreshRuns(); await poll();
  } catch(e) { error(e.message); }
  setInterval(poll,1000); animate();
}
initialize();
