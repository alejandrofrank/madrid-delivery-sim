"use strict";
const $ = (id) => document.getElementById(id);
let evidence,
  city,
  selectedCategory = "all",
  selectedCapability = null;
let historicalBanner = null;
let selectedRun = new URLSearchParams(location.search).get("test_run");
const expandedScenarios = new Set();
const names = {
  passed: "Passed",
  failed: "Failed",
  skipped: "Skipped",
  xfailed: "Expected failure",
  xpassed: "Unexpected pass",
  not_run: "Not run",
  not_measured: "Not measured",
  incomplete: "Partial evidence",
  running: "Running",
  current: "Matches running source",
  outdated: "Source changed",
  stale: "Older than 24h",
  unavailable: "Unavailable",
};
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function badge(status, text) {
  return el("span", text || names[status] || status, `badge ${status}`);
}
function when(value) {
  return value
    ? new Intl.DateTimeFormat("en-GB", {
        timeZone: "Europe/Madrid",
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(value)) + " Madrid"
    : "Not recorded";
}
function seconds(value) {
  return value < 1 ? `${Math.round(value * 1000)} ms` : `${value.toFixed(1)} s`;
}
function title(value) {
  return value.replace(/^test_/, "").replaceAll("_", " ");
}
function message(id, text) {
  $(id).textContent = text;
  $(id).hidden = !text;
}
async function get(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error("Local evidence could not be loaded.");
  return response.json();
}
function tab(name) {
  for (const id of ["tests", "evals", "city", "history"]) {
    $(id + "-panel").hidden = id !== name;
    $(id + "-tab").setAttribute("aria-selected", String(id === name));
    $(id + "-tab").tabIndex = id === name ? 0 : -1;
  }
}
for (const id of ["tests", "evals", "city", "history"])
  $(id + "-tab").addEventListener("click", () => tab(id));
document.querySelector(".tabs").addEventListener("keydown", (event) => {
  const ids = ["tests", "evals", "city", "history"];
  const index = ids.findIndex(
    (id) => id + "-tab" === document.activeElement.id,
  );
  if (index < 0) return;
  let next;
  if (event.key === "ArrowRight") next = (index + 1) % ids.length;
  if (event.key === "ArrowLeft") next = (index + 3) % ids.length;
  if (event.key === "Home") next = 0;
  if (event.key === "End") next = 3;
  if (next !== undefined) {
    event.preventDefault();
    tab(ids[next]);
    $(ids[next] + "-tab").focus();
  }
});
async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    message("notice", "Copied. Paste it into your Bash terminal.");
  } catch {
    message("notice", text);
  }
}
$("copy-command").addEventListener("click", () => copy("make health"));
$("copy-scenario-command").addEventListener("click", () =>
  copy("make eval-agents"),
);
for (const id of ["scenario-role-filter", "scenario-status-filter"])
  $(id).addEventListener("change", renderScenarios);
