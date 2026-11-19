// Detail drawer (work + all its releases) and the add/edit forms.
import { api } from './api.js';
import { coverHTML, esc } from './shelf.js';

let ctx = null; // { meta, onChange, toast }

const drawer = () => document.getElementById('drawer');
const backdrop = () => document.getElementById('drawer-backdrop');

export function initDetail(context) {
  ctx = context;
  backdrop().addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !drawer().hidden && !document.getElementById('form-dialog').open) closeDrawer();
  });
}

export function closeDrawer() {
  drawer().hidden = true;
  backdrop().hidden = true;
}

export async function openDrawer(workId, focusReleaseId) {
  try {
    const work = await api.work(workId);
    renderDrawer(work, focusReleaseId);
  } catch (e) {
    ctx.toast(e.message, true);
  }
}

function options(list, selected) {
  return list.map(v => `<option ${v === selected ? 'selected' : ''}>${esc(v)}</option>`).join('');
}

function releaseHTML(r, work, focus) {
  const b = { ...r, title: work.title, edition: work.edition };
  const libraryEnabled = ctx.meta.pdf_library_enabled;
  const libraryPath = r.pdf_path?.startsWith('library:');
  const flags = `
    <label class="check"><input type="checkbox" data-flag="owned_physical" ${r.owned_physical ? 'checked' : ''}> Own print copy</label>
    <label class="check"><input type="checkbox" data-flag="owned_pdf" ${r.owned_pdf ? 'checked' : ''}> Own PDF</label>`;
  const meta = [r.year, r.publisher, r.product_code && `Code ${r.product_code}`, r.isbn && `ISBN ${r.isbn}`].filter(Boolean).map(esc).join(' · ');
  return `<div class="release ${r.is_primary ? 'primary-rel' : ''}" data-release="${esc(r.id)}" ${focus ? 'id="focus-release"' : ''}>
    <div class="mini">${coverHTML(b)}</div>
    <div>
      <div class="rhead">
        <span class="kind-chip">${esc(r.release_kind)}</span>
        <span>${esc(r.label || (r.release_kind === 'Original' ? 'Original printing' : r.release_kind))}</span>
        ${r.is_primary ? '<span class="kind-chip" title="Shown on the shelf when releases are grouped">Shelf default</span>' : ''}
      </div>
      <div class="rmeta">${meta || '&nbsp;'}</div>
      ${r.notes ? `<div class="rmeta">${esc(r.notes)}</div>` : ''}
      <div class="flags">${flags}</div>
      ${r.pdf_path ? `<div class="pdf-path" title="Linked PDF">📄 ${esc(libraryPath ? r.pdf_path.slice('library:'.length) : r.pdf_path)}</div>` : ''}
      <div class="pdf-link" ${r.has_pdf || libraryEnabled ? 'hidden' : ''} data-pdf-form>
        <input type="text" aria-label="PDF path on the server" placeholder='Paste full PDF path, e.g. D:\\Books\\DnD\\PHB.pdf' value="${esc(libraryPath ? '' : r.pdf_path || '')}">
        <button class="secondary" data-act="save-pdf">Link</button>
      </div>
      <div class="actions">
        ${r.has_pdf ? `
          <button class="primary" data-act="open-pdf">Open PDF</button>
          <button class="secondary" data-act="open-ext" title="Open in your default PDF app">Open in app</button>
          <button class="secondary" data-act="unlink-pdf">Unlink</button>` : ''}
        ${libraryEnabled ? `<button class="${r.has_pdf ? 'secondary' : 'primary'}" data-act="browse-pdf">${r.has_pdf ? 'Change PDF' : 'Browse PDF library'}</button>` : ''}
        ${libraryEnabled || r.has_pdf ? `<button class="secondary" data-act="change-pdf">${libraryEnabled ? 'Enter path manually' : 'Change PDF'}</button>` : ''}
        <label class="secondary" style="cursor:pointer">Upload cover<input type="file" accept="image/png,image/jpeg,image/webp" data-act="upload" hidden></label>
        ${r.cover_source === 'upload' ? `<button class="secondary" data-act="reset-cover">${r.has_pdf ? 'Use PDF cover' : 'Remove cover'}</button>` : ''}
        ${r.cover_source === 'pdf' ? '<button class="secondary" data-act="reset-cover">Re-render cover</button>' : ''}
        ${!r.is_primary ? '<button class="secondary" data-act="make-primary">Make shelf default</button>' : ''}
        <button class="secondary" data-act="edit-release">Edit</button>
        ${work.releases.length > 1 ? '<button class="secondary danger" data-act="delete-release">Delete</button>' : ''}
      </div>
    </div>
  </div>`;
}

