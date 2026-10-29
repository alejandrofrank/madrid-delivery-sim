/* Local restaurant supply lab. All external data is rendered with textContent. */
'use strict';

const $ = id => document.getElementById(id);
const clone = value => JSON.parse(JSON.stringify(value));
const pretty = value => JSON.stringify(value, null, 2);
const roles = {household: 'Household', restaurant: 'Restaurant', market: 'Supermarket'};
const colors = {household: '#68737e', restaurant: '#9b4c28', market: '#2b6755'};
const budgetLabels = {
  events_per_run: ['Events / run', 1, 1000],
  tool_calls_per_event: ['Tool calls / event', 1, 16],
  tool_calls_per_run: ['Tool calls / run', 1, 2000],
  memory_entries: ['Memory entries', 1, 100],
  memory_bytes: ['Memory bytes', 1, 65536],
};
let blueprint = null;
let agentTemplates = {};
const adkBudgetLabels = {
  model_calls_per_event: ['Model calls / event', 1, 8],
  model_calls_per_run: ['Model calls / restaurant / run', 1, 100],
  reserved_tokens_per_run: ['Reserved tokens / restaurant / run', 1, 1048576],
};
const memoryDefaults = {max_facts: 8, max_bytes: 8192, ttl_seconds: 3600};
const routingDefaults = {
  strategy: 'jev_first', confidence_threshold: 0.85, margin_threshold: 0.20,
  calls_per_run: 32, input_tokens_per_run: 64000, usd_limit: 0.01, model: 'jev-1.14.0',
};
let draft = null;
let snapshot = null;
let selectedId = null;
let agentEditScope = 'inherit';
let draftDirty = false;
let editorDirty = false;
let jsonDirty = false;
let busy = false;
let pollTimer = null;
let inspectVersion = 0;
let inspection = null;
let inspectionAgentId = null;
let inspectionLoadedAt = 0;
let runId = null;
let replay = null;
let activityRoutes = [];
let mapSignature = '';
let displayedClock = '';
let clock = {from: 0, to: 0, at: performance.now(), interval: 500};
let searchContext = '';
let searchVersion = 0;
let orderBookRun = null;
const orderRows = new Map();

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function svgNode(tag, attrs = {}) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}

function showError(error) {
  $('error').textContent = error instanceof Error ? error.message : String(error);
  $('error').hidden = false;
}

function clearError() { $('error').hidden = true; }

function notice(message) {
  $('notice').textContent = message;
  $('notice').hidden = !message;
}

async function api(path, options = {}) {
  const response = await fetch(path, {cache: 'no-store', ...options});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    let detail = data.detail || data.error || response.statusText;
    if (Array.isArray(detail)) detail = detail.map(item => `${(item.loc || []).slice(1).join('.')}: ${item.msg}`).join('\n');
    if (typeof detail === 'object') detail = pretty(detail);
    const error = new Error(response.status === 409 || response.status === 412
      ? 'The blueprint changed in another session. Your draft is preserved. Reload this page after copying your changes to load the current revision.'
      : `${response.status}: ${detail}`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function currentEntity() { return draft?.entities?.find(entity => entity.id === selectedId); }
function runEntity() { return snapshot?.entities?.find(entity => entity.id === selectedId); }
function entityName(id) { return snapshot?.entities?.find(entity => entity.id === id)?.name || draft?.entities?.find(entity => entity.id === id)?.name || id || '—'; }
function running() { return snapshot && ['running', 'pending', 'queued', 'starting'].includes(snapshot.run.status); }
function completed() { return snapshot && !running(); }

function updateButtons() {
  $('save-blueprint').disabled = !draft || !draftDirty || busy;
  $('start-run').disabled = !draft || busy || running();
  $('start-run').textContent = draftDirty ? 'Save & start simulation' : 'Start simulation';
  $('download-evidence').disabled = !snapshot;
  $('check-replay').disabled = !snapshot || running() || busy;
  $('blueprint-state').textContent = !blueprint ? 'Loading blueprint…' : draftDirty ? 'Unsaved next-run edits' : `Blueprint saved · ${String(blueprint.revision).slice(0, 8)}`;
  $('blueprint-state').style.color = draftDirty ? 'var(--orange)' : '';
}

function markDirty() {
  draftDirty = true;
  updateButtons();
}

function formatHour(seconds, config = snapshot?.config || draft) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0)) + Number(config?.start_hour ?? 11) * 3600;
  return [Math.floor(total / 3600) % 24, Math.floor(total / 60) % 60, total % 60].map(value => String(value).padStart(2, '0')).join(':');
}

function relativeTime(seconds) {
  if (seconds === undefined || seconds === null) return '—';
  return `${(Number(seconds) / 60).toFixed(1)} min`;
}

function hourWindow(window) { return `${window?.start ?? 0}–${window?.end ?? 24}`; }
function csv(value) { return String(value || '').split(',').map(item => item.trim()).filter(Boolean); }

function parseWindow(text) {
  const match = String(text).trim().match(/^(\d{1,2})\s*[-–]\s*(\d{1,2})$/);
  if (!match || Number(match[1]) > 23 || Number(match[2]) > 24 || Number(match[1]) === Number(match[2])) throw new Error('Hours need a start from 0 to 23 and a different end from 0 to 24, such as 11–14 or 0–24. Overnight windows are supported.');
  return {start: Number(match[1]), end: Number(match[2])};
}

function agentDefinition(entity = currentEntity()) {
  if (!entity) return {};
  return agentEditScope === 'entity' ? entity.agent || draft.agents[entity.kind] : draft.agents[entity.kind];
}

function captureEditor(report = true) {
  if (!draft || !currentEntity()) return true;
  if (jsonDirty) return applyAdvanced(report);
  if (!editorDirty) return true;
  if (!$('entity-form').checkValidity()) {
    if (report) $('entity-form').reportValidity();
    return false;
  }
  try {
    const entity = currentEntity();
    entity.name = $('entity-name').value.trim();
    entity.node = Number($('entity-node').value);
    entity.opening_hours = parseWindow($('entity-opening').value);
    entity.recipe_ids = csv($('entity-recipes').value);
    entity.order_hours = csv($('entity-hours').value).map(parseWindow);
    entity.allow_substitutions = $('entity-substitutions').checked;
    entity.excluded_ingredients = csv($('entity-excluded').value);
    if (agentEditScope !== 'inherit') {
      const agent = agentDefinition();
      agent.display_name = $('agent-name').value.trim();
      agent.soul = $('agent-soul').value;
      agent.memory = $('agent-memory').value === 'default' ? null : {
        mode: $('agent-memory').value,
        max_facts: Number($('agent-memory-max-facts').value),
        max_bytes: Number($('agent-memory-max-bytes').value),
        ttl_seconds: Number($('agent-memory-ttl-seconds').value),
      };
      if (agent.brain) {
        agent.brain.instructions = $('agent-prompt').value;
        agent.brain.routing = $('adk-routing').value === 'jev_first' ? {
          ...routingDefaults, ...agent.brain.routing, strategy: 'jev_first',
          confidence_threshold: Number($('adk-routing-confidence').value),
          margin_threshold: Number($('adk-routing-margin').value),
        } : null;
        for (const key of Object.keys(adkBudgetLabels)) agent.brain[key] = Number($(`adk-budget-${key}`).value);
      }
      agent.latency_seconds = Number($('agent-latency').value);
      for (const key of Object.keys(budgetLabels)) agent.limits[key] = Number($(`budget-${key}`).value);
    }
    editorDirty = false;
    $('entity-json').value = pretty(entity);
    $('agent-json').value = pretty(agentDefinition());
    return true;
  } catch (error) {
    if (report) showError(error);
    return false;
  }
}

function captureSettings() {
  if (!$('settings-form').checkValidity() || !$('playback-control').checkValidity()) {
    $('settings-form').closest('details').open = true;
    $('settings-form').reportValidity();
    $('playback-control').reportValidity();
    return false;
  }
  for (const field of $('settings-form').elements) if (field.name) draft[field.name] = Number(field.value);
  draft.playback_seconds = Number($('playback-control').value);
  return true;
}

