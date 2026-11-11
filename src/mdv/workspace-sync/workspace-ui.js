// "Workspace data" browser for MDV in Verily Workbench.
// Injected into MDV's pages by nginx. Lets users browse the workspace's buckets and open a file or
// MDV project with one click; the server links or converts it from the bucket (no upload) and MDV
// opens the result. Backend: workspace_ui.py, routed at /_workspace/.
(() => {
  if (window.__mdvWorkspaceData) return;
  window.__mdvWorkspaceData = true;

  const API = '/_workspace/api';
  const SUPPORTED = 'MDV projects, AnnData (.h5ad), MuData (.h5mu), VCF (.vcf, .vcf.gz), and tables (.csv, .tsv)';
  const ICONS = {
    bucket: 'M4 6h16v3H4zM5 10h14l-1 9H6z',
    folder: 'M3 6a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z',
    project: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
    file: 'M6 3h8l4 4v14H6zM14 3v4h4',
  };

  const css = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: Roboto, system-ui, -apple-system, "Segoe UI", sans-serif; }
    .fab { position: fixed; right: 16px; bottom: 16px; z-index: 2147483000; display: flex;
      align-items: center; gap: 8px; height: 40px; padding: 0 14px 0 12px; border: 0;
      border-radius: 20px; background: #1565c0; color: #fff; font-size: 14px; font-weight: 500;
      cursor: pointer; box-shadow: 0 3px 8px rgba(0,0,0,.3); opacity: .92; }
    .fab:hover { opacity: 1; background: #0d47a1; }
    .fab svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.8; }
    .backdrop { position: fixed; inset: 0; z-index: 2147483001; background: rgba(0,0,0,.4);
      display: flex; align-items: center; justify-content: center; }
    .dialog { width: min(760px, 94vw); max-height: 84vh; display: flex; flex-direction: column;
      background: #fff; color: #212121; border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,.35); }
    header { display: flex; align-items: center; padding: 16px 20px 8px; }
    h2 { margin: 0; font-size: 18px; font-weight: 500; flex: 1; }
    .close { border: 0; background: none; font-size: 22px; line-height: 1; cursor: pointer; color: #555; }
    .crumbs { padding: 4px 20px 10px; font-size: 13px; color: #555; border-bottom: 1px solid #e0e0e0; }
    .crumbs a { color: #1565c0; cursor: pointer; text-decoration: none; }
    .crumbs a:hover { text-decoration: underline; }
    .list { overflow: auto; flex: 1; min-height: 160px; }
    .row { display: flex; align-items: center; gap: 12px; padding: 9px 20px; font-size: 14px;
      border-bottom: 1px solid #f2f2f2; }
    .row.nav { cursor: pointer; }
    .row.nav:hover { background: #f5f8fd; }
    .row.dim { color: #9e9e9e; }
    .row svg { width: 20px; height: 20px; flex: none; fill: none; stroke: #5f6368; stroke-width: 1.6; }
    .row.project svg { stroke: #1565c0; }
    .name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .meta { font-size: 12px; color: #757575; white-space: nowrap; }
    .open { border: 1px solid #1565c0; background: #fff; color: #1565c0; border-radius: 4px;
      padding: 4px 12px; font-size: 13px; font-weight: 500; cursor: pointer; }
    .open:hover { background: #1565c0; color: #fff; }
    .empty, .status { padding: 28px 20px; font-size: 14px; color: #424242; line-height: 1.5; }
    .status strong { display: block; font-size: 15px; margin-bottom: 6px; }
    .error { color: #c62828; }
    .spinner { width: 22px; height: 22px; border: 3px solid #bbdefb; border-top-color: #1565c0;
      border-radius: 50%; animation: spin 1s linear infinite; margin-bottom: 12px; }
    @keyframes spin { to { transform: rotate(360deg); } }
    details { margin-top: 12px; font-size: 12px; }
    pre { white-space: pre-wrap; background: #f5f5f5; padding: 8px; max-height: 180px; overflow: auto; }
    footer { padding: 10px 20px 14px; font-size: 12px; color: #757575; border-top: 1px solid #e0e0e0; }
    .loglink { color: #1565c0; cursor: pointer; text-decoration: underline; }
    .log { margin: 0 20px 16px; max-height: 50vh; font: 12px/1.45 ui-monospace, Menlo, Consolas, monospace; }
    .back { margin-top: 14px; }
  `;

  const host = document.createElement('div');
  host.id = 'mdv-workspace-data';
  const root = host.attachShadow({ mode: 'open' });
  root.innerHTML = `<style>${css}</style>`;

  const el = (tag, attrs = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'onclick') node.onclick = v; else node.setAttribute(k, v);
    }
    for (const c of children) node.append(c);
    return node;
  };
  const icon = (type) => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', ICONS[type] || ICONS.file);
    svg.append(p);
    return svg;
  };
  const size = (n) => {
    if (n == null) return '';
    const u = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
  };
  const mmss = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  const api = async (path, opts) => {
    const r = await fetch(API + path, { cache: 'no-store', ...opts });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
    return body;
  };

  const fab = el('button', { class: 'fab', title: 'Open data from this Workbench workspace' },
    icon('folder'), 'Workspace data');
  const crumbs = el('div', { class: 'crumbs' });
  const list = el('div', { class: 'list' });
  const dialog = el('div', { class: 'dialog', role: 'dialog', 'aria-modal': 'true',
    'aria-label': 'Open workspace data' },
    el('header', {}, el('h2', {}, 'Open workspace data'),
      el('button', { class: 'close', 'aria-label': 'Close', onclick: () => close() }, '×')),
    crumbs, list,
    el('footer', {}, `Opens ${SUPPORTED} directly from your workspace buckets, without uploading. `
      + 'Bucket data is read-only in MDV. ', el('a', { class: 'loglink', onclick: () => showLog() }, 'Activity log')));
  const backdrop = el('div', { class: 'backdrop' }, dialog);
  backdrop.addEventListener('click', (e) => { if (e.target === backdrop) close(); });
  root.append(fab);

  // Reopen at the last folder, also after MDV navigates to another page.
  const LAST_FOLDER = 'mdvWorkspaceDataFolder';
  let busy = false;
  let current = sessionStorage.getItem(LAST_FOLDER) || '';

  function open() {
    if (!backdrop.isConnected) root.append(backdrop);
    if (!busy) browse(current);
  }
  function close() {
    if (!busy) backdrop.remove();
  }
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
  fab.onclick = open;

  function renderCrumbs(path) {
    crumbs.replaceChildren(el('a', { onclick: () => browse('') }, 'Workspace'));
    let acc = '';
    for (const part of path ? path.split('/') : []) {
      acc = acc ? `${acc}/${part}` : part;
      const target = acc;
      crumbs.append(' › ', el('a', { onclick: () => browse(target) }, part));
    }
  }

  async function browse(path) {
    current = path;
    sessionStorage.setItem(LAST_FOLDER, path);
    renderCrumbs(path);
    list.replaceChildren(el('div', { class: 'status' }, el('div', { class: 'spinner' }), 'Loading…'));
    let data;
    try {
      data = await api(`/list?path=${encodeURIComponent(path)}`);
    } catch (e) {
      if (path) { browse(''); return; }  // the folder is gone or its bucket isn't mounted
      list.replaceChildren(el('div', { class: 'status error' }, `Couldn't list workspace buckets: ${e.message}`));
      return;
    }
    if (!data.entries.length) {
      list.replaceChildren(el('div', { class: 'empty' }, path
        ? 'This folder is empty.'
        : 'No workspace buckets are available to MDV yet. Buckets are mounted when the app starts: '
          + 'wait a minute after starting the app, or restart the app if you added the bucket after it started.'));
      return;
    }
    list.replaceChildren(...data.entries.map(rowFor));
    if (data.truncated) list.append(el('div', { class: 'empty' }, 'Showing the first 2,000 items.'));
  }

  function rowFor(entry) {
    if (entry.type === 'bucket' || entry.type === 'folder') {
      return el('div', { class: 'row nav', onclick: () => browse(entry.path), title: entry.path },
        icon(entry.type), el('span', { class: 'name' }, entry.name));
    }
    const openBtn = el('button', { class: 'open', onclick: (e) => { e.stopPropagation(); importPath(entry); } }, 'Open');
    if (entry.type === 'project') {
      return el('div', { class: 'row project', title: entry.path }, icon('project'),
        el('span', { class: 'name' }, entry.name), el('span', { class: 'meta' }, 'MDV project'), openBtn);
    }
    if (!entry.importable) {
      return el('div', { class: 'row dim', title: 'MDV can\'t open this file type' }, icon('file'),
        el('span', { class: 'name' }, entry.name), el('span', { class: 'meta' }, size(entry.size)));
    }
    return el('div', { class: 'row', title: entry.path }, icon('file'),
      el('span', { class: 'name' }, entry.name), el('span', { class: 'meta' }, size(entry.size)), openBtn);
  }

  async function importPath(entry) {
    busy = true;
    const verb = entry.type === 'project' ? 'Adding' : 'Converting';
    const title = el('strong', {}, `${verb} ${entry.name}…`);
    const note = el('div', {}, entry.type === 'project'
      ? 'The project stays in your bucket; MDV reads it from there.'
      : `MDV is converting the file from your bucket. Large files can take several minutes; you can keep this open.`);
    const timer = el('div', { class: 'meta' });
    const logPre = el('pre');
    list.replaceChildren(el('div', { class: 'status' }, el('div', { class: 'spinner' }), title, note, timer,
      el('details', {}, el('summary', {}, 'Details'), logPre)));
    try {
      let job = await api('/import', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: entry.path }) });
      while (job.state === 'running') {
        timer.textContent = `Elapsed ${mmss(job.elapsed || 0)}`;
        logPre.textContent = (job.log || []).join('\n');
        await new Promise((r) => setTimeout(r, 1500));
        job = await api(`/jobs/${job.id}`);
      }
      if (job.state !== 'done') throw new Error(job.message || 'Import failed');
      title.textContent = `Opening ${job.project_name}…`;
      location.href = `/project/${job.project_id}/`;
    } catch (e) {
      busy = false;
      list.replaceChildren(el('div', { class: 'status' },
        el('strong', { class: 'error' }, `Couldn't open ${entry.name}`), el('div', {}, e.message),
        el('details', {}, el('summary', {}, 'Details'), el('pre', {}, logPre.textContent || 'No details.')),
        el('button', { class: 'open back', onclick: () => browse(current) }, 'Back')));
    }
  }

  // The app's data activity (what was linked, converted or removed), for troubleshooting.
  async function showLog() {
    if (busy) return;
    crumbs.replaceChildren(el('a', { onclick: () => browse(current) }, '‹ Back'), '  Activity log');
    const pre = el('pre', { class: 'log' }, 'Loading…');
    list.replaceChildren(pre);
    try {
      const r = await fetch('/_workspace-sync.log', { cache: 'no-store' });
      const lines = r.ok ? (await r.text()).trimEnd().split('\n') : [];
      pre.textContent = lines.length ? lines.slice(-300).join('\n') : 'No activity yet.';
      pre.scrollTop = pre.scrollHeight;
    } catch (e) {
      pre.textContent = `Couldn't load the activity log: ${e.message}`;
    }
  }

  const mount = () => document.body.append(host);
  if (document.body) mount(); else document.addEventListener('DOMContentLoaded', mount);
})();
