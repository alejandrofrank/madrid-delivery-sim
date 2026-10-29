/* Retained operator evidence. No paid execution controls or application authority. */
(() => {
  const node = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = String(text);
    if (cls) n.className = cls;
    return n;
  };
  const json = value => JSON.stringify(value, null, 2);
  const usd = value => value == null ? "Unknown" : `$${Number(value).toFixed(6)}`;
  const pretty = value => typeof value === "string" ? value : json(value);
  const time = value => value ? new Date(value).toLocaleTimeString([], {hour12:false}) : "Time unavailable";
  const percentile = (calls, p) => {
    const values = calls.map(c => c.latency_ms).filter(v => typeof v === "number").sort((a,b) => a-b);
    return values.length ? `${(values[Math.ceil(p * values.length)-1]/1000).toFixed(2)} s` : "Unknown";
  };
  function disclosure(parent, label, content) {
    const d = node("details");d.append(node("summary",label),node("pre",pretty(content)));parent.append(d);
  }
  function chat(parent, content, label) {
    if (!content) return;
    const box = node("div", undefined, "chat");
    box.append(node("div",label,"chat-label"));
    for (const part of content.parts || []) {
      if (part.text) box.append(node("pre",part.text));
      if (part.function_call) box.append(node("pre",`${part.function_call.name}(${json(part.function_call.args)})`));
      if (part.function_response) box.append(node("pre",`${part.function_response.name} → ${json(part.function_response.response)}`));
    }
    parent.append(box);
  }
  function render(data) {
    document.getElementById("state").textContent = `${data.profile.model} · ${data.profile.location} · ${new Date(data.created_at).toLocaleString()} · Vertex admission ${usd(data.vertex_admission_limit_usd)} + Jev ${usd(data.jev_maximum_usd_at_tariff)} · previous Vertex usage ${usd(data.prior_vertex_accounted_usd || 0)}`;
    const wrap = node("div",undefined,"table-wrap"), table = node("table"), head = node("tr"), body=node("tbody");
    for(const h of ["Agent / SOUL","Supplier","Delivered","Gemini calls","Latency p50 / p95","Vertex usage cost","Jev calls / cost"]) head.append(node("th",h));
    const thead=node("thead");thead.append(head);table.append(thead,body);wrap.append(table);
    const traces=document.getElementById("traces");traces.replaceChildren();
    for(const p of data.profiles) {
      const e=p.evidence || {calls:[],tools:[],turns:[],jev_calls:[],searches:[],cost:{}};
      const name=p.soul === "speed" ? "Elena" : "Mateo", row=node("tr");
      for(const value of [`${name} · ${p.soul}`,p.supplier || "Pending",p.metrics?.delivered ?? "—",e.calls.length,`${percentile(e.calls,.5)} / ${percentile(e.calls,.95)}`,`${usd(e.cost.known_vertex_usd)}${e.cost.unknown_vertex_calls ? ` + ${e.cost.unknown_vertex_calls} unknown` : ""}`,`${e.jev_calls.length} / ${usd(e.cost.jev_known_usd)}${e.cost.unknown_jev_calls ? " + unknown" : ""}`]) row.append(node("td",value));
      body.append(row);
      const section=node("section",undefined,"profile"), header=node("div",undefined,"profile-header"), title=node("h2",`${name} · ${p.soul} SOUL`), link=node("a","Open city run");
      link.href=`/restaurant-lab?run=${encodeURIComponent(p.run)}`;header.append(title,link);section.append(header);
      section.append(node("p",`${p.status} · ${p.wall_seconds ?? "—"} s wall time · choice ${p.soul_choice_matches ? "matches SOUL" : "not verified"} · replay ${p.replay_matches ? "matches" : "not verified"} · Jev ${p.jev_verified ? "verified" : "not verified"} · reserved ${usd(e.cost.vertex_reserved_usd)}`,p.status==="completed" ? "pass" : "fail"));
      for(const t of e.turns) {
        const d=node("details",undefined,"turn"), summary=node("summary"), panel=node("div",undefined,"turn-body");
        summary.append(node("span",`Event ${t.event_id}`,"pill"),document.createTextNode(`${t.result?.action || t.state} · ${t.result?.summary || t.error_code || "No saved decision"}`));
        panel.append(node("h3","Scoped tools"));
        for(const tool of e.tools.filter(x=>x.event_id===t.event_id)) {
          const r=node("div",undefined,"tool"), left=node("div");left.append(node("strong",tool.tool),node("div",time(tool.created_at)));
          const right=node("div");disclosure(right,"Observed result",tool.result);r.append(left,right);panel.append(r);
        }
        for(const search of e.searches.filter(x=>x.event_id===t.event_id)) {
          panel.append(node("h3",`Jev relevance · ${search.query} · ${Number(search.duration_ms).toFixed(0)} ms`));
          disclosure(panel,"Classification results and budget receipt",search);
        }
        panel.append(node("h3","Selected memory"));
        if(!t.memory.length) panel.append(node("p","No relevant prior facts were recalled for this event."));
        for(const fact of t.memory) {const m=node("div",undefined,"memory");m.append(node("strong",`${fact.kind || fact.key || "Fact"} · ${fact.fact_id ?? fact.id}`));disclosure(m,"Value, provenance, expiry and version",fact);panel.append(m);}
        panel.append(node("h3","Model calls"));
        for(const call of e.calls.filter(x=>x.event_id===t.event_id)) {
          const c=node("details",undefined,"call");c.append(node("summary",`Call ${call.step} · ${time(call.started_at)} · ${call.latency_ms ?? "?"} ms · ${usd(call.usage_cost_usd)} · ${call.usage?.prompt_token_count ?? "?"} input tokens`));
          const request=call.request_body;
          if(request) {disclosure(c,"System prompt + SOUL",request.config.system_instruction);for(const content of request.contents) chat(c,content,`${content.role} · before call ${call.step}`);disclosure(c,"Declared tools and generation settings",request.config);}
          chat(c,call.response_body,`${name} · ${time(call.completed_at)} · model response`);
          disclosure(c,"Provider usage / request fingerprint",{usage:call.usage,request_hash:call.request_hash,reserved_usd:call.reserved_usd});panel.append(c);
        }
        d.append(summary,panel);section.append(d);
      }
      traces.append(section);
    }
    document.getElementById("comparison").replaceChildren(wrap);
  }
  async function load() {try {const response=await fetch("/api/supply/model-comparison",{cache:"no-store"});if(!response.ok) throw new Error("No live comparison recorded yet.");render(await response.json());}catch(error){document.getElementById("state").textContent=error.message;}}
  document.getElementById("refresh").addEventListener("click",load);load();
})();