function renderSettings() {
  for (const field of $('settings-form').elements) if (field.name) field.value = draft[field.name];
  $('playback-control').value = draft.playback_seconds;
  $('settings-summary').textContent = `${draft.duration_minutes} simulated minutes · ${draft.calls_per_household} call(s) / household · seed ${draft.seed}`;
}

function renderEntityOptions() {
  $('entity-select').replaceChildren();
  for (const [kind, name] of Object.entries(roles)) {
    const group = element('optgroup');
    group.label = `${name}s`;
    for (const entity of draft.entities.filter(item => item.kind === kind)) {
      const option = element('option', `${entity.name} · ${entity.id}`);
      option.value = entity.id;
      group.append(option);
    }
    $('entity-select').append(group);
  }
  $('entity-select').value = selectedId;
}

function renderAgentEditor() {
  const entity = currentEntity();
  const agent = agentDefinition();
  const disabled = agentEditScope === 'inherit';
  $('agent-scope').value = agentEditScope;
  $('role-template-note').textContent = agentEditScope === 'entity' ? 'This entity only' : `${roles[entity.kind]} template`;
  $('agent-name').value = agent.display_name || '';
  $('agent-soul').value = agent.soul || '';
  $('agent-latency').value = agent.latency_seconds ?? 0;
  $('agent-memory').value = agent.memory?.mode || 'default';
  $('agent-memory').disabled = disabled;
  $('agent-memory-max-facts').value = agent.memory?.max_facts ?? memoryDefaults.max_facts;
  $('agent-memory-max-bytes').value = agent.memory?.max_bytes ?? memoryDefaults.max_bytes;
  $('agent-memory-ttl-seconds').value = agent.memory?.ttl_seconds ?? memoryDefaults.ttl_seconds;
  syncMemoryFields();
  $('agent-engine').value = agent.brain?.provider === 'vertex' ? 'vertex' : agent.brain ? 'adk' : 'rules';
  $('agent-engine').disabled = disabled || entity.kind !== 'restaurant';
  $('adk-editor').hidden = !agent.brain;
  $('agent-prompt').value = agent.brain?.instructions || '';
  $('agent-prompt').disabled = disabled || !agent.brain;
  $('agent-prompt').required = !disabled && !!agent.brain;
  $('adk-routing').value = agent.brain?.routing?.strategy === 'jev_first' ? 'jev_first' : 'tool_loop';
  $('adk-routing').disabled = disabled || !agent.brain;
  $('adk-routing-confidence').value = agent.brain?.routing?.confidence_threshold ?? routingDefaults.confidence_threshold;
  $('adk-routing-margin').value = agent.brain?.routing?.margin_threshold ?? routingDefaults.margin_threshold;
  syncRoutingFields();
  $('adk-provider-note').textContent = agent.brain?.provider === 'vertex'
    ? 'Vertex requires the matching approved deployment profile, explicit deployment opt-in and a positive monetary allowance. Live calls can cost money.'
    : 'The ADK model loop uses a scripted offline fixture. Jev routing, if selected, requires its separate provider opt-in and budget. The fixture tests wiring and safety, not LLM understanding.';
  $('load-adk-profile').disabled = disabled;
  $('adk-profile').disabled = disabled;
  $('adk-budget-fields').replaceChildren();
  if (agent.brain) for (const [key, [label, min, max]] of Object.entries(adkBudgetLabels)) {
    const field = element('label', label), input = element('input');
    Object.assign(input, {id: `adk-budget-${key}`, type: 'number', min: String(min), max: String(max), required: true, value: agent.brain[key], disabled});
    field.append(input); $('adk-budget-fields').append(field);
  }
  for (const id of ['agent-name', 'agent-soul', 'agent-latency']) $(id).disabled = disabled;
  $('budget-fields').replaceChildren();
  for (const [key, [label, min, max]] of Object.entries(budgetLabels)) {
    const field = element('label', label);
    const input = element('input');
    Object.assign(input, {id: `budget-${key}`, type: 'number', min: String(min), max: String(max), step: '1', required: true, value: agent.limits?.[key] ?? min, disabled});
    field.append(input);
    $('budget-fields').append(field);
  }
  $('agent-json').value = pretty(agent);
  $('agent-json').readOnly = disabled;
  $('agent-json').setAttribute('aria-label', disabled ? 'Inherited agent definition, read only. Choose override or shared template to edit.' : 'Editable agent definition JSON');
}

function syncMemoryFields() {
  const explicit = $('agent-memory').value !== 'default';
  $('agent-memory-fields').hidden = !explicit;
  for (const id of ['agent-memory-max-facts', 'agent-memory-max-bytes', 'agent-memory-ttl-seconds']) {
    $(id).disabled = !explicit || agentEditScope === 'inherit';
    $(id).required = explicit && agentEditScope !== 'inherit';
  }
}

function syncRoutingFields() {
  const enabled = $('adk-routing').value === 'jev_first' && !!agentDefinition().brain;
  $('adk-routing-fields').hidden = !enabled;
  for (const id of ['adk-routing-confidence', 'adk-routing-margin']) {
    $(id).disabled = !enabled || agentEditScope === 'inherit';
    $(id).required = enabled && agentEditScope !== 'inherit';
  }
}

function renderEntityHeading(entity) {
  $('inspector-title').textContent = entity.name;
  $('entity-context').textContent = `${entity.id} · node ${entity.node} · grid ${entity.node % 32}, ${Math.floor(entity.node / 32)}`;
  $('entity-kind').textContent = roles[entity.kind] || entity.kind;
}

function renderEditor() {
  const entity = currentEntity();
  if (!entity) return;
  renderEntityHeading(entity);
  $('entity-name').value = entity.name;
  $('entity-node').value = entity.node;
  $('entity-opening').value = hourWindow(entity.opening_hours);
  $('entity-recipes').value = (entity.recipe_ids || []).join(', ');
  $('entity-hours').value = (entity.order_hours || []).map(hourWindow).join(', ');
  $('entity-substitutions').checked = entity.allow_substitutions;
  $('entity-excluded').value = (entity.excluded_ingredients || []).join(', ');
  $('entity-json').value = pretty(entity);
  renderAgentEditor();
  editorDirty = false;
  jsonDirty = false;
}

function applyAdvanced(report = true) {
  try {
    const original = currentEntity();
    const entity = JSON.parse($('entity-json').value);
    const agent = JSON.parse($('agent-json').value);
    if (!entity || typeof entity !== 'object' || Array.isArray(entity)) throw new Error('Entity definition must be a JSON object.');
    if (entity.id !== original.id || entity.kind !== original.kind) throw new Error('Keep the entity ID and kind unchanged so order and agent references remain valid.');
    if (!entity.name || !Number.isInteger(entity.node) || entity.node < 0 || entity.node > 1023) throw new Error('Entity needs a name and an integer node from 0 to 1023.');
    if (agentEditScope !== 'inherit' && (!agent || typeof agent !== 'object' || Array.isArray(agent) || !agent.limits)) throw new Error('Agent definition must be a JSON object with limits.');
    if (agentEditScope === 'entity') entity.agent = agent;
    if (agentEditScope === 'role') draft.agents[entity.kind] = agent;
    draft.entities[draft.entities.findIndex(item => item.id === selectedId)] = entity;
    if (agentEditScope !== 'role') agentEditScope = entity.agent ? 'entity' : 'inherit';
    editorDirty = false;
    jsonDirty = false;
    markDirty();
    renderEditor();
    renderEntityOptions();
    drawMap(true);
    if (report) { clearError(); notice('JSON applied to your draft. Save the blueprint to validate all definitions.'); }
    return true;
  } catch (error) {
    if (report) showError(new Error(`JSON was not applied: ${error.message}`));
    return false;
  }
}

async function saveBlueprint() {
  if (!captureEditor() || !captureSettings()) return false;
  busy = true;
  updateButtons();
  clearError();
  try {
    const result = await api('/api/supply/blueprint', {method: 'PUT', headers: {'Content-Type': 'application/json', 'If-Match': blueprint.revision}, body: JSON.stringify(draft)});
    blueprint = result;
    draft = clone(result.config);
    draftDirty = false;
    editorDirty = false;
    jsonDirty = false;
    if (!currentEntity()) selectedId = draft.entities[0]?.id;
    renderSettings();
    renderEntityOptions();
    renderEditor();
    drawMap(true);
    notice(snapshot ? 'Blueprint saved. The selected run keeps its original definitions. Start a new simulation to use these edits.' : 'Blueprint saved. The next simulation will use these definitions.');
    return true;
  } catch (error) {
    showError(error);
    return false;
  } finally {
    busy = false;
    updateButtons();
  }
}

