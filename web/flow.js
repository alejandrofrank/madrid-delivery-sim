'use strict';
const $=id=>document.getElementById(id);
const esc=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const svgNode=(tag,attrs={})=>{const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);return node;};
// Fictional display identities never replace authenticated role IDs.
function agentName(id){
 const [role,scope='']=String(id).split(':');
 if(role==='dispatcher')return 'Elena Vega';if(role==='judge')return 'Victor Sol';
 const first=['Lucia','Mateo','Nora','Hugo','Alba','Leo','Ines','Bruno','Clara','Gael','Vera','Marco'];
 const last={inventory:'Rios',fulfillment:'Luna',courier:'Mora'};
 const number=Number(scope.match(/\d+$/)?.[0]||1);
 return `${first[(number-1)%first.length]} ${last[role]||'Vidal'}${number>12?' '+Math.ceil(number/12):''}`;
}
function agentLabel(id){return `${agentName(id)} · ${String(id).split(':')[0]}`;}
let movementClock=null,animationRoutes=[],lastArrivals=new Set(),arrivalRun=null,lastMemoryRefresh=0;
let products=[],selectedCustomer=null,selectedBasket=null,config=null,city=null,snapshot=null,selectedStore=null,selectedAgent=null,selectedTab='overview',runId=new URLSearchParams(location.search).get('run'),pollTimer=null;
let view=null,fullView=null,mapCity=null,drag=null,storeDirty=false,legacyReadOnly=false;
const terminal=status=>['complete','completed','finished','failed'].includes(status);
async function request(url,options){const r=await fetch(url,options);if(!r.ok){let message='The request could not be completed.';try{const body=await r.json();const detail=body.detail;if(Array.isArray(detail))message=detail.map(item=>`${(item.loc||[]).filter(part=>part!=='body').join(' → ')}: ${item.msg||'Invalid value'}`).join('; ');else if(typeof detail==='string')message=detail;}catch{}throw Error(message);}return r.json();}
function fail(error){$('error').textContent=error.message;$('error').hidden=false;$('start').disabled=false;$('status').textContent='Connection error';}
function show(section){for(const id of ['welcome','configuration','store-view','agent-view','customer-view','help-view'])$(id).hidden=id!==section;}
function applyView(){if(view)$('city').setAttribute('viewBox',`${view.x} ${view.y} ${view.w} ${view.h}`);}
function zoom(factor,x=.5,y=.5){if(!view)return;const w=view.w*factor,h=view.h*factor;if(w<fullView.w*.08||w>fullView.w*2)return;view={x:view.x+(view.w-w)*x,y:view.y+(view.h-h)*y,w,h};applyView();}
$('zoom-in').onclick=()=>zoom(.75);$('zoom-out').onclick=()=>zoom(1.3);$('reset-map').onclick=()=>{view={...fullView};applyView();};
$('city').addEventListener('wheel',event=>{event.preventDefault();const r=$('city').getBoundingClientRect();zoom(event.deltaY>0?1.12:.89,(event.clientX-r.left)/r.width,(event.clientY-r.top)/r.height);},{passive:false});
$('city').addEventListener('pointerdown',event=>{if(event.target.closest('[data-store],[data-courier],[data-customer]'))return;drag={x:event.clientX,y:event.clientY,view:{...view}};$('city').setPointerCapture(event.pointerId);$('city').classList.add('dragging');});
$('city').addEventListener('pointermove',event=>{if(!drag)return;const r=$('city').getBoundingClientRect();view={...drag.view,x:drag.view.x-(event.clientX-drag.x)*drag.view.w/r.width,y:drag.view.y-(event.clientY-drag.y)*drag.view.h/r.height};applyView();});
const endMapDrag=()=>{drag=null;$('city').classList.remove('dragging');};
for(const event of ['pointerup','pointercancel','lostpointercapture'])$('city').addEventListener(event,endMapDrag);
window.addEventListener('blur',endMapDrag);
function baseMap(nextCity){
 city=nextCity;const identity=JSON.stringify([city.nodes.length,city.edges.length,city.stores.map(s=>s.id),city.customers?.length||0,city.buildings?.length||0]);if(identity===mapCity)return;mapCity=identity;
 const svg=$('city');svg.replaceChildren();const nodes=new Map(city.nodes.map(n=>[String(n.id),n]));
 const xs=city.nodes.map(n=>n.x),ys=city.nodes.map(n=>n.y),minX=Math.min(...xs),minY=Math.min(...ys),width=Math.max(...xs)-minX,height=Math.max(...ys)-minY,pad=Math.max(width,height)*.065||1;
 fullView={x:minX-pad,y:minY-pad,w:width+pad*2,h:height+pad*2};view={...fullView};applyView();
 drawCityFabric(svg,nodes,width);
 const roads=svgNode('g',{'data-layer':'roads'});let path='';for(const e of city.edges){const a=nodes.get(String(e.from)),b=nodes.get(String(e.to));if(a&&b)path+=`M${a.x},${a.y}L${b.x},${b.y}`;}roads.append(svgNode('path',{d:path,stroke:'#3a4d56','stroke-width':Math.max(width/800,.5),fill:'none'}));svg.append(roads);drawRoadDirection(svg,nodes,width);
 svg.setAttribute('data-node-count',city.nodes.length);svg.setAttribute('data-road-count',city.edges.length);
 svg.append(svgNode('g',{id:'route-layer'}),svgNode('g',{id:'customer-layer'}),svgNode('g',{id:'store-layer'}),svgNode('g',{id:'courier-layer'}));
 $('graph-info').textContent=`${city.nodes.length.toLocaleString()} junctions · ${city.stores.length} shops`;
 drawStores();drawCustomers();applyEntityFilter();
}
function storeData(store){return config?.stores?.find(s=>s.id===store.id)||store;}
function drawStores(){const layer=$('store-layer');if(!layer)return;layer.replaceChildren();const nodes=new Map(city.nodes.map(n=>[String(n.id),n]));const unit=fullView.w/46;
 for(const raw of city.stores){const s=storeData(raw),n=nodes.get(String(raw.node));if(!n)continue;const pharmacy=JSON.stringify(raw).toLowerCase().includes('pharmac');const g=svgNode('g',{'data-store':s.id,class:'store-marker',tabindex:0,role:'button','aria-label':`Shop ${s.name||s.id}`});
 g.append(svgNode('circle',{cx:n.x,cy:n.y,r:unit*1.3,fill:'transparent'}));g.append(svgNode('rect',{x:n.x-unit*.6,y:n.y-unit*.6,width:unit*1.2,height:unit*1.2,rx:unit*.2,fill:s.enabled===false?'#9ca9a0':pharmacy?'#799e9a':'#3d596c',stroke:selectedStore===s.id?'#63d5c5':'#c3d5dc','stroke-width':unit*.18}));
 g.append(svgNode('path',{d:`M${n.x-unit*.65},${n.y-unit*.25}h${unit*1.3}m-${unit*1.05},${unit*.15}v${unit*.45}m${unit*.55},-${unit*.45}v${unit*.45}`,stroke:'#c3d5dc','stroke-width':unit*.1,fill:'none','pointer-events':'none'}));
 const text=svgNode('text',{x:n.x+unit*.9,y:n.y+unit*.2,'font-size':unit*.65});text.textContent=s.name||s.id;g.append(text);g.onclick=()=>selectStore(s.id);g.onkeydown=e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();selectStore(s.id);}};layer.append(g);}}
