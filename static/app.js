// App state, filter UI, URL-hash persistence and view switching.
import { api } from './api.js';
import { EDITION_COLORS, booksPerRow, esc, renderGrid, renderShelves, renderTable } from './shelf.js';
import { initDetail, openDrawer, workForm } from './detail.js';
import { clickItem, initSelect, isSelecting, paint } from './select.js';

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const THEME_KEY = 'theme';

function preferredTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch { /* use system preference */ }
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function syncThemeButton() {
  const current = document.documentElement.dataset.theme
    || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const next = current === 'dark' ? 'light' : 'dark';
  const label = `Switch to ${next} theme`;
  $('#toggle-theme').textContent = next === 'dark' ? '☾ Dark' : '☀ Light';
  $('#toggle-theme').setAttribute('aria-label', label);
  $('#toggle-theme').title = label;
}

const savedTheme = (() => {
  try { return localStorage.getItem(THEME_KEY); } catch { return null; }
})();
if (savedTheme === 'light' || savedTheme === 'dark') {
  document.documentElement.dataset.theme = savedTheme;
}

const DEFAULTS = {
  page: 'collection', view: 'shelf', sort: 'year', desc: true, grouped: true, all: false, contents: false,
  hide: [], edition: [], type: [], setting: [], publisher: [], ymin: '', ymax: '', owned: false, not_physically_owned: false, pdf: false, no_pdf: false, q: '',
};
let state = { ...DEFAULTS };
let meta = null;
let books = [];
let collapsed = new Set();
const PDF_SEARCH_PAGE_SIZE = 30;
let pdfSearchQuery = '';
let pdfSearchOffset = 0;
let pdfSearchRevision = 0;
const pdfSearchGroups = new Map();
let pdfSearchPoll = null;
let pdfIndexRefreshing = false;
let pdfIndexRefreshPending = false;
let pdfSearchMatch = 'all';
try { collapsed = new Set(JSON.parse(localStorage.getItem('collapsedShelves') || '[]')); } catch { /* storage unavailable */ }

// ---------------------------------------------------------------- URL hash <-> state

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  const s = { ...DEFAULTS };
  const list = (k) => (p.get(k) ? p.get(k).split('|').filter(Boolean) : []);
  const bool = (k, d) => (p.has(k) ? p.get(k) === '1' : d);
  if (p.get('page') === 'pdf-search') s.page = 'pdf-search';
  if (p.get('view')) s.view = p.get('view');
  if (p.get('sort')) s.sort = p.get('sort');
  s.desc = bool('desc', DEFAULTS.desc);
  s.grouped = bool('grouped', true);
  s.all = bool('all', false);
  s.contents = bool('contents', false);
  s.owned = bool('owned', false);
  s.not_physically_owned = bool('not_physically_owned', false);
  s.pdf = bool('pdf', false);
  s.no_pdf = bool('no_pdf', false);
  s.hide = list('hide');
  s.edition = list('edition');
  s.type = list('type');
  s.setting = p.getAll('setting');
  s.publisher = p.getAll('publisher');
  s.ymin = p.get('ymin') || '';
  s.ymax = p.get('ymax') || '';
  s.q = p.get('q') || '';
  return s;
}

function writeHash() {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(state)) {
    const d = DEFAULTS[k];
    if (Array.isArray(v)) {
      // Free-text names may contain pipes; repeated parameters also preserve blanks.
      if (k === 'publisher' || k === 'setting') v.forEach(value => p.append(k, value));
      else if (v.length) p.set(k, v.join('|'));
    }
    else if (typeof v === 'boolean') { if (v !== d) p.set(k, v ? '1' : '0'); }
    else if (v !== d && v !== '') p.set(k, v);
  }
  const h = p.toString();
  history.replaceState(null, '', h ? '#' + h : location.pathname);
}

// ---------------------------------------------------------------- filter UI