async function startRun() {
  if (busy || running()) return;
  if (!captureEditor() || !captureSettings()) return;
  if (draftDirty && !await saveBlueprint()) return;
  busy = true;
  updateButtons();
  clearError();
  try {
    const result = await api('/api/supply/runs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({revision: blueprint.revision})});
    runId = result.id;
    sessionStorage.setItem('supply-run-id', runId);
    const url = new URL(location.href); url.searchParams.set('run', runId);
    history.replaceState(null, '', url);
    snapshot = null;
    replay = null;
    inspection = null;
    inspectionAgentId = null;
    inspectVersion++;
    mapSignature = '';
    $('replay-result').hidden = true;
    $('replay-state').textContent = 'Replay becomes available after this run finishes.';
    notice('Simulation started. Calls, ingredient requests, and deliveries are synthetic local events.');
    await pollRun();
  } catch (error) { showError(error); }
  finally { busy = false; updateButtons(); }
}

function useSnapshot(data) {
  const sameRun = snapshot?.run.id === data.run.id;
  const now = performance.now();
  const previous = visualTime(now);
  clock = {from: sameRun ? Math.min(previous, Number(data.run.sim_time)) : Number(data.run.sim_time), to: Number(data.run.sim_time), at: now, interval: sameRun ? Math.max(200, Math.min(1500, now - clock.at)) : 500};
  snapshot = data;
  $('run-state').textContent = `${String(data.run.status).replaceAll('_', ' ')} · ${relativeTime(data.run.sim_time)}`;
  $('run-id').textContent = `Run ${data.run.id}`;
  $('map-source').textContent = `Frozen run · ${String(data.run.id).slice(0, 8)}`;
  $('map-context').textContent = '32 × 32 fictional grid · run positions frozen at start';
  $('evidence-context').textContent = `Run ${String(data.run.id).slice(0, 8)} · simulated conversations and append-only facts`;
  renderMetrics();
  drawMap();
  renderInspection();
  renderEvidence();
  renderInvariants();
  updateButtons();
  if (!inspection || performance.now() - inspectionLoadedAt > 2000) loadAgentInspection();
}

async function pollRun() {
  clearTimeout(pollTimer);
  if (!runId) return;
  try {
    const data = await api(`/api/supply/runs/${encodeURIComponent(runId)}`);
    useSnapshot(data);
    if (running()) pollTimer = setTimeout(pollRun, 500);
    else $('replay-state').textContent = replay ? 'Replay checked against persisted facts.' : 'Run finished. Verify its stock and order projections from persisted facts.';
  } catch (error) {
    showError(error);
    if (error.status === 404) { sessionStorage.removeItem('supply-run-id'); runId = null; }
    else pollTimer = setTimeout(pollRun, 2000);
  }
}

function renderMetrics() {
  const orders = snapshot?.orders || [];
  const usage = snapshot?.metrics || {};
  const provider = String(usage.model_provider || usage.provider || 'disabled');
  const calls = snapshot ? (usage.model_calls ?? '—') : 0;
  const reserved = usage.search_reserved_calls;
  let usageCaption = provider === 'disabled' || provider === 'local' ? 'Free local city policies' : `${provider} · actual usage unknown`;
  if (reserved !== undefined && reserved !== null) {
    if (Number(reserved) > 0) {
      const actualInput = usage.search_actual_input_tokens;
      const knownUsage = usage.search_unknown_usage_calls === 0 && actualInput !== undefined && actualInput !== null;
      usageCaption = knownUsage
        ? `${provider} · ${reserved} reserved calls; ${actualInput} input tokens`
        : `${provider} · ${reserved} reserved; actual usage unknown`;
    } else usageCaption = '0 reserved · local city policies';
  } else if (snapshot && usage.model_calls === null) usageCaption = `${provider} · actual usage unknown`;
  if (usage.adk_offline_calls) usageCaption += ` · ${usage.adk_offline_calls} offline ADK calls, €0`;
  if (usage.adk_vertex_dispatches) usageCaption += ` · ${usage.adk_vertex_dispatches} Vertex dispatches; $${Number(usage.adk_reserved_usd || 0).toFixed(4)} reserved`;
  const active = orders.filter(order => !['delivered', 'failed', 'rejected', 'cancelled'].includes(order.status));
  const delivered = orders.filter(order => order.status === 'delivered');
  const failed = orders.filter(order => ['failed', 'rejected', 'cancelled'].includes(order.status));
  const stats = [
    ['Entities', mapEntities().length, 'Homes, kitchens & markets'],
    ['Orders', snapshot ? orders.length : '—', 'Simulated household demand'],
    ['In progress', snapshot ? active.length : '—', 'Calls, sourcing & cooking'],
    ['Delivered', snapshot ? delivered.length : '—', 'Completed meal orders'],
    ['Failed', snapshot ? failed.length : '—', 'Inspect facts for the reason'],
    ['Provider calls', calls, usageCaption],
  ];
  $('metrics').replaceChildren(...stats.map(([label, value, caption]) => {
    const metric = element(label === 'Orders' ? 'button' : 'article', null, 'metric');
    if (label === 'Orders') {
      metric.type = 'button';
      metric.classList.add('metric-action');
      metric.disabled = !snapshot;
      metric.setAttribute('aria-label', `View all ${orders.length} orders`);
      metric.setAttribute('aria-controls', 'orders-panel');
      metric.addEventListener('click', () => {
        activateTab($('orders-tab'), $('orders-tab').parentElement);
        $('orders-tab').focus({preventScroll: true});
        $('run-evidence').scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start'});
      });
    }
    metric.append(element('span', label), element('strong', value), element('small', caption));
    return metric;
  }));
}

function mapEntities() { return snapshot?.entities || draft?.entities || []; }

function coordinates(entity) {
  const node = Number(entity?.node ?? entity?.definition?.node);
  return {x: node % 32, y: Math.floor(node / 32)};
}

function drawMap(force = false) {
  if (!draft) return;
  const entities = mapEntities();
  const filter = $('map-filter').value;
  const signature = `${snapshot?.run.id || blueprint?.revision}:${filter}:${selectedId}:${JSON.stringify(entities.map(entity => [entity.id, entity.name, entity.node]))}`;
  const svg = $('city-map');
  if (signature !== mapSignature || force) {
    mapSignature = signature;
    svg.replaceChildren();
    const city = snapshot?.city || blueprint.city || {};
    const fabric = svgNode('g', {'aria-hidden': 'true', 'pointer-events': 'none'});
    const spacing = Number(city.spacing_m || 500);
    for (const area of city.neighborhoods || []) {
      fabric.append(svgNode('rect', {x: Number(area.x) / spacing, y: Number(area.y) / spacing, width: Number(area.width) / spacing, height: Number(area.height) / spacing, fill: '#f1f2f3', stroke: '#d4d8dc', 'stroke-width': '.03'}));
      const label = svgNode('text', {x: Number(area.x) / spacing + .5, y: Number(area.y) / spacing + .75, class: 'district-label'});
      label.textContent = area.name;
      fabric.append(label);
    }
    for (const building of city.buildings || []) {
      if (['home', 'apartment'].includes(building.kind)) continue;
      fabric.append(svgNode('rect', {x: Number(building.x) / spacing, y: Number(building.y) / spacing, width: Math.max(.2, Number(building.width) / spacing), height: Math.max(.2, Number(building.height) / spacing), rx: '.05', fill: building.kind === 'park' ? '#e5ece7' : '#d4d8dc'}));
    }
    svg.append(fabric);
    const roads = svgNode('g', {'aria-hidden': 'true', 'pointer-events': 'none'});
    for (let n = 0; n < 32; n++) {
      roads.append(svgNode('line', {x1: 0, x2: 31, y1: n, y2: n, stroke: n % 4 ? '#dfe2e5' : '#b6bdc3', 'stroke-width': n % 4 ? '.045' : '.08'}));
      roads.append(svgNode('line', {y1: 0, y2: 31, x1: n, x2: n, stroke: n % 4 ? '#dfe2e5' : '#b6bdc3', 'stroke-width': n % 4 ? '.045' : '.08'}));
    }
    svg.append(roads, svgNode('g', {id: 'activity-routes', 'aria-hidden': 'true'}));
    const markers = svgNode('g');
    for (const entity of [...entities].sort((a, b) => (a.kind === 'household' ? 0 : 1) - (b.kind === 'household' ? 0 : 1))) {
      if (filter !== 'all' && entity.kind !== filter) continue;
      const {x, y} = coordinates(entity);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      const selected = selectedId === entity.id;
      const radius = entity.kind === 'household' ? .22 : .38;
      const group = svgNode('g', {class: 'entity', role: 'button', tabindex: '0', 'aria-label': `${entity.name}, ${roles[entity.kind] || entity.kind}, grid ${x}, ${y}`, 'aria-pressed': selected, 'data-entity-id': entity.id});
      const title = svgNode('title'); title.textContent = `${entity.name} · ${entity.id}`;
      group.append(title, svgNode('circle', {cx: x, cy: y, r: radius + .2, fill: 'transparent'}));
      if (selected) group.append(svgNode('circle', {cx: x, cy: y, r: radius + .17, class: 'selected-ring'}));
      let shape;
      if (entity.kind === 'household') shape = svgNode('path', {d: `M${x - radius},${y - .02}L${x},${y - radius}L${x + radius},${y - .02}V${y + radius}H${x - radius}Z`});
      else if (entity.kind === 'restaurant') shape = svgNode('rect', {x: x - radius, y: y - radius, width: radius * 2, height: radius * 2, rx: '.11'});
      else shape = svgNode('path', {d: `M${x},${y - radius - .06}L${x + radius + .06},${y}L${x},${y + radius + .06}L${x - radius - .06},${y}Z`});
      shape.setAttribute('fill', colors[entity.kind] || '#3d596c');
      shape.setAttribute('stroke', '#ffffff');
      shape.setAttribute('stroke-width', '.075');
      shape.setAttribute('class', 'marker-body');
      group.append(shape);
      if (entity.kind !== 'household' || selected) {
        const label = svgNode('text', {x: x > 23 ? x - radius - .22 : x + radius + .22, y: y + .12, 'text-anchor': x > 23 ? 'end' : 'start', class: 'entity-label'});
        label.textContent = entity.name;
        group.append(label);
      }
      group.addEventListener('click', () => selectEntity(entity.id));
      group.addEventListener('keydown', event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); selectEntity(entity.id); } });
      markers.append(group);
    }
    svg.append(markers);
    $('map-empty').hidden = true;
  }
  const counts = Object.keys(roles).map(kind => `${entities.filter(entity => entity.kind === kind).length} ${kind === 'market' ? 'supermarkets' : kind + 's'}`);
  $('map-counts').textContent = counts.join(' · ');
  drawActivity();
}