// Preserve route order, including repeated junctions on pickup/delivery legs.
function routeProgress(route,durations,elapsed){
 const travelled=route.length?[route[0]]:[];let remaining=Math.max(0,elapsed),position=route[0];
 for(let i=0;i<route.length-1;i++){
  const seconds=Number(durations[i]);if(!Number.isFinite(seconds)||seconds<=0)return null;
  if(remaining<seconds){const f=remaining/seconds;position={x:route[i].x+(route[i+1].x-route[i].x)*f,y:route[i].y+(route[i+1].y-route[i].y)*f};if(f>0)travelled.push(position);return {position,travelled,remaining:[position,...route.slice(i+1)]};}
  remaining-=seconds;position=route[i+1];travelled.push(position);
 }
 return {position,travelled,remaining:[]};
}
function routeColor(id){return '#63d5c5';}
function drawMovement(data){
 const routes=$('route-layer'),couriers=$('courier-layer');if(!routes)return;routes.replaceChildren();couriers.replaceChildren();
 const nodes=new Map(city.nodes.map(n=>[String(n.id),n])),edges=new Map(city.edges.map(e=>[`${e.from}:${e.to}`,e]));const unit=fullView.w/110,drawn=new Set();
 for(const job of data.jobs||[]){
  const ids=job.route||[],route=ids.map(id=>nodes.get(String(id)));if(!route.length||route.some(n=>!n))continue;
  // Missing or forbidden edges must never become straight-line shortcuts.
  if(ids.some((id,i)=>i>0&&!edges.has(`${ids[i-1]}:${id}`)))continue;
  const active=['assigned','in_transit','arrived'].includes(job.status),failed=['abandoned','stranded'].includes(job.status);
  const selected=selectedBasket===job.basket||selectedStore===job.store||selectedAgent===`courier:${job.courier}`;
  const attempts=(data.attempts||[]).filter(a=>a.basket===job.basket&&a.courier===job.courier),attempt=attempts.at(-1);
  const accepted=job.accepted===true||attempt?.accepted===true;
  const durations=job.route_durations?.length?job.route_durations:attempt?.edge_durations||ids.slice(1).map((id,i)=>edges.get(`${ids[i]}:${id}`).travel_seconds);
  const elapsed=job.status==='delivered'?Infinity:accepted&&!failed?Math.max(0,Number(data.run.sim_time)-Number(job.depart_sim??data.run.sim_time)):0;
  const progress=routeProgress(route,durations,elapsed);if(!progress)continue;
  const color=failed?'#f28e8e':routeColor(job.courier||job.basket);
  if(active||selected){
   const group=svgNode('g',{'data-route-basket':job.basket,'data-route-courier':job.courier||'', 'data-route-status':job.status});
   const title=svgNode('title');title.textContent=`${job.courier?agentLabel(`courier:${job.courier}`):'Awaiting courier'} · ${job.basket} · solid: travelled, dashed: remaining`;group.append(title);
   const line=(points,kind)=>{if(points.length<2)return;group.append(svgNode('polyline',{points:points.map(n=>`${n.x},${n.y}`).join(' '),'data-route-part':kind,fill:'none',stroke:color,'stroke-width':unit*(selected ? .32 : .22),'stroke-opacity':kind==='travelled'?'.4':'.9','stroke-dasharray':kind==='remaining'?`${unit*.65} ${unit*.4}`:'none','stroke-linejoin':'round','stroke-linecap':'round'}));};
   line(progress.travelled,'travelled');line(progress.remaining,'remaining');
   const end=route.at(-1);group.append(svgNode('path',{'data-route-end':job.basket,d:`M${end.x},${end.y-unit*.55}l${unit*.55},${unit*.55}l-${unit*.55},${unit*.55}l-${unit*.55},-${unit*.55}Z`,fill:'#c3d5dc',stroke:color,'stroke-width':unit*.15}));routes.append(group);
  }
  if(failed){const n=nodes.get(String(job.parcel_node))||route[0];routes.append(svgNode('path',{d:`M${n.x-unit/2},${n.y-unit/2}l${unit},${unit}m0,-${unit}l-${unit},${unit}`,stroke:'#b25b48','stroke-width':unit*.3}));}
  if(!active||!accepted||!job.courier||drawn.has(job.courier)||['failed','dropped','dropout','abandoned','rejected'].includes(attempt?.status))continue;
  courierMarker(job.courier,progress.position,unit,couriers,'active',color);drawn.add(job.courier);
 }
 for(const courier of data.fleet||[]){if(drawn.has(courier.id))continue;const n=nodes.get(String(courier.node));if(n)courierMarker(courier.id,n,unit,couriers,courier.status,routeColor(courier.id));}
}
function courierMarker(id,n,unit,layer,status='active',color='#d48628'){unit*=1.8;const g=svgNode('g',{'data-courier':id,class:'courier-marker',role:'button',tabindex:0,'aria-label':`${agentLabel(`courier:${id}`)} · ${status}`,'data-anchor-x':n.x,'data-anchor-y':n.y});g.append(svgNode('circle',{cx:n.x,cy:n.y,r:unit*.75,fill:'transparent'}),svgNode('circle',{cx:n.x,cy:n.y,r:unit*.4,fill:['offline','dropped','dropout','unavailable'].includes(status)?'#8b9490':color,stroke:'#c3d5dc','stroke-width':unit*.12}));g.append(svgNode('path',{d:`M${n.x-unit*.25},${n.y}h${unit*.5}m-${unit*.15},0l-${unit*.12},-${unit*.2}`,stroke:'#c3d5dc','stroke-width':unit*.1,fill:'none','pointer-events':'none'}));const label=svgNode('title');label.textContent=agentLabel(`courier:${id}`);g.append(label);g.onclick=()=>inspectAgent(`courier:${id}`);g.onkeydown=e=>{if(e.key==='Enter')inspectAgent(`courier:${id}`);};layer.append(g);}
function selectStore(id){selectedCustomer=null;selectedBasket=null;selectedStore=id;selectedAgent=null;storeDirty=false;show('store-view');selectedTab='overview';for(const button of document.querySelectorAll('[data-tab]'))button.setAttribute('aria-selected',button.dataset.tab===selectedTab);renderStore();drawStores();if(snapshot)drawMovement(snapshot);}
function renderStore(preserveEdits=false){if(!selectedStore||!city)return;const raw=city.stores.find(s=>s.id===selectedStore);if(!raw)return;const store=storeData(raw),editable=Boolean(config)&&!legacyReadOnly;$('context-title').textContent=store.name||store.id;
 $('store-overview').hidden=selectedTab!=='overview';$('store-stock').hidden=selectedTab!=='stock';$('store-team').hidden=selectedTab!=='team';
 const jobs=(snapshot?.jobs||[]).filter(j=>j.store===store.id),scheduled=(snapshot?.order_schedule||[]).filter(o=>o.store===store.id);
 const keepForm=preserveEdits&&(storeDirty||document.activeElement?.closest('#store-form'));
 if(!keepForm){
 $('store-overview').innerHTML=`<p class="muted">${esc(raw.domain||raw.kind||raw.type||'Local shop')} · ${esc(store.id)}</p><form id="store-form"><label>Name<input name="name" type="text" minlength="1" maxlength="60" required value="${esc(store.name||store.id)}" ${editable?'':'disabled'}></label><label>Open for orders<input name="enabled" type="checkbox" ${store.enabled!==false?'checked':''} ${editable?'':'disabled'}></label><label>Stock units<input name="stock_units" type="number" min="0" max="20" value="${store.stock_units??3}" ${editable?'':'disabled'}></label><label>Couriers<input name="couriers" type="number" min="0" max="3" value="${store.couriers??1}" ${editable?'':'disabled'}></label><label>Demand weight<input name="demand_weight" type="number" min="0" max="3" step="0.1" value="${store.demand_weight??1}" ${editable?'':'disabled'}></label>${editable?'<button type="submit">Save shop for next run</button>':'<p>This saved run has a read-only shop configuration.</p>'}</form><p id="store-saved" class="muted"></p><h3>Orders</h3><p>${scheduled.length} scheduled · ${jobs.filter(j=>j.status==='delivered').length} delivered</p>${jobs.map(j=>`<div class="record"><strong>${esc(j.basket)}</strong> <span class="badge">${esc(j.status)}</span><p class="muted">${esc(j.courier?agentLabel(`courier:${j.courier}`):'Waiting for courier')}</p></div>`).join('')}`;
 $('store-form').onsubmit=event=>{event.preventDefault();if(!editable)return;const form=new FormData(event.target);Object.assign(store,{name:String(form.get('name')),enabled:form.has('enabled'),stock_units:Number(form.get('stock_units')),couriers:Number(form.get('couriers')),demand_weight:Number(form.get('demand_weight'))});storeDirty=false;$('store-saved').textContent='Saved for the next simulation.';$('context-title').textContent=store.name;drawStores();};
 $('store-form').oninput=()=>{storeDirty=true;};
 }
 const stock=(snapshot?.stock||[]).filter(s=>s.store===store.id);$('store-stock').innerHTML=stock.length?`<p class="muted">${stock.length} products stocked at this shop</p><table><thead><tr><th>Product</th><th>On hand</th><th>Reserved</th><th>Available</th></tr></thead><tbody>${stock.map(s=>`<tr><td>${esc(productName(s.sku,s.product_name||s.name))}<details><summary>SKU</summary>${esc(s.sku)}</details></td><td>${esc(s.on_hand)}</td><td>${esc(s.reserved)}</td><td>${esc(s.available_now)}</td></tr>`).join('')}</tbody></table>`:'<p>Stock appears when the simulation starts.</p>';
 const fleet=(snapshot?.fleet||[]).filter(c=>c.home_store===store.id);$('store-team').innerHTML=`<p>Inspect one agent’s role, tools and private memory at a time. Home-base couriers join the shared fleet; each courier sees only its own job. A home base grants no stock access.</p>${[['inventory:'+store.id,'Inventory','Reserves available stock'],['fulfillment:'+store.id,'Fulfillment','Picks reserved baskets'],...fleet.map(c=>['courier:'+c.id,c.id,c.status])].map(([id,name,detail])=>`<button class="agent-button" data-agent="${esc(id)}">${esc(agentName(id))}<small>${esc(name)} · ${esc(detail)}</small></button>`).join('')}${snapshot?'':'<p class="muted">Start a simulation to inspect agent memory.</p>'}`;
}
for(const button of document.querySelectorAll('[data-tab]'))button.onclick=()=>{selectedTab=button.dataset.tab;for(const b of document.querySelectorAll('[data-tab]'))b.setAttribute('aria-selected',b===button);renderStore();};
function agentSettings(data){
 const parameters=data.parameters||{},budget=data.agent?.budget||{},store=parameters.store;
 const rows=[];
 if(parameters.home_store)rows.push(['Home base',parameters.home_store]);
 if(store)rows.push(['Shop',store.name||store.id],['Stock units',store.stock_units],['Home-base couriers',store.couriers],['Demand weight',store.demand_weight],['Accepting orders',store.enabled?'Yes':'No']);
 for(const [key,label] of [['traffic_multiplier','Traffic multiplier'],['dropout_rate_per_hour','Dropout per courier-hour'],['memory_ttl_seconds','Memory lifetime (seconds)'],['max_total_attempts','Maximum attempts'],['max_retry_route_minutes','Retry route limit (minutes)']])if(parameters[key]!==undefined)rows.push([label,parameters[key]]);
 if(parameters.settings_apply)rows.push(['Settings apply',String(parameters.settings_apply).replaceAll('_',' ')]);
 const budgetLabels={events_reserved:'Events reserved',tools_reserved:'Tools reserved',events_limit:'Event allowance',tools_limit:'Tool allowance',events_used:'Events used',tools_used:'Tools used'};
 for(const [key,value]of Object.entries(budget))if(key in budgetLabels&&typeof value!=='object')rows.push([budgetLabels[key]||key.replaceAll('_',' '),value]);
 if(data.expired_memory_count)rows.push(['Expired memory records',data.expired_memory_count]);
 return rows.length?`<table><tbody>${rows.map(([label,value])=>`<tr><td>${esc(label)}</td><td>${esc(value)}</td></tr>`).join('')}</tbody></table>`:'<p class="muted">Frozen settings available in the role definition.</p>';
}
async function inspectAgent(id,quiet=false){
 selectedCustomer=null;selectedAgent=id;show('agent-view');renderDriverLive();if(snapshot)drawMovement(snapshot);$('context-title').textContent=agentLabel(id);
 if(!quiet){window.selectedAgentEvidence=null;$('agent-content').innerHTML='<p>Loading this agent’s memory…</p>';}lastMemoryRefresh=performance.now();
 if(!runId){$('agent-content').innerHTML='<p>Start a simulation to inspect this agent.</p>';return;}
 try{
  const data=await request(`/api/lab/city-runs/${encodeURIComponent(runId)}/agents/${encodeURIComponent(id)}`);
  if(selectedAgent!==id)return;
  window.selectedAgentEvidence=data;lastMemoryRefresh=performance.now();renderDriverLive();const agent=data.agent;
  const memories=(data.memory||[]).map(m=>`<details class="record"><summary>${esc(m.key)}</summary><pre>${esc(JSON.stringify(m.body,null,2))}</pre><small>Observed ${esc(m.observed_sim)}s · expires ${esc(m.expires_sim)}s · event ${esc(m.event_id)}</small></details>`).join('');
  $('agent-content').innerHTML=`<button id="refresh-agent">Refresh this agent’s memory</button>
   <span class="badge">${esc(agent.agent_id)}</span><h3>Private memory · ${(data.memory||[]).length} records</h3>
   ${memories||'<p>No current private memory. Records may have expired or this agent may have no observations yet.</p>'}
   ${data.expired_memory_count?`<p class="muted">${esc(data.expired_memory_count)} expired records are excluded.</p>`:''}
   <details open><summary>Agent settings</summary>${agentSettings(data)}</details>
   <details><summary>Role, tools and frozen definition</summary><pre>${esc(JSON.stringify({tools:agent.tools,limits:agent.limits,soul:agent.soul,definition_hash:agent.definition_hash},null,2))}</pre></details>
   <h3>Shared courier briefings</h3><p class="muted">Simulated queued messages; no real calls.</p>
   ${(data.briefs||[]).map(b=>`<details><summary>Basket ${esc(b.basket)} · attempt ${esc(b.attempt)}</summary><pre>${esc(JSON.stringify(b.body,null,2))}</pre></details>`).join('')||'<p>No briefings for this agent.</p>'}`;
 }catch(error){$('agent-content').innerHTML=`<p class="bad">${esc(error.message)}</p>`;}
}
document.addEventListener('click',event=>{if(event.target.closest('#refresh-agent')&&selectedAgent){inspectAgent(selectedAgent);return;}const button=event.target.closest('[data-agent]');if(button)inspectAgent(button.dataset.agent);});$('back-store').onclick=()=>selectedStore?selectStore(selectedStore):resetPanel();function resetPanel(){selectedCustomer=null;selectedBasket=null;selectedAgent=null;selectedStore=null;show('welcome');$('context-title').textContent='Operations watch';drawStores();}$('close-panel').onclick=resetPanel;
$('configure').onclick=()=>{selectedCustomer=null;selectedAgent=null;if(legacyReadOnly){legacyReadOnly=false;storeDirty=false;populateConfig();$('config-saved').textContent='New-session defaults restored. This saved run’s evidence stays unchanged.';}show('configuration');$('context-title').textContent='Configure city';$('configure').setAttribute('aria-expanded','true');};
function populateConfig(){if(!config)return;for(const input of $('global-form').elements){if(input.name&&config[input.name]!==undefined)input.value=config[input.name];}$('speed').value=String(config.playback_seconds||30);}
$('global-form').onsubmit=event=>{event.preventDefault();if(!config)return;for(const [key,value] of new FormData(event.target))config[key]=(key==='agent_mode'?String(value):Number(value));$('config-saved').textContent='Saved for the next simulation.';};$('speed').onchange=()=>{if(config)config.playback_seconds=Number($('speed').value);};
function render(data){const ai=data.agent_runtime?.decision_mode==='gcp_ai_judge';document.querySelector('.mode-badge').textContent=ai?`GCP judge · ${data.agent_runtime.model_calls} completed calls`:'Rules only · no AI calls';$('help-view').innerHTML=ai?'<p>The recovery judge calls a private GCP Vertex AI gateway. Inventory, fulfillment, dispatch and couriers use local rules. The model receives bounded numeric recovery facts, not household profiles, product lists or private memory text.</p><p>Durable call and token reservations precede requests. SQL enforces retry, deadline and cost limits. Provider failures deny recovery.</p>':'<p>Agents are deterministic workers with separate identities, tools, memory and budgets. No model calls are made in local mode.</p>';updateMovementClock(data);renderOperations(data);snapshot=data;announceArrivals(data);window.deliverySnapshot=data;$('status').textContent=data.run.status;$('clock').textContent=`${String(Math.floor(data.run.sim_time/60)).padStart(2,'0')}:${String(Math.floor(data.run.sim_time%60)).padStart(2,'0')}`;baseMap(data.city);drawMovement(data);cacheAnimationRoutes(data);renderDriverLive();applyEntityFilter();if(selectedCustomer)renderCustomer();const jobs=data.jobs||[],delivered=jobs.filter(j=>j.status==='delivered').length;$('run-summary').textContent=`${delivered} delivered · ${jobs.filter(j=>['assigned','in_transit'].includes(j.status)).length} on the road · ${(data.order_schedule||[]).length} scheduled`;const session=data.session_summary?.completion_reason?data.session_summary:null;if(session&&terminal(data.run.status)){const reason=session.completion_reason==='budget_limit'?'Stopped at session budget':'Observation window ended';$('status').textContent=reason;$('run-summary').textContent=`${reason} · ${delivered} delivered · ${session.unfinished_jobs} unfinished · ${session.scheduled_orders} scheduled`;} $('outcomes').textContent=`${jobs.length} baskets · ${delivered} delivered${session?' · '+session.unfinished_jobs+' unfinished':''}`;if(selectedStore&&!selectedAgent&&!selectedCustomer)renderStore(true);$('timeline').innerHTML=(data.timeline||[]).map(t=>`<div class="record"><small>${esc(t.sim_time)}s</small> ${esc(t.label)} · ${esc(t.basket)} <span class="badge">${esc(t.status)}</span></div>`).join('');$('trace').innerHTML=`<pre>${esc(JSON.stringify({invariants:data.invariants,incidents:data.incidents,reviews:data.reviews,events:data.events,decisions:data.decisions},null,2))}</pre>`;$('download').href=`/api/lab/delivery-runs/${encodeURIComponent(data.run.id)}/evidence`;$('download').hidden=!terminal(data.run.status);}
async function poll(){try{const data=await request(`/api/lab/delivery-runs/${encodeURIComponent(runId)}`);render(data);if(selectedAgent?.startsWith('courier:')&&performance.now()-lastMemoryRefresh>4000)inspectAgent(selectedAgent,true);if(terminal(data.run.status)){$('start').disabled=false;return;}pollTimer=setTimeout(poll,500);}catch(error){fail(error);}}
$('start').onclick=async()=>{if(!config)return;clearTimeout(pollTimer);$('error').hidden=true;$('start').disabled=true;$('status').textContent='Starting';try{config.playback_seconds=Number($('speed').value);const result=await request('/api/lab/city-runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(config)});runId=result.id;history.replaceState(null,'',`?run=${encodeURIComponent(runId)}`);selectedAgent=null;resetPanel();await poll();}catch(error){fail(error);}};
(async()=>{try{const result=await request('/api/lab/city-config');products=result.products||[];config=structuredClone(result.defaults);$('agent-mode').querySelector('[value="gcp_ai"]').disabled=!result.agent_modes?.gcp_ai;baseMap(result.city);populateConfig();$('status').textContent='Ready';window.cityConfig=config;if(runId){const data=await request(`/api/lab/delivery-runs/${encodeURIComponent(runId)}`);legacyReadOnly=!data.config;config=data.config?structuredClone(data.config):config;populateConfig();render(data);if(!terminal(data.run.status)){$('start').disabled=true;pollTimer=setTimeout(poll,500);}}}catch(error){if(runId){config=null;await poll();}else fail(error);}})();
function productName(sku,fallback){if(fallback)return fallback;const p=products.find(p=>p.listing_id===sku||p.sku===sku||`${p.source}:${p.listing_id}`===sku);return p?.name||sku;}
function drawCityFabric(svg,nodes,width){
 const layer=svgNode('g',{'data-layer':'buildings','pointer-events':'none'});
 for(const area of city.neighborhoods||[]){layer.append(svgNode('rect',{x:area.x,y:area.y,width:area.width,height:area.height,fill:'#19252a',stroke:'#161d2b','stroke-width':width/1500,rx:width/300}));const text=svgNode('text',{x:Number(area.x)+Number(area.width)/2,y:Number(area.y)+Number(area.height)*.15,'text-anchor':'middle','font-size':width/85,class:'neighborhood-label'});text.textContent=area.name;layer.append(text);}
 for(const b of city.buildings||[]){const colors={home:'#25343a',apartment:'#25343a',park:'#223831',office:'#26363d'};layer.append(svgNode('rect',{x:b.x,y:b.y,width:b.width,height:b.height,rx:Math.min(b.width,b.height)*.14,fill:colors[b.kind]||'#26363d',stroke:'#354750','stroke-width':width/2200,'data-building':b.id,'data-kind':b.kind}));if(b.kind==='park'){layer.append(svgNode('circle',{cx:Number(b.x)+Number(b.width)/2,cy:Number(b.y)+Number(b.height)/2,r:Math.min(b.width,b.height)*.25,fill:'#315a44'}));}}
 svg.append(layer);
}
function drawRoadDirection(svg,nodes,width){
 const layer=svgNode('g',{'data-layer':'road-directions','pointer-events':'none'}),pairs=new Set(city.edges.map(e=>`${e.from}:${e.to}`)),seenLabels=new Set();const unit=width/750;
 for(const edge of city.edges){const a=nodes.get(String(edge.from)),b=nodes.get(String(edge.to));if(!a||!b)continue;const oneWay=!pairs.has(`${edge.to}:${edge.from}`);if(oneWay){const dx=b.x-a.x,dy=b.y-a.y,length=Math.hypot(dx,dy)||1,ux=dx/length,uy=dy/length,x=(a.x+b.x)/2,y=(a.y+b.y)/2;layer.append(svgNode('path',{d:`M${x-ux*unit-uy*unit},${y-uy*unit+ux*unit}L${x+ux*unit},${y+uy*unit}L${x-ux*unit+uy*unit},${y-uy*unit-ux*unit}`,stroke:'#7b858e','stroke-width':unit*.5,fill:'none','data-direction':`${edge.from}:${edge.to}`}));}
 const name=edge.name||edge.road_name;if(name&&!seenLabels.has(name)){seenLabels.add(name);const text=svgNode('text',{x:(a.x+b.x)/2,y:(a.y+b.y)/2-width/600,'font-size':width/240,class:'road-label'});text.textContent=name;layer.append(text);}}
 svg.append(layer);
}
function drawCustomers(){const layer=$('customer-layer');if(!layer)return;layer.replaceChildren();const nodes=new Map(city.nodes.map(n=>[String(n.id),n])),homes=new Map((city.buildings||[]).map(b=>[b.id,b])),unit=fullView.w/108;
 for(const customer of city.customers||[]){const home=homes.get(customer.home_id),node=nodes.get(String(customer.home_node));if(!home&&!node)continue;const x=home?Number(home.x)+Number(home.width)/2:node.x,y=home?Number(home.y)+Number(home.height)/2:node.y;const selected=selectedCustomer===customer.id;const g=svgNode('g',{'data-customer':customer.id,class:'customer-marker',role:'button',tabindex:0,'aria-label':`${customer.name} · ${customer.id}`});g.append(svgNode('circle',{cx:x,cy:y,r:unit*1.5,fill:'transparent'}),svgNode('path',{d:`M${x-unit*.8},${y}L${x},${y-unit*.7}L${x+unit*.8},${y}V${y+unit*.65}H${x-unit*.8}Z`,fill:selected?'#63d5c5':'#aab4bd',stroke:selected?'#a02e2e':'#5c6771','stroke-width':unit*.16}),svgNode('path',{d:`M${x-unit*.16},${y+unit*.65}V${y+unit*.16}h${unit*.32}v${unit*.49}`,stroke:'#5c6771','stroke-width':unit*.15,fill:'none'}));if(selected){const text=svgNode('text',{x:x+unit,y:y-unit,'font-size':unit*.9});text.textContent=customer.name;g.append(text);}g.onclick=()=>selectCustomer(customer.id);g.onkeydown=e=>{if(e.key==='Enter')selectCustomer(customer.id);};layer.append(g);}
 $('customer-options').innerHTML=(city.customers||[]).map(c=>`<option value="${esc(c.name)} · ${esc(c.id)}"></option>`).join('');
}
function selectCustomer(id,basket=null){selectedCustomer=id;selectedBasket=basket;selectedStore=null;selectedAgent=null;show('customer-view');renderCustomer();drawCustomers();if(snapshot)drawMovement(snapshot);applyEntityFilter();}
function renderCustomer(){const customer=(city.customers||[]).find(c=>c.id===selectedCustomer);if(!customer)return;$('context-title').textContent=customer.name;const time=Number(snapshot?.run.sim_time||0),orders=(snapshot?.order_schedule||[]).filter(o=>o.customer_id===customer.id||o.home_id===customer.home_id),groups={Upcoming:[],Active:[],Past:[]};for(const order of orders){const job=(snapshot?.jobs||[]).find(j=>j.basket===order.basket),task=(snapshot?.tasks||[]).find(t=>t.basket===order.basket);const state=job?.status||task?.status||'scheduled';const future=Number(order.arrival_sim)>time,done=['delivered','abandoned','rejected','request_rejected'].includes(state);groups[future?'Upcoming':done?'Past':'Active'].push({order,state:future?'Scheduled':state});}
 $('customer-view').innerHTML=`<span class="badge">${esc(customer.id)}</span><p>${esc(customer.address)}</p><p class="muted">Human operator view. Upcoming orders are simulated arrivals, not delivery promises.</p>${Object.entries(groups).map(([title,rows])=>`<h3>${title} orders · ${rows.length}</h3>${rows.map(({order,state})=>{const store=city.stores.find(s=>s.id===order.store);return `<button class="customer-order ${selectedBasket===order.basket?'selected':''}" data-order-basket="${esc(order.basket)}"><strong>${esc(productName(order.sku,order.product_name))}</strong><span class="badge">${esc(state)}</span><small>${esc(store?.name||order.store)} · ${esc(order.quantity)} item(s)</small><small>Arrival ${Math.round(order.arrival_sim/60)} min · deadline ${Math.round(order.deadline_sim/60)} min · ${esc(order.basket)}</small></button>`;}).join('')||'<p class="muted">No orders in this stage.</p>'}`).join('')}`;
}
function applyEntityFilter(){const filter=$('entity-filter').value;for(const [id,kind]of [['store-layer','stores'],['customer-layer','customers'],['courier-layer','couriers']]){const layer=$(id);if(layer)layer.style.display=filter==='all'||filter===kind?'':'none';}}
$('entity-filter').onchange=applyEntityFilter;$('customer-search').addEventListener('input',()=>{const value=$('customer-search').value.toLowerCase(),customer=(city?.customers||[]).find(c=>`${c.name} · ${c.id}`.toLowerCase()===value||c.name.toLowerCase()===value||c.id.toLowerCase()===value);if(customer){$('entity-filter').value='customers';selectCustomer(customer.id);}});
$('agent-help').onclick=()=>{selectedCustomer=null;selectedAgent=null;show('help-view');$('context-title').textContent='How agents work';};
document.addEventListener('click',event=>{const button=event.target.closest('[data-order-basket]');if(button&&selectedCustomer)selectCustomer(selectedCustomer,button.dataset.orderBasket);});

let workspace='overview';
function renderOperations(data){
 const jobs=data?.jobs||[],schedule=data?.order_schedule||[],fleet=data?.fleet||[];
 const active=jobs.filter(j=>['assigned','in_transit','arrived'].includes(j.status)),delivered=jobs.filter(j=>j.status==='delivered');
 const exceptions=jobs.filter(j=>['abandoned','stranded','deferred','rejected'].includes(j.status));
 const metrics=[['Order volume',schedule.length?schedule.filter(o=>o.arrival_sim<=Number(data?.run.sim_time||0)).length:jobs.length,'Arrived this session'],['In progress',active.length,'Assigned & on the road'],['Delivered',delivered.length,'Confirmed handoffs'],['Available fleet',fleet.filter(c=>c.status==='active'&&!c.busy_basket).length,`${fleet.length} couriers in network`],['Exceptions',exceptions.length,'Require operational review']];
 $('operation-metrics').innerHTML=metrics.map(([label,value,note],i)=>`<div class="metric ${i===4&&value?'metric-warning':''}"><span>${label}</span><strong>${data?value:'—'}</strong><small>${note}</small></div>`).join('');
 $('workspace-run').textContent=data?`SESSION ${String(data.run.id).slice(0,8).toUpperCase()}`:'Local environment';
 $('network-health').textContent=data?`${active.length} active deliveries · ${fleet.length} couriers`:'12 establishments · 128 households';
 const feed=(data?.incidents||[]).slice(-5).reverse();
 $('activity-feed').innerHTML=feed.length?feed.map(i=>`<div class="activity-item"><span class="activity-dot"></span><div><strong>${esc(String(i.kind).replaceAll('_',' '))}</strong><small>${Math.round(Number(i.sim_time||0)/60)} min · ${esc(i.basket||i.courier||'Network')}</small></div></div>`).join(''):'<div class="empty-state">No incidents recorded.<small>Traffic, withdrawals and recovery decisions appear here.</small></div>';
 renderBoard(data);
}
function renderBoard(data=snapshot){
 const fleet=data?.fleet||[],jobs=data?.jobs||[],schedule=data?.order_schedule||[],filter=$('board-filter').value;
 $('board-title').textContent={overview:'Order book',orders:'Order book',fleet:'Fleet roster',stores:'Establishment network'}[workspace];
 $('board-filter').parentElement.hidden=['fleet','stores'].includes(workspace);
 if(workspace==='fleet'){$('board-content').innerHTML=`<div class="entity-cards">${fleet.map(c=>`<button data-agent="courier:${esc(c.id)}" class="entity-card"><span class="avatar">${esc(agentName('courier:'+c.id).slice(0,1))}</span><strong>${esc(agentName('courier:'+c.id))}</strong><small>${esc(c.id)} · ${esc(c.status)}</small><span class="badge">${esc(c.busy_basket||'Available')}</span></button>`).join('')||'<div class="empty-state">Start a session to see your courier team.</div>'}</div>`;return;}
 if(workspace==='stores'){$('board-content').innerHTML=`<div class="entity-cards">${(city?.stores||[]).map(raw=>{const st=storeData(raw);return `<button class="entity-card" data-open-store="${esc(st.id)}"><strong>${esc(st.name||st.id)}</strong><small>${esc(raw.domain||'Establishment')} · ${esc(st.id)}</small><span class="badge">${st.enabled===false?'Closed':'Accepting orders'}</span></button>`;}).join('')}</div>`;return;}
 let rows=schedule.length?schedule.filter(o=>o.arrival_sim<=Number(data?.run.sim_time||0)):jobs;
 rows=rows.filter(o=>{const j=jobs.find(j=>j.basket===o.basket),state=j?.status||data?.tasks?.find(t=>t.basket===o.basket)?.status||o.status||'scheduled';return filter==='all'||(filter==='active'?['assigned','in_transit','arrived'].includes(state):['abandoned','stranded','deferred','rejected'].includes(state));});
 $('board-content').innerHTML=rows.length?`<table class="order-table"><thead><tr><th>Order / customer</th><th>Origin</th><th>Courier</th><th>Status</th><th>Arrival</th></tr></thead><tbody>${rows.map(o=>{const j=jobs.find(j=>j.basket===o.basket),st=city?.stores?.find(s=>s.id===o.store),state=j?.status||data?.tasks?.find(t=>t.basket===o.basket)?.status||o.status||'scheduled';return `<tr><td><button class="order-link" data-open-order="${esc(o.basket)}"><strong>${esc(o.basket)}</strong><small>${esc(o.customer_name||'Delivery customer')}</small></button></td><td>${esc(st?.name||o.store||'—')}</td><td>${j?.courier?esc(agentName('courier:'+j.courier)):'<span class="muted">Unassigned</span>'}</td><td><span class="status-pill state-${esc(state)}">${esc(state.replaceAll('_',' '))}</span></td><td class="mono">${o.arrival_sim===undefined?'—':Math.round(o.arrival_sim/60)+' min'}</td></tr>`;}).join('')}</tbody></table>`:'<div class="empty-state">No orders in this view.<small>Start a simulation to watch demand arrive across the network.</small></div>';
}
$('board-filter').onchange=()=>renderBoard();
document.addEventListener('click',event=>{
 const tab=event.target.closest('[data-workspace]');if(tab){workspace=tab.dataset.workspace;for(const b of document.querySelectorAll('[data-workspace]')){b.classList.toggle('rail-active',b===tab);b.setAttribute('aria-pressed',String(b===tab));}if(workspace==='overview')resetPanel();renderBoard();if(workspace!=='overview')$('board-title').scrollIntoView({block:'nearest',behavior:'smooth'});}
 const shop=event.target.closest('[data-open-store]');if(shop)selectStore(shop.dataset.openStore);
 const order=event.target.closest('[data-open-order]');if(order){const id=order.dataset.openOrder,o=snapshot?.order_schedule?.find(o=>o.basket===id);if(o?.customer_id)selectCustomer(o.customer_id,id);else{selectedBasket=id;if(snapshot)drawMovement(snapshot);}}
});
renderOperations(null);
function updateMovementClock(data){
 const now=performance.now(),sim=Number(data.run.sim_time),same=movementClock?.run===data.run.id;
 if(!same){movementClock={run:data.run.id,from:sim,to:sim,at:now,interval:500};arrivalRun=null;}
 else if(sim!==movementClock.to){const previous=visualSimTime();movementClock={run:data.run.id,from:Math.min(previous,sim),to:sim,at:now,interval:Math.max(200,Math.min(1200,now-movementClock.at))};}
}
function visualSimTime(now=performance.now()){
 if(!movementClock)return Number(snapshot?.run.sim_time||0);
 const f=Math.max(0,Math.min(1,(now-movementClock.at)/movementClock.interval));
 return movementClock.from+(movementClock.to-movementClock.from)*f;
}
function cacheAnimationRoutes(data){
 const nodes=new Map(data.city.nodes.map(n=>[String(n.id),n]));animationRoutes=[];
 for(const job of data.jobs||[]){if(!job.accepted||!['assigned','in_transit','arrived'].includes(job.status))continue;
  const route=(job.route||[]).map(id=>nodes.get(String(id)));if(!route.length||route.some(n=>!n)||!job.route_durations?.length)continue;
  animationRoutes.push({courier:job.courier,route,durations:job.route_durations,depart:Number(job.depart_sim)});
 }
}
function renderDriverLive(){
 const box=$('driver-live');if(!selectedAgent?.startsWith('courier:')||!snapshot){box.replaceChildren();return;}
 const id=selectedAgent.slice(8),courier=snapshot.fleet.find(c=>c.id===id),job=snapshot.jobs.find(j=>j.courier===id&&['assigned','in_transit','arrived'].includes(j.status));
 const store=city.stores.find(s=>s.id===job?.store),order=snapshot.order_schedule?.find(o=>o.basket===job?.basket);
 box.innerHTML=`<div class="driver-identity"><span class="avatar">${esc(agentName(selectedAgent).slice(0,1))}</span><div><strong>${esc(agentName(selectedAgent))}</strong><small>${esc(id)} · ${esc(courier?.status||'Unknown')}</small></div></div>${job?`<div class="driver-job"><span class="eyebrow">CURRENT ORDER</span><strong>${esc(job.basket)}</strong><span class="status-pill">${esc(job.status.replaceAll('_',' '))}</span><div class="driver-route"><div><i></i><span>${esc(store?.name||job.store)}<small>Pickup · ${esc(job.accepted?'Briefing accepted':'Awaiting briefing')}</small></span></div><div><i></i><span>${esc(order?.customer_name||'Delivery customer')}<small>Drop-off · junction ${esc(job.customer_node)}</small></span></div></div><div class="driver-eta"><span>Arrival in</span><strong id="driver-eta-value">—</strong><small>Simulated time · traffic included</small></div><button id="focus-driver-route">Focus route · ${Math.max(0,job.route.length-1)} road segments</button></div>`:'<div class="empty-state">No current order.<small>This courier is available or offline. Past assignments remain in the order book.</small></div>'}`;
 const focus=$('focus-driver-route');if(focus)focus.onclick=()=>{selectedBasket=job.basket;drawMovement(snapshot);const path=job.route.map(id=>city.nodes.find(n=>n.id===id)).filter(Boolean),xs=path.map(n=>n.x),ys=path.map(n=>n.y),pad=fullView.w*.05;view={x:Math.min(...xs)-pad,y:Math.min(...ys)-pad,w:Math.max(...xs)-Math.min(...xs)+2*pad,h:Math.max(...ys)-Math.min(...ys)+2*pad};applyView();};
}
function announceArrivals(data){
 const arrived=(data.order_schedule||[]).filter(o=>o.arrival_sim<=data.run.sim_time),initial=arrivalRun!==data.run.id;
 if(initial){$('arrival-toast').hidden=true;clearTimeout(window.arrivalToastTimer);arrivalRun=data.run.id;lastArrivals=new Set(arrived.map(o=>o.basket));return;}
 const fresh=arrived.filter(o=>!lastArrivals.has(o.basket));for(const order of fresh)lastArrivals.add(order.basket);
 if(fresh.length){const order=fresh.at(-1),toast=$('arrival-toast');toast.textContent=`New order ${order.basket} · ${order.customer_name||'Customer'} · ${productName(order.sku,order.product_name)}`;toast.hidden=false;clearTimeout(window.arrivalToastTimer);window.arrivalToastTimer=setTimeout(()=>toast.hidden=true,4500);}
}
let lastDriverPaint=0;
function animateCouriers(now){
 if(document.hidden||matchMedia('(prefers-reduced-motion: reduce)').matches){requestAnimationFrame(animateCouriers);return;}
 const sim=visualSimTime(now);
 for(const track of animationRoutes){const marker=document.querySelector(`[data-courier="${CSS.escape(track.courier)}"]`);if(!marker)continue;const p=routeProgress(track.route,track.durations,Math.max(0,sim-track.depart));if(p)marker.setAttribute('transform',`translate(${p.position.x-Number(marker.dataset.anchorX)},${p.position.y-Number(marker.dataset.anchorY)})`);}
 if(now-lastDriverPaint>200){const eta=$('driver-eta-value');if(eta&&selectedAgent){const job=snapshot?.jobs?.find(j=>j.courier===selectedAgent.slice(8)&&['assigned','in_transit','arrived'].includes(j.status));if(job){const seconds=Math.max(0,Math.ceil(job.arrive_sim-sim));eta.textContent=job.accepted?`${Math.floor(seconds/60)}m ${String(seconds%60).padStart(2,'0')}s`:'Awaiting acceptance';}}lastDriverPaint=now;}
 requestAnimationFrame(animateCouriers);
}
requestAnimationFrame(animateCouriers);
