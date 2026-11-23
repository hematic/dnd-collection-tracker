const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const { Script } = require('node:vm');

const source = readFileSync(join(__dirname, '../static/app.js'), 'utf8');
const coverSource = source.slice(
  source.indexOf('// ---------------------------------------------------------------- cover size'),
  source.indexOf('// ---------------------------------------------------------------- data + render'),
);
const pollingSource = source.slice(
  source.indexOf('function bindPdfSearch()'),
  source.indexOf('// ---------------------------------------------------------------- cover size'),
);
const flush = () => new Promise(resolve => setImmediate(resolve));

test('companion shelves render separately after RPG editions and before Other with independent collapse state', () => {
  const shelfSource = readFileSync(join(__dirname, '../static/shelf.js'), 'utf8')
    .replace(/^export \{ esc \};$/m, '').replace(/^export /gm, '');
  const { renderShelves } = new Script(shelfSource + '\n({ renderShelves });').runInNewContext({
    getComputedStyle: () => ({ getPropertyValue: () => '128' }),
    document: { documentElement: {} },
  });
  const element = { clientWidth: 1000, innerHTML: '' };
  const editions = ['AD&D 1e', '5e (2024)', 'D&D Companions', 'Other'];
  renderShelves(element, editions.map((edition, index) => ({
    edition, title: edition === 'Other' ? 'Personal third-party guide' : 'Official companion',
    id: `release-${index}`, work_id: `work-${index}`, release_kind: 'Original', book_type: 'Other',
  })), { editions, showAll: false, grouped: true, collapsed: new Set(['D&D Companions']) });
  const position = edition => element.innerHTML.indexOf(`data-edition="${edition}"`);
  assert.ok(position('5e (2024)') < position('AD&amp;D 1e'));
  assert.ok(position('AD&amp;D 1e') < position('D&amp;D Companions'));
  assert.ok(position('D&amp;D Companions') < position('Other'));
  assert.match(element.innerHTML, /class="shelf collapsed" data-edition="D&amp;D Companions"/);
  assert.match(element.innerHTML, /class="shelf " data-edition="Other"/);
  assert.match(element.innerHTML, /Personal third-party guide/);
});

test('rapid cover-size changes render once per frame using the latest size', () => {
  const frames = new Map();
  const sizes = new Map();
  const slider = {};
  let renders = 0;
  const setCoverSize = new Script(coverSource + '\nsetCoverSize;').runInNewContext({
    document: { documentElement: { style: { setProperty: (key, value) => sizes.set(key, value) } } },
    $: () => slider,
    localStorage: { setItem() {} },
    books: [{}],
    state: { view: 'shelf' },
    render: () => { renders += 1; },
    requestAnimationFrame: callback => {
      frames.set(frames.size + 1, callback);
      return frames.size;
    },
  });
  for (const size of [180, 220, 260]) setCoverSize(size);
  assert.equal(renders, 0);
  assert.equal(frames.size, 1);
  assert.equal(sizes.get('--cover-w'), '260px');
  assert.equal(slider.value, 260);
  frames.values().next().value();
  assert.equal(renders, 1);
});

function polling(status) {
  const timers = new Map();
  const elements = new Map();
  const listeners = new Map();
  let nextTimer = 0;
  let requests = 0;
  let getStatus = () => Promise.resolve(status);
  const document = {
    hidden: false,
    body: { classList: { toggle() {} } },
    addEventListener: (name, handler) => listeners.set(name, handler),
  };
  const $ = selector => {
    if (!elements.has(selector)) {
      elements.set(selector, {
        open: false,
        classList: { remove() {} },
        setAttribute() {},
        addEventListener() {},
      });
    }
    return elements.get(selector);
  };
  const schedule = (callback, delay) => {
    const id = ++nextTimer;
    timers.set(id, { callback, delay });
    return id;
  };
  const app = new Script(`
    let state = { page: 'pdf-search' };
    let meta = { can_edit: true };
    let pdfSearchPoll = null;
    let pdfIndexRefreshing = false;
    let pdfIndexRefreshPending = false;
    ${pollingSource}
    ({ bindPdfSearch, setActivePage, refreshPdfIndexStatus });
  `).runInNewContext({
    $, document,
    writeHash() {},
    esc: value => value,
    api: { pdfIndexStatus: () => { requests += 1; return getStatus(); } },
    setTimeout: schedule,
    setInterval: schedule,
    clearTimeout: id => timers.delete(id),
    clearInterval: id => timers.delete(id),
  });
  return {
    ...app, timers, document, listeners, elements,
    requests: () => requests,
    setResponse: handler => { getStatus = handler; },
  };
}

