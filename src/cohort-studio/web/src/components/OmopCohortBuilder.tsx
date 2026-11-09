import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { OmopCompatibility, OmopConcept, OmopCount, OmopCriterion, OmopDomain, OmopInfo, OmopSpec, SourceRef } from "../types";
import "./OmopCohortBuilder.css";

const DOMAINS: { value: OmopDomain; label: string }[] = [
  { value: "condition", label: "Condition" }, { value: "drug", label: "Drug" },
  { value: "procedure", label: "Procedure" }, { value: "measurement", label: "Measurement" },
  { value: "observation", label: "Observation" }, { value: "visit", label: "Visit" },
  { value: "device", label: "Device" }, { value: "death", label: "Death" },
];
type Rule = { criterion: OmopCriterion; concepts: OmopConcept[] };
const number = (value: string) => value === "" ? undefined : Number(value);
const validNumber = (value: string) => value === "" || Number.isFinite(Number(value));
const validInteger = (value: string) => value === "" || Number.isInteger(Number(value));

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
  const [editing, setEditing] = useState<number | null>(null);
  const [exclude, setExclude] = useState(false);
  const [descendants, setDescendants] = useState(true);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [minCount, setMinCount] = useState("1");
  const [standardOnly, setStandardOnly] = useState(true);
  const [valueMin, setValueMin] = useState("");
  const [valueMax, setValueMax] = useState("");
  const [timing, setTiming] = useState<"" | "before" | "after">("");
  const [observation, setObservation] = useState(true);
  const [gender, setGender] = useState("");
  const [ageMin, setAgeMin] = useState("");
  const [ageMax, setAgeMax] = useState("");
  const [birthMin, setBirthMin] = useState("");
  const [birthMax, setBirthMax] = useState("");
  const [count, setCount] = useState<OmopCount | null>(null);
  const [counting, setCounting] = useState(false);
  const [countError, setCountError] = useState("");
  const countRequest = useRef(0);
  const countQueue = useRef<Promise<unknown>>(Promise.resolve());
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [compatibility, setCompatibility] = useState<OmopCompatibility | null>(null);
  const [compatError, setCompatError] = useState("");
  const [reviewedMapping, setReviewedMapping] = useState(false);

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

  const firstIncluded = rules.findIndex((rule) => !rule.criterion.exclude);
  const nextFirst = editing === null ? firstIncluded : rules.findIndex((rule, index) => index === editing ? !exclude : !rule.criterion.exclude);
  const canUseTiming = editing === null ? firstIncluded >= 0 : nextFirst >= 0 && nextFirst !== editing;
  const indexConflict = editing !== null && nextFirst !== firstIncluded
    && (Boolean(timing) || rules.some((rule, index) => index !== editing && Boolean(rule.criterion.index_relation)));
  const demographicError = ![ageMin, ageMax].every(validNumber) || ![birthMin, birthMax].every(validInteger)
    || Boolean(ageMin && ageMax && Number(ageMin) > Number(ageMax))
    || Boolean(birthMin && birthMax && Number(birthMin) > Number(birthMax));
  const ruleError = Boolean(start && end && start > end) || !Number.isInteger(Number(minCount)) || Number(minCount) < 1
    || (domain === "measurement" && (![valueMin, valueMax].every(validNumber)
      || Boolean(valueMin && valueMax && Number(valueMin) > Number(valueMax))));
  const spec: OmopSpec = { criteria: rules.map((rule) => rule.criterion), demographics: {
    ...(gender ? { gender_concept_ids: [Number(gender)] } : {}),
    ...(ageMin ? { age_min: number(ageMin) } : {}), ...(ageMax ? { age_max: number(ageMax) } : {}),
    ...(birthMin ? { year_of_birth_min: number(birthMin) } : {}), ...(birthMax ? { year_of_birth_max: number(birthMax) } : {}),
  }, require_observation: observation };
  const previewing = selected.length > 0 || editing !== null;
  const canPreview = !previewing || (!ruleError && !indexConflict && (editing !== null || rules.length < 12)
    && (domain === "death" || selected.length > 0));
  const draftCriterion: OmopCriterion = { domain, concept_ids: selected.map((c) => c.concept_id),
    descendants: domain === "death" ? false : descendants, exclude, min_count: Number(minCount),
    ...(start ? { start } : {}), ...(end ? { end } : {}), ...(timing && canUseTiming ? { index_relation: timing } : {}),
    ...(domain === "measurement" && valueMin ? { value_min: number(valueMin) } : {}),
    ...(domain === "measurement" && valueMax ? { value_max: number(valueMax) } : {}) };
  const countSpec: OmopSpec = previewing && canPreview ? { ...spec, criteria: editing === null
    ? [...spec.criteria, draftCriterion] : spec.criteria.map((criterion, index) => index === editing ? draftCriterion : criterion) } : spec;
  const specKey = JSON.stringify(countSpec);
  const aliases = Object.entries(info?.table_mapping ?? {});
  const needsReview = aliases.length > 0 && !reviewedMapping;
  useEffect(() => {
    if (!schema) return;
    let current = true;
    setReviewedMapping(false);
    api.omopInfo(resourceId, schema).then((result) => { if (current) setInfo(result); })
      .catch((e) => { if (current) setError((e as Error).message); });
    return () => { current = false; };
  }, [resourceId, schema]);
  useEffect(() => {
    if (!schema || demographicError || !canPreview) { setCompatibility(null); return; }
    let current = true;
    setCompatibility(null); setCompatError("");
    const timer = window.setTimeout(() => {
      api.omopCompatibility(resourceId, schema, JSON.parse(specKey) as OmopSpec)
        .then((result) => { if (current) setCompatibility(result); })
        .catch((e) => { if (current) setCompatError((e as Error).message); });
    }, 200);
    return () => { current = false; window.clearTimeout(timer); };
  }, [resourceId, schema, specKey, demographicError, canPreview]);
  const incompatible = !compatibility || !compatibility.meets_threshold || compatibility.matched !== compatibility.total;
  useEffect(() => {
    const requestId = ++countRequest.current;
    setCount(null); setCountError(""); setCounting(false);
    if (!schema || incompatible || needsReview || demographicError || !canPreview) return;
    const timer = window.setTimeout(() => {
      if (countRequest.current !== requestId) return;
      setCounting(true);
      const pending = countQueue.current.then(async () => {
        if (countRequest.current !== requestId) return;
        try {
          const result = await api.omopCount(resourceId, schema, JSON.parse(specKey) as OmopSpec);
          if (countRequest.current === requestId) setCount(result);
        } catch (e) {
          if (countRequest.current === requestId) setCountError((e as Error).message);
        } finally {
          if (countRequest.current === requestId) setCounting(false);
        }
      });
      countQueue.current = pending;
    }, 700);
    return () => { window.clearTimeout(timer); };
  }, [resourceId, schema, specKey, incompatible, needsReview, demographicError, canPreview, previewing]);
  useEffect(() => () => { countRequest.current++; }, []);
  const search = async () => {
    if (!schema || !query.trim() || needsReview) return;
    setBusy("Searching…"); setError(""); setSearched(false);
    try { setResults((await api.omopConcepts(resourceId, schema, query.trim(), domain, standardOnly)).concepts); setSearched(true); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(""); }
  };
  const addRule = () => {
    if (domain !== "death" && !selected.length) return;
    const rule: Rule = {
      criterion: draftCriterion,
      concepts: selected,
    };
    setRules((previous) => editing === null ? [...previous, rule] : previous.map((item, i) => i === editing ? rule : item));
    setEditing(null);
    setSelected([]); setResults([]); setQuery(""); setSearched(false);
    setStart(""); setEnd(""); setMinCount("1"); setValueMin(""); setValueMax(""); setTiming("");
  };
  const editRule = (index: number) => {
    const rule = rules[index];
    const c = rule.criterion;
    setEditing(index); setDomain(c.domain); setExclude(Boolean(c.exclude));
    setDescendants(c.descendants ?? true); setSelected(rule.concepts);
    setStart(c.start ?? ""); setEnd(c.end ?? ""); setMinCount(String(c.min_count ?? 1));
    setValueMin(c.value_min === undefined ? "" : String(c.value_min));
    setValueMax(c.value_max === undefined ? "" : String(c.value_max));
    setTiming(c.index_relation ?? ""); setResults([]); setQuery(""); setSearched(false);
  };
  const cancelEdit = () => {
    setEditing(null); setSelected([]); setResults([]); setQuery(""); setSearched(false);
    setStart(""); setEnd(""); setMinCount("1"); setValueMin(""); setValueMax(""); setTiming("");
  };
  const countCohort = async () => {
    const requestId = ++countRequest.current;
    setBusy("Counting…"); setError("");
    setCount(null); setCountError(""); setCounting(true);
    const pending = countQueue.current.then(() => api.omopCount(resourceId, schema, spec));
    countQueue.current = pending.catch(() => undefined);
    try { const result = await pending; if (countRequest.current === requestId) setCount(result); }
    catch (e) { if (countRequest.current === requestId) setCountError((e as Error).message); }
    finally { if (countRequest.current === requestId) setCounting(false); setBusy(""); }
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
            setSchema(e.target.value); setRules([]); cancelEdit();
          }}>
            {(info.cdm_schemas ?? []).map((s) => <option key={s.cdm_schema} value={s.cdm_schema}>{s.cdm_schema}</option>)}
          </select></label>
        </div>
        {aliases.length > 0 && <div><strong>Review matched table names</strong>
          <ul>{aliases.map(([standard, actual]) => <li key={standard}>{standard} → {actual}</li>)}</ul>
          <label className="omop-check"><input type="checkbox" checked={reviewedMapping} onChange={(e) => setReviewedMapping(e.target.checked)} /> I verified these tables contain the corresponding OMOP data</label>
        </div>}
        {Boolean(Object.keys(info.ambiguous_tables ?? {}).length) && <div>Multiple possible table matches were not selected:
          <ul>{Object.entries(info.ambiguous_tables ?? {}).map(([name, candidates]) => <li key={name}>{name}: {candidates.join(", ")}</li>)}</ul>
        </div>}
        {compatibility && <div role="status">Selected features: {compatibility.matched} of {compatibility.total} required tables match ({compatibility.percent}%).
          {compatibility.missing_tables.length > 0 && <p>Missing tables: {compatibility.missing_tables.join(", ")}.</p>}
          {Object.entries(compatibility.missing_columns).map(([table, columns]) => <p key={table}>Missing columns in {table}: {columns.join(", ")}.</p>)}
        </div>}
        {compatError && <p role="alert">Could not check OMOP compatibility: {compatError}</p>}
        <div className="omop-layout">
        <section className="omop-criteria" aria-label="Concept criteria">
        <h4>Find concepts</h4>
        <div className="omop-fields">
          <label>Domain<select aria-label="Domain" value={domain} onChange={(e) => { setDomain(e.target.value as OmopDomain); setSelected([]); setResults([]); setQuery(""); setSearched(false); setValueMin(""); setValueMax(""); }}>
            {DOMAINS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
          </select></label>
          <label>Match<select aria-label="Match" value={exclude ? "exclude" : "include"} onChange={(e) => setExclude(e.target.value === "exclude")}>
            <option value="include">Include people with</option><option value="exclude">Exclude people with</option>
          </select></label>
        </div>
        {domain !== "death" && <>
          <div className="omop-search"><label>Search concepts<input type="search" placeholder="Search by concept name, ID, or code" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void search(); } }} /></label>
            <button type="button" className="primary" disabled={!query.trim() || needsReview} onClick={() => void search()}>Search</button></div>
          <label className="omop-check"><input type="checkbox" checked={standardOnly} onChange={(e) => { setStandardOnly(e.target.checked); setResults([]); setSearched(false); }} /> Standard concepts only</label>
          {!standardOnly && <p>Nonstandard concepts may not be present in the domain's concept ID field.</p>}
          {results.length > 0 && <div className="omop-results" role="group" aria-label="Concept search results">{results.map((concept) => <label key={concept.concept_id} className="omop-result">
            <input type="checkbox" checked={selected.some((c) => c.concept_id === concept.concept_id)} onChange={(e) => setSelected((items) => e.target.checked ? [...items, concept] : items.filter((c) => c.concept_id !== concept.concept_id))} />
            <span><strong>{concept.concept_name}</strong><small>{concept.concept_id} · {concept.vocabulary_id}{concept.standard_concept !== "S" ? " · nonstandard" : ""}</small></span></label>)}</div>}
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
          <label>Timing relative to index<select value={canUseTiming ? timing : ""} disabled={!canUseTiming} onChange={(e) => setTiming(e.target.value as "" | "before" | "after")}>
            <option value="">Any time</option><option value="before">Before index</option><option value="after">After index</option>
          </select></label>
          {domain === "measurement" && <><label>Minimum value<input type="number" step="any" value={valueMin} onChange={(e) => setValueMin(e.target.value)} /></label>
            <label>Maximum value<input type="number" step="any" value={valueMax} onChange={(e) => setValueMax(e.target.value)} /></label></>}
        </div><p>The index date is the first event of the first included criterion, or the first observation start if there is no included criterion. Before and after are exclusive.</p></details>
        {ruleError && <p role="alert">Check the event dates, counts and measurement values.</p>}
        {indexConflict && <p role="alert">Remove time-relative criteria before changing the index event.</p>}
        {(selected.length > 0 || editing !== null) && <p>{editing === null ? "Add the selected concepts as a criterion before continuing." : "Update or cancel the criterion before continuing."}</p>}
        <h4>Cohort criteria</h4>
        {rules.length > 0 && <p>All criteria must match. Concepts within one criterion match any selected concept.</p>}
        {rules.length > 0 && <ul className="omop-rules">{rules.map((rule, index) => <li key={index}>
          <span>{rule.criterion.exclude ? "Exclude" : "Include"} {rule.criterion.domain}: {rule.concepts.map((c) => `${c.concept_name} (${c.concept_id})`).join(", ") || "any"}{rule.criterion.descendants ? " · descendants" : ""}
            {rule.criterion.min_count && rule.criterion.min_count > 1 ? ` · at least ${rule.criterion.min_count} events` : ""}
            {rule.criterion.start ? ` · from ${rule.criterion.start}` : ""}{rule.criterion.end ? ` · through ${rule.criterion.end}` : ""}
            {rule.criterion.value_min !== undefined ? ` · value ≥ ${rule.criterion.value_min}` : ""}{rule.criterion.value_max !== undefined ? ` · value ≤ ${rule.criterion.value_max}` : ""}
            {rule.criterion.index_relation ? ` · ${rule.criterion.index_relation} index` : ""}{index === firstIncluded ? " · index event" : ""}</span>
          <span className="omop-rule-actions"><button type="button" className="quiet" disabled={editing !== null} onClick={() => editRule(index)} aria-label={`Edit criterion ${index + 1}`}>Edit</button>
          <button type="button" className="quiet" aria-label={`Remove criterion ${index + 1}`}
            disabled={editing !== null || index === firstIncluded && rules.some((item) => Boolean(item.criterion.index_relation))}
            title={index === firstIncluded && rules.some((item) => Boolean(item.criterion.index_relation)) ? "Remove time-relative criteria first." : undefined}
            onClick={() => { if (index === firstIncluded) setTiming(""); setRules((items) => items.filter((_, i) => i !== index)); }}>✕</button></span>
        </li>)}</ul>}
        {rules.some((item) => Boolean(item.criterion.index_relation)) && <p>Remove time-relative criteria before removing the index event.</p>}
        </section>
        <aside className="omop-demographics" aria-label="Demographics and observation">
        <h4>Demographics</h4>
        <div className="omop-fields">
          <label>Gender (OMOP)<select value={gender} onChange={(e) => setGender(e.target.value)}>
            <option value="">Any</option><option value="8532">Female</option><option value="8507">Male</option>
          </select></label>
          <label>Minimum age at index<input type="number" value={ageMin} onChange={(e) => setAgeMin(e.target.value)} /></label>
          <label>Maximum age at index<input type="number" value={ageMax} onChange={(e) => setAgeMax(e.target.value)} /></label>
          <label>Birth year from<input type="number" step="1" value={birthMin} onChange={(e) => setBirthMin(e.target.value)} /></label>
          <label>Birth year through<input type="number" step="1" value={birthMax} onChange={(e) => setBirthMax(e.target.value)} /></label>
        </div>
        <p className="omop-demographic-hint">Age is index year minus birth year; people without an index date cannot match an age filter.</p>
        <label className="omop-check"><input type="checkbox" checked={observation} onChange={(e) => setObservation(e.target.checked)} /> Require an observation period</label>
        {demographicError && <p role="alert">Check the age and birth-year ranges.</p>}
        </aside>
        </div>
        <div className="omop-actions"><div className="omop-count" role="status" aria-live="polite">
          {!canPreview ? "Check the criterion to see the count."
            : counting ? "Counting people…"
            : countError ? `Count unavailable: ${countError}`
            : count ? <>{previewing && "Preview: "}<strong>{count.persons.toLocaleString()} people</strong> of {count.total_persons.toLocaleString()}
              {count.attrition.length > 0 && <details><summary>Show cohort steps</summary><ol>{count.attrition.map((step, i) => <li key={i}>{step.label}: {step.persons.toLocaleString()}</li>)}</ol></details>}</>
            : ""}
        </div>{editing !== null && <button type="button" onClick={cancelEdit}>Cancel edit</button>}
          <button type="button" disabled={domain !== "death" && !selected.length || editing === null && rules.length >= 12 || ruleError || indexConflict} onClick={addRule}>{editing === null ? "Add criterion" : "Update criterion"}</button>
          <button type="button" disabled={!schema || selected.length > 0 || editing !== null || demographicError || incompatible || needsReview} onClick={() => void countCohort()}>Count people</button>
          <button type="button" className="primary" disabled={!schema || selected.length > 0 || editing !== null || demographicError || incompatible || needsReview} onClick={() => void add()}>Add to Data Builder</button></div>
      </fieldset>}
    </section>
  </div>;
}