function buildChecklists() {
  $('#edition-list').innerHTML = meta.editions.map(e => `
    <label class="check"><input type="checkbox" data-list="edition" value="${e}">
      <span class="swatch" style="background:${EDITION_COLORS[e] || '#555'}"></span>${e}</label>`).join('');
  $('#type-list').innerHTML = meta.book_types.map(t => `
    <label class="check"><input type="checkbox" data-list="type" value="${t}">${t}</label>`).join('');
  buildCatalogChecklists();
  $('#export-edition').innerHTML = '<option value="">All editions</option>' +
    meta.editions.map(e => `<option value="${e}">${e}</option>`).join('');
  $('#pdf-search-editions').innerHTML =
    '<button class="secondary" type="button" data-all-editions aria-pressed="true">All editions</button>' +
    meta.editions.map(e => `<button class="secondary" type="button" data-edition="${esc(e)}" aria-pressed="true">${esc(e)}</button>`).join('');
  if (meta.year_min) { $('#year-min').placeholder = meta.year_min; $('#year-max').placeholder = meta.year_max; }
}

function buildCatalogChecklist(key, names, blankLabel) {
  const choices = [...new Set([...names, ...state[key]])]
    .filter(Boolean).sort((a, b) => a.localeCompare(b));
  $(`#${key}-list`).innerHTML = ['', ...choices].map(name => `
    <label class="check"><input type="checkbox" data-list="${key}" value="${esc(name)}">${esc(name || blankLabel)}</label>`).join('');
}

function buildCatalogChecklists() {
  buildCatalogChecklist('setting', meta.settings, 'No setting set');
  buildCatalogChecklist('publisher', meta.publishers, 'No publisher set');
}

function syncControls() {
  $$('.view-switch button').forEach(b => b.classList.toggle('active', b.dataset.view === state.view));
  $('#sort').value = state.sort;
  $('#sort-dir').textContent = state.desc ? '↓' : '↑';
  $('#group-shelves').checked = state.grouped;
  $('#group-shelves').closest('label').hidden = state.view !== 'shelf';
  $('#all-releases').checked = state.all;
  $('#show-contents').checked = state.contents;
  $('#owned').checked = state.owned;
  $('#not-physically-owned').checked = state.not_physically_owned;
  $('#has-pdf').checked = state.pdf;
  $('#no-pdf').checked = state.no_pdf;
  const filteredExport = $('#export-scope').value === 'filtered';
  $('#export-edition').disabled = filteredExport;
  $('#export-filtered-hint').hidden = !filteredExport;
  $('#export-csv').href = exportUrl();
  $('#year-min').value = state.ymin;
  $('#year-max').value = state.ymax;
  if ($('#search') !== document.activeElement) $('#search').value = state.q;
  $$('[data-hide]').forEach(c => { c.checked = c.dataset.hide.split('|').every(k => state.hide.includes(k)); });
  $$('[data-list]').forEach(c => { c.checked = state[c.dataset.list].includes(c.value); });
  $$('[data-filter-group]').forEach(group => {
    const count = group.dataset.filterGroup === 'year'
      ? [$('#year-min').value, $('#year-max').value].filter(Boolean).length
      : group.querySelectorAll('input[type="checkbox"]:checked').length;
    const badge = group.querySelector('[data-count-for]');
    badge.textContent = count ? String(count) : '';
    badge.hidden = !count;
  });
}

