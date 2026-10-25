import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type {
  Dataset, JoinCondition, JoinEngine, JoinHow, JoinOp, JoinPreview, JoinStep,
  JoinRecommendation, JoinSuggestion, JoinValidation, Source, SourceRef, TableInfo,
} from "../types";
import { Combobox } from "./Combobox";

interface Props {
  datasets: Dataset[];
  sources: Source[];
  busy: boolean;
  onJoin: (p: { baseId: string; steps: JoinStep[]; allowLoaded?: boolean }) => void;
  initialPlan?: { title: string; baseId: string; steps: JoinStep[]; allowLoaded: boolean };
  onSourceOpened: (opened: Awaited<ReturnType<typeof api.openSourceRef>>,
                   title: string, sourceRef: SourceRef) => void;
  onClose: () => void;
}

const HOWS: { id: JoinHow; label: string; hint: string }[] = [
  { id: "left", label: "Left", hint: "Keep every row on the left; add matches" },
  { id: "inner", label: "Inner", hint: "Only rows that match on both sides" },
  { id: "right", label: "Right", hint: "Keep every row of the joined table" },
  { id: "full", label: "Full", hint: "Keep every row from both sides" },
  { id: "semi", label: "Has match", hint: "Left rows with a match; adds no columns" },
  { id: "anti", label: "No match", hint: "Left rows without a match; adds no columns" },
];
const OPS: JoinOp[] = ["=", "!=", "<", "<=", ">", ">="];
const ARROW = " → ";
const MAX_STEPS = 6;
const VALIDATE_DELAY_MS = 300;
const ENGINE_LABEL: Record<JoinEngine, string> = {
  aurora: "runs in Aurora", duckdb: "runs in memory",
};

interface StepState extends JoinStep { touched: boolean; pickCols: boolean }
type KeyRecommendation = JoinRecommendation & { sourceTitle: string };

const aliasOf = (d?: Dataset) =>
  (d?.title ?? "joined").replace(/\.(parquet|csv|tsv|txt|json|ndjson)$/i, "");

const addsColumns = (how: JoinHow) => how !== "semi" && how !== "anti";

function Venn({ how }: { how: JoinHow }) {
  const a = { cx: 7, cy: 7, r: 5.5 }, b = { cx: 14, cy: 7, r: 5.5 };
  const id = `venn-${how}`;
  return (
    <svg className="venn" width="21" height="14" viewBox="0 0 21 14" aria-hidden>
      <defs>
        <clipPath id={`${id}-a`}><circle {...a} /></clipPath>
        <mask id={`${id}-not-b`}>
          <rect width="21" height="14" fill="white" /><circle {...b} fill="black" />
        </mask>
      </defs>
      {(how === "left" || how === "full") && <circle {...a} className="venn-fill" />}
      {(how === "right" || how === "full") && <circle {...b} className="venn-fill" />}
      {(how === "inner" || how === "semi") &&
        <circle {...b} className="venn-fill" clipPath={`url(#${id}-a)`} />}
      {how === "anti" && <circle {...a} className="venn-fill" mask={`url(#${id}-not-b)`} />}
      <circle {...a} className="venn-line" />
      <circle {...b} className={`venn-line${addsColumns(how) ? "" : " venn-dashed"}`} />
    </svg>
  );
}

function outputColumns(base: Dataset | undefined, steps: StepState[],
                       upTo: number, byId: Map<string, Dataset>): string[] {
  const cols = base ? base.columns.map((c) => c.name) : [];
  steps.slice(0, upTo).forEach((s) => {
    const right = byId.get(s.right_id);
    if (!right || !addsColumns(s.how)) return;
    const picked = s.columns ?? right.columns.map((c) => c.name);
    picked.forEach((c) => cols.push(`${s.alias}${ARROW}${c}`));
  });
  return cols;
}

function defaultCondition(leftCols: string[], right?: Dataset): JoinCondition {
  void leftCols;
  void right;
  return { left: "", op: "=", right: "" };
}

const directAurora = (ref?: SourceRef) => ref?.kind === "aurora" && "table" in ref;

function sourceResources(ref?: SourceRef): string[] {
  if (!ref) return [];
  if (ref.kind === "join") return [
    ...sourceResources(ref.base), ...ref.steps.flatMap((step) => sourceResources(step.source)),
  ];
  if (ref.kind === "derived") return sourceResources(ref.base);
  return [ref.resource_id];
}

