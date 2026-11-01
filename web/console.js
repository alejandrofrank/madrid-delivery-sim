/* Small shared primitives; all charts use observed runtime values. */
window.Ops = (() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const paths = {
    bike:'<circle cx="6" cy="16" r="4"/><circle cx="18" cy="16" r="4"/><path d="m6 16 5-9 7 9h-7L7 7H4m7 0h4m-2-3h3"/>',
    moto:'<circle cx="5" cy="17" r="3"/><circle cx="19" cy="17" r="3"/><path d="m5 17 4-7h6l4 7M8 14h8M13 6h4l2 7M5 10h4"/>',
    van:'<path d="M2 7h12v10H2zM14 10h5l3 4v3h-8"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/>',
    courier:'<path d="M3 7 12 3l9 4v11l-9 4-9-4zM3 7l9 4 9-4M12 11v11M7 5l10 4"/>',
    dispatcher:'<circle cx="12" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="19" r="2"/><path d="M12 7v5M5 17v-5h14v5"/>',
    store:'<path d="M3 9h18l-2-5H5zM4 9v12h16V9M9 21v-7h6v7"/>',
    household:'<path d="m3 11 9-8 9 8M5 9v12h14V9M10 21v-7h4v7"/>',
    judge:'<path d="M12 3v18M5 6h14M5 6l-3 8h6zM19 6l-3 8h6zM7 21h10"/>'
  };
  function icon(role, className="role-symbol") {return '<svg class="'+className+'" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'+(paths[role]||paths[{restaurant:'store',market:'store',inventory:'store',fulfillment:'courier'}[role]]||paths.courier)+'</svg>';}
  function sparkline(values,label="Observed history") {
    const samples=values.filter(Number.isFinite);if(samples.length<2)return "";
    const max=Math.max(...samples),min=Math.min(...samples),range=max-min||1;
    const points=samples.map((v,i)=>(i/(samples.length-1)*68+2).toFixed(1)+","+(20-(v-min)/range*16).toFixed(1)).join(" ");
    return '<svg viewBox="0 0 72 24" role="img" aria-label="'+escape(label)+'"><polyline points="'+points+'" fill="none" stroke="var(--ui-accent)" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>';
  }
  function liveHTML(element,html) {
    const active=document.activeElement,focused=element.contains(active)?active?.getAttribute("data-courier"):null;
    const scroll=element.scrollTop;element.innerHTML=html;element.scrollTop=scroll;
    if(focused) [...element.querySelectorAll("[data-courier]")].find(x=>x.dataset.courier===focused)?.focus({preventScroll:true});
  }
  return {escape,icon,sparkline,liveHTML};
})();
/* Shared live list for agent runtimes. Counters come from persisted events/orders. */
Ops.createRoster = function(mount,onSelect,options={}){
 const esc=Ops.escape;
 mount.innerHTML='<div class="roster-heading"><h2>Agents <span class="roster-count"></span></h2><span class="roster-state"></span></div><div class="roster-filters"><label>Role<select class="roster-role"><option value="">All roles</option></select></label><label>Status<select class="roster-status"><option value="">All statuses</option></select></label><label>Find agent<input class="roster-search" type="search" placeholder="Name or ID"></label></div><div class="roster-labels"><span>Agent / current task</span><span>Status</span><span>Total / rate</span></div><div class="roster-list"></div><p class="roster-history"></p>';
 const role=mount.querySelector(".roster-role"),status=mount.querySelector(".roster-status"),search=mount.querySelector(".roster-search"),list=mount.querySelector(".roster-list");
 let rows=[],selected=null,lastKey=null,histories=new Map(),previous=new Map();
 function filters(select,values,title){const old=select.value;select.replaceChildren(new Option(title,""),...values.map(x=>new Option(x.replaceAll("_"," "),x)));select.value=values.includes(old)?old:"";}
 function render(){
   const query=search.value.toLowerCase(),shown=rows.filter(r=>(!role.value||r.role===role.value)&&(!status.value||r.status===status.value)&&(!query||(r.name+" "+r.id+" "+(r.identity||"")+" "+(r.roleLabel||"")+" "+(r.task||"")).toLowerCase().includes(query)));
   const focused=list.contains(document.activeElement)?document.activeElement.closest("[data-roster-id]")?.dataset.rosterId:null,scroll=list.scrollTop;
   list.innerHTML=shown.map(r=>'<button class="roster-row '+(selected===r.id?"is-selected":"")+'" data-roster-id="'+esc(r.id)+'" aria-pressed="'+(selected===r.id)+'"><span class="roster-identity">'+Ops.icon(r.role)+'<span><strong>'+esc(r.name)+'</strong>'+(r.identity?'<small class="roster-id">'+esc(r.identity)+'</small>':'')+'<small>'+esc([r.roleLabel,r.task||r.role.replaceAll("_"," ")].filter(Boolean).join(" · "))+'</small></span></span><span class="roster-pill '+(r.active?"is-active":"")+'">'+esc(r.status.replaceAll("_"," "))+'</span><span class="roster-count-value">'+(Number.isFinite(r.count)?r.count:"—")+Ops.sparkline(histories.get(r.id)||[],(options.rateLabel||"Recorded activity per simulated minute"))+'</span></button>').join("")||'<p class="roster-empty">'+(rows.length?"No agents match your filters.":"No live agents yet. Start a session from Simulation.")+'</p>';
   list.scrollTop=scroll;if(focused)[...list.querySelectorAll("[data-roster-id]")].find(x=>x.dataset.rosterId===focused)?.focus({preventScroll:true});
 }
 [role,status,search].forEach(el=>el.addEventListener("input",render));
 list.addEventListener("click",e=>{const row=e.target.closest("[data-roster-id]");if(row){selected=row.dataset.rosterId;render();onSelect(selected);}});
 return {update(next,selection,key,seconds,runStatus){
   rows=next;selected=selection;
   if(key&&key!==lastKey){lastKey=key;for(const row of rows){let values=histories.get(row.id)||[];if(Number.isFinite(row.count)){const last=previous.get(row.id);if(last&&Number.isFinite(seconds)&&seconds>last.time)values.push(Math.max(0,row.count-last.count)*60/(seconds-last.time));previous.set(row.id,{count:row.count,time:seconds});if(values.length>30)values.shift();histories.set(row.id,values);}}}
   filters(role,[...new Set(rows.map(r=>r.role))].sort(),"All roles");filters(status,[...new Set(rows.map(r=>r.status))].sort(),"All statuses");
   mount.querySelector(".roster-count").textContent=rows.length;
   mount.querySelector(".roster-state").textContent=rows.filter(r=>r.active).length+" working";
   const sampled=[...histories.values()].some(values=>values.length>=2);
   const history=sampled?"Curves observed since opening.":["complete","failed"].includes(runStatus)?"History unavailable for this completed run.":"Collecting history.";
   mount.querySelector(".roster-history").textContent=(options.scope||"Totals: retained decisions / delivered orders.")+" "+history+" Curves: activity / simulated min.";
   render();
 },reset(){histories=new Map();previous=new Map();lastKey=null;}};
};
