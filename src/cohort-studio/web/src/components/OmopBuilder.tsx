import { useEffect, useRef, useState } from "react";
import { api, OpenResult, CohortAgentResult } from "../api";
import type { OmopConcept, OmopCount, OmopCriterion, OmopDomain, OmopInfo, OmopSpec, Source } from "../types";

const domains: OmopDomain[] = ["condition", "drug", "procedure", "measurement", "observation", "visit", "device", "death"];
const openTables = new Set(["person", "observation_period", "condition_occurrence", "drug_exposure",
  "procedure_occurrence", "measurement", "observation", "visit_occurrence", "device_exposure",
  "death", "visit_detail", "specimen", "condition_era", "drug_era", "dose_era", "payer_plan_period"]);
type Rule = OmopCriterion & { names: string[] };
const numeric = (value: string) => value === "" ? undefined : Number(value);

export function OmopBuilder({ sources, onOpen }: {
  sources: Source[]; onOpen: (result: OpenResult, title: string) => void;
}) {
  const aurora = sources.filter((s) => s.kind === "aurora");
  const [rid, setRid] = useState("");
  // Remount the editor when the resource changes: rules and late responses
  // must never be carried into a different database.
  return <section className="omop-builder" aria-label="OMOP cohort builder">
    <h2>OMOP cohorts</h2>
    <p className="settings-hint">Build a person cohort from clinical events in an OMOP database.</p>
    <label className="omop-resource">OMOP datasource
      <select value={rid} onChange={(e) => setRid(e.target.value)}>
        <option value="">Choose an Aurora database…</option>
        {aurora.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
      </select>
    </label>
    {!aurora.length && <p>No Aurora databases available. Connect a Workbench workspace with an OMOP resource.</p>}
    {rid && <Editor key={rid} rid={rid} onOpen={onOpen} />}
  </section>;
}

function Editor({ rid, onOpen }: { rid: string; onOpen: (r: OpenResult, title: string) => void }) {
  const [info, setInfo] = useState<OmopInfo | null>(null);
  const [rules, setRules] = useState<Rule[]>([]);
  const [domain, setDomain] = useState<OmopDomain>("condition");
  const [q, setQ] = useState("");
  const [standard, setStandard] = useState(true);
  const [results, setResults] = useState<OmopConcept[] | null>(null);
  const [selected, setSelected] = useState<OmopConcept[]>([]);
  const [observed, setObserved] = useState(true);
  const [demo, setDemo] = useState<OmopSpec["demographics"]>({});
  const [count, setCount] = useState<OmopCount | null>(null);
  const [name, setName] = useState("OMOP cohort");
  const [table, setTable] = useState("person");
  const [restrict, setRestrict] = useState(true);
  const [names, setNames] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [prompt, setPrompt] = useState("");
  const [history, setHistory] = useState<{ role: string; content: string }[]>([]);
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
  const changeRules = (next: Rule[]) => {
    // The first included rule defines the index; it cannot be relative to itself.
    const first = next.findIndex((r) => !r.exclude);
    setRules(next.map((r, i) => i === first ? { ...r, index_relation: undefined } : r));
    setCount(null);
  };
  const update = (i: number, patch: Partial<Rule>) => changeRules(rules.map((r, j) => j === i ? { ...r, ...patch } : r));
  const first = rules.findIndex((r) => !r.exclude);
  const refresh = () => run("Detecting OMOP…", async () => {
    const out = await api.omopInfo(rid, true);
    if (mounted.current) { setInfo(out); setCount(null); }
  });

  return <>
    <div className="omop-toolbar">
      {info?.cdm && <span>CDM {info.version ?? "unknown version"} · {info.cdm_schema}</span>}
      <button onClick={refresh} disabled={!!busy}>Refresh detection</button>
      {busy && <span role="status">{busy}</span>}
    </div>
    {error && <p role="alert" className="omop-error">{error}</p>}
    {info && !info.cdm && <p>No OMOP CDM found in this database.</p>}
    {info?.cdm && <fieldset className="omop-fields" disabled={!!busy}>
      <div className="omop-grid">
        <div>
          <section className="omop-card">
            <h3>1. Find concepts</h3>
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
            <p className="settings-hint">Concepts within one rule use OR. Rules use AND. Descendants are included by default.</p>
            <button disabled={domain !== "death" && !selected.length} onClick={() => {
              changeRules([...rules, { domain, concept_ids: selected.map((c) => c.concept_id),
                names: selected.map((c) => c.concept_name), descendants: !!info.vocab_schema, min_count: 1 }]);
              setSelected([]);
            }}>Add criterion{selected.length ? ` (${selected.length} concepts)` : ""}</button>
          </section>
          <section className="omop-card">
            <h3>2. Define cohort</h3>
            <p className="settings-hint">Index date is the first event in the first included criterion. Without one, it is the first observation start. Age uses index year minus birth year.</p>
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
            <label className="omop-check"><input type="checkbox" checked={observed} onChange={(e) => { setObserved(e.target.checked); setCount(null); }} />Require events within an observation period (except death)</label>
            <div className="omop-row">
              <label>Gender<select value={demo.gender_concept_ids?.[0] ?? ""} onChange={(e) => { setDemo({ ...demo, gender_concept_ids: e.target.value ? [Number(e.target.value)] : [] }); setCount(null); }}>
                <option value="">Any</option><option value="8532">Female</option><option value="8507">Male</option></select></label>
              {([['age_min', 'Minimum age'], ['age_max', 'Maximum age'], ['year_of_birth_min', 'Birth year from'], ['year_of_birth_max', 'Birth year to']] as const).map(([key, label]) =>
                <label key={key}>{label}<input type="number" value={demo[key] ?? ""} onChange={(e) => { setDemo({ ...demo, [key]: numeric(e.target.value) }); setCount(null); }} /></label>)}
            </div>
          </section>
        </div>
        <div>
          <section className="omop-card" aria-label="Cohort assistant">
            <h3>Cohort assistant</h3>
            <p className="settings-hint">Describe a cohort, or ask about running Workbench workflows and apps. Select an AI provider in Settings.</p>
            <div className="omop-chat" aria-live="polite">
              {history.map((m, i) => <p key={i}><strong>{m.role === "user" ? "You" : "Assistant"}:</strong> {m.content}</p>)}
            </div>
            <label>Ask the cohort assistant<textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} maxLength={8000} /></label>
            <button disabled={!prompt.trim()} onClick={() => run("Asking cohort assistant…", async () => {
              const message = prompt.trim();
              const out = await api.omopAgent(rid, message, history, spec);
              if (!mounted.current) return;
              setHistory([...history, { role: "user", content: message }, { role: "assistant", content: out.reply }].slice(-30));
              setPrompt(""); setProposal(out.spec ? out : null);
            })}>Ask assistant</button>
            {proposal?.spec && <div className="omop-proposal">
              <p>{proposal.reason || "Proposed cohort"}</p>
              <details><summary>Review proposed criteria</summary><pre>{JSON.stringify(proposal.spec, null, 2)}</pre></details>
              <button onClick={() => {
                const next = proposal.spec!;
                changeRules(next.criteria.map((r) => ({ ...r, names: r.concept_ids.map((id) => proposal.concept_names?.[String(id)] || `Concept ${id}`) })));
                setObserved(next.require_observation); setDemo(next.demographics);
                // Count again after applying so displayed results always match the editor.
                setCount(null); setProposal(null);
              }}>Apply proposed cohort</button>
            </div>}
          </section>
          <section className="omop-card">
            <h3>3. Count and explore</h3>
            <button className="primary" onClick={() => run("Counting cohort…", async () => {
              const out = await api.omopCount(rid, spec); if (mounted.current) setCount(out);
            })}>Count cohort</button>
            {count && <div aria-label="Cohort count">
              <p className="omop-count">{count.persons.toLocaleString()} <span>of {count.total_persons.toLocaleString()} persons</span></p>
              <table className="omop-attrition"><thead><tr><th>Step</th><th>Persons</th></tr></thead><tbody>
                {[{ label: "All persons", persons: count.total_persons }, ...count.attrition].map((step, i) =>
                  <tr key={i}><td>{step.label}</td><td>{step.persons.toLocaleString()}</td></tr>)}
              </tbody></table>
            </div>}
            <label>Cohort name<input type="text" value={name} onChange={(e) => setName(e.target.value)} /></label>
            <button disabled={!count || !name.trim()} onClick={() => run("Opening cohort…", async () => {
              const out = await api.omopOpen(rid, spec, name.trim()); if (mounted.current) onOpen(out, name.trim());
            })}>Open cohort</button>
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
            <button disabled={restrict && !count} onClick={() => run("Opening clinical table…", async () => {
              const out = await api.omopDomain(rid, table, restrict ? spec : null, names);
              if (mounted.current) onOpen(out, table);
            })}>Open clinical table</button>
          </section>
        </div>
      </div>
    </fieldset>}
  </>;
}
