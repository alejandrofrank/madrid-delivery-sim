"use strict";
const $ = id => document.getElementById(id);
let live = null, evidence = null, runId = "", activeStore = "", polling = false;
let drawnCity = "";
let catalogueChosen = false;
const productKey = p => `${p.source}:${p.listing_id}`;
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`Request failed (${response.status}). Check the local services.`);
  return response.json();
}
function row(values) { const tr = el("tr"); values.forEach(v => tr.append(el("td", String(v)))); return tr; }
function drawCity(state) {
  const renderKey = `${state.city.sha256}:${activeStore}`;
  if (renderKey === drawnCity) return;
  drawnCity = renderKey;
  const svg = $("city"), ns = "http://www.w3.org/2000/svg";
  svg.replaceChildren();
  function shape(tag, attrs, text) {
    const node = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
    if (text) node.textContent = text;
    return node;
  }
  const nodes = new Map(state.city.nodes.map(n => [n.id, n]));
  const points = [...nodes.values()];
  const minX = Math.min(...points.map(n => n.x)), maxX = Math.max(...points.map(n => n.x));
  const minY = Math.min(...points.map(n => n.y)), maxY = Math.max(...points.map(n => n.y));
  const extent = Math.max(maxX - minX, maxY - minY, 500);
  const scale = extent / 1500;
  const padding = 200 * scale;
  svg.setAttribute("viewBox", `${minX-padding} ${minY-padding} ${maxX-minX+2*padding} ${maxY-minY+2*padding}`);
  function label(x, y, text, anchor = "start") {
    return shape("text", {x,y,"text-anchor":anchor,style:`font-size:${40*scale}px;paint-order:stroke;stroke:#f8fafb;stroke-width:${8*scale}px;stroke-linejoin:round`}, text);
  }
  state.city.edges.forEach(edge => {
    const a = nodes.get(edge.from), b = nodes.get(edge.to);
    svg.append(shape("line", {x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:"#cbd7dc","stroke-width":6*scale}));
  });
  state.city.stores.forEach(store => {
    const point = nodes.get(store.node);
    const group = shape("g", {class:"store",tabindex:0,role:"button","aria-label":`Inspect ${store.name}`});
    group.append(shape("circle", {cx:point.x,cy:point.y,r:24*scale,fill:store.id===activeStore?"#c08317":"#176c60"}));
    const anchor = point.x > (minX+maxX)/2 ? "end" : "start";
    group.append(label(point.x, point.y-45*scale, store.name, anchor));
    function choose() { activeStore = store.id; render(); }
    group.onclick = choose;
    group.onkeydown = event => { if(event.key==="Enter" || event.key===" "){event.preventDefault();choose();} };
    svg.append(group);
  });
  state.city.facilities.forEach(facility => {
    const point = nodes.get(facility.node);
    svg.append(shape("rect", {x:point.x-15*scale,y:point.y-15*scale,width:30*scale,height:30*scale,fill:"#718795"}));
    const anchor = point.x > (minX+maxX)/2 ? "end" : "start";
    svg.append(label(point.x+(anchor === "end" ? -30 : 30)*scale, point.y+15*scale, facility.kind, anchor));
  });
}
function render() {
  if (!live?.run) return;
  const checkpoint = $("checkpoint").value;
  const state = checkpoint === "live" ? live : evidence?.checkpoints[Number(checkpoint)]?.state || live;
  const products = new Map(state.catalogue.products.map(p => [productKey(p),p]));
  const target = state.stock.find(s => s.store===state.selected_store && s.sku===state.selected_product);
  $("available").textContent = target?.available_now ?? "—";
  $("reserved").textContent = target?.reserved ?? "—";
  $("incoming").textContent = target?.incoming.reduce((sum,s) => sum+s.quantity,0) ?? 0;
  $("eta").textContent = target?.incoming.length ? `Expected minute ${target.incoming[0].expected_sim/60} · forecast` : "No pending supply";
  $("product").textContent = products.get(state.selected_product)?.name || state.selected_product;
  const valid = Object.values(state.invariants).every(Boolean);
  $("invariants").textContent = valid ? "PASS" : "FAIL";
  $("invariants").className = valid ? "good" : "bad";
  $("clock").textContent = `Simulation minute ${state.run.sim_time/60} · availability as of this checkpoint`;
  $("status").textContent = live.run.status.toUpperCase();
  $("start").disabled = ["ready","running"].includes(live.run.status);
  if (!activeStore) activeStore = state.selected_store;
  $("store").replaceChildren(...state.city.stores.map(s => new Option(`${s.name} · ${s.catalogue_source || s.kind}`,s.id)));
  $("store").value = activeStore;
  $("stock").replaceChildren(...state.stock.filter(s => s.store===activeStore).map(s => {
    const p = products.get(s.sku);
    return row([p?.name||s.sku,s.on_hand,s.reserved,s.available_now,s.version]);
  }));
  const observedDates = [...new Set(state.catalogue.products.map(p => p.observed_on))].sort();
  $("provenance").textContent = `Catalogue date: ${observedDates.join(", ")}. All stock, store locations, supply and demand are simulated. Imported prices use the warehouse observation day and are not live availability.`;
  $("manifest").textContent = JSON.stringify({city_hash:state.city.sha256,catalogue_hash:state.catalogue_hash,...state.catalogue},null,2);
  $("baskets").replaceChildren(...state.baskets.map(b => el("p",`${b.id}: ${b.status} · ${b.quantity} unit · reservation deadline minute ${b.expires_sim/60}`,"record")));
  if (!state.baskets.length) $("baskets").textContent = "No committed basket effects yet.";
  $("decisions").replaceChildren(...state.decisions.map(d => {
    const record = el("div",undefined,"record");
    record.append(el("strong",`Minute ${d.sim_time/60} · ${d.action}`),el("p",d.detail.rule),el("small",JSON.stringify(d.detail)));
    return record;
  }));
  $("events").replaceChildren(...state.events.map(e => row([e.topic,e.state,e.attempts,e.due_sim/60])));
  $("recovery").textContent = evidence ? `Real process exit ${evidence.crash.exit_code}; reclaimed on attempt ${evidence.crash.recovered_attempts}. Inspect the first checkpoint to see the rolled-back write and leased event.` : "Crash after stock write, before commit: the leased event survives while stock writes roll back. Recovery waits for the wall-clock lease.";
  $("run-info").textContent = `Run ${state.run.id} · seed ${state.run.seed} · stock quantities and city are simulated`;
  if (live.run.status==="failed") { $("error").hidden=false; $("error").textContent=`Scenario failed: ${live.run.error}. State remains inspectable.`; }
  drawCity(state);
}
async function poll() {
  if(polling) return;
  polling=true;
  try {
    const requestedRun = runId;
    const state = await api(`/api/lab/state${requestedRun?`?run=${requestedRun}`:""}`);
    if (requestedRun !== runId) return;
    if (!state.run) { $("status").textContent="READY"; return; }
    if(live?.run?.id!==state.run.id) { evidence=null; activeStore=""; $("checkpoint").replaceChildren(new Option("Live / final state","live")); }
    live=state; runId=state.run.id;
    if(live.run.status==="complete" && !evidence) {
      const response=await fetch(`/api/lab/runs/${runId}/evidence`);
      if(response.ok) {
        evidence=await response.json();
        evidence.checkpoints.forEach((c,i) => $("checkpoint").add(new Option(c.label,String(i))));
        $("download").href=`/api/lab/runs/${runId}/evidence`; $("download").hidden=false;
      }
    }
    render();
  } catch(error) { $("error").hidden=false; $("error").textContent=error.message; }
  finally { polling=false; }
}
$("checkpoint").onchange=render;
$("catalogue").onchange=() => { catalogueChosen=true; };
$("store").onchange=() => {activeStore=$("store").value;render();};
$("start").onclick=async () => {
  $("start").disabled=true; $("error").hidden=true; $("download").hidden=true;
  $("status").textContent="STARTING";
  try {
    const selection = $("catalogue").value;
    const body = {seed:Number($("seed").value),catalogue:selection,playback_seconds:15};
    if (selection.startsWith("history:")) { body.catalogue="bakiano-history"; body.sample_date=selection.slice(8); }
    const result=await api("/api/lab/runs",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    runId=result.id; live=null; evidence=null; activeStore="";
    $("checkpoint").replaceChildren(new Option("Live / final state","live"));
    await poll();
  } catch(error) {$("error").hidden=false;$("error").textContent=error.message;$("start").disabled=false;}
};
api("/api/lab/catalogues").then(sources => {if(sources["bakiano-local"]) $("catalogue").add(new Option("Bakiano · local imported snapshot","bakiano-local"));}).catch(()=>{});
api("/api/lab/history").then(history => {
  if (!history.available) { $("history-coverage").textContent="No dated sample installed. The synthetic fixture runs entirely offline."; return; }
  const missing = history.days.filter(day => day.status==="missing").map(day => day.date);
  $("history-coverage").textContent=`Local Bakiano sample · ${history.start} to ${history.end} · ${history.available_days}/${history.requested_days} dates observed${missing.length?` · Missing: ${missing.join(", ")}`:""}. No live queries.`;
  [...history.days].reverse().forEach(day => {
    const option=new Option(`Bakiano · ${day.date} · ${day.products} observations${day.status==="missing"?" · missing":""}`,`history:${day.date}`);
    option.disabled=day.status==="missing"; $("catalogue").add(option);
  });
  const latest=[...history.days].reverse().find(day => day.status==="available");
  if (latest && !catalogueChosen) $("catalogue").value=`history:${latest.date}`;
}).catch(() => {$("history-coverage").textContent="The local history manifest needs repair. The synthetic fixture remains available.";});
poll(); setInterval(poll,500);
