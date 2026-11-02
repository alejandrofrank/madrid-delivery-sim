/* Real store state, lazy 3D and an accessible floor-plan fallback. */
window.StoreUI=(()=>{
 const $=id=>document.getElementById(id),esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const motion=matchMedia('(prefers-reduced-motion: reduce)');
 const names={requested:'Reserving stock',reserved:'Ready to pick',picking:'Picking shelves',packing:'Packing basket',to_dock:'Moving to dock',dock:'Waiting for courier',handed_off:'With courier',cancelled:'Order cancelled'};
 let hooks,layer,data=null,city=null,storeId=null,orderId=null,scene=null,generation=0,follow=null,loading=false,opened=false,run=null,request=0;
 function init(options){
  hooks=options;layer=L.layerGroup().addTo(hooks.map);
  $('store-demo').onclick=startDemo;
  $('store-open').onclick=()=>open($('store-select').value);
  $('store-back').onclick=()=>close(true);
  $('store-fit').onclick=()=>{scene?.fit();$('store-track').checked=false;};
  $('store-track').onchange=e=>scene?.track(e.target.checked);
  $('store-order').onchange=()=>{orderId=$('store-order').value||null;render();};
  $('store-follow').onclick=()=>{if(follow){follow=null;scene?.track(false);}else if(orderId){follow=orderId;scene?.track(true);$('store-track').checked=true;}render();};
  $('store-stop').onclick=()=>{follow=null;$('store-stop').hidden=true;$('store-follow-note').textContent='Order following stopped.';};
  $('store-incident').onclick=trigger;
  $('store-view').addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();close(true);}});
 }
 async function startDemo(){
  $('store-demo').disabled=true;$('store-follow-note').textContent='Starting a seeded store order…';
  try{
   const result=await hooks.api('/api/stores/demo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({seed:42,wall_seconds:60,chaos:$('store-demo-chaos').checked})});
   await hooks.selectRun(result.id);
   run=result.id;storeId=result.store;orderId=result.order;follow=orderId;
   await refresh();
   $("chaos-panel").open=false;
   await open(storeId,orderId);
   $('store-track').checked=true;scene?.track(true);
  }catch(error){$('store-follow-note').textContent=error.message;}
  finally{$('store-demo').disabled=false;}
 }
 async function update(next,runtime){
  city=next;
  $('store-launch').hidden=runtime.mode==='replay';
  if(runtime.mode==='replay')return;
  if(run!==next.run?.id){request++;close(false);run=next.run?.id;data=null;follow=null;}
  if(!next.run?.store_config){layer.clearLayers();$('store-select').replaceChildren(new Option('Start a store demo',''));$('store-open').disabled=true;return;}
  await refresh();
 }
 async function refresh(){
  if(!run||loading)return;
  loading=true;const key=++request,current=run;
  try{
   const next=await hooks.api('/api/runs/'+encodeURIComponent(run)+'/stores');
   if(key!==request||current!==run)return;
   data=next;layer.clearLayers();
   const value=storeId||$('store-select').value;
   $('store-select').replaceChildren(...data.stores.map(s=>new Option(s.name+' · '+s.load+' active',s.store)));
   if(data.stores.some(s=>s.store===value))$('store-select').value=value;
   $('store-open').disabled=!data.stores.length;
   for(const s of data.stores){
    const icon=L.divIcon({className:'store-pin',iconSize:null,html:esc(s.name)+' · '+s.load});
    L.marker([s.lat,s.lon],{icon,keyboard:true,title:s.name+', '+s.load+' orders. Open store.'}).on('click',()=>open(s.store)).addTo(layer);
   }
   if(opened)render();
   if(follow){
    const s=data.stores.find(s=>s.orders.some(o=>o.order_id===follow)),o=s?.orders.find(o=>o.order_id===follow);
    const delivery=city?.orders?.find(o=>o.id===follow);
    $('store-stop').hidden=false;
    $('store-follow-note').textContent=follow+' · '+(delivery?.status==='delivered'?'Delivered to the doorstep':names[o?.stage]||'Waiting for stock');
    if(o?.stage==='handed_off'){
     if(opened){close(false);hooks.choose('order',follow);hooks.locate();}
     if(delivery?.status==='delivered'){follow=null;$('store-stop').hidden=true;}
    }else if(o?.stage==='cancelled'){follow=null;$('store-stop').hidden=true;}
   }
  }catch(error){$('store-follow-note').textContent='Store state unavailable. '+error.message;}
  finally{loading=false;}
 }
 async function open(id,selectedOrder){
  const store=data?.stores.find(s=>s.store===id);if(!store)return;
  close(false);storeId=id;orderId=selectedOrder||store.orders.find(o=>!['handed_off','cancelled'].includes(o.stage))?.order_id||store.orders[0]?.order_id||null;
  const token=++generation;
  hooks.map.flyTo([store.lat,store.lon],17,{animate:!motion.matches,duration:.5});
  if(!motion.matches)await new Promise(resolve=>setTimeout(resolve,450));
  if(token!==generation)return;
  $("chaos-panel").open=false;
  opened=true;document.body.dataset.storeOpen='true';$('store-view').hidden=false;$('store-back').focus({preventScroll:true});
  $('store-view').scrollIntoView({behavior:motion.matches?'instant':'smooth',block:'start'});
  $('store-render-status').textContent='Loading local 3D models; floor plan ready.';render();
  try{
   if(new URLSearchParams(location.search).has('store-fallback'))throw new Error('Floor-plan mode selected.');
   const module=await import('./store-3d.js?v=9914096e761c');
   const built=await module.createStoreScene($('store-stage'),store,text=>{$('store-render-status').textContent=text;},()=>{
    if(token!==generation)return;
    scene?.dispose();scene=null;
    $('store-floor').removeAttribute('hidden');
    $('store-render-status').textContent='Floor plan · graphics connection lost. Order tracking still works.';
   },()=>{$('store-track').checked=true;});
   if(token!==generation){built?.dispose();return;}
   scene=built;$('store-floor').setAttribute('hidden','');scene?.track(!!follow);render();
  }catch(error){
   console.warn("Store 3D fallback:",error.message);
   if(token!==generation)return;
   $('store-render-status').textContent='Floor plan · 3D unavailable. Order tracking still works.';
   $('store-stage').querySelector('canvas')?.remove();
   $('store-floor').removeAttribute('hidden');
  }
 }
 function close(stop){
  generation++;scene?.dispose();scene=null;opened=false;
  $('store-view').hidden=true;$('store-floor').removeAttribute('hidden');
  document.body.dataset.storeOpen='false';hooks?.map.invalidateSize();
  if(stop){follow=null;$('store-stop').hidden=true;$('store-open').focus();}
 }
 function floor(store,order){
  const l=store.layout,stock=new Map(store.shelves.map(s=>[s.slot,s.quantity]));
  let body='<rect x="0" y="0" width="'+l.width+'" height="'+l.depth+'" fill="#213943"/>';
  for(let a=0;a<l.config.aisles;a++)body+='<rect x="'+(a*3+1.5)+'" y="1.2" width="1" height="'+(l.depth-4)+'" fill="#708994"/>';
  for(const s of l.slots)if(order&&Object.hasOwn(order.lines,s.sku))body+='<rect x="'+(s.x+s.side*.65-.2)+'" y="'+(s.z-.2)+'" width=".4" height=".4" fill="'+((order.picked[s.sku]||0)>=order.lines[s.sku]?'#83d6a2':stock.get(s.id)>0?'#52e5d5':'#e8ae63')+'"/>';
  for(const w of store.workers){
   if(w.route)body+='<polyline points="'+w.route.points.map(p=>p.slice(0,2).join(',')).join(' ')+'" fill="none" stroke="#52e5d5" stroke-width=".14"/>';
   body+='<circle cx="'+w.position[0]+'" cy="'+w.position[1]+'" r=".4" fill="'+(w.available?'#e0eef5':'#efaaa2')+'"/>';
  }
  for(const n of store.conditions.blocked){const p=l.nodes[n];body+='<rect x="'+(p[0]-.5)+'" y="'+(p[1]-.5)+'" width="1" height="1" fill="#e8ae63"/>';}
  body+='<text x="1" y="'+(l.depth-1)+'" font-size=".65" fill="#e0eef5">PACK</text><text x="'+(l.width-5)+'" y="'+(l.depth-1)+'" font-size=".65" fill="#e0eef5">COURIER DOCK</text>';
  $('store-floor').setAttribute('viewBox','-1 -1 '+(l.width+2)+' '+(l.depth+2));$('store-floor').innerHTML=body;
 }
 function render(){
  const store=data?.stores.find(s=>s.store===storeId);if(!store||!opened)return;
  const order=store.orders.find(o=>o.order_id===orderId);
  $('store-title').textContent=store.name+' · '+store.district;
  $('store-load').textContent=store.load+' active orders · '+store.workers.filter(w=>w.kind!=='forklift').length+' pickers'+(city?.run?.status==='running'?' · live':' · shift complete');
  const select=$('store-order'),signature=store.orders.map(o=>o.order_id).join('|');
  if(select.dataset.items!==signature){select.replaceChildren(new Option('All store work',''),...store.orders.map(o=>new Option(o.order_id,o.order_id)));select.dataset.items=signature;}
  select.value=orderId||'';
  $('store-order-title').textContent=order?order.order_id:'Store work';
  $('store-order-state').textContent=order?((order.status==='delivered'?'Delivered to the doorstep':names[order.stage]||order.stage)):'Choose an order to highlight its shelves and basket.';
  $('store-decision').textContent=order?.decision?('Fulfillment: '+(order.decision.reason||order.decision.action.replaceAll('_',' '))):'';
  const catalogue=new Map(store.catalogue.map(p=>[p.sku,p.name]));
  $('store-basket').innerHTML=order?Object.entries(order.lines).map(([sku,quantity])=>'<li data-picked="'+((order.picked[sku]||0)>=quantity)+'"><span>'+esc(catalogue.get(sku)||sku)+'</span><strong>'+(order.picked[sku]||0)+' / '+quantity+'</strong></li>').join(''):'';
  const worker=store.workers.find(w=>w.id===order?.worker),clock=data.sim_time;
  $('store-facts').innerHTML='<dt>Picker</dt><dd>'+esc(worker?.id||'Awaiting assignment')+'</dd><dt>Current step</dt><dd>'+esc(worker?.task?.action||'Waiting')+'</dd><dt>Store clock</dt><dd>'+Math.floor(clock/60)+':'+String(clock%60).padStart(2,'0')+'</dd><dt>Blocked cells</dt><dd>'+store.conditions.blocked.length+'</dd><dt>Robots offline</dt><dd>'+store.conditions.broken.length+'</dd>';
  $('store-follow').disabled=!order;$('store-follow').textContent=follow?'Stop following':'Follow this order';$('store-follow').setAttribute('aria-pressed',String(!!follow));
  $('store-trace').href='/agent-traces?source=madrid&run='+encodeURIComponent(run)+'&order='+encodeURIComponent(orderId||'');
  $('store-incident').disabled=city?.run?.status!=='running';
  floor(store,order);
  $('store-legend').textContent=scene?'Cyan: order shelves and planned path · green: picked · amber: blocked':'Cyan: order shelves and route · green: picked · amber: unavailable · circles: workers (red: offline)';
  scene?.update(store,order,{sim:clock,rate:city?.run?.status==='running'?city.run.duration/Math.max(1,city.run.wall_seconds):0});
 }
 async function trigger(){
  const button=$('store-incident');button.disabled=true;
  try{const kind=$('store-incident-kind').value;
   await hooks.api('/api/runs/'+run+'/chaos',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:'store-'+Date.now(),kind,target:storeId,duration:120})});
   $('store-incident-status').textContent='Scheduled at the next city minute. Inspect the route and decisions.';
  }catch(error){$('store-incident-status').textContent=error.message;}
  finally{button.disabled=city?.run?.status!=='running';}
 }
 function selectOrder(id){const s=data?.stores.find(s=>s.orders.some(o=>o.order_id===id));if(s)open(s.store,id);}
 return {init,update,selectOrder};
})();
