/** Read-only, headless browser contract checks. No simulation writes or provider calls. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const base = process.env.ANATOMY_URL || 'http://localhost:8010';
const out = '.impeccable/review';
(async () => {
  await fs.mkdir(out, {recursive:true});
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + '/architecture');
    await page.locator('.anatomy-identity h2').waitFor();
    assert.equal(await page.locator('#chapter-title').innerText(), 'Meet the agents');
    const data = await (await page.request.get(base + '/api/agent-anatomy')).json();
    assert.equal(await page.locator('.team-agent').count(), data.agents.length);
    let panels = 0;
    for (const agent of data.agents) {
      await page.locator(`.team-agent[data-agent="${agent.id}"]`).click();
      assert.equal(await page.locator('.anatomy-identity h2').innerText(), agent.name);
      for (const panel of agent.panels) {
        await page.locator('#anatomy-part-select').selectOption(panel.id);
        assert.equal(await page.locator('#anatomy-panel-title').innerText(), panel.title);
        assert.equal(await page.locator('.anatomy-summary').innerText(), panel.summary);
        assert.equal(await page.locator('.anatomy-sources a[data-source]').count(), panel.sources.length);
        assert.equal(await page.locator('.anatomy-illustration [aria-pressed="true"]').getAttribute('data-part'), panel.id);
        panels++;
      }
    }
    await page.locator('.team-agent[data-agent="restaurant"]').click();
    const engine = page.locator('.anatomy-illustration [data-part="model"]');
    await engine.focus(); await page.keyboard.press('Enter');
    assert.equal(await page.locator('#anatomy-panel-title').innerText(), 'Model & routing');
    await page.keyboard.press('ArrowRight');
    assert.notEqual(await page.evaluate(() => document.activeElement.dataset.part), 'model');
    await page.keyboard.press('Space');
    assert.equal(await page.locator('#anatomy-panel-title').innerText(), 'A2A & MCP');
    await page.getByText('Inspect the generated Agent Card', {exact:true}).click();
    assert.match(await page.locator('.anatomy-card pre').innerText(), /supportedInterfaces/);
    await page.locator('.anatomy-sources a[data-source]').first().click();
    await page.locator('#source-dialog[open]').waitFor();
    await page.waitForFunction(() => document.querySelector('#source-code').textContent.length > 0);
    assert.match(await page.locator('#source-code').innerText(), /A2A/);
    await page.keyboard.press('Escape');
    await page.getByText('Read the handoffs as text', {exact:true}).click();
    assert((await page.locator('.anatomy-edge-list li').count()) > 0);
    await page.getByText('Read the handoffs as text', {exact:true}).click();
    await page.getByRole('button', {name:'Replay handoffs',exact:true}).click();
    assert.equal(await page.locator('.team-wire.connected').first().evaluate(el => getComputedStyle(el).animationName), 'none');
    assert.equal(await page.locator('.team-wire.event.connected').first().evaluate(el => getComputedStyle(el).strokeDasharray), 'none');
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.getByRole('button', {name:'Replay handoffs',exact:true}).click();
    await page.waitForFunction(() => document.querySelector('.anatomy-connections').classList.contains('playing'));
    assert.equal(await page.locator('.team-wire.connected').first().evaluate(el => getComputedStyle(el).animationIterationCount), '4');
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.locator('#anatomy-part-select').selectOption('mission');
    const sizes = [['desktop',1440,1000],['mobile',390,844],['user-1916',1916,1244]];
    const captures = [];
    for (const [name,width,height] of sizes) {
      await page.setViewportSize({width,height});
      await page.evaluate(() => {document.activeElement?.blur();scrollTo(0,0);});
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${name}: no page overflow`);
      // Every path lands in the centre of its role column, including wide screens.
      const maxOffset = await page.evaluate(() => {
        const graph = document.querySelector('.anatomy-connections');
        return Math.max(...[...graph.querySelectorAll('path')].map(path => {
          const point = path.getPointAtLength(path.getTotalLength()).matrixTransform(graph.getScreenCTM());
          const box = document.querySelector(`[data-agent="${path.dataset.to}"]`).getBoundingClientRect();
          return Math.abs(point.x - (box.left + box.width / 2));
        }));
      });
      assert(maxOffset < 2, `${name}: handoffs align with agent columns (${maxOffset})`);
      await page.screenshot({path:`${out}/${name}.png`,fullPage:true});
      await page.screenshot({path:`${out}/${name}-viewport.png`});
      captures.push({name,width,height});
    }
    await page.setViewportSize({width:390,height:844});
    await page.locator('#anatomy-part-select').selectOption('evals');
    await page.locator('#anatomy-inspector').evaluate(el => scrollTo(0, el.getBoundingClientRect().top + scrollY - 145));
    await page.screenshot({path:`${out}/mobile-evals.png`});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    // A failed read has a usable retry and never produces an empty diagram.
    await page.route('**/api/agent-anatomy', route => route.fulfill({status:503,body:'Unavailable'}));
    await page.goto(base + '/architecture');
    await page.getByRole('button',{name:'Retry agent definitions'}).waitFor();
    await page.unroute('**/api/agent-anatomy');
    await page.getByRole('button',{name:'Retry agent definitions'}).click();
    await page.locator('.anatomy-identity h2').waitFor();
    assert.deepEqual(errors, []);
    const result = {checked_at:new Date().toISOString(),agents:data.agents.length,panels,
      keyboard:true,source_dialog:true,card:true,finite_animation:true,reduced_motion:true,
      retry:true,aligned_handoffs:true,no_horizontal_page_overflow:true,captures};
    await fs.writeFile(`${out}/anatomy-checks.json`, JSON.stringify(result,null,2));
    console.log(JSON.stringify(result,null,2));
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