export function JoinPanel({ datasets, sources, busy, onJoin, initialPlan,
                            onSourceOpened, onClose }: Props) {
  const byId = useMemo(() => new Map(datasets.map((d) => [d.id, d])), [datasets]);
  const [baseId, setBaseId] = useState(initialPlan?.baseId ?? datasets[0]?.id ?? "");
  const base = byId.get(baseId);
  const [resourceKey, setResourceKey] = useState("");
  const [sourceTables, setSourceTables] = useState<TableInfo[]>([]);
  const [sourceSchema, setSourceSchema] = useState("");
  const [sourceTable, setSourceTable] = useState("");
  const [sourceBusy, setSourceBusy] = useState(false);
  const [sourceError, setSourceError] = useState("");
  const [sourceMode, setSourceMode] = useState<"table" | "sql">("table");
  const [sqlName, setSqlName] = useState("");
  const [sqlText, setSqlText] = useState("");
  const [sqlPreview, setSqlPreview] = useState<Awaited<ReturnType<typeof api.previewSql>> | null>(null);
  const [sqlPreviewInput, setSqlPreviewInput] = useState("");
  const [sqlPreviewResourceId, setSqlPreviewResourceId] = useState("");
  const [sqlBusy, setSqlBusy] = useState(false);
  const [sqlError, setSqlError] = useState("");
  const sqlRequest = useRef(0);
  const selectedSource = sources.find((source) =>
    `${source.kind}:${source.id}` === resourceKey);

  const invalidateSqlPreview = () => {
    sqlRequest.current += 1;
    setSqlBusy(false);
    setSqlPreview(null);
    setSqlPreviewInput("");
    setSqlPreviewResourceId("");
    setSqlError("");
  };

  useEffect(() => {
    if (!resourceKey && sources.length) {
      const first = sources[0];
      setResourceKey(`${first.kind}:${first.id}`);
    }
  }, [resourceKey, sources]);

  useEffect(() => {
    if (!selectedSource) { setSourceTables([]); setSourceTable(""); return; }
    let cancelled = false;
    setSourceTables([]);
    setSourceSchema("");
    setSourceTable("");
    setSourceError("");
    api.tables(selectedSource.kind, selectedSource.id).then((items) => {
      if (!cancelled) setSourceTables(items);
    }).catch((error) => {
      if (!cancelled) setSourceError((error as Error).message);
    });
    return () => { cancelled = true; };
  }, [resourceKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const attachOpenedSource = (opened: Awaited<ReturnType<typeof api.openSourceRef>>,
                              title: string, sourceRef: SourceRef) => {
    onSourceOpened(opened, title, sourceRef);
    if (!baseId) {
      setBaseId(opened.dataset_id);
      setSteps([{ right_id: "", how: "left", alias: "joined", columns: null,
        touched: false, pickCols: false,
        conditions: [{ left: "", op: "=", right: "" }] }]);
    } else {
      setSteps((previous) => {
        const add = (): StepState => ({
          right_id: opened.dataset_id, how: "left", alias: title,
          columns: null, touched: false, pickCols: false,
          conditions: [{ left: "", op: "=", right: "" }],
        });
        const emptyIndex = previous.findIndex((step) => !step.right_id);
        if (emptyIndex >= 0) return previous.map((step, i) =>
          i === emptyIndex ? add() : step);
        if (previous.length < MAX_STEPS) return [...previous, add()];
        return previous;
      });
    }
  };

  const addSourceTable = async () => {
    if (!selectedSource) return;
    if (baseId && steps.every((step) => step.right_id) && steps.length >= MAX_STEPS) {
      setSourceError(`A join can include up to ${MAX_STEPS} additional tables.`);
      return;
    }
    const info = sourceTables.find((item) => item.name === sourceTable);
    if (!info) return;
    const sourceRef: SourceRef = {
      kind: selectedSource.kind, resource_id: selectedSource.id,
      ...(selectedSource.uuid ? { uuid: selectedSource.uuid } : {}),
      ...(info.schema ? { schema: info.schema } : {}),
      table: info.table ?? info.name,
    };
    setSourceBusy(true);
    setSourceError("");
    try {
      const opened = await api.openSourceRef(sourceRef);
      const duplicateCount = datasets.filter((dataset) => {
        const ref = dataset.sourceRef;
        return ref && "table" in ref && ref.kind === sourceRef.kind
          && ref.resource_id === sourceRef.resource_id
          && ref.schema === sourceRef.schema && ref.table === sourceRef.table;
      }).length;
      const title = duplicateCount ? `${info.name} (${duplicateCount + 1})` : info.name;
      attachOpenedSource(opened, title, sourceRef);
      setSourceTable("");
    } catch (error) {
      setSourceError((error as Error).message);
    } finally {
      setSourceBusy(false);
    }
  };

  const previewSql = async () => {
    if (selectedSource?.kind !== "aurora") return;
    const requestId = ++sqlRequest.current;
    const resourceId = selectedSource.id;
    const query = sqlText.trim();
    setSqlBusy(true);
    setSqlError("");
    setSqlPreview(null);
    try {
      const result = await api.previewSql(resourceId, query);
      if (requestId === sqlRequest.current) {
        setSqlPreview(result);
        setSqlPreviewInput(query);
        setSqlPreviewResourceId(resourceId);
      }
    } catch (error) {
      if (requestId === sqlRequest.current) setSqlError((error as Error).message);
    } finally {
      if (requestId === sqlRequest.current) setSqlBusy(false);
    }
  };

  const addSqlSource = async () => {
    const preview = sqlPreview;
    if (!preview || sqlPreviewResourceId !== selectedSource?.id
        || sqlPreviewInput !== sqlText.trim()) return;
    setSourceBusy(true);
    setSqlError("");
    try {
      const requestedName = sqlName.trim() || "SQL result";
      const duplicateCount = datasets.filter((dataset) => dataset.title === requestedName).length;
      const title = duplicateCount ? `${requestedName} (${duplicateCount + 1})` : requestedName;
      const sourceRef: SourceRef = { ...preview.source_ref, name: title };
      const opened = await api.openSourceRef(sourceRef);
      onSourceOpened(opened, title, sourceRef);
      setSqlPreview(null);
      onClose();
    } catch (error) {
      setSqlError((error as Error).message);
    } finally {
      setSourceBusy(false);
    }
  };

  const newStep = (rightId: string, prior: StepState[]): StepState => {
    const right = byId.get(rightId);
    const leftCols = outputColumns(base, prior, prior.length, byId);
    return { right_id: rightId, how: "left", alias: aliasOf(right),
             columns: null, touched: false, pickCols: false,
             conditions: [defaultCondition(leftCols, right)] };
  };

  const firstOther = (exclude: string) =>
    datasets.find((d) => d.id !== exclude)?.id ?? "";
  const [steps, setSteps] = useState<StepState[]>(() => initialPlan
    ? initialPlan.steps.map((step) => ({ ...step, touched: true, pickCols: false }))
    : [newStep(firstOther(baseId), [])]);
  const canAddSource = !baseId || steps.some((step) => !step.right_id)
    || steps.length < MAX_STEPS;
  const [suggestions, setSuggestions] = useState<Record<number, JoinSuggestion[]>>({});
  const [recommendations, setRecommendations] = useState<Record<number, KeyRecommendation[]>>({});
  const [recommendationWarnings, setRecommendationWarnings] = useState<string[]>([]);
  const [preview, setPreview] = useState<JoinPreview | null>(null);
  const [previewErr, setPreviewErr] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const previewRequest = useRef(0);
  const [allowLoaded, setAllowLoaded] = useState(initialPlan?.allowLoaded ?? false);

  const stepKey = steps.map((s) => s.right_id).join("|");
  const recommendationKey = steps.map((s) =>
    `${s.right_id}:${s.how}:${s.alias}:${s.columns?.join(",") ?? "*"}`).join("|");
  const commonKeys = base?.columns.map((c) => c.name).filter((name) =>
    steps.length > 0 && steps.every((s) =>
      byId.get(s.right_id)?.columns.some((c) => c.name === name))) ?? [];
  const [commonKey, setCommonKey] = useState("");
  const selectedInputs = [base, ...steps.map((step) => byId.get(step.right_id))]
    .filter((dataset): dataset is Dataset => Boolean(dataset));
  const resources = new Set(selectedInputs.flatMap((dataset) => sourceResources(dataset.sourceRef)));
  const hasUnbackedLoaded = selectedInputs.some((dataset) =>
    dataset.queryScope === "loaded" && !dataset.sourceRef);
  const crossSource = resources.size > 1 || (resources.size > 0 && hasUnbackedLoaded);

  useEffect(() => {
    if (!commonKeys.includes(commonKey)) setCommonKey(commonKeys[0] ?? "");
  }, [stepKey, baseId, commonKeys.join("|")]);

  useEffect(() => {
    let cancelled = false;
    setSuggestions({});
    Promise.all(steps.map(async (s, i) => {
      if (!s.right_id) return [] as JoinSuggestion[];
      const lefts: { id: string; prefix: string }[] = [{ id: baseId, prefix: "" }];
      steps.slice(0, i).forEach((p) => {
        if (addsColumns(p.how)) lefts.push({ id: p.right_id, prefix: `${p.alias}${ARROW}` });
      });
      const recommendationPairs = lefts.filter((l) => {
        const leftDataset = byId.get(l.id);
        const rightDataset = byId.get(s.right_id);
        return l.id && l.id !== s.right_id
          && !(directAurora(leftDataset?.sourceRef) && directAurora(rightDataset?.sourceRef));
      });
      const all = await Promise.all(recommendationPairs.map((l) =>
        api.suggestJoin(l.id, s.right_id)
          .then((r) => r.map((x) => ({ ...x, left: l.prefix + x.left })))
          .catch(() => [] as JoinSuggestion[])));
      const leftCols = new Set(outputColumns(base, steps, i, byId));
      return all.flat().filter((x) => leftCols.has(x.left))
        .sort((a, b) => b.score - a.score).slice(0, 3);
    })).then((ranked) => {
      if (cancelled) return;
      setSuggestions(Object.fromEntries(ranked.map((items, i) => [i, items])));
    });
    return () => { cancelled = true; };
  }, [baseId, recommendationKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let cancelled = false;
    setRecommendations({});
    setRecommendationWarnings([]);
    const requests = steps.map(async (step, stepIndex) => {
      const right = byId.get(step.right_id);
      if (!directAurora(right?.sourceRef)) return { stepIndex, candidates: [], warnings: [] };
      const lefts: { dataset: Dataset; prefix: string }[] = [];
      if (base && directAurora(base.sourceRef)) lefts.push({ dataset: base, prefix: "" });
      steps.slice(0, stepIndex).forEach((prior) => {
        const dataset = byId.get(prior.right_id);
        if (addsColumns(prior.how) && dataset && directAurora(dataset.sourceRef))
          lefts.push({ dataset, prefix: `${prior.alias}${ARROW}` });
      });
      const results = await Promise.all(lefts.map(async (left) => {
        try {
          const result = await api.recommendJoin(left.dataset.sourceRef!, right?.sourceRef!);
          return {
            candidates: result.candidates.map((candidate) => ({
              ...candidate,
              keys: candidate.keys.map((key) => ({ ...key, left: left.prefix + key.left })),
              sourceTitle: left.dataset.title,
            })),
            warnings: result.warnings,
          };
        } catch { return { candidates: [], warnings: [] }; }
      }));
      const visibleLeftCols = new Set(outputColumns(base, steps, stepIndex, byId));
      const visibleRightCols = new Set(right?.columns.map((column) => column.name) ?? []);
      const methodOrder = { foreign_key: 0, exact_name: 1, jev: 2 };
      const candidates = results.flatMap((result) => result.candidates)
        .filter((candidate) => candidate.keys.length > 0 && candidate.keys.every((key) =>
          visibleLeftCols.has(key.left) && visibleRightCols.has(key.right)))
        .sort((a, b) => methodOrder[a.method] - methodOrder[b.method])
        .slice(0, 3);
      return { stepIndex, candidates,
        warnings: results.flatMap((result) => result.warnings) };
    });
    Promise.all(requests).then((results) => {
      if (cancelled) return;
      setRecommendations(Object.fromEntries(results.map((result) =>
        [result.stepIndex, result.candidates])));
      setRecommendationWarnings([...new Set(results.flatMap((result) => result.warnings))]);
    });
    return () => { cancelled = true; };
  }, [baseId, recommendationKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    previewRequest.current += 1;
    setPreview(null);
    setPreviewErr("");
    setPreviewing(false);
  }, [baseId, steps]);

  const [validation, setValidation] = useState<JoinValidation | null>(null);
  useEffect(() => {
    setValidation(null);
    if (!base || steps.some((s) => !s.right_id)) { setValidation(null); return; }
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      api.validateJoin(baseId, payload(), ctrl.signal, crossSource && allowLoaded)
        .then(setValidation)
        .catch(() => { if (!ctrl.signal.aborted) setValidation(null); });
    }, VALIDATE_DELAY_MS);
    return () => { clearTimeout(timer); ctrl.abort(); };
  }, [baseId, steps, crossSource, allowLoaded]); // eslint-disable-line react-hooks/exhaustive-deps

  const options = datasets.map((d) => ({ id: d.id, label: d.title, hint: d.source }));
  const schemas = [...new Set(sourceTables.map((item) => item.schema ?? ""))];
  const visibleSourceTables = sourceTables.filter((item) =>
    !sourceSchema || (item.schema ?? "") === sourceSchema);
  const engine = preview?.engine ?? validation?.engine;

  const update = (i: number, patch: Partial<StepState>) =>
    setSteps((prev) => prev.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  const setCondition = (i: number, k: number, patch: Partial<JoinCondition>) =>
    setSteps((prev) => prev.map((s, j) => j !== i ? s : {
      ...s, touched: true,
      conditions: s.conditions.map((c, m) => (m === k ? { ...c, ...patch } : c)),
    }));

  const changeBase = (id: string) => {
    setBaseId(id);
    setSteps([newStep(firstOther(id), [])]);
    setSuggestions({});
  };

  const applyCommonKey = () => {
    if (!commonKey) return;
    setSteps((prev) => prev.map((s) => {
      const condition = { left: commonKey, op: "=" as const, right: commonKey };
      return { ...s, touched: true,
        conditions: s.conditions.length
          ? [condition, ...s.conditions.slice(1)] : [condition] };
    }));
  };

  const changeRight = (i: number, id: string) =>
    setSteps((prev) => prev.map((s, j) => (j === i ? newStep(id, prev.slice(0, i)) : s)));

  const payload = (): JoinStep[] => steps.map(
    ({ right_id, how, conditions, columns, alias }) =>
      ({ right_id, how, conditions, columns, alias: alias.trim() }));

  const valid = Boolean(base) && validation?.ok !== false && steps.every((s) =>
    s.right_id && s.conditions.length > 0
    && s.conditions.every((c) => c.left && c.right));

  const runPreview = async () => {
    const requestId = ++previewRequest.current;
    setPreviewing(true);
    setPreviewErr("");
    try {
      const result = await api.previewJoin(baseId, payload(), crossSource && allowLoaded);
      if (requestId === previewRequest.current) setPreview(result);
    } catch (e) {
      if (requestId === previewRequest.current) setPreviewErr((e as Error).message);
    } finally {
      if (requestId === previewRequest.current) setPreviewing(false);
    }
  };

  const changeAllowLoaded = (value: boolean) => {
    setAllowLoaded(value);
    previewRequest.current += 1;
    setPreview(null);
    setPreviewErr("");
    setPreviewing(false);
  };

  return (
    <div className="join-panel">
      <div className="join-row">
        {initialPlan && <strong>Edit {initialPlan.title}</strong>}
        {!initialPlan && sourceMode === "table" && <label>Start from
          <Combobox label="Start from" value={baseId} options={options}
                    onChange={changeBase} placeholder="Choose a table…" />
        </label>}
        <div style={{ flex: 2 }} />
        <button className="quiet" onClick={onClose}>✕</button>
      </div>

      {sources.length > 0 && (
        <div className="join-source-picker">
          <strong>Add a source</strong>
          <div className="explore-toggle" role="group" aria-label="Source type">
            <button type="button" aria-pressed={sourceMode === "table"}
                    onClick={() => setSourceMode("table")}>Table</button>
            <button type="button" aria-pressed={sourceMode === "sql"}
                    disabled={selectedSource?.kind !== "aurora"}
                    onClick={() => setSourceMode("sql")}>SQL</button>
          </div>
          <div className="join-row">
            <label>Datasource
              <select aria-label="Join datasource" value={resourceKey}
                      disabled={sourceBusy}
                      onChange={(e) => { invalidateSqlPreview(); setResourceKey(e.target.value);
                        if (!e.target.value.startsWith("aurora:")) setSourceMode("table"); }}>
                {sources.map((item) => (
                  <option key={`${item.kind}:${item.id}`} value={`${item.kind}:${item.id}`}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            {sourceMode === "table" && <><label>Schema
              <select aria-label="Join schema" value={sourceSchema}
                      onChange={(e) => { setSourceSchema(e.target.value); setSourceTable(""); }}>
                <option value="">All schemas</option>
                {schemas.map((schema) => (
                  <option key={schema} value={schema}>{schema || "Default schema"}</option>
                ))}
              </select>
            </label>
            <Combobox label="Source table to add" value={sourceTable}
                      options={visibleSourceTables.map((item) => ({
                        id: item.name, label: item.name, hint: item.detail,
                      }))}
                      onChange={setSourceTable} placeholder="Search tables…" />
            <button className="primary" disabled={!sourceTable || sourceBusy || busy || !canAddSource}
                    onClick={addSourceTable}>
              {sourceBusy ? "Adding…" : "Add table"}
            </button></>}
          </div>
          {sourceMode === "table" && sourceError && <div className="join-error" role="alert">{sourceError}</div>}
          {sourceMode === "sql" && <div>
            <div className="join-row">
              <label>SQL source name
                <input type="text" value={sqlName} maxLength={128} placeholder="e.g. visits" disabled={sourceBusy}
                       onChange={(event) => setSqlName(event.target.value)} />
              </label>
            </div>
            <label>SQL query
              <textarea className="join-sql-editor" aria-label="SQL query" value={sqlText}
                        disabled={sourceBusy} spellCheck={false} placeholder="SELECT … FROM schema.table"
                        onChange={(event) => { invalidateSqlPreview(); setSqlText(event.target.value); }} />
            </label>
            <div className="join-row">
              <button className="primary" disabled={!selectedSource || selectedSource.kind !== "aurora"
                || !sqlText.trim() || sqlBusy || sourceBusy || busy || !canAddSource}
                      onClick={previewSql}>
                {sqlBusy ? "Previewing…" : "Preview SQL"}
              </button>
              {sqlPreview && <button disabled={sourceBusy || busy}
                onClick={addSqlSource}>{sourceBusy ? "Opening…" : "Open SQL result"}</button>}
            </div>
            {sqlError && <div className="join-error" role="alert">{sqlError}</div>}
            {sqlPreview && <div className="join-sql-preview" aria-label="SQL preview">
              <p>{sqlPreview.rows} preview rows{sqlPreview.truncated ? " (more rows available)" : ""}</p>
              <table><thead><tr>{sqlPreview.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
                <tbody>{sqlPreview.sample.map((row, index) => <tr key={index}>
                  {sqlPreview.columns.map((column, cell) => {
                    const value = row[cell];
                    const display = value == null ? "NULL"
                      : typeof value === "object" ? JSON.stringify(value) : String(value);
                    return <td key={`${column}-${cell}`}>{display}</td>;
                  })}
                </tr>)}</tbody>
              </table>
            </div>}
          </div>}
        </div>
      )}

      {sourceMode === "table" && <>
      {steps.length > 1 && commonKeys.length > 0 && (
        <div className="join-row">
          <label>Common key
            <select value={commonKey} onChange={(e) => setCommonKey(e.target.value)}
                    disabled={!commonKeys.length}>
              {commonKeys.map((key) => <option key={key}>{key}</option>)}
            </select>
          </label>
          <button className="link" disabled={!commonKey} onClick={applyCommonKey}>
            Apply key to all
          </button>
        </div>
      )}

      {steps.map((s, i) => {
        const right = byId.get(s.right_id);
        const leftCols = outputColumns(base, steps, i, byId);
        const rightCols = right?.columns.map((c) => c.name) ?? [];
        const picked = s.columns ?? rightCols;
        return (
          <div className="join-step" key={i}>
            <div className="join-step-head">
              <span className="join-step-no">{i + 1}</span>
              <div className="join-hows" role="radiogroup" aria-label="Join type">
                {HOWS.map((h) => (
                  <button key={h.id} title={h.hint} role="radio"
                          aria-checked={s.how === h.id}
                          className={`join-how${s.how === h.id ? " on" : ""}`}
                          onClick={() => update(i, { how: h.id })}>
                    <Venn how={h.id} />{h.label}
                  </button>
                ))}
              </div>
              {steps.length > 1 && (
                <button className="quiet" title="Remove this step"
                        onClick={() => setSteps((prev) => prev.filter((_, j) => j !== i))}>✕</button>
              )}
            </div>

            <div className="join-row">
              <label>Table
                <Combobox label={`Table to join in step ${i + 1}`} value={s.right_id}
                          options={options.filter((o) => o.id !== baseId)}
                          onChange={(id) => changeRight(i, id)}
                          placeholder="Search open tables…" />
              </label>
            </div>

            <details className="join-advanced">
              <summary>Advanced</summary>
              <div className="join-row">
                {addsColumns(s.how) && (
                  <label>Name joined columns as
                    <input value={s.alias} onChange={(e) => update(i, { alias: e.target.value })}
                           placeholder={aliasOf(right)} />
                  </label>
                )}
                <button className="link" onClick={() => update(i, { touched: true,
                  conditions: [...s.conditions, defaultCondition(leftCols, right)] })}>
                  + condition
                </button>
                {addsColumns(s.how) && (
                  <button className="link" onClick={() => update(i, { pickCols: !s.pickCols })}>
                    columns: {picked.length === rightCols.length ? "all" : `${picked.length}/${rightCols.length}`} ▾
                  </button>
                )}
              </div>
              {addsColumns(s.how) && s.pickCols && (
                <div className="join-cols">
                  <button className="link" onClick={() => update(i, { columns: null })}>all</button>
                  <button className="link" onClick={() => update(i, { columns: [] })}>none</button>
                  {rightCols.map((col) => (
                    <label key={col} className="join-col">
                      <input type="checkbox" checked={picked.includes(col)}
                             onChange={(e) => update(i, { columns: e.target.checked
                               ? rightCols.filter((x) => x === col || picked.includes(x))
                               : picked.filter((x) => x !== col) })} />
                      {col}
                    </label>
                  ))}
                </div>
              )}
            </details>

            {s.conditions.map((c, k) => {
              const check = validation?.steps[i]?.conditions[k];
              return (
                <Fragment key={k}>
                  <div className={`join-cond${check?.problem ? " invalid" : ""}`}>
                    <span className="join-cond-label">{k === 0 ? "on" : "and"}</span>
                    <select disabled={sourceBusy || busy} aria-label={`Left key step ${i + 1} condition ${k + 1}`}
                            value={c.left} onChange={(e) => setCondition(i, k, { left: e.target.value })}>
                      <option value="" disabled>Choose column</option>
                      {leftCols.map((col) => <option key={col}>{col}</option>)}
                    </select>
                    <select className="join-op" value={c.op}
                            onChange={(e) => setCondition(i, k, { op: e.target.value as JoinOp })}>
                      {OPS.map((o) => <option key={o}>{o}</option>)}
                    </select>
                    <select disabled={sourceBusy || busy} aria-label={`Right key step ${i + 1} condition ${k + 1}`}
                            value={c.right} onChange={(e) => setCondition(i, k, { right: e.target.value })}>
                      <option value="" disabled>Choose column</option>
                      {rightCols.map((col) => <option key={col}>{col}</option>)}
                    </select>
                    {s.conditions.length > 1 && (
                      <button className="quiet" title="Remove condition"
                              onClick={() => update(i, { touched: true,
                                conditions: s.conditions.filter((_, m) => m !== k) })}>✕</button>
                    )}
                  </div>
                  {check?.problem && <div className="join-check join-error" role="alert">{check.problem}</div>}
                  {check?.note && <div className="join-check settings-hint">{check.note}</div>}
                </Fragment>
              );
            })}
            {(validation?.steps[i]?.problems ?? []).map((p) =>
              <div key={p} className="join-check join-error" role="alert">{p}</div>)}
            <div className="join-tools">
              {(recommendations[i] ?? []).map((candidate, candidateIndex) => (
                <Fragment key={`${candidate.method}-${candidateIndex}`}>
                  <button className="chip"
                          onClick={() => update(i, { touched: true,
                            conditions: candidate.keys.map((key) => ({
                              left: key.left, op: "=" as const, right: key.right,
                            })) })}>
                    Apply {candidate.sourceTitle}: {candidate.keys.map((key) =>
                      `${key.left} = ${key.right}`).join(" AND ")}
                    {` · ${candidate.method === "foreign_key" ? "foreign key"
                      : candidate.method === "exact_name" ? "matching names" : "Jev suggestion"}`}
                    {candidate.method === "jev" && candidate.confidence != null
                      ? ` · ${Math.round(candidate.confidence * 100)}% confidence` : ""}
                  </button>
                  {candidate.evidence.length > 0 && (
                    <details className="join-evidence">
                      <summary>Evidence</summary>
                      {candidate.evidence.join("; ")}
                    </details>
                  )}
                </Fragment>
              ))}
              {(suggestions[i] ?? []).map((sg) => (
                <button key={`${sg.left}|${sg.right}`} className="chip"
                        title={`${Math.round(sg.overlap * 100)}% of left values found`}
                        onClick={() => update(i, { touched: true,
                          conditions: [{ left: sg.left, op: "=", right: sg.right }] })}>
                  {sg.left} = {sg.right} · {Math.round(sg.overlap * 100)}%
                </button>
              ))}
            </div>
          </div>
        );
      })}

      {recommendationWarnings.length > 0 && (
        <details className="join-evidence">
          <summary>Recommendation details</summary>
          {[...new Set(recommendationWarnings)].map((warning) => (
            <div key={warning}>{warning}</div>
          ))}
        </details>
      )}

      <div className="join-row">
        {steps.length < MAX_STEPS && datasets.length >= 2 && (
          <button className="link"
                  onClick={() => setSteps((prev) => [...prev, newStep(firstOther(baseId), prev)])}>
            + add another table
          </button>
        )}
        <div style={{ flex: 1 }} />
        {engine && (
          <span className={`join-engine ${engine}`}
                title={validation?.engine_reason ?? ""}>{ENGINE_LABEL[engine]}</span>
        )}
        <button className="quiet" disabled={!valid || previewing || sourceBusy || busy
          || (crossSource && !allowLoaded)} onClick={runPreview}>
          {previewing ? "Previewing…" : "Preview"}
        </button>
        <button className="primary" disabled={!valid || busy || sourceBusy
          || (crossSource && !allowLoaded)}
                onClick={() => onJoin({ baseId, steps: payload(), allowLoaded: crossSource && allowLoaded })}>
          {busy ? "Joining…" : initialPlan ? "Create edited join in new tab" : "Join into new tab"}
        </button>
      </div>

      {crossSource && <div className="settings-hint join-warn">
        <label><input type="checkbox" checked={allowLoaded} disabled={busy || previewing}
          onChange={(event) => changeAllowLoaded(event.target.checked)} />
          Allow full-source cross-source join
        </label>
        <div>{allowLoaded
          ? "Studio will scan each complete source and stage the join on disk. The operation stops above 1 TB."
          : "Cross-source joins require your approval to scan complete sources."}</div>
      </div>}

      {(validation?.problems ?? []).map((p) =>
        <div key={p} className="settings-hint join-error">{p}</div>)}
      {validation?.generated_sql && <details className="join-evidence">
        <summary>Generated SQL</summary>
        <div className="settings-hint">Engine: {validation.generated_sql.engine === "aurora" ? "Aurora" : "DuckDB"}</div>
        {validation.generated_sql.staged_inputs?.length ? <div className="settings-hint">
          Staged inputs: {validation.generated_sql.staged_inputs.join(", ")}
        </div> : null}
        <pre aria-label="Generated SQL" style={{ overflowX: "auto", whiteSpace: "pre-wrap", maxHeight: 260 }}>
          {validation.generated_sql.sql}
        </pre>
        <div className="settings-hint">Parameters</div>
        <pre aria-label="SQL parameters" style={{ overflowX: "auto", whiteSpace: "pre-wrap", maxHeight: 180 }}>
          {JSON.stringify(validation.generated_sql.parameters, null, 2)}
        </pre>
      </details>}
      {!preview && (validation?.capped_inputs.length ?? 0) > 0 && (
        <div className="settings-hint join-warn join-capped">
          Runs in memory on the loaded rows of {validation!.capped_inputs.join(", ")},
          which hit the row cap — results may be incomplete.
        </div>
      )}
      {previewErr && <div className="settings-hint join-error">{previewErr}</div>}
      {preview && (
        <div className="join-preview">
          <div className="join-funnel">
            <span>{preview.base_rows.toLocaleString()} rows</span>
            {preview.steps.map((st, i) => (
              <span key={i}>→ {HOWS.find((h) => h.id === steps[i]?.how)?.label.toLowerCase()}{" "}
                {steps[i]?.alias || aliasOf(byId.get(steps[i]?.right_id ?? ""))}:{" "}
                <strong>{st.rows.toLocaleString()}</strong>
                {st.fanout && (
                  <span className="join-warn join-fanout"
                        title="Rows multiplied: the join key repeats on the joined side.">
                    {" "}×{st.growth} fan-out
                  </span>
                )}</span>
            ))}
            {preview.truncated && <span className="join-warn">capped at {preview.rows.toLocaleString()} rows</span>}
          </div>
          {preview.notes.map((n) => <div key={n} className="settings-hint">{n}</div>)}
          <div className="join-sample">
            <table>
              <thead><tr>{preview.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>
                {preview.sample.map((row, r) => (
                  <tr key={r}>{row.map((v, c) => <td key={c}>{v == null ? "—" : String(v)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      </>}
    </div>
  );
}