function bindControls() {
  $$('.view-switch button').forEach(b => b.addEventListener('click', () => update({ view: b.dataset.view }, false)));
  bindPdfSearch();
  bindHelp();
  $('#toggle-theme').addEventListener('click', () => {
    const theme = preferredTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem(THEME_KEY, theme); } catch { /* theme still applies for this page */ }
    syncThemeButton();
  });
  $('#sort').addEventListener('change', (e) => update({ sort: e.target.value }));
  $('#sort-dir').addEventListener('click', () => update({ desc: !state.desc }));
  $('#group-shelves').addEventListener('change', (e) => update({ grouped: e.target.checked }, false));
  $('#all-releases').addEventListener('change', (e) => update({ all: e.target.checked }));
  $('#show-contents').addEventListener('change', (e) => update({ contents: e.target.checked }));
  $('#cover-size').addEventListener('input', (e) => setCoverSize(e.target.value));
  $('#owned').addEventListener('change', (e) => update({ owned: e.target.checked }));
  $('#not-physically-owned').addEventListener('change', (e) => update({ not_physically_owned: e.target.checked }));
  $('#has-pdf').addEventListener('change', (e) => update({ pdf: e.target.checked }));
  $('#no-pdf').addEventListener('change', (e) => update({ no_pdf: e.target.checked }));
  for (const id of ['#year-min', '#year-max']) {
    $(id).addEventListener('change', () => update({ ymin: $('#year-min').value, ymax: $('#year-max').value }));
  }
  let t;
  $('#search').addEventListener('input', (e) => { clearTimeout(t); t = setTimeout(() => update({ q: e.target.value.trim() }), 200); });

  $$('[data-hide]').forEach(c => c.addEventListener('change', () => {
    const kinds = c.dataset.hide.split('|');
    const hide = state.hide.filter(k => !kinds.includes(k));
    update({ hide: c.checked ? [...hide, ...kinds] : hide });
  }));
  $('#filters').addEventListener('change', (e) => {
    const c = e.target.closest('[data-list]');
    if (!c) return;
    const key = c.dataset.list;
    const set = new Set(state[key]);
    c.checked ? set.add(c.value) : set.delete(c.value);
    update({ [key]: [...set] });
  });
  $$('[data-clear]').forEach(b => b.addEventListener('click', () => update({ [b.dataset.clear]: [] })));
  $('#reset').addEventListener('click', () => update({ ...DEFAULTS, view: state.view }));
  $('#export-scope').addEventListener('change', syncControls);
  $('#export-edition').addEventListener('change', syncControls);
  const filters = $('#filters');
  const toggleFilters = (open) => {
    filters.classList.toggle('open', open);
    const toggle = $('#toggle-filters');
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Hide filters' : 'Show filters');
  };
  $('#toggle-filters').addEventListener('click', () => toggleFilters(!filters.classList.contains('open')));
  $('#close-filters').addEventListener('click', () => toggleFilters(false));
  $('#add-book').addEventListener('click', () => workForm(null));
  $('#add-set').addEventListener('click', () => workForm(null, { book_type: 'Boxed Set', edition: state.edition[0] }));
}

function bindHelp() {
  const dialog = $('#help-dialog');
  const sections = $$('[data-help-section]');
  const open = (topic) => {
    sections.forEach(section => {
      section.open = topic
        ? section.dataset.helpSection === topic
        : section.dataset.helpSection === 'collection';
    });
    dialog.showModal();
    if (topic) dialog.querySelector(`[data-help-section="${topic}"]`)?.scrollIntoView({ block: 'nearest' });
  };
  $('#open-help').addEventListener('click', () => open(null));
  $$('[data-help-topic]').forEach(button => {
    button.addEventListener('click', () => open(button.dataset.helpTopic));
  });
  $$('[data-close-help]').forEach(button => button.addEventListener('click', () => dialog.close()));
}

function bindPdfSearch() {
  document.addEventListener('visibilitychange', () => {
    clearTimeout(pdfSearchPoll);
    pdfSearchPoll = null;
    if (!document.hidden && state.page === 'pdf-search') refreshPdfIndexStatus();
  });
  $('#open-collection').addEventListener('click', () => setActivePage('collection'));
  $('#open-pdf-search').addEventListener('click', () => {
    setActivePage('pdf-search');
    $('#pdf-search-query').focus();
  });
  $('#pdf-search-form').addEventListener('submit', (e) => {
    e.preventDefault();
    pdfSearchQuery = $('#pdf-search-query').value.trim();
    pdfSearchMatch = $('#pdf-search-match').value;
    $('#pdf-search-page').classList.toggle('has-search', Boolean(pdfSearchQuery));
    $('#pdf-search-output').hidden = !pdfSearchQuery;
    resetPdfSearch();
  });
  $('#pdf-search-editions').addEventListener('click', (e) => {
    const button = e.target.closest('button');
    if (!button) return;
    const all = $('#pdf-search-editions [data-all-editions]');
    const editions = $$('#pdf-search-editions [data-edition]');
    const pressed = button.getAttribute('aria-pressed') !== 'true';
    if (button === all) editions.forEach(item => item.setAttribute('aria-pressed', String(pressed)));
    else button.setAttribute('aria-pressed', String(pressed));
    all.setAttribute('aria-pressed', String(editions.every(item => item.getAttribute('aria-pressed') === 'true')));
    resetPdfSearch();
  });
  $('#pdf-search-more').addEventListener('click', searchPdfPages);
  $('#index-pdfs').addEventListener('click', () => startPdfIndex('all'));
  $('#reindex-pdfs').addEventListener('click', () => {
    if (confirm('Re-index every linked PDF? This may take a while.')) startPdfIndex('reindex');
  });
  $('#retry-pdfs').addEventListener('click', () => startPdfIndex('failed'));
  $('#pause-pdfs').addEventListener('click', () => startPdfIndex('pause'));
  $('#pdf-index-failures').addEventListener('click', async (e) => {
    const button = e.target.closest('[data-retry-pdf]');
    if (!button) return;
    button.disabled = true;
    try {
      await api.retryPdfIndex(button.dataset.retryPdf);
      toast('PDF queued for re-indexing');
      await refreshPdfIndexStatus();
    } catch (error) {
      toast(error.message, true);
      button.disabled = false;
    }
  });
}

