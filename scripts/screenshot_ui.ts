/** Reproducible browser evidence. Run with Node >=20 after npm ci + playwright install. */
const { chromium } = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const args = process.argv.slice(2);
const option = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback;
const base = option('--url', 'http://127.0.0.1:8021').replace(/\/$/, '');
const phase = option('--phase', 'after');
if (args.includes('--help')) {
  console.log('Usage: node scripts/screenshot_ui.ts [--url URL] [--phase NAME] [--out PATH] [--only flow,supply,lab,health,agent-traces,documentation,madrid] [--width N --height N] [--runs JSON_FILE] [--trace-source delivery --trace-agent AGENT_ID] [--check]');
  process.exit(0);
}
if (!/^[a-z0-9-]+$/.test(phase)) throw Error('Use a simple phase name, such as before or after.');
const out = path.resolve(option('--out', 'docs/media/' + phase));
const catalogue = [
  ['flow', '/delivery-lab', '#city[data-node-count]'],
  ['supply', '/restaurant-lab', '#city-map'],
  ['lab', '/lab', '#city'],
  ['health', '/health', '#main'],
  ['agent-traces', '/agent-traces', '#traces'],
  ['documentation', '/architecture', '#document:not([hidden])'],
  ['madrid', '/', '#map'],
];
const requested = option('--only', '').split(',').filter(Boolean);
for (const name of requested) {
  if (!catalogue.some(([key]) => key === name)) throw Error('Unknown page: ' + name);
}
const pages = catalogue.filter(([name]) => !requested.length || requested.includes(name));
const customWidth = Number(option('--width', '0'));
const customHeight = Number(option('--height', '0'));
if ((customWidth || customHeight) && (!Number.isInteger(customWidth) || !Number.isInteger(customHeight) || customWidth < 320 || customHeight < 320 || customWidth > 3840 || customHeight > 2160)) {
  throw Error('Custom --width and --height must both be integers within 320–3840 × 320–2160.');
}
const sizes = customWidth
  ? [['custom', customWidth, customHeight]]
  : [['desktop', 1440, 960], ['laptop', 1280, 800], ['mobile', 390, 844]];
let browser;
(async () => {
  await fs.mkdir(out, {recursive:true});
  browser = await chromium.launch({headless:true});
  const context = await browser.newContext({reducedMotion:'reduce', locale:'en-GB'});
  const results = [];
  const runsPath = option('--runs', '');
  const runs = runsPath ? JSON.parse(await fs.readFile(runsPath, 'utf8')) : {};
  for (const [name, id] of Object.entries(runs)) {
    if (!catalogue.some(([key]) => key === name) || typeof id !== 'string' || !id.trim()) {
      throw Error('Run assignments must map known page names to nonempty run IDs.');
    }
  }
  for (const [name, route, ready] of pages) {
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.setViewportSize({width:sizes[0][1], height:sizes[0][2]});
    const target = new URL(base + route);
    if (runs[name]) target.searchParams.set('run', runs[name]);
    if (name === 'agent-traces' && option('--trace-agent','')) {
      target.searchParams.set('source',option('--trace-source','delivery'));
      target.searchParams.set('agent',option('--trace-agent',''));
    }
    const response = await page.goto(target.href, {waitUntil:'domcontentloaded'});
    await page.waitForSelector(ready, {state:'attached', timeout:30000});
    await page.evaluate(() => document.fonts.ready);
    if(name==="health")await page.waitForFunction(()=>!document.getElementById("provenance").textContent.includes("Loading local"),null,{timeout:60000});
    if(name==="agent-traces" && option("--trace-agent",""))await page.waitForSelector("#live-timeline .timeline-step",{timeout:30000});
    if (name === "madrid") await page.waitForFunction(()=>document.getElementById("map").dataset.basemap==="ready",{},{timeout:30000});
    await page.waitForTimeout(1500);
    for (const [size, width, height] of sizes) {
      await page.setViewportSize({width,height});
      await page.waitForTimeout(250);
      await page.evaluate(() => window.scrollTo(0,0));
      await page.screenshot({path:path.join(out, name+'-'+size+'.png'),fullPage:true});
      if (size === 'desktop' || size === 'custom') await page.screenshot({path:path.join(out,name+'-viewport.png')});
      const audit = await page.evaluate(() => ({
        horizontalOverflow:document.documentElement.scrollWidth > innerWidth,
        width:innerWidth,
        title:document.title,
        heading:document.querySelector('h1')?.textContent?.trim(),
        unlabeledControls:[...document.querySelectorAll('input:not([type=hidden]),select,textarea,button')].filter(el => !el.hidden && el.getClientRects().length && !el.textContent.trim() && !el.labels?.length && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby') && !el.title).map(el=>el.id||el.outerHTML.slice(0,100)),
      }));
      results.push({page:name, route, run:runs[name] || null, size, status:response.status(), ...audit, errors:[...errors]});
    }
    console.log('Captured '+name+': '+sizes.map(([size])=>size).join(', '));
    await page.close();
  }
  await fs.writeFile(path.join(out,'report.json'),JSON.stringify({base,phase,capturedAt:new Date().toISOString(),results},null,2)+'\n');
  await browser.close();
  if (args.includes('--check') && results.some(r=>r.status!==200 || r.horizontalOverflow || r.errors.length || r.unlabeledControls.length)) process.exitCode=1;
})().catch(async error => {console.error(error);await browser?.close();process.exitCode=1;});
