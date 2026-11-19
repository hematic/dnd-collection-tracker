// Rendering of the shelf, grid and table views.
export const EDITION_COLORS = {
  'OD&D': '#8c6d3f',
  'Basic': '#2f5f9e',
  'AD&D 1e': '#a2462a',
  'AD&D 2e': '#3d3d3d',
  '3.0': '#7a1f1f',
  '3.5': '#5a2a6e',
  '4e': '#1f5a7a',
  '5e (2014)': '#9b2c1f',
  '5e (2024)': '#2c6e4f',
  'D&D Companions': '#756039',
  'Other': '#6b6b6b',
};

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export { esc };

export function coverHTML(b) {
  if (b.cover_url) return `<img src="${esc(b.cover_url)}" alt="" loading="lazy" decoding="async">`;
  const color = EDITION_COLORS[b.edition] || '#555';
  return `<div class="placeholder" style="--ed:${color}">
      <span class="ph-ed">${esc(b.edition)}</span>
      <span class="ph-title">${esc(b.title)}</span>
      <span class="ph-code">${esc(b.product_code || '')}</span>
    </div>`;
}

function ribbonHTML(kind) {
  if (!kind || kind === 'Original') return '';
  const short = { 'Premium Reprint': 'PREMIUM', 'Special Edition': 'SPECIAL', 'Alternate Cover': 'ALT COVER' }[kind] || kind.toUpperCase();
  return `<span class="ribbon k-${kind.replace(/\s+/g, '-')}">${esc(short)}</span>`;
}

function tooltip(b) {
  const parts = [b.title, `${b.edition} · ${b.book_type}`, [b.display_year, b.release_kind, b.label].filter(Boolean).join(' · ')];
  if (b.product_code) parts.push(`Code ${b.product_code}`);
  const owned = [b.own_hc && 'hardcover', b.own_pdf && 'PDF'].filter(Boolean);
  if (owned.length) parts.push(`Owned: ${owned.join(' + ')}`);
  if (b.release_count > 1) parts.push(`${b.release_count} releases of this book`);
  if (b.content_count) parts.push(`Box set containing ${b.content_count} books`);
  if (b.parent_title) parts.push(`Part of: ${b.parent_title}`);
  parts.push(b.pdf_release_id ? 'Click to open PDF' : 'Click for details');
  return parts.join('\n');
}

function ownedBadge(b) {
  const parts = [b.own_hc && 'HC', b.own_pdf && 'PDF'].filter(Boolean);
  if (!parts.length) return '';
  const cls = b.own_hc && b.own_pdf ? 'both' : b.own_hc ? 'hc' : 'pdf';
  return `<span class="badge own ${cls}">${parts.join(' + ')}</span>`;
}

function bookCard(b, showAll) {
  const chips = [
    b.content_count ? `<span class="badge more box" title="Box set with ${b.content_count} books inside">📦 ${b.content_count} books</span>` : '',
    !showAll && b.release_count > 1 ? `<span class="badge more" title="${b.release_count} releases (printings/reprints) of this book">${b.release_count} rel.</span>` : '',
  ].join('');
  const more = chips ? `<span class="chips">${chips}</span>` : '';
  return `<div class="book" data-work="${esc(b.work_id)}" data-release="${esc(b.id)}" data-pdf-release="${esc(b.pdf_release_id || '')}"
              role="button" tabindex="0" title="${esc(tooltip(b))}">
      <span class="cover">${coverHTML(b)}
        ${ribbonHTML(b.release_kind)}
        ${more}
        <span class="badges">
          ${b.display_year ? `<span class="badge">${esc(b.display_year)}</span>` : ''}
          ${ownedBadge(b)}
        </span>
      </span>
      <div class="caption" data-info><div class="t">${esc(b.title)}</div>
        <div class="s">${esc(b.edition)} · ${esc(b.book_type)}${b.release_kind !== 'Original' ? ' · ' + esc(b.release_kind) : ''}</div></div>
    </div>`;
}

// How many covers fit across one shelf at the current window width.
export function booksPerRow(el) {
  const css = getComputedStyle(document.documentElement);
  const coverW = parseFloat(css.getPropertyValue('--cover-w')) || 128;
  const gap = 14, pad = 28; // keep in sync with .shelf-row gap / .shelf-body padding
  return Math.max(1, Math.floor((el.clientWidth - pad + gap) / (coverW + gap)));
}