function metric(label, value, note, state) {
  const node = el("article", undefined, "metric");
  node.append(el("span", label), el("strong", value, state), el("p", note));
  return node;
}
function effectiveStatus(status, freshness) {
  return freshness === "current" ? status : freshness || "unavailable";
}
function capabilityStatus(cap) {
  const run = evidence.test_run;
  if (!run) return "not_measured";
  if (run.freshness !== "current") return run.freshness;
  if (cap.status === "failed") return "failed";
  return run.scope === "full" && run.state === "completed"
    ? cap.status
    : "incomplete";
}
function renderSummary() {
  const run = evidence.test_run,
    metrics = $("metrics");
  metrics.replaceChildren();
  if (run) {
    const count = run.counts;
    metrics.append(
      metric(
        "Tests passed",
        `${count.passed} / ${count.total}`,
        `${evidence.categories.length} categories · ${run.scope} run`,
        effectiveStatus(run.status, run.freshness),
      ),
    );
    const provenance = $("provenance");
    provenance.replaceChildren(
      badge(run.status),
      badge(run.freshness),
      el("span", when(run.completed_at || run.started_at)),
      el(
        "span",
        `Source ${run.source_fingerprint.slice(0, 10)}${run.source_revision ? " · base commit " + run.source_revision.slice(0, 7) : ""}`,
      ),
    );
    if (run.freshness !== "current")
      message(
        "notice",
        "This receipt does not prove the current source is healthy. Run make health to refresh it.",
      );
    else if (run.scope !== "full" || run.state !== "completed")
      message(
        "notice",
        "This is partial or running evidence. Skipped, filtered and unfinished checks are not counted as passing.",
      );
    else message("notice", "");
    $("footer-state").textContent =
      `${seconds(run.duration_seconds)} · source fingerprint covers code, tests, fixtures and configuration`;
  } else {
    metrics.append(
      metric(
        "Test evidence",
        "Not recorded",
        "Run make health to collect every case",
        "not_measured",
      ),
    );
    $("provenance").replaceChildren(
      badge("not_measured"),
      el("span", evidence.message || "No test receipt found."),
    );
  }
  const caps = evidence.capabilities.filter((cap) => cap.status === "passed");
  metrics.append(
    metric(
      "Capability regressions",
      run ? `${caps.length} / ${evidence.capabilities.length}` : "Not measured",
      "Selected checks · overlapping categories",
      run
        ? effectiveStatus(
            run.scope === "full" &&
              run.state === "completed" &&
              caps.length === evidence.capabilities.length &&
              caps.length > 0
              ? "passed"
              : "incomplete",
            run.freshness,
          )
        : "not_measured",
    ),
  );
  const scenarios = evidence.scenarios;
  metrics.append(
    metric(
      "Role scenario cases",
      scenarios?.available
        ? `${scenarios.counts.passed} / ${scenarios.counts.total}`
        : "Not measured",
      scenarios?.available
        ? `${scenarios.counts.failed} failed · ${scenarios.counts.not_measured} unmeasured${scenarios.freshness !== "current" ? " · historical" : ""}`
        : "Run make eval-agents · local deterministic rules",
      scenarios?.available
        ? effectiveStatus(scenarios.status, scenarios.freshness)
        : "not_measured",
    ),
  );
  const services = city?.services || [],
    ok = services.filter((s) => s.status === "passed").length;
  metrics.append(
    metric(
      "Local services",
      services.length ? `${ok} / ${services.length}` : "Unknown",
      city
        ? `Last probe · ${when(city.checked_at)}`
        : "Postgres and Redis · read-only probes",
      services.length
        ? ok === services.length
          ? "passed"
          : "failed"
        : "not_measured",
    ),
  );
}
function renderCategories() {
  const root = $("categories");
  root.replaceChildren();
  const groups = [
    {
      id: "all",
      name: "All tests",
      description: "Every collected case, including parameters",
      counts: evidence.test_run?.counts || { passed: 0, total: 0, failed: 0 },
      file_count: new Set(evidence.tests.map((c) => c.file)).size,
    },
    ...evidence.categories,
  ];
  for (const group of groups) {
    const button = el("button", undefined, "category");
    button.setAttribute("aria-pressed", String(selectedCategory === group.id));
    const head = el("div", undefined, "category-head");
    head.append(
      el("span", group.name),
      el(
        "span",
        `${group.counts.passed}/${group.counts.total}`,
        group.counts.failed ? "failed" : "",
      ),
    );
    const bar = el("div", undefined, "bar"),
      pass = el("i"),
      fail = el("i", undefined, "fail");
    pass.style.width = `${group.counts.total ? (100 * group.counts.passed) / group.counts.total : 0}%`;
    fail.style.width = `${group.counts.total ? (100 * group.counts.failed) / group.counts.total : 0}%`;
    bar.append(pass, fail);
    button.append(
      head,
      el("small", `${group.file_count} files · ${group.description}`),
      bar,
    );
    button.addEventListener("click", () => {
      selectedCategory = group.id;
      selectedCapability = null;
      renderCategories();
      renderTests();
    });
    root.append(button);
  }
}
function renderTests() {
  const root = $("test-list");
  const openFiles = new Set(
    [...root.querySelectorAll(".file-group[open]")].map(
      (node) => node.dataset.file,
    ),
  );
  const openCases = new Set(
    [...root.querySelectorAll(".case[open]")].map(
      (node) => node.dataset.caseId,
    ),
  );
  root.replaceChildren();
  const query = $("search").value.toLowerCase().trim(),
    status = $("status-filter").value,
    kind = $("kind-filter").value;
  const active = evidence.capabilities.find((c) => c.id === selectedCapability),
    allowed = active ? new Set(active.test_ids) : null;
  const tests = evidence.tests.filter(
    (c) =>
      (selectedCategory === "all" || c.category === selectedCategory) &&
      (!allowed || allowed.has(c.id)) &&
      (!query || `${c.id} ${c.description}`.toLowerCase().includes(query)) &&
      (status === "all" ||
        c.status === status ||
        (status === "skipped" && ["xfailed", "xpassed"].includes(c.status))) &&
      (kind === "all" ||
        c.markers.includes("integration") === (kind === "integration")),
  );
  const files = new Map();
  for (const test of tests) {
    if (!files.has(test.file)) files.set(test.file, []);
    files.get(test.file).push(test);
  }
  $("result-count").textContent =
    `Showing ${tests.length} of ${evidence.tests.length} cases · ${files.size} files. Open a file, then a check to inspect its case ID and result.`;
  $("selection-note").hidden = !active;
  if (active) {
    $("selection-note").replaceChildren(
      el("span", `Capability: ${active.name}`),
    );
    const clear = el("button", "Clear");
    clear.addEventListener("click", () => {
      selectedCapability = null;
      renderTests();
    });
    $("selection-note").append(clear);
  }
  if (!tests.length) {
    root.append(
      el(
        "p",
        evidence.available
          ? "No checks match these filters."
          : "No case-level receipt yet. Run make health; a summary count is not treated as individual test evidence.",
        "empty",
      ),
    );
    return;
  }
  for (const [file, cases] of files) {
    const group = el("details", undefined, "file-group"),
      summary = el("summary"),
      heading = el("div", undefined, "file-heading");
    group.dataset.file = file;
    group.open = openFiles.has(file);
    const passed = cases.filter((c) => c.status === "passed").length;
    heading.append(
      el("strong", title(file.split("/").pop().replace(".py", ""))),
      el("small", file),
    );
    summary.append(
      heading,
      el(
        "span",
        `${passed} / ${cases.length}`,
        `file-count ${cases.some((c) => c.status === "failed") ? "failed" : passed === cases.length ? "passed" : "incomplete"}`,
      ),
    );
    group.append(summary);
    for (const test of cases) {
      const item = el("details", undefined, "case"),
        line = el("summary");
      item.dataset.caseId = test.id;
      item.open = openCases.has(test.id);
      line.append(
        badge(test.status),
        el("span", title(test.name), "case-title"),
        el("span", seconds(test.duration_seconds), "case-duration"),
      );
      const body = el("div", undefined, "case-body");
      body.append(
        el("p", test.description),
        el(
          "p",
          `${test.file}:${test.line} · ${test.markers.includes("integration") ? "Postgres integration" : "Other / unit check"}${test.failure_phase ? " · failed during " + test.failure_phase : ""}`,
          "case-source",
        ),
        el("code", test.id),
      );
      const button = el("button", "Copy test ID");
      button.addEventListener("click", () => copy(test.id));
      body.append(button);
      if (test.markers.length)
        body.append(
          el("p", `Markers: ${test.markers.join(", ")}`, "case-source"),
        );
      item.append(line, body);
      group.append(item);
    }
    root.append(group);
  }
}
for (const id of ["search", "status-filter", "kind-filter"])
  $(id).addEventListener(id === "search" ? "input" : "change", () =>
    renderTests(),
  );
