/* Add trace navigation without changing the retained agent evidence renderer. */
(() => {
  "use strict";
  const section = document.createElement("section");
  section.setAttribute("aria-labelledby", "telemetry-title");
  const title = document.createElement("h2");
  title.id = "telemetry-title";
  title.textContent = "Queue and agent traces";
  const status = document.createElement("p");
  status.setAttribute("role", "status");
  const results = document.createElement("div");
  section.append(title, status, results);
  document.querySelector("main > header").after(section);
  async function load() {
    try {
      const response = await fetch("/api/telemetry/traces", {cache: "no-store"});
      if (!response.ok) throw new Error("Trace index is temporarily unavailable.");
      const data = await response.json();
      status.textContent = data.mode === "disabled"
        ? "Tracing is off. Start the optional tracing compose profile for local Jaeger."
        : `${data.mode === "gcp" ? "Cloud Trace" : "Local Jaeger"} · Up to 30 recent traces. Sampling and collector retention affect availability.`;
      const table = document.createElement("table");
      const head = document.createElement("tr");
      for (const label of ["Correlation", "Run", "Events", "Trace ID"]) {
        const th = document.createElement("th"); th.textContent = label; head.append(th);
      }
      table.append(head);
      for (const trace of data.traces) {
        const row = document.createElement("tr");
        for (const value of [trace.correlation_id, trace.run_id, trace.events]) {
          const td = document.createElement("td"); td.textContent = String(value); row.append(td);
        }
        const td = document.createElement("td");
        if (trace.url) {
          const link = document.createElement("a"); link.textContent = trace.trace_id;
          link.href = trace.url; link.target = "_blank"; link.rel = "noopener noreferrer";
          td.append(link);
        } else { td.textContent = trace.trace_id; }
        row.append(td); table.append(row);
      }
      results.replaceChildren(table);
    } catch (error) { status.textContent = error.message; }
  }
  document.getElementById("refresh").addEventListener("click", load);
  load();
})();
