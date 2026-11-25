import { api } from './api.js';
import { esc } from './shelf.js';

const PAGE_SIZE = 30;
const LINK_BATCH = 25;
const LABELS = { ready: 'Ready to link', review: 'Needs review', none: 'No match', ignored: 'Ignored' };
const printingName = p => [p.title, p.edition, p.year, p.kind, p.label].filter(Boolean).join(' · ');
const fileUrl = (action, path) => `/api/pdf-import/${action}?${new URLSearchParams({ path })}`;

export function initPdfImport(page, picker, onLinks) {
  const $ = name => page.querySelector(`[data-import-${name}]`);
  const select = new Map();
  const filters = [...$('filters').querySelectorAll('[data-tier]')];
  let tier = 'ready', offset = 0, total = 0, generation = 0, query = '';
  let items = [], busy = false, scanning = false, loaded = false, timer, searchTimer, revision = 0;
  let defaultSelection = true;

  function showError(text = '') {
    $('error').textContent = text;
    $('error').hidden = !text;
  }

  function buttons() {
    const locked = busy || scanning || !loaded;
    $('scan').disabled = busy || scanning;
    $('query').disabled = locked;
    filters.forEach(button => { button.disabled = locked; });
    const available = items.filter(row => row.selected && row.tier === 'ready');
    const pageSelected = available.length && available.every(row => select.has(row.path));
    $('select').textContent = pageSelected ? 'Clear selection' : 'Select this page';
    $('select').disabled = locked || !available.length;
    $('select-all').hidden = tier !== 'ready' || total <= items.length;
    $('select-all').disabled = locked;
    $('link').textContent = select.size ? `Link ${select.size} selected` : 'Link selected';
    $('link').disabled = $('ignore').disabled = locked || !select.size;
    $('count').textContent = select.size ? `${select.size} selected across pages` : '';
    $('prev').disabled = locked || offset === 0;
    $('next').disabled = locked || offset + items.length >= total;
    $('rows').querySelectorAll('button, input').forEach(el => { el.disabled = locked; });
  }

  function render() {
    $('rows').innerHTML = items.map((row, i) => {
      const filename = row.path.split('/').pop();
      const folder = row.path.slice(0, -filename.length).replace(/\/$/, '');
      const selected = row.selected;
      const best = selected || row.candidates[0];
      const matching = row.candidates.find(c => c.id === selected?.id);
      return `<article class="pdf-import-row" data-row="${i}">
        <input type="checkbox" data-mark aria-label="Select ${esc(filename)}"
          ${select.has(row.path) ? 'checked' : ''} ${!selected ? 'hidden' : ''}>
        <a class="pdf-import-thumb" href="${esc(fileUrl('file', row.path))}" target="_blank" rel="noopener"
          aria-label="Open ${esc(filename)} in a new tab">
          <img alt="" loading="lazy" src="${esc(fileUrl('preview', row.path))}">
          <span aria-hidden="true">PDF</span>
        </a>
        <div class="pdf-import-details">
          <strong>${esc(filename)}</strong>
          ${folder ? `<div class="rmeta">${esc(folder)}</div>` : ''}
          ${best ? `<div class="pdf-import-printing">${esc(printingName(best))}${best.linked ? ' (already linked)' : ''}</div>` : ''}
          ${row.note ? `<p class="rmeta">${esc(row.note)}</p>` : ''}
          <div class="pdf-import-reasons">
            ${(row.manual ? ['Chosen manually'] : (matching || best)?.reasons || []).map(reason =>
              `<span class="rmeta">${esc(reason)}</span>`).join('')}
          </div>
          ${row.tier === 'review' && row.candidates.some(c => !c.linked) ? `<div class="pdf-import-choices">
            ${row.candidates.filter(c => !c.linked).map(c =>
              `<button type="button" class="secondary" data-choose="${esc(c.id)}"
                title="${esc(c.reasons.join(', '))}">${esc(printingName(c))}</button>`).join('')}
          </div>` : ''}
        </div>
        <div class="pdf-import-actions">
          ${row.tier === 'ignored' ? '<button type="button" class="secondary" data-act="restore">Restore</button>' :
            `<button type="button" class="secondary" data-act="change">${selected ? 'Change printing' : 'Choose printing'}</button>
             <button type="button" class="secondary" data-act="ignore">Ignore</button>`}
          <a href="${esc(fileUrl('file', row.path))}" target="_blank" rel="noopener">Open PDF</a>
        </div>
      </article>`;
    }).join('') || '<p class="rmeta">No PDFs in this view.</p>';
    $('rows').querySelectorAll('img').forEach(img => {
      img.addEventListener('load', () => { img.nextElementSibling.hidden = true; });
      img.addEventListener('error', () => { img.hidden = true; });
    });
    $('pagination').hidden = total <= PAGE_SIZE;
    $('range').textContent = total ? `${offset + 1}–${offset + items.length} of ${total}` : '';
    buttons();
  }

  async function refresh({ reset = false } = {}) {
    clearTimeout(timer);
    if (page.hidden) return;
    const token = ++revision;
    loaded = false;
    buttons();
    try {
      const state = await api.pdfImportStatus();
      if (token !== revision) return;
      scanning = state.status === 'scanning';
      if (generation !== state.generation || reset) {
        select.clear();
        offset = 0;
        defaultSelection = true;
      }
      generation = state.generation;
      $('scan').textContent = state.finished_at ? 'Rescan library' : 'Scan library';
      $('status').textContent = scanning ? `Scanning… ${state.scanned} PDFs checked` :
        state.finished_at ? `Last completed scan: ${new Date(state.finished_at.replace(' ', 'T') + 'Z').toLocaleString()}.` : '';
      if (state.status === 'done') {
        $('status').textContent += ` ${state.scanned} checked, ${state.already_linked} already linked, ${state.skipped} skipped.`;
      }
      if (state.error) showError(state.error);
      const hasQueue = !scanning && Boolean(state.finished_at);
      $('controls').hidden = !hasQueue;
      $('rows').hidden = !hasQueue;
      if (!hasQueue) $('pagination').hidden = true;
      if (!hasQueue) return;
      filters.forEach(button => {
        const key = button.dataset.tier;
        button.textContent = `${LABELS[key]} (${state.counts[key]})`;
        button.setAttribute('aria-pressed', String(key === tier));
      });
      let result = await api.pdfImportFiles({ tier, q: query, offset, limit: PAGE_SIZE });
      if (token !== revision) return;
      if (result.generation !== generation) {
        timer = setTimeout(refresh, 250);
        return;
      }
      if (offset > 0 && !result.items.length) {
        offset = Math.max(0, Math.floor((result.total - 1) / PAGE_SIZE) * PAGE_SIZE);
        result = await api.pdfImportFiles({ tier, q: query, offset, limit: PAGE_SIZE });
        if (token !== revision) return;
        if (result.generation !== generation) {
          timer = setTimeout(refresh, 250);
          return;
        }
      }
      ({ items, total } = result);
      if (defaultSelection && tier === 'ready') {
        for (const row of items) if (row.selected) select.set(row.path, row.selected.id);
      }
      for (const row of items) {
        if (select.has(row.path) && select.get(row.path) !== row.selected?.id) select.delete(row.path);
      }
      loaded = true;
      render();
    } catch (error) {
      if (token === revision) showError(error.message);
    } finally {
      if (token === revision) {
        buttons();
        if (scanning && !page.hidden) timer = setTimeout(refresh, 700);
      }
    }
  }

  async function act(run) {
    if (busy) return;
    busy = true;
    showError();
    $('report').replaceChildren();
    buttons();
    try {
      await run();
    } catch (error) {
      showError(error.message);
    } finally {
      busy = false;
      buttons();
    }
  }

  function resetView() {
    select.clear();
    offset = 0;
    defaultSelection = true;
  }

  async function decide(action, paths, release_id) {
    await act(async () => {
      for (let from = 0; from < paths.length; from += 50) {
        await api.decidePdfImport({ generation, paths: paths.slice(from, from + 50), action, release_id });
        for (const path of paths.slice(from, from + 50)) select.delete(path);
      }
      if (action === 'choose') {
        $('report').textContent = 'Printing saved. You can approve the link under Ready to link.';
      }
      await refresh();
    });
  }

  function choosePrinting(row) {
    picker.innerHTML = `<form method="dialog" class="picker">
      <h2 id="pdf-import-picker-title">Choose a printing</h2>
      <p class="rmeta">${esc(row.path)}</p>
      <label>Search title, code, ISBN, or setting <input class="picker-q" type="search" maxlength="256"></label>
      <p class="rmeta" data-picker-status role="status"></p>
      <div class="picker-list"></div>
      <div class="form-actions"><button class="secondary">Cancel</button></div>
    </form>`;
    const search = picker.querySelector('input');
    const list = picker.querySelector('.picker-list');
    const status = picker.querySelector('[data-picker-status]');
    const alternatives = row.candidates.filter(c => !c.linked);
    let sequence = 0, debounce;
    const options = records => records.map(p => `<button type="button" class="secondary"
      data-printing="${esc(p.id)}">${esc(printingName(p))}</button>`).join('');
    async function lookup() {
      const token = ++sequence;
      const q = search.value.trim();
      status.textContent = 'Searching…';
      list.innerHTML = alternatives.length ? `<strong>Suggested printings</strong>${options(alternatives)}` : '';
      try {
        const books = await api.books({ all_releases: true, contents: true, no_pdf: true, sort: 'title', q });
        if (token !== sequence || !picker.open) return;
        const suggestions = new Set(alternatives.map(p => p.id));
        const results = books.filter(p => !suggestions.has(p.id));
        status.textContent = results.length > 50 ? 'Showing the first 50 results. Refine the search to see others.' :
          results.length ? '' : 'No other unlinked printings found. Try a shorter search.';
        list.insertAdjacentHTML('beforeend', options(results.slice(0, 50).map(p => ({
          id: p.id, title: p.title, edition: p.edition, year: p.display_year, kind: p.release_kind, label: p.label,
        }))));
      } catch (error) {
        if (token === sequence) status.textContent = error.message;
      }
    }
    search.value = row.query.slice(0, 256);
    search.addEventListener('input', () => {
      sequence++;
      clearTimeout(debounce);
      debounce = setTimeout(lookup, 200);
    });
    search.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); clearTimeout(debounce); lookup(); } });
    list.addEventListener('click', e => {
      const button = e.target.closest('[data-printing]');
      if (!button) return;
      picker.close();
      decide('choose', [row.path], button.dataset.printing);
    });
    picker.addEventListener('close', () => { sequence++; clearTimeout(debounce); }, { once: true });
    picker.showModal();
    search.focus();
    lookup();
  }

  $('scan').addEventListener('click', () => act(async () => {
    await api.scanPdfImport();
    await refresh({ reset: true });
  }));
  $('filters').addEventListener('click', e => {
    if (!e.target.dataset.tier || e.target.dataset.tier === tier) return;
    tier = e.target.dataset.tier;
    resetView();
    refresh();
  });
  $('query').addEventListener('input', () => {
    query = $('query').value.trim();
    resetView();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(refresh, 200);
    buttons();
  });
  $('prev').addEventListener('click', () => { offset -= PAGE_SIZE; refresh(); });
  $('next').addEventListener('click', () => { offset += PAGE_SIZE; refresh(); });
  $('select').addEventListener('click', () => {
    defaultSelection = false;
    if (items.filter(row => row.selected).every(row => select.has(row.path))) select.clear();
    else for (const row of items) if (row.selected) select.set(row.path, row.selected.id);
    render();
  });
  $('select-all').addEventListener('click', () => act(async () => {
    const pending = new Map();
    for (let from = 0; from < total; from += 50) {
      const result = await api.pdfImportFiles({ tier: 'ready', q: query, offset: from, limit: 50 });
      if (result.generation !== generation || result.total !== total) throw new Error('Review list changed. Refresh and try again.');
      for (const row of result.items) if (row.selected) pending.set(row.path, row.selected.id);
    }
    select.clear();
    for (const [path, id] of pending) select.set(path, id);
    render();
  }));
  $('rows').addEventListener('change', e => {
    const row = items[Number(e.target.closest('[data-row]')?.dataset.row)];
    if (!row?.selected || !e.target.matches('[data-mark]')) return;
    defaultSelection = false;
    if (e.target.checked) select.set(row.path, row.selected.id);
    else select.delete(row.path);
    buttons();
  });
  $('rows').addEventListener('click', e => {
    const button = e.target.closest('button');
    const row = items[Number(button?.closest('[data-row]')?.dataset.row)];
    if (!row) return;
    if (button.dataset.choose) decide('choose', [row.path], button.dataset.choose);
    if (button.dataset.act === 'change') choosePrinting(row);
    if (['ignore', 'restore'].includes(button.dataset.act)) decide(button.dataset.act, [row.path]);
  });
  $('ignore').addEventListener('click', () => decide('ignore', [...select.keys()]));
  $('link').addEventListener('click', () => act(async () => {
    const batch = [...select].map(([path, release_id]) => ({ path, release_id }));
    const progress = $('progress');
    progress.hidden = false;
    progress.max = batch.length;
    progress.value = 0;
    let linked = 0;
    const issues = [];
    try {
      for (let i = 0; i < batch.length; i += LINK_BATCH) {
        const { results } = await api.linkPdfImport({ generation, items: batch.slice(i, i + LINK_BATCH) });
        for (const result of results) {
          if (result.linked) { linked++; select.delete(result.path); }
          if (result.warning || result.error) issues.push(`${result.path}: ${result.warning || result.error}`);
        }
        progress.value += results.length;
      }
    } finally {
      progress.hidden = true;
      $('report').innerHTML = `<p>Linked ${linked} of ${batch.length} PDFs.${linked ?
        ' Run indexing from PDF Search when you want these files to be searchable.' : ''}</p>
        ${issues.length ? `<ul>${issues.map(issue => `<li>${esc(issue)}</li>`).join('')}</ul>` : ''}`;
      if (linked) onLinks();
      await refresh();
    }
  }));
  page.onPageChange = active => {
    if (active) refresh();
    else { revision++; clearTimeout(timer); clearTimeout(searchTimer); }
  };
}