function renderDrawer(work, focusReleaseId) {
  // Header cover: same preference as the shelf (owned, then has a cover, then primary).
  const owned = (r) => r.owned_physical || r.owned_pdf || r.has_pdf;
  const primary = work.releases.find(r => owned(r) && r.cover_url)
    || work.releases.find(r => r.cover_url)
    || work.releases.find(r => r.is_primary) || work.releases[0];
  const el = drawer();
  el.innerHTML = `
    <button class="icon-btn close" data-act="close" aria-label="Close">✕</button>
    <div class="drawer-head">
      <div class="cover">${coverHTML({ ...primary, title: work.title, edition: work.edition })}</div>
      <div>
        <div class="drawer-title-row">
          <h2>${esc(work.title)}</h2>
          <button class="icon-btn copy-title" data-act="copy-title" aria-label="Copy book title" title="Copy title">⧉</button>
        </div>
        <dl class="meta">
          <dt>Edition</dt><dd>${esc(work.edition)}</dd>
          <dt>Type</dt><dd>${esc(work.book_type)}</dd>
          <dt>First published</dt><dd>${esc(work.first_year ?? '—')}</dd>
          ${work.setting ? `<dt>Setting</dt><dd>${esc(work.setting)}</dd>` : ''}
          ${work.parent ? `<dt>Part of</dt><dd><a href="#" data-act="open-work" data-id="${esc(work.parent.id)}">📦 ${esc(work.parent.title)}</a></dd>` : ''}
          <dt>Releases</dt><dd>${work.releases.length}</dd>
          ${work.source === 'user' ? '<dt>Source</dt><dd>Added or edited by you</dd>' : ''}
        </dl>
        ${work.notes ? `<p>${esc(work.notes)}</p>` : ''}
        <div class="actions">
          <button class="secondary" data-act="edit-work">Edit book</button>
          <button class="secondary" data-act="add-release">+ Add release</button>
          ${work.parent
            ? '<button class="secondary" data-act="remove-from-set">Remove from box set</button>'
            : `<button class="secondary" data-act="add-existing">📦 Put existing books in this set</button>
               <button class="secondary" data-act="add-content">+ New book inside this set</button>`}
          <button class="secondary danger" data-act="delete-work">Delete book</button>
        </div>
      </div>
    </div>
    ${contentsHTML(work)}
    <h3>Releases &amp; printings</h3>
    ${work.releases.map(r => releaseHTML(r, work, r.id === focusReleaseId)).join('')}
  `;
  el.hidden = false;
  backdrop().hidden = false;
  el.scrollTop = 0;
  document.getElementById('focus-release')?.scrollIntoView({ block: 'nearest' });

  el.onclick = (e) => handleClick(e, work);
  el.onchange = (e) => handleChange(e, work);
  el.onkeydown = (e) => {
    if (e.key === 'Enter' && e.target.matches('[data-pdf-form] input')) {
      e.target.closest('[data-pdf-form]').querySelector('[data-act="save-pdf"]').click();
    }
  };
}

