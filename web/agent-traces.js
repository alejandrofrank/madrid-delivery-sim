/* Retained operator evidence. No paid execution controls or application authority. */
(() => {
  const node = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = String(text);
    if (cls) n.className = cls;
    return n;
  };
  const json = value => JSON.stringify(value, null, 2);
  const usd = value => value == null || !Number.isFinite(Number(value)) ? "Unknown" : `$${Number(value).toFixed(6)}`;
  const pretty = value => typeof value === "string" ? value : json(value);
  const time = value => value ? new Date(value).toLocaleTimeString([], {hour12:false}) : "Time unavailable";
  const percentile = (calls, p) => {
    const values = calls.map(c => c.latency_ms).filter(v => typeof v === "number").sort((a,b) => a-b);
    return values.length ? `${(values[Math.ceil(p * values.length)-1]/1000).toFixed(2)} s` : "Unknown";
  };
  function disclosure(parent, label, content) {
    const d = node("details");d.append(node("summary",label),node("pre",pretty(content)));parent.append(d);
  }
  const list = value => Array.isArray(value) ? value : [];
  const label = value => String(value || "").replaceAll("_", " ");
  const percent = value => value !== null && value !== undefined && value !== "" && typeof value !== "boolean" && Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1)}%` : "Unknown";
  const seconds = value => typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(2)} s` : "Unknown";
  const milliseconds = value => typeof value === "number" && Number.isFinite(value) ? seconds(value / 1000) : "Unknown";
  const routes = value => list(value?.route_decisions ?? value?.routing_decisions);
  function evidenceTable(headers, rows, className = "") {
    const wrap = node("div", undefined, `table-wrap ${className}`.trim());
    const table = node("table"), thead = node("thead"), head = node("tr"), body = node("tbody");
    for (const title of headers) { const th = node("th", title); th.scope = "col"; head.append(th); }
    for (const values of rows) {
      const row = node("tr");
      for (const value of values) { const cell = node("td"); cell.append(value instanceof Node ? value : document.createTextNode(String(value ?? "—"))); row.append(cell); }
      body.append(row);
    }
    thead.append(head); table.append(thead, body); wrap.append(table); return wrap;
  }
  function routeTable(decisions) {
    return evidenceTable(["Event", "Selected executor", "Confidence", "Margin", "Reason", "Memory", "Routing latency"], decisions.map(decision => [
      decision.event_id ?? "—", label(decision.executor ?? decision.selected_executor ?? "unknown"),
      percent(decision.confidence), percent(decision.margin), node("span", decision.reason || "No reason recorded", "route-reason"),
      decision.memory_mode ?? "Unknown", milliseconds(decision.latency_ms),
    ]), "route-decisions");
  }
  function checkState(value) {
    if (value === true || value === "passed" || value === "ok" || value?.passed === true) return "pass";
    if (value === false || value === "failed" || value?.passed === false) return "fail";
    return "";
  }
  function checks(parent, values) {
    const box = node("div", undefined, "outcome-checks");
    for (const [name, value] of Object.entries(values || {})) {
      const state = checkState(value), text = state === "pass" ? "passed" : state === "fail" ? "failed" : value == null ? "unknown" : pretty(value);
      const item = node("span", `${label(name)}: ${text}`, `check ${state}`.trim());
      if (value?.message) item.title = value.message;
      box.append(item);
    }
    parent.append(box.childNodes.length ? box : node("p", "No outcome checks recorded."));
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
  function modelCall(parent, call, name) {
    const box = node("details", undefined, "call");
    box.append(node("summary", `Call ${call.step ?? "—"} · ${time(call.started_at)} · ${call.latency_ms ?? "?"} ms · ${usd(call.usage_cost_usd)} · ${call.usage?.prompt_token_count ?? "?"} input tokens`));
    const request = call.request_body;
    if (request) {
      disclosure(box, "System prompt + SOUL", request.config?.system_instruction);
      for (const content of list(request.contents)) chat(box, content, `${content.role || "Message"} · before call ${call.step ?? "—"}`);
      disclosure(box, "Declared tools and generation settings", request.config);
    } else box.append(node("p", "No saved model request body."));
    if (call.response_body) chat(box, call.response_body, `${name} · ${time(call.completed_at)} · model response`);
    else box.append(node("p", "No saved model response body."));
    disclosure(box, "Provider usage / request fingerprint", {state: call.state, usage: call.usage, request_hash: call.request_hash, reserved_usd: call.reserved_usd});
    disclosure(box, "Complete model call receipt", call);
    parent.append(box);
  }
  function selectedMemory(parent, memory, mode) {
    if (mode === "none") parent.append(node("p", "Recall is disabled. Retained audit facts remain inspectable."));
    if (memory === undefined || memory === null) { parent.append(node("p", "No selected-memory snapshot was retained for this event.")); return; }
    if (typeof memory === "string") { parent.append(node("pre", memory || "No relevant prior facts were recalled.")); return; }
    const facts = Array.isArray(memory) ? memory : list(memory.facts);
    if (!facts.length) parent.append(node("p", mode === "none" ? "No facts were supplied to recall." : "No relevant prior facts were recalled for this event."));
    for (const fact of facts) {
      const card = node("div", undefined, "memory");
      card.append(node("strong", `${fact.kind || fact.key || "Fact"} · ${fact.fact_id ?? fact.id ?? "ID unavailable"}`));
      if (fact.body !== undefined) card.append(node("pre", pretty(fact.body)));
      disclosure(card, "Value, provenance, scope, expiry and version", fact); parent.append(card);
    }
    if (!Array.isArray(memory)) disclosure(parent, "Structured memory representation and scope", memory);
  }
  function armBuildingBlocks(parent, arm) {
    const agent = list(arm.configuration?.entities).find(entity => entity.kind === "restaurant")?.agent;
    if (agent) {
      const definition = node("details", undefined, "agent-building-blocks");
      definition.append(node("summary", "Frozen agent building blocks · SOUL, prompt, tools, memory and limits"));
      const body = node("div", undefined, "turn-body");
      body.append(node("h4", "SOUL / decision preferences"), node("pre", agent.soul || "No saved SOUL"));
      body.append(node("h4", "Role prompt"), node("pre", agent.brain?.instructions || "No saved role prompt"));
      disclosure(body, "Declared tools, routing and agent limits", {tools: agent.brain?.tools, routing: agent.brain?.routing || null, memory: agent.memory, limits: agent.limits, brain: agent.brain});
      definition.append(body); parent.append(definition);
    }
    const evidence = arm.evidence || {}, decisions = routes(arm).length ? routes(arm) : routes(evidence);
    const events = new Map(list(evidence.turns).map(turn => [String(turn.event_id), turn]));
    for (const receipt of [...decisions, ...list(evidence.tools), ...list(evidence.calls), ...list(evidence.searches)]) {
      if (receipt.event_id != null && !events.has(String(receipt.event_id))) events.set(String(receipt.event_id), {event_id: receipt.event_id, state: "receipt retained"});
    }
    parent.append(node("h4", `Event decisions and agent building blocks · ${events.size} event(s)`));
    if (!events.size) { parent.append(node("p", "No event building blocks have been retained for this arm yet.", "note")); return; }
    for (const turn of events.values()) {
      const matches = receipt => String(receipt.event_id) === String(turn.event_id);
      const eventRoutes = decisions.filter(matches), calls = list(evidence.calls).filter(matches), tools = list(evidence.tools).filter(matches);
      const plan = turn.result || eventRoutes.find(route => route.decision)?.decision;
      const executor = eventRoutes[0]?.executor || (calls.length ? "gemini" : "unrecorded");
      const savedSummary = plan?.summary || plan?.reason || turn.error_code || eventRoutes[0]?.reason || "No saved decision summary";
      const detail = node("details", undefined, "turn route-turn"), heading = node("summary"), body = node("div", undefined, "turn-body");
      heading.append(node("span", `Event ${turn.event_id}`, "pill"), document.createTextNode(`${label(executor)} · ${label(plan?.action || turn.state)} · ${String(savedSummary).slice(0, 180)}`));
      body.append(node("h4", "Recorded plan"), node("p", savedSummary, "decision-summary"));
      if (plan) {
        body.append(node("p", `${label(plan.action || "Action unavailable")}${plan.supplier ? ` · supplier ${plan.supplier}` : ""}${plan.substitute ? ` · substitute ${plan.substitute}` : ""}`));
        disclosure(body, "Saved action and decision summary", plan);
      }
      if (eventRoutes.length) {
        body.append(node("h4", "Routing decision"), routeTable(eventRoutes));
        for (const route of eventRoutes) {
          if (route.model) { disclosure(body, "Jev request · scoped observations, SOUL and selected memory", route.request_body); disclosure(body, "Jev classifications and usage", route.response_body); }
          else body.append(node("p", "Local protocol rule · no Jev classifier call for this event."));
        }
      }
      body.append(node("h4", `Scoped tools · ${tools.length}`));
      for (const tool of tools) {
        const record = node("div", undefined, "tool"), title = node("div");
        title.append(node("strong", tool.tool || "Tool unavailable"), node("div", `Receipt ${tool.step ?? "—"}`));
        const result = node("div"); disclosure(result, "Observed result", tool.result); record.append(title, result); body.append(record);
      }
      if (!tools.length) body.append(node("p", "No scoped tool receipts recorded for this event."));
      for (const search of list(evidence.searches).filter(matches)) {
        body.append(node("h4", `Ingredient relevance search · ${search.query || "Query unavailable"}`));
        body.append(node("p", `${milliseconds(search.duration_ms)} aggregate search-operation duration; individual Jev provider latency is not retained.`));
        disclosure(body, "Search classifications and budget receipt", search);
      }
      body.append(node("h4", `Selected memory · ${turn.memory_mode || arm.memory_mode || "Unknown"}`));
      selectedMemory(body, turn.memory, turn.memory_mode || arm.memory_mode);
      body.append(node("h4", `Gemini model calls · ${calls.length}`));
      for (const call of calls) modelCall(body, call, arm.soul || "Agent");
      if (!calls.length) body.append(node("p", "No Gemini model call recorded for this event."));
      disclosure(body, "Complete saved event result", turn);
      detail.append(heading, body); parent.append(detail);
    }
  }
  function comparisonDeltas(parent, data) {
    const arms = new Map(list(data.arms).map(arm => [arm.id, arm]));
    if (!list(data.comparisons).length) return;
    const signed = (value, cost = false) => {
      const number = value === null || value === undefined ? NaN : Number(value);
      return Number.isFinite(number) ? `${number < 0 ? "−" : "+"}${cost ? "$" : ""}${Math.abs(number).toFixed(cost ? 6 : 2)}${cost ? "" : " s"}` : "Unknown";
    };
    parent.append(node("h3", "Paired differences"), node("p", "Cascade minus baseline. Differences appear only for pairs with passed outcomes and fully known usage.", "note"));
    parent.append(evidenceTable(["Scenario", "Outcome gate", "Usage cost difference", "Wall-time difference"], list(data.comparisons).map(pair => {
      const pairedArms = [arms.get(pair.baseline), arms.get(pair.cascade)];
      const verified = pair.passed === true && pair.known_usage === true && pairedArms.every(arm => arm?.status === "completed" && arm.cost?.unknown_calls === 0 && Object.values(arm.outcome_checks || {}).every(value => checkState(value) === "pass"));
      return [label(pair.scenario), verified ? "Passed · known usage" : label(pair.status || "Unverified"),
        verified ? signed(pair.observed_cost_delta_usd ?? pair.cost_delta_usd, true) : "Withheld",
        verified ? signed(pair.observed_wall_seconds_delta ?? pair.wall_delta_seconds) : "Withheld"];
    }), "paired-differences"));
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
        const decisions = routes(e).filter(x => x.event_id === t.event_id);
        if (decisions.length) { panel.append(node("h3", "Routing decisions"), routeTable(decisions)); disclosure(panel, "Routing receipts", decisions); }
        panel.append(node("h3",`Selected memory${t.memory_mode ? ` · ${t.memory_mode}` : ""}`));
        if(!list(t.memory).length) panel.append(node("p",t.memory_mode === "none" ? "Recall disabled for this event. Audit facts remain inspectable." : "No relevant prior facts were recalled for this event."));
        for(const fact of list(t.memory)) {const m=node("div",undefined,"memory");m.append(node("strong",`${fact.kind || fact.key || "Fact"} · ${fact.fact_id ?? fact.id}`));disclosure(m,"Value, provenance, expiry and version",fact);panel.append(m);}
        panel.append(node("h3","Model calls"));
        for(const call of e.calls.filter(x=>x.event_id===t.event_id)) modelCall(panel, call, name);
        d.append(summary,panel);section.append(d);
      }
      traces.append(section);
    }
    document.getElementById("comparison").replaceChildren(wrap);
  }
  function renderRouting(data, prefix = "route") {
    const arms = list(data.arms), state = document.getElementById(`${prefix}-state`);
    const summary = document.getElementById(`${prefix}-summary`), comparison = document.getElementById(`${prefix}-comparison`);
    const outcomes = document.getElementById(`${prefix}-outcomes`), traces = document.getElementById(`${prefix}-traces`);
    comparison.replaceChildren(); outcomes.replaceChildren(); traces.replaceChildren();
    const created = data.created_at ? new Date(data.created_at).toLocaleString() : "Date unavailable";
    state.textContent = `${label(data.status || "retained")} · ${created} · ${arms.length} retained arm(s)`;
    summary.hidden = !data.summary;
    summary.textContent = typeof data.summary === "string" ? data.summary : pretty(data.summary);
    if (!arms.length) comparison.append(node("p", "No completed routing arms are retained yet. Refresh after the comparison finishes.", "note"));
    if (arms.length) comparison.append(evidenceTable(
      ["Arm / SOUL", "Memory", "Status / delivered", "Gemini / Jev calls", "Known usage cost", "Median / wall time", "Rules / Jev / Gemini routes"],
      arms.map(arm => {
        const calls = arm.provider_calls || {}, cost = arm.cost || {}, breakdown = arm.route_breakdown || {};
        const unknown = Number(cost.unknown_calls || 0);
        const name = node("div"); name.append(node("strong", arm.label || arm.id || "Unnamed arm"));
        if (arm.soul) name.append(node("small", `${arm.soul} SOUL`, "cell-note"));
        return [name, arm.memory_mode ?? "Unknown", `${label(arm.status || "unknown")} / ${arm.metrics?.delivered ?? "—"}`,
          `${calls.gemini ?? "—"} / ${calls.jev ?? "—"}`,
          `${usd(cost.total_usd)}${unknown ? ` + ${unknown} unknown call(s)` : ""}`,
          `${milliseconds(arm.median_latency_ms)} / ${seconds(arm.wall_seconds)}`,
          `${breakdown.rules ?? "—"} / ${breakdown.jev ?? "—"} / ${breakdown.gemini ?? "—"}`];
      }), "routing-arms"));
    const failed = arms.some(arm => Object.values(arm.outcome_checks || {}).some(value => checkState(value) === "fail"))
      || Object.values(data.outcome_comparison || {}).some(value => checkState(value) === "fail");
    if (failed) outcomes.append(node("p", "One or more outcome checks failed. Cost and timing describe these runs; successful outcomes are not established.", "outcome-warning fail"));
    if (data.outcome_comparison) {
      outcomes.append(node("h3", "Outcome comparison"));
      checks(outcomes, data.outcome_comparison);
      disclosure(outcomes, "Recorded outcome comparison", data.outcome_comparison);
    }
    comparisonDeltas(outcomes, data);
    if (data.budget) disclosure(outcomes, "Frozen comparison admission ceilings and accounted usage", {budget: data.budget, accounting: data.accounting});
    if (prefix === "contract" && data.previous_attempt) {
      let known = 0, attempts = 0, cursor = data;
      while (cursor) {
        known += list(cursor.arms).reduce((sum, arm) => sum + Number(arm.cost?.total_usd || 0), 0);
        attempts += 1; cursor = cursor.previous_attempt;
      }
      outcomes.append(node("p", `${attempts} retained attempts · cumulative known token cost ${usd(known)} · conservative accounting ${usd(data.accounting?.total_accounted_usd)} · shared cap ${usd(data.budget?.total_ceiling_usd)}. Includes stopped probes; invoice reconciliation pending.`, "note"));
    }
    for (const arm of arms) {
      const section = node("section", undefined, "profile route-profile"), header = node("div", undefined, "profile-header");
      header.append(node("h3", `${arm.label || arm.id || "Unnamed arm"}${arm.soul ? ` · ${arm.soul} SOUL` : ""}`));
      if (arm.run) { const link = node("a", "Open city run"); link.href = `/restaurant-lab?run=${encodeURIComponent(arm.run)}`; header.append(link); }
      section.append(header, node("p", `Frozen memory: ${arm.memory_mode ?? "Unknown"} · ${label(arm.status || "unknown")}`));
      checks(section, arm.outcome_checks);
      const cost = arm.cost || {};
      section.append(node("p", `Vertex ${usd(cost.vertex_usd)} · Jev ${usd(cost.jev_usd)} · total ${usd(cost.total_usd)}${cost.unknown_calls ? ` · ${cost.unknown_calls} call(s) with unknown usage` : ""}`, "note"));
      disclosure(section, "Run metrics, provider counts and route breakdown", {metrics: arm.metrics, provider_calls: arm.provider_calls, route_breakdown: arm.route_breakdown, median_latency_ms: arm.median_latency_ms, latency: arm.latency, wall_seconds: arm.wall_seconds, cost: arm.cost});
      const decisions = routes(arm).length ? routes(arm) : routes(arm.evidence);
      const details = node("details", undefined, "route-receipts");
      details.append(node("summary", `${decisions.length} routing decision(s) · confidence, margin and execution reason`));
      details.append(decisions.length ? routeTable(decisions) : node("p", "No routing decisions recorded for this arm. A baseline model loop may have no router receipts.", "note"));
      if (decisions.length) disclosure(details, "Complete routing receipts", decisions);
      section.append(details); armBuildingBlocks(section, arm); traces.append(section);
    }
    disclosure(traces, "Retained routing comparison JSON", data);
    if (data.previous_attempt) disclosure(traces, "Earlier verification attempt · retained failure and accounted cost", data.previous_attempt);
    outcomes.append(node("p", "Costs use retained provider usage and the recorded tariff. Missing usage is unknown. Provider medians use measured Gemini and Jev router calls; older aggregate search timings are shown separately. Baseline and cascade provider mixes may differ. This page makes no model calls.", "note"));
  }
  async function loadModelComparison() {
    try {
      const response = await fetch("/api/supply/model-comparison", {cache:"no-store"});
      if (!response.ok) throw new Error("No live SOUL comparison recorded yet.");
      render(await response.json());
    } catch (error) { document.getElementById("state").textContent = error.message; }
  }
  async function loadRoutingComparison() {
    try {
      const response = await fetch("/api/supply/route-comparison", {cache:"no-store"});
      if (!response.ok) throw new Error(response.status === 404 ? "No retained routing comparison yet." : "Routing evidence is temporarily unavailable.");
      renderRouting(await response.json());
    } catch (error) {
      const retained = document.getElementById("route-comparison").childNodes.length > 0;
      document.getElementById("route-state").textContent = `${error.message}${retained ? " Previously loaded evidence remains below." : " This does not affect the SOUL comparison."}`;
    }
  }
  async function loadContractVerification() {
    try {
      const response = await fetch("/api/supply/contract-verification", {cache:"no-store"});
      if (!response.ok) throw new Error(response.status === 404 ? "No retained contract verification yet." : "Contract evidence is temporarily unavailable.");
      renderRouting(await response.json(), "contract");
    } catch (error) { document.getElementById("contract-state").textContent = error.message; }
  }
  async function load() {
    const refresh = document.getElementById("refresh"); refresh.disabled = true;
    try { await Promise.allSettled([loadModelComparison(), loadRoutingComparison(), loadContractVerification()]); }
    finally { refresh.disabled = false; }
  }
  document.getElementById("refresh").addEventListener("click",load);load();
})();