const idleStatus = {
  linked: 1, done: 1, queued: 0, processing: 0, not_indexed: 0, error: 0,
  ocr_books: 0, ocr_pages: 0, ocr_unrecorded: 0, failures: [],
  worker_online: true, paused: false,
};

test('PDF status polling slows down when idle and waits for each response', async () => {
  const app = polling({ ...idleStatus, done: 0, queued: 1 });
  app.setActivePage('pdf-search');
  await flush();
  assert.equal(app.timers.size, 1);
  const [id, activeTimer] = [...app.timers][0];
  app.timers.delete(id);
  app.setResponse(() => Promise.resolve(idleStatus));
  await activeTimer.callback();
  assert.equal(app.timers.size, 1);
  const idleTimer = [...app.timers.values()][0];
  assert.ok(activeTimer.delay <= 2500);
  assert.ok(idleTimer.delay >= 10000);
});

test('hidden tabs stop polling and resume immediately when visible', async () => {
  const app = polling(idleStatus);
  app.bindPdfSearch();
  app.setActivePage('pdf-search');
  await flush();
  app.document.hidden = true;
  app.listeners.get('visibilitychange')();
  assert.equal(app.timers.size, 0);
  const requests = app.requests();
  await app.refreshPdfIndexStatus();
  assert.equal(app.requests(), requests);
  app.document.hidden = false;
  app.listeners.get('visibilitychange')();
  await flush();
  assert.equal(app.requests(), requests + 1);
  assert.equal(app.timers.size, 1);
  app.setActivePage('collection');
  assert.equal(app.timers.size, 0);
  app.listeners.get('visibilitychange')();
  await flush();
  assert.equal(app.requests(), requests + 1);
});

test('slow PDF status requests do not overlap or accumulate timers', async () => {
  const app = polling(idleStatus);
  let finish;
  const pending = new Promise(resolve => { finish = resolve; });
  app.setResponse(() => pending);
  const first = app.refreshPdfIndexStatus();
  app.refreshPdfIndexStatus();
  assert.equal(app.requests(), 1);
  assert.equal(app.timers.size, 0);
  finish(idleStatus);
  await first;
  assert.equal(app.timers.size, 1);
  const timer = [...app.timers.values()][0];
  assert.equal(timer.delay, 0);
});

test('paused and offline queues use the slower polling interval', async () => {
  for (const change of [{ paused: true }, { worker_online: false }]) {
    const app = polling({ ...idleStatus, done: 0, queued: 1, ...change });
    await app.refreshPdfIndexStatus();
    assert.equal(app.timers.size, 1);
    assert.ok([...app.timers.values()][0].delay >= 10000);
  }
});

test('status failures remain visible and recover on the next poll', async () => {
  const app = polling(idleStatus);
  app.setResponse(() => Promise.reject(new Error('Server unavailable')));
  await app.refreshPdfIndexStatus();
  assert.match(app.elements.get('#pdf-index-status').textContent, /Server unavailable/);
  const [id, timer] = [...app.timers][0];
  app.timers.delete(id);
  app.setResponse(() => Promise.resolve({ ...idleStatus, done: 0, queued: 1 }));
  await timer.callback();
  assert.equal(app.requests(), 2);
  assert.equal(app.timers.size, 1);
  assert.ok([...app.timers.values()][0].delay <= 2500);
});

test('index progress, current PDF, OCR totals and failures are reported separately', async () => {
  const app = polling({
    ...idleStatus, linked: 12, done: 8, queued: 2, processing: 1, error: 1,
    ocr_books: 6, ocr_pages: 42, ocr_unrecorded: 1,
    current: { title: 'Sample bestiary', indexed_pages: 12, page_count: 20, ocr_pages: 3 },
    failures: [{ title: 'Sample adventure', error: 'PDF not found', release_id: 'failed' }],
  });
  await app.refreshPdfIndexStatus();
  const element = id => app.elements.get(`#pdf-index-${id}`);
  assert.equal(element('status').textContent, '8 of 12 linked PDFs indexed');
  assert.equal(element('progress').value, 8);
  assert.equal(element('progress').max, 12);
  assert.equal(element('current-title').textContent, 'Sample bestiary');
  assert.match(element('current-pages').textContent, /12 of 20 pages.*3 OCRed/);
  assert.match(element('metrics').innerHTML, /<li>2 queued<\/li>.*<li>OCR: 6 PDFs, 42 pages<\/li>/);
  assert.equal(element('issues').hidden, false);
  assert.equal(element('issues-label').textContent, 'Indexing failures (1)');
  assert.match(element('failures').innerHTML, /data-retry-pdf="failed"/);

  app.setResponse(() => Promise.resolve(idleStatus));
  await app.refreshPdfIndexStatus();
  assert.equal(element('current').hidden, true);
  assert.equal(element('issues').hidden, true);
});