function findEntity(value) {
  if (!value) return null;
  return mapEntities().find(entity => value === entity.id || String(value).endsWith(`:${entity.id}`)) || null;
}

function drawActivity() {
  const layer = $('activity-routes');
  if (!layer) return;
  layer.replaceChildren();
  activityRoutes = [];
  for (const event of (snapshot?.events || []).filter(item => ['pending', 'queued', 'leased'].includes(item.state)).slice(-36)) {
    const from = findEntity(event.producer) || findEntity(event.payload?.household) || findEntity(event.payload?.restaurant);
    const to = findEntity(event.target_store);
    if (!from || !to || from.id === to.id) continue;
    const a = coordinates(from), b = coordinates(to);
    const path = svgNode('path', {d: `M${a.x},${a.y}L${b.x},${b.y}`, class: 'activity-route'});
    const dot = svgNode('circle', {r: '.13', class: 'activity-dot'});
    layer.append(path, dot);
    const latency = Math.max(1, Number(snapshot.config?.communication_latency_seconds || 5));
    activityRoutes.push({a, b, dot, due: Number(event.due_sim), latency});
  }
}

function visualTime(now = performance.now()) {
  const fraction = Math.max(0, Math.min(1, (now - clock.at) / clock.interval));
  return clock.from + (clock.to - clock.from) * fraction;
}

function animate(now) {
  const time = visualTime(now);
  const text = formatHour(time);
  if (text !== displayedClock) { $('sim-clock').textContent = text; displayedClock = text; }
  for (const route of activityRoutes) {
    const fraction = Math.max(0, Math.min(1, (time - route.due + route.latency) / route.latency));
    route.dot.setAttribute('cx', route.a.x + (route.b.x - route.a.x) * fraction);
    route.dot.setAttribute('cy', route.a.y + (route.b.y - route.a.y) * fraction);
  }
  requestAnimationFrame(animate);
}

function selectEntity(id) {
  if (id === selectedId) return;
  if (!captureEditor()) { $('entity-select').value = selectedId; return; }
  selectedId = id;
  if (!currentEntity()) return;
  agentEditScope = currentEntity().agent ? 'entity' : 'inherit';
  inspection = null;
  inspectionAgentId = null;
  inspectionLoadedAt = 0;
  $('entity-select').value = id;
  renderEditor();
  drawMap(true);
  renderInspection();
  renderEvidence();
  loadAgentInspection();
}

function agentForEntity() {
  const agents = Array.isArray(snapshot?.agents) ? snapshot.agents : Object.values(snapshot?.agents || {});
  return agents.find(agent => agent.entity_id === selectedId || agent.namespace === selectedId || agent.store === selectedId || agent.agent_id === selectedId || String(agent.agent_id || '').endsWith(`:${selectedId}`));
}

async function loadAgentInspection() {
  const agent = agentForEntity();
  if (!runId || !agent?.agent_id) return;
  const inspectedRun = runId;
  const version = ++inspectVersion;
  inspectionLoadedAt = performance.now();
  try {
    const data = await api(`/api/supply/runs/${encodeURIComponent(runId)}/agents/${encodeURIComponent(agent.agent_id)}`);
    if (version !== inspectVersion || inspectedRun !== runId || agentForEntity()?.agent_id !== agent.agent_id) return;
    inspection = data;
    inspectionAgentId = agent.agent_id;
    renderInspection();
  } catch (error) {
    if (version !== inspectVersion) return;
    inspection = {inspection_error: error.message};
    inspectionAgentId = agent.agent_id;
    renderInspection();
  }
}

function jsonDetails(label, data, open = false) {
  const details = element('details');
  details.open = open;
  details.append(element('summary', label), element('pre', pretty(data)));
  return details;
}

function statList(entries) {
  const list = element('dl', null, 'stat-list');
  for (const [label, value] of entries) {
    const item = element('div'); item.append(element('dt', label), element('dd', typeof value === 'object' ? pretty(value) : value ?? '—')); list.append(item);
  }
  return list;
}

function table(headers, rows) {
  const node = element('table');
  const head = element('thead'), tr = element('tr');
  for (const header of headers) tr.append(element('th', header));
  head.append(tr);
  const body = element('tbody');
  for (const row of rows) {
    const line = element('tr');
    for (const cell of row) { const td = element('td'); td.append(cell instanceof Node ? cell : document.createTextNode(String(cell ?? '—'))); line.append(td); }
    body.append(line);
  }
  node.append(head, body);
  return node;
}

function stateBadge(value) {
  const good = ['delivered', 'ready', 'completed', 'processed', 'received', 'accepted', 'ok', 'passed'].includes(value);
  const bad = ['failed', 'rejected', 'cancelled', 'dead'].includes(value);
  return element('span', String(value || 'unknown').replaceAll('_', ' '), `state ${good ? 'good' : bad ? 'bad' : 'pending'}`);
}

