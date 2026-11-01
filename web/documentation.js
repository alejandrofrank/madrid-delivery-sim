/* Read-only documentation reader. All content and diagram assets are local. */
"use strict";

const $ = (selector) => document.querySelector(selector);
const reader = $("#chapter-body");
let catalogue;
let currentPage;
let renderVersion = 0;
let diagramManifest;
let headingObserver;
let toastTimer;
let sourceRequest = 0;
let diagramScale = 100;
let activeDiagram;

const components = {
  city: {
    name: "City & operator",
    state: "IMPLEMENTED · LOCAL",
    purpose:
      "A reproducible business environment, with editable demand, stores, recipes, traffic and incidents. The operator is trusted and can inspect broader evidence than any agent.",
    inputs: "Frozen run configuration + seed + scheduled household demand.",
    outputs:
      "Addressed events, authoritative world updates and inspection views.",
    boundary:
      "Display names are fictional; they do not establish permissions. UI inspection is not an agent tool.",
    sources: ["src/delivery/supply.py", "src/delivery/running_city.py"],
    page: "restaurant-supply",
  },
  agents: {
    name: "Scoped role workers",
    state: "IMPLEMENTED · LOCAL",
    purpose:
      "One reusable LocalAgent object binds a frozen role definition to an authenticated database scope. Deterministic policies work alongside Google ADK restaurant and customer-service adapters, with scripted offline models and separately enabled paid inference.",
    inputs:
      "An addressed event, fenced lease, approved tools and relevant recall.",
    outputs:
      "Validated business actions, memory revisions, a decision receipt and queued handoffs.",
    boundary:
      "Prompts and SOUL do not grant authority. PostgreSQL and fixed tool implementations enforce scope.",
    sources: ["src/delivery/agent_runtime.py", "src/delivery/agent_specs.py"],
    page: "agent-implementation",
  },
  postgres: {
    name: "Postgres: facts & execution",
    state: "IMPLEMENTED · LOCAL",
    purpose:
      "Domain facts, durable queue, typed memory, budgets and audit share one transactional boundary. Workers do not message one another directly. Redis is not the authoritative agent transport.",
    inputs: "Authenticated, leased and budgeted tool operations.",
    outputs:
      "Atomic effects + outgoing events + ACK; provenance and revision history.",
    boundary:
      "Inference request, dispatch marker and result are committed in short transactions. Provider I/O holds no database connection; uncertain dispatch outcomes fail closed.",
    sources: ["src/delivery/queue.py", "sql/migrations/015_typed_memory.sql"],
    page: "memory",
  },
  gateway: {
    name: "Cloud Run recovery judge",
    state: "OPTIONAL · GCP",
    purpose:
      "A stateless, IAM-authenticated decision service in a dedicated Terraform project. A separate caller identity invokes it; its runtime identity has a prediction-only custom role.",
    inputs:
      "Sanitized numeric recovery facts + packaged synthetic meal snapshot.",
    outputs: "A schema-validated approve/deny verdict and usage metadata.",
    boundary:
      "No city database credentials, customer names, raw agent memory or business action tools. This page does not check whether the service is running.",
    sources: ["infra/gcp-ai/main.tf", "infra/gcp-ai/gateway.py"],
    page: "gcp-components",
  },
  model: {
    name: "Google publisher model",
    state: "OPTIONAL · PAID INFERENCE",
    purpose:
      "Vertex REST performs the bounded judgement task. Model choice is versioned and must pass task-specific evaluations; selecting a cloud product does not establish model quality.",
    inputs:
      "Fixed gateway instructions, synthetic reference data and allowed facts.",
    outputs:
      "A short structured verdict; local rules retain the final feasibility gate.",
    boundary:
      "A six-call/token allowance is not a monetary ceiling. Current local role evals exercise rules, not live LLM quality.",
    sources: ["src/delivery/cloud_ai.py", "config/agents/judge-gcp/role.json"],
    page: "enterprise-gcp",
  },
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function pageURL(id, hash = "") {
  return `/architecture?page=${encodeURIComponent(id)}${hash}`;
}

function sourceURL(path, line) {
  const url = new URL(location.href);
  url.searchParams.set("source", path);
  if (line) url.searchParams.set("line", line);
  else url.searchParams.delete("line");
  return url.pathname + url.search + url.hash;
}

function sourceLink(path, label = path) {
  const link = element("a", label, "source-link");
  link.href = sourceURL(path);
  link.dataset.source = path;
  return link;
}

function toast(text) {
  $("#toast").textContent = text;
  $("#toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($("#toast").hidden = true), 3000);
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied to clipboard");
  } catch {
    toast("Clipboard is unavailable. Select and copy the text directly.");
  }
}

async function getJSON(url) {
  const response = await fetch(url, {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok)
    throw new Error(`Reference unavailable (${response.status}).`);
  return response.json();
}

function buildNavigation() {
  const nav = $("#topics");
  let group;
  catalogue.pages.forEach((page, index) => {
    if (page.group !== group) {
      group = page.group;
      nav.append(element("p", group, "nav-group"));
    }
    const link = element("a", undefined, "topic-link");
    link.href = pageURL(page.id);
    link.dataset.page = page.id;
    link.append(
      element("span", String(index).padStart(2, "0")),
      document.createTextNode(page.title),
    );
    nav.append(link);
  });
}

function selectComponent(key) {
  const component = components[key];
  if (!component) return;
  document.querySelectorAll("[data-component]").forEach((button) => {
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.component === key),
    );
  });
  const inspector = $("#component-inspector");
  inspector.replaceChildren(
    element("h3", component.name),
    element("span", component.state, "component-state"),
    element("p", component.purpose),
  );
  const details = element("dl");
  [
    ["Receives", component.inputs],
    ["Produces", component.outputs],
    ["Trust boundary", component.boundary],
  ].forEach(([label, value]) => {
    details.append(element("dt", label), element("dd", value));
  });
  inspector.append(details);
  component.sources.forEach((path) => inspector.append(sourceLink(path)));
  const chapter = element("a", "Read the full contract →", "read-chapter");
  chapter.href = pageURL(component.page);
  inspector.append(chapter);
}

