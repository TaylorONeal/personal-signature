// Optional browser-only development check. No personal data or HTTP server required.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');

(async () => {
  const browser = await chromium.launch();
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'corpus-deck-test-'));
  try {
    const context = await browser.newContext({ offline: true, viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const errors = [];
    const remote = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    page.on('request', request => { if (/^https?:/.test(request.url())) remote.push(request.url()); });
    await page.goto(pathToFileURL(path.resolve('docs/deck.html')).href);
    await page.evaluate(() => document.fonts.ready);
    assert.equal(await page.locator('main > section').count(), 125);
    assert.equal(await page.locator('#status').textContent(), '1 / 125');
    await page.getByRole('button', { name: 'Next slide', exact: true }).click();
    assert.equal(await page.locator('#status').textContent(), '2 / 125');
    await page.keyboard.press('End');
    assert.equal(await page.locator('#status').textContent(), '125 / 125');
    await page.keyboard.press('Home');
    await page.keyboard.press('t');
    assert.equal(await page.locator('#slide-list button').count(), 125);
    await page.locator('#slide-list button').nth(64).click();
    assert.equal(await page.locator('#status').textContent(), '65 / 125');
    await page.reload();
    assert.equal(await page.locator('#status').textContent(), '65 / 125');
    assert.match(await page.locator('section:not([hidden])').textContent(), /late arrivals/);
    // Check clipping on every slide at its native design size, after fonts load.
    const overflow = await page.evaluate(() => {
      const result = [];
      for (const slide of document.querySelectorAll('main > section')) {
        const hidden = slide.hidden;
        slide.hidden = false;
        if (slide.scrollHeight > slide.clientHeight + 2 || slide.scrollWidth > slide.clientWidth + 2) result.push(slide.dataset.label);
        slide.hidden = hidden;
      }
      return result;
    });
    assert.deepEqual(overflow, [], `Slides overflow: ${overflow.join(', ')}`);
    for (const viewport of [{width: 1440, height: 900}, {width: 390, height: 844}]) {
      await page.setViewportSize(viewport);
      await page.waitForFunction(() => {
        const r = document.querySelector('main').getBoundingClientRect();
        return r.left >= -1 && r.right <= innerWidth + 1 && r.top >= 55 && r.bottom <= innerHeight + 1;
      });
    }
    await page.emulateMedia({ media: 'print' });
    assert.equal(await page.locator('main > section:visible').count(), 125);
    assert.equal(await page.locator('section[data-label="Delta mode"]').evaluate(e => getComputedStyle(e).display), 'grid');
    const pdf = await page.pdf({ path: path.join(temp, 'deck.pdf'), preferCSSPageSize: true, printBackground: true });
    assert.equal((pdf.toString('latin1').match(/\/Type\s*\/Page\b/g) || []).length, 125);
    assert.deepEqual(remote, [], 'Deck must not request external resources');
    assert.deepEqual(errors, [], 'Browser errors');
    await context.close();
    console.log('Deck passed: 125 slides, offline, keyboard/list navigation, mobile fit, no overflow, 125 PDF pages, no browser errors.');
  } finally {
    await browser.close();
    fs.rmSync(temp, { recursive: true, force: true }); // Only this test's private temp directory.
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
