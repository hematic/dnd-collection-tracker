const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const { Script } = require('node:vm');

const source = readFileSync(join(__dirname, '../static/app.js'), 'utf8');
// Exercise the actual URL-state functions without booting the browser UI.
const script = new Script(source.slice(
  source.indexOf('const DEFAULTS ='),
  source.indexOf('// ---------------------------------------------------------------- filter UI'),
) + source.slice(
  source.indexOf('function queryParams()'),
  source.indexOf('async function reloadCollection()'),
) + '\n({ DEFAULTS, readHash, writeHash, queryParams, exportUrl, setState: next => { state = next; } });');

function urlState(hash = '', exportOptions = {}) {
  const location = { hash, pathname: '/' };
  const controls = {
    '#export-scope': { value: exportOptions.scope || 'all' },
    '#export-edition': { value: exportOptions.edition || '' },
  };
  const history = {
    replaceState(_state, _unused, url) {
      location.hash = new URL(url, 'http://localhost/').hash;
    },
  };
  return {
    ...script.runInNewContext({ URLSearchParams, location, history, $: selector => controls[selector] }),
    location,
  };
}

test('a URL without a sort direction uses the newest-first default', () => {
  const app = urlState();
  assert.equal(app.readHash().desc, true);
});

test('explicit ascending and descending bookmarks remain supported', () => {
  assert.equal(urlState('#desc=0').readHash().desc, false);
  assert.equal(urlState('#desc=1').readHash().desc, true);
});

test('companion shelf bookmarks and API filters preserve the ampersand and remain separate from Other', () => {
  const app = urlState();
  app.setState({ ...app.DEFAULTS, edition: ['D&D Companions'] });
  app.writeHash();
  const restored = urlState(app.location.hash);
  assert.deepEqual(Array.from(restored.readHash().edition), ['D&D Companions']);
  restored.setState(restored.readHash());
  const query = new URLSearchParams(restored.queryParams());
  assert.deepEqual(query.getAll('edition'), ['D&D Companions']);
});
test('both sort directions survive a saved URL round trip', () => {
  for (const sort of ['year', 'title', 'edition', 'type', 'code', 'publisher']) {
    for (const desc of [true, false]) {
      const app = urlState();
      app.setState({ ...app.DEFAULTS, sort, desc });
      app.writeHash();
      const restored = urlState(app.location.hash).readHash();
      assert.equal(restored.sort, sort);
      assert.equal(restored.desc, desc, `${sort}, descending=${desc}`);
    }
  }
});

test('publisher bookmarks preserve blank selections and free-text names', () => {
  for (const publisher of [[], [''], ['TSR', '', 'A&B | "Press"']]) {
    const app = urlState();
    app.setState({ ...app.DEFAULTS, publisher });
    app.writeHash();
    const restored = urlState(app.location.hash).readHash();
    assert.deepEqual(Array.from(restored.publisher), publisher);
  }
});

test('publisher API parameters preserve multiple selections without splitting names', () => {
  const app = urlState();
  const publisher = ['', 'TSR', 'A&B | "Press"'];
  app.setState({ ...app.DEFAULTS, publisher, edition: ['AD&D 1e'], owned: true });
  const params = app.queryParams();
  assert.deepEqual(params.getAll('publisher'), publisher);
  assert.equal(params.get('edition'), 'AD&D 1e');
  assert.equal(params.get('owned'), 'true');
});

test('missing PDF selection survives bookmarks and clears with default filters', () => {
  const app = urlState();
  assert.equal(app.readHash().no_pdf, false);
  app.setState({ ...app.DEFAULTS, no_pdf: true });
  app.writeHash();
  assert.equal(urlState(app.location.hash).readHash().no_pdf, true);
  assert.equal(app.queryParams().get('no_pdf'), 'true');
  app.setState({ ...app.DEFAULTS });
  app.writeHash();
  assert.equal(app.queryParams().has('no_pdf'), false);
  assert.equal(new URLSearchParams(app.location.hash.slice(1)).has('no_pdf'), false);
});

test('settings preserve multiple free-text selections and blanks in bookmarks and requests', () => {
  const app = urlState();
  const setting = ['Greyhawk', '', 'A&B | "Worlds"'];
  app.setState({ ...app.DEFAULTS, setting });
  app.writeHash();
  const restored = urlState(app.location.hash);
  assert.deepEqual(Array.from(restored.readHash().setting), setting);
  restored.setState(restored.readHash());
  assert.deepEqual(restored.queryParams().getAll('setting'), setting);
  restored.setState({ ...restored.DEFAULTS });
  restored.writeHash();
  assert.equal(restored.location.hash, '');
  assert.equal(restored.queryParams().has('setting'), false);
});

test('filtered export uses collection filters, not the separate export edition', () => {
  const app = urlState('', { scope: 'filtered', edition: 'Other' });
  app.setState({
    ...app.DEFAULTS,
    edition: ['AD&D 1e', 'AD&D 2e'], type: ['Sourcebook'], publisher: ['', 'A&B | "Press"'],
    setting: ['Greyhawk', ''],
    ymin: '1990', ymax: '1999', owned: true, no_pdf: true, q: 'Planescape',
    hide: ['Digital', 'Reprint'], sort: 'publisher', desc: false, all: true, contents: true,
  });
  const url = new URL(app.exportUrl(), 'http://localhost/');
  assert.equal(url.pathname, '/api/export-view.csv');
  const params = url.searchParams;
  assert.equal(params.get('edition'), 'AD&D 1e|AD&D 2e');
  assert.equal(params.get('type'), 'Sourcebook');
  assert.deepEqual(params.getAll('publisher'), ['', 'A&B | "Press"']);
  assert.deepEqual(params.getAll('setting'), ['Greyhawk', '']);
  assert.equal(params.get('year_min'), '1990');
  assert.equal(params.get('year_max'), '1999');
  assert.equal(params.get('owned'), 'true');
  assert.equal(params.get('no_pdf'), 'true');
  assert.equal(params.get('q'), 'Planescape');
  assert.equal(params.get('hide_kinds'), 'Digital|Reprint');
  assert.equal(params.get('sort'), 'publisher');
  assert.equal(params.get('desc'), 'false');
  assert.equal(params.get('all_releases'), 'true');
  assert.equal(params.get('contents'), 'true');
});

test('inventory export keeps its independent scope and edition', () => {
  for (const scope of ['all', 'missing', 'owned']) {
    const app = urlState('', { scope, edition: 'Other' });
    app.setState({ ...app.DEFAULTS, edition: ['AD&D 1e'], no_pdf: true, q: 'Planescape' });
    assert.equal(app.exportUrl(), `/api/export.csv?scope=${scope}&edition=Other`);
  }
});