const PDF_INDEX_ACTIVE_POLL_MS = 2500;
const PDF_INDEX_IDLE_POLL_MS = 15000;

function setActivePage(page) {
  state.page = page;
  writeHash();
  document.body.classList.toggle('pdf-mode', page === 'pdf-search');
  $('#collection-page').hidden = page !== 'collection';
  $('#pdf-search-page').hidden = page !== 'pdf-search';
  $('#open-collection').setAttribute('aria-pressed', String(page === 'collection'));
  $('#open-pdf-search').setAttribute('aria-pressed', String(page === 'pdf-search'));
  clearTimeout(pdfSearchPoll);
  pdfSearchPoll = null;
  if (page === 'pdf-search') {
    $('#filters').classList.remove('open');
    $('#toggle-filters').setAttribute('aria-expanded', 'false');
    $('#toggle-filters').setAttribute('aria-label', 'Show filters');
    refreshPdfIndexStatus();
  }
}

async function refreshPdfIndexStatus() {
  clearTimeout(pdfSearchPoll);
  pdfSearchPoll = null;
  if (state.page !== 'pdf-search' || document.hidden) return;
  if (pdfIndexRefreshing) {
    pdfIndexRefreshPending = true;
    return;
  }
  pdfIndexRefreshing = true;
  let pollDelay = PDF_INDEX_IDLE_POLL_MS;
  try {
    const status = await api.pdfIndexStatus();
    const parts = [`${status.done} of ${status.linked} linked PDFs indexed`];
    if (status.processing && status.current) {
      parts.push(`Processing ${status.current.title} (${status.current.indexed_pages}/${status.current.page_count} pages; ${status.current.ocr_pages || 0} OCRed)`);
    } else if (status.queued) {
      parts.push(`${status.queued} queued`);
    }
    if (status.not_indexed) parts.push(`${status.not_indexed} not started`);
    if (status.error) parts.push(`${status.error} failed`);
    if (status.paused && (status.processing || status.queued)) parts.push('paused');
    if (!status.worker_online && (status.processing || status.queued)) parts.push('OCR worker offline');
    parts.push(`OCR used in ${status.ocr_books} PDF${status.ocr_books === 1 ? '' : 's'} (${status.ocr_pages} page${status.ocr_pages === 1 ? '' : 's'})`);
    if (status.ocr_unrecorded) {
      parts.push(`${status.ocr_unrecorded} PDF${status.ocr_unrecorded === 1 ? '' : 's'} without OCR details`);
    }
    $('#pdf-index-status').textContent = parts.join(' · ');
    $('#pdf-index-actions').hidden = !meta.can_edit;
    const active = status.queued > 0 || status.processing > 0;
    if (active && !status.paused && status.worker_online) pollDelay = PDF_INDEX_ACTIVE_POLL_MS;
    const needsIndex = status.not_indexed > 0 || status.error > 0 || status.ocr_unrecorded > 0;
    $('#index-pdfs').textContent = status.paused && active
      ? 'Resume indexing'
      : status.linked === 0 ? 'No linked PDFs'
        : needsIndex ? 'Start indexing' : 'Check for new or changed PDFs';
    $('#index-pdfs').disabled = !meta.can_edit || status.linked === 0 || (!status.paused && active);
    $('#pause-pdfs').disabled = !meta.can_edit || status.paused || !active;
    $('#reindex-pdfs').disabled = !meta.can_edit || active || status.linked === 0;
    $('#retry-pdfs').disabled = !meta.can_edit || status.error === 0 || active;
    $('#pdf-index-failures').innerHTML = status.failures.map(f => `
      <div class="pdf-index-failure">
        <span><b>${esc(f.title)}</b>: ${esc(f.error || 'Indexing failed')}</span>
        ${meta.can_edit ? `<button class="secondary" type="button" data-retry-pdf="${esc(f.release_id)}">Retry</button>` : ''}
      </div>`).join('');
  } catch (error) {
    $('#pdf-index-status').textContent = `Could not load PDF index status: ${error.message}`;
  } finally {
    pdfIndexRefreshing = false;
    const delay = pdfIndexRefreshPending ? 0 : pollDelay;
    pdfIndexRefreshPending = false;
    if (state.page === 'pdf-search' && !document.hidden) {
      pdfSearchPoll = setTimeout(refreshPdfIndexStatus, delay);
    }
  }
}

