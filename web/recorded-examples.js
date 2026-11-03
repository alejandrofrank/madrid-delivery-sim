/* Explicit, read-only examples. Live execution starts only from an existing action. */
window.ProductExamples=(()=>{
 const cache=new Map();
 async function load(kind){
  if(!['inventory','restaurant','store'].includes(kind))throw Error('Unknown recorded example');
  if(!cache.has(kind))cache.set(kind,fetch('/static/data/examples/'+kind+'.json').then(async response=>{
   if(!response.ok)throw Error('The recorded example could not load. Refresh to try again.');
   const payload=await response.json();
   if(payload.recording?.read_only!==true||payload.recording?.paid_model_calls!==0)throw Error('Invalid recorded example');
   return payload;
  }).catch(error=>{cache.delete(kind);throw error;}));
  return cache.get(kind);
 }
 function banner(label,onStart){
  document.getElementById('recorded-example-banner')?.remove();
  const {make,button}=ProductUI,box=make('aside',null,'ui-recording');box.id='recorded-example-banner';box.setAttribute('aria-label','Recorded example');
  const text=make('div');text.append(make('strong','Recorded example'),make('p',label+' · synthetic data · no paid model calls.'));
  let readOnly=false;fetch('/api/runtime').then(r=>r.ok?r.json():null).then(runtime=>{readOnly=runtime?.mode==='replay';}).catch(()=>{});
  const start=button('Start your own run');start.addEventListener('click',async()=>{start.disabled=true;try{if(readOnly){location.href='/engineers/architecture?page=overview';return;}await onStart();}finally{start.disabled=false;}});box.append(text,start);
  document.getElementById('main')?.prepend(box);
  return {remove(){box.remove();},label(value){text.querySelector('p').textContent=value;}};
 }
 function supplyRead(data,path){
  const url=new URL(path,location.origin),parts=url.pathname.split('/').map(decodeURIComponent);
  if(parts[2]!=='supply'||parts[3]!=='runs'||parts[4]!==data.snapshot.run.id)return undefined;
  if(parts.length===5)return structuredClone(data.snapshot);
  if(parts[5]==='agents')return structuredClone(data.agent_details[parts[6]]);
  if(parts[5]==='orders')return structuredClone(data.order_details[parts[6]]);
  if(parts[5]==='evidence')return structuredClone(data);
  if(parts[5]==='replay')return structuredClone(data.replay);
  if(parts[5]==='entities'&&parts[7]==='search'){
   const query=(url.searchParams.get('query')||'').toLocaleLowerCase();
   const rows=data.snapshot.stock.filter(row=>row.owner===parts[6]);
   const results=rows.filter(row=>(String(row.ingredient)+' '+String(row.name||'')).toLocaleLowerCase().includes(query));
   return {results:results.map(row=>({...row,id:row.ingredient,name:row.name||row.ingredient,available_now:row.on_hand-row.reserved})),reviews:[],candidates_count:rows.length,as_of_sim:data.snapshot.run.sim_time};
  }
  throw Error('This detail was not retained in the recording. Start a new run to inspect it.');
 }
 return {load,banner,supplyRead};
})();