function contentsHTML(work) {
  if (!work.contents?.length) return '';
  return `<h3>Books in this box set (${work.contents.length})</h3>
    <div class="contents">${work.contents.map(c => `
      <div class="content-item">
        <div class="mini">${coverHTML({ ...c, edition: work.edition })}</div>
        <div>
          <a href="#" class="ct" data-act="open-work" data-id="${esc(c.id)}">${esc(c.title)}</a>
          <div class="rmeta">${esc(c.book_type)}${c.owned_physical ? ' · HC' : ''}${c.owned_pdf ? ' · PDF' : ''}</div>
          <div class="actions">
            ${c.pdf_release_id ? `<button class="primary" data-act="open-child-pdf" data-id="${esc(c.pdf_release_id)}">Open PDF</button>` : ''}
            <button class="secondary" data-act="open-work" data-id="${esc(c.id)}">${c.pdf_release_id ? 'Details' : 'Link PDF / details'}</button>
            <button class="secondary" data-act="remove-child" data-id="${esc(c.id)}" title="Take this book out of the set (it is not deleted)">Remove</button>
          </div>
        </div>
      </div>`).join('')}
    </div>`;
}

async function refresh(work, updated, msg) {
  if (updated?.warning) ctx.toast(updated.warning, true);
  else if (msg) ctx.toast(msg);
  renderDrawer(updated || await api.work(work.id));
  ctx.onChange();
}

