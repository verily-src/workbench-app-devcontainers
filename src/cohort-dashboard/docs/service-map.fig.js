FIGS.push({
  id: 'dash', name: 'Cohort Dashboard · service map',
  hint: '1–8 play a flow · space next · click a service or its tag · esc clear',
  aria: 'Isometric map of Cohort Dashboard: the Panel server, its TTL cache, the DuckDB, SQLAlchemy and BigQuery engines, and the workspace services behind them. Every service has a name tag. Press 1 to 8 to play a request flow, or click a service to see its connections.',
  css: `[data-fig="dash"] .press.lit .label, [data-fig="dash"] .press.latched .label { fill:var(--panel); }
        [data-fig="dash"] .sub { opacity:.7; }
        [data-fig="dash"] .icon { fill:none; stroke:var(--ink); stroke-width:1.5; vector-effect:non-scaling-stroke; stroke-linecap:round; stroke-linejoin:round; }
        [data-fig="dash"] .press.lit .icon, [data-fig="dash"] .press.latched .icon { stroke:var(--panel); }
        [data-fig="dash"] .tag { cursor:pointer; }
        [data-fig="dash"] .tag rect { fill:var(--body); stroke:var(--line); stroke-width:1; vector-effect:non-scaling-stroke; transition:stroke .3s; }
        [data-fig="dash"] .tag line { stroke:var(--detail); stroke-width:1; vector-effect:non-scaling-stroke; }
        [data-fig="dash"] .tag .nm { fill:var(--ink-hi); font-family:var(--mono); }
        [data-fig="dash"] .tag .rl { fill:var(--ink); font-family:var(--mono); opacity:.75; }
        [data-fig="dash"] .tag.on rect { stroke:var(--accent-dim); }
        [data-fig="dash"] .tag.hot rect, [data-fig="dash"] .tag.hot line { stroke:var(--accent); }
        [data-fig="dash"] .tag.hot .nm, [data-fig="dash"] .tag.on .nm { fill:var(--accent-hi); }`,
  mount(stage, api) {
    const Z = 10;

    const N = {
      workbench: { x:170, y:50,  w:80,  d:90,  h:40, shape:'shield',  name:'Workbench',         role:'backend · abac creds', info:['resource registry','per-resource creds'] },
      lineage:   { x:300, y:50,  w:130, d:90,  h:30, shape:'ledger',  name:'Lineage log',       role:'lineage.py',           info:['_lineage_event + _edge','sqlite when no aurora'] },
      wb:        { x:470, y:50,  w:80,  d:90,  h:34, shape:'term',    name:'wb CLI',            role:'resolve · configure',  info:['resource list/resolve','configure-aws · auth'] },
      db:        { x:600, y:50,  w:90,  d:90,  h:32, shape:'chip', mark:'SQL',  name:'SQLAlchemy engine', role:'db.py · psycopg pool', info:['psycopg · pool of 5','conn string cached'] },
      aurora:    { x:760, y:40,  w:110, d:110, h:64, shape:'cyl', r:46, bands:2, name:'Aurora PostgreSQL', role:'data store · aws', info:['tables · views · s3 fdw','lineage tables'] },
      browser:   { x:30,  y:240, w:100, d:110, h:80, shape:'monitor', name:'Browser',           role:'panel ui · bokeh',     info:['panel ui in the tab','no react build'] },
      proxy:     { x:170, y:250, w:80,  d:90,  h:38, shape:'gate',    name:'App proxy',         role:'workbench · websocket', info:['workbench app proxy','~60s request limit'] },
      panel:     { x:300, y:230, w:130, d:130, h:90, shape:'server',  name:'Panel server',      role:'main.py · :8080',      info:['one session per tab','pandas filters·charts'] },
      cache:     { x:470, y:255, w:80,  d:80,  h:32, shape:'stack',   name:'TTL cache',         role:'cache.py · shared',    info:['shared by all sessions','list 300s · fetch 600s'] },
      duck:      { x:600, y:240, w:90,  d:110, h:40, shape:'chip', mark:'DUCK', name:'DuckDB',  role:'duck.py · httpfs',     info:['read_parquet/csv_auto','straight from s3'] },
      s3:        { x:760, y:240, w:110, d:110, h:48, shape:'bucket', r:48, name:'S3 bucket',    role:'parquet · csv · json', info:['storage folder resource','read in place'] },
      gtex:      { x:30,  y:450, w:100, d:90,  h:12, shape:'doc',     name:'GTEx V8',           role:'public sample data',   info:['open-access samples','seed into aurora'] },
      aws:       { x:470, y:450, w:80,  d:90,  h:12, shape:'key',     name:'AWS profiles',      role:'per-resource creds',   info:['~/.workbench/aws/*.conf','AWS_CONFIG_FILE'] },
      bqpy:      { x:600, y:450, w:90,  d:90,  h:30, shape:'chip', mark:'BQ',   name:'BigQuery client', role:'bq.py',            info:['client per project','gcloud adc creds'] },
      bigquery:  { x:760, y:440, w:110, d:110, h:44, shape:'cyl', r:46, bands:1, name:'BigQuery',  role:'data store · gcp',  info:['gcp workspaces','SELECT ... LIMIT 100k'] },
    };
    const TAG_LIFT = 26;

    const K = api.iso.frame([[0,0,0],[900,0,0],[0,600,0],[900,600,0],
      ...Object.values(N).map(n => [n.x + n.w / 2, n.y + n.d / 2, Z + n.h + TAG_LIFT + 40])]);
    const { P, TOP, FRONT, SIDE, box, boxc } = K;
    const esc = api.iso.esc;
    const ctr = id => [N[id].x + N[id].w / 2, N[id].y + N[id].d / 2];

    const E = {
      'browser-proxy':  [[130,295],[170,295]],
      'proxy-panel':    [[250,295],[300,295]],
      'panel-lineage':  [[365,230],[365,140]],
      'panel-cache':    [[430,295],[470,295]],
      'cache-duck':     [[550,295],[600,295]],
      'cache-db':       [[550,270],[575,270],[575,185],[630,185],[630,140]],
      'cache-bqpy':     [[550,320],[585,320],[585,405],[630,405],[630,450]],
      'lineage-db':     [[410,50],[410,28],[645,28],[645,50]],
      'wb-db':          [[550,95],[600,95]],
      'wb-workbench':   [[490,140],[490,185],[210,185],[210,140]],
      'wb-aws':         [[470,120],[448,120],[448,480],[470,480]],
      'aws-duck':       [[530,450],[530,422],[670,422],[670,350]],
      'db-aurora':      [[690,95],[760,95]],
      'duck-s3':        [[690,295],[760,295]],
      'bqpy-bigquery':  [[690,495],[760,495]],
      'aurora-s3':      [[815,150],[815,240]],
      'gtex-panel':     [[130,495],[340,495],[340,360]],
    };
    for (const k of Object.keys(E)) { const [a, b] = k.split('-'); E[k] = [ctr(a), ...E[k], ctr(b)]; }

    const MODS = [['filters','filters'],['charts','charts'],['grid','grid'],['export','export'],['seed','seed']];
    const IN = ['browser>proxy','proxy>panel'], OUT = ['panel>proxy','proxy>browser'];

    const FLOWS = [
      { name:'boot · warm caches', steps:[
        { e:['panel>cache','cache>db'], m:[], t:['warm_resource_cache()','background thread'] },
        { e:['db>wb','wb>workbench'], m:[], t:['wb resource list','aurora · s3 · bq'] },
        { e:['wb>aws'], m:[], t:['wb workspace','configure-aws'] },
        { e:['db>wb','wb>workbench'], m:[], t:['resolve conn strings','--include-password'] },
        { e:['db>aurora','aws>duck','duck>s3'], m:[], t:['warm catalogs','tables + s3 ls'] },
      ]},
      { name:'load aurora table', steps:[
        { e:IN, m:[], t:['load table click','over the websocket'] },
        { e:['panel>cache'], m:[], t:['fetch_aurora_table','ttl 600s · miss'] },
        { e:['cache>db','db>aurora'], m:[], t:['SELECT * LIMIT 100k','pooled psycopg conn'] },
        { e:['panel>lineage','lineage>db','db>aurora'], m:[], t:['table_loaded event','_lineage_event row'] },
        { e:OUT, m:['filters','charts','grid'], t:['auto dashboard','filters inferred'] },
      ]},
      { name:'read parquet via duckdb', steps:[
        { e:IN, m:[], t:['pick an s3 folder','list its files'] },
        { e:['panel>cache','cache>duck','duck>s3'], m:[], t:['aws s3 ls --recursive','--profile <resource>'] },
        { e:['aws>duck'], m:[], t:['CREATE SECRET wb','credential_chain'] },
        { e:['duck>s3','duck>cache'], m:[], t:['read_parquet(s3://…)','LIMIT 100k → pandas'] },
        { e:OUT, m:['filters','charts','grid'], t:['same dashboard','no download step'] },
      ]},
      { name:'query bigquery', steps:[
        { e:IN, m:[], t:['pick a bq dataset','gcp workspace'] },
        { e:['panel>cache','cache>bqpy'], m:[], t:['bq.list_tables','ttl 300s'] },
        { e:['bqpy>bigquery'], m:[], t:['SELECT * LIMIT 100k','gcloud adc creds'] },
        { e:['bqpy>cache','panel>lineage'], m:[], t:['dataframe cached','lineage → sqlite'] },
        { e:OUT, m:['filters','charts','grid'], t:['same dashboard','one code path'] },
      ]},
      { name:'filter + charts (live)', steps:[
        { e:IN, m:['filters'], t:['widget value change','no apply button'] },
        { e:[], m:['filters'], t:['pandas mask','multichoice · range'] },
        { e:[], m:['charts'], t:['charts.build()','all vs selected'] },
        { e:OUT, m:['grid','charts'], t:['bokeh diff over ws','no datasource hit'] },
      ]},
      { name:'register s3 in aurora', steps:[
        { e:IN, m:[], t:['register s3 data','name · s3:// · format'] },
        { e:['panel>cache','cache>db','db>aurora'], m:[], t:['CREATE FOREIGN TABLE','aurora_analytics'] },
        { e:['aurora>s3'], m:[], t:['aurora reads s3 itself','needs pg 17.11+'] },
        { e:['panel>cache'], m:[], t:['ttl_cache.invalidate()','tables relisted'] },
        { e:['panel>lineage','lineage>db','db>aurora'], m:[], t:['s3_registered event','parent: s3 location'] },
      ]},
      { name:'export cohort', steps:[
        { e:IN, m:['export'], t:['export tsv click','filedownload widget'] },
        { e:[], m:['filters','export'], t:['filtered_df()','to_csv(sep=tab)'] },
        { e:['panel>lineage','lineage>db','db>aurora'], m:['export'], t:['export event','filters in payload'] },
        { e:OUT, m:['export'], t:['cohort.tsv','downloaded in browser'] },
      ]},
      { name:'seed gtex v8', steps:[
        { e:IN, m:['seed'], t:['load gtex v8','sample attributes'] },
        { e:['gtex>panel'], m:['seed'], t:['pandas read_csv','public gcs url'] },
        { e:['panel>cache','cache>db','db>aurora'], m:['seed'], t:['to_sql chunks of 1000','gtex_samples table'] },
        { e:['panel>cache','panel>lineage','lineage>db'], m:['seed'], t:['cache invalidated','gtex_loaded event'] },
      ]},
    ];

    const edgeOf = s => {
      const [a, b] = s.split('>');
      if (E[`${a}-${b}`]) return { key:`${a}-${b}`, dir:'f', a, b };
      return { key:`${b}-${a}`, dir:'r', a, b };
    };
    const f2 = v => v.toFixed(1);
    const pathD = pts => 'M' + pts.map(([x, y]) => P(x, y, Z).map(f2).join(' ')).join(' L');

    // A circle in the ground plane projects to an axis-aligned ellipse with these radius factors.
    const EX = Math.SQRT2 * Math.cos(Math.PI / 6), EY = Math.SQRT2 * Math.sin(Math.PI / 6);
    function cyl(cx, cy, z0, h, r, bands = 0, taper = 1) {
      const [tx, ty] = P(cx, cy, z0 + h), [bx, by] = P(cx, cy, z0), rb = r * taper;
      const arc = (z, rr) => { const [x, y] = P(cx, cy, z); return `M${f2(x - rr * EX)} ${f2(y)} A${f2(rr * EX)} ${f2(rr * EY)} 0 0 0 ${f2(x + rr * EX)} ${f2(y)}`; };
      let s = `<path class="face" d="M${f2(tx - r * EX)} ${f2(ty)} L${f2(bx - rb * EX)} ${f2(by)} A${f2(rb * EX)} ${f2(rb * EY)} 0 0 0 ${f2(bx + rb * EX)} ${f2(by)} L${f2(tx + r * EX)} ${f2(ty)} Z"/>`;
      for (let i = 1; i <= bands; i++) { const k = i / (bands + 1); s += `<path class="detail" d="${arc(z0 + h * (1 - k), r + (rb - r) * k)}"/>`; }
      s += `<ellipse class="face top" cx="${f2(tx)}" cy="${f2(ty)}" rx="${f2(r * EX)}" ry="${f2(r * EY)}"/>`;
      return s;
    }

    function shape(id, n) {
      const { x, y, w, d, h } = n, cx = x + w / 2, cy = y + d / 2, top = Z + h;
      const onTop = inner => `<g transform="${TOP(x, y, top)}">${inner}</g>`;
      const onFront = inner => `<g transform="${FRONT(x, y + d, top)}">${inner}</g>`;
      switch (n.shape) {
        case 'cyl':
          return cyl(cx, cy, Z, h, n.r, n.bands);
        case 'bucket': {
          const [tx, ty] = P(cx, cy, top);
          return cyl(cx, cy, Z, h, n.r, 1, 0.76) +
            `<ellipse class="face recess" cx="${f2(tx)}" cy="${f2(ty)}" rx="${f2(n.r * 0.84 * EX)}" ry="${f2(n.r * 0.84 * EY)}"/>`;
        }
        case 'chip': {
          let s = '';
          for (let i = 0; i < 4; i++) s += box(x + 12 + i * (w - 30) / 3, y + d - 6, Z, 6, 10, 6);
          for (let i = 0; i < 4; i++) s += box(x + w - 6, y + 12 + i * (d - 30) / 3, Z, 10, 6, 6);
          s += box(x, y, Z + 6, w, d, h - 6, 4);
          s += onTop(`<rect class="detail" x="${w * 0.22}" y="${d * 0.22}" width="${w * 0.56}" height="${d * 0.56}" rx="3"/>
            <text class="label" x="${w / 2}" y="${d / 2 + 4}" font-size="11" text-anchor="middle">${n.mark}</text>`);
          return s;
        }
        case 'stack': {
          let s = '';
          for (let i = 0; i < 3; i++) {
            const z0 = Z + i * 12;
            s += box(x, y, z0, w, d, 8, 6);
            if (i < 2) s += boxc(x + 6, y + 6, z0 + 8, w - 12, d - 12, 4, 4, 'recess');
          }
          return s;
        }
        case 'gate':
          return box(x + 18, y, Z, w - 36, 16, h - 8) + box(x + 18, y + d - 16, Z, w - 36, 16, h - 8) +
                 box(x + 10, y, Z + h - 8, w - 20, d, 8, 3);
        case 'monitor':
          return box(x + 28, y + 30, Z, 44, 44, 6, 4) + box(x + 44, y + 46, Z + 6, 12, 12, 18) +
                 box(x, y + 40, Z + 22, w, 14, h - 22, 3) +
                 `<g transform="${FRONT(x, y + 54, top)}"><rect class="face recess" x="6" y="6" width="${w - 12}" height="${h - 36}" rx="2"/>
                   ${[14, 26, 18, 34, 22].map((bh, i) => `<rect class="detail" x="${16 + i * 15}" y="${h - 32 - bh}" width="9" height="${bh}"/>`).join('')}</g>`;
        case 'server':
          return box(x, y, Z, w, d, h, 6);
        case 'term':
          return box(x, y, Z, w, d, h, 6) +
            onFront(`<rect class="face recess" x="8" y="6" width="${w - 16}" height="${h - 12}" rx="2"/>
              <text class="label" x="14" y="${h / 2 + 4}" font-size="11">&gt;_ wb</text>`);
        case 'shield':
          return box(x, y, Z, w, d, h, 6) +
            onFront(`<path class="icon" d="M${w / 2} 6 L${w / 2 + 12} 11 L${w / 2 + 11} 24 L${w / 2} 33 L${w / 2 - 11} 24 L${w / 2 - 12} 11 Z"/>
              <path class="icon" d="M${w / 2 - 5} 19 L${w / 2 - 1} 23 L${w / 2 + 6} 15"/>`);
        case 'ledger':
          return box(x, y, Z, w, d, h, 6) +
            onTop(`<path class="icon" d="M26 30 L64 58 M64 58 L104 30 M64 58 L64 76"/>
              ${[[26,30],[104,30],[64,58],[64,76]].map(([a, b]) => `<circle class="icon" cx="${a}" cy="${b}" r="5"/>`).join('')}`);
        case 'key':
          return box(x, y, Z, w, d, h, 8) +
            onTop(`<circle class="icon" cx="22" cy="${d / 2}" r="10"/>
              <path class="icon" d="M32 ${d / 2} L${w - 12} ${d / 2} M${w - 22} ${d / 2} L${w - 22} ${d / 2 + 10} M${w - 32} ${d / 2} L${w - 32} ${d / 2 + 7}"/>`);
        case 'doc':
          return box(x, y, Z, w, d, h, 2) +
            onTop(`<path class="icon" d="M${w - 24} 4 L${w - 24} 24 L${w - 4} 24"/>
              ${api.iso.slits(22, d - 14, 10, 12, w - 34, false)}`);
      }
      return box(x, y, Z, w, d, h, 6);
    }

    let svg = box(0, 0, 0, 900, 600, Z, 16);
    svg += `<g transform="${TOP(0,0,Z)}">
      <rect class="detail" x="12" y="12" width="876" height="576" rx="10"/>
      <rect class="detail" x="285" y="16" width="420" height="562" rx="8" stroke-dasharray="4 4"/>
      <rect class="detail" x="745" y="24" width="136" height="546" rx="8" stroke-dasharray="2 4"/>
      <text class="label sub" x="292" y="572" font-size="8">workbench vm · docker · panel serve</text>
      <text class="label sub" x="752" y="565" font-size="8">workspace data</text>
      <text class="label sub" x="30" y="582" font-size="9">cohort dashboard · service map</text>
      ${[[24,24],[876,24],[24,576],[876,576]].map(([a, b]) => `<circle class="detail" cx="${a}" cy="${b}" r="3"/>`).join('')}
    </g>`;

    for (const [k, pts] of Object.entries(E)) {
      const dd = pathD(pts), rev = pathD([...pts].reverse());
      svg += `<path class="wire-under" d="${dd}"/><path class="wire" id="dash-w-${k}" d="${dd}"/>`;
      svg += `<path class="pulse" id="dash-p-${k}-f" pathLength="1000" d="${dd}"/>`;
      svg += `<path class="pulse" id="dash-p-${k}-r" pathLength="1000" d="${rev}"/>`;
    }

    const order = Object.entries(N).sort(([, a], [, b]) => (a.x + a.y) - (b.x + b.y));
    for (const [id, n] of order) svg += `<g class="press" id="dash-n-${id}" data-node="${id}">${shape(id, n)}</g>`;

    const A = N.panel, aTop = Z + A.h;
    svg += `<g transform="${FRONT(A.x, A.y + A.d, aTop)}">
      <rect class="halo" id="dash-halo" filter="url(#bloom)" x="4" y="4" width="122" height="58" rx="6"/>
      <rect class="glass" id="dash-glass" filter="url(#soft)" x="8" y="8" width="114" height="50" rx="4"/>
      <text class="scr scr-accent" id="dash-l0" x="13" y="20" font-size="7"></text>
      <text class="scr" id="dash-st" x="117" y="20" font-size="6.5" text-anchor="end"></text>
      <text class="scr" id="dash-l1" x="13" y="36" font-size="6.8"></text>
      <text class="scr" id="dash-l2" x="13" y="48" font-size="6.8"></text>
      ${MODS.map(([m, lbl], i) => `<circle class="led" id="dash-m-${m}" filter="url(#soft)" cx="${17 + i * 24}" cy="68" r="2.6"/>
        <text class="label sub" x="${17 + i * 24}" y="80" font-size="5" text-anchor="middle">${lbl}</text>`).join('')}
    </g>`;
    svg += `<g transform="${SIDE(A.x + A.w, A.y + A.d, aTop)}">
      <text class="label" x="10" y="16" font-size="8">panel + holoviz</text>
      <text class="label sub" x="10" y="27" font-size="6">row cap 100k · in-memory</text>
      ${api.iso.slits(10, 120, 6, 40, 82)}
    </g>`;

    const NAME_FS = 13, ROLE_FS = 9.5;
    for (const [id, n] of order) {
      const [cx, cy] = ctr(id), [ax, ay] = P(cx, cy, Z + n.h), ty = ay - TAG_LIFT;
      const tw = Math.max(n.name.length * NAME_FS, n.role.length * ROLE_FS) * 0.6 + 16, th = 34;
      svg += `<g class="tag" id="dash-t-${id}" data-node="${id}">
        <line x1="${f2(ax)}" y1="${f2(ay)}" x2="${f2(ax)}" y2="${f2(ty)}"/>
        <rect x="${f2(ax - tw / 2)}" y="${f2(ty - th)}" width="${f2(tw)}" height="${th}" rx="5"/>
        <text class="nm" x="${f2(ax)}" y="${f2(ty - th + 15)}" font-size="${NAME_FS}" text-anchor="middle">${esc(n.name)}</text>
        <text class="rl" x="${f2(ax)}" y="${f2(ty - 7)}" font-size="${ROLE_FS}" text-anchor="middle">${esc(n.role)}</text>
      </g>`;
    }

    const [vx, vy, , vh] = K.viewBox.split(/[\s,]+/).map(Number);
    svg += `<g class="legend">
      <text class="label sub" x="${f2(vx + 18)}" y="${f2(vy + vh - 40)}" font-size="10">cylinder · data store     bucket · s3     chip · query engine     layers · cache</text>
      <text class="label sub" x="${f2(vx + 18)}" y="${f2(vy + vh - 24)}" font-size="10">gate · app proxy     key / shield / terminal · credentials     monitor · browser</text>
    </g>`;

    stage.setAttribute('viewBox', K.viewBox);
    stage.innerHTML = svg;

    const $ = id => stage.querySelector('#' + id);
    const st = { flow: -1, step: -1, focus: null, run: 0 };

    function nodesOf(step) {
      const s = new Set();
      step.e.forEach(x => { const g = edgeOf(x); s.add(g.a); s.add(g.b); });
      if (step.m.length) s.add('panel');
      return s;
    }

    function render() {
      const lit = new Set(), hotEdges = new Set(), latched = new Set(), mods = new Set();
      let l0 = 'cohort dashboard', stx = '', l1 = 'press 1–8 to play', l2 = 'or click a service';
      if (st.flow >= 0) {
        const f = FLOWS[st.flow];
        f.steps.slice(0, st.step + 1).forEach((s, i) => {
          s.e.forEach(x => hotEdges.add(edgeOf(x).key));
          nodesOf(s).forEach(n => (i === st.step ? lit : latched).add(n));
        });
        const cur = f.steps[st.step];
        cur.m.forEach(m => mods.add(m));
        l0 = `${st.flow + 1} · ${f.name}`; stx = `${st.step + 1}/${f.steps.length}`;
        [l1, l2] = cur.t;
      } else if (st.focus) {
        const n = N[st.focus];
        latched.add(st.focus);
        for (const k of Object.keys(E)) if (k.split('-').includes(st.focus)) { hotEdges.add(k); k.split('-').forEach(x => x !== st.focus && lit.add(x)); }
        l0 = n.name.toLowerCase(); [l1, l2] = n.info;
      }
      for (const k of Object.keys(E)) $(`dash-w-${k}`).classList.toggle('hot', hotEdges.has(k));
      for (const id of Object.keys(N)) {
        const on = latched.has(id) && !lit.has(id);
        $(`dash-n-${id}`).classList.toggle('lit', lit.has(id));
        $(`dash-n-${id}`).classList.toggle('latched', on);
        $(`dash-t-${id}`).classList.toggle('hot', lit.has(id));
        $(`dash-t-${id}`).classList.toggle('on', on);
      }
      for (const [m] of MODS) $(`dash-m-${m}`).classList.toggle('hot', mods.has(m));
      const on = st.flow >= 0 || !!st.focus;
      $('dash-glass').classList.toggle('hot', on); $('dash-halo').classList.toggle('hot', on);
      $('dash-l0').textContent = l0; $('dash-st').textContent = stx;
      $('dash-l1').textContent = l1; $('dash-l2').textContent = l2;
      api.power(on);
      api.readout(st.flow >= 0 ? `flow ${st.flow + 1} · ${FLOWS[st.flow].name} · step ${stx}`
        : st.focus ? `${N[st.focus].name.toLowerCase()} · ${hotEdges.size} links` : 'idle · keys 1–8');
    }

    function pulse() {
      if (st.flow < 0) return;
      for (const x of FLOWS[st.flow].steps[st.step].e) { const g = edgeOf(x); api.replay($(`dash-p-${g.key}-${g.dir}`)); }
    }

    function play(i) {
      const run = ++st.run, f = FLOWS[i];
      st.flow = i; st.focus = null;
      const go = s => {
        if (run !== st.run) return;
        st.step = s; render(); pulse();
        if (s + 1 < f.steps.length) api.after(1500, () => go(s + 1));
      };
      go(0);
    }

    function clear() { st.run++; st.flow = -1; st.step = -1; st.focus = null; render(); }

    api.every(1000, pulse);

    stage.addEventListener('click', e => {
      const g = e.target.closest('[data-node]'); if (!g) return;
      const id = g.dataset.node;
      st.run++; st.flow = -1; st.step = -1;
      st.focus = st.focus === id ? null : id;
      render();
    });

    render();
    return {
      key: e => {
        if (e.key >= '1' && e.key <= String(FLOWS.length)) { play(+e.key - 1); return true; }
        if (e.key === ' ' || e.key === 'Enter') { play((st.flow + 1) % FLOWS.length); return true; }
        if (e.key === 'Escape' || e.key === '0') { clear(); return true; }
        return false;
      },
      demo: () => api.after(300, () => play(1)),
    };
  },
});
