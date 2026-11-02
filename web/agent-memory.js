/* Public examples and limits come from the runtime reference, never live memory. */
(() => {
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  function disclosure(label,content){const d=el("details");d.append(el("summary",label),content);return d;}
  function code(value){const pre=el("pre",typeof value==="string"?value:JSON.stringify(value,null,2),"memory-code");pre.tabIndex=0;pre.setAttribute("aria-label","Scrollable synthetic memory example");return pre;}
  function paragraphs(host,items){items.forEach(text=>host.append(el("p",text)));}
  function flow(items,cls="memory-flow"){
    const list=el("ol",undefined,cls);
    items.forEach(([title,text])=>{const li=el("li");li.append(el("strong",title),el("span",text));list.append(li);});
    return list;
  }
  function select(label,values,change,id){
    const wrap=el("label",label,"memory-select"),choice=el("select");choice.id=id;
    values.forEach(([value,text])=>{const option=el("option",text);option.value=value;choice.append(option);});
    choice.onchange=()=>change(choice.value);wrap.append(choice);return [wrap,choice];
  }
  function mount(host,data){
    host.classList.add("memory-reference");
    if(!data.persistent){
      host.append(el("h4","A fresh context for each complaint"),flow([
        ["Complaint facts","Only the current request enters the session."],
        ["ADK session","Classify the complaint, then discard conversational state."],
        ["Durable receipt","Record the request/result for idempotency, not future recall."]
      ]),el("p",data.applicability),el("p","The shared memory system below is not wired into this classifier.","memory-note"));
      const shared=disclosure("Understand the shared memory system",el("div"));
      shared.lastElementChild.append(el("p",data.format_note));
      paragraphs(shared.lastElementChild,data.evidence);
      shared.lastElementChild.append(flow(data.storage.gcp.nodes));
      paragraphs(shared.lastElementChild,data.storage.gcp.details);
      host.append(shared);return;
    }
    let contract=data.contracts[0],mode="typed",place="local";
    const tabs=el("div",undefined,"memory-tabs");tabs.setAttribute("role","tablist");tabs.setAttribute("aria-label","Memory documentation");
    const content=el("div",undefined,"memory-tab-content");content.id="memory-tab-content";content.setAttribute("role","tabpanel");content.tabIndex=0;
    const views={record:["Record",record],core:["Core view",core],storage:["Local / GCP",storage],rules:["Constraints",rules]};
    let current="record";
    function show(id){
      current=id;
      tabs.querySelectorAll("button").forEach(b=>{const active=b.dataset.view===id;b.setAttribute("aria-selected",String(active));b.tabIndex=active?0:-1;});
      content.setAttribute("aria-labelledby","memory-tab-"+id);content.replaceChildren();views[id][1]();
    }
    Object.entries(views).forEach(([id,[label]])=>{
      const b=el("button",label);b.id="memory-tab-"+id;b.dataset.view=id;b.setAttribute("role","tab");b.setAttribute("aria-controls",content.id);b.onclick=()=>show(id);
      b.onkeydown=e=>{const ids=Object.keys(views),i=ids.indexOf(id);let next;
        if(e.key==="ArrowRight")next=ids[(i+1)%ids.length];if(e.key==="ArrowLeft")next=ids[(i+ids.length-1)%ids.length];
        if(e.key==="Home")next=ids[0];if(e.key==="End")next=ids.at(-1);
        if(next){e.preventDefault();show(next);tabs.querySelector('[data-view="'+next+'"]').focus();}
      };tabs.append(b);
    });
    host.append(tabs,content);show(current);
    function contractPicker(){
      if(data.contracts.length<2)return;
      const [wrap,choice]=select("Observation type",data.contracts.map(c=>[c.kind,c.kind]),value=>{contract=data.contracts.find(c=>c.kind===value);show(current);},"memory-kind");
      choice.value=contract.kind;content.append(wrap);
    }
    function record(){
      content.append(el("h4",data.format),el("p",data.format_note));
      contractPicker();
      const figure=el("figure",undefined,"memory-record");
      figure.append(el("figcaption","One synthetic "+contract.kind+" record"));
      const groups=el("div",undefined,"memory-record-groups"),body=el("div",undefined,"memory-record-fields");body.id="memory-fields";
      const note=el("p",undefined,"memory-note");note.setAttribute("role","status");
      function group(index){
        const field=data.fields[index];body.replaceChildren();
        groups.querySelectorAll("button").forEach((b,i)=>b.setAttribute("aria-pressed",String(i===index)));
        field.keys.forEach(key=>{
          const row=el("div",undefined,"memory-field");if(key==="body")row.classList.add("memory-body-field");
          row.append(el("code",key),el("span",typeof contract.record[key]==="object"?JSON.stringify(contract.record[key],null,2):String(contract.record[key])));
          body.append(row);
        });note.textContent=field.note;
      }
      data.fields.forEach((field,i)=>{
        const b=el("button");b.append(el("strong",field.title),el("span",field.keys.length+" fields"));
        b.setAttribute("aria-controls",body.id);b.onclick=()=>group(i);groups.append(b);
      });
      figure.append(groups,body,note);content.append(figure);group(1);
      content.append(disclosure("Accepted body schema",code(contract.body_schema)),
        disclosure("Complete example record",code(contract.record)));
      const usage=el("div");paragraphs(usage,[data.applicability,"Accepted incoming events: "+contract.topics.join(", ")+"."]);
      content.append(disclosure("When this agent uses it",usage));
    }
    function core(){
      content.append(el("h4","What reaches the agent"),el("p","The same record, presented five ways. Previewing a format does not change a run."));
      contractPicker();
      const [wrap,choice]=select("Memory profile",Object.keys(data.profile_notes).map(k=>[k,k]),value=>{mode=value;update();},"memory-profile");
      choice.value=mode;const note=el("p"),output=el("div");
      content.append(wrap,note,output);
      function update(){note.textContent=data.profile_notes[mode];output.replaceChildren(code(contract.projections[mode]));}
      update();
      content.append(el("h4","How recall enters the core"),flow(data.recall_path));
      const semantic=el("div");semantic.append(el("p",data.semantic.note));
      const facts=el("dl",undefined,"memory-limits");
      [["Embedding model",data.semantic.model],["Vector dimensions",data.semantic.dimensions],["Query cap",data.semantic.query_bytes+" UTF-8 bytes"],["Paid embedding API calls",data.semantic.paid_embedding_calls]].forEach(([k,v])=>{facts.append(el("dt",k),el("dd",String(v)));});
      semantic.append(facts);content.append(disclosure("Inside semantic ranking",semantic),el("p",data.applicability,"memory-note"));
    }
    function storage(){
      const [wrap,choice]=select("Storage path",[["local","Local"],["gcp","Google Cloud"]],value=>{place=value;update();},"memory-storage");
      choice.value=place;content.append(wrap);const diagram=el("div");content.append(diagram);
      function update(){
        const view=data.storage[place];diagram.replaceChildren(el("h4",view.title),el("p",view.status,"memory-note"),flow(view.nodes,"memory-storage-flow"));
        const details=el("div");paragraphs(details,view.details);diagram.append(details);
      }update();
    }
    function rules(){
      content.append(el("h4","Separate limits for recall and storage"),el("p","Defaults for an explicitly selected profile. Frozen run settings can be stricter; these are not live usage meters."));
      const table=el("table",undefined,"memory-bounds"),head=el("thead"),row=el("tr");
      ["Recall limit","Default","Allowed"].forEach(t=>{const th=el("th",t);th.scope="col";row.append(th);});head.append(row);
      const body=el("tbody");
      const labels={max_facts:"Complete facts",max_bytes:"UTF-8 bytes",ttl_seconds:"Lifetime (sim s)"};
      Object.entries(labels).forEach(([key,label])=>{
        const prop=data.profile_schema.properties[key],tr=el("tr"),th=el("th",label);th.scope="row";
        tr.append(th,el("td",String(prop.default)),el("td",prop.minimum+"\u2013"+prop.maximum));body.append(tr);
      });table.append(head,body);content.append(table);
      const limits=el("dl",undefined,"memory-limits");
      [["Live entries / entity",data.capacity.memory_entries],["Live body bytes / entity",data.capacity.memory_bytes],["Tool calls / event",data.capacity.tool_calls_per_event]].forEach(([k,v])=>limits.append(el("dt",k),el("dd",String(v))));
      content.append(limits,el("p",data.manifest_profile?"This manifest selects a profile: "+JSON.stringify(data.manifest_profile):"This role manifest leaves the profile unset. A run may select one; unset preserves legacy recall.","memory-note"));
      content.append(el("h4","Expiry keeps the audit trail"),flow(data.lifecycle));
      data.rules.forEach(([title,text])=>content.append(disclosure(title,el("p",text))));
      const evidence=el("div");paragraphs(evidence,data.evidence);content.append(disclosure("What the tests prove",evidence));
    }
  }
  window.AgentMemory={mount};
})();