function scenarioScore(score, historical) {
  if (score === null || score === undefined) return "Not measured";
  return `${Number(score.toFixed(1))}%${historical ? " · historical" : ""}`;
}
function criterionValue(value) {
  return value === null || value === undefined ? "Not measured" : String(value);
}
function renderScenarios() {
  const report = evidence.scenarios,
    provenance = $("scenario-provenance"),
    roles = $("scenario-roles"),
    cases = $("scenario-cases");
  for (const detail of cases.querySelectorAll("details[data-scenario-id]")) {
    if (detail.open) expandedScenarios.add(detail.dataset.scenarioId);
    else expandedScenarios.delete(detail.dataset.scenarioId);
  }
  provenance.replaceChildren();
  roles.replaceChildren();
  cases.replaceChildren();
  $("scenario-note").textContent = report?.note || "";
  if (!report) {
    provenance.append(badge("not_measured"));
    cases.append(
      el("p", "No role scenario receipt. Run make eval-agents.", "empty"),
    );
    $("scenario-count").textContent = "Role scenarios have not been measured.";
    return;
  }
  const historical = report.available && report.freshness !== "current",
    state = report.available
      ? effectiveStatus(report.status, report.freshness)
      : "not_measured";
  provenance.append(
    badge(state),
    el("strong", scenarioScore(report.score, historical)),
    el(
      "span",
      report.available ? when(report.created_at) : "No local scenario receipt",
    ),
  );
  if (report.available) {
    provenance.append(
      el("span", `${report.version} · seed ${report.seed} · ${report.mode}`),
    );
    if (report.reproduction) {
      const repeat = report.reproduction;
      const comparison = badge(
        effectiveStatus(
          repeat.repetitions > 1
            ? repeat.matched
              ? "passed"
              : "failed"
            : "not_measured",
          report.freshness,
        ),
        repeat.repetitions > 1
          ? `${repeat.repetitions} runs ${repeat.matched ? "matched" : "differ"}`
          : "1 run recorded · repeat not measured",
      );
      if (repeat.hashes?.length) comparison.title = repeat.hashes.join(" · ");
      provenance.append(comparison);
    }
    for (const [label, value] of [
      ["Source", report.source_fingerprint],
      ["Fixtures", report.fixture_hash],
      ["Outcomes", report.outcome_hash],
    ]) {
      const fingerprint = el(
        "span",
        `${label} ${value?.slice(0, 12) || "not recorded"}`,
        "scenario-fingerprint",
      );
      if (value) fingerprint.title = value;
      provenance.append(fingerprint);
    }
    if (historical)
      provenance.append(
        el(
          "p",
          `Historical scores: ${names[report.freshness] || "source cannot be verified"}. Run make eval-agents for current evidence.`,
          "scenario-history",
        ),
      );
  }
  for (const role of report.roles || []) {
    const card = el("article", undefined, "scenario-role"),
      head = el("div", undefined, "capability-head"),
      status = report.available
        ? effectiveStatus(role.status, report.freshness)
        : "not_measured";
    head.append(el("h3", role.name), badge(status));
    card.append(
      head,
      el("strong", scenarioScore(role.score, historical), status),
      el(
        "p",
        `${role.counts.passed} / ${role.counts.total} cases passed · ${role.counts.failed} failed · ${role.counts.not_measured} unmeasured`,
      ),
      el(
        "p",
        `${role.checks_passed} / ${role.checks_total} criteria passed`,
        "subtle",
      ),
    );
    const inspect = el("button", "Inspect cases");
    inspect.addEventListener("click", () => {
      $("scenario-role-filter").value = role.id;
      $("scenario-status-filter").value = "all";
      renderScenarios();
    });
    card.append(inspect);
    roles.append(card);
  }
  const roleFilter = $("scenario-role-filter").value,
    statusFilter = $("scenario-status-filter").value,
    allCases = report.cases || [],
    matchingRole = allCases.filter(
      (item) => roleFilter === "all" || item.role === roleFilter,
    ),
    visible = matchingRole.filter(
      (item) => statusFilter === "all" || item.status === statusFilter,
    ),
    failed = matchingRole.filter((item) => item.status === "failed").length;
  $("scenario-count").textContent =
    `Showing ${visible.length} of ${matchingRole.length} cases · ${failed} failed${historical ? " in this historical receipt" : ""}. Open a case to inspect expected and actual criteria.`;
  if (!visible.length) {
    cases.append(
      el(
        "p",
        statusFilter === "failed"
          ? matchingRole.some((item) => item.status === "not_measured")
            ? "No failed cases recorded. Unmeasured cases have no passing result; select All cases to inspect them."
            : "No failed cases in this receipt. Select All cases to inspect the passing evidence."
          : "No scenario cases recorded. Run make eval-agents.",
        "empty",
      ),
    );
  }
  for (const item of visible) {
    const detail = el("details", undefined, "scenario-case"),
      summary = el("summary"),
      heading = el("div", undefined, "scenario-case-heading"),
      status = report.available
        ? effectiveStatus(item.status, report.freshness)
        : "not_measured";
    detail.dataset.scenarioId = item.id;
    detail.open = expandedScenarios.has(item.id);
    detail.addEventListener("toggle", () => {
      if (!detail.isConnected) return;
      if (detail.open) expandedScenarios.add(item.id);
      else expandedScenarios.delete(item.id);
    });
    heading.append(
      el("strong", item.name),
      el("small", `${item.role} · ${item.id}`),
    );
    summary.append(
      badge(
        status,
        historical
          ? `${names[item.status] || item.status} · historical`
          : undefined,
      ),
      heading,
      el("span", scenarioScore(item.score, historical), "scenario-case-score"),
    );
    const body = el("div", undefined, "scenario-case-body");
    body.append(
      el("p", item.description),
      el(
        "p",
        "Criteria retain failed or missing observations across all repeats. Each criterion and source event identifies its repetition.",
        "subtle",
      ),
      el(
        "p",
        item.error ? `Error code: ${item.error}` : "Error code: none recorded",
        item.error ? "failed" : "subtle",
      ),
      table(
        ["Criterion", "Expected", "Actual", "Repeat", "Result"],
        (item.checks || []).map((check) => [
          check.label,
          criterionValue(check.expected),
          criterionValue(check.actual),
          check.repetition ?? "—",
          badge(
            report.available
              ? effectiveStatus(check.status, report.freshness)
              : "not_measured",
            historical
              ? `${names[check.status] || check.status} · historical`
              : undefined,
          ),
        ]),
      ),
      el("h3", "Source evidence"),
    );
    if (item.evidence?.length) {
      body.append(
        table(
          [
            "Repeat",
            "Event",
            "Topic",
            "Trace",
            "State",
            "Attempts",
            "Simulation time",
          ],
          item.evidence.map((event) => [
            event.repetition ?? 1,
            event.sequence,
            event.topic,
            event.trace,
            event.state,
            event.attempts,
            event.sim_time,
          ]),
        ),
      );
    } else body.append(el("p", "No source events recorded.", "subtle"));
    detail.append(summary, body);
    cases.append(detail);
  }
}
function renderEvals() {
  renderScenarios();
  const root = $("capabilities");
  root.replaceChildren();
  for (const cap of evidence.capabilities) {
    const card = el("article", undefined, "capability"),
      head = el("div", undefined, "capability-head");
    head.append(el("h3", cap.name), badge(capabilityStatus(cap)));
    card.append(
      head,
      el("strong", `${cap.counts.passed} / ${cap.counts.total}`),
      el("p", cap.description),
    );
    if (cap.missing_selectors.length)
      card.append(
        el(
          "p",
          `${cap.missing_selectors.length} configured scenario(s) missing from this receipt.`,
          "incomplete",
        ),
      );
    card.append(el("p", cap.limits, "limit"));
    const inspect = el("button", "Inspect checks");
    inspect.addEventListener("click", () => {
      selectedCapability = cap.id;
      selectedCategory = "all";
      $("search").value = "";
      $("status-filter").value = "all";
      $("kind-filter").value = "all";
      renderCategories();
      renderTests();
      tab("tests");
    });
    card.append(inspect);
    root.append(card);
  }
  const judge = evidence.judge;
  $("judge-status").replaceChildren(
    badge(
      judge.available
        ? effectiveStatus(
            judge.counts.passed === judge.counts.total ? "passed" : "failed",
            judge.freshness,
          )
        : "not_measured",
    ),
  );
  const target = $("judge");
  target.replaceChildren();
  if (!judge.available) {
    target.append(
      el("p", "No offline evaluation receipt. Run make health.", "empty"),
    );
    return;
  }
  target.append(
    el(
      "p",
      `${judge.fixture_version} · ${when(judge.created_at)} · ${judge.note}`,
      "subtle",
    ),
  );
  target.append(
    table(
      ["Case", "Expected", "Actual", "Result", "Local latency"],
      judge.rows.map((r) => [
        title(r.case_id.replaceAll("-", "_")),
        r.expected_decision,
        r.actual_decision || "No decision",
        badge(r.passed ? "passed" : "failed"),
        `${r.latency_ms} ms`,
      ]),
    ),
  );
}
function table(headers, rows) {
  const wrap = el("div", undefined, "table-scroll"),
    table = el("table"),
    head = el("tr");
  headers.forEach((h) => head.append(el("th", h)));
  const thead = el("thead");
  thead.append(head);
  table.append(thead);
  const body = el("tbody");
  for (const values of rows) {
    const row = el("tr");
    for (const value of values) {
      const cell = el("td");
      cell.append(
        value instanceof Node ? value : document.createTextNode(String(value)),
      );
      row.append(cell);
    }
    body.append(row);
  }
  table.append(body);
  wrap.append(table);
  return wrap;
}
function renderHistory() {
  const root = $("history");
  root.replaceChildren();
  if (evidence.invalid_history_reports)
    root.append(
      el(
        "p",
        `${evidence.invalid_history_reports} invalid receipt(s) could not be read. Their results are unknown.`,
        "notice",
      ),
    );
  if (!evidence.history.length) {
    root.append(el("p", "No finished local runs recorded.", "empty"));
    return;
  }
  root.append(
    table(
      [
        "Finished · Madrid",
        "Result",
        "Passed / total",
        "Scope",
        "Source",
        "Inspect",
      ],
      evidence.history.map((run) => {
        const button = el("button", "View run");
        button.addEventListener("click", () => {
          selectedRun = run.id;
          const url = new URL(location.href);
          url.searchParams.set("test_run", run.id);
          history.replaceState(null, "", url);
          loadEvidence();
          tab("tests");
        });
        const state = el("div");
        state.append(
          badge(run.status),
          document.createTextNode(" "),
          badge(run.freshness),
        );
        return [
          when(run.completed_at),
          state,
          `${run.counts.passed} / ${run.counts.total}`,
          run.scope,
          run.source_fingerprint.slice(0, 10),
          button,
        ];
      }),
    ),
  );
}
function renderChecks() {
  const root = $("checks");
  root.replaceChildren();
  const checks = evidence.static_checks;
  if (!checks.available) {
    root.append(el("p", "No code-check receipt. Run make health.", "empty"));
    return;
  }
  root.append(
    el(
      "p",
      `${when(checks.created_at)} · ${names[checks.freshness]}`,
      "subtle",
    ),
  );
  for (const check of checks.checks) {
    const row = el("div", undefined, "check");
    row.append(
      el("span", `${check.label} · ${seconds(check.duration_seconds)}`),
      badge(effectiveStatus(check.status, checks.freshness)),
    );
    root.append(row);
  }
}
function renderCity() {
  if (!city) return;
  $("runtime-time").textContent = when(city.checked_at);
  const services = $("services");
  services.replaceChildren();
  for (const service of city.services) {
    const card = el("article", undefined, "service"),
      head = el("div");
    head.append(el("h3", service.name), badge(service.status));
    card.append(
      head,
      el(
        "p",
        service.latency_ms === null
          ? "Probe could not connect. Connection details are withheld."
          : `Probe latency ${service.latency_ms} ms`,
      ),
    );
    services.append(card);
  }
  const provider = el("article", undefined, "service");
  provider.append(
    el("h3", "Default model provider"),
    el(
      "p",
      city.provider_mode === "disabled"
        ? "Disabled. City policies stay local; per-run reservations are shown below."
        : "Configured. This page does not call providers or inspect cloud resources.",
    ),
  );
  services.append(provider);
  const select = $("city-run"),
    previous = select.value;
  select.replaceChildren();
  for (const run of city.runs) {
    const option = el(
      "option",
      `${run.kind} · ${run.id.slice(0, 8)} · ${run.status}`,
    );
    option.value = run.id;
    select.append(option);
  }
  if (city.selected) select.value = city.selected.id;
  else if (previous) select.value = previous;
  const root = $("diagnostics");
  root.replaceChildren();
  if (city.diagnostics_unavailable) {
    root.append(
      el(
        "p",
        "Database probe passed, but simulation diagnostics are unavailable.",
        "empty",
      ),
    );
    return;
  }
  if (!city.selected) {
    root.append(
      el(
        "p",
        "No simulation selected or database diagnostics unavailable.",
        "empty",
      ),
    );
    return;
  }
  const selected = city.selected,
    queue = selected.queue,
    grid = el("div", undefined, "diagnostics");
  for (const [label, value, state] of [
    ["Waiting", queue.ready, "neutral"],
    ["Leased", queue.leased, "neutral"],
    ["Expired leases", queue.expired, queue.expired ? "incomplete" : "passed"],
    ["Dead letters", queue.dead, queue.dead ? "failed" : "passed"],
    ["Retries", queue.retries, "neutral"],
  ]) {
    const box = el("div", undefined, "diagnostic");
    box.append(el("strong", String(value), state), el("span", label));
    grid.append(box);
  }
  root.append(
    grid,
    el(
      "p",
      `${queue.total} queued events · ${selected.model_reservations} model/search reservations. Failed simulations and intentionally injected incidents remain in history.`,
      "diagnostic-note",
    ),
  );
  if (selected.budget) {
    const b = selected.budget;
    root.append(
      el(
        "p",
        `Run budget: ${b.events_reserved}/${b.events_limit} event attempts · ${b.tools_reserved}/${b.tools_limit} reserved tool slots.`,
        "diagnostic-note",
      ),
    );
  }
  const run = city.runs.find((r) => r.id === selected.id);
  if (run) {
    const link = el("a", "Open simulation evidence");
    link.href = run.kind === "delivery"
      ? `/api/lab/delivery-runs/${encodeURIComponent(run.id)}`
      : `/${run.kind === "restaurant" ? "restaurant-lab" : ""}?run=${encodeURIComponent(run.id)}`;
    root.append(link);
  }
}
async function loadEvidence() {
  try {
    try {
      evidence = await get("/api/health/evidence" + (selectedRun ? "?test_run=" + encodeURIComponent(selectedRun) : ""));
      if(!evidence.available&&!selectedRun)throw Error("No retained local report");
      historicalBanner?.remove();historicalBanner=null;
    }catch(error){
      if(selectedRun)throw error;
      evidence=await get("/static/data/health-evidence.json");
      if(!historicalBanner){
        historicalBanner=ProductExamples.banner("Historical test results from "+when(evidence.recording.completed_at)+". These do not certify this running build",async()=>{
          location.href="/engineers/architecture?page=validation";
        });
        document.querySelector("#recorded-example-banner button").textContent="How to run the checks";
      }
    }
    renderSummary();
    renderCategories();
    renderTests();
    renderEvals();
    renderHistory();
    renderChecks();
    message("error", "");
  } catch {
    if (evidence) {
      if (evidence.test_run) evidence.test_run.freshness = "unavailable";
      evidence.static_checks.freshness = "unavailable";
      evidence.judge.freshness = "unavailable";
      if (evidence.scenarios) evidence.scenarios.freshness = "unavailable";
      renderSummary();
      renderEvals();
      renderChecks();
    }
    $("provenance").replaceChildren(
      badge("unavailable"),
      el("span", "Refresh failed. Retained catalogue is historical evidence."),
    );
    message(
      "error",
      "Test evidence is unavailable. Check the local service and refresh; no passing result is assumed.",
    );
  }
}
async function loadCity(run) {
  try {
    city = await get(
      "/api/health/runtime" + (run ? "?run=" + encodeURIComponent(run) : ""),
    );
    renderCity();
    if (evidence) renderSummary();
  } catch {
    $("services").replaceChildren(
      el("p", "This view has no live worker connection. The recorded shift is ready to explore.", "empty"),
    );
    $("diagnostics").replaceChildren(
      el("p", "Live diagnostics appear when you connect an authorized workspace.", "empty"),
    );
    const watch=el("a","Watch the recorded shift");watch.href="/watch";$("services").append(watch);
    $("runtime-time").textContent = "No live connection";
    city = null;
    if (evidence) renderSummary();
  }
}
$("city-run").addEventListener("change", () => loadCity($("city-run").value));
$("latest").addEventListener("click", () => {
  selectedRun = null;
  const url = new URL(location.href);
  url.searchParams.delete("test_run");
  history.replaceState(null, "", url);
  loadEvidence();
  tab("tests");
});
$("refresh").addEventListener("click", async () => {
  $("refresh").disabled = true;
  await Promise.allSettled([loadEvidence(), loadCity($("city-run").value)]);
  $("refresh").disabled = false;
});
Promise.allSettled([loadEvidence(), loadCity()]);
setInterval(() => {
  if (!document.hidden)
    Promise.allSettled([loadEvidence(), loadCity($("city-run").value)]);
}, 30000);
