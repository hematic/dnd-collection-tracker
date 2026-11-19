// Select mode: pick several books (click / shift-click) and change one property on all of them.
import { api } from './api.js';
import { esc } from './shelf.js';

let ctx = null;                 // { meta, toast, reload }
let on = false;
const picked = new Map();       // release id -> work id
let lastClicked = null;         // release id, for shift-click ranges

const $ = (s) => document.querySelector(s);
const items = () => [...document.querySelectorAll('#content [data-release]')];
const orderedIds = () => [...new Set(items().map(el => el.dataset.release))];

export const isSelecting = () => on;

export function initSelect(context) {
  ctx = context;
  const bar = document.createElement('div');
  bar.id = 'bulk-bar';
  bar.className = 'bulk-bar';
  bar.hidden = true;
  bar.innerHTML = `
    <span class="bulk-count"></span>
    <button class="secondary" data-bulk="all">Select all shown</button>
    <button class="secondary" data-bulk="clear">Clear</button>
    <button class="primary" data-bulk="edit">Change a property…</button>
    <button class="secondary" data-bulk="done">Done</button>`;
  document.body.append(bar);
  bar.addEventListener('click', (e) => {
    const act = e.target.closest('[data-bulk]')?.dataset.bulk;
    if (act === 'all') { items().forEach(el => picked.set(el.dataset.release, el.dataset.work)); paint(); }
    if (act === 'clear') { picked.clear(); paint(); }
    if (act === 'edit') editDialog();
    if (act === 'done') setMode(false);
  });
  $('#select-mode').addEventListener('click', () => setMode(!on));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && on && !$('#form-dialog').open && $('#drawer').hidden) setMode(false);
  });
}

export function setMode(value) {
  on = value;
  if (!on) { picked.clear(); lastClicked = null; }
  document.body.classList.toggle('selecting', on);
  $('#select-mode').classList.toggle('active', on);
  $('#select-mode').textContent = on ? '✓ Selecting' : 'Select';
  $('#bulk-bar').hidden = !on;
  paint();
}

// Called for every click on a book while select mode is on.
export function clickItem(e, item) {
  const id = item.dataset.release;
  if (e.shiftKey && lastClicked) {
    const ids = orderedIds();
    const [a, b] = [ids.indexOf(lastClicked), ids.indexOf(id)].sort((x, y) => x - y);
    if (a >= 0) {
      for (const rid of ids.slice(a, b + 1)) {
        const el = document.querySelector(`#content [data-release="${CSS.escape(rid)}"]`);
        picked.set(rid, el.dataset.work);
      }
    }
  } else if (picked.has(id)) {
    picked.delete(id);
  } else {
    picked.set(id, item.dataset.work);
  }
  lastClicked = id;
  paint();
}

// Re-apply the selected look after every render.
export function paint() {
  items().forEach(el => el.classList.toggle('selected', on && picked.has(el.dataset.release)));
  const n = picked.size;
  const bar = $('#bulk-bar');
  bar.querySelector('.bulk-count').textContent = n
    ? `${n} selected` : 'Click books to select them (shift-click for a range)';
  bar.querySelector('[data-bulk="edit"]').disabled = !n;
  bar.querySelector('[data-bulk="clear"]').disabled = !n;
}

// ---------------------------------------------------------------- bulk edit dialog

const yesNo = '<select name="v"><option value="1">Yes</option><option value="0">No</option></select>';

async function editDialog() {
  const { meta } = ctx;
  let sets = [];
  try { sets = await api.boxsets(); } catch { /* picker stays empty */ }
  const opts = (list) => list.map(v => `<option>${esc(v)}</option>`).join('');
  const FIELDS = {
    edition: ['Edition', `<select name="v">${opts(meta.editions)}</select>`, v => ({ work: { edition: v } })],
    book_type: ['Book type', `<select name="v">${opts(meta.book_types)}</select>`, v => ({ work: { book_type: v } })],
    first_year: ['First published (year)', '<input name="v" type="number" min="1970" max="2100" placeholder="blank = clear">',
      v => ({ work: { first_year: v === '' ? null : Number(v) } })],
    setting: ['Setting', '<input name="v" placeholder="e.g. Forgotten Realms (blank = clear)">', v => ({ work: { setting: v || null } })],
    parent_id: ['Part of box set', `<select name="v"><option value="">— Not part of a box set —</option>${
      sets.map(b => `<option value="${esc(b.id)}">${esc(b.title)} (${esc(b.edition)})</option>`).join('')}</select>`,
      v => ({ work: { parent_id: v || null } })],
    publisher: ['Publisher (of the selected release)', '<input name="v" placeholder="e.g. Kobold Press">', v => ({ release: { publisher: v || null } })],
    owned_physical: ['Own print copy (selected release)', yesNo, v => ({ release: { owned_physical: v === '1' } })],
    owned_pdf: ['Own PDF (selected release)', yesNo, v => ({ release: { owned_pdf: v === '1' } })],
  };
  const releaseIds = [...picked.keys()];
  const workIds = [...new Set(picked.values())];
  const dlg = $('#form-dialog');
  dlg.innerHTML = `<form method="dialog" class="bulk-form">
      <h2>Change ${workIds.length} book${workIds.length === 1 ? '' : 's'}</h2>
      <div class="form-grid">
        <label class="full">Property<select name="field">${
          Object.entries(FIELDS).map(([k, [label]]) => `<option value="${k}">${esc(label)}</option>`).join('')}</select></label>
        <label class="full">New value<span class="bulk-value"></span></label>
      </div>
      <div class="form-error" hidden></div>
      <div class="form-actions">
        <button type="button" class="secondary" data-cancel>Cancel</button>
        <button type="submit" class="primary">Apply to ${workIds.length}</button>
      </div>
    </form>`;
  const form = dlg.querySelector('form');
  const showValue = () => { form.querySelector('.bulk-value').innerHTML = FIELDS[form.field.value][1]; };
  form.field.addEventListener('change', showValue);
  showValue();
  dlg.querySelector('[data-cancel]').onclick = () => dlg.close();
  form.onsubmit = async (e) => {
    e.preventDefault();
    const [label, , build] = FIELDS[form.field.value];
    const change = build(form.v.value.trim());
    try {
      await api.bulk({ work_ids: workIds, release_ids: releaseIds, ...change });
      dlg.close();
      ctx.toast(`${label.replace(/ \(.*\)$/, '')} updated on ${workIds.length} book${workIds.length === 1 ? '' : 's'}`);
      ctx.reload();
    } catch (err) {
      const box = form.querySelector('.form-error');
      box.textContent = err.message;
      box.hidden = false;
    }
  };
  dlg.showModal();
}