function renderInspection() {
  const box = $('selected-run-details');
  box.replaceChildren();
  syncIngredientSearch();
  if (!snapshot) { $('inspection-note').textContent = 'Start a simulation to inspect frozen definitions, stock, and private agent memory.'; return; }
  const entity = runEntity();
  if (!entity) { $('inspection-note').textContent = 'This entity is in the next-run blueprint and is absent from the selected run.'; return; }
  $('inspection-note').textContent = `Frozen run state for ${entity.name}. This operator view can inspect each agent; agents receive only their own scoped tools and memory.`;
  const agent = agentForEntity();
  const detail = inspectionAgentId === agent?.agent_id ? inspection : null;
  const identity = detail?.agent || agent || {};
  const definition = identity.definition || identity;
  const frozenSettings = entity.definition?.agent || snapshot.config?.agents?.[entity.kind] || {};
  const frozenMemory = Object.hasOwn(definition, 'memory') ? definition.memory : frozenSettings.memory;
  if ($('inspection-tab').getAttribute('aria-selected') === 'true') renderEntityHeading(entity);
  const agentSection = element('section', null, 'inspector-section');
  agentSection.append(element('h3', 'Agent identity'), statList([
    ['Display name', identity.display_name || identity.definition?.display_name || entity.definition?.agent?.display_name || '—'],
    ['Role', identity.role || entity.kind],
    ['Engine', definition.policy === 'adk' ? `Google ADK · ${definition.brain?.provider || 'offline'}` : 'Local rules'],
    ['Frozen routing', definition.policy !== 'adk' ? 'Local rules' : definition.brain?.routing?.strategy === 'jev_first' ? 'Jev first; escalate uncertainty' : 'Current model tool loop'],
    ['Frozen memory mode', frozenMemory?.mode || 'Default / inherit'],
    ['Agent ID', identity.agent_id || 'Not provisioned'],
    ['Latency', `${identity.latency_seconds ?? identity.definition?.latency_seconds ?? entity.definition?.agent?.latency_seconds ?? snapshot.config?.agents?.[entity.kind]?.latency_seconds ?? '—'} seconds`],
  ]));
  if (definition.policy === 'adk' && agent?.adk_budget) agentSection.append(statList([
    ['ADK model calls', `${agent.adk_budget.calls_reserved} / ${definition.brain.model_calls_per_run}`],
    ['ADK tokens reserved', `${agent.adk_budget.tokens_reserved} / ${definition.brain.reserved_tokens_per_run}`],
    ['ADK money reserved', `$${Number(agent.adk_budget.usd_reserved).toFixed(4)} / $${Number(definition.brain.usd_limit).toFixed(2)}`],
  ]));
  const ownStock = (snapshot.stock || []).filter(row => row.owner === entity.id || row.owner === agent?.agent_id);
  const stockSection = element('section', null, 'inspector-section');
  stockSection.append(element('h3', `Own stock · ${ownStock.length} ingredients`));
  stockSection.append(ownStock.length ? table(['Ingredient', 'On hand', 'Reserved'], ownStock.map(row => [`${row.ingredient} · ${row.unit}`, row.on_hand, row.reserved ?? 0])) : element('p', entity.kind === 'household' ? 'Households place meal orders and do not share kitchen stock.' : 'No stock rows in this snapshot.'));
  const memorySection = element('section', null, 'inspector-section');
  memorySection.append(element('h3', 'Own memory & budgets'));
  if (frozenMemory) memorySection.append(statList([
    ['Memory mode', frozenMemory.mode],
    ['Recall limits', `${frozenMemory.max_facts} facts · ${frozenMemory.max_bytes} bytes · ${frozenMemory.ttl_seconds} s lifetime`],
  ]));
  if (frozenMemory?.mode === 'none') memorySection.append(element('p', 'Recall is disabled for this run. Retained audit facts remain available to this operator view.', 'scope-note'));
  const memory = detail?.memory ?? agent?.memory ?? [];
  const budget = identity.budget || detail?.budget || agent?.budget || detail?.parameters?.limits || identity.limits || {};
  if (detail?.inspection_error) memorySection.append(element('p', `Agent inspection unavailable: ${detail.inspection_error}`));
  memorySection.append(jsonDetails('Scoped private memory', memory, true), jsonDetails('Budget use and limits', budget), jsonDetails('Frozen agent definition, soul & parameters', {agent: identity, parameters: detail?.parameters || {}}), jsonDetails('Frozen entity definition', entity.definition || entity));
  box.append(agentSection, stockSection, memorySection);
}

function syncIngredientSearch() {
  const entity = runEntity();
  const available = Boolean(snapshot && entity && ['restaurant', 'market'].includes(entity.kind));
  $('ingredient-search').hidden = !available;
  const context = available ? `${snapshot.run.id}:${entity.id}` : '';
  if (context === searchContext) return;
  searchContext = context;
  searchVersion++;
  $('ingredient-query').value = '';
  $('ingredient-search-button').disabled = false;
  $('ingredient-search-state').textContent = 'Observed stock only. A match does not reserve ingredients.';
  $('ingredient-search-results').replaceChildren();
}

async function searchIngredients(event) {
  event.preventDefault();
  const query = $('ingredient-query').value.trim();
  if (!query) {
    searchVersion++;
    $('ingredient-search-button').disabled = false;
    $('ingredient-search-results').replaceChildren();
    $('ingredient-search-state').textContent = 'Enter an ingredient name or ID to search this entity’s stock.';
    $('ingredient-query').focus();
    return;
  }
  const entity = runEntity();
  if (!snapshot || !entity || !['restaurant', 'market'].includes(entity.kind)) return;
  const context = searchContext;
  const version = ++searchVersion;
  $('ingredient-search-button').disabled = true;
  $('ingredient-search-state').textContent = 'Matching ingredients in this entity’s observed stock…';
  $('ingredient-search-results').replaceChildren();
  try {
    const data = await api(`/api/supply/runs/${encodeURIComponent(snapshot.run.id)}/entities/${encodeURIComponent(entity.id)}/search?query=${encodeURIComponent(query)}`);
    if (version !== searchVersion || context !== searchContext) return;
    const results = Array.isArray(data.results) ? data.results : [];
    const box = $('ingredient-search-results');
    if (results.length) {
      box.append(table(['Ingredient', 'Available now', 'Version'], results.map(item => {
        const label = element('span', item.name || item.id);
        label.append(element('small', item.id));
        return [label, `${item.available_now ?? 0} ${item.unit || ''}`, item.version ?? '—'];
      })));
    } else box.append(element('p', 'No matching ingredients in this entity’s stock.', 'search-empty'));
    const reviews = Array.isArray(data.reviews) ? data.reviews : [];
    if (reviews.length) {
      const details = element('details', null, 'search-reviews');
      details.append(element('summary', `${reviews.length} match review(s)`), table(['Candidate / choice', 'Confidence', 'Source'], reviews.map(review => {
        const choice = typeof review.choice === 'object' ? pretty(review.choice) : review.choice;
        const label = element('span', review.id || '—'); label.append(element('small', choice || '—'));
        const confidence = typeof review.confidence === 'number' ? `${Math.round(review.confidence * 100)}%` : review.confidence ?? '—';
        return [label, confidence, review.source || 'local'];
      })));
      box.append(details);
    }
    $('ingredient-search-state').textContent = `${results.length} match(es) · ${data.candidates_count ?? results.length} candidates · observed ${formatHour(data.as_of_sim)}. Stock is not reserved.`;
  } catch (error) {
    if (version !== searchVersion || context !== searchContext) return;
    $('ingredient-search-state').textContent = `Ingredient search unavailable: ${error.message}`;
  } finally {
    if (version === searchVersion && context === searchContext) $('ingredient-search-button').disabled = false;
  }
}

function touches(value, id = selectedId) {
  if (!value || !id) return false;
  if (typeof value === 'string') return value === id || value.endsWith(`:${id}`);
  if (Array.isArray(value)) return value.some(item => touches(item, id));
  if (typeof value === 'object') return Object.values(value).some(item => touches(item, id));
  return false;
}

function selectedOrderIds() {
  return new Set((snapshot?.orders || []).filter(order => order.household === selectedId || order.restaurant === selectedId).map(order => order.id));
}

function related(row, orderIds) {
  if (!$('entity-only').checked) return true;
  return touches(row) || orderIds.has(row.order_id) || orderIds.has(row.payload?.order_id) || orderIds.has(row.payload?.order) || orderIds.has(row.payload?.detail?.order);
}

function entityLink(id) {
  const button = element('button', entityName(id));
  button.type = 'button';
  button.addEventListener('click', () => selectEntity(id));
  return button;
}

