import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  Dataset, JoinCondition, JoinHow, JoinOp, JoinPreview, JoinStep,
  JoinSuggestion,
} from "../types";

interface Props {
  datasets: Dataset[];
  busy: boolean;
  onJoin: (p: { baseId: string; steps: JoinStep[] }) => void;
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

interface StepState extends JoinStep { touched: boolean; pickCols: boolean }

const aliasOf = (d?: Dataset) =>
  (d?.title ?? "joined").replace(/\.(parquet|csv|tsv|txt|json|ndjson)$/i, "");

const addsColumns = (how: JoinHow) => how !== "semi" && how !== "anti";

// Two-circle diagram of which rows a join keeps (left circle = left side).
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
  const rightCols = right?.columns.map((c) => c.name) ?? [];
  const shared = leftCols.find((c) => rightCols.includes(c));
  return { left: shared ?? leftCols[0] ?? "", op: "=",
           right: shared ?? rightCols[0] ?? "" };
}

export function JoinPanel({ datasets, busy, onJoin, onClose }: Props) {
  const byId = useMemo(() => new Map(datasets.map((d) => [d.id, d])), [datasets]);
  const [baseId, setBaseId] = useState(datasets[0]?.id ?? "");
  const base = byId.get(baseId);

  const newStep = (rightId: string, prior: StepState[]): StepState => {
    const right = byId.get(rightId);
    const leftCols = outputColumns(base, prior, prior.length, byId);
    return { right_id: rightId, how: "left", alias: aliasOf(right),
             columns: null, touched: false, pickCols: false,
             conditions: [defaultCondition(leftCols, right)] };
  };

  const firstOther = (exclude: string) =>
    datasets.find((d) => d.id !== exclude)?.id ?? "";
  const [steps, setSteps] = useState<StepState[]>(() =>
    [newStep(firstOther(baseId), [])]);
  const [suggestions, setSuggestions] = useState<Record<number, JoinSuggestion[]>>({});
  const [preview, setPreview] = useState<JoinPreview | null>(null);
  const [previewErr, setPreviewErr] = useState("");
  const [previewing, setPreviewing] = useState(false);

  const stepKey = steps.map((s) => s.right_id).join("|");

  // Suggest keys against the base and every earlier joined table.
  useEffect(() => {
    let cancelled = false;
    steps.forEach((s, i) => {
      if (!s.right_id) return;
      const lefts: { id: string; prefix: string }[] = [{ id: baseId, prefix: "" }];
      steps.slice(0, i).forEach((p) => {
        if (addsColumns(p.how)) lefts.push({ id: p.right_id, prefix: `${p.alias}${ARROW}` });
      });
      Promise.all(lefts.filter((l) => l.id && l.id !== s.right_id).map((l) =>
        api.suggestJoin(l.id, s.right_id)
          .then((r) => r.map((x) => ({ ...x, left: l.prefix + x.left })))
          .catch(() => [] as JoinSuggestion[])))
        .then((all) => {
          if (cancelled) return;
          const leftCols = new Set(outputColumns(base, steps, i, byId));
          const ranked = all.flat().filter((x) => leftCols.has(x.left))
            .sort((a, b) => b.score - a.score).slice(0, 3);
          setSuggestions((prev) => ({ ...prev, [i]: ranked }));
          // A same-named default key stands; otherwise take the best guess.
          const top = ranked[0];
          if (top) setSteps((prev) => prev.map((p, j) =>
            j === i && !p.touched && p.conditions.length === 1
              && p.conditions[0].left !== p.conditions[0].right
              ? { ...p, conditions: [{ left: top.left, op: "=", right: top.right }] }
              : p));
        });
    });
    return () => { cancelled = true; };
  }, [baseId, stepKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { setPreview(null); setPreviewErr(""); }, [baseId, steps]);

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

  const changeRight = (i: number, id: string) =>
    setSteps((prev) => prev.map((s, j) => (j === i ? newStep(id, prev.slice(0, i)) : s)));

  const payload = (): JoinStep[] => steps.map(
    ({ right_id, how, conditions, columns, alias }) =>
      ({ right_id, how, conditions, columns, alias: alias.trim() }));

  const valid = Boolean(base) && steps.every((s) =>
    s.right_id && s.conditions.length > 0
    && s.conditions.every((c) => c.left && c.right));

  const runPreview = async () => {
    setPreviewing(true);
    setPreviewErr("");
    try {
      setPreview(await api.previewJoin(baseId, payload()));
    } catch (e) {
      setPreviewErr((e as Error).message);
    } finally {
      setPreviewing(false);
    }
  };

  return (
    <div className="join-panel">
      <div className="join-row">
        <label>Start from
          <select value={baseId} onChange={(e) => changeBase(e.target.value)}>
            {datasets.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
          </select>
        </label>
        <div style={{ flex: 2 }} />
        <button className="quiet" onClick={onClose}>✕</button>
      </div>

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
                <select value={s.right_id} onChange={(e) => changeRight(i, e.target.value)}>
                  {datasets.filter((d) => d.id !== baseId).map((d) =>
                    <option key={d.id} value={d.id}>{d.title}</option>)}
                </select>
              </label>
              {addsColumns(s.how) && (
                <label>Name joined columns as
                  <input value={s.alias} onChange={(e) => update(i, { alias: e.target.value })}
                         placeholder={aliasOf(right)} />
                </label>
              )}
            </div>

            {s.conditions.map((c, k) => (
              <div className="join-cond" key={k}>
                <span className="join-cond-label">{k === 0 ? "on" : "and"}</span>
                <select value={c.left} onChange={(e) => setCondition(i, k, { left: e.target.value })}>
                  {leftCols.map((col) => <option key={col}>{col}</option>)}
                </select>
                <select className="join-op" value={c.op}
                        onChange={(e) => setCondition(i, k, { op: e.target.value as JoinOp })}>
                  {OPS.map((o) => <option key={o}>{o}</option>)}
                </select>
                <select value={c.right} onChange={(e) => setCondition(i, k, { right: e.target.value })}>
                  {rightCols.map((col) => <option key={col}>{col}</option>)}
                </select>
                {s.conditions.length > 1 && (
                  <button className="quiet" title="Remove condition"
                          onClick={() => update(i, { touched: true,
                            conditions: s.conditions.filter((_, m) => m !== k) })}>✕</button>
                )}
              </div>
            ))}
            <div className="join-tools">
              <button className="link" onClick={() => update(i, { touched: true,
                conditions: [...s.conditions, defaultCondition(leftCols, right)] })}>
                + condition
              </button>
              {(suggestions[i] ?? []).map((sg) => (
                <button key={`${sg.left}|${sg.right}`} className="chip"
                        title={`${Math.round(sg.overlap * 100)}% of left values found`}
                        onClick={() => update(i, { touched: true,
                          conditions: [{ left: sg.left, op: "=", right: sg.right }] })}>
                  {sg.left} = {sg.right} · {Math.round(sg.overlap * 100)}%
                </button>
              ))}
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
          </div>
        );
      })}

      <div className="join-row">
        {steps.length < MAX_STEPS && datasets.length >= 2 && (
          <button className="link"
                  onClick={() => setSteps((prev) => [...prev, newStep(firstOther(baseId), prev)])}>
            + add another table
          </button>
        )}
        <div style={{ flex: 1 }} />
        <button className="quiet" disabled={!valid || previewing} onClick={runPreview}>
          {previewing ? "Previewing…" : "Preview"}
        </button>
        <button className="primary" disabled={!valid || busy}
                onClick={() => onJoin({ baseId, steps: payload() })}>
          {busy ? "Joining…" : "Join into new tab"}
        </button>
      </div>

      {previewErr && <div className="settings-hint join-error">{previewErr}</div>}
      {preview && (
        <div className="join-preview">
          <div className="join-funnel">
            <span>{preview.base_rows.toLocaleString()} rows</span>
            {preview.steps.map((st, i) => (
              <span key={i}>→ {HOWS.find((h) => h.id === steps[i]?.how)?.label.toLowerCase()}{" "}
                {steps[i]?.alias || aliasOf(byId.get(steps[i]?.right_id ?? ""))}:{" "}
                <strong>{st.rows.toLocaleString()}</strong></span>
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
    </div>
  );
}
