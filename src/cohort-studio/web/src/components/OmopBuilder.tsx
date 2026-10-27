import { useEffect, useRef, useState } from "react";
import { api, OpenResult, CohortAgentResult } from "../api";
import type { OmopConcept, OmopCount, OmopCriterion, OmopDomain, OmopInfo, OmopSpec, OmopSummary, Source } from "../types";
import { ChartCard } from "./ChartCard";

const domains: OmopDomain[] = ["condition", "drug", "procedure", "measurement", "observation", "visit", "device", "death"];
const openTables = new Set(["person", "observation_period", "condition_occurrence", "drug_exposure",
  "procedure_occurrence", "measurement", "observation", "visit_occurrence", "device_exposure",
  "death", "visit_detail", "specimen", "condition_era", "drug_era", "dose_era", "payer_plan_period"]);
type Rule = OmopCriterion & { names: string[] };
const numeric = (value: string) => value === "" ? undefined : Number(value);

export function OmopBuilder({ source, active, palette, onOpen }: {
  source: Source | null;
  active: boolean;
  palette: string;
  onOpen: (result: OpenResult, title: string) => void;
}) {
  const [visited, setVisited] = useState<string[]>([]);
  const activeRid = active && source?.kind === "aurora" ? source.id : null;
  useEffect(() => {
    if (activeRid) {
      setVisited((previous) => previous.includes(activeRid)
        ? previous : [...previous, activeRid]);
    }
  }, [activeRid]);
  const resourceIds = [...new Set([
    ...visited,
    ...(activeRid ? [activeRid] : []),
  ])];

  return <section className="omop-builder" aria-label="OMOP cohort builder">
    <h2>OMOP cohorts</h2>
    {active && source?.kind !== "aurora" && <p>
      Select an Aurora datasource with an existing OMOP schema. Selecting a
      datasource does not import data.
    </p>}
    {resourceIds.map((rid) => <div key={rid} hidden={!active || source?.id !== rid}>
      <Editor rid={rid} active={active && source?.id === rid} palette={palette} onOpen={onOpen} />
    </div>)}
  </section>;
}