function actorName(id) {
  const known = {'dispatcher:fleet': 'Fleet dispatcher', lab_world: 'City world', supply_ingress: 'Household scheduler'};
  return known[id] || entityName(String(id || '').replace(/^(household|restaurant|market):/, ''));
}

function readableAction(value) {
  const text = String(value || 'Recorded step').replaceAll('_', ' ').replaceAll('.', ' · ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function renderOrderBook() {
  const box = $('orders-panel');
  const currentRun = snapshot?.run.id || null;
  if (orderBookRun !== currentRun || !box.firstChild) {
    orderBookRun = currentRun;
    orderRows.clear();
    box.replaceChildren();
    box.append(element('p', 'All orders in this run, including scheduled calls. Select an order to expand its complete history.', 'order-book-note'));
  }
  if (!snapshot?.orders?.length) {
    if (!box.querySelector('.empty')) box.append(element('p', snapshot ? 'No orders were scheduled for this run.' : 'Start a simulation to see its orders here.', 'empty'));
    return;
  }
  const schedule = new Map((snapshot.calls || snapshot.config.schedule || []).map(call => [call.order_id, call]));
  const orders = [...snapshot.orders].sort((a, b) => (schedule.get(a.id)?.arrival_sim ?? a.created_sim) - (schedule.get(b.id)?.arrival_sim ?? b.created_sim) || a.id.localeCompare(b.id));
  for (const order of orders) {
    let row = orderRows.get(order.id);
    if (!row) {
      const disclosure = element('details', null, 'order-record');
      disclosure.dataset.orderId = order.id;
      const summary = element('summary', null, 'order-summary');
      const body = element('div', null, 'order-history');
      disclosure.append(summary, body);
      row = {disclosure, summary, body, signature: '', data: null, loading: false, fetchedAt: 0, fingerprint: ''};
      orderRows.set(order.id, row);
      disclosure.addEventListener('toggle', event => {
        if (event.target === disclosure && disclosure.open) loadOrderHistory(order.id, row);
      });
      box.append(disclosure);
    }
    const call = schedule.get(order.id);
    const signature = pretty([order, call?.arrival_sim]);
    if (row.signature !== signature) {
      row.signature = signature;
      const arrow = element('span', '›', 'order-disclosure'); arrow.setAttribute('aria-hidden', 'true');
      const title = element('span', null, 'order-title');
      title.append(element('strong', readableAction(order.meal)), element('small', `${order.id} · ${order.quantity} serving(s)`));
      const route = element('span', `${entityName(order.household)} → ${entityName(order.restaurant)}`, 'order-parties');
      row.summary.replaceChildren(arrow, title, route, stateBadge(order.status === 'intent' ? 'scheduled' : order.status), element('span', formatHour(call?.arrival_sim ?? order.created_sim), 'mono order-time'));
    }
    if (row.disclosure.open && running()) loadOrderHistory(order.id, row);
  }
}

async function loadOrderHistory(orderId, row, force = false) {
  if (row.loading || (!force && row.data && (!running() || performance.now() - row.fetchedAt < 5000))) return;
  const requestedRun = snapshot?.run.id;
  if (!requestedRun) return;
  row.loading = true;
  if (!row.data) row.body.replaceChildren(element('p', 'Loading complete order history…', 'order-load-state'));
  try {
    const data = await api(`/api/supply/runs/${encodeURIComponent(requestedRun)}/orders/${encodeURIComponent(orderId)}`);
    if (snapshot?.run.id !== requestedRun || orderRows.get(orderId) !== row) return;
    row.data = data;
    row.fetchedAt = performance.now();
    const fingerprint = pretty(data);
    if (fingerprint !== row.fingerprint || force) {
      row.fingerprint = fingerprint;
      renderOrderHistory(data, row.body, () => loadOrderHistory(orderId, row, true));
    }
  } catch (error) {
    if (snapshot?.run.id !== requestedRun || orderRows.get(orderId) !== row) return;
    row.fingerprint = '';
    const message = element('p', `Order history unavailable: ${error.message}`, 'notice error');
    const retry = element('button', 'Retry loading history');
    retry.type = 'button'; retry.addEventListener('click', () => loadOrderHistory(orderId, row, true));
    row.body.replaceChildren(message, retry);
  } finally { row.loading = false; }
}

function memoryValue(value, field = '') {
  if (value === null) return 'None';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (Array.isArray(value)) return field === 'route' ? `${value.length} route waypoints` : value.map(item => memoryValue(item)).join(', ') || 'Empty list';
  if (typeof value === 'object') return Object.entries(value).map(([key, item]) => `${readableAction(key)}: ${memoryValue(item, key)}`).join(' · ') || 'Empty record';
  if (['sim_time', 'arrive_sim', 'deadline_sim', 'depart_sim'].includes(field) && Number.isFinite(value)) return formatHour(value);
  if (['actor', 'courier', 'store'].includes(field)) return actorName(value);
  return String(value).replaceAll('_', ' ');
}

function memoryCard(write, person) {
  const card = element('div', null, `chat-memory memory-${write.mode}`);
  const modes = {created: 'Memory created', updated: 'Memory updated', unchanged: 'Memory retained · no value changed', expired: 'Memory renewed · previous entry expired', unknown: 'Saved memory · previous value unavailable'};
  card.append(element('strong', modes[write.mode] || 'Saved memory'));
  if (write.kind) card.append(element('p', `${readableAction(write.kind)} · revision ${write.version} · source event #${write.event_id}`, 'memory-validity'));
  if (person) card.append(element('p', `${person.name} · private ${person.role.toLowerCase()} memory`, 'memory-owner'));
  const list = element('dl', null, 'memory-changes');
  const metadata = new Set(['order', 'basket', 'actor', 'sim_time', 'fact_sequence']);
  const appendChange = (change, target) => {
    const row = element('div', null, 'memory-change');
    row.append(element('dt', change.label));
    const value = element('dd');
    if (change.had_before && write.mode !== 'unknown') {
      value.append(element('span', memoryValue(change.before, change.field), 'memory-before'), element('span', ' → ', 'memory-arrow'));
    }
    value.append(element('span', change.has_after ? memoryValue(change.after, change.field) : 'Removed', 'memory-after'));
    row.append(value); target.append(row);
  };
  const secondary = change => metadata.has(change.field) || (['created', 'unknown'].includes(write.mode) && (change.field === 'action' || change.after === null));
  const visible = write.changes.filter(change => !secondary(change));
  if (write.mode === 'updated' && !visible.length) card.firstChild.textContent = 'Memory observation refreshed';
  visible.forEach(change => appendChange(change, list));
  if (visible.length) card.append(list);
  const extra = write.changes.filter(secondary);
  if (extra.length) {
    const details = element('details', null, 'memory-metadata');
    const values = element('dl', null, 'memory-changes');
    extra.forEach(change => appendChange(change, values));
    details.append(element('summary', 'Additional saved fields'), values); card.append(details);
  }
  card.append(element('p', `Observed ${formatHour(write.observed_sim)} · recall expires ${formatHour(write.expires_sim)}`, 'memory-validity'));
  return card;
}

function renderOrderHistory(data, box, refresh) {
  box.replaceChildren();
  const header = element('div', null, 'order-history-heading');
  header.append(element('p', `${data.order.id} · ${data.facts.length} facts · ${data.events.length} messages · ${data.decisions.length} decisions. Complete order history, independent of the map selection.`));
  const button = element('button', 'Refresh history'); button.type = 'button'; button.addEventListener('click', refresh);
  header.append(button); box.append(header);
  if (data.order.reason) box.append(element('p', data.order.reason, 'order-outcome'));
  const chat = element('section', null, 'order-section order-conversation');
  chat.append(element('h3', 'Order conversation'), element('p', 'Local simulation · named agents · simulation clock. Messages are readable renderings of recorded queue events; calls use the saved transcript.', 'conversation-note'));
  if (data.decisions.length && !data.memory_history_complete) {
    chat.append(element('p', 'This older run has incomplete memory history. Retained snapshots are shown where available; previous values were not recorded.', 'order-memory-note'));
  }
  const messages = element('ol', null, 'chat-thread');
  messages.setAttribute('aria-label', 'Recorded order conversation');
  const eventById = new Map(data.events.map(event => [event.id, event]));
  for (const message of data.conversation || []) {
    const item = element('li', null, `chat-message chat-${message.sender.kind}`);
    const avatar = element('span', message.sender.initials, 'chat-avatar'); avatar.setAttribute('aria-hidden', 'true');
    const bubble = element('article', null, 'chat-bubble');
    const heading = element('div', null, 'chat-heading');
    const sender = element('div', null, 'chat-person');
    sender.append(element('strong', message.sender.name), element('span', `${message.sender.role} · ${message.sender.entity}`));
    const time = element('time', `${message.time_kind === 'due' ? 'Due ' : ''}${formatHour(message.sim_time)}`, 'chat-time mono');
    time.title = message.time_kind === 'due' ? 'Scheduled queue delivery time; sent time was not recorded.' : 'Recorded simulation time when the sender queued this message.';
    heading.append(sender, time);
    bubble.append(heading, element('p', `To ${message.recipient.name} · ${message.recipient.entity}`, 'chat-recipient'), element('p', message.text, 'chat-text'));
    const receipt = element('div', null, 'chat-receipt');
    const waiting = ['ready', 'leased'].includes(message.state);
    const receiptText = message.processed_sim !== null ? `${message.recipient.name} processed ${formatHour(message.processed_sim)}` : message.state === 'done' ? 'Queue acknowledged · no agent decision recorded' : `${waiting ? 'Awaiting processing' : 'No successful processing recorded'} · due ${formatHour(message.due_sim)}`;
    receipt.append(stateBadge(message.state === 'done' ? 'processed' : message.state), element('span', receiptText));
    if (message.attempts > 1) receipt.append(element('span', `${message.attempts} attempts`));
    bubble.append(receipt);
    if (message.outcome.action || message.outcome.status) {
      const outcome = element('p', null, 'chat-outcome');
      outcome.append(element('strong', `${message.recipient.name}: `), document.createTextNode(readableAction(message.outcome.action || message.outcome.status)));
      if (message.outcome.status) outcome.append(document.createTextNode(' · '), stateBadge(message.outcome.status));
      bubble.append(outcome);
    }
    if (message.outcome.reason) bubble.append(element('p', message.outcome.reason, 'chat-reason'));
    const recordedError = eventById.get(message.event_id)?.error;
    if (recordedError) bubble.append(element('p', `Message processing error: ${recordedError}`, 'chat-reason'));
    for (const write of message.memory) bubble.append(memoryCard(write));
    const evidence = jsonDetails(`Queue evidence · #${message.event_id} · ${message.topic}`, eventById.get(message.event_id));
    evidence.classList.add('chat-evidence'); bubble.append(evidence);
    if (message.sender.kind === 'system') {
      const detail = element('details', null, 'chat-system-event');
      const summary = element('summary', `${formatHour(message.sim_time)} · ${message.sender.name} → ${message.recipient.name} · ${readableAction(message.topic)}`);
      detail.append(summary, bubble); item.append(avatar, detail);
    } else item.append(avatar, bubble);
    messages.append(item);
  }
  chat.append(messages);
  if (!messages.childNodes.length) chat.append(element('p', 'No messages recorded yet.'));
  box.append(chat);
  if (data.requests.length) {
    const ingredients = element('section', null, 'order-section');
    ingredients.append(element('h3', 'Ingredient requests · latest state'), table(['Ingredient', 'Quantity', 'Supermarket', 'Status'], data.requests.map(request => [request.ingredient, `${request.quantity} ${request.unit}`, entityName(request.market), stateBadge(request.status)])));
    box.append(ingredients);
  }
  const steps = element('section', null, 'order-section');
  steps.append(element('h3', 'All steps'));
  const decisions = new Map(data.decisions.map(decision => [decision.event_id, decision]));
  const factEvents = new Set(data.facts.map(fact => fact.event_id));
  const timeline = [
    ...data.facts.map(fact => ({sim: fact.sim_time, actor: fact.actor, title: fact.detail?.action || fact.kind, detail: fact.detail, sequence: fact.sequence, decision: decisions.get(fact.event_id)})),
    ...data.decisions.filter(decision => !factEvents.has(decision.event_id)).map(decision => ({sim: decision.sim_time, actor: decision.agent, title: decision.action, detail: decision.detail, decision, sequence: Number.MAX_SAFE_INTEGER})),
  ].sort((a, b) => a.sim - b.sim || a.sequence - b.sequence);
  for (const step of timeline) {
    const record = element('article', null, 'record order-step');
    const heading = element('div', null, 'record-head');
    heading.append(element('time', formatHour(step.sim), 'mono'), element('strong', readableAction(step.title)));
    record.append(heading, element('p', actorName(step.actor)));
    if (step.detail?.reason) record.append(element('p', step.detail.reason));
    if (step.decision?.detail?.rule) record.append(element('p', step.decision.detail.rule));
    record.append(jsonDetails('Recorded state and decision', {step: step.detail, decision: step.decision?.detail}));
    steps.append(record);
  }
  if (!timeline.length) steps.append(element('p', 'No steps recorded yet. This order may still be scheduled.'));
  box.append(steps);
  const memory = element('section', null, 'order-section');
  memory.append(element('h3', 'Agent memory'));
  memory.append(element('p', 'Each card belongs to the receiving agent. Operator inspection does not grant other agents access to this memory.'));
  const writes = (data.conversation || []).flatMap(message => message.memory.map(write => ({...write, person: message.recipient}))).sort((a, b) => a.observed_sim - b.observed_sim);
  for (const write of writes) memory.append(memoryCard(write, write.person));
  if (!writes.length) memory.append(element('p', data.decisions.length ? 'No retained memory writes are available for this order.' : 'No agent has written memory for this order yet.'));
  const recalled = element('details', null, 'memory-recall-audit');
  recalled.append(element('summary', 'What agents recalled for this order'));
  const people = new Map((data.conversation || []).map(message => [message.event_id, message.recipient]));
  const factsById = new Map((data.typed_memory || []).map(fact => [fact.id, fact]));
  for (const decision of data.decisions) {
    for (const read of decision.detail.memory_reads || []) {
      const item = element('article', null, 'record');
      const person = people.get(decision.event_id);
      item.append(element('p', `${formatHour(decision.sim_time)} · ${person?.name || actorName(decision.agent)} · ${read.facts.length} relevant fact(s)`));
      for (const fact of read.facts) {
        const saved = factsById.get(fact.fact_id);
        item.append(element('p', `${readableAction(fact.kind)} · revision ${fact.version} · source event #${fact.event_id} · expires ${formatHour(fact.expires_sim)}`, 'memory-validity'));
        if (saved) item.append(statList(Object.entries(saved.body).map(([key, value]) => [readableAction(key), memoryValue(value, key)])));
      }
      if (!read.facts.length) item.append(element('p', 'No live matching facts. Other orders, roles, expired values and older revisions are excluded.'));
      recalled.append(item);
    }
  }
  if (recalled.childNodes.length === 1) recalled.append(element('p', 'This run predates typed recall auditing.'));
  memory.append(recalled);
  box.append(memory);
  const navigation = element('nav', null, 'order-history-navigation');
  navigation.setAttribute('aria-label', 'Order history sections');
  for (const [label, section] of [['Conversation', chat], ['All steps', steps], ['Agent memory', memory]]) {
    const link = element('button', label);
    link.type = 'button';
    link.addEventListener('click', () => section.scrollIntoView({block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'}));
    navigation.append(link);
  }
  header.append(navigation);
}

function renderEvidence() {
  const ids = selectedOrderIds();
  const orders = snapshot?.orders || [];
  const messages = (snapshot?.events || []).filter(event => related(event, ids));
  const facts = (snapshot?.facts || []).filter(fact => related(fact, ids));
  $('order-count').textContent = orders.length;
  $('message-count').textContent = messages.length;
  $('fact-count').textContent = facts.length;
  renderOrderBook();
  $('messages-panel').replaceChildren();
  $('facts-panel').replaceChildren();
  const emptyText = snapshot ? 'No records for this selection. Clear “Selected entity only” to inspect the full run.' : 'Start a simulation to watch household calls create orders and ingredient requests.';
  if (messages.length) {
    for (const event of messages.slice(-150).reverse()) {
      const record = element('article', null, 'record');
      const heading = element('div', null, 'record-head');
      heading.append(element('strong', event.topic), stateBadge(event.state), element('span', `Due ${formatHour(event.due_sim)} · ${event.id}`, 'mono'));
      record.append(heading, element('p', `${entityName(event.producer)} → ${entityName(event.target_store)}`), element('p', `Trace ${event.trace_id || '—'} · simulated local message`, 'subtle'), jsonDetails('Message payload', event.payload || {}));
      $('messages-panel').append(record);
    }
    if (messages.length > 150) $('messages-panel').append(element('p', 'Showing the newest 150 messages. Download JSON for the complete run.', 'scope-note'));
  } else $('messages-panel').append(element('p', emptyText, 'empty'));
  if (facts.length) {
    for (const fact of facts.slice(-150).reverse()) {
      const record = element('article', null, 'record');
      const heading = element('div', null, 'record-head');
      heading.append(element('span', `#${fact.sequence}`, 'mono'), element('strong', fact.kind), element('span', formatHour(fact.sim_time), 'mono'));
      record.append(heading, element('p', `${entityName(fact.actor)}${fact.order_id ? ' · ' + fact.order_id : ''}`), jsonDetails('Fact, event trace & replay payload', fact));
      $('facts-panel').append(record);
    }
    if (facts.length > 150) $('facts-panel').append(element('p', 'Showing the newest 150 facts. Download JSON for the complete replay chain.', 'scope-note'));
  } else $('facts-panel').append(element('p', emptyText, 'empty'));
}

function renderInvariants() {
  const box = $('invariant-results'); box.replaceChildren();
  for (const [name, value] of Object.entries(snapshot?.invariants || {})) {
    const passed = value === true || value === 'ok' || value?.passed === true;
    const failed = value === false || value?.passed === false;
    box.append(element('span', `${name.replaceAll('_', ' ')}: ${typeof value === 'object' ? pretty(value) : value}`, `state ${passed ? 'good' : failed ? 'bad' : ''}`));
  }
  if (!box.childNodes.length) box.append(element('p', 'Stock conservation, nonnegative quantities, and run invariants appear here.', 'empty'));
}

async function verifyReplay() {
  if (!runId || running()) return;
  $('check-replay').disabled = true;
  $('replay-state').textContent = 'Replaying persisted facts…';
  try {
    replay = await api(`/api/supply/runs/${encodeURIComponent(runId)}/replay`);
    $('replay-state').textContent = replay.matches ? 'Replay matches persisted stock and orders.' : 'Replay mismatch. Inspect the detailed comparison below.';
    $('replay-state').style.color = replay.matches ? 'var(--green)' : 'var(--red)';
    $('replay-result').textContent = pretty(replay);
    $('replay-result').hidden = false;
  } catch (error) { showError(error); $('replay-state').textContent = 'Replay could not be verified.'; }
  finally { updateButtons(); }
}

function activateTab(tab, row) {
  if (row.classList.contains('evidence-tabs')) $('entity-filter-control').hidden = tab.id === 'orders-tab';
  const tabs = [...row.querySelectorAll('[role=tab]')];
  for (const item of tabs) {
    const selected = item === tab;
    item.setAttribute('aria-selected', selected);
    item.tabIndex = selected ? 0 : -1;
    $(item.getAttribute('aria-controls')).hidden = !selected;
  }
  if (tab.id === 'inspection-tab') renderInspection();
  if (tab.id === 'definition-tab' && currentEntity()) renderEntityHeading(currentEntity());
}

for (const row of document.querySelectorAll('[role=tablist]')) {
  row.addEventListener('click', event => { const tab = event.target.closest('[role=tab]'); if (tab) activateTab(tab, row); });
  row.addEventListener('keydown', event => {
    const tabs = [...row.querySelectorAll('[role=tab]')];
    const index = tabs.indexOf(document.activeElement);
    if (index < 0 || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    activateTab(tabs[next], row); tabs[next].focus();
  });
}

$('settings-form').addEventListener('submit', event => event.preventDefault());
$('settings-form').addEventListener('input', () => { if (draft) markDirty(); });
$('playback-control').addEventListener('input', () => { if (draft) markDirty(); });
$('entity-form').addEventListener('submit', event => event.preventDefault());
$('entity-form').addEventListener('input', event => { if (draft && event.target.id !== 'agent-scope') { editorDirty = true; markDirty(); } });
$('agent-scope').addEventListener('change', () => {
  const next = $('agent-scope').value;
  if (!captureEditor()) { $('agent-scope').value = agentEditScope; return; }
  const entity = currentEntity();
  if (next === 'entity' && !entity.agent) { entity.agent = clone(draft.agents[entity.kind]); markDirty(); }
  if (next === 'inherit' && entity.agent) { entity.agent = null; markDirty(); }
  agentEditScope = next;
  renderAgentEditor();
  $('entity-json').value = pretty(entity);
});
$('agent-engine').addEventListener('change', () => {
  const next = $('agent-engine').value;
  if (!captureEditor()) return;
  const agent = agentDefinition();
  if (next === 'adk') {
    agent.brain = clone(agentTemplates['restaurant-v1'].brain);
    agent.limits.tool_calls_per_event = 16;
  } else agent.brain = null;
  markDirty(); renderAgentEditor();
});
$('agent-memory').addEventListener('change', syncMemoryFields);
$('adk-routing').addEventListener('change', syncRoutingFields);
$('load-adk-profile').addEventListener('click', () => {
  if (!captureEditor()) return;
  const agent = agentDefinition(), template = agentTemplates['restaurant-v1'];
  agent.soul = template.souls[$('adk-profile').value];
  agent.brain.instructions = template.brain.instructions;
  agent.display_name = $('adk-profile').value === 'cost' ? 'Mateo' : 'Elena';
  markDirty(); renderAgentEditor();
});
for (const id of ['entity-json', 'agent-json']) $(id).addEventListener('input', () => { jsonDirty = true; editorDirty = false; markDirty(); });
document.querySelector('.advanced').addEventListener('toggle', event => { if (event.target.open && editorDirty && !jsonDirty) captureEditor(); });
$('apply-json').addEventListener('click', () => applyAdvanced());
$('entity-select').addEventListener('change', () => selectEntity($('entity-select').value));
$('map-filter').addEventListener('change', () => drawMap(true));
$('entity-only').addEventListener('change', renderEvidence);
$('ingredient-search-form').addEventListener('submit', searchIngredients);
$('save-blueprint').addEventListener('click', saveBlueprint);
$('start-run').addEventListener('click', startRun);
$('check-replay').addEventListener('click', verifyReplay);
$('download-evidence').addEventListener('click', async () => {
  if (!snapshot) return;
  const requestedRun = snapshot.run.id;
  const button = $('download-evidence'); button.disabled = true; button.textContent = 'Preparing JSON…';
  try {
    const evidence = await api(`/api/supply/runs/${encodeURIComponent(requestedRun)}/evidence`);
    const url = URL.createObjectURL(new Blob([pretty(evidence)], {type: 'application/json'}));
    const link = element('a'); link.href = url; link.download = `restaurant-supply-${requestedRun}.json`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { showError(error); }
  finally { button.textContent = 'Download JSON'; updateButtons(); }
});
window.addEventListener('beforeunload', event => { if (draftDirty) { event.preventDefault(); event.returnValue = ''; } });

(async function initialize() {
  renderMetrics(); renderEvidence();
  requestAnimationFrame(animate);
  try {
    [blueprint, agentTemplates] = await Promise.all([api('/api/supply/blueprint'), api('/api/supply/agent-templates')]);
    draft = clone(blueprint.config);
    selectedId = draft.entities.find(entity => entity.kind === 'restaurant')?.id || draft.entities[0]?.id;
    agentEditScope = currentEntity()?.agent ? 'entity' : 'inherit';
    renderSettings(); renderEntityOptions(); renderEditor(); renderMetrics(); drawMap(true); updateButtons();
    runId = new URLSearchParams(location.search).get('run') || sessionStorage.getItem('supply-run-id');
    if (runId) await pollRun();
  } catch (error) { showError(error); $('map-empty').textContent = 'City unavailable. Check the local API error above.'; }
})();