async function startPdfIndex(mode) {
  try {
    const result = await api.startPdfIndex(mode);
    if (mode === 'pause') toast('PDF indexing paused');
    else if (mode === 'resume') toast('PDF indexing resumed');
    else toast(result.queued ? `Queued ${result.queued} PDF${result.queued === 1 ? '' : 's'}` : 'No PDFs need indexing');
    await refreshPdfIndexStatus();
  } catch (error) {
    toast(error.message, true);
  }
}

function resetPdfSearch() {
  pdfSearchRevision++;
  pdfSearchOffset = 0;
  pdfSearchGroups.clear();
  $('#pdf-search-results').replaceChildren();
  $('#pdf-search-error').hidden = true;
  $('#pdf-search-export').hidden = true;
  $('#pdf-search-more').hidden = true;
  $('#pdf-search-more').disabled = false;
  if (pdfSearchQuery) searchPdfPages();
}

async function searchPdfPages() {
  const summary = $('#pdf-search-summary');
  const more = $('#pdf-search-more');
  const download = $('#pdf-search-export');
  const errorEl = $('#pdf-search-error');
  if (more.disabled || !pdfSearchQuery) return;
  const activeEditions = $$('#pdf-search-editions [data-edition][aria-pressed="true"]');
  if (!activeEditions.length) {
    summary.textContent = 'Select at least one edition to show matches.';
    return;
  }
  const revision = pdfSearchRevision;
  const params = new URLSearchParams({ q: pdfSearchQuery, match: pdfSearchMatch });
  if (activeEditions.length !== meta.editions.length) {
    activeEditions.forEach(item => params.append('editions', item.dataset.edition));
  }
  const pageParams = new URLSearchParams(params);
  pageParams.set('limit', PDF_SEARCH_PAGE_SIZE);
  pageParams.set('offset', pdfSearchOffset);
  errorEl.hidden = true;
  more.disabled = true;
  if (!pdfSearchOffset) summary.textContent = 'Searching indexed PDFs…';
  try {
    const result = await api.searchPdfText(pageParams);
    if (revision !== pdfSearchRevision) return;
    const matchDescription = { all: 'all words', any: 'any word', phrase: 'the exact phrase' }[pdfSearchMatch];
    const count = `${result.total} matching page${result.total === 1 ? '' : 's'}`;
    for (const row of result.results) appendPdfSearchPage(row);
    pdfSearchOffset += result.results.length;
    summary.textContent = result.total
      ? `${count} for ${matchDescription} “${pdfSearchQuery}”${pdfSearchOffset < result.total ? ` · ${pdfSearchOffset} loaded` : ''}`
      : `No matching indexed pages for “${pdfSearchQuery}”. The PDF index may still be processing.`;
    more.hidden = pdfSearchOffset >= result.total || !result.results.length;
    download.hidden = !result.total;
    if (result.total) download.href = api.exportPdfSearchUrl(params);
  } catch (error) {
    if (revision !== pdfSearchRevision) return;
    if (!pdfSearchOffset) summary.textContent = '';
    errorEl.textContent = error.message;
    errorEl.hidden = false;
  } finally {
    if (revision === pdfSearchRevision) more.disabled = false;
  }
}

