/** Reproducible browser evidence. Run with Node >=20 after npm ci + playwright install. */
const { chromium } = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const args = process.argv.slice(2);
const option = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback;
const base = option('--url', 'http://127.0.0.1:8021').replace(/\/$/, '');
const phase = option('--phase', 'after');
if (!/^[a-z0-9-]+$/.test(phase)) throw Error('Use a simple phase name, such as before or after.');
const out = path.resolve(option('--out', 'docs/media/' + phase));
const pages = [
  ['flow', '/delivery-lab', '#city[data-node-count]'],
  ['supply', '/restaurant-lab', '#city-map'],
  ['lab', '/lab', '#city'],
  ['health', '/health', '#main'],
  ['agent-traces', '/agent-traces', '#traces'],
  ['documentation', '/architecture', '#document:not([hidden])'],
  ['madrid', '/', '#map'],
];
const sizes = [['desktop', 1440, 960], ['laptop', 1280, 800], ['mobile', 390, 844]];
let browser;
(async () => {
  await fs.mkdir(out, {recursive:true});
  browser = await chromium.launch({headless:true});
  const context = await browser.newContext({reducedMotion:'reduce', locale:'en-GB'});
  const results = [];
  for (const [name, route, ready] of pages) {
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.setViewportSize({width:1440, height:960});
    const response = await page.goto(base + route, {waitUntil:'domcontentloaded'});
    await page.waitForSelector(ready, {state:'attached', timeout:30000});
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(1500);
    for (const [size, width, height] of sizes) {
      await page.setViewportSize({width,height});
      await page.waitForTimeout(250);
      await page.evaluate(() => window.scrollTo(0,0));
      await page.screenshot({path:path.join(out, name+'-'+size+'.png'),fullPage:true});
      if (size === 'desktop') await page.screenshot({path:path.join(out,name+'-viewport.png')});
      const audit = await page.evaluate(() => ({
        horizontalOverflow:document.documentElement.scrollWidth > innerWidth,
        width:innerWidth,
        title:document.title,
        heading:document.querySelector('h1')?.textContent?.trim(),
        unlabeledControls:[...document.querySelectorAll('input:not([type=hidden]),select,textarea,button')].filter(el => !el.hidden && el.getClientRects().length && !el.textContent.trim() && !el.labels?.length && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby') && !el.title).map(el=>el.id||el.outerHTML.slice(0,100)),
      }));
      results.push({page:name, route, size, status:response.status(), ...audit, errors:[...errors]});
    }
    console.log('Captured '+name+': desktop, laptop, mobile');
    await page.close();
  }
  await fs.writeFile(path.join(out,'report.json'),JSON.stringify({base,phase,capturedAt:new Date().toISOString(),results},null,2)+'\n');
  await browser.close();
  if (args.includes('--check') && results.some(r=>r.status!==200 || r.horizontalOverflow || r.errors.length || r.unlabeledControls.length)) process.exitCode=1;
})().catch(async error => {console.error(error);await browser?.close();process.exitCode=1;});
