// "Open from workspace" for MDV in Verily Workbench.
//
// Injected into MDV's pages by nginx. Adds an "Open from workspace" card to MDV's project catalog
// and a matching button to the project toolbar, built from MDV's own elements so they look and
// behave like the rest of MDV. They open a dialog showing the Workbench workspace's resources the
// way Workbench does (Workbench folders, Cloud Storage buckets with their type, stewardship and
// description). Opening a file or MDV project links or converts it on the server straight from the
// bucket (no upload), then MDV opens the result. Backend: workspace_ui.py, routed at /_workspace/.
(() => {
  if (window.__mdvWorkspaceData) return;
  window.__mdvWorkspaceData = true;

  const API = '/_workspace/api';
  const LABEL = 'Open from workspace';
  const LAST_FOLDER = 'mdvWorkspaceDataFolder';
  const KIND_LABELS = { anndata: 'AnnData', mudata: 'MuData', vcf: 'VCF', table: 'Table' };
  const PATHS = {
    // Material icons, as used by MDV (MUI).
    folderOpen: 'M20 6h-8l-2-2H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2m0 12H4V8h16z',
    folder: 'M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8z',
    project: 'M3 13h8V3H3zm0 8h8v-6H3zm10 0h8V11h-8zm0-18v6h8V3z',
    file: 'M6 2c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm7 7V3.5L18.5 9z',
    close: 'M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z',
    error: 'M11 15h2v2h-2zm0-8h2v6h-2zm.99-5C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2M12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8',
    // Workbench's Cloud Storage icon.
    bucket: 'M20 11H4V4H20V11ZM20 20H4V13H20V20ZM16 8.5C15.4477 8.5 15 8.05225 15 7.5C15 6.9477 15.4477 6.5 16 6.5C16.5523 6.5 17 6.9477 17 7.5C17 8.05225 16.5523 8.5 16 8.5ZM7 8H13V7H7V8ZM16 17.5C15.4477 17.5 15 17.0522 15 16.5C15 15.9477 15.4477 15.5 16 15.5C16.5523 15.5 17 15.9477 17 16.5C17 17.0522 16.5523 17.5 16 17.5ZM7 17H13V16H7V17Z',
  };

  // MUI default palettes, matching MDV's light and dark themes (<html class="light|dark">).
  const THEMES = {
    light: {
      paper: '#fff', paperImage: 'none', text: 'rgba(0,0,0,.87)', text2: 'rgba(0,0,0,.6)',
      disabled: 'rgba(0,0,0,.38)', divider: 'rgba(0,0,0,.12)', icon: 'rgba(0,0,0,.54)',
      hover: 'rgba(0,0,0,.04)', primary: '#1976d2', primaryHover: '#1565c0', onPrimary: '#fff',
      selected: 'rgba(25,118,210,.08)', selectedHover: 'rgba(25,118,210,.12)',
      track: 'rgb(167,202,237)', code: 'rgba(0,0,0,.04)',
      errorBg: 'rgb(253,237,237)', errorText: 'rgb(95,33,32)', errorIcon: '#d32f2f',
    },
    dark: {
      paper: '#121212', paperImage: 'linear-gradient(rgba(255,255,255,.16), rgba(255,255,255,.16))',
      text: '#fff', text2: 'rgba(255,255,255,.7)', disabled: 'rgba(255,255,255,.5)',
      divider: 'rgba(255,255,255,.12)', icon: '#fff', hover: 'rgba(255,255,255,.08)',
      primary: '#90caf9', primaryHover: '#42a5f5', onPrimary: 'rgba(0,0,0,.87)',
      selected: 'rgba(144,202,249,.16)', selectedHover: 'rgba(144,202,249,.24)',
      track: 'rgb(58,81,99)', code: 'rgba(255,255,255,.06)',
      errorBg: 'rgb(22,11,11)', errorText: 'rgb(244,199,199)', errorIcon: '#f44336',
    },
  };

  const css = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: Roboto, Helvetica, Arial, sans-serif; }
    .backdrop { position: fixed; inset: 0; z-index: 1300; background: rgba(0,0,0,.5);
      display: flex; align-items: center; justify-content: center; }
    .paper { display: flex; flex-direction: column; width: min(720px, calc(100% - 64px));
      height: min(640px, calc(100% - 64px)); background-color: var(--paper);
      background-image: var(--paperImage); color: var(--text); border-radius: 4px;
      box-shadow: 0 11px 15px -7px rgba(0,0,0,.2), 0 24px 38px 3px rgba(0,0,0,.14),
        0 9px 46px 8px rgba(0,0,0,.12); outline: none; }
    .title { display: flex; align-items: flex-start; padding: 16px 12px 8px 24px; }
    .title h2 { margin: 0; font-size: 20px; font-weight: 500; line-height: 1.6; letter-spacing: .0075em; }
    .title .sub { font-size: 14px; color: var(--text2); line-height: 1.43; }
    .grow { flex: 1; min-width: 0; }
    .iconbtn { border: 0; background: none; color: var(--icon); width: 40px; height: 40px;
      border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; }
    .iconbtn:hover { background: var(--hover); }
    svg { width: 24px; height: 24px; fill: currentColor; flex: none; }
    .crumbs { padding: 0 24px 12px; font-size: 16px; line-height: 1.5; color: var(--text2);
      display: flex; flex-wrap: wrap; align-items: center; border-bottom: 1px solid var(--divider); }
    .crumbs a { color: inherit; cursor: pointer; text-decoration: none; }
    .crumbs a:hover { text-decoration: underline; }
    .crumbs .sep { margin: 0 8px; }
    .crumbs .current { color: var(--text); }
    .content { flex: 1; overflow: auto; position: relative; }
    ul { list-style: none; margin: 0; padding: 8px 0; }
    li { display: flex; align-items: center; padding: 8px 24px; cursor: pointer; user-select: none; outline: none; }
    li:hover { background: var(--hover); }
    li.selected { background: var(--selected); }
    li.selected:hover { background: var(--selectedHover); }
    li:focus-visible { background: var(--hover); }
    li.disabled { cursor: default; opacity: .38; }
    li.disabled:hover { background: none; }
    li .icon { min-width: 56px; color: var(--icon); display: flex; }
    li.project .icon, li.bucket .icon { color: var(--primary); }
    .itemtext { flex: 1; min-width: 0; }
    .primary { font-size: 16px; line-height: 1.5; letter-spacing: .00938em; overflow: hidden;
      text-overflow: ellipsis; white-space: nowrap; }
    .secondary { font-size: 14px; line-height: 1.43; color: var(--text2); overflow: hidden;
      text-overflow: ellipsis; white-space: nowrap; }
    .empty { padding: 48px 32px; text-align: center; font-size: 14px; color: var(--text2); line-height: 1.6; }
    .actions { display: flex; align-items: center; gap: 8px; padding: 8px; border-top: 1px solid var(--divider); }
    .btn { font-size: 14px; font-weight: 500; letter-spacing: .02857em; line-height: 1.75;
      padding: 6px 16px; border-radius: 4px; border: 0; cursor: pointer; background: none; color: var(--primary); }
    .btn.text { padding: 6px 8px; }
    .btn:hover { background: var(--selected); }
    .btn.contained { background: var(--primary); color: var(--onPrimary);
      box-shadow: 0 3px 1px -2px rgba(0,0,0,.2), 0 2px 2px 0 rgba(0,0,0,.14), 0 1px 5px 0 rgba(0,0,0,.12); }
    .btn.contained:hover { background: var(--primaryHover); }
    .btn:disabled, .btn.contained:disabled { cursor: default; color: var(--disabled); background: none; box-shadow: none; }
    .btn.contained:disabled { background: var(--divider); }
    .progress { position: absolute; top: 0; left: 0; right: 0; height: 4px; overflow: hidden; background: var(--track); }
    .progress::before { content: ""; position: absolute; top: 0; bottom: 0; background: var(--primary);
      animation: indeterminate 2.1s cubic-bezier(.65,.815,.735,.395) infinite; }
    @keyframes indeterminate { 0% { left: -35%; right: 100%; } 60% { left: 100%; right: -90%; } 100% { left: 100%; right: -90%; } }
    .status { padding: 32px 24px; }
    .status .h { font-size: 16px; line-height: 1.5; margin-bottom: 4px; }
    .status .b { font-size: 14px; line-height: 1.43; color: var(--text2); }
    .alert { display: flex; gap: 12px; padding: 6px 16px; border-radius: 4px; margin: 24px;
      background: var(--errorBg); color: var(--errorText); font-size: 14px; line-height: 1.43; }
    .alert svg { color: var(--errorIcon); width: 22px; height: 22px; margin-top: 7px; }
    .alert .h { font-weight: 500; margin: 8px 0 4px; }
    .alert p { margin: 0 0 8px; }
    details { margin-top: 16px; font-size: 13px; color: var(--text2); }
    summary { cursor: pointer; }
    pre { white-space: pre-wrap; word-break: break-word; margin: 8px 0 0; padding: 8px 12px;
      background: var(--code); border-radius: 4px; font: 12px/1.45 ui-monospace, Menlo, Consolas, monospace;
      color: var(--text); max-height: 220px; overflow: auto; }
    pre.log { margin: 16px 24px; max-height: none; }
    .tooltip { position: fixed; z-index: 1500; pointer-events: none; padding: 4px 8px; border-radius: 4px;
      background: rgba(97,97,97,.92); color: #fff; font-size: 11px; font-weight: 500; line-height: 1.4;
      white-space: nowrap; opacity: 0; transition: opacity 150ms; }
    .tooltip.show { opacity: 1; }
    .fab { position: fixed; right: 16px; bottom: 16px; z-index: 1200; display: flex; align-items: center;
      gap: 8px; height: 40px; padding: 0 16px 0 12px; border: 0; border-radius: 20px; cursor: pointer;
      background: var(--primary); color: var(--onPrimary); font-size: 14px; font-weight: 500;
      box-shadow: 0 3px 5px -1px rgba(0,0,0,.2), 0 6px 10px 0 rgba(0,0,0,.14), 0 1px 18px 0 rgba(0,0,0,.12); }
    .fab svg { width: 20px; height: 20px; }
  `;

  // ---- helpers ------------------------------------------------------------------------------

  const el = (tag, attrs = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) node.setAttribute(k, v === true ? '' : v);
    }
    node.append(...children.filter((c) => c != null));
    return node;
  };
  const icon = (name) => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', PATHS[name]);
    if (name === 'bucket') { p.setAttribute('fill-rule', 'evenodd'); p.setAttribute('clip-rule', 'evenodd'); }
    svg.append(p);
    return svg;
  };
  const size = (n) => {
    const u = ['bytes', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${i ? n.toFixed(1) : n} ${u[i]}`;
  };
  const date = (t) => new Date(t * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  const mmss = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  const api = async (path, opts) => {
    const r = await fetch(API + path, { cache: 'no-store', ...opts });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
    return body;
  };

  // ---- shadow root and theme ---------------------------------------------------------------

  const host = el('div', { id: 'mdv-workspace-data' });
  const root = host.attachShadow({ mode: 'open' });
  root.append(el('style', {}, css));
  const tooltip = el('div', { class: 'tooltip', role: 'tooltip' });
  root.append(tooltip);
  const applyTheme = () => {
    const palette = THEMES[document.documentElement.classList.contains('dark') ? 'dark' : 'light'];
    for (const [k, v] of Object.entries(palette)) host.style.setProperty(`--${k}`, v);
  };
  applyTheme();
  new MutationObserver(applyTheme).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });

  // ---- dialog -------------------------------------------------------------------------------

  let current = sessionStorage.getItem(LAST_FOLDER) || '';
  let workspace = '';
  let selected = null;
  let busy = false;

  const subtitle = el('div', { class: 'sub' });
  const crumbs = el('nav', { class: 'crumbs', 'aria-label': 'Location' });
  const content = el('div', { class: 'content' });
  const openBtn = el('button', { class: 'btn contained', disabled: true, onclick: () => selected && openItem(selected) }, 'Open');
  const cancelBtn = el('button', { class: 'btn', onclick: () => close() }, 'Cancel');
  const activityBtn = el('button', { class: 'btn text', onclick: () => showActivity() }, 'View activity');
  const paper = el('div', { class: 'paper', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'wd-title', tabindex: '-1' },
    el('div', { class: 'title' },
      el('div', { class: 'grow' }, el('h2', { id: 'wd-title' }, LABEL), subtitle),
      el('button', { class: 'iconbtn', 'aria-label': 'Close', onclick: () => close() }, icon('close'))),
    crumbs, content,
    el('div', { class: 'actions' }, activityBtn, el('div', { class: 'grow' }), cancelBtn, openBtn));
  const backdrop = el('div', { class: 'backdrop', onmousedown: (e) => { if (e.target === backdrop) close(); } }, paper);
  paper.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); close(); }
    if (e.key === 'Enter' && selected && !busy && (e.target === paper || e.target.tagName === 'LI')) openItem(selected);
  });

  function open() {
    if (!backdrop.isConnected) root.append(backdrop);
    paper.focus();
    if (!busy) browse(current);
  }
  function close() {
    if (busy) return;
    backdrop.remove();
  }
  function setSubtitle() {
    subtitle.textContent = workspace ? `${workspace} workspace` : 'Workbench workspace';
  }

  function renderCrumbs(path, extra) {
    const parts = path ? path.split('/') : [];
    const items = [{ label: 'Resources', path: '' }];
    parts.forEach((p, i) => items.push({ label: p, path: parts.slice(0, i + 1).join('/') }));
    if (extra) items.push({ label: extra });
    crumbs.replaceChildren();
    items.forEach((item, i) => {
      if (i) crumbs.append(el('span', { class: 'sep', 'aria-hidden': 'true' }, '/'));
      const last = i === items.length - 1;
      crumbs.append(last ? el('span', { class: 'current', 'aria-current': 'page' }, item.label)
        : el('a', { onclick: () => browse(item.path) }, item.label));
    });
  }

  function select(item, li) {
    selected = item;
    for (const node of content.querySelectorAll('li.selected')) node.classList.remove('selected');
    li.classList.add('selected');
    openBtn.disabled = false;
  }

  function secondary(e) {
    if (e.type === 'wbfolder') return 'Folder';
    if (e.type === 'bucket') return [e.label || 'Cloud Storage bucket', e.description].filter(Boolean).join(' · ');
    if (e.type === 'folder') return null;
    if (e.type === 'project') return 'MDV project';
    const parts = [e.importable ? KIND_LABELS[e.kind] : 'Not supported by MDV', size(e.size)];
    if (e.modified) parts.push(`Modified ${date(e.modified)}`);
    return parts.join(' · ');
  }

  function rowFor(e) {
    const navigates = ['wbfolder', 'bucket', 'folder'].includes(e.type);
    const openable = e.type === 'project' || (e.type === 'file' && e.importable);
    const iconName = { wbfolder: 'folder', bucket: 'bucket', folder: 'folder', project: 'project' }[e.type] || 'file';
    const sec = secondary(e);
    const li = el('li', { class: `${e.type}${!navigates && !openable ? ' disabled' : ''}`, tabindex: '0',
      role: 'option', title: e.path, 'aria-disabled': !navigates && !openable ? 'true' : false },
      el('span', { class: 'icon' }, icon(iconName)),
      el('div', { class: 'itemtext' }, el('div', { class: 'primary' }, e.name), sec ? el('div', { class: 'secondary' }, sec) : null));
    if (navigates) {
      li.addEventListener('click', () => browse(e.path));
      li.addEventListener('keydown', (k) => { if (k.key === 'Enter') { k.stopPropagation(); browse(e.path); } });
    } else if (openable) {
      li.addEventListener('click', () => select(e, li));
      li.addEventListener('dblclick', () => openItem(e));
      li.addEventListener('focus', () => select(e, li));
    }
    return li;
  }

  async function browse(path) {
    current = path;
    selected = null;
    openBtn.disabled = true;
    openBtn.hidden = false;
    sessionStorage.setItem(LAST_FOLDER, path);
    renderCrumbs(path);
    content.replaceChildren(el('div', { class: 'progress' }));
    let data;
    try {
      data = await api(`/list?path=${encodeURIComponent(path)}`);
    } catch (e) {
      if (path) { browse(''); return; }  // the folder is gone or its bucket isn't mounted
      content.replaceChildren(errorAlert(`Couldn't list the workspace's resources`, e.message));
      return;
    }
    workspace = data.workspace || workspace;
    setSubtitle();
    if (current !== path) return;
    if (!data.entries.length) {
      content.replaceChildren(el('div', { class: 'empty' }, path
        ? 'This folder is empty.'
        : 'No Cloud Storage buckets are available to MDV yet. Buckets are connected when the app starts: wait a minute, or restart the app if the bucket was added after the app started.'));
      return;
    }
    const list = el('ul', { role: 'listbox', 'aria-label': 'Workspace resources' }, ...data.entries.map(rowFor));
    content.replaceChildren(list);
    if (data.truncated) content.append(el('div', { class: 'empty' }, 'Showing the first 2,000 items.'));
  }

  function errorAlert(title, message, details) {
    return el('div', { class: 'alert', role: 'alert' }, icon('error'),
      el('div', { class: 'grow' }, el('div', { class: 'h' }, title), el('p', {}, message),
        details ? el('details', {}, el('summary', {}, 'Details'), el('pre', {}, details)) : null));
  }

  async function openItem(item) {
    if (busy) return;
    busy = true;
    openBtn.disabled = true;
    cancelBtn.disabled = true;
    const bucket = item.path.split('/').slice(0, -1).join('/');
    const heading = el('div', { class: 'h' }, item.type === 'project' ? `Opening ${item.name}…` : `Converting ${item.name}…`);
    const elapsed = el('div', { class: 'b' });
    const log = el('pre');
    content.replaceChildren(el('div', { class: 'progress' }), el('div', { class: 'status' }, heading,
      el('div', { class: 'b' }, item.type === 'project'
        ? 'MDV reads this project directly from the workspace.'
        : 'MDV is converting this file directly from the workspace; your bucket isn\'t changed. Large files can take several minutes.'),
      elapsed, el('details', {}, el('summary', {}, 'Details'), log)));
    renderCrumbs(bucket, item.name);
    try {
      let job = await api('/import', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: item.path }) });
      while (job.state === 'running') {
        elapsed.textContent = `Elapsed ${mmss(job.elapsed || 0)}`;
        log.textContent = (job.log || []).join('\n');
        await new Promise((r) => setTimeout(r, 1500));
        job = await api(`/jobs/${job.id}`);
      }
      if (job.state !== 'done') throw Object.assign(new Error(job.message || 'Something went wrong.'), { log: (job.log || []).join('\n') });
      heading.textContent = `Opening ${job.project_name}…`;
      location.href = `/project/${job.project_id}/`;
    } catch (e) {
      busy = false;
      cancelBtn.disabled = false;
      openBtn.disabled = true;
      content.replaceChildren(errorAlert(`Couldn't open ${item.name}`, e.message, e.log || log.textContent || null));
    }
  }

  // The app's data activity (what was linked, converted or removed), for troubleshooting.
  async function showActivity() {
    if (busy) return;
    selected = null;
    openBtn.hidden = true;
    renderCrumbs(current, 'Activity');
    const pre = el('pre', { class: 'log' }, 'Loading…');
    content.replaceChildren(pre);
    try {
      const r = await fetch('/_workspace-sync.log', { cache: 'no-store' });
      const lines = r.ok ? (await r.text()).trimEnd().split('\n').filter(Boolean) : [];
      pre.textContent = lines.length ? lines.slice(-300).join('\n') : 'No activity yet.';
      content.scrollTop = content.scrollHeight;
    } catch (e) {
      pre.textContent = `Couldn't load the activity log: ${e.message}`;
    }
  }

  // ---- entry points in MDV's own UI ---------------------------------------------------------

  const MARK = 'data-mdv-workspace-entry';

  function swapIcon(svg) {
    if (!svg) return;
    svg.setAttribute('data-testid', 'FolderOpenIcon');
    svg.replaceChildren(icon('folderOpen').firstChild);
  }

  // Catalog: a card next to MDV's "Create new project" and "Import an existing project" cards.
  function addCatalogCard() {
    if (document.querySelector(`[${MARK}="card"]`)) return true;
    const label = [...document.querySelectorAll('h6')].find((h) => h.textContent.trim() === 'Import an existing project');
    const item = label && label.closest('.MuiGrid2-root:not(.MuiGrid2-container), .MuiGrid-item');
    if (!item) return false;
    const card = item.cloneNode(true);
    card.setAttribute(MARK, 'card');
    card.querySelector('h6').textContent = LABEL;
    swapIcon(card.querySelector('svg'));
    const target = card.querySelector('button') || card;
    target.setAttribute('aria-label', LABEL);
    target.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); open(); });
    item.after(card);
    return true;
  }

  // Project page: a toolbar button after MDV's "Add Datasource" button, with an MDV-style tooltip.
  function addToolbarButton() {
    if (document.querySelector(`[${MARK}="toolbar"]`)) return true;
    const anchor = document.querySelector('button[aria-label="Add Datasource"]');
    if (!anchor) return false;
    const btn = anchor.cloneNode(true);
    btn.setAttribute(MARK, 'toolbar');
    btn.setAttribute('aria-label', LABEL);
    swapIcon(btn.querySelector('svg'));
    btn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); hideTip(); open(); });
    btn.addEventListener('mouseenter', () => showTip(btn));
    btn.addEventListener('mouseleave', hideTip);
    btn.addEventListener('focus', () => showTip(btn));
    btn.addEventListener('blur', hideTip);
    anchor.after(btn);
    return true;
  }
  function showTip(target) {
    tooltip.textContent = LABEL;
    const r = target.getBoundingClientRect();
    tooltip.style.top = `${r.bottom + 6}px`;
    tooltip.style.left = `${r.left + r.width / 2}px`;
    tooltip.style.transform = 'translateX(-50%)';
    tooltip.classList.add('show');
  }
  function hideTip() { tooltip.classList.remove('show'); }

  // Fallback if MDV's layout changes and neither entry point can be found.
  let fab = null;
  function addFallback() {
    if (fab || document.querySelector(`[${MARK}]`)) return;
    fab = el('button', { class: 'fab', 'aria-label': LABEL, onclick: () => open() }, icon('folderOpen'), LABEL);
    root.append(fab);
  }

  function ensureEntryPoints() {
    const found = addCatalogCard() || addToolbarButton();
    if (found && fab) { fab.remove(); fab = null; }
    return found;
  }

  const start = () => {
    document.body.append(host);
    // MDV renders with React; re-add entry points if they're removed or rendered later.
    let pending = false;
    new MutationObserver(() => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(() => { pending = false; ensureEntryPoints(); });
    }).observe(document.body, { childList: true, subtree: true });
    ensureEntryPoints();
    setTimeout(() => { if (!ensureEntryPoints()) addFallback(); }, 8000);
  };
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();