function appendPdfSearchPage(row) {
  let group = pdfSearchGroups.get(row.release_id);
  if (!group) {
    group = document.createElement('details');
    group.className = 'pdf-search-result';
    group.innerHTML = `<summary><b>${esc(row.title)}</b>
      <span>${esc(row.edition)} · ${esc(row.release_kind)}${row.label ? ` · ${esc(row.label)}` : ''}</span>
    </summary>`;
    $('#pdf-search-results').append(group);
    pdfSearchGroups.set(row.release_id, group);
  }
  group.insertAdjacentHTML('beforeend', `
    <div class="pdf-search-page-match">
      <a href="${api.pdfUrl(row.release_id)}#page=${row.page_number}" target="_blank" rel="noopener">
        Open PDF at page ${row.page_number}
      </a>
      <p>${esc(row.snippet).replaceAll('\u001f', '<mark>').replaceAll('\u001e', '</mark>')}</p>
    </div>`);
}

// ---------------------------------------------------------------- cover size

let coverSizeFrame = null;

function setCoverSize(px, save = true) {
  document.documentElement.style.setProperty('--cover-w', `${px}px`);
  $('#cover-size').value = px;
  if (save) { try { localStorage.setItem('coverSize', px); } catch { /* ignore */ } }
  if (books.length && state.view !== 'table' && coverSizeFrame === null) {
    coverSizeFrame = requestAnimationFrame(() => {
      coverSizeFrame = null;
      if (books.length && state.view !== 'table') render();
    });
  }
}

// ---------------------------------------------------------------- data + render

function queryParams() {
  const p = { sort: state.sort, desc: state.desc, all_releases: state.all, contents: state.contents };
  if (state.edition.length) p.edition = state.edition.join('|');
  if (state.type.length) p.type = state.type.join('|');
  if (state.hide.length) p.hide_kinds = state.hide.join('|');
  if (state.ymin) p.year_min = state.ymin;
  if (state.ymax) p.year_max = state.ymax;
  if (state.owned) p.owned = true;
  if (state.not_physically_owned) p.not_physically_owned = true;
  if (state.pdf) p.has_pdf = true;
  if (state.no_pdf) p.no_pdf = true;
  if (state.q) p.q = state.q;
  const params = new URLSearchParams(p);
  state.setting.forEach(setting => params.append('setting', setting));
  state.publisher.forEach(publisher => params.append('publisher', publisher));
  return params;
}

function exportUrl() {
  const scope = $('#export-scope').value;
  if (scope === 'filtered') return `/api/export-view.csv?${queryParams()}`;
  const params = new URLSearchParams({ scope });
  if ($('#export-edition').value) params.set('edition', $('#export-edition').value);
  return `/api/export.csv?${params}`;
}

async function reloadCollection() {
  try {
    meta = await api.meta();
    buildCatalogChecklists();
    syncControls();
  } catch (e) {
    toast(`Could not refresh setting and publisher choices: ${e.message}`, true);
  }
  await load();
}

let loadSeq = 0;
async function load() {
  const seq = ++loadSeq;
  try {
    const result = await api.books(queryParams());
    if (seq !== loadSeq) return; // a newer request superseded this one
    books = result;
    render();
  } catch (e) {
    toast(e.message, true);
  }
}

function render() {
  const el = $('#content');
  const withPdf = books.filter(b => b.has_pdf).length;
  const filtered = JSON.stringify({ ...state, page: 0, view: 0, sort: 0, desc: 0, grouped: 0 }) !==
    JSON.stringify({ ...DEFAULTS, page: 0, view: 0, sort: 0, desc: 0, grouped: 0 });
  $('#summary').textContent =
    `${books.length} ${state.all ? 'release' : 'book'}${books.length === 1 ? '' : 's'}` +
    (filtered ? ' match your filters' : '') + ` · ${withPdf} with a linked PDF`;
  if (!books.length) {
    el.innerHTML = '<div class="empty">No books match these filters.</div>';
    return;
  }
  const opts = { editions: meta.editions, showAll: state.all, grouped: state.grouped, collapsed, sort: state.sort, desc: state.desc };
  if (state.view === 'grid') renderGrid(el, books, opts);
  else if (state.view === 'table') renderTable(el, books, opts);
  else renderShelves(el, books, opts);
  paint();
}