function slug(text) {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^\p{L}\p{N}\s_-]/gu, "")
    .replace(/\s+/g, "-");
}

function rewriteLinks(page) {
  reader.querySelectorAll("a").forEach((link) => {
    const href = link.getAttribute("href") || "";
    if (href.startsWith("#")) {
      link.href = pageURL(page.id, href);
      return;
    }
    // Resolve repository-relative links against the source Markdown's directory.
    const url = new URL(href, `https://reference.invalid/${page.file}`);
    if (url.origin === "https://reference.invalid" && !href.startsWith("/")) {
      const path = decodeURIComponent(url.pathname.slice(1));
      const target = catalogue.pages.find((entry) => entry.file === path);
      if (target) link.href = pageURL(target.id, url.hash);
      else if (catalogue.sources.includes(path)) {
        link.href = sourceURL(path, url.hash.match(/^#L?(\d+)/)?.[1]);
        link.dataset.source = path;
        if (url.hash) link.dataset.line = url.hash.replace(/^#L?/, "");
        link.classList.add("source-link");
      } else {
        // A directory or non-catalogued supporting artifact remains a manual
        // private-repository link; it is never turned into arbitrary file access.
        link.href = `https://github.com/alejandrofrank/madrid-delivery-sim/blob/main/${path}${url.hash}`;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
    } else if (url.protocol === "https:" || url.protocol === "http:") {
      if (url.hostname === "localhost" && url.port === "8010")
        link.href = url.pathname + url.search + url.hash;
      else if (
        url.origin !== location.origin &&
        url.origin !== "https://reference.invalid"
      ) {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
    } else if (!href.startsWith("/")) {
      link.removeAttribute("href");
    }
  });
}

function buildHeadings() {
  headingObserver?.disconnect();
  const toc = $("#table-of-contents");
  toc.replaceChildren();
  const seen = new Map();
  const headings = Array.from(reader.querySelectorAll("h2,h3"));
  headings.forEach((heading) => {
    const base = slug(heading.textContent);
    const count = seen.get(base) || 0;
    seen.set(base, count + 1);
    heading.id = base + (count ? `-${count}` : "");
    const anchor = element("a", "#", "heading-link");
    anchor.href = pageURL(currentPage.id, `#${heading.id}`);
    anchor.setAttribute("aria-label", `Link to ${heading.textContent}`);
    heading.append(anchor);
    if (heading.tagName === "H2") {
      const link = element("a", heading.textContent.replace(/#$/, ""));
      link.href = pageURL(currentPage.id, `#${heading.id}`);
      link.dataset.heading = heading.id;
      toc.append(link);
    }
  });
  if (currentPage.id === "overview") {
    const link = element("a", "Component explorer");
    link.href = pageURL("overview", "#system-explorer");
    toc.prepend(link);
  }
  headingObserver = new IntersectionObserver(
    (entries) => {
      const visible = entries.find((entry) => entry.isIntersecting);
      if (!visible) return;
      toc
        .querySelectorAll("a")
        .forEach((link) =>
          link.classList.toggle(
            "active",
            link.dataset.heading === visible.target.id,
          ),
        );
    },
    { rootMargin: "-100px 0px -60% 0px" },
  );
  headings
    .filter((heading) => heading.tagName === "H2")
    .forEach((heading) => headingObserver.observe(heading));
}

function enhanceBlocks() {
  reader.querySelectorAll("table").forEach((table) => {
    const wrap = element("div", undefined, "table-wrap");
    wrap.tabIndex = 0;
    wrap.setAttribute("role", "region");
    wrap.setAttribute("aria-label", "Scrollable reference table");
    table.replaceWith(wrap);
    wrap.append(table);
  });
  reader.querySelectorAll("pre").forEach((pre) => {
    const code = pre.querySelector("code");
    if (!code || code.classList.contains("language-mermaid")) return;
    const wrap = element("div", undefined, "code-block");
    const heading = element("div", undefined, "code-heading");
    const language = code.className.replace("language-", "") || "reference";
    const button = element("button", "Copy");
    button.setAttribute("aria-label", `Copy ${language} code`);
    button.addEventListener("click", () => copy(code.textContent));
    heading.append(element("span", language.toUpperCase()), button);
    pre.replaceWith(wrap);
    wrap.append(heading, pre);
  });
}

function loadDiagrams() {
  if (!diagramManifest) {
    diagramManifest = getJSON("/static/diagrams/manifest.json").catch(
      (error) => {
        diagramManifest = null;
        throw error;
      },
    );
  }
  return diagramManifest;
}

async function renderDiagrams(version) {
  const blocks = Array.from(reader.querySelectorAll("code.language-mermaid"));
  if (!blocks.length) return;
  const page = currentPage;
  const cards = blocks.map((block, index) => {
    const source = block.textContent;
    const card = element("figure", undefined, "diagram-card");
    const heading = element("figcaption", undefined, "diagram-heading");
    const title = `Diagram ${index + 1} · ${page.title}`;
    const expand = element("button", "Expand");
    expand.disabled = true;
    expand.setAttribute("aria-label", `Expand diagram ${index + 1}`);
    heading.append(element("span", title, "diagram-caption"), expand);
    const canvas = element("div", "Loading local SVG…", "diagram-render");
    canvas.tabIndex = 0;
    canvas.setAttribute("role", "region");
    canvas.setAttribute("aria-label", `Overview of ${title.toLowerCase()}; use Expand for readable detail`);
    const details = element("details");
    const code = element("code", source);
    const pre = element("pre");
    pre.append(code);
    details.append(
      element("summary", "Diagram source · Markdown reference"),
      pre,
    );
    card.append(heading, canvas, details);
    block.parentElement.replaceWith(card);
    expand.addEventListener("click", () => {
      $("#diagram-title").textContent = title;
      const image = canvas.querySelector("img");
      if (!image) return;
      $("#diagram-large").replaceChildren(image.cloneNode(true));
      activeDiagram = $("#diagram-large img");
      $("#diagram-download").href = image.src;
      diagramScale = 100;
      $("#diagram-dialog").showModal();
      // Open at a readable size; Fit remains an explicit full-graph view.
      const fit = fittedDiagramWidth();
      diagramScale = Math.min(
        800,
        Math.max(
          100,
          Math.ceil(
            ((Number(activeDiagram.getAttribute("width")) * 0.9) / fit) * 4,
          ) * 25,
        ),
      );
      scaleDiagram();
    });
    return { source, canvas, expand, title, details, heading, index };
  });
  try {
    const manifest = await loadDiagrams();
    for (const card of cards) {
      if (version !== renderVersion) return;
      try {
        const asset = manifest.diagrams.find(
          (entry) => entry.page === page.id && entry.index === card.index,
        );
        if (
          !asset ||
          asset.reference !== card.source.trim() ||
          !/^\/static\/diagrams\/[a-z0-9-]+\.svg$/.test(asset.asset) ||
          !/^[a-f0-9]{64}$/.test(asset.svg_sha256)
        )
          throw new Error("Diagram asset is missing or stale.");
        const image = element("img");
        image.alt = `${asset.title}. ${asset.description}`;
        image.width = asset.svg.width;
        image.height = asset.svg.height;
        image.decoding = "async";
        image.addEventListener("load", () => {
          card.expand.disabled = false;
        });
        image.addEventListener("error", () => {
          card.canvas.replaceChildren(
            element(
              "p",
              "The SVG is unavailable. Read its source below.",
              "diagram-error",
            ),
          );
        });
        image.src = `${asset.asset}?v=${asset.svg_sha256.slice(0, 12)}`;
        card.canvas.replaceChildren(image);
        card.heading.querySelector(".diagram-caption").textContent =
          asset.title;
        card.canvas.setAttribute(
          "aria-label",
          `Overview of ${asset.title.toLowerCase()}; use Expand for readable detail`,
        );
        card.details.querySelector("summary").textContent =
          "Diagram source · D2 / ELK";
        const d2 = element("pre");
        d2.append(
          element(
            "code",
            `${asset.source}\n\n# Shared styles (common.d2)\n${asset.common_source}`,
          ),
        );
        const reference = element("details", undefined, "diagram-reference");
        const pre = element("pre");
        pre.append(element("code", card.source));
        reference.append(
          element("summary", "Original Markdown reference"),
          pre,
        );
        const source = element("a", "Open D2 source ↗", "diagram-source-link");
        source.href = asset.source_asset;
        source.target = "_blank";
        source.rel = "noopener";
        card.details.replaceChildren(
          card.details.querySelector("summary"),
          source,
          d2,
          reference,
        );
      } catch {
        card.canvas.replaceChildren(
          element(
            "p",
            "The diagram needs a local rebuild. Its complete Markdown source is available below.",
            "diagram-error",
          ),
        );
      }
    }
  } catch {
    cards.forEach((card) =>
      card.canvas.replaceChildren(
        element(
          "p",
          "The local diagram catalogue is unavailable. Read the source below.",
          "diagram-error",
        ),
      ),
    );
  }
}

function fittedDiagramWidth() {
  if (!activeDiagram) return 1;
  const viewport = $("#diagram-large");
  const ratio =
    Number(activeDiagram.getAttribute("width")) /
    Number(activeDiagram.getAttribute("height"));
  return Math.max(
    1,
    Math.min(viewport.clientWidth - 24, (viewport.clientHeight - 24) * ratio),
  );
}

function scaleDiagram() {
  if (!activeDiagram) return;
  const fit = fittedDiagramWidth();
  activeDiagram.style.minWidth = "0";
  activeDiagram.style.width = `${Math.max(1, (fit * diagramScale) / 100)}px`;
  $("#diagram-zoom").textContent = `${diagramScale}%`;
}

function pagination(index) {
  const nav = $("#chapter-pagination");
  nav.replaceChildren();
  [
    [catalogue.pages[index - 1], "Previous chapter"],
    [catalogue.pages[index + 1], "Next chapter"],
  ].forEach(([page, label]) => {
    if (!page) return;
    const link = element("a");
    link.href = pageURL(page.id);
    link.append(
      element("small", label),
      document.createTextNode(
        page.title + (label.startsWith("Next") ? " →" : ""),
      ),
    );
    nav.append(link);
  });
}

async function showPage(id, resetScroll = false) {
  const index = catalogue.pages.findIndex((page) => page.id === id);
  if (index < 0) {
    currentPage = null;
    renderVersion++;
    headingObserver?.disconnect();
    $("#table-of-contents").replaceChildren();
    document.title = "Unknown chapter · madrid-delivery-sim";
    $("#error").hidden = false;
    $("#error").textContent =
      "This chapter does not exist. Choose a topic from the navigation.";
    $("#document").hidden = true;
    return;
  }
  currentPage = catalogue.pages[index];
  document.body.classList.toggle("anatomy-mode", currentPage.id === "agent-anatomy");
  $("#agent-anatomy").hidden = currentPage.id !== "agent-anatomy";
  const version = ++renderVersion;
  $("#error").hidden = true;
  $("#document").hidden = false;
  document.title = `${currentPage.title} · madrid-delivery-sim`;
  $("#breadcrumb-topic").textContent = currentPage.group;
  $("#chapter-title").textContent = currentPage.title;
  $("#chapter-summary").textContent = currentPage.summary;
  $("#chapter-status").textContent = currentPage.status;
  $("#review-date").textContent = currentPage.id === "agent-anatomy"
    ? "Generated on request · dated evidence"
    : `Reference review · ${catalogue.reviewed_at}`;
  $("#reading-time").textContent =
    `${Math.max(1, Math.ceil(currentPage.body.split(/\s+/).length / 220))} min read`;
  $("#markdown-link").href = sourceURL(currentPage.file);
  $("#markdown-link").dataset.source = currentPage.file;
  $("#system-explorer").hidden = currentPage.id !== "overview";
  $("#request-flow").hidden = currentPage.id !== "overview";
  document.querySelectorAll(".topic-link").forEach((link) => {
    if (link.dataset.page === currentPage.id)
      link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  reader.innerHTML = DOMPurify.sanitize(
    marked.parse(currentPage.body, { gfm: true }),
    {
      USE_PROFILES: { html: true },
      FORBID_TAGS: ["style", "iframe", "form", "input", "button", "img"],
      FORBID_ATTR: ["style"],
    },
  );
  reader.querySelector("h1")?.remove();
  rewriteLinks(currentPage);
  buildHeadings();
  enhanceBlocks();
  pagination(index);
  if (currentPage.id === "overview") selectComponent("agents");
  if (currentPage.id === "agent-anatomy") await window.AgentAnatomy.mount($("#agent-anatomy"));
  if (resetScroll) window.scrollTo({ top: 0, behavior: "instant" });
  await renderDiagrams(version);
  if (version !== renderVersion) return;
  if (location.hash)
    document
      .getElementById(decodeURIComponent(location.hash.slice(1)))
      ?.scrollIntoView();
}

async function showSource(path, line) {
  const request = ++sourceRequest;
  const dialog = $("#source-dialog");
  $("#source-title").textContent = path;
  $("#source-note").textContent = "Loading a catalogued repository source…";
  $("#source-code").replaceChildren();
  if (!dialog.open) dialog.showModal();
  try {
    const result = await getJSON(
      `/api/documentation/source?path=${encodeURIComponent(path)}`,
    );
    if (request !== sourceRequest || !dialog.open) return;
    const fragment = document.createDocumentFragment();
    result.text.split("\n").forEach((text, index) => {
      const row = element("span", text || " ", "source-line");
      if (index + 1 === Number(line)) row.classList.add("highlight");
      fragment.append(row);
    });
    $("#source-code").replaceChildren(fragment);
    $("#source-note").textContent =
      "Current local checkout. Only explicitly catalogued documentation and implementation files are exposed. No code is executed.";
    $("#source-code .highlight")?.scrollIntoView({ block: "center" });
  } catch {
    if (request === sourceRequest)
      $("#source-note").textContent =
        "This source is not available in the local documentation catalogue.";
  }
}

function search(query) {
  const words = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
  const results = $("#search-results");
  results.replaceChildren();
  if (!words.length) {
    $("#search-count").textContent =
      "Search chapter titles, headings and full text.";
    return;
  }
  const matches = catalogue.pages
    .map((page) => {
      const title = page.title.toLowerCase();
      const text = `${page.title} ${page.summary} ${page.body}`.toLowerCase();
      return {
        page,
        score: words.every((word) => text.includes(word))
          ? words.reduce((sum, word) => sum + (title.includes(word) ? 5 : 1), 0)
          : 0,
      };
    })
    .filter((entry) => entry.score)
    .sort((a, b) => b.score - a.score);
  $("#search-count").textContent =
    `${matches.length} chapter${matches.length === 1 ? "" : "s"} found`;
  matches.forEach(({ page }) => {
    const link = element("a", undefined, "search-result");
    link.href = pageURL(page.id);
    const plain = page.body
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/[#*`>|]/g, " ")
      .replace(/\s+/g, " ");
    const first = plain.toLowerCase().indexOf(words[0]);
    const start = Math.max(0, first - 65);
    const excerpt = `${start ? "…" : ""}${plain.slice(start, start + 230)}…`;
    link.append(
      element("small", page.group),
      element("strong", page.title),
      element("p", excerpt),
    );
    results.append(link);
  });
}

function openSearch() {
  if (!catalogue) return;
  $("#search-dialog").showModal();
  $("#search-input").focus();
  search($("#search-input").value);
}

function closeSourceURL() {
  sourceRequest++;
  const url = new URL(location.href);
  if (url.searchParams.has("source")) {
    url.searchParams.delete("source");
    url.searchParams.delete("line");
    history.replaceState({}, "", url.pathname + url.search + url.hash);
  }
}

document.addEventListener("click", async (event) => {
  const component = event.target.closest("[data-component]");
  if (component) selectComponent(component.dataset.component);
  const closer = event.target.closest("[data-close]");
  if (closer) document.getElementById(closer.dataset.close).close();
  const link = event.target.closest("a");
  if (
    !link ||
    event.ctrlKey ||
    event.metaKey ||
    event.shiftKey ||
    event.altKey ||
    event.button !== 0
  )
    return;
  const url = new URL(link.href);
  if (url.origin !== location.origin || url.pathname !== "/architecture")
    return;
  event.preventDefault();
  if (!catalogue) return;
  $("#search-dialog").close();
  const source = link.dataset.source || url.searchParams.get("source");
  if (source) {
    history.pushState({}, "", url.pathname + url.search + url.hash);
    await showSource(source, link.dataset.line || url.searchParams.get("line"));
    return;
  }
  if ($("#source-dialog").open) $("#source-dialog").close();
  const id = url.searchParams.get("page") || "agent-anatomy";
  const changed = id !== currentPage?.id;
  history.pushState({}, "", url.pathname + url.search + url.hash);
  $(".sidebar").classList.remove("expanded");
  $("#toggle-topics").setAttribute("aria-expanded", "false");
  if (changed) {
    await showPage(id, true);
    $("#reader").focus({ preventScroll: true });
  } else if (url.hash)
    document
      .getElementById(decodeURIComponent(url.hash.slice(1)))
      ?.scrollIntoView();
  else window.scrollTo({ top: 0, behavior: "instant" });
});

window.addEventListener("popstate", async () => {
  if (!catalogue) return;
  const routeURL = location.href;
  const params = new URLSearchParams(location.search);
  const id = params.get("page") || "agent-anatomy";
  if (id !== currentPage?.id) await showPage(id, true);
  else if (location.hash)
    document
      .getElementById(decodeURIComponent(location.hash.slice(1)))
      ?.scrollIntoView();
  if (location.href !== routeURL) return;
  if (params.has("source"))
    await showSource(params.get("source"), params.get("line"));
  else if ($("#source-dialog").open) $("#source-dialog").close();
});

$("#source-dialog").addEventListener("close", closeSourceURL);
$("#search-input").addEventListener("input", (event) =>
  search(event.target.value),
);
$("#search-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    $("#search-results a")?.click();
  }
});
$("#open-search").addEventListener("click", openSearch);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    const dialog = document.querySelector("dialog[open]");
    if (dialog) { event.preventDefault(); dialog.close(); return; }
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    if (!$("#search-dialog").open) openSearch();
  }
});
$("#copy-link").addEventListener("click", () => copy(location.href));
$("#print-page").addEventListener("click", () => window.print());
$("#toggle-topics").addEventListener("click", () => {
  const expanded = $(".sidebar").classList.toggle("expanded");
  $("#toggle-topics").setAttribute("aria-expanded", String(expanded));
});
$("#diagram-in").addEventListener("click", () => {
  diagramScale = Math.min(800, diagramScale + 25);
  scaleDiagram();
});
$("#diagram-out").addEventListener("click", () => {
  diagramScale = Math.max(50, diagramScale - 25);
  scaleDiagram();
});
$("#diagram-reset").addEventListener("click", () => {
  diagramScale = 100;
  scaleDiagram();
});
window.addEventListener("resize", () => {
  if ($("#diagram-dialog").open) scaleDiagram();
});

(async () => {
  try {
    catalogue = await getJSON("/api/documentation");
    buildNavigation();
    await showPage(
      new URLSearchParams(location.search).get("page") || "agent-anatomy",
    );
    const params = new URLSearchParams(location.search);
    if (params.has("source"))
      await showSource(params.get("source"), params.get("line"));
  } catch {
    $("#error").hidden = false;
    $("#error").textContent =
      "The local reference could not be loaded. Refresh the page after starting the app. No cloud services are required.";
  } finally {
    $("#loading").hidden = true;
  }
})();

document.getElementById('replay-flow').addEventListener('click', () => {
  const flow = document.getElementById('request-flow');
  flow.classList.remove('is-playing');
  void flow.offsetWidth;
  flow.classList.add('is-playing');
});