// Title label on the shelf edge under each book; clicking it opens the details.
function shelfTag(b) {
  return `<div class="shelf-tag-slot">
      <button class="shelf-tag" data-info data-work="${esc(b.work_id)}" data-release="${esc(b.id)}" title="Details: ${esc(b.title)}">
        <span class="t">${esc(b.title)}</span>
        ${b.parent_title ? `<span class="s">in ${esc(b.parent_title)}</span>` : ''}
      </button>
    </div>`;
}

function shelfRows(list, perRow, showAll) {
  let html = '';
  for (let i = 0; i < list.length; i += perRow) {
    const row = list.slice(i, i + perRow);
    html += `<div class="shelf-unit">
      <div class="shelf-body"><div class="shelf-row">${row.map(b => bookCard(b, showAll)).join('')}</div></div>
      <div class="shelf-plank"></div>
      <div class="shelf-tags">${row.map(shelfTag).join('')}</div>
    </div>`;
  }
  return html;
}

export function renderShelves(el, books, { editions, showAll, grouped, collapsed }) {
  const perRow = booksPerRow(el);
  if (!grouped) {
    el.innerHTML = `<section class="shelf">${shelfRows(books, perRow, showAll)}</section>`;
    return;
  }
  // Newest RPG edition first; non-edition shelves stay at the bottom.
  const companionShelves = ['D&D Companions', 'Other'];
  const order = editions.filter(e => !companionShelves.includes(e)).reverse()
    .concat(companionShelves.filter(e => editions.includes(e)));
  const byEd = new Map(order.map(e => [e, []]));
  for (const b of books) (byEd.get(b.edition) || byEd.set(b.edition, []).get(b.edition)).push(b);
  el.innerHTML = [...byEd].filter(([, list]) => list.length).map(([ed, list]) => {
    const color = EDITION_COLORS[ed] || '#555';
    const hc = list.filter(b => b.own_hc).length;
    const pdf = list.filter(b => b.own_pdf).length;
    return `
    <section class="shelf ${collapsed.has(ed) ? 'collapsed' : ''}" data-edition="${esc(ed)}" style="--ed:${color}">
      <div class="shelf-head">
        <h2>${esc(ed)}</h2>
        <span class="count">${list.length} ${showAll ? 'release' : 'book'}${list.length === 1 ? '' : 's'}
          ${hc || pdf ? ` · ${hc} HC · ${pdf} PDF` : ''}</span>
        <button data-collapse="${esc(ed)}" aria-expanded="${!collapsed.has(ed)}">${collapsed.has(ed) ? 'Show ▸' : 'Hide ▾'}</button>
      </div>
      <div class="shelf-rows">${shelfRows(list, perRow, showAll)}</div>
    </section>`;
  }).join('');
}

export function renderGrid(el, books, { showAll }) {
  el.innerHTML = `<div class="grid">${books.map(b => bookCard(b, showAll)).join('')}</div>`;
}

const COLS = [
  ['title', 'Title', b => b.title],
  ['edition', 'Edition', b => b.edition],
  ['type', 'Type', b => b.book_type],
  ['year', 'Year', b => b.display_year ?? ''],
  [null, 'Release', b => `<span class="kind-chip">${esc(b.release_kind)}</span>${b.label ? ' ' + esc(b.label) : ''}`, true],
  ['code', 'Code', b => b.product_code || ''],
  [null, 'Owned', b => [b.own_hc && 'HC', b.own_pdf && (b.pdf_release_id ? 'PDF' : 'PDF (unlinked)')].filter(Boolean).join(' + ')],
];

export function renderTable(el, books, { sort, desc }) {
  el.innerHTML = `<div class="table-wrap"><table class="books">
    <thead><tr>${COLS.map(([key, label]) => `<th ${key ? `data-sort="${key}"` : ''}>${label}${key === sort ? (desc ? ' ↓' : ' ↑') : ''}</th>`).join('')}</tr></thead>
    <tbody>${books.map(b => `<tr data-work="${esc(b.work_id)}" data-release="${esc(b.id)}">${COLS.map(([key, , fn, raw]) =>
      `<td class="${key === 'title' ? 'title' : ''}">${raw ? fn(b) : esc(fn(b))}</td>`).join('')}</tr>`).join('')}</tbody>
  </table></div>`;
}
