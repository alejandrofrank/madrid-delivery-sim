/* The server owns every agent fact. This file supplies geometry and interaction only. */
(() => {
  const NS = "http://www.w3.org/2000/svg";
  const order = ["household", "restaurant", "market", "inventory", "fulfillment", "dispatcher", "courier", "customer_service", "judge"];
  const shapes = {
    mission: '<path d="M169 100h122l13 40v54H156v-54z"/><path d="M177 111h106l9 31H166z" class="machine-glass"/>',
    persona: '<rect x="185" y="151" width="90" height="31" rx="5"/><circle cx="207" cy="165" r="4"/><circle cx="253" cy="165" r="4"/><path d="M222 171h16"/>',
    tools: '<path d="M156 204h-25v58h-21m194-58h25v58h21"/><path d="M100 250v24h20m240-24v24h-20"/><circle cx="131" cy="224" r="8"/><circle cx="329" cy="224" r="8"/>',
    memory: '<rect x="152" y="211" width="34" height="89" rx="14"/><path d="M159 230h20m-20 15h20m-20 15h20m-20 15h20"/>',
    policy: '<path d="M143 194h174v119H143zM149 200l14 14m148-14-14 14m-148 93 14-14m148 14-14-14" class="machine-cage"/>',
    limits: '<rect x="276" y="211" width="27" height="64" rx="3"/><path d="M283 220h13m-13 11h13m-13 11h13m-13 11h13m-13 11h13"/>',
    model: '<rect x="198" y="214" width="65" height="61" rx="5"/><circle cx="230" cy="244" r="18"/><circle cx="230" cy="244" r="7"/><path d="M230 222v7m0 30v7m-22-22h7m30 0h7"/>',
    protocols: '<path d="M249 99V68h38V49"/><circle cx="287" cy="43" r="6"/><path d="M273 32a19 19 0 0 1 28 0M267 24a28 28 0 0 1 40 0"/>',
    events: '<path d="M156 124h-26v-18h-19m193 18h26v-18h19"/><path d="m113 99 10 7-10 7m231-14 10 7-10 7"/>',
    evals: '<rect x="209" y="283" width="53" height="23" rx="3"/><path d="m219 294 5 5 8-10m8 3h14m-14 7h14"/>',
    environment: '<rect x="137" y="326" width="186" height="38" rx="19"/><circle cx="159" cy="345" r="11"/><circle cx="206" cy="345" r="11"/><circle cx="254" cy="345" r="11"/><circle cx="301" cy="345" r="11"/><path d="M180 313v13m100-13v13"/>',
  };
  const labels = {
    mission: [42, 145, "Role", "M100 141h48"],
    persona: [355, 173, "Persona", "M278 167h69"],
    tools: [40, 243, "Tools", "M78 239h37"],
    memory: [40, 289, "Memory", "M103 285h42"],
    policy: [350, 312, "Guardrails", "M320 304h23"],
    limits: [355, 218, "Budget", "M309 214h38"],
    model: [355, 264, "Model", "M266 260h81"],
    protocols: [338, 59, "A2A / MCP", "M299 48h32"],
    events: [40, 86, "Events", "M101 82h29v17"],
    evals: [40, 318, "Evals", "M85 314h35l10-12h72"],
    environment: [195, 393, "Environment", "M230 367v11"],
  };
  function node(tag, text, cls) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }
  function svgNode(tag, attrs = {}) {
    const el = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, value));
    return el;
  }
  function machine(agent, select, small = false) {
    const svg = svgNode("svg", {viewBox: small ? "90 20 280 355" : "0 0 460 420", class: "agent-machine"});
    if (small) svg.setAttribute("aria-hidden", "true");
    else {
      svg.setAttribute("role", "group");
      svg.setAttribute("aria-label", `${agent.name} anatomy: choose a machine part`);
    }
    const body = svgNode("path", {d: "M151 194h158v120H151z", class: "machine-body"});
    svg.append(body);
    // The safety cage is drawn first so it never covers the individual controls.
    ["policy", ...Object.keys(shapes).filter(key => key !== "policy")].forEach(key => {
      const g = svgNode("g", {class: "machine-part", "data-part": key});
      g.innerHTML = shapes[key]; // Fixed, authored SVG only; no server text enters markup.
      if (!small) {
        const panel = agent.panels.find(p => p.id === key);
        g.setAttribute("role", "button");
        g.setAttribute("tabindex", "0");
        g.setAttribute("aria-label", `${panel.title} — ${panel.part}`);
        g.setAttribute("aria-controls", "anatomy-inspector");
        const [x, y, text, line] = labels[key];
        g.append(svgNode("path", {d: line, class: "part-leader"}));
        const label = svgNode("text", {x, y, class: "part-label"});
        label.textContent = text;
        g.append(label);
        g.addEventListener("click", () => select(key));
        g.addEventListener("keydown", event => {
          if (["Enter", " "].includes(event.key)) { event.preventDefault(); select(key); }
          if (["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(event.key)) {
            event.preventDefault();
            const parts = [...svg.querySelectorAll('[role="button"]')];
            const direction = ["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1;
            parts[(parts.indexOf(g) + direction + parts.length) % parts.length].focus();
          }
        });
      }
      svg.append(g);
    });
    return svg;
  }
  function sourceLink(path) {
    const a = node("a", path);
    const url = new URL(location.href);
    url.searchParams.set("source", path);
    a.href = url.pathname + url.search;
    a.dataset.source = path;
    return a;
  }
  let generation = 0;
  async function mount(host) {
    const version = ++generation;
    host.replaceChildren(node("p", "Loading agent manifests and recorded evidence…", "anatomy-status"));
    try {
      const response = await fetch("/api/agent-anatomy", {cache: "no-store", credentials: "same-origin"});
      if (!response.ok) throw new Error("Unavailable");
      const data = await response.json();
      if (version !== generation || host.hidden) return;
      render(host, data);
    } catch {
      if (version !== generation) return;
      const error = node("p", "Agent definitions could not be loaded. Retry after the local service is ready.");
      error.setAttribute("role", "alert");
      const retry = node("button", "Retry agent definitions");
      retry.onclick = () => mount(host);
      host.replaceChildren(error, retry);
    }
  }
  function render(host, data) {
    host.replaceChildren();
    host.dataset.fingerprint = data.input_fingerprint;
    const agents = [...data.agents].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
    const params = new URLSearchParams(location.search);
    let selected = agents.find(a => a.id === params.get("agent")) || agents.find(a => a.id === "restaurant") || agents[0];
    let part = params.get("part") || "mission";
    const heading = node("div", undefined, "anatomy-team-heading");
    heading.append(node("p", "Choose an agent, then inspect its parts. These are role templates; a shift creates many individual agents."));
    host.append(heading);
    const toolbar = node("div", undefined, "anatomy-team-toolbar");
    toolbar.append(node("span", "Solid lines: queued events · Dashed lines: A2A calls · Illustrated topology, not live traffic"));
    const replay = node("button", "Replay handoffs");
    toolbar.append(replay);
    host.append(toolbar);
    const scroll = node("div", undefined, "anatomy-team-scroll");
    scroll.setAttribute("role", "region");
    scroll.setAttribute("aria-label", "Agent team diagram; scroll horizontally on small screens");
    scroll.tabIndex = 0;
    const team = node("div", undefined, "anatomy-team");
    const scheduler = node("p", "Simulation scheduler · A2A JSON-RPC", "anatomy-scheduler");
    team.append(scheduler);
    const graph = svgNode("svg", {viewBox: "0 0 1170 285", preserveAspectRatio: "none", class: "anatomy-connections", "aria-hidden": "true"});
    const x = id => agents.findIndex(a => a.id === id) * 130 + 65;
    data.edges.forEach((edge, index) => {
      const start = x(edge.source), end = x(edge.target);
      const d = edge.kind === "a2a" ? `M585 27H${end}V61` :
        `M${start} 201V${220 + (index % 5) * 11}H${end}V201`;
      const path = svgNode("path", {d, class: `team-wire ${edge.kind}`, "data-from": edge.source, "data-to": edge.target});
      graph.append(path);
    });
    team.append(graph);
    const roster = node("div", undefined, "anatomy-team-roster");
    agents.forEach(agent => {
      const button = node("button", undefined, "team-agent");
      button.dataset.agent = agent.id;
      button.setAttribute("aria-controls", "anatomy-detail");
      button.append(machine(agent, null, true), node("strong", agent.name));
      button.append(node("small", agent.panels.find(p => p.id === "protocols").card ? "A2A + events" : "Queued events"));
      button.onclick = () => choose(agent.id, "mission");
      roster.append(button);
    });
    team.append(roster); scroll.append(team); host.append(scroll);
    const connections = node("details", undefined, "anatomy-edge-list");
    connections.append(node("summary", "Read the handoffs as text"));
    const edgeText = node("ul"); connections.append(edgeText); host.append(connections);
    replay.onclick = () => {
      graph.classList.remove("playing");
      requestAnimationFrame(() => { void graph.getBoundingClientRect(); graph.classList.add("playing"); });
    };
    const detail = node("section", undefined, "anatomy-detail"); detail.id = "anatomy-detail";
    const identity = node("div", undefined, "anatomy-identity");
    const name = node("h2"); const mission = node("p");
    identity.append(name, mission); detail.append(identity);
    const workbench = node("div", undefined, "anatomy-workbench");
    const drawing = node("div", undefined, "anatomy-drawing");
    const picker = node("label", "Inspect a part", "anatomy-part-picker");
    const select = node("select"); select.id = "anatomy-part-select";
    picker.append(select); drawing.append(picker);
    const illustration = node("div", undefined, "anatomy-illustration"); drawing.append(illustration);
    drawing.append(node("p", "Select a labelled part. Keyboard: Tab to a part, arrow keys to move, Enter to inspect.", "anatomy-hint"));
    const inspector = node("section", undefined, "anatomy-inspector");
    inspector.id = "anatomy-inspector"; inspector.setAttribute("aria-labelledby", "anatomy-panel-title");
    const status = node("span", "", "sr-only"); status.setAttribute("role", "status");
    workbench.append(drawing, inspector); detail.append(workbench, status); host.append(detail);
    select.onchange = () => choose(selected.id, select.value);
    let environment = "all";
    const footer = node("p", undefined, "anatomy-provenance");
    footer.append(document.createTextNode("Generated from repository files · definition fingerprint "), node("code", data.input_fingerprint.slice(0, 12)), document.createTextNode(" · "), sourceLink("docs/evidence/heldout-release.json"));
    host.append(footer);
    function choose(id, key, updateURL = true) {
      selected = agents.find(a => a.id === id) || selected;
      part = selected.panels.some(p => p.id === key) ? key : "mission";
      name.textContent = selected.name;
      mission.textContent = selected.mission;
      roster.querySelectorAll("button").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.agent === selected.id)));
      graph.querySelectorAll("path").forEach(path => path.classList.toggle("connected", [path.dataset.from, path.dataset.to].includes(selected.id)));
      edgeText.replaceChildren(...data.edges.filter(e => e.source === selected.id || e.target === selected.id).map(e => node("li", `${e.source} → ${e.target} · ${e.kind === "a2a" ? "A2A" : "queue"}: ${e.topics.join(", ")}`)));
      if (illustration.dataset.agent !== selected.id) {
        illustration.replaceChildren(machine(selected, value => choose(selected.id, value)));
        illustration.dataset.agent = selected.id;
      }
      illustration.querySelectorAll('[role="button"]').forEach(g => g.setAttribute("aria-pressed", String(g.dataset.part === part)));
      select.replaceChildren(...selected.panels.map(p => { const option = node("option", `${p.title} · ${p.part}`); option.value = p.id; return option; }));
      select.value = part;
      const basePanel = selected.panels.find(p => p.id === part);
      const variant = basePanel.environments?.[environment];
      const panel = variant ? {...basePanel,...variant} : basePanel;
      const title = node("h3", panel.title); title.id = "anatomy-panel-title";
      inspector.replaceChildren(title, node("p", panel.summary, "anatomy-summary"));
      if(basePanel.environments){
        const label=node("label","Environment","anatomy-part-picker");
        const environmentSelect=node("select");environmentSelect.id="anatomy-environment";
        const all=node("option","All environments");all.value="all";environmentSelect.append(all);
        Object.entries(basePanel.environments).forEach(([id,view])=>{const option=node("option",view.label);option.value=id;environmentSelect.append(option);});
        environmentSelect.value=environment;
        environmentSelect.onchange=()=>{environment=environmentSelect.value;choose(selected.id,part);};
        label.append(environmentSelect);inspector.insertBefore(label,title);
        const wheels=illustration.querySelector('[data-part="environment"]');
        wheels?.setAttribute("data-environment",environment);
      }
      const numbers = node("dl", undefined, "anatomy-numbers");
      Object.entries(panel.numbers).forEach(([label, value]) => {
        const row = node("div"); row.append(node("dt", label.replaceAll("_", " ")), node("dd", String(value))); numbers.append(row);
      }); inspector.append(numbers);
      if (panel.results?.length) {
        const tableWrap = node("div", undefined, "anatomy-results");
        const table = node("table");
        const caption = node("caption", "Recorded held-out results · scripted offline ADK");
        const head = node("thead"); const tr = node("tr");
        ["Arm", "Cases × k", "pass^k / 95% CI", "Cost / success", "p95"].forEach(text => {const th = node("th", text); th.scope = "col"; tr.append(th);}); head.append(tr);
        const body = node("tbody");
        panel.results.forEach(result => {
          const row = node("tr");
          [result.arm, `${result.cases} × ${result.repeat}`, `${result.pass_power_k.toFixed(3)} / [${result.pass_power_k_ci95.join(", ")}]`, result.cost_per_success_usd === null ? "Unmeasured" : `$${result.cost_per_success_usd.toFixed(4)}`, `${result.p95_latency_ms.toFixed(1)} ms`].forEach(text => row.append(node("td", text)));
          body.append(row);
        }); table.append(caption, head, body); tableWrap.append(table); inspector.append(tableWrap);
      }
      const details = node("div", undefined, "anatomy-explanation");
      panel.details.forEach(text => details.append(node("p", text))); inspector.append(details);
      if (panel.card) {
        const disclosure = node("details", undefined, "anatomy-card");
        disclosure.append(node("summary", "Inspect the generated Agent Card"), node("pre", JSON.stringify(panel.card, null, 2))); inspector.append(disclosure);
      }
      const links = node("nav", undefined, "anatomy-sources"); links.setAttribute("aria-label", "Evidence for this part");
      links.append(node("strong", "Source of truth"));
      panel.sources.forEach(path => links.append(sourceLink(path)));
      const chapter = node("a", "Read the docs chapter →"); chapter.href = `/architecture?page=${panel.chapter}`;
      links.append(chapter); inspector.append(links);
      status.textContent = `${selected.name}: ${panel.title}`;
      if (updateURL) {
        const url = new URL(location.href); url.searchParams.set("agent", selected.id); url.searchParams.set("part", part);
        history.replaceState({}, "", url.pathname + url.search);
      }
    }
    choose(selected.id, part, false);
  }
  window.AgentAnatomy = {mount};
})();