async function handleClick(e, work) {
  const btn = e.target.closest('[data-act]');
  if (!btn || btn.tagName === 'INPUT') return;
  const relEl = btn.closest('[data-release]');
  const rid = relEl?.dataset.release;
  const rel = work.releases.find(r => r.id === rid);
  try {
    switch (btn.dataset.act) {
      case 'close': return closeDrawer();
      case 'copy-title':
        if (!navigator.clipboard?.writeText) throw new Error('Clipboard access is unavailable in this browser');
        await navigator.clipboard.writeText(work.title);
        return ctx.toast('Book title copied');
      case 'open-work': e.preventDefault(); return openDrawer(btn.dataset.id);
      case 'open-child-pdf': return window.open(api.pdfUrl(btn.dataset.id), '_blank');
      case 'add-content': return workForm(null, { parent_id: work.id, edition: work.edition, first_year: work.first_year, setting: work.setting });
      case 'add-existing': return pickBooksForSet(work);
      case 'remove-child':
        await api.updateWork(btn.dataset.id, { parent_id: null });
        return refresh(work, null, 'Removed from box set');
      case 'remove-from-set':
        return refresh(work, await api.updateWork(work.id, { parent_id: null }), 'Removed from box set');
      case 'open-pdf': return window.open(api.pdfUrl(rid), '_blank');
      case 'open-ext': await api.openExternal(rid); return ctx.toast('Opened in your PDF app');
      case 'browse-pdf': return pickLibraryPdf(work, rel, btn);
      case 'change-pdf': {
        const form = relEl.querySelector('[data-pdf-form]');
        form.hidden = false;
        form.querySelector('input').select();
        return;
      }
      case 'save-pdf': {
        const path = relEl.querySelector('[data-pdf-form] input').value;
        if (!path.trim()) return ctx.toast('Paste the full path to a PDF first', true);
        return refresh(work, await api.linkPdf(rid, path), 'PDF linked');
      }
      case 'unlink-pdf':
        return refresh(work, await api.linkPdf(rid, ''), 'PDF unlinked');
      case 'reset-cover':
        return refresh(work, await api.resetCover(rid), 'Cover updated');
      case 'make-primary':
        return refresh(work, await api.updateRelease(rid, { is_primary: true }));
      case 'edit-release':
        return releaseForm(work, rel);
      case 'add-release':
        return releaseForm(work, null);
      case 'delete-release':
        if (!confirm(`Delete the release "${rel.label || rel.release_kind}"?`)) return;
        return refresh(work, await api.deleteRelease(rid), 'Release deleted');
      case 'edit-work':
        return workForm(work);
      case 'delete-work':
        if (!confirm(`Delete "${work.title}" and all its releases? Linked PDFs on disk are not touched.`)) return;
        await api.deleteWork(work.id);
        closeDrawer();
        ctx.toast('Book deleted');
        return ctx.onChange();
    }
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

async function handleChange(e, work) {
  const rid = e.target.closest('[data-release]')?.dataset.release;
  try {
    if (e.target.dataset.flag) {
      await api.updateRelease(rid, { [e.target.dataset.flag]: e.target.checked });
      ctx.onChange();
    } else if (e.target.dataset.act === 'upload' && e.target.files[0]) {
      await refresh(work, await api.uploadCover(rid, e.target.files[0]), 'Cover uploaded');
    }
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

// ---------------------------------------------------------------- forms

const libraryIcon = (path) => `<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="${path}"/></svg>`;
const folderIcon = libraryIcon('M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z');
const fileIcon = libraryIcon('M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zm0 0v6h6M8 13h8m-8 4h6');
const nextIcon = libraryIcon('m9 6 6 6-6 6');

function pickLibraryPdf(work, release, trigger) {
  const dlg = document.getElementById('pdf-library-dialog');
  dlg.innerHTML = `<form method="dialog" class="pdf-library">
    <header class="pdf-library-header">
      <h2 id="pdf-library-title">Browse PDF library</h2>
      <p id="pdf-library-description">Choose a PDF for this printing. The file stays in your library.</p>
      <nav aria-label="Current library folder"><ol data-location></ol></nav>
      <label class="pdf-library-filter">
        ${libraryIcon('M21 21l-4.4-4.4M19 11a8 8 0 1 1-16 0 8 8 0 0 1 16 0')}
        <input type="search" aria-label="Filter this folder" placeholder="Filter this folder…" autocomplete="off" autofocus>
      </label>
    </header>
    <div class="pdf-library-body" data-body>
      <p class="pdf-library-status" data-status role="status"></p>
      <ul class="pdf-library-files" aria-label="Folders and PDF files" data-files></ul>
    </div>
    <footer class="pdf-library-footer">
      <p class="pdf-library-selection" data-selection></p>
      <div class="form-error" role="alert" hidden></div>
      <div class="form-actions">
        <button type="button" class="secondary" data-cancel>Cancel</button>
        <button type="submit" class="primary" disabled>Link PDF</button>
      </div>
    </footer>
  </form>`;
  const form = dlg.querySelector('form');
  const location = form.querySelector('[data-location]');
  const filter = form.querySelector('input[type="search"]');
  const body = form.querySelector('[data-body]');
  const files = form.querySelector('[data-files]');
  const status = form.querySelector('[data-status]');
  const selection = form.querySelector('[data-selection]');
  const error = form.querySelector('.form-error');
  const submit = form.querySelector('[type="submit"]');
  const cancel = form.querySelector('[data-cancel]');
  let loading = false;
  let saving = false;

  const showError = (err) => {
    error.textContent = err.message;
    error.hidden = false;
  };
  const updateSelection = () => {
    const selected = files.querySelector('input:checked');
    const name = selected?.closest('label').querySelector('.pdf-library-name').textContent;
    selection.textContent = name || 'No PDF selected';
    submit.disabled = saving || !selected;
  };
  const applyFilter = () => {
    if (loading) return;
    const query = filter.value.trim().toLowerCase();
    let visible = 0;
    for (const row of files.children) {
      row.hidden = !row.dataset.name.includes(query);
      if (!row.hidden) visible++;
      else if (row.querySelector('input')?.checked) row.querySelector('input').checked = false;
    }
    status.textContent = visible ? '' : query ? 'No names match this filter.' : 'This folder has no folders or PDFs.';
    updateSelection();
  };
  const load = async (target) => {
    loading = true;
    filter.focus();
    const parts = target ? target.split('/') : [];
    location.innerHTML = ['Library', ...parts].map((name, index) => {
      if (parts.length > 3 && index > 0 && index < parts.length - 1) {
        return index === 1 ? `<li aria-hidden="true">${nextIcon}<span>…</span></li>` : '';
      }
      const current = index === parts.length;
      const path = parts.slice(0, index).join('/');
      return `<li>${index ? nextIcon : ''}${current
        ? `<span aria-current="location">${esc(name)}</span>`
        : `<button type="button" data-directory="${esc(path)}">${esc(name)}</button>`}</li>`;
    }).join('');
    files.replaceChildren();
    filter.value = '';
    body.scrollTop = 0;
    files.setAttribute('aria-busy', 'true');
    updateSelection();
    error.hidden = true;
    status.textContent = 'Loading folder…';
    try {
      const { entries } = await api.pdfLibrary(target);
      if (!dlg.open || !form.isConnected) return;
      files.innerHTML = entries.map(entry => {
        const name = `<span class="pdf-library-name">${esc(entry.name)}</span>`;
        return `<li data-name="${esc(entry.name.toLowerCase())}">${entry.directory
          ? `<button type="button" class="pdf-library-row" data-directory="${esc(entry.path)}">${folderIcon}${name}${nextIcon}</button>`
          : `<label class="pdf-library-row"><input type="radio" name="pdf" value="${esc(entry.path)}">${fileIcon}${name}</label>`
        }</li>`;
      }).join('');
      loading = false;
      applyFilter();
    } catch (err) {
      status.textContent = '';
      showError(err);
    } finally {
      loading = false;
      files.removeAttribute('aria-busy');
    }
  };
  const parentOf = (path) => path.split('/').slice(0, -1).join('/');
  filter.oninput = applyFilter;
  filter.onkeydown = (event) => { if (event.key === 'Enter') event.preventDefault(); };
  form.onclick = (event) => {
    const folder = event.target.closest('[data-directory]');
    if (folder && !loading && !saving) load(folder.dataset.directory);
  };
  files.onchange = updateSelection;
  cancel.onclick = () => { if (!saving) dlg.close(); };
  dlg.onclose = () => { if (trigger.isConnected) trigger.focus(); };
  dlg.onkeydown = (event) => {
    if (event.key !== 'Escape' || event.isComposing) return;
    event.preventDefault();
    event.stopPropagation();
    if (!saving) dlg.close();
  };
  dlg.oncancel = (event) => {
    if (form.isConnected && saving) event.preventDefault();
  };
  form.onsubmit = async (event) => {
    event.preventDefault();
    const selected = files.querySelector('input:checked');
    if (!selected || saving) return;
    saving = true;
    submit.textContent = 'Linking…';
    cancel.disabled = true;
    updateSelection();
    error.hidden = true;
    try {
      const updated = await api.linkLibraryPdf(release.id, selected.value);
      dlg.close();
      await refresh(work, updated, 'PDF linked');
      drawer().querySelector(`[data-release="${CSS.escape(release.id)}"] [data-act="browse-pdf"]`)?.focus();
    } catch (err) {
      showError(err);
    } finally {
      saving = false;
      cancel.disabled = false;
      submit.textContent = 'Link PDF';
      updateSelection();
    }
  };
  dlg.showModal();
  const relative = release.pdf_path?.startsWith('library:') ? release.pdf_path.slice('library:'.length) : '';
  load(parentOf(relative));
}

function showForm(title, fieldsHTML, onSubmit) {
  const dlg = document.getElementById('form-dialog');
  dlg.innerHTML = `<form method="dialog">
      <h2>${esc(title)}</h2>
      <div class="form-grid">${fieldsHTML}</div>
      <div class="form-error" hidden></div>
      <div class="form-actions">
        <button type="button" class="secondary" data-cancel>Cancel</button>
        <button type="submit" class="primary">Save</button>
      </div>
    </form>`;
  const form = dlg.querySelector('form');
  dlg.querySelector('[data-cancel]').onclick = () => dlg.close();
  form.onsubmit = async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    form.querySelectorAll('input[type=checkbox]').forEach(c => { data[c.name] = c.checked; });
    for (const k of ['first_year', 'year']) {
      if (k in data) data[k] = data[k] === '' ? null : Number(data[k]);
    }
    for (const [k, v] of Object.entries(data)) if (v === '') data[k] = null;
    try {
      await onSubmit(data);
      dlg.close();
    } catch (err) {
      const box = form.querySelector('.form-error');
      box.textContent = err.message;
      box.hidden = false;
    }
  };
  dlg.showModal();
  form.querySelector('input, select')?.focus();
}

const field = (label, name, value, attrs = '', full = false) =>
  `<label class="${full ? 'full' : ''}">${label}<input name="${name}" value="${esc(value ?? '')}" ${attrs}></label>`;
const select = (label, name, list, value) =>
  `<label>${label}<select name="${name}">${options(list, value)}</select></label>`;

function releaseFields(r, defaults = {}, prefix = '') {
  const v = r || defaults;
  return `
    ${select('Release kind', `${prefix}release_kind`, ctx.meta.release_kinds, v.release_kind || 'Reprint')}
    ${field('Year', `${prefix}year`, v.year, 'type="number" min="1970" max="2100"')}
    ${field('Label (what makes it distinct)', `${prefix}label`, v.label, 'placeholder="e.g. 2012 premium reprint, gold foil cover"', true)}
    ${field('Publisher', `${prefix}publisher`, v.publisher)}
    ${field('Product code', `${prefix}product_code`, v.product_code)}
    ${field('ISBN', `${prefix}isbn`, v.isbn, '', true)}
    <label class="full">Notes<textarea name="${prefix}notes" rows="2">${esc(v.notes || '')}</textarea></label>`;
}

// Multi-select picker: tick existing books to place them inside `set` (untick to take them out).
async function pickBooksForSet(set) {
  const all = await api.books({ sort: 'title', desc: false, contents: true });
  const books = all.filter(b => b.work_id !== set.id && !b.content_count);
  const inSet = new Set((set.contents || []).map(c => c.id));
  const dlg = document.getElementById('form-dialog');
  dlg.innerHTML = `<form method="dialog" class="picker">
      <h2>Books in “${esc(set.title)}”</h2>
      <p class="rmeta">Tick the books that belong in this set. Unticking takes a book out (it isn't deleted).</p>
      <input type="search" class="picker-q" placeholder="Filter, e.g. Game Master's Book" autocomplete="off">
      <div class="picker-list">${books.map(b => `
        <label class="check" data-text="${esc(`${b.title} ${b.edition} ${b.display_year ?? ''}`.toLowerCase())}">
          <input type="checkbox" value="${esc(b.work_id)}" ${inSet.has(b.work_id) ? 'checked' : ''}>
          <span><b>${esc(b.title)}</b> <span class="rmeta">${esc(b.edition)}${b.display_year ? ' · ' + b.display_year : ''}${
            b.parent_id && b.parent_id !== set.id ? ` · in ${esc(b.parent_title)}` : ''}</span></span>
        </label>`).join('')}</div>
      <div class="form-error" hidden></div>
      <div class="form-actions">
        <span class="rmeta picker-count"></span>
        <button type="button" class="secondary" data-cancel>Cancel</button>
        <button type="submit" class="primary">Save</button>
      </div>
    </form>`;
  const form = dlg.querySelector('form');
  const boxes = [...form.querySelectorAll('.picker-list input')];
  const count = () => { form.querySelector('.picker-count').textContent = `${boxes.filter(c => c.checked).length} selected`; };
  count();
  form.addEventListener('change', count);
  form.querySelector('.picker-q').addEventListener('input', (e) => {
    const q = e.target.value.trim().toLowerCase().replace(/[’']/g, '');
    form.querySelectorAll('.picker-list label').forEach(l => {
      l.hidden = q && !l.dataset.text.replace(/[’']/g, '').includes(q);
    });
  });
  form.querySelector('.picker-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') e.preventDefault(); });
  dlg.querySelector('[data-cancel]').onclick = () => dlg.close();
  form.onsubmit = async (e) => {
    e.preventDefault();
    const changes = boxes.filter(c => c.checked !== inSet.has(c.value));
    try {
      for (const c of changes) await api.updateWork(c.value, { parent_id: c.checked ? set.id : null });
      dlg.close();
      await refresh(set, null, changes.length ? `Updated ${changes.length} book${changes.length === 1 ? '' : 's'}` : '');
    } catch (err) {
      const box = form.querySelector('.form-error');
      box.textContent = err.message;
      box.hidden = false;
    }
  };
  dlg.showModal();
  form.querySelector('.picker-q').focus();
}

export async function workForm(work, defaults = {}) {
  const editing = !!work;
  const w = work || defaults;
  const shelfRelease = editing ? work.releases.find(r => r.is_primary) || work.releases[0] : null;
  let sets = [];
  try { sets = (await api.boxsets()).filter(b => b.id !== work?.id); } catch { /* picker just stays empty */ }
  const currentParent = editing ? work.parent?.id : defaults.parent_id;
  const parentPicker = work?.contents?.length ? '' : `
      <label class="full">Part of box set
        <select name="parent_id">
          <option value="">— Not part of a box set —</option>
          ${[['Box sets', sets.filter(b => b.book_type === 'Boxed Set')], ['Other books', sets.filter(b => b.book_type !== 'Boxed Set')]]
            .filter(([, list]) => list.length)
            .map(([label, list]) => `<optgroup label="${label}">${list.map(b =>
              `<option value="${esc(b.id)}" ${b.id === currentParent ? 'selected' : ''}>${esc(b.title)} (${esc(b.edition)}${b.first_year ? ', ' + b.first_year : ''})</option>`).join('')}</optgroup>`).join('')}
        </select>
      </label>`;
  const releaseBlock = editing ? `
      <label class="full" style="margin-top:6px;font-weight:600;color:var(--ink)">Shelf default release details</label>
      ${releaseFields(shelfRelease, {}, 'first_release_')}
      <label class="check"><input type="checkbox" name="first_release_owned_physical" ${shelfRelease.owned_physical ? 'checked' : ''}> Own print copy</label>
      <label class="check"><input type="checkbox" name="first_release_owned_pdf" ${shelfRelease.owned_pdf ? 'checked' : ''}> Own PDF</label>` : `
      <label class="full" style="margin-top:6px;font-weight:600;color:var(--ink)">First release</label>
      ${releaseFields(null, { release_kind: 'Original' })}
      <label class="check"><input type="checkbox" name="owned_physical"> Own print copy</label>`;
  const newSet = !editing && defaults.book_type === 'Boxed Set';
  const title = editing ? 'Edit book' : defaults.parent_id ? 'Add a book inside this box set'
    : newSet ? 'New box set (or collection)' : 'Add a book';
  showForm(title, `
      ${field('Title', 'title', editing ? w.title : '', 'required', true)}
      ${select('Edition', 'edition', ctx.meta.editions, w.edition)}
      ${select('Book type', 'book_type', ctx.meta.book_types, w.book_type)}
      ${field('First published', 'first_year', w.first_year, 'type="number" min="1970" max="2100"')}
      ${field('Setting', 'setting', w.setting, 'placeholder="e.g. Forgotten Realms"')}
      ${newSet ? '' : parentPicker}
      ${editing ? `<label class="full">Notes<textarea name="notes" rows="2">${esc(w.notes || '')}</textarea></label>` : ''}
      ${releaseBlock}`,
    async (d) => {
      const parent_id = 'parent_id' in d ? (d.parent_id || null) : undefined;
      if (editing) {
        const { title, edition, book_type, first_year, setting, notes } = d;
        const body = { title, edition, book_type, first_year, setting, notes };
        if (parent_id !== undefined) body.parent_id = parent_id;
        body.release_id = shelfRelease.id;
        body.release = {
          release_kind: d.first_release_release_kind,
          year: d.first_release_year,
          label: d.first_release_label,
          publisher: d.first_release_publisher,
          product_code: d.first_release_product_code,
          isbn: d.first_release_isbn,
          notes: d.first_release_notes,
          owned_physical: d.first_release_owned_physical,
          owned_pdf: d.first_release_owned_pdf,
        };
        await refresh(work, await api.updateWork(work.id, body), 'Saved');
      } else {
        const { title, edition, book_type, first_year, setting, parent_id: _p, ...rel } = d;
        if (rel.year == null) rel.year = first_year;
        const created = await api.createWork({ title, edition, book_type, first_year, setting, parent_id: parent_id ?? null, release: rel });
        ctx.toast('Book added');
        ctx.onChange();
        renderDrawer(created);
        if (newSet) setTimeout(() => pickBooksForSet(created), 0); // go straight to filling it
      }
    });
}

function releaseForm(work, rel) {
  showForm(rel ? 'Edit release' : `Add a release of “${work.title}”`, releaseFields(rel), async (d) => {
    const updated = rel ? await api.updateRelease(rel.id, d) : await api.createRelease(work.id, d);
    await refresh(work, updated, rel ? 'Saved' : 'Release added');
  });
}
