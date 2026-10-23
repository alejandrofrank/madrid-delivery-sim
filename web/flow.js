'use strict';
const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const roles = [
 ['Inventory', 'Reserves confirmed stock. Cannot pick items or move couriers.'],
 ['Fulfillment', 'Picks a reserved basket at its assigned store. Cannot change stock policy or delivery routes.'],
 ['Dispatcher', 'Assigns couriers and routes. The world engine moves couriers and records authoritative arrival. Cannot reserve or pick stock.']
];
let snapshot = null, runId = new URLSearchParams(location.search).get('run'), pollTimer = null;
function renderRoles(agents = []) {
 $('roles').innerHTML = roles.map(([name, boundary]) => `<article class="role-card" data-role="${name.toLowerCase()}"><h3>${name}</h3><p>${boundary}</p></article>`).join('');
 const active=agents.filter(a=>Number(a.events_reserved)>0||Number(a.tools_reserved)>0);
 const identity=a=>`<details><summary>${escapeHTML(a.agent_id)} · ${escapeHTML(a.store)} · events ${escapeHTML(a.events_reserved)} / ${escapeHTML(a.events_limit)} · tools ${escapeHTML(a.tools_reserved)} / ${escapeHTML(a.tools_limit)}</summary><pre>${escapeHTML(JSON.stringify(a,null,2))}</pre></details>`;
 $('agent-identities').innerHTML=`<details><summary>Active agent identities (${active.length})</summary>${active.map(identity).join('')}</details><details><summary>Inactive agent identities (${agents.length-active.length})</summary>${agents.filter(a=>!active.includes(a)).map(identity).join('')}</details>`;
}
renderRoles();
const svgElement = (tag, attrs) => { const e = document.createElementNS('http://www.w3.org/2000/svg',tag); for (const [k,v] of Object.entries(attrs)) e.setAttribute(k,v); return e; };
function drawCity(data) {
 const svg = $('city'); svg.replaceChildren();
 const nodes = new Map(data.city.nodes.map(n => [String(n.id),n]));
 const coordinates = data.city.nodes;
 const minX = Math.min(...coordinates.map(n=>n.x)), maxX = Math.max(...coordinates.map(n=>n.x));
 const minY = Math.min(...coordinates.map(n=>n.y)), maxY = Math.max(...coordinates.map(n=>n.y));
 const pad = Math.max(maxX-minX,maxY-minY)*.055 || 1;
 svg.setAttribute('viewBox',`${minX-pad} ${minY-pad} ${maxX-minX+2*pad} ${maxY-minY+2*pad}`);
 const radius = pad*.16;
 for (const edge of data.city.edges) { const a=nodes.get(String(edge.from)), b=nodes.get(String(edge.to)); if(a&&b) svg.append(svgElement('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:'#ccd7dc','stroke-width':radius*.3,'data-road':''})); }
 for(const node of coordinates) svg.append(svgElement('circle',{cx:node.x,cy:node.y,r:radius*.35,fill:'#9caeb5','data-node':node.id}));
 for(const store of data.city.stores) {const n=nodes.get(String(store.node)); if(n) {const e=svgElement('rect',{x:n.x-radius,y:n.y-radius,width:radius*2,height:radius*2,fill:'#263b43'}); const t=svgElement('title',{});t.textContent=store.name||store.id;e.append(t);svg.append(e);}}
 for(const job of data.jobs) {
 const route=(job.route||[]).map(id=>nodes.get(String(id))).filter(Boolean);
 if(route.length>1) svg.append(svgElement('polyline',{points:route.map(n=>`${n.x},${n.y}`).join(' '),fill:'none',stroke:'#148674','stroke-width':radius*.6,'stroke-opacity':'.65','data-route':job.basket}));
 const customer=nodes.get(String(job.customer_node)); if(customer) svg.append(svgElement('circle',{cx:customer.x,cy:customer.y,r:radius,fill:'#fff',stroke:'#148674','stroke-width':radius*.4}));
 if(route.length) {
 const times=route.slice(1).map((n,i)=>Number(data.city.edges.find(e=>String(e.from)===String(route[i].id)&&String(e.to)===String(n.id))?.travel_seconds)||1);
 let remaining=Math.max(0,Number(data.run.sim_time)-(Number(job.depart_sim)||0)),position=route[0];
 for(let i=0;i<times.length;i++){if(remaining<=times[i]){const f=remaining/times[i];position={x:route[i].x+(route[i+1].x-route[i].x)*f,y:route[i].y+(route[i+1].y-route[i].y)*f};break;}remaining-=times[i];position=route[i+1];}
 svg.append(svgElement('circle',{cx:position.x,cy:position.y,r:radius*1.25,fill:'#d57c19',stroke:'white','stroke-width':radius*.3,'data-courier':job.courier||job.basket}));
 }
 }
 $('graph-info').textContent=`${coordinates.length} nodes · ${data.city.edges.length} directed roads`;
}
function render(data) {
 snapshot=data; $('status').textContent=data.run.status; $('clock').textContent=`Simulation ${Number(data.run.sim_time).toFixed(1)}s`;
 $('run-info').textContent=`Run ${data.run.id} · No external model calls · Local synthetic scenario`;
 const baskets=[...new Set([...data.tasks,...data.jobs].map(t=>t.basket))];
 $('baskets').innerHTML=baskets.map(b=>{const tasks=data.tasks.filter(t=>t.basket===b),jobs=data.jobs.filter(j=>j.basket===b);const status=jobs.at(-1)?.status||tasks.at(-1)?.status||'pending';const normalized=String(status).toLowerCase().replace(/[-_ ]/g,'');let index=['reserved','picking','dispatched','intransit','delivered'].indexOf(normalized);if(['picked','ready'].includes(normalized))index=1;if(['dispatch','assigned'].includes(normalized))index=2;if(normalized==='arrived')index=3;return `<article class="record" data-basket="${escapeHTML(b)}"><strong>${escapeHTML(b)} · <span data-basket-status>${escapeHTML(status)}</span></strong><p>${tasks.map(t=>escapeHTML(t.store)).join(', ')}</p><div class="steps">${['Stock reservation','Picking','Dispatch','In transit','Delivered'].map((s,i)=>`<span class="step ${i<=index?'active':''}">${s}</span>`).join('')}</div><details><summary>Task and route evidence</summary><pre>${escapeHTML(JSON.stringify({tasks,jobs},null,2))}</pre></details></article>`;}).join('');
 $('invariants').innerHTML=Object.entries(data.invariants).map(([k,v])=>`<p class="${v?'good':'bad'}">${v?'✓':'✗'} ${escapeHTML(k.replaceAll('_',' '))}</p>`).join('');
 $('stock').innerHTML=data.stock.map(s=>`<tr><td>${escapeHTML(s.store)} / ${escapeHTML(s.sku)}</td><td>${escapeHTML(s.on_hand)}</td><td>${escapeHTML(s.reserved)}</td><td>${escapeHTML(s.available_now)}</td></tr>`).join('');
 renderRoles(data.agents);
 $('decisions').innerHTML=data.decisions.map(d=>`<details><summary>${escapeHTML(d.sim_time)}s · ${escapeHTML(d.agent)} · ${escapeHTML(d.action)}</summary><pre>${escapeHTML(JSON.stringify(d.detail,null,2))}</pre></details>`).join('');
 $('events').innerHTML=data.events.map(e=>`<details><summary>${escapeHTML(e.topic)} · ${escapeHTML(e.state)}</summary><p>Event ${escapeHTML(e.id)} ← Parent ${escapeHTML(e.parent_id)}<br>Trace ${escapeHTML(e.trace_id)}<br>Producer ${escapeHTML(e.producer)} · Attempts ${escapeHTML(e.attempts)} · Due ${escapeHTML(e.due_sim)}s</p></details>`).join('');
 $('timeline').innerHTML=(data.timeline||[]).map(t=>`<tr><td>${escapeHTML(t.sim_time)}s</td><td>${escapeHTML(t.basket)}</td><td>${escapeHTML(t.label)}</td><td>${escapeHTML(t.status)}</td><td>${escapeHTML(t.node)}</td></tr>`).join('');
 $('download').href=`/api/lab/delivery-runs/${encodeURIComponent(data.run.id)}/evidence`;
 $('download').hidden=!['completed','complete','finished'].includes(data.run.status);
 drawCity(data);
 window.deliverySnapshot=data;
}
async function request(url,options){const response=await fetch(url,options);if(!response.ok)throw Error(`${response.status}: ${await response.text()}`);return response.json();}
async function poll(){try{const data=await request(`/api/lab/delivery-runs/${encodeURIComponent(runId)}`);render(data);if(['completed','complete','failed','finished'].includes(data.run.status)){ $('start').disabled=false;return;}pollTimer=setTimeout(poll,500);}catch(e){fail(e);}}
function fail(e){$('error').textContent=e.message;$('error').hidden=false;$('status').textContent='Run error';$('start').disabled=false;}
$('start').addEventListener('click',async()=>{clearTimeout(pollTimer);$('error').hidden=true;$('start').disabled=true;$('status').textContent='Starting';try{const result=await request('/api/lab/delivery-runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({seed:Number($('seed').value),playback_seconds:Number($('duration').value)})});runId=result.id;history.replaceState(null,'',`?run=${encodeURIComponent(runId)}`);await poll();}catch(e){fail(e);}});


if (runId) { $("start").disabled=true; poll(); }
