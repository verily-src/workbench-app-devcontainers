FIGS.push({
  id: 'cohort', name: 'Cohort Studio · service map',
  hint: '1–6 play a flow · space next · click a service · esc clear',
  aria: 'Isometric map of Cohort Studio and the services it talks to. Press 1 to 6 to play a request flow, or click a service to see its connections.',
  css: `[data-fig="cohort"] .press.lit .label, [data-fig="cohort"] .press.latched .label { fill:var(--panel); }
        [data-fig="cohort"] .sub { opacity:.7; }`,
  mount(stage, api) {
    const Z = 10;
    const K = api.iso.frame([[0,0,0],[640,0,0],[0,560,0],[640,560,0],[230,220,Z+84],[40,40,Z+44],[470,40,Z+34]]);
    const { P, TOP, FRONT, SIDE, box } = K;
    const esc = api.iso.esc;

    const N = {
      workflows: { x:40,  y:40,  w:110, d:90,  h:44, t:'WORKFLOWS', s:'nextflow · omics',   info:['workbench workflow jobs','outputs land in s3'] },
      llm:       { x:215, y:40,  w:90,  d:80,  h:36, t:'LLM API',   s:'chat · ask ai',      info:['claude / openai / gemini','key held server-side'] },
      git:       { x:325, y:40,  w:60,  d:80,  h:28, t:'GIT',       s:'branch tar',         info:['branch tarball','source for self-update'] },
      bq:        { x:470, y:40,  w:100, d:90,  h:34, t:'BIGQUERY',  s:'bq.py',              info:['bigquery datasets','read via bq.py'] },
      wb:        { x:40,  y:210, w:110, d:90,  h:30, t:'WB CLI',    s:'auth · resource · job', info:['wb resource resolve','wb workflow job run'] },
      api:       { x:230, y:220, w:140, d:120, h:84, t:'FASTAPI',   s:'uvicorn pid 1',      info:['fastapi · /api + /mcp','in-memory cohort store'] },
      s3:        { x:470, y:210, w:100, d:90,  h:40, t:'S3',        s:'duckdb parquet/csv', info:['parquet / csv / json','duckdb + aws profile'] },
      browser:   { x:40,  y:400, w:120, d:90,  h:40, t:'BROWSER',   s:'react · echarts',    info:['react + ts + echarts','thin: renders aggs'] },
      agent:     { x:230, y:440, w:100, d:80,  h:30, t:'MCP AGENT', s:'external client',    info:['any mcp client','drives the builder'] },
      aurora:    { x:470, y:400, w:100, d:90,  h:56, t:'AURORA',    s:'postgres',           info:['tables · views','lineage · agent turns'] },
    };

    const E = {
      'browser-api':  [[100,400],[100,370],[250,370],[250,340]],
      'agent-api':    [[290,440],[290,340]],
      'api-wb':       [[230,260],[150,260]],
      'wb-workflows': [[95,210],[95,130]],
      'api-llm':      [[260,220],[260,120]],
      'api-git':      [[355,220],[355,120]],
      'api-s3':       [[370,255],[470,255]],
      'api-bq':       [[370,232],[430,232],[430,85],[470,85]],
      'api-aurora':   [[370,320],[420,320],[420,445],[470,445]],
      'workflows-s3': [[150,100],[190,100],[190,170],[500,170],[500,210]],
    };

    const MODS = [['data','data'],['agent','agent'],['views','views'],['lin','lineage'],['mcp','mcp']];

    const FLOWS = [
      { name:'explore a cohort', steps:[
        { e:['api>wb'], m:['data'], t:['wb resource list','resolve → abac creds'] },
        { e:['api>aurora','api>s3','api>bq'], m:['data'], t:['load the table','sqlalchemy·duckdb·bq'] },
        { e:['browser>api'], m:['data'], t:['POST /query','filters + chart specs'] },
        { e:['api>browser','api>aurora'], m:['data','lin'], t:['counts·aggs·50 rows','lineage event logged'] },
      ]},
      { name:'ask ai / chat', steps:[
        { e:['browser>api'], m:['agent'], t:['POST /ask · /chat','natural language'] },
        { e:['api>llm'], m:['agent'], t:['selected provider','tool runner'] },
        { e:['llm>api'], m:['agent','data'], t:['tool calls','filters on dataset'] },
        { e:['api>aurora','api>browser'], m:['agent','lin'], t:['_agent_turn row','answer + filters'] },
      ]},
      { name:'save a view', steps:[
        { e:['browser>api'], m:['views'], t:['POST /views','tabs·filters·charts'] },
        { e:['api>wb'], m:['views'], t:['wb auth status','owner of the view'] },
        { e:['api>aurora','api>s3'], m:['views'], t:['_studio_views row','or a json object'] },
        { e:['api>browser'], m:['views'], t:['view saved','shareable link'] },
      ]},
      { name:'cohort → workflow', steps:[
        { e:['browser>api'], m:['data'], t:['export cohort','filtered rows'] },
        { e:['api>s3'], m:['data','lin'], t:['cohort csv → bucket','lineage: exported'] },
        { e:['api>wb'], m:['lin'], t:['wb workflow job run','batch input csv'] },
        { e:['wb>workflows'], m:[], t:['nextflow / omics','job running'] },
        { e:['workflows>s3','api>wb'], m:[], t:['outputs → s3 bucket','poll: running badge'] },
      ]},
      { name:'external agent', steps:[
        { e:['agent>api'], m:['mcp'], t:['/mcp streamable http','list_datasources'] },
        { e:['api>aurora','api>s3'], m:['mcp','data'], t:['open_dataset','same store as the ui'] },
        { e:['api>agent'], m:['mcp','data'], t:['query_dataset','counts + aggregates'] },
      ]},
      { name:'restart-to-deploy', steps:[
        { e:['browser>api'], m:[], t:['POST /admin/update','self_update.sh'] },
        { e:['api>git'], m:[], t:['fetch branch tarball','npm build → static'] },
        { e:[], m:[], t:['pkill uvicorn pid 1','docker restarts it'], restart:true },
        { e:['api>browser'], m:[], t:['GET /version','new sha is live'] },
      ]},
    ];

    const edgeOf = s => {
      const [a, b] = s.split('>');
      if (E[`${a}-${b}`]) return { key:`${a}-${b}`, dir:'f', a, b };
      return { key:`${b}-${a}`, dir:'r', a, b };
    };
    const pathD = pts => 'M' + pts.map(([x, y]) => P(x, y, Z).join(' ')).join(' L');

    let svg = box(0, 0, 0, 640, 560, Z, 16);
    svg += `<g transform="${TOP(0,0,Z)}">
      <rect class="detail" x="12" y="12" width="616" height="536" rx="10"/>
      <rect class="detail" x="205" y="195" width="190" height="172" rx="8" stroke-dasharray="4 4"/>
      <text class="label sub" x="212" y="361" font-size="7">workbench vm · docker · restart: always</text>
      <text class="label sub" x="360" y="540" font-size="9">cohort studio · service map</text>
      ${[[24,24],[616,24],[24,536],[616,536]].map(([x, y]) => `<circle class="detail" cx="${x}" cy="${y}" r="3"/>`).join('')}
    </g>`;

    for (const [k, pts] of Object.entries(E)) {
      const d = pathD(pts), rev = pathD([...pts].reverse());
      svg += `<path class="wire-under" d="${d}"/><path class="wire" id="cohort-w-${k}" d="${d}"/>`;
      svg += `<path class="pulse" id="cohort-p-${k}-f" pathLength="1000" d="${d}"/>`;
      svg += `<path class="pulse" id="cohort-p-${k}-r" pathLength="1000" d="${rev}"/>`;
    }

    const order = Object.entries(N).sort(([, a], [, b]) => (a.x + a.y) - (b.x + b.y));
    for (const [id, n] of order) {
      const top = Z + n.h;
      svg += `<g class="press" id="cohort-n-${id}" data-node="${id}">${box(n.x, n.y, Z, n.w, n.d, n.h, 6)}`;
      svg += `<g transform="${TOP(n.x, n.y, top)}">
        <text class="label" x="9" y="${n.d / 2}" font-size="11">${esc(n.t)}</text>
        <text class="label sub" x="9" y="${n.d / 2 + 12}" font-size="7">${esc(n.s)}</text></g>`;
      if (id !== 'api') {
        svg += `<g transform="${FRONT(n.x, n.y + n.d, top)}">
          <circle class="led" id="cohort-led-${id}" filter="url(#soft)" cx="${n.w - 12}" cy="9" r="2.6"/>
          ${api.iso.slits(8, Math.min(n.w - 24, 56), 6, n.h - 12, n.h - 5)}</g>`;
      }
      svg += `</g>`;
    }

    const A = N.api, aTop = Z + A.h;
    svg += `<g transform="${FRONT(A.x, A.y + A.d, aTop)}">
      <rect class="halo" id="cohort-halo" filter="url(#bloom)" x="4" y="4" width="132" height="58" rx="6"/>
      <rect class="glass" id="cohort-glass" filter="url(#soft)" x="8" y="8" width="124" height="50" rx="4"/>
      <text class="scr scr-accent" id="cohort-l0" x="14" y="20" font-size="7.5"></text>
      <text class="scr" id="cohort-st" x="126" y="20" font-size="7" text-anchor="end"></text>
      <text class="scr" id="cohort-l1" x="14" y="36" font-size="7"></text>
      <text class="scr" id="cohort-l2" x="14" y="48" font-size="7"></text>
      ${MODS.map(([m, lbl], i) => `<circle class="led" id="cohort-m-${m}" filter="url(#soft)" cx="${20 + i * 25}" cy="66" r="2.6"/>
        <text class="label sub" x="${20 + i * 25}" y="78" font-size="5" text-anchor="middle">${lbl}</text>`).join('')}
    </g>`;
    svg += `<g transform="${SIDE(A.x + A.w, A.y + A.d, aTop)}">
      <text class="label" x="10" y="16" font-size="8">/api  ·  /mcp</text>
      <text class="label sub" x="10" y="27" font-size="6">:8080 behind workbench proxy</text>
      ${api.iso.slits(10, 110, 6, 40, 74)}
    </g>`;

    stage.setAttribute('viewBox', K.viewBox);
    stage.innerHTML = svg;

    const $ = id => stage.querySelector('#' + id);
    const st = { flow: -1, step: -1, focus: null, run: 0 };

    function nodesOf(step) { const s = new Set(); step.e.forEach(x => { const g = edgeOf(x); s.add(g.a); s.add(g.b); }); s.add('api'); return s; }

    function render() {
      const lit = new Set(), hotEdges = new Set(), latched = new Set(), mods = new Set();
      let l0 = 'cohort studio', stx = '', l1 = 'press 1–6 to play', l2 = 'or click a service';
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
        l0 = n.t.toLowerCase(); [l1, l2] = n.info;
      }
      for (const k of Object.keys(E)) $(`cohort-w-${k}`).classList.toggle('hot', hotEdges.has(k));
      for (const id of Object.keys(N)) {
        const g = $(`cohort-n-${id}`);
        g.classList.toggle('lit', lit.has(id) && !(st.focus && id === st.focus));
        g.classList.toggle('latched', latched.has(id) && !lit.has(id));
        const led = $(`cohort-led-${id}`); if (led) led.classList.toggle('hot', lit.has(id) || latched.has(id));
      }
      for (const [m] of MODS) $(`cohort-m-${m}`).classList.toggle('hot', mods.has(m));
      const on = st.flow >= 0 || !!st.focus;
      $('cohort-glass').classList.toggle('hot', on); $('cohort-halo').classList.toggle('hot', on);
      $('cohort-l0').textContent = l0; $('cohort-st').textContent = stx;
      $('cohort-l1').textContent = l1; $('cohort-l2').textContent = l2;
      api.power(on);
      api.readout(st.flow >= 0 ? `flow ${st.flow + 1} · ${FLOWS[st.flow].name} · step ${stx}`
        : st.focus ? `${st.focus} · ${hotEdges.size} links` : 'idle · keys 1–6');
    }

    function pulse() {
      if (st.flow < 0) return;
      for (const x of FLOWS[st.flow].steps[st.step].e) { const g = edgeOf(x); api.replay($(`cohort-p-${g.key}-${g.dir}`)); }
    }

    function play(i) {
      const run = ++st.run, f = FLOWS[i];
      st.flow = i; st.focus = null;
      const go = s => {
        if (run !== st.run) return;
        st.step = s; render(); pulse();
        if (f.steps[s].restart) api.flash($('cohort-n-api'));
        if (s + 1 < f.steps.length) api.after(1400, () => go(s + 1));
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
      api.flash(g); render();
    });

    render();
    return {
      key: e => {
        if (e.key >= '1' && e.key <= String(FLOWS.length)) { play(+e.key - 1); return true; }
        if (e.key === ' ' || e.key === 'Enter') { play((st.flow + 1) % FLOWS.length); return true; }
        if (e.key === 'Escape' || e.key === '0') { clear(); return true; }
        return false;
      },
      demo: () => api.after(300, () => play(0)),
    };
  },
});
