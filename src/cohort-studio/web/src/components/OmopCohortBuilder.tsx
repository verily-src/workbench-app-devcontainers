import { useEffect, useState } from "react";
import { api } from "../api";
import type { OmopConcept, OmopCount, OmopCriterion, OmopDomain, OmopInfo, OmopSpec, SourceRef } from "../types";
import "./OmopCohortBuilder.css";

const DOMAINS: { value: OmopDomain; label: string }[] = [
  { value: "condition", label: "Condition" }, { value: "drug", label: "Drug" },
  { value: "procedure", label: "Procedure" }, { value: "measurement", label: "Measurement" },
  { value: "observation", label: "Observation" }, { value: "visit", label: "Visit" },
  { value: "device", label: "Device" }, { value: "death", label: "Death" },
];
type Rule = { criterion: OmopCriterion; labels: string[] };

export function OmopCohortBuilder({ resourceId, onAdd, onClose }: {
  resourceId: string; onAdd: (ref: Extract<SourceRef, { kind: "omop_cohort" }>) => Promise<void>; onClose: () => void;
}) {
  const [info, setInfo] = useState<OmopInfo | null>(null);
  const [schema, setSchema] = useState("");
  const [name, setName] = useState("OMOP cohort");
  const [domain, setDomain] = useState<OmopDomain>("condition");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<OmopConcept[]>([]);
  const [searched, setSearched] = useState(false);
  const [selected, setSelected] = useState<OmopConcept[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [exclude, setExclude] = useState(false);
  const [descendants, setDescendants] = useState(true);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [minCount, setMinCount] = useState("1");
  const [observation, setObservation] = useState(true);
  const [count, setCount] = useState<OmopCount | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    setBusy("Loading OMOP schemas…"); setError("");
    api.omopInfo(resourceId).then((result) => {
      if (!current) return;
      setInfo(result);
      setSchema(result.cdm_schema ?? "");
    }).catch((e) => { if (current) setError((e as Error).message); })
      .finally(() => { if (current) setBusy(""); });
    return () => { current = false; };
  }, [resourceId]);

  const spec: OmopSpec = { criteria: rules.map((rule) => rule.criterion), demographics: {}, require_observation: observation };
  useEffect(() => { setCount(null); }, [rules, observation, schema]);
  const search = async () => {
    if (!schema || !query.trim()) return;
    setBusy("Searching…"); setError(""); setSearched(false);
    try { setResults((await api.omopConcepts(resourceId, schema, query.trim(), domain)).concepts); setSearched(true); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(""); }
  };
  const addRule = () => {
    if (domain !== "death" && !selected.length) return;
    setRules((previous) => [...previous, {
      criterion: { domain, concept_ids: selected.map((c) => c.concept_id), descendants: domain === "death" ? false : descendants, exclude,
        min_count: Number(minCount), ...(start ? { start } : {}), ...(end ? { end } : {}) },
      labels: selected.map((c) => `${c.concept_name} (${c.concept_id})`),
    }]);
    setSelected([]); setResults([]); setQuery(""); setSearched(false);
    setStart(""); setEnd(""); setMinCount("1");
  };
  const countCohort = async () => {
    setBusy("Counting…"); setError("");
    try { setCount(await api.omopCount(resourceId, schema, spec)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(""); }
  };
  const add = async () => {
    setBusy("Opening cohort…"); setError("");
    try {
      await onAdd({ kind: "omop_cohort", resource_id: resourceId, cdm_schema: schema,
                    spec, membership_mode: "live", name: name.trim() || "OMOP cohort" });
      onClose();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(""); }
  };

  return <div className="jc-dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
    <section className="jc-dialog wide omop-builder" role="dialog" aria-modal="true" aria-label="Build OMOP cohort"
             onKeyDown={(e) => { if (e.key === "Escape" && !busy) onClose(); }}>
      <div className="jc-bottom-head"><h3>Build OMOP cohort</h3><span className="jc-spacer" />
        <button type="button" className="quiet" aria-label="Close OMOP cohort" disabled={Boolean(busy)} onClick={onClose}>✕</button></div>
      {error && <p role="alert" className="join-error">{error}</p>}
      {busy && <p role="status">{busy}</p>}
      {info && !info.cdm && <p>No OMOP CDM was found in this datasource.</p>}
      {info?.cdm && <fieldset disabled={Boolean(busy)}>
        <div className="omop-fields">
          <label>Cohort name<input value={name} maxLength={128} onChange={(e) => setName(e.target.value)} /></label>
          <label>CDM schema<select value={schema} onChange={(e) => {
            if ((rules.length > 0 || selected.length > 0) && !window.confirm("Changing the schema clears the selected criteria. Continue?")) return;
            setSchema(e.target.value); setRules([]); setSelected([]); setResults([]); setSearched(false);
          }}>
            {(info.cdm_schemas ?? []).map((s) => <option key={s.cdm_schema} value={s.cdm_schema}>{s.cdm_schema}</option>)}
          </select></label>
        </div>
        <label className="omop-check"><input type="checkbox" checked={observation} onChange={(e) => setObservation(e.target.checked)} /> Require an observation period</label>
        {count && <div role="status" className="omop-count"><strong>{count.persons.toLocaleString()} people</strong> of {count.total_persons.toLocaleString()}
          {count.attrition.length > 0 && <details><summary>Show cohort steps</summary><ol>{count.attrition.map((step, i) => <li key={i}>{step.label}: {step.persons.toLocaleString()}</li>)}</ol></details>}</div>}
        <h4>Criteria</h4>
        <p>All criteria must match. Concepts within one criterion match any selected concept.</p>
        {rules.length === 0 && <p>Without criteria, the cohort includes everyone in the selected population.</p>}
        {rules.length > 0 && <ul className="omop-rules">{rules.map((rule, index) => <li key={index}>
          <span>{rule.criterion.exclude ? "Exclude" : "Include"} {rule.criterion.domain}: {rule.labels.join(", ") || "any"}{rule.criterion.descendants ? " · descendants" : ""}
            {rule.criterion.min_count && rule.criterion.min_count > 1 ? ` · at least ${rule.criterion.min_count} events` : ""}
            {rule.criterion.start ? ` · from ${rule.criterion.start}` : ""}{rule.criterion.end ? ` · through ${rule.criterion.end}` : ""}</span>
          <button type="button" className="quiet" aria-label={`Remove criterion ${index + 1}`} onClick={() => setRules((items) => items.filter((_, i) => i !== index))}>✕</button>
        </li>)}</ul>}
        <div className="omop-fields">
          <label>Domain<select value={domain} onChange={(e) => { setDomain(e.target.value as OmopDomain); setSelected([]); setResults([]); setQuery(""); setSearched(false); }}>
            {DOMAINS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
          </select></label>
          <label>Match<select aria-label="Match" value={exclude ? "exclude" : "include"} onChange={(e) => setExclude(e.target.value === "exclude")}>
            <option value="include">Include people with</option><option value="exclude">Exclude people with</option>
          </select></label>
        </div>
        {domain !== "death" && <>
          <div className="omop-search"><label>Search concepts<input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void search(); } }} /></label>
            <button type="button" disabled={!query.trim()} onClick={() => void search()}>Search</button></div>
          {results.length > 0 && <div className="omop-results" role="group" aria-label="Concept search results">{results.map((concept) => <label key={concept.concept_id} className="omop-check">
            <input type="checkbox" checked={selected.some((c) => c.concept_id === concept.concept_id)} onChange={(e) => setSelected((items) => e.target.checked ? [...items, concept] : items.filter((c) => c.concept_id !== concept.concept_id))} />
            {concept.concept_name} · {concept.concept_id} · {concept.vocabulary_id}</label>)}</div>}
          {searched && results.length === 0 && <p role="status">No concepts found.</p>}
          {selected.length > 0 && <div aria-label="Selected concepts"><strong>Selected concepts</strong><ul className="omop-rules">{selected.map((concept) => <li key={concept.concept_id}>
            <span>{concept.concept_name} · {concept.concept_id}</span><button type="button" className="quiet" aria-label={`Remove concept ${concept.concept_id}`} onClick={() => setSelected((items) => items.filter((item) => item.concept_id !== concept.concept_id))}>✕</button>
          </li>)}</ul></div>}
          <label className="omop-check"><input type="checkbox" checked={descendants} onChange={(e) => setDescendants(e.target.checked)} /> Include descendant concepts</label>
        </>}
        <details><summary>Event limits</summary><div className="omop-fields">
          <label>From<input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></label>
          <label>Through<input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></label>
          <label>Minimum events<input type="number" min="1" step="1" value={minCount} onChange={(e) => setMinCount(e.target.value)} /></label>
        </div></details>
        {(start && end && start > end || !Number.isInteger(Number(minCount)) || Number(minCount) < 1) && <p role="alert">Check the date range and minimum events.</p>}
        <button type="button" disabled={domain !== "death" && !selected.length || rules.length >= 12 || Boolean(start && end && start > end) || !Number.isInteger(Number(minCount)) || Number(minCount) < 1} onClick={addRule}>Add criterion</button>
        {selected.length > 0 && <p>Add the selected concepts as a criterion before continuing.</p>}
        <div className="omop-actions"><button type="button" disabled={!schema || selected.length > 0} onClick={() => void countCohort()}>Count people</button>
          <button type="button" className="primary" disabled={!schema || selected.length > 0} onClick={() => void add()}>Add to Data Builder</button></div>
      </fieldset>}
    </section>
  </div>;
}