function Editor({ rid, active, palette, onOpen }: {
  rid: string; active: boolean; palette: string;
  onOpen: (r: OpenResult, title: string) => void;
}) {
  const [info, setInfo] = useState<OmopInfo | null>(null);
  const [chartTitles, setChartTitles] = useState<Record<string, string>>({});
  const [rules, setRules] = useState<Rule[]>([]);
  const [domain, setDomain] = useState<OmopDomain>("condition");
  const [q, setQ] = useState("");
  const [standard, setStandard] = useState(true);
  const [results, setResults] = useState<OmopConcept[] | null>(null);
  const [selected, setSelected] = useState<OmopConcept[]>([]);
  const [observed, setObserved] = useState(true);
  const [demo, setDemo] = useState<OmopSpec["demographics"]>({});
  const [count, setCount] = useState<OmopCount | null>(null);
  const [summary, setSummary] = useState<OmopSummary | null>(null);
  const [summaryView, setSummaryView] = useState<"charts" | "table">("charts");
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState("");
  const [name, setName] = useState("OMOP cohort");
  const [table, setTable] = useState("person");
  const [restrict, setRestrict] = useState(true);
  const [names, setNames] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [prompt, setPrompt] = useState("");
  const [history, setHistory] = useState<{ role: string; content: string }[]>([]);
  const [chatSessionId, setChatSessionId] = useState<string>();
  const [historyBefore, setHistoryBefore] = useState<number | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  useEffect(() => {
    let cancelled = false;
    setHistory([]); setChatSessionId(undefined); setHistoryBefore(null); setHistoryLoading(true); setHistoryError("");
    api.chatHistory("omop", rid).then(out => {
      if (cancelled) return;
      setHistory(out.messages); setChatSessionId(out.session_id ?? undefined);
      setHistoryBefore(out.has_more ? out.next_before_message_id : null);
    }).catch(e => { if (!cancelled) setHistoryError(e.message); }).finally(() => { if (!cancelled) setHistoryLoading(false); });
    return () => { cancelled = true; };
  }, [rid]);
  const [proposal, setProposal] = useState<CohortAgentResult | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const run = async (label: string, action: () => Promise<void>) => {
    setBusy(label); setError("");
    try { await action(); } catch (e) { if (mounted.current) setError((e as Error).message); }
    finally { if (mounted.current) setBusy(""); }
  };
  useEffect(() => {
    let cancelled = false;
    setBusy("Detecting OMOP…");
    api.omopInfo(rid).then((data) => { if (!cancelled) setInfo(data); })
      .catch((e) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setBusy(""); });
    return () => { cancelled = true; };
  }, [rid]);
  const spec: OmopSpec = { criteria: rules.map(({ names: _names, ...rule }) => rule),
    require_observation: observed, demographics: demo };
  const specKey = JSON.stringify(spec);
  const specVersion = useRef(0);
  const currentSpec = useRef(spec);
  currentSpec.current = spec;
  const summaryValid = [...rules.flatMap((rule) => [rule.min_count, rule.value_min,
    rule.value_max]), demo.age_min, demo.age_max, demo.year_of_birth_min,
    demo.year_of_birth_max].every((value) => value === undefined || Number.isFinite(value))
    && rules.every((rule) => (rule.min_count === undefined
        || (Number.isInteger(rule.min_count) && rule.min_count >= 1))
      && (!rule.start || !rule.end || rule.start <= rule.end)
      && (rule.value_min === undefined || rule.value_max === undefined
        || rule.value_min <= rule.value_max))
    && (demo.age_min === undefined || demo.age_max === undefined || demo.age_min <= demo.age_max)
    && (demo.year_of_birth_min === undefined || demo.year_of_birth_max === undefined
      || demo.year_of_birth_min <= demo.year_of_birth_max);
  const clearSummary = () => { setSummary(null); setSummaryError(""); };
  const invalidateSpecResult = () => {
    specVersion.current += 1;
    setCount(null);
    clearSummary();
  };
  useEffect(() => {
    if (!active) return;
    setSummary(null);
    setSummaryError("");
    if (!info?.cdm || !summaryValid) return;
    let cancelled = false;
    const requestVersion = specVersion.current;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setSummaryLoading(true);
      api.omopSummary(rid, spec, controller.signal).then((data) => {
        if (!cancelled && requestVersion === specVersion.current
            && JSON.stringify(currentSpec.current) === specKey) setSummary(data);
      }).catch((error) => {
        if (!cancelled && requestVersion === specVersion.current
            && error.name !== "AbortError")
          setSummaryError((error as Error).message);
      }).finally(() => {
        if (!cancelled) setSummaryLoading(false);
      });
    }, 600);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      controller.abort();
      setSummaryLoading(false);
    };
  }, [active, rid, info?.cdm, info?.cdm_schema, info?.vocab_schema,
      specKey, summaryValid]); // eslint-disable-line react-hooks/exhaustive-deps

  const changeRules = (next: Rule[]) => {

    const first = next.findIndex((r) => !r.exclude);
    setRules(next.map((r, i) => i === first ? { ...r, index_relation: undefined } : r));
    invalidateSpecResult();
  };
  const update = (i: number, patch: Partial<Rule>) => changeRules(rules.map((r, j) => j === i ? { ...r, ...patch } : r));
  const first = rules.findIndex((r) => !r.exclude);
  const refresh = () => run("Detecting OMOP…", async () => {
    const out = await api.omopInfo(rid, true);
    if (mounted.current) { setInfo(out); setCount(null); }
  });
  const countCohort = () => {
    const requestSpec = spec;
    const requestVersion = specVersion.current;
    const requestKey = JSON.stringify(requestSpec);
    return run("Counting cohort…", async () => {
      const out = await api.omopCount(rid, requestSpec);
      if (mounted.current && requestVersion === specVersion.current
          && JSON.stringify(currentSpec.current) === requestKey) setCount(out);
    });
  };
  const openCohort = () => {
    const requestSpec = spec;
    const requestName = name.trim();
    return run("Opening cohort…", async () => {
      const out = await api.omopOpen(rid, requestSpec, requestName);
      if (mounted.current) onOpen(out, requestName);
    });
  };
  const summaryCharts = summary ? [
    { title: "Gender", data: summary.charts.gender.map((item) =>
      ({ category: item.category, value: item.persons })) },
    { title: "Age at index", data: summary.charts.age_at_index.map((item) =>
      ({ category: item.category, value: item.persons })) },
    ...summary.charts.domains.map((item) => ({
      title: `All recorded ${item.domain} events for cohort`,
      data: item.concepts.map((concept) =>
        ({ category: concept.label, value: concept.persons })),
    })),
    { title: "Attrition", data: summary.attrition.map((item) =>
      ({ category: item.label, value: item.persons })) },
  ].filter((chart) => chart.data.length > 0) : [];
  const currentCount: OmopCount | null = count ?? (summary ? {
    persons: summary.persons, total_persons: summary.total_persons,
    attrition: summary.attrition,
  } : null);

  return <>
    <div className="omop-toolbar">
      {info?.cdm && <span>CDM {info.version ?? "unknown version"} · {info.cdm_schema}</span>}
      <button onClick={refresh} disabled={!!busy}>Refresh detection</button>
      {busy && <span role="status">{busy}</span>}
    </div>
    {error && <p role="alert" className="omop-error">{error}</p>}
    {info && !info.cdm && <p role="status">
      No OMOP CDM schema is visible in the selected Aurora datasource. Cohort
      tools query an existing schema. No data was imported automatically.
    </p>}
    {info?.cdm && <fieldset className="omop-fields" disabled={!!busy}>
      <div className="omop-grid">
        <div>
          <section className="omop-card">
            <h3>Find concepts</h3>
            <div className="omop-row">
              <label>Domain<select value={domain} onChange={(e) => {
                setDomain(e.target.value as OmopDomain); setSelected([]); setResults(null);
              }}>{domains.map((d) => <option key={d}>{d}</option>)}</select></label>
              <label>Concept name, ID or code<input type="text" value={q} onChange={(e) => { setQ(e.target.value); setResults(null); }} /></label>
            </div>
            <label className="omop-check"><input type="checkbox" checked={standard} onChange={(e) => { setStandard(e.target.checked); setResults(null); }} />Standard concepts only</label>
            <button disabled={!info.vocab_schema} onClick={() => run("Searching…", async () => {
              const out = await api.omopConcepts(rid, q, domain, standard);
              if (mounted.current) setResults(out.concepts);
            })}>Search concepts</button>
            {!info.vocab_schema && <p>Vocabulary tables are missing. Concept search is unavailable.</p>}
            {results && <div className="omop-search" aria-label="Concept results">
              {results.length === 0 && <p>No matching concepts.</p>}
              {results.map((c) => <label key={c.concept_id} className="omop-result">
                <input type="checkbox" checked={selected.some((s) => s.concept_id === c.concept_id)} onChange={(e) => setSelected(e.target.checked
                  ? [...selected, c] : selected.filter((s) => s.concept_id !== c.concept_id))} />
                <span><strong>{c.concept_name}</strong><small>{c.concept_id} · {c.vocabulary_id} · {c.persons === null ? "Person count unknown" : `${c.persons.toLocaleString()} persons (exact concept)`}</small></span>
              </label>)}
            </div>}
            <p className="settings-hint">Concepts use OR; criteria use AND.</p>
            <button disabled={domain !== "death" && !selected.length} onClick={() => {
              changeRules([...rules, { domain, concept_ids: selected.map((c) => c.concept_id),
                names: selected.map((c) => c.concept_name), descendants: !!info.vocab_schema, min_count: 1 }]);
              setSelected([]);
            }}>Add criterion{selected.length ? ` (${selected.length} concepts)` : ""}</button>
          </section>
          <section className="omop-card">
            <h3>Define cohort</h3>
            <p className="settings-hint">Index date is the first included event, or the first observation start. Age is measured at index.</p>
            {!rules.length && <p>No event criteria: all persons who meet the observation and demographic filters.</p>}
            {rules.map((r, i) => <div className="omop-rule" key={i} aria-label={`Criterion ${i + 1}`}>
              <div className="omop-toolbar"><strong>{i + 1}. {r.names.join(" OR ") || "Death"}</strong>
                {i === first && <span className="settings-hint">Index event</span>}
                <button aria-label={`Remove criterion ${i + 1}`} onClick={() => changeRules(rules.filter((_, j) => j !== i))}>Remove</button>
              </div>
              <div className="omop-row">
                <label>Match<select value={r.exclude ? "exclude" : "include"} onChange={(e) => update(i, { exclude: e.target.value === "exclude" })}>
                  <option value="include">Include</option><option value="exclude">Exclude</option></select></label>
                <label>Minimum events<input type="number" min={1} value={r.min_count ?? ""} onChange={(e) => update(i, { min_count: numeric(e.target.value) })} /></label>
                <label>Timing<select value={r.index_relation ?? ""} disabled={i === first} onChange={(e) => update(i, { index_relation: (e.target.value || undefined) as Rule["index_relation"] })}>
                  <option value="">Any time</option><option value="before">Before index (strict)</option><option value="after">After index (strict)</option></select></label>
              </div>
              <div className="omop-row">
                <label>Start date<input type="date" value={r.start ?? ""} onChange={(e) => update(i, { start: e.target.value || undefined })} /></label>
                <label>End date<input type="date" value={r.end ?? ""} onChange={(e) => update(i, { end: e.target.value || undefined })} /></label>
                {r.domain === "measurement" && <>
                  <label>Minimum value<input type="number" value={r.value_min ?? ""} onChange={(e) => update(i, { value_min: numeric(e.target.value) })} /></label>
                  <label>Maximum value<input type="number" value={r.value_max ?? ""} onChange={(e) => update(i, { value_max: numeric(e.target.value) })} /></label>
                </>}
              </div>
              <label className="omop-check"><input type="checkbox" checked={r.descendants ?? true} onChange={(e) => update(i, { descendants: e.target.checked })} />Include descendants</label>
            </div>)}
            <label className="omop-check"><input type="checkbox" checked={observed} onChange={(e) => { setObserved(e.target.checked); invalidateSpecResult(); }} />Require events within an observation period (except death)</label>
            <div className="omop-row">
              <label>Gender<select value={demo.gender_concept_ids?.[0] ?? ""} onChange={(e) => { setDemo({ ...demo, gender_concept_ids: e.target.value ? [Number(e.target.value)] : [] }); invalidateSpecResult(); }}>
                <option value="">Any</option><option value="8532">Female</option><option value="8507">Male</option></select></label>
              {([['age_min', 'Minimum age'], ['age_max', 'Maximum age'], ['year_of_birth_min', 'Birth year from'], ['year_of_birth_max', 'Birth year to']] as const).map(([key, label]) =>
                <label key={key}>{label}<input type="number" value={demo[key] ?? ""} onChange={(e) => { setDemo({ ...demo, [key]: numeric(e.target.value) }); invalidateSpecResult(); }} /></label>)}
            </div>
          </section>
        </div>
        <div>
          <section className="omop-card" aria-label="Cohort assistant">
            <h3>Cohort assistant</h3>
            <div className="omop-chat" aria-live="polite">
              {historyBefore !== null && <button disabled={historyLoading || !!busy} onClick={() => run("Loading history…", async () => {
                const out = await api.chatHistory("omop", rid, chatSessionId, historyBefore);
                setHistory([...out.messages, ...history]);
                setHistoryBefore(out.has_more ? out.next_before_message_id : null);
              })}>Earlier messages</button>}
              {history.map((m, i) => <p key={i}><strong>{m.role === "user" ? "You" : "Assistant"}:</strong> {m.content}</p>)}
            </div>
            {historyError && <p role="alert">{historyError}</p>}
            <label>Ask the cohort assistant<textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} maxLength={8000} /></label>
            <button disabled={!prompt.trim() || historyLoading || !!busy} onClick={() => run("Asking cohort assistant…", async () => {
              const message = prompt.trim();
              const out = await api.omopAgent(rid, message, history, spec, chatSessionId);
              if (!mounted.current) return;
              setChatSessionId(out.session_id);
              setHistory([...history, { role: "user", content: message }, { role: "assistant", content: out.reply }]);
              setPrompt(""); setProposal(out.spec ? out : null);
            })}>Ask assistant</button>
            {proposal?.spec && <div className="omop-proposal">
              <p>{proposal.reason || "Proposed cohort"}</p>
              <details><summary>Review proposed criteria</summary><pre>{JSON.stringify(proposal.spec, null, 2)}</pre></details>
              <button onClick={() => {
                const next = proposal.spec!;
                changeRules(next.criteria.map((r) => ({ ...r, names: r.concept_ids.map((id) => proposal.concept_names?.[String(id)] || `Concept ${id}`) })));
                setObserved(next.require_observation); setDemo(next.demographics);

                setCount(null); setProposal(null);
              }}>Apply proposed cohort</button>
            </div>}
          </section>
          <section className="omop-card">
            <h3>Count and explore</h3>
            <button className="primary" onClick={countCohort}>Count cohort</button>
            {currentCount && <div aria-label="Cohort count">
              <p className="omop-count">{currentCount.persons.toLocaleString()} <span>of {currentCount.total_persons.toLocaleString()} persons</span></p>
              <table className="omop-attrition"><thead><tr><th>Step</th><th>Persons</th></tr></thead><tbody>
                {[{ label: "All persons", persons: currentCount.total_persons }, ...currentCount.attrition].map((step, i) =>
                  <tr key={i}><td>{step.label}</td><td>{step.persons.toLocaleString()}</td></tr>)}
              </tbody></table>
            </div>}
            <label>Cohort name<input type="text" value={name} onChange={(e) => setName(e.target.value)} /></label>
            <button disabled={!currentCount || !name.trim()} onClick={openCohort}>Open cohort</button>
            <p className="settings-hint">Counts use the full database. Open datasets use the app row limit.</p>
          </section>
          <section className="omop-card">
            <h3>Explore clinical tables</h3>
            <label>Clinical table<select value={table} onChange={(e) => setTable(e.target.value)}>
              {info.tables?.filter((t) => openTables.has(t.name)).map((t) =>
                <option key={t.name} value={t.name}>{t.name} ({t.approx ? "≈" : ""}{t.rows.toLocaleString()} rows)</option>)}
            </select></label>
            <label className="omop-check"><input type="checkbox" checked={restrict} onChange={(e) => setRestrict(e.target.checked)} />Restrict to current cohort</label>
            <label className="omop-check"><input type="checkbox" checked={names} onChange={(e) => setNames(e.target.checked)} />Add concept names</label>
            <button disabled={restrict && !currentCount} onClick={() => run("Opening clinical table…", async () => {
              const out = await api.omopDomain(rid, table, restrict ? spec : null, names);
              if (mounted.current) onOpen(out, table);
            })}>Open clinical table</button>
          </section>
        </div>
      </div>
          <section className="omop-card" aria-label="OMOP cohort summary">
            <div className="omop-results-heading"><h3>Cohort summary</h3>
              <div className="explore-toggle" role="group" aria-label="Summary view">
                <button aria-pressed={summaryView === "charts"} onClick={() => setSummaryView("charts")}>Charts</button>
                <button aria-pressed={summaryView === "table"} onClick={() => setSummaryView("table")}>Table</button>
              </div>
              <button disabled={!currentCount || !name.trim()} onClick={openCohort}>View people</button>
            </div>
            {summaryLoading && <span role="status">Updating charts…</span>}
            {summaryError && <p role="alert" className="omop-error">{summaryError}</p>}
            {summary && <>
              <p>{summary.persons.toLocaleString()} of {summary.total_persons.toLocaleString()} persons</p>
              {summaryView === "charts" ? <div className="omop-summary-charts">
                {summaryCharts.map((chart) => (
                  <ChartCard key={chart.title} spec={{ kind: "bar", x: chart.title, title: chartTitles[chart.title] }}
                    result={{ kind: "bar", x: chart.title, data: chart.data }}
                    palette={palette} kinds={["bar"]} readOnly
                    compactCategoryLabels
                    onTapCategory={() => undefined} onChangeKind={() => undefined}
                    onRename={(title) => setChartTitles((current) => ({ ...current, [chart.title]: title }))}
                    onToggleWide={() => undefined} onClose={() => undefined} />
                ))}
              </div> : <div className="omop-summary-tables">{summaryCharts.map((chart) => (
                <table key={chart.title} aria-label={chartTitles[chart.title] || chart.title} className="omop-attrition">
                  <caption>{chartTitles[chart.title] || chart.title}</caption><thead><tr><th>Category</th><th>Persons</th></tr></thead>
                  <tbody>{chart.data.map((row, i) => <tr key={i}><td>{row.category}</td><td>{row.value.toLocaleString()}</td></tr>)}</tbody>
                </table>
              ))}</div>}
            </>}
          </section>
    </fieldset>}
  </>;
}
