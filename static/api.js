// Thin fetch wrapper around the tracker's JSON API.
async function request(method, url, body, isForm = false) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    if (isForm) opts.body = body;
    else { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  }
  const res = await fetch(url, opts);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      if (j.detail) msg = typeof j.detail === 'string' ? j.detail : j.detail.map(d => d.msg).join('; ');
    } catch { /* not JSON */ }
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

const enc = encodeURIComponent;

export const api = {
  meta: () => request('GET', '/api/meta'),
  boxsets: () => request('GET', '/api/boxsets'),
  books: (params) => request('GET', '/api/books?' + new URLSearchParams(params)),
  searchPdfText: (params) => request('GET', '/api/search/pdf?' + new URLSearchParams(params)),
  exportPdfSearchUrl: (params) => '/api/search/pdf.csv?' + new URLSearchParams(params),
  pdfIndexStatus: () => request('GET', '/api/pdf-index'),
  startPdfIndex: (mode) => request('POST', `/api/pdf-index?mode=${enc(mode)}`),
  retryPdfIndex: (id) => request('POST', `/api/pdf-index/${enc(id)}/retry`),
  work: (id) => request('GET', `/api/works/${enc(id)}`),
  createWork: (body) => request('POST', '/api/works', body),
  updateWork: (id, body) => request('PATCH', `/api/works/${enc(id)}`, body),
  deleteWork: (id) => request('DELETE', `/api/works/${enc(id)}`),
  createRelease: (workId, body) => request('POST', `/api/works/${enc(workId)}/releases`, body),
  updateRelease: (id, body) => request('PATCH', `/api/releases/${enc(id)}`, body),
  deleteRelease: (id) => request('DELETE', `/api/releases/${enc(id)}`),
  linkPdf: (id, path) => request('PATCH', `/api/releases/${enc(id)}/pdf`, { path }),
  pdfLibrary: (directory) => request('GET', '/api/pdf-library?' + new URLSearchParams({ directory })),
  linkLibraryPdf: (id, library_path) => request('PATCH', `/api/releases/${enc(id)}/pdf`, { library_path }),
  uploadCover: (id, file) => {
    const fd = new FormData();
    fd.append('file', file);
    return request('POST', `/api/releases/${enc(id)}/cover`, fd, true);
  },
  resetCover: (id) => request('DELETE', `/api/releases/${enc(id)}/cover`),
  openExternal: (id) => request('POST', `/api/releases/${enc(id)}/open-external`),
  bulk: (body) => request('POST', '/api/bulk', body),
  pdfUrl: (id) => `/pdf/${enc(id)}`,
};
