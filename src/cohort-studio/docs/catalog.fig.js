FIGS.push({
  id: 'cat', name: 'Views-only DuckDB catalog',
  hint: 'p publish · a attach · 1–4 query a view · n new partition · w try a write · esc reset',
  aria: 'Isometric figure of a views-only DuckDB catalog in Cohort Studio. Press P to publish a catalog over an S3 folder, A to attach it read-only, 1 to 4 to query a view and see which files it reads, N to add a partition, W to attempt a write.',
  css: `[data-fig="cat"] .press.lit .label, [data-fig="cat"] .press.latched .label { fill:var(--panel); }
        [data-fig="cat"] .sub { opacity:.7; }
        [data-fig="cat"] .gone { display:none; }
        [data-fig="cat"] .icon { fill:none; stroke:var(--ink); stroke-width:1.5; vector-effect:non-scaling-stroke; stroke-linecap:round; stroke-linejoin:round; }
        [data-fig="cat"] .press.lit .icon, [data-fig="cat"] .press.latched .icon { stroke:var(--panel); }
        [data-fig="cat"] .row { cursor:pointer; }
        [data-fig="cat"] .row rect { fill:transparent; }
        [data-fig="cat"] .row.hot rect { fill:var(--accent); opacity:.28; }
        [data-fig="cat"] .tag rect { fill:var(--body); stroke:var(--line); stroke-width:1; vector-effect:non-scaling-stroke; transition:stroke .3s; }
        [data-fig="cat"] .tag line { stroke:var(--detail); stroke-width:1; vector-effect:non-scaling-stroke; }
        [data-fig="cat"] .tag .nm { fill:var(--ink-hi); font-family:var(--mono); }
        [data-fig="cat"] .tag .rl { fill:var(--ink); font-family:var(--mono); opacity:.75; }
        [data-fig="cat"] .tag.hot rect, [data-fig="cat"] .tag.hot line { stroke:var(--accent); }
        [data-fig="cat"] .tag.hot .nm { fill:var(--accent-hi); }`,
  mount(stage, api) {
    const Z = 10, TZ = Z + 6;
    const K = api.iso.frame([[0,0,0],[760,0,0],[0,560,0],[760,560,0],[195,120,Z+150],[580,60,TZ+70],[150,480,Z+180]]);
    const { P, TOP, FRONT, SIDE, box } = K;
    const esc = api.iso.esc, f2 = v => v.toFixed(1);

    const FILES = {
      samples:  { x:450, y:50,  w:80, d:56, label:'samples.parquet' },
      donors:   { x:545, y:50,  w:80, d:56, label:'donors.csv' },
      subjects: { x:640, y:50,  w:80, d:56, label:'subjects.json' },
      y2024:    { x:460, y:150, w:70, d:56, label:'year=2024' },
      y2025:    { x:548, y:150, w:70, d:56, label:'year=2025' },
      y2026:    { x:636, y:150, w:70, d:56, label:'year=2026', later:true },
    };
    const VIEWS = [
      { name:'samples',  src:'samples.parquet',          files:['samples'] },
      { name:'donors',   src:'donors.csv',               files:['donors'] },
      { name:'subjects', src:'subjects.json',            files:['subjects'] },
      { name:'visits',   src:'visits/year=*/*.parquet',  files:['y2024','y2025','y2026'] },
    ];

    const W = {
      'secret-pub': [[190,250,Z],[190,190,Z]],
      'build':      [[195,120,Z],[340,130,Z]],
      'upload':     [[340,130,Z],[400,130,Z],[400,285,Z],[430,285,Z],[430,285,TZ],[490,285,TZ]],
      'secret-att': [[240,290,Z],[320,290,Z],[320,380,Z]],
      'attach':     [[470,300,TZ],[470,330,TZ],[470,330,Z],[470,362,Z],[410,362,Z],[410,400,Z]],
      'v-samples':  [[345,400,Z],[345,338,Z],[538,338,Z],[538,330,Z],[538,330,TZ],[538,78,TZ],[530,78,TZ]],
      'v-donors':   [[360,400,Z],[360,344,Z],[627,344,Z],[627,330,Z],[627,330,TZ],[627,78,TZ],[625,78,TZ]],
      'v-subjects': [[375,400,Z],[375,350,Z],[724,350,Z],[724,330,Z],[724,330,TZ],[724,78,TZ],[720,78,TZ]],
      'v-visits':   [[390,400,Z],[390,356,Z],[585,356,Z],[585,330,Z],[585,330,TZ],[585,224,TZ]],
      'result':     [[300,470,Z],[262,470,Z]],
    };
    const pathD = pts => 'M' + pts.map(p => P(...p).map(f2).join(' ')).join(' L');

    let svg = box(0, 0, 0, 760, 560, Z, 16);
    svg += `<g transform="${TOP(0,0,Z)}"><rect class="detail" x="12" y="12" width="736" height="536" rx="10"/>
      <text class="label sub" x="24" y="540" font-size="9">cohort studio · views-only duckdb catalog</text></g>`;

    svg += box(430, 30, Z, 300, 300, 6, 10);
    svg += `<g transform="${TOP(0,0,TZ)}">
      <rect class="detail" x="440" y="40" width="280" height="280" rx="6"/>
      <rect class="detail" x="452" y="140" width="262" height="86" rx="4" stroke-dasharray="4 3"/>
      <text class="label sub" x="458" y="221" font-size="7">visits/year=*/</text>
      <rect class="detail" x="450" y="255" width="80" height="60" rx="4" stroke-dasharray="3 3"/>
      <text class="label sub" x="542" y="300" font-size="7">_catalog/</text>
      <text class="label sub" x="542" y="312" font-size="7">s3://…/cohort-data/</text>
    </g>`;

    for (const [k, pts] of Object.entries(W)) {
      const d = pathD(pts), rev = pathD([...pts].reverse());
      svg += `<path class="wire-under" d="${d}"/><path class="wire" id="cat-w-${k}" d="${d}"/>
        <path class="pulse" id="cat-p-${k}-f" pathLength="1000" d="${d}"/><path class="pulse" id="cat-p-${k}-r" pathLength="1000" d="${rev}"/>`;
    }

    for (const [id, f] of Object.entries(FILES)) {
      svg += `<g class="press${f.later ? ' gone' : ''}" id="cat-f-${id}" data-file="${id}">${box(f.x, f.y, TZ, f.w, f.d, 8, 3)}
        <g transform="${TOP(f.x, f.y, TZ + 8)}"><text class="label" x="7" y="${f.d / 2 + 3}" font-size="${Math.min(8, (f.w - 12) / (f.label.length * 0.6)).toFixed(1)}">${esc(f.label)}</text>
        ${api.iso.slits(f.d / 2 + 10, f.d - 8, 6, 7, f.w - 20, false)}</g></g>`;
    }
    svg += `<g class="press gone" id="cat-slot">${box(450, 255, TZ, 80, 60, 10, 3)}
      <g transform="${TOP(450, 255, TZ + 10)}"><text class="label" x="7" y="22" font-size="7.5">cohort.duckdb</text>
      <text class="label sub" x="7" y="34" font-size="6.5">views only</text>
      ${api.iso.slits(42, 52, 5, 7, 60, false)}</g></g>`;

    svg += `<g class="press" id="cat-n-key">${box(140, 250, Z, 100, 70, 10, 8)}
      <g transform="${TOP(140, 250, Z + 10)}"><circle class="icon" cx="24" cy="35" r="10"/>
      <path class="icon" d="M34 35 L88 35 M78 35 L78 45 M68 35 L68 42"/></g></g>`;

    svg += `<g class="press" id="cat-n-server">${box(120, 50, Z, 150, 140, 80, 6)}</g>`;
    svg += `<g transform="${FRONT(120, 190, Z + 80)}">
      <rect class="halo" id="cat-halo" filter="url(#bloom)" x="4" y="4" width="142" height="56" rx="6"/>
      <rect class="glass" id="cat-glass" filter="url(#soft)" x="8" y="8" width="134" height="48" rx="4"/>
      <text class="scr scr-accent" id="cat-l0" x="14" y="21" font-size="7.5"></text>
      <text class="scr" id="cat-l1" x="14" y="35" font-size="7"></text>
      <text class="scr" id="cat-l2" x="14" y="47" font-size="7"></text>
      <text class="label sub" x="14" y="70" font-size="6">catalog.py · POST /api/catalogs/build</text></g>`;
    svg += `<g transform="${SIDE(270, 190, Z + 80)}">${api.iso.slits(12, 128, 6, 12, 70)}</g>`;
    svg += `<g class="press" id="cat-btn-pub" data-act="publish">${box(150, 80, Z + 80, 70, 44, 8, 6)}
      <g transform="${TOP(150, 80, Z + 88)}"><text class="label" x="35" y="26" font-size="9" text-anchor="middle">PUBLISH</text></g></g>`;

    svg += `<g class="press gone" id="cat-n-local">${box(305, 105, Z, 70, 50, 8, 3)}
      <g transform="${TOP(305, 105, Z + 8)}"><text class="label" x="6" y="22" font-size="6.5">tmp/cohort.duckdb</text>
      ${api.iso.slits(30, 42, 6, 6, 50, false)}</g></g>`;

    let duck = '';
    for (let i = 0; i < 4; i++) duck += box(312 + i * 30, 474, Z, 6, 10, 6);
    for (let i = 0; i < 3; i++) duck += box(414, 392 + i * 28, Z, 10, 6, 6);
    duck += box(300, 380, Z + 6, 120, 100, 30, 4);
    duck += `<g transform="${TOP(300, 380, Z + 36)}"><rect class="detail" x="16" y="58" width="88" height="34" rx="3"/>
      <text class="label" x="60" y="80" font-size="11" text-anchor="middle">DUCKDB</text></g>`;
    svg += `<g class="press" id="cat-n-duck">${duck}</g>`;
    svg += `<g class="press" id="cat-btn-att" data-act="attach">${box(318, 392, Z + 36, 84, 40, 7, 6)}
      <g transform="${TOP(318, 392, Z + 43)}"><text class="label" x="42" y="24" font-size="8.5" text-anchor="middle">ATTACH</text></g></g>`;
    svg += `<g class="press" id="cat-lock" data-act="write"><g transform="${FRONT(300, 480, Z + 36)}">
      <path class="icon" d="M${92} 12 L92 7 A6 6 0 0 1 104 7 L104 12"/>
      <rect class="face" x="88" y="12" width="20" height="14" rx="2"/>
      <text class="label sub" x="10" y="20" font-size="7">READ_ONLY</text></g></g>`;

    svg += `<g class="press" id="cat-n-panel">${box(40, 476, Z, 220, 14, 120, 3)}</g>`;
    svg += `<g transform="${FRONT(40, 490, Z + 120)}">
      <rect class="glass" id="cat-pglass" filter="url(#soft)" x="6" y="6" width="208" height="108" rx="3"/>
      <text class="scr scr-accent" id="cat-ph" x="14" y="20" font-size="8"></text>
      ${VIEWS.map((v, i) => `<g class="row" id="cat-r-${i}" data-view="${i}">
        <rect x="10" y="${27 + i * 21}" width="200" height="18" rx="2"/>
        <text class="scr" id="cat-rn-${i}" x="16" y="${39 + i * 21}" font-size="8"></text>
        <text class="scr" id="cat-rs-${i}" x="204" y="${39 + i * 21}" font-size="6.5" text-anchor="end"></text></g>`).join('')}
    </g>`;

    const TAGS = [
      ['server', 195, 120, Z + 88, 'Cohort Studio', 'catalog.publish()'],
      ['local', 340, 130, Z + 8, 'Local copy', 'tempdir · built here'],
      ['slot', 490, 285, TZ + 10, 'Catalog file', 'views only · no rows'],
      ['tray', 725, 320, TZ, 'S3 folder', 'workspace resource'],
      ['key', 190, 285, Z + 10, 'AWS profile', 'secret before ATTACH'],
      ['duck', 360, 430, Z + 43, 'DuckDB', 'ATTACH … (READ_ONLY)'],
      ['panel', 150, 483, Z + 120, 'Views', 'cat.main · 0 rows stored'],
    ];
    for (const [id, x, y, z, name, role] of TAGS) {
      const [ax, ay] = P(x, y, z), ty = ay - 24, tw = Math.max(name.length * 13, role.length * 9.5) * 0.6 + 16, th = 34;
      svg += `<g class="tag" id="cat-t-${id}"><line x1="${f2(ax)}" y1="${f2(ay)}" x2="${f2(ax)}" y2="${f2(ty)}"/>
        <rect x="${f2(ax - tw / 2)}" y="${f2(ty - th)}" width="${f2(tw)}" height="${th}" rx="5"/>
        <text class="nm" x="${f2(ax)}" y="${f2(ty - th + 15)}" font-size="13" text-anchor="middle">${esc(name)}</text>
        <text class="rl" x="${f2(ax)}" y="${f2(ty - 7)}" font-size="9.5" text-anchor="middle">${esc(role)}</text></g>`;
    }

    stage.setAttribute('viewBox', K.viewBox);
    stage.innerHTML = svg;

    const $ = id => stage.querySelector('#' + id);
    const st = { published:false, attached:false, partitions:2, view:-1, run:0, wires:new Set(), lit:new Set(), tags:new Set(), lines:['', '', ''] };

    function filesOf(v) { return VIEWS[v].files.filter(f => !FILES[f].later || st.partitions > 2); }

    function render() {
      for (const k of Object.keys(W)) $(`cat-w-${k}`).classList.toggle('hot', st.wires.has(k));
      for (const id of Object.keys(FILES)) {
        $(`cat-f-${id}`).classList.toggle('gone', !!FILES[id].later && st.partitions < 3);
        $(`cat-f-${id}`).classList.toggle('lit', st.lit.has(`f-${id}`));
      }
      $('cat-slot').classList.toggle('gone', !st.published);
      $('cat-slot').classList.toggle('lit', st.lit.has('slot'));
      $('cat-slot').classList.toggle('latched', st.published && st.attached && !st.lit.has('slot'));
      $('cat-n-local').classList.toggle('gone', !st.lit.has('local'));
      $('cat-n-local').classList.toggle('lit', st.lit.has('local'));
      for (const n of ['key', 'server', 'duck', 'panel']) $(`cat-n-${n}`).classList.toggle('lit', st.lit.has(n));
      $('cat-btn-att').classList.toggle('latched', st.attached);
      for (const t of ['server','local','slot','tray','key','duck','panel']) $(`cat-t-${t}`).classList.toggle('hot', st.tags.has(t));
      const [l0, l1, l2] = st.lines;
      $('cat-l0').textContent = l0 || 'views-only catalog'; $('cat-l1').textContent = l1 || 'p publish · a attach';
      $('cat-l2').textContent = l2 || '1–4 query · n partition';
      const live = st.published || st.lit.size > 0;
      $('cat-glass').classList.toggle('hot', live); $('cat-halo').classList.toggle('hot', live);
      $('cat-pglass').classList.toggle('hot', st.attached);
      $('cat-ph').textContent = st.attached ? 'cat · READ_ONLY · 4 views' : 'not attached';
      VIEWS.forEach((v, i) => {
        $(`cat-rn-${i}`).textContent = st.attached ? v.name : '';
        $(`cat-rs-${i}`).textContent = st.attached ? (v.files.length > 1 ? `${filesOf(i).length} files · ${v.src}` : v.src) : '';
        $(`cat-r-${i}`).classList.toggle('hot', st.attached && st.view === i);
      });
      api.power(live);
    }

    function show(step) {
      st.wires = new Set(step.w || []); st.lit = new Set(step.l || []); st.tags = new Set(step.t || []);
      st.lines = step.s; if (step.do) step.do();
      render();
      for (const k of st.wires) {
        const rev = (step.rev || []).includes(k);
        api.replay($(`cat-p-${k}-${rev ? 'r' : 'f'}`));
      }
      if (step.r) api.readout(step.r);
    }

    function sequence(steps, ms = 1300) {
      const run = ++st.run;
      steps.forEach((s, i) => api.after(i * ms, () => { if (run === st.run) show(s); }));
    }

    function publish() {
      flash('cat-btn-pub');
      const parts = st.partitions, files = 3 + parts;
      sequence([
        { w:['secret-pub'], l:['key','server'], t:['key','server'], s:['publish · 1/6','CREATE SECRET wb','PROVIDER config'], rev:['secret-pub'], r:'secret from the folder profile' },
        { l:['server','f-samples','f-donors','f-subjects','f-y2024','f-y2025', ...(parts > 2 ? ['f-y2026'] : [])], t:['tray'], s:['publish · 2/6','aws s3 ls --recursive',`${files} data files`], r:`listed ${files} files` },
        { l:['f-y2024','f-y2025', ...(parts > 2 ? ['f-y2026'] : [])], t:['tray'], s:['publish · 3/6','plan_views()','partitions → 1 glob view'], r:'4 views planned · visits = hive glob' },
        { w:['build'], l:['server','local'], t:['local'], s:['publish · 4/6','CREATE VIEW × 4','each source probed'], r:'built in a temp dir' },
        { l:['local'], t:['local'], s:['publish · 5/6','verify_views_only()','0 tables · 4 views'], r:'0 tables · 4 views · ~300 kb' },
        { w:['upload'], l:['local','slot'], t:['slot'], s:['publish · 6/6','aws s3 cp →','_catalog/cohort.duckdb'], do:() => { st.published = true; }, r:'published · catalog_published logged' },
        { s:['published','cohort.duckdb','a to attach'] },
      ]);
    }

    function attach() {
      flash('cat-btn-att');
      if (!st.published) { st.run++; show({ s:['nothing to attach','publish first','press p'], r:'publish a catalog first' }); return; }
      sequence([
        { w:['secret-att'], l:['key','duck'], t:['key','duck'], s:['attach · 1/3','secret before ATTACH','same profile'], r:'secret created before attach' },
        { w:['attach'], l:['slot','duck'], t:['slot','duck'], s:['attach · 2/3',"ATTACH 's3://…'","AS cat (READ_ONLY)"], rev:['attach'], r:'attached read-only' },
        { w:['result'], l:['duck','panel'], t:['panel'], s:['attach · 3/3','duckdb_views()','4 views listed'], do:() => { st.attached = true; }, r:'4 views · no rows in the file' },
      ], 1100);
    }

    function query(i) {
      if (!st.attached) { st.run++; show({ s:['not attached','press a first',''], r:'attach the catalog first' }); return; }
      st.run++;
      const v = VIEWS[i], fl = filesOf(i);
      st.view = i;
      show({ w:[`v-${v.name}`, 'result'], l:['duck','panel', ...fl.map(f => `f-${f}`)], t:['duck','tray','panel'],
        s:[`view · ${v.name}`, `SELECT * FROM cat.${v.name}`, `→ ${fl.length} file${fl.length > 1 ? 's' : ''} read`],
        r:`cat.${v.name} → ${v.src} · data stays in s3` });
    }

    function partition() {
      st.run++;
      st.partitions = st.partitions > 2 ? 2 : 3;
      const added = st.partitions > 2;
      show({ l: added ? ['f-y2026'] : [], t:['tray'],
        s:[added ? 'new partition' : 'partition removed', 'year=2026/', added ? 'glob view: no republish' : 'visits back to 2 files'],
        r: added ? 'year=2026 landed · press 4: same query, 3 files' : 'year=2026 removed' });
    }

    function write() {
      st.run++;
      api.flash($('cat-lock'));
      show({ l: st.attached ? ['duck'] : [], t:['duck'],
        s: st.attached ? ['write refused', 'CREATE TABLE cat.x …', 'attached READ_ONLY'] : ['not attached', 'nothing to write', ''],
        r: st.attached ? 'read-only: edit a local copy and republish' : 'attach first' });
    }

    function reset() {
      st.run++; Object.assign(st, { published:false, attached:false, partitions:2, view:-1, wires:new Set(), lit:new Set(), tags:new Set(), lines:['', '', ''] });
      render(); api.readout('idle · p to publish');
    }

    function flash(id) { api.flash($(id)); }

    stage.addEventListener('click', e => {
      const act = e.target.closest('[data-act]'), row = e.target.closest('[data-view]'), file = e.target.closest('[data-file]');
      if (act) ({ publish, attach, write })[act.dataset.act]();
      else if (row) query(+row.dataset.view);
      else if (file) { const i = VIEWS.findIndex(v => v.files.includes(file.dataset.file)); if (i >= 0) query(i); }
    });

    render(); api.readout('idle · p to publish');
    return {
      key: e => {
        const k = e.key.toLowerCase();
        if (k === 'p') { publish(); return true; }
        if (k === 'a') { attach(); return true; }
        if (k === 'n') { partition(); return true; }
        if (k === 'w') { write(); return true; }
        if (k >= '1' && k <= '4') { query(+k - 1); return true; }
        if (k === 'escape' || k === '0') { reset(); return true; }
        return false;
      },
      demo: () => { publish(); api.after(9500, attach); api.after(13500, () => query(3)); },
    };
  },
});