function update(patch, reload = true) {
  state = { ...state, ...patch };
  writeHash();
  syncControls();
  if (reload) load(); else render();
}

// ---------------------------------------------------------------- clicks on books

function bindContent() {
  const content = $('#content');
  const activate = (e) => {
    const collapseBtn = e.target.closest('[data-collapse]');
    if (collapseBtn) {
      const ed = collapseBtn.dataset.collapse;
      collapsed.has(ed) ? collapsed.delete(ed) : collapsed.add(ed);
      try { localStorage.setItem('collapsedShelves', JSON.stringify([...collapsed])); } catch { /* ignore */ }
      return render();
    }
    const th = e.target.closest('th[data-sort]');
    if (th) return update(th.dataset.sort === state.sort ? { desc: !state.desc } : { sort: th.dataset.sort, desc: false });

    const item = e.target.closest('[data-release]');
    if (!item) return;
    if (isSelecting()) return clickItem(e, item);
    const wantsInfo = e.target.closest('[data-info]') || item.tagName === 'TR' || e.shiftKey;
    if (!wantsInfo && item.dataset.pdfRelease) {
      window.open(api.pdfUrl(item.dataset.pdfRelease), '_blank');
    } else {
      openDrawer(item.dataset.work, item.dataset.release);
    }
  };
  content.addEventListener('click', activate);
  content.addEventListener('keydown', (e) => {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('.book')) { e.preventDefault(); activate(e); }
  });
}

// ---------------------------------------------------------------- toast

let toastTimer;
export function toast(msg, isError = false) {
  const el = $('#toast');
  el.textContent = msg;
  el.className = 'toast' + (isError ? ' error' : '');
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 2500);
}

// ---------------------------------------------------------------- boot

(async function boot() {
  try {
    meta = await api.meta();
  } catch (e) {
    $('#content').innerHTML = `<div class="empty">Could not reach the tracker server: ${e.message}</div>`;
    return;
  }
  state = readHash();
  syncThemeButton();
  setActivePage(state.page);
  document.body.classList.toggle('readonly', !meta.can_edit);
  document.body.classList.toggle('no-external', !meta.can_open_external);
  if (meta.user) $('#whoami').textContent = meta.can_edit ? meta.user : `${meta.user} (view only)`;
  $('#app-version').textContent = meta.version;
  // Keep sticky shelves and the sidebar below the app and collection toolbars.
  const topbar = $('.topbar');
  const collectionToolbar = $('.collection-toolbar');
  new ResizeObserver(() => {
    document.documentElement.style.setProperty('--topbar-h', `${topbar.offsetHeight}px`);
    document.documentElement.style.setProperty('--collection-toolbar-h', `${collectionToolbar.offsetHeight}px`);
  }).observe(topbar);
  new ResizeObserver(() => {
    document.documentElement.style.setProperty('--collection-toolbar-h', `${collectionToolbar.offsetHeight}px`);
  }).observe(collectionToolbar);
  try { const px = localStorage.getItem('coverSize'); if (px) setCoverSize(px, false); } catch { /* ignore */ }
  buildChecklists();
  bindControls();
  bindContent();
  initDetail({ meta, onChange: reloadCollection, toast });
  initSelect({ meta, toast, reload: reloadCollection });
  syncControls();
  window.addEventListener('hashchange', () => {
    state = readHash();
    buildCatalogChecklists();
    syncControls();
    setActivePage(state.page);
    load();
  });
  // Re-flow shelf rows when the window width changes the number of covers per row.
  let lastPerRow = 0, resizeTimer;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (state.view !== 'shelf') return;
      const n = booksPerRow($('#content'));
      if (n !== lastPerRow) { lastPerRow = n; render(); }
    }, 120);
  });
  load();
})();
