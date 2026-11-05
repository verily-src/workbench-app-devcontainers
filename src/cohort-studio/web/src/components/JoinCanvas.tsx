/** Visual join canvas: drag tables onto a canvas, link them, and run the join.
 * Builds exactly the same join request as the step builder (JoinPanel); see
 * joinModel.ts for the canvas ↔ request mapping. */
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { DataJob, OpenResult } from "../api";
import type {
  ColumnProfile, Dataset, JoinFilter, JoinHow, JoinOp, JoinPreview, JoinRecommendation,
  JoinStep, JoinSuggestion, JoinValidation, Source, SourceRef, TableInfo,
} from "../types";
import { tableStats } from "../format";
import { Combobox } from "./Combobox";
import { JobProgress } from "./DataJobs";
import type { FilterRow } from "./JoinPanel";
import {
  ARROW, FilterEditor, KIND_LABEL, Venn, addsColumns, colKind, directAurora, filterProblem,
  sentFilters, sourceResources,
} from "./JoinPanel";
import {
  MAX_JOINED, NODE_H, NODE_W, byNodeId, connector, fromPlan, isBlankCond, isCompleteCond,
  layout, localProblems, offeredColumns, orderedSteps, rootOf, subtree, toJoinRef, toPlan,
  uniqueAlias,
} from "../joinModel";
import type { CanvasCond, CanvasNode, JoinPlan } from "../joinModel";
import "./JoinCanvas.css";

type JoinRef = Extract<SourceRef, { kind: "join" }>;

export interface CanvasJoinRequest {
  baseId: string; steps: JoinStep[]; allowLoaded: boolean; baseFilters: JoinFilter[];
  title: string; extraInputs: Dataset[]; fromCanvas: true;
}

interface Props {
  /** Open tabs in Explore; they can be used as canvas tables. */
  datasets: Dataset[];
  sources: Source[];
  busy: boolean;
  /** A saved join to reconstruct (Edit join in canvas); a new nonce reopens. */
  edit?: { nonce: number; title: string; ref: JoinRef } | null;
  onJoin: (p: CanvasJoinRequest) => Promise<unknown>;
  onOpenResult: (opened: OpenResult, title: string, sourceRef?: SourceRef) => void;
  onAddSource: () => void;
  onClose: () => void;
}

const KIND_BADGE: Record<string, string> = {
  aurora: "Aurora", postgres: "PostgreSQL", athena: "Athena", s3: "S3", bq: "BigQuery",
  catalog: "Catalog", sql: "SQL", join: "Join", derived: "Derived", materialized: "Snapshot",
  group_summary: "Summary", omop_cohort: "OMOP",
};
const SOURCE_KIND_LABEL: Record<string, string> = {
  aurora: "Aurora database", postgres: "PostgreSQL / RDS", athena: "Athena / Iceberg",
  s3: "S3 files", bq: "BigQuery", catalog: "Catalog",
};
const MAIN_HOWS: { id: JoinHow; label: string }[] = [
  { id: "inner", label: "Inner" }, { id: "left", label: "Left" },
  { id: "right", label: "Right" }, { id: "full", label: "Outer" },
];
const MORE_HOWS: { id: JoinHow; label: string }[] = [
  { id: "semi", label: "Has match" }, { id: "anti", label: "No match" },
];
const HOW_LABEL: Record<JoinHow, string> = {
  inner: "Inner", left: "Left", right: "Right", full: "Outer", semi: "Has match", anti: "No match",
};
const OPS: JoinOp[] = ["=", "!=", "<", "<=", ">", ">="];
const VALIDATE_DELAY_MS = 300;
const SAVED_KEY = "cohort-studio.join-canvas.saved";
const DRAG_TYPE = "application/x-cohort-table";

function explain(how: JoinHow, left: string, right: string): string {
  switch (how) {
    case "inner": return `Returns rows only where ${left} and ${right} have matching values in the join fields.`;
    case "left": return `Returns every ${left} row, with ${right} values where they match (blank otherwise).`;
    case "right": return `Returns every ${right} row, with ${left} values where they match (blank otherwise).`;
    case "full": return `Returns every row from both ${left} and ${right}, side by side where they match.`;
    case "semi": return `Keeps ${left} rows that have a match in ${right}; adds no ${right} columns.`;
    case "anti": return `Keeps ${left} rows with no match in ${right}; adds no ${right} columns.`;
  }
}

type DragItem = { type: "table"; sourceKey: string; name: string } | { type: "tab"; datasetId: string };

let nodeSeq = 0;
const nodeId = () => `n${++nodeSeq}`;

/** #root may be CSS-zoomed (Display size); pointer offsets inside it are divided by this. */
const rootZoom = () =>
  parseFloat(getComputedStyle(document.getElementById("root") ?? document.body).zoom) || 1;

function TypeIcon({ column }: { column?: ColumnProfile }) {
  const kind = colKind(column);
  const geo = /(^|_)(lat|latitude|lon|lng|longitude|country|state|city|zip|postal|county|region)($|_)/i
    .test(column?.name ?? "");
  const label = geo ? "geographic" : KIND_LABEL[kind];
  return (
    <span className={`jc-type jc-type-${geo ? "geo" : kind}`} title={label} aria-label={label} role="img">
      {geo ? (
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden>
          <circle cx="8" cy="8" r="6.2" /><path d="M1.8 8h12.4M8 1.8c2 2 2 10.4 0 12.4M8 1.8c-2 2-2 10.4 0 12.4" />
        </svg>
      ) : kind === "time" ? (
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden>
          <rect x="2" y="3" width="12" height="11" rx="1.5" /><path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3" />
        </svg>
      ) : kind === "number" ? "#" : kind === "bool" ? "T|F" : "Abc"}
    </span>
  );
}

function TableIcon() {
  return (
    <svg className="jc-table-icon" width="14" height="14" viewBox="0 0 16 16" fill="none"
         stroke="currentColor" strokeWidth="1.3" aria-hidden>
      <rect x="1.8" y="2.5" width="12.4" height="11" rx="1.5" />
      <path d="M1.8 6h12.4M1.8 9.5h12.4M6.2 6v7.5" />
    </svg>
  );
}

interface LinkDraft {
  nodeId: string; how: JoinHow; conditions: CanvasCond[]; filterRows: FilterRow[];
  /** Set when suggested keys were filled in, until the user changes them. */
  suggestedBy?: string;
  edited: boolean;
}

interface KeyIdeas {
  recommendations: (JoinRecommendation & { sourceTitle: string })[];
  suggestions: JoinSuggestion[];
}

function refTitle(ref: SourceRef): string {
  if (ref.kind === "join") return "Joined input";
  if (ref.kind === "derived") return ref.spec.name;
  if (ref.kind === "group_summary") return `Group summary (${ref.spec.group_by.join(", ")})`;
  if (ref.kind === "omop_cohort") return ref.name || "OMOP cohort";
  if (ref.kind === "sql") return ref.name || "SQL result";
  if (ref.kind === "materialized") return "Saved join";
  return ref.table.split("/").pop() ?? ref.table;
}

const toDataset = (opened: OpenResult, title: string, ref?: SourceRef): Dataset => ({
  id: opened.dataset_id, title, source: opened.source, sourceRef: opened.source_ref ?? ref,
  sourceInfo: opened.source_info, queryScope: opened.query_scope, columns: opened.columns,
  filters: [], charts: [], page: 0,
});

const sameRef = (a?: SourceRef, b?: SourceRef) => Boolean(a && b) && JSON.stringify(a) === JSON.stringify(b);

export function JoinCanvas({ datasets, sources, busy, edit, onJoin, onOpenResult, onAddSource, onClose }: Props) {
  const [nodes, setNodes] = useState<CanvasNode[]>([]);
  const [name, setName] = useState("New join");
  const [selection, setSelection] = useState<{ type: "node" | "link"; id: string } | null>(null);
  const [draft, setDraft] = useState<LinkDraft | null>(null);
  const [mode, setMode] = useState<"live" | "extract">("live");
  const [extractResource, setExtractResource] = useState("");
  const [extractTable, setExtractTable] = useState("");
  const [allowLoaded, setAllowLoaded] = useState(false);
  const [validation, setValidation] = useState<JoinValidation | null>(null);
  const [preview, setPreview] = useState<JoinPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewErr, setPreviewErr] = useState("");
  const [previewJob, setPreviewJob] = useState<{ job: DataJob; receivedAt: number } | null>(null);
  const [growthConfirmed, setGrowthConfirmed] = useState(false);
  const [showSql, setShowSql] = useState(false);
  const [copyStatus, setCopyStatus] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filterTable, setFilterTable] = useState("");
  const [gridTable, setGridTable] = useState("result");
  const [rowLimitText, setRowLimitText] = useState("100");
  const [rowLimit, setRowLimit] = useState(100);
  const [gridOpen, setGridOpen] = useState(true);
  const [fieldsOpen, setFieldsOpen] = useState(true);
  const [fieldSearch, setFieldSearch] = useState("");
  const [tablePreview, setTablePreview] = useState<{ nodeId: string; columns: string[]; data: unknown[][];
    total?: number; error?: string; loading?: boolean } | null>(null);
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [hoverNode, setHoverNode] = useState<string | null>(null);
  const [canvasHover, setCanvasHover] = useState(false);
  const [connectDrag, setConnectDrag] = useState<{ from: string; x: number; y: number } | null>(null);
  const [ideas, setIdeas] = useState<Record<string, KeyIdeas>>({});
  const [saved, setSaved] = useState<{ name: string; ref: JoinRef; savedAt: string } | null>(() => {
    try { return JSON.parse(localStorage.getItem(SAVED_KEY) || "null"); } catch { return null; }
  });

  // Connections pane.
  const [sourceKey, setSourceKey] = useState("");
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [tablesLoading, setTablesLoading] = useState(false);
  const [tablesError, setTablesError] = useState("");
  const [tablesRefresh, setTablesRefresh] = useState(0);
  const [tableSearch, setTableSearch] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const nodesRef = useRef(nodes);
  nodesRef.current = nodes;
  const previewRequest = useRef(0);
  const previewAbort = useRef<AbortController | null>(null);

  const selectedSource = sources.find((s) => `${s.kind}:${s.id}` === sourceKey);
  useEffect(() => {
    if (!sourceKey && sources.length) setSourceKey(`${sources[0].kind}:${sources[0].id}`);
  }, [sourceKey, sources]);
  useEffect(() => {
    if (!selectedSource) { setTables([]); return; }
    let current = true;
    setTables([]); setTablesError(""); setTablesLoading(true);
    api.tables(selectedSource.kind, selectedSource.id, tablesRefresh > 0)
      .then((items) => { if (current) setTables(items); })
      .catch((e) => { if (current) setTablesError((e as Error).message); })
      .finally(() => { if (current) setTablesLoading(false); });
    return () => { current = false; };
  }, [sourceKey, tablesRefresh]); // eslint-disable-line react-hooks/exhaustive-deps

  const ids = useMemo(() => byNodeId(nodes), [nodes]);
  const root = rootOf(nodes);
  const steps = useMemo(() => orderedSteps(nodes), [nodes]);
  const ready = nodes.length > 0 && nodes.every((n) => n.dataset);
  const plan: JoinPlan | null = useMemo(() => (ready ? toPlan(nodes) : null), [nodes, ready]);
  const planKey = JSON.stringify(plan);
  const local = useMemo(() => localProblems(nodes), [nodes]);
  const inputs = nodes.map((n) => n.dataset).filter((d): d is Dataset => Boolean(d));
  const resources = new Set(inputs.flatMap((d) => sourceResources(d.sourceRef)));
  const crossSource = resources.size > 1
    || (resources.size > 0 && inputs.some((d) => d.queryScope === "loaded" && !d.sourceRef));
  const sentAllowLoaded = crossSource && allowLoaded;
  const auroraTargets = sources.filter((s) => (s.kind === "aurora" || s.kind === "postgres") && !s.read_only);
  const extractReason = auroraTargets.length ? null
    : "Extract saves the joined rows as a new database table and needs a writable Aurora or PostgreSQL datasource.";
  useEffect(() => { if (extractReason && mode === "extract") setMode("live"); }, [extractReason, mode]);
  useEffect(() => {
    if (!extractResource && auroraTargets[0]) setExtractResource(auroraTargets[0].id);
  }, [auroraTargets.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const [extractTableEdited, setExtractTableEdited] = useState(false);
  useEffect(() => {
    if (!extractTableEdited)
      setExtractTable(name.trim().replace(/[^A-Za-z0-9_]/g, "_").toLowerCase().slice(0, 48) || "joined");
  }, [name, extractTableEdited]);

  // ---- Server validation (debounced), preview reset on change ----
  useEffect(() => {
    setValidation(null);
    setCopyStatus("");
    previewRequest.current += 1;
    previewAbort.current?.abort();
    setPreview(null); setPreviewErr(""); setPreviewing(false); setGrowthConfirmed(false);
    if (!plan || !plan.steps.length) return;
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      api.validateJoin(plan.baseId, plan.steps, ctrl.signal, sentAllowLoaded, plan.baseFilters)
        .then(setValidation)
        .catch(() => { if (!ctrl.signal.aborted) setValidation(null); });
    }, VALIDATE_DELAY_MS);
    return () => { clearTimeout(timer); ctrl.abort(); };
  }, [planKey, sentAllowLoaded]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => previewAbort.current?.abort(), []);

  // ---- Key suggestions per link (parent → child) ----
  const linkKey = steps.map((n) => `${n.id}:${n.parentId}:${n.dataset?.id ?? ""}:${ids.get(n.parentId!)?.dataset?.id ?? ""}`).join("|");
  useEffect(() => {
    let cancelled = false;
    for (const node of steps) {
      const parent = ids.get(node.parentId!);
      const left = parent?.dataset, right = node.dataset;
      const key = `${left?.id}|${right?.id}`;
      if (!left || !right || ideas[node.id + "@" + key]) continue;
      const both = directAurora(left.sourceRef) && directAurora(right.sourceRef);
      const recs = both
        ? api.recommendJoin(left.sourceRef!, right.sourceRef!).then((r) => r.candidates
            .filter((c) => c.keys.length > 0).map((c) => ({ ...c, sourceTitle: parent!.title })))
            .catch(() => [])
        : Promise.resolve([]);
      const sugg = both ? Promise.resolve([] as JoinSuggestion[])
        : api.suggestJoin(left.id, right.id).then((r) => r.sort((a, b) => b.score - a.score).slice(0, 3))
            .catch(() => [] as JoinSuggestion[]);
      void Promise.all([recs, sugg]).then(([recommendations, suggestions]) => {
        if (cancelled) return;
        const order = { foreign_key: 0, exact_name: 1, jev: 2 };
        setIdeas((prev) => ({ ...prev, [node.id + "@" + key]: {
          recommendations: recommendations.sort((a, b) => order[a.method] - order[b.method]).slice(0, 3),
          suggestions } }));
      });
    }
    return () => { cancelled = true; };
  }, [linkKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const ideasFor = (node: CanvasNode): KeyIdeas | undefined => {
    const parent = ids.get(node.parentId ?? "");
    return ideas[`${node.id}@${parent?.dataset?.id}|${node.dataset?.id}`];
  };

  /** Confident suggestion to pre-fill a new link's draft (the user still applies it). */
  const confident = (node: CanvasNode): { conditions: CanvasCond[]; by: string } | null => {
    const found = ideasFor(node);
    const parentId = node.parentId!;
    const rec = found?.recommendations.find((r) => r.method !== "jev" || (r.confidence ?? 0) >= 0.8);
    if (rec) return { by: rec.method === "foreign_key" ? "a foreign key" : rec.method === "exact_name" ? "matching names" : "a Jev suggestion",
      conditions: rec.keys.map((k) => ({ leftNode: parentId, left: k.left, op: "=", right: k.right })) };
    const sg = found?.suggestions.find((s) => s.overlap >= 0.9);
    if (sg) return { by: `${Math.round(sg.overlap * 100)}% matching values`,
      conditions: [{ leftNode: parentId, left: sg.left, op: "=", right: sg.right }] };
    return null;
  };

  // Fill the open draft once suggestions arrive, unless the user already edited it.
  useEffect(() => {
    if (!draft || draft.edited || draft.conditions.some((c) => !isBlankCond(c))) return;
    const node = ids.get(draft.nodeId);
    if (!node) return;
    const idea = confident(node);
    if (idea) setDraft({ ...draft, conditions: idea.conditions, suggestedBy: idea.by });
  }, [ideas, draft?.nodeId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- Node operations ----
  const patchNode = (id: string, patch: Partial<CanvasNode>) =>
    setNodes((prev) => prev.map((n) => (n.id === id ? { ...n, ...patch } : n)));

  const openLink = (id: string, list = nodesRef.current) => {
    const node = list.find((n) => n.id === id);
    if (!node) return;
    setSelection({ type: "link", id });
    const blank = !node.conditions.length;
    setDraft({ nodeId: id, how: node.how, edited: false,
      conditions: blank ? [{ leftNode: node.parentId!, left: "", op: "=", right: "" }] : node.conditions,
      filterRows: node.filterRows });
  };

  const closeOwned = (list: CanvasNode[]) => {
    for (const n of list) if (n.owned && n.dataset) void api.closeDataset(n.dataset.id).catch(() => undefined);
  };

  const removeNode = (id: string) => {
    const gone = subtree(nodesRef.current, id);
    closeOwned(nodesRef.current.filter((n) => gone.has(n.id)));
    setNodes((prev) => prev.filter((n) => !gone.has(n.id)));
    if (selection && gone.has(selection.id)) { setSelection(null); setDraft(null); }
    if (gone.has(gridTable)) setGridTable("result");
  };

  const reparent = (childId: string, parentId: string) => {
    const list = nodesRef.current;
    const child = list.find((n) => n.id === childId);
    if (!child?.parentId || subtree(list, childId).has(parentId) || child.parentId === parentId) return;
    const next = list.map((n) => (n.id === childId
      ? { ...n, parentId, touched: false, conditions: [] } : n));
    setNodes(next);
    openLink(childId, next);
  };

  const addItem = async (item: DragItem, target?: string) => {
    setError("");
    const list = nodesRef.current;
    if (list.length > MAX_JOINED) { setError(`A join can include up to ${MAX_JOINED} additional tables.`); return; }
    const parentId = list.length ? (target && list.some((n) => n.id === target) ? target : rootOf(list)!.id) : undefined;
    const id = nodeId();
    if (item.type === "tab") {
      const dataset = datasets.find((d) => d.id === item.datasetId);
      if (!dataset) return;
      const node: CanvasNode = {
        id, title: dataset.title, badge: KIND_BADGE[dataset.sourceRef?.kind ?? ""] ?? "Open tab",
        dataset, owned: false, rows: dataset.result?.total, alias: uniqueAlias(dataset.title, list),
        columns: null, filterRows: [], parentId, how: "left", conditions: [], touched: false,
      };
      const next = [...list, node];
      setNodes(next);
      if (parentId) openLink(id, next); else setSelection({ type: "node", id });
      return;
    }
    const source = sources.find((s) => `${s.kind}:${s.id}` === item.sourceKey);
    const info = (item.sourceKey === sourceKey ? tables : []).find((t) => t.name === item.name);
    if (!source || !info) return;
    const ref: SourceRef = {
      kind: source.kind, resource_id: source.id, ...(source.uuid ? { uuid: source.uuid } : {}),
      ...(info.schema ? { schema: info.schema } : {}), table: info.table ?? info.name,
    } as SourceRef;
    const title = info.name.split("/").pop() || info.name;
    const placeholder: CanvasNode = {
      id, title, badge: KIND_BADGE[source.kind] ?? source.kind, owned: true,
      rows: info.rows, rowsEstimated: info.rows_estimated, columnCount: info.columns,
      alias: uniqueAlias(title, list), columns: null, filterRows: [], parentId, how: "left",
      conditions: [], touched: false,
    };
    setNodes([...list, placeholder]);
    try {
      const opened = await api.openSourceRef(ref);
      const dataset = toDataset(opened, title, ref);
      if (!nodesRef.current.some((n) => n.id === id)) { void api.closeDataset(dataset.id).catch(() => undefined); return; }
      const next = nodesRef.current.map((n) => (n.id === id ? { ...n, dataset } : n));
      setNodes(next);
      if (parentId) openLink(id, next); else setSelection({ type: "node", id });
    } catch (e) {
      setNodes((prev) => prev.filter((n) => n.id !== id));
      setError(`Could not open ${title}: ${(e as Error).message}`);
    }
  };

  const clearCanvas = () => {
    closeOwned(nodesRef.current);
    setNodes([]); setSelection(null); setDraft(null); setGridTable("result");
    setAllowLoaded(false); setStatus(""); setError("");
  };

  // ---- Reconstruct a saved join (Edit join in canvas / reopen saved model) ----
  const reconstruct = async (ref: JoinRef, title: string, editing = false) => {
    clearCanvas();
    setStatus(`Opening ${title}…`);
    const opened: { ref: SourceRef; dataset: Dataset; owned: boolean }[] = [];
    const open = async (source: SourceRef): Promise<Dataset> => {
      const reuse = opened.find((o) => sameRef(o.ref, source))?.dataset
        ?? datasets.find((d) => sameRef(d.sourceRef, source));
      if (reuse) { opened.push({ ref: source, dataset: reuse, owned: false }); return reuse; }
      const result = await api.openSourceRef(source);
      const dataset = toDataset(result, refTitle(source), source);
      opened.push({ ref: source, dataset, owned: true });
      return dataset;
    };
    try {
      const base = await open(ref.base);
      const stepIds: JoinStep[] = [];
      for (const step of ref.steps) {
        const { source, ...rest } = step;
        stepIds.push({ ...rest, right_id: (await open(source)).id });
      }
      const seen = new Set<string>();
      const list = fromPlan({ baseId: base.id, steps: stepIds, baseFilters: ref.base_filters ?? [] },
        (datasetId, index) => {
          const entry = opened[index];
          const owned = entry.owned && !seen.has(datasetId);
          seen.add(datasetId);
          return { id: nodeId(), title: entry.dataset.title, dataset: entry.dataset, owned,
                   badge: KIND_BADGE[entry.ref.kind] ?? entry.ref.kind };
        });
      setNodes(list);
      setName(editing ? `${title} (edited)` : title);
      setAllowLoaded(ref.allow_loaded ?? false);
      setStatus("");
    } catch (e) {
      for (const o of opened) if (o.owned) void api.closeDataset(o.dataset.id).catch(() => undefined);
      setStatus("");
      setError(`Could not open the join on the canvas: ${(e as Error).message}`);
    }
  };
  const lastEdit = useRef<number | null>(null);
  useEffect(() => {
    if (!edit || lastEdit.current === edit.nonce) return;
    lastEdit.current = edit.nonce;
    void reconstruct(edit.ref, edit.title, true);
  }, [edit?.nonce]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- Drag and drop ----
  const startDrag = (event: React.DragEvent, item: DragItem) => {
    event.dataTransfer.setData(DRAG_TYPE, JSON.stringify(item));
    event.dataTransfer.setData("text/plain", item.type === "table" ? item.name : item.datasetId);
    event.dataTransfer.effectAllowed = "copy";
  };
  const dropTarget = (event: React.DragEvent) =>
    (event.target as Element).closest<HTMLElement>("[data-node-id]")?.dataset.nodeId;
  const onDragOver = (event: React.DragEvent) => {
    if (!event.dataTransfer.types.includes(DRAG_TYPE)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setCanvasHover(true);
    setHoverNode(dropTarget(event) ?? null);
  };
  const onDrop = (event: React.DragEvent) => {
    event.preventDefault();
    setCanvasHover(false); setHoverNode(null);
    const raw = event.dataTransfer.getData(DRAG_TYPE);
    if (!raw) return;
    try { void addItem(JSON.parse(raw) as DragItem, dropTarget(event)); } catch { /* not ours */ }
  };

  // Connector handle: drag from one card onto another to join that table to this one.
  const startConnect = (event: React.PointerEvent, from: string) => {
    event.preventDefault();
    event.stopPropagation();
    const rect = canvasRef.current!.getBoundingClientRect();
    const zoom = rootZoom();
    const scroll = canvasRef.current!;
    const at = (e: PointerEvent | React.PointerEvent) => ({
      x: (e.clientX - rect.left) / zoom + scroll.scrollLeft,
      y: (e.clientY - rect.top) / zoom + scroll.scrollTop,
    });
    setConnectDrag({ from, ...at(event) });
    const move = (e: PointerEvent) => setConnectDrag({ from, ...at(e) });
    const up = (e: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setConnectDrag(null);
      const target = document.elementFromPoint(e.clientX, e.clientY)
        ?.closest<HTMLElement>("[data-node-id]")?.dataset.nodeId;
      if (target && target !== from) reparent(target, from);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  // ---- Draft (join configuration) ----
  const draftNode = draft ? ids.get(draft.nodeId) : undefined;
  const draftParent = draftNode ? ids.get(draftNode.parentId ?? "") : undefined;
  const setDraftPatch = (patch: Partial<LinkDraft>) =>
    setDraft((d) => (d ? { ...d, ...patch, edited: true, suggestedBy: "conditions" in patch ? undefined : d.suggestedBy } : d));
  const applyDraft = () => {
    if (!draft) return;
    patchNode(draft.nodeId, {
      how: draft.how, touched: true, filterRows: draft.filterRows,
      conditions: draft.conditions.filter((c) => !isBlankCond(c)),
    });
    setDraft(null); setSelection(null);
  };
  const cancelDraft = () => { setDraft(null); setSelection(null); };
  useEffect(() => {
    if (!selection) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !(e.target as Element)?.closest?.("[role=combobox], [role=listbox]")) {
        setDraft(null); setSelection(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selection]);

  // ---- Problems and disabled reasons ----
  const stepIndex = new Map(steps.map((n, i) => [n.id, i]));
  const linkName = (n: CanvasNode) => `${ids.get(n.parentId ?? "")?.title ?? "?"} → ${n.title}`;
  const problemsFor = (n: CanvasNode): string[] => {
    const i = stepIndex.get(n.id);
    const server = i === undefined ? undefined : validation?.steps[i];
    const out = [...(local.get(n.id) ?? [])];
    if (server) {
      out.push(...server.problems.filter((p) => !/add at least one join condition/i.test(p)));
      server.conditions.forEach((c) => { if (c.problem) out.push(c.problem); });
      (server.filters ?? []).forEach((f) => { if (f.problem) out.push(f.problem); });
    }
    if (n.touched && !n.conditions.some(isCompleteCond)) out.push("Choose at least one pair of matching fields.");
    return [...new Set(out)];
  };
  const shownProblems = steps.filter((n) => n.touched).map((n) => ({ node: n, problems: problemsFor(n) }))
    .filter((p) => p.problems.length);
  const baseProblems = (validation?.base_filters ?? []).map((f) => f.problem).filter(Boolean) as string[];
  const disabledReason = ((): string | null => {
    if (!root) return "Drag a table onto the canvas to start.";
    if (!ready) return "Waiting for tables to open.";
    if (!steps.length) return "Add a second table to join.";
    const pendingBase = root.filterRows.find((r) => filterProblem(r));
    if (pendingBase) return `${root.title}: ${filterProblem(pendingBase)}`;
    for (const n of steps) {
      if (!n.conditions.some(isCompleteCond)) return `Choose matching fields for ${linkName(n)}.`;
      const lp = local.get(n.id);
      if (lp?.length) return `${linkName(n)}: ${lp[0]}`;
      const fp = n.filterRows.find((r) => filterProblem(r));
      if (fp) return `${n.title}: ${filterProblem(fp)}`;
    }
    if (validation?.ok === false) return "Fix the problems listed under the canvas.";
    return null;
  })();
  const needsGrowthConfirm = Boolean(preview?.large_growth) && !growthConfirmed;
  const footerReason = disabledReason
    ?? (crossSource && !allowLoaded ? "Allow the full-source cross-source join to continue." : null)
    ?? (needsGrowthConfirm ? "Confirm the large result to continue." : null)
    ?? (mode === "extract" && (!extractResource || !extractTable.trim()) ? "Choose where to save the extract." : null)
    ?? (busy || running ? "Waiting for the current operation to finish." : null);
  const canRun = footerReason === null;
  const canPreview = disabledReason === null && !(crossSource && !allowLoaded) && !previewing && !running;

  // ---- Preview, run, save ----
  const runPreview = async () => {
    if (!plan) return;
    const controller = new AbortController();
    previewAbort.current = controller;
    const requestId = ++previewRequest.current;
    setPreviewing(true); setPreviewErr(""); setPreviewJob(null); setGridTable("result"); setGridOpen(true);
    try {
      const result = await api.previewJoin(plan.baseId, plan.steps, sentAllowLoaded, controller.signal,
        (job) => { if (requestId === previewRequest.current) setPreviewJob({ job, receivedAt: Date.now() }); },
        plan.baseFilters);
      if (requestId === previewRequest.current) setPreview(result);
    } catch (e) {
      if (requestId === previewRequest.current) setPreviewErr((e as Error).message);
    } finally {
      if (previewAbort.current === controller) previewAbort.current = null;
      if (requestId === previewRequest.current) { setPreviewing(false); setPreviewJob(null); }
    }
  };

  const create = async () => {
    if (!plan || !canRun) return;
    setError(""); setStatus("");
    const title = name.trim() || "Joined table";
    if (mode === "live") {
      await onJoin({ baseId: plan.baseId, steps: plan.steps, allowLoaded: sentAllowLoaded,
        baseFilters: plan.baseFilters, title, extraInputs: inputs, fromCanvas: true });
      return;
    }
    setRunning(true);
    let joinedId = "";
    try {
      setStatus("Joining…");
      const joined = await api.join(plan.baseId, plan.steps, sentAllowLoaded, plan.baseFilters);
      joinedId = joined.dataset_id;
      setStatus(`Saving the extract to ${extractResource}…`);
      const out = await api.materialize(joinedId, extractResource, extractTable.trim());
      const target = auroraTargets.find((s) => s.id === extractResource);
      const ref = { kind: target?.kind ?? "aurora", resource_id: extractResource, table: out.table } as SourceRef;
      const opened = await api.openSourceRef(ref);
      onOpenResult(opened, title, ref);
      setStatus(`Saved ${out.rows.toLocaleString()} rows to ${out.table}.`);
    } catch (e) {
      setError(`Extract failed: ${(e as Error).message}`);
      setStatus("");
    } finally {
      if (joinedId) void api.closeDataset(joinedId).catch(() => undefined);
      setRunning(false);
    }
  };

  const saveRecipe = toJoinRef(nodes, sentAllowLoaded);
  const saveReason = !ready ? "Add tables to the canvas first." : "reason" in saveRecipe ? saveRecipe.reason : null;
  const save = () => {
    if ("reason" in saveRecipe) return;
    const entry = { name: name.trim() || "New join", ref: saveRecipe.ref, savedAt: new Date().toISOString() };
    try { localStorage.setItem(SAVED_KEY, JSON.stringify(entry)); } catch { /* storage disabled */ }
    setSaved(entry);
    setStatus(`Saved “${entry.name}” in this browser.`);
  };
  const cancel = () => { clearCanvas(); setName("New join"); onClose(); };

  const copySql = async () => {
    const statement = validation?.generated_sql?.copyable_sql;
    if (!statement) return;
    try { await navigator.clipboard.writeText(statement); setCopyStatus("SQL copied."); }
    catch { setCopyStatus("Clipboard access is unavailable."); }
  };

  // ---- Grid data ----
  const gridNode = gridTable === "result" ? undefined : ids.get(gridTable);
  useEffect(() => {
    if (!gridNode?.dataset) { setTablePreview(null); return; }
    let current = true;
    const datasetId = gridNode.dataset.id, nodeIdNow = gridNode.id;
    setTablePreview({ nodeId: nodeIdNow, columns: [], data: [], loading: true });
    fetch(`/api/datasets/${encodeURIComponent(datasetId)}/query`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filters: [], charts: [], page: 0, page_size: Math.min(1000, rowLimit),
        entity_column: null, refresh: false, sort: null }),
    }).then(async (r) => {
      const body = await r.json();
      if (!r.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Preview failed (${r.status}).`);
      if (current) setTablePreview({ nodeId: nodeIdNow, columns: body.rows.columns, data: body.rows.data, total: body.total });
    }).catch((e) => { if (current) setTablePreview({ nodeId: nodeIdNow, columns: [], data: [], error: (e as Error).message }); });
    return () => { current = false; };
  }, [gridNode?.id, gridNode?.dataset?.id, rowLimit]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Output fields of the grid table: name, table node, remote field, profile. */
  const fieldRows = (): { field: string; node: CanvasNode; remote: string; column?: ColumnProfile; included: boolean }[] => {
    const list = gridNode ? [gridNode] : root ? [root, ...steps] : [];
    return list.flatMap((n) => {
      if (n.parentId && !addsColumns(n.how) && !gridNode) return [];
      const cols = n.dataset?.columns ?? [];
      return cols.map((c) => ({
        field: n.parentId && !gridNode ? `${n.alias.trim()}${ARROW}${c.name}` : c.name,
        node: n, remote: c.name, column: c,
        included: !n.parentId || n.columns === null || n.columns.includes(c.name),
      }));
    });
  };
  const fields = fieldRows();
  const visibleFields = fields.filter((f) => !fieldSearch.trim()
    || `${f.field} ${f.node.title}`.toLowerCase().includes(fieldSearch.trim().toLowerCase()));
  const toggleField = (n: CanvasNode, remote: string, on: boolean) => {
    const all = n.dataset?.columns.map((c) => c.name) ?? [];
    const picked = n.columns ?? all;
    const next = on ? all.filter((c) => c === remote || picked.includes(c)) : picked.filter((c) => c !== remote);
    patchNode(n.id, { columns: next.length === all.length ? null : next });
  };
  const setAllFields = (on: boolean) => {
    const touched = new Set(visibleFields.filter((f) => f.node.parentId).map((f) => f.node.id));
    setNodes((prev) => prev.map((n) => {
      if (!touched.has(n.id)) return n;
      const all = n.dataset?.columns.map((c) => c.name) ?? [];
      const shown = new Set(visibleFields.filter((f) => f.node.id === n.id).map((f) => f.remote));
      const picked = new Set(n.columns ?? all);
      shown.forEach((c) => (on ? picked.add(c) : picked.delete(c)));
      const next = all.filter((c) => picked.has(c));
      return { ...n, columns: next.length === all.length ? null : next };
    }));
  };

  const resultColumn = (name: string): { table: string; field: string; column?: ColumnProfile } => {
    if (gridNode) return { table: gridNode.title, field: name, column: gridNode.dataset?.columns.find((c) => c.name === name) };
    const step = steps.find((n) => name.startsWith(`${n.alias.trim()}${ARROW}`));
    const owner = step ?? root;
    const field = step ? name.slice(step.alias.trim().length + ARROW.length) : name;
    return { table: owner?.title ?? "", field, column: owner?.dataset?.columns.find((c) => c.name === field) };
  };

  const filterCount = nodes.reduce((sum, n) => sum + sentFilters(n.filterRows, n.dataset?.columns ?? []).length, 0);
  const lastStat = preview?.large_growth ? undefined : preview?.steps[preview.steps.length - 1];
  const resultRows = lastStat ? `${lastStat.estimated ? "~" : ""}${lastStat.rows.toLocaleString()} rows`
    + (preview?.growth_total != null && preview.growth_total !== 1 ? ` (${preview.growth_total}× the start table)` : "")
    : null;
  const estimate = root?.rows != null ? `${root.title}: ${root.rowsEstimated ? "~" : ""}${root.rows.toLocaleString()} rows` : null;

  // ---- Layout ----
  const { pos, width, height } = layout(nodes);
  const selectedLink = selection?.type === "link" ? selection.id : null;
  const selectedNode = selection?.type === "node" ? ids.get(selection.id) : undefined;
  const reasonId = "jc-reason";

  const tableGroups = useMemo(() => {
    const needle = tableSearch.trim().toLowerCase();
    const shown = tables.filter((t) => !needle || t.name.toLowerCase().includes(needle));
    const groups = new Map<string, TableInfo[]>();
    for (const t of shown) {
      const key = t.schema ?? "";
      groups.set(key, [...(groups.get(key) ?? []), t]);
    }
    return [...groups.entries()];
  }, [tables, tableSearch]);
  const tabsShown = datasets.filter((d) => !tableSearch.trim()
    || d.title.toLowerCase().includes(tableSearch.trim().toLowerCase()));
  const full = nodes.length > MAX_JOINED;
  const addTarget = selection?.type === "node" ? selection.id : selection?.type === "link" ? selection.id : undefined;

  const nodeFilterEditor = (n: CanvasNode) => (
    <FilterEditor rows={n.filterRows} columns={n.dataset?.columns ?? []} table={n.title}
                  label={n.parentId ? n.title : "Start table"}
                  checks={n.parentId ? validation?.steps[stepIndex.get(n.id) ?? -1]?.filters : validation?.base_filters}
                  disabled={busy || running} onChange={(rows) => patchNode(n.id, { filterRows: rows })} />
  );

  return (
    <div className="jc" aria-label="Visual join canvas">
      {/* Top bar */}
      <div className="jc-topbar">
        <label className="jc-name">
          <span className="sr-only">Join name</span>
          <input type="text" aria-label="Join name" value={name} maxLength={128}
                 onChange={(e) => setName(e.target.value)} />
        </label>
        <div className="jc-mode" role="radiogroup" aria-label="Connection">
          <span className="jc-label">Connection</span>
          <label title="The joined tab queries its sources; same-database Aurora joins run in the database.">
            <input type="radio" name="jc-mode" checked={mode === "live"} onChange={() => setMode("live")} /> Live
          </label>
          <label title={extractReason ?? "Save the joined rows as a new database table, then open that table."}
                 className={extractReason ? "disabled" : undefined}>
            <input type="radio" name="jc-mode" checked={mode === "extract"} disabled={Boolean(extractReason)}
                   onChange={() => setMode("extract")} /> Extract
          </label>
        </div>
        {mode === "extract" && (
          <div className="jc-extract">
            <select aria-label="Extract database" value={extractResource} onChange={(e) => setExtractResource(e.target.value)}>
              {auroraTargets.map((s) => <option key={s.id} value={s.id}>{s.label || s.id}</option>)}
            </select>
            <input type="text" aria-label="Extract table name" value={extractTable} maxLength={63}
                   onChange={(e) => { setExtractTable(e.target.value); setExtractTableEdited(true); }} />
          </div>
        )}
        <div className="jc-filters-summary">
          <span className="jc-label">Filters</span> <strong>{filterCount}</strong>
          <button type="button" className="link" disabled={!ready} onClick={() => {
            setSelection(null); setDraft(null);
            setFilterTable(filterTable && ids.has(filterTable) ? filterTable : root?.id ?? ""); setFiltersOpen(true); }}>
            Add
          </button>
        </div>
        <div className="jc-spacer" />
        <button type="button" className="quiet" disabled={!validation?.generated_sql}
                title={validation?.generated_sql ? "Show the SQL Studio runs" : "SQL appears once the join is valid"}
                onClick={() => setShowSql(true)}>Show SQL</button>
        <button type="button" className="quiet" disabled={!canPreview} onClick={() => void runPreview()}
                aria-describedby={footerReason ? reasonId : undefined}>{previewing ? "Previewing…" : "Preview"}</button>
        <button type="button" className="quiet" onClick={cancel}>Cancel</button>
        <button type="button" disabled={Boolean(saveReason)} title={saveReason ?? "Keep this join model in this browser"}
                onClick={save}>Save</button>
        <button type="button" className="primary" disabled={!canRun} onClick={() => void create()}
                aria-describedby={footerReason ? reasonId : undefined}>
          {busy || running ? "Working…" : "Save & open in Explore"}
        </button>
      </div>

      <div className="jc-body">
        {/* Connections pane */}
        <aside className="jc-connections" aria-label="Connections">
          <div className="jc-pane-head">
            <h3>Connections</h3>
            <button type="button" className="link" onClick={onAddSource}>Add</button>
          </div>
          <ul className="jc-sources" aria-label="Datasources">
            {sources.map((s) => {
              const key = `${s.kind}:${s.id}`;
              return (
                <li key={key}>
                  <button type="button" aria-pressed={key === sourceKey}
                          className={`jc-source${key === sourceKey ? " on" : ""}`}
                          onClick={() => { setSourceKey(key); setTableSearch(""); }}>
                    <span className="jc-source-name">{s.label || s.id}</span>
                    <small>{SOURCE_KIND_LABEL[s.kind] ?? s.kind}</small>
                  </button>
                </li>
              );
            })}
            {!sources.length && <li className="settings-hint">Waiting for workspace datasources…</li>}
          </ul>
          <div className="jc-pane-head">
            <h3>Tables</h3>
            <button type="button" className="link" disabled={!selectedSource || tablesLoading}
                    title="List tables again" onClick={() => setTablesRefresh((n) => n + 1)}>Refresh</button>
          </div>
          <div className="jc-search">
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
              <circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5L14 14" />
            </svg>
            <input ref={searchRef} type="search" aria-label="Search tables" placeholder="Search tables"
                   value={tableSearch} onChange={(e) => setTableSearch(e.target.value)} />
          </div>
          <div className="jc-table-list">
            {tablesLoading && <div className="settings-hint" role="status">Listing tables…</div>}
            {tablesError && <div className="join-error" role="alert">{tablesError}</div>}
            {tableGroups.map(([schema, items]) => (
              <div key={schema} role="group" aria-label={schema ? `Schema ${schema}` : "Tables"}>
                {schema && <div className="jc-group-label">{schema}</div>}
                <ul>
                  {items.map((t) => (
                    <li key={t.name} className="jc-table-item" draggable={!full}
                        data-table={t.name}
                        onDragStart={(e) => startDrag(e, { type: "table", sourceKey, name: t.name })}>
                      <TableIcon />
                      <span className="jc-table-name" title={[t.detail, tableStats(t)].filter(Boolean).join(" · ")}>
                        {t.table ?? t.name}
                      </span>
                      <button type="button" className="quiet jc-add" disabled={full}
                              aria-label={`Add ${t.name} to canvas`}
                              title={full ? `A join can include up to ${MAX_JOINED} additional tables.`
                                : nodes.length ? "Join this table to the selected table (or the start table)" : "Start the join with this table"}
                              onClick={() => void addItem({ type: "table", sourceKey, name: t.name }, addTarget)}>+</button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            {tabsShown.length > 0 && (
              <div role="group" aria-label="Open tabs">
                <div className="jc-group-label">Open tabs</div>
                <ul>
                  {tabsShown.map((d) => (
                    <li key={d.id} className="jc-table-item" draggable={!full} data-tab={d.id}
                        onDragStart={(e) => startDrag(e, { type: "tab", datasetId: d.id })}>
                      <TableIcon />
                      <span className="jc-table-name" title={d.source}>{d.title}</span>
                      <button type="button" className="quiet jc-add" disabled={full}
                              aria-label={`Add ${d.title} to canvas`}
                              onClick={() => void addItem({ type: "tab", datasetId: d.id }, addTarget)}>+</button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </aside>

        <div className="jc-main">
          {/* Canvas */}
          <section className="jc-canvas-wrap" aria-label="Join canvas">
            <div className="jc-canvas-head">
              <button type="button" className="quiet" onClick={() => { searchRef.current?.focus(); searchRef.current?.select(); }}>
                + Add data
              </button>
              <span className="settings-hint">
                {nodes.length ? "Drop a table on a card to join it to that table; drag a card's handle onto another card to move a join." : ""}
              </span>
              {status && <span className="jc-status" role="status">{status}</span>}
            </div>
            <div ref={canvasRef} className={`jc-canvas${canvasHover ? " drop" : ""}`} data-testid="join-canvas"
                 onDragOver={onDragOver} onDragLeave={(e) => {
                   if (!e.currentTarget.contains(e.relatedTarget as Node | null)) { setCanvasHover(false); setHoverNode(null); }
                 }} onDrop={onDrop}
                 onClick={(e) => { if (e.target === e.currentTarget) { setSelection(null); setDraft(null); } }}>
              {!nodes.length && (
                <div className="jc-empty">
                  <div className="jc-empty-title">Drag a table here to start</div>
                  <ol>
                    <li>Pick a datasource on the left and drag a table onto the canvas (or press <strong>+</strong>).</li>
                    <li>Drag more tables onto a card to join them to it.</li>
                    <li>Click the join badge on a link to choose the join type and matching fields.</li>
                  </ol>
                  {saved && (
                    <button type="button" className="quiet" onClick={() => void reconstruct(saved.ref, saved.name)}>
                      Reopen saved join “{saved.name}”
                    </button>
                  )}
                </div>
              )}
              {nodes.length > 0 && (
                <div className="jc-stage" style={{ width, height }}>
                  <svg className="jc-links" width={width} height={height} aria-hidden>
                    {steps.map((n) => {
                      const from = pos.get(n.parentId!), to = pos.get(n.id);
                      if (!from || !to) return null;
                      const { d } = connector(from, to);
                      const bad = n.touched && problemsFor(n).length > 0;
                      return <path key={n.id} d={d}
                                   className={`jc-link${selectedLink === n.id ? " on" : ""}${bad ? " bad" : ""}${!n.conditions.some(isCompleteCond) ? " pending" : ""}`} />;
                    })}
                    {connectDrag && pos.get(connectDrag.from) && (
                      <line className="jc-link-draft" x1={pos.get(connectDrag.from)!.x + NODE_W}
                            y1={pos.get(connectDrag.from)!.y + NODE_H / 2} x2={connectDrag.x} y2={connectDrag.y} />
                    )}
                  </svg>
                  {steps.map((n) => {
                    const from = pos.get(n.parentId!), to = pos.get(n.id);
                    if (!from || !to) return null;
                    const { badge } = connector(from, to);
                    const parent = ids.get(n.parentId!)!;
                    const keyless = !n.conditions.some(isCompleteCond);
                    const bad = n.touched && problemsFor(n).length > 0;
                    return (
                      <button key={n.id} type="button"
                              className={`jc-badge${selectedLink === n.id ? " on" : ""}${bad ? " bad" : ""}${keyless ? " pending" : ""}`}
                              style={{ left: badge.x, top: badge.y }}
                              aria-pressed={selectedLink === n.id}
                              aria-label={`Join ${parent.title} to ${n.title}: ${HOW_LABEL[n.how]} join${keyless ? ", needs matching fields" : ""}. Edit join`}
                              title={`${HOW_LABEL[n.how]} join${keyless ? " · choose matching fields" : ""}`}
                              onClick={() => (selectedLink === n.id ? cancelDraft() : openLink(n.id))}>
                        <Venn how={n.how} />
                        {keyless && <span className="jc-badge-dot" aria-hidden />}
                      </button>
                    );
                  })}
                  {nodes.map((n) => {
                    const p = pos.get(n.id);
                    if (!p) return null;
                    const cols = n.dataset?.columns.length ?? n.columnCount;
                    const isRoot = !n.parentId;
                    return (
                      <div key={n.id} data-node-id={n.id} role="group" aria-label={`${n.title} table`}
                           className={`jc-node${selection?.id === n.id && selection.type === "node" ? " on" : ""}${hoverNode === n.id ? " drop" : ""}${isRoot ? " root" : ""}${n.dataset ? "" : " opening"}`}
                           style={{ left: p.x, top: p.y, width: NODE_W, height: NODE_H }}>
                        <button type="button" className="jc-node-main"
                                aria-label={`${n.title}${isRoot ? " (start table)" : ""}. Table details`}
                                aria-pressed={selection?.type === "node" && selection.id === n.id}
                                onClick={() => { setDraft(null); setSelection(selection?.type === "node" && selection.id === n.id ? null : { type: "node", id: n.id }); }}>
                          <span className="jc-node-title"><TableIcon /><span>{n.title}</span>
                            {n.parentId && n.alias.trim() && n.alias.trim() !== n.title && <span className="jc-node-alias">as {n.alias.trim()}</span>}
                          </span>
                          <span className="jc-node-meta">
                            <span className="jc-chip">{n.badge}</span>
                            {isRoot && <span className="jc-chip jc-chip-root">Start</span>}
                            {!n.dataset ? <span>Opening…</span> : <span>
                              {n.rows != null ? `${n.rowsEstimated ? "~" : ""}${n.rows.toLocaleString()} rows · ` : ""}
                              {cols != null ? `${cols} columns` : ""}
                            </span>}
                          </span>
                        </button>
                        <button type="button" className="quiet jc-node-remove"
                                aria-label={isRoot ? `Remove ${n.title} and every joined table` : `Remove ${n.title}`}
                                title={isRoot ? "Remove every table" : subtree(nodes, n.id).size > 1 ? "Remove this table and the tables joined to it" : "Remove this table"}
                                onClick={() => (isRoot ? clearCanvas() : removeNode(n.id))}>✕</button>
                        {n.dataset && addsColumns(n.how) && (
                          <span className="jc-handle" aria-hidden title="Drag onto another card to join it to this table"
                                onPointerDown={(e) => startConnect(e, n.id)} />
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </section>

          {/* Status bar: validation, estimates, consent */}
          <div className="jc-statusbar" aria-label="Join status">
            {(validation?.engine) && (
              <span className={`join-engine ${validation.engine}`} title={validation.engine_reason ?? ""}>
                {validation.engine === "aurora" ? "runs in Aurora" : "runs in memory"}
              </span>
            )}
            {estimate && <span className="settings-hint">{estimate}</span>}
            {resultRows && <span className={`join-result-rows${preview?.large_growth ? " join-warn" : ""}`}>Result: {resultRows}</span>}
            {preview?.large_growth && (
              <label className="join-growth-confirm join-warn">
                <input type="checkbox" checked={growthConfirmed} onChange={(e) => setGrowthConfirmed(e.target.checked)} />
                Run anyway: {preview.steps[preview.steps.length - 1]?.rows.toLocaleString()} rows ({preview.growth_total}× the start table)
              </label>
            )}
            {crossSource && (
              <label className="jc-consent join-warn" title={allowLoaded
                ? "Studio will scan each complete source and stage the join on disk. The operation stops above 1 TB."
                : "Cross-source joins require your approval to scan complete sources."}>
                <input type="checkbox" checked={allowLoaded} disabled={busy || previewing || running}
                       onChange={(e) => setAllowLoaded(e.target.checked)} />
                Allow full-source cross-source join
              </label>
            )}
            <span className="jc-spacer" />
            <span className="join-disabled-reason" id={reasonId} aria-live="polite">{footerReason ?? ""}</span>
          </div>
          {(shownProblems.length > 0 || baseProblems.length > 0 || (validation?.problems.length ?? 0) > 0 || error) && (
            <ul className="jc-problems" aria-label="Join problems">
              {error && <li className="join-error" role="alert">{error}</li>}
              {(validation?.problems ?? []).map((p) => <li key={p} className="join-error">{p}</li>)}
              {baseProblems.map((p) => <li key={p} className="join-error">{root?.title}: {p}</li>)}
              {shownProblems.map(({ node, problems }) => (
                <li key={node.id} className="join-error">
                  <button type="button" className="link" onClick={() => openLink(node.id)}>{linkName(node)}</button>
                  : {problems.join(" ")}
                </li>
              ))}
            </ul>
          )}
          {!preview && (validation?.capped_inputs.length ?? 0) > 0 && (
            <div className="settings-hint join-warn">
              Runs in memory on the loaded rows of {validation!.capped_inputs.join(", ")}, which hit the row cap — results may be incomplete.
            </div>
          )}

          {/* Bottom: join configuration, table details, or data grid */}
          {draft && draftNode && draftParent ? (
            <section className="jc-bottom jc-config" aria-label="Join configuration">
              <div className="jc-bottom-head">
                <h3>Join configuration</h3>
                <span className="settings-hint">{draftParent.title} → {draftNode.title}</span>
                <span className="jc-spacer" />
                <button type="button" className="quiet" aria-label="Close join configuration" onClick={cancelDraft}>✕</button>
              </div>
              <div className="jc-config-body">
                <div className="jc-clauses" role="group" aria-label="Join clauses">
                  <div className="jc-section-title">Join clauses</div>
                  <div className="jc-clause jc-clause-head" aria-hidden>
                    <span>{draftParent.title}</span><span /><span>{draftNode.title}</span><span />
                  </div>
                  {draft.conditions.map((c, k) => {
                    const leftNode = ids.get(c.leftNode) ?? draftParent;
                    const leftOptions = offeredColumns(draftParent).map((col) => ({
                      id: `${draftParent.id}::${col}`, label: col,
                      hint: KIND_LABEL[colKind(draftParent.dataset?.columns.find((x) => x.name === col))] }));
                    if (c.left && leftNode.id !== draftParent.id)
                      leftOptions.unshift({ id: `${leftNode.id}::${c.left}`, label: `${leftNode.title} · ${c.left}`, hint: "earlier table" });
                    const rightOptions = (draftNode.dataset?.columns ?? []).map((col) => ({
                      id: col.name, label: col.name, hint: KIND_LABEL[colKind(col)] }));
                    const setCond = (patch: Partial<CanvasCond>) => setDraftPatch({
                      conditions: draft.conditions.map((x, m) => (m === k ? { ...x, ...patch } : x)) });
                    const lk = c.left ? colKind(leftNode.dataset?.columns.find((x) => x.name === c.left)) : null;
                    const rk = c.right ? colKind(draftNode.dataset?.columns.find((x) => x.name === c.right)) : null;
                    return (
                      <Fragment key={k}>
                        <div className="jc-clause">
                          <Combobox label={`Left field, clause ${k + 1}`} value={c.left ? `${leftNode.id}::${c.left}` : ""}
                                    options={leftOptions} placeholder={`Search ${draftParent.title} fields…`}
                                    onChange={(id) => { const at = id.indexOf("::"); setCond({ leftNode: id.slice(0, at), left: id.slice(at + 2) }); }} />
                          <select className="join-op" aria-label={`Operator, clause ${k + 1}`} value={c.op}
                                  onChange={(e) => setCond({ op: e.target.value as JoinOp })}>
                            {OPS.map((o) => <option key={o}>{o}</option>)}
                          </select>
                          <Combobox label={`Right field, clause ${k + 1}`} value={c.right} options={rightOptions}
                                    placeholder={`Search ${draftNode.title} fields…`} onChange={(id) => setCond({ right: id })} />
                          <button type="button" className="quiet" aria-label={`Remove clause ${k + 1}`}
                                  disabled={draft.conditions.length === 1 && isBlankCond(c)}
                                  onClick={() => setDraftPatch({ conditions: draft.conditions.length === 1
                                    ? [{ leftNode: draftParent.id, left: "", op: "=", right: "" }]
                                    : draft.conditions.filter((_, m) => m !== k) })}>✕</button>
                        </div>
                        {lk && rk && lk !== rk && (
                          <div className="join-check settings-hint">{c.left} is {KIND_LABEL[lk]} and {c.right} is {KIND_LABEL[rk]}; Studio compares them after converting.</div>
                        )}
                      </Fragment>
                    );
                  })}
                  <div className="join-tools">
                    <button type="button" className="link"
                            disabled={draft.conditions.some(isBlankCond) || draft.conditions.length >= 12}
                            onClick={() => setDraftPatch({ conditions: [...draft.conditions,
                              { leftNode: draftParent.id, left: "", op: "=", right: "" }] })}>
                      + Add a new join clause
                    </button>
                  </div>
                  {draft.suggestedBy && (
                    <div className="settings-hint jc-suggested" role="status">
                      Suggested from {draft.suggestedBy}. Check the fields, then Apply.
                    </div>
                  )}
                  {(() => {
                    const found = ideasFor(draftNode);
                    const chips = [
                      ...(found?.recommendations ?? []).map((r) => ({
                        key: `r-${r.method}-${r.keys.map((x) => x.left + x.right).join()}`,
                        label: `${r.keys.map((x) => `${x.left} = ${x.right}`).join(" and ")} · ${r.method === "foreign_key" ? "foreign key" : r.method === "exact_name" ? "matching names" : "Jev suggestion"}`,
                        conditions: r.keys.map((x): CanvasCond => ({ leftNode: draftParent.id, left: x.left, op: "=", right: x.right })),
                      })),
                      ...(found?.suggestions ?? []).map((s) => ({
                        key: `s-${s.left}-${s.right}`, label: `${s.left} = ${s.right} · ${Math.round(s.overlap * 100)}% match`,
                        conditions: [{ leftNode: draftParent.id, left: s.left, op: "=" as JoinOp, right: s.right }],
                      })),
                    ].filter((chip) => chip.conditions.every((x) => offeredColumns(draftParent).includes(x.left)));
                    return chips.length > 0 && (
                      <div className="join-tools">
                        <span className="settings-hint">Suggested keys:</span>
                        {chips.map((chip) => (
                          <button key={chip.key} type="button" className="chip"
                                  onClick={() => setDraftPatch({ conditions: chip.conditions })}>{chip.label}</button>
                        ))}
                      </div>
                    );
                  })()}
                  <FilterEditor rows={draft.filterRows} columns={draftNode.dataset?.columns ?? []} table={draftNode.title}
                                label={draftNode.title}
                                checks={JSON.stringify(draft.filterRows) === JSON.stringify(draftNode.filterRows)
                                  ? validation?.steps[stepIndex.get(draftNode.id) ?? -1]?.filters : undefined}
                                disabled={busy || running} onChange={(rows) => setDraftPatch({ filterRows: rows })} />
                </div>
                <div className="jc-types" role="group" aria-label="Join type">
                  <div className="jc-section-title">Join type</div>
                  <div className="jc-type-buttons" role="radiogroup" aria-label="Join type">
                    {MAIN_HOWS.map((h) => (
                      <button key={h.id} type="button" role="radio" aria-checked={draft.how === h.id}
                              className={`jc-how${draft.how === h.id ? " on" : ""}`}
                              onClick={() => setDraftPatch({ how: h.id })}>
                        <Venn how={h.id} /><span>{h.label}</span>
                      </button>
                    ))}
                  </div>
                  <details className="jc-more" open={draft.how === "semi" || draft.how === "anti"}>
                    <summary>More</summary>
                    <div className="jc-type-buttons small" role="radiogroup" aria-label="Match-only join type">
                      {MORE_HOWS.map((h) => (
                        <button key={h.id} type="button" role="radio" aria-checked={draft.how === h.id}
                                className={`jc-how${draft.how === h.id ? " on" : ""}`}
                                onClick={() => setDraftPatch({ how: h.id })}>
                          <Venn how={h.id} /><span>{h.label}</span>
                        </button>
                      ))}
                    </div>
                  </details>
                  <p className="jc-explain" aria-live="polite">{explain(draft.how, draftParent.title, draftNode.title)}</p>
                </div>
              </div>
              <div className="jc-bottom-foot">
                <button type="button" className="quiet jc-danger" onClick={() => removeNode(draftNode.id)}>
                  Remove {draftNode.title} from the join
                </button>
                <span className="jc-spacer" />
                <button type="button" className="quiet" onClick={cancelDraft}>Cancel</button>
                <button type="button" className="primary" onClick={applyDraft}
                        disabled={draft.conditions.some((c) => !isBlankCond(c) && !isCompleteCond(c))}
                        title={draft.conditions.some((c) => !isBlankCond(c) && !isCompleteCond(c)) ? "Finish or remove the incomplete join clause" : undefined}>
                  Apply
                </button>
              </div>
            </section>
          ) : selectedNode ? (
            <section className="jc-bottom jc-details" aria-label={`${selectedNode.title} details`}>
              <div className="jc-bottom-head">
                <h3>{selectedNode.title}</h3>
                <span className="jc-chip">{selectedNode.badge}</span>
                {!selectedNode.parentId && <span className="jc-chip jc-chip-root">Start table</span>}
                <span className="settings-hint">{selectedNode.dataset?.source}</span>
                <span className="jc-spacer" />
                <button type="button" className="quiet" aria-label="Close table details" onClick={() => setSelection(null)}>✕</button>
              </div>
              <div className="jc-details-body">
                <div>
                  {selectedNode.parentId ? (<>
                    <label className="jc-field">Name joined columns as
                      <input type="text" value={selectedNode.alias} maxLength={64}
                             onChange={(e) => patchNode(selectedNode.id, { alias: e.target.value })} />
                    </label>
                    <label className="jc-field">Join to
                      <select aria-label={`Join ${selectedNode.title} to`} value={selectedNode.parentId}
                              onChange={(e) => reparent(selectedNode.id, e.target.value)}>
                        {nodes.filter((n) => !subtree(nodes, selectedNode.id).has(n.id)).map((n) => (
                          <option key={n.id} value={n.id} disabled={Boolean(n.parentId) && !addsColumns(n.how)}>
                            {n.title}{n.parentId ? "" : " (start table)"}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button type="button" className="link" onClick={() => openLink(selectedNode.id)}>Edit join with {ids.get(selectedNode.parentId)?.title}</button>
                  </>) : <p className="settings-hint">The start table keeps all its columns; the other tables are joined to it.</p>}
                  {nodeFilterEditor(selectedNode)}
                </div>
                <div className="jc-col-picker" role="group" aria-label={`${selectedNode.title} columns`}>
                  <div className="jc-section-title">Columns</div>
                  {selectedNode.parentId && addsColumns(selectedNode.how) && (
                    <div className="join-tools">
                      <button type="button" className="link" onClick={() => patchNode(selectedNode.id, { columns: null })}>All</button>
                      <button type="button" className="link" onClick={() => patchNode(selectedNode.id, { columns: [] })}>None</button>
                    </div>
                  )}
                  <div className="jc-col-list">
                    {(selectedNode.dataset?.columns ?? []).map((c) => (
                      <label key={c.name} className="jc-col">
                        <input type="checkbox" disabled={!selectedNode.parentId || !addsColumns(selectedNode.how)}
                               checked={!selectedNode.parentId || (addsColumns(selectedNode.how) && (selectedNode.columns === null || selectedNode.columns.includes(c.name)))}
                               onChange={(e) => toggleField(selectedNode, c.name, e.target.checked)} />
                        <TypeIcon column={c} /> {c.name}
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            </section>
          ) : (
            <section className={`jc-bottom jc-grid${gridOpen ? "" : " collapsed"}`} aria-label="Data preview">
              <div className="jc-bottom-head">
                <label className="jc-grid-pick">
                  <span className="sr-only">Preview table</span>
                  <select aria-label="Preview table" value={gridTable} onChange={(e) => setGridTable(e.target.value)}>
                    <option value="result">Joined result</option>
                    {nodes.map((n) => <option key={n.id} value={n.id} disabled={!n.dataset}>{n.title}</option>)}
                  </select>
                </label>
                <span className="settings-hint" aria-live="polite">
                  {fields.filter((f) => f.included).length} fields
                  {gridNode ? (tablePreview?.total != null ? ` · ${tablePreview.total.toLocaleString()} rows` : "")
                    : resultRows ? ` · ${resultRows}` : ""}
                </span>
                <span className="jc-spacer" />
                <label className="jc-limit">Rows
                  <input type="number" min={1} max={1000} aria-label="Rows to show" value={rowLimitText}
                         onChange={(e) => setRowLimitText(e.target.value)}
                         onKeyDown={(e) => { if (e.key === "Enter") setRowLimit(Math.max(1, Math.min(1000, Number(rowLimitText) || 100))); }} />
                </label>
                <button type="button" className="quiet" onClick={() => setRowLimit(Math.max(1, Math.min(1000, Number(rowLimitText) || 100)))}>Apply</button>
                <button type="button" className="quiet jc-chevron" aria-expanded={gridOpen}
                        aria-label={gridOpen ? "Collapse data preview" : "Expand data preview"}
                        onClick={() => setGridOpen(!gridOpen)}>{gridOpen ? "▾" : "▸"}</button>
              </div>
              {gridOpen && (
                <div className="jc-grid-body">
                  <div className={`jc-fields${fieldsOpen ? "" : " folded"}`}>
                    <button type="button" className="quiet jc-fields-toggle" aria-expanded={fieldsOpen}
                            onClick={() => setFieldsOpen(!fieldsOpen)}>{fieldsOpen ? "◂ Fields" : "Fields ▸"}</button>
                    {fieldsOpen && (<>
                      <div className="jc-fields-tools">
                        <input type="search" aria-label="Search fields" placeholder="Search fields"
                               value={fieldSearch} onChange={(e) => setFieldSearch(e.target.value)} />
                        <button type="button" className="link" disabled={!visibleFields.some((f) => f.node.parentId)}
                                onClick={() => setAllFields(true)}>All</button>
                        <button type="button" className="link" disabled={!visibleFields.some((f) => f.node.parentId)}
                                onClick={() => setAllFields(false)}>None</button>
                      </div>
                      <table className="jc-fields-table" aria-label="Fields">
                        <thead><tr><th aria-label="Include" /><th>Type</th><th>Field name</th><th>Physical table</th><th>Remote field name</th></tr></thead>
                        <tbody>
                          {visibleFields.map((f) => (
                            <tr key={`${f.node.id}:${f.remote}`} className={f.included ? "" : "excluded"}>
                              <td><input type="checkbox" checked={f.included}
                                         disabled={!f.node.parentId || Boolean(gridNode)}
                                         aria-label={`Include ${f.field}`}
                                         title={!f.node.parentId ? "The start table keeps all its columns" : gridNode ? "Choose fields on the joined result" : undefined}
                                         onChange={(e) => toggleField(f.node, f.remote, e.target.checked)} /></td>
                              <td><TypeIcon column={f.column} /></td>
                              <td>{f.field}</td>
                              <td>{f.node.title}</td>
                              <td>{f.remote}</td>
                            </tr>
                          ))}
                          {!visibleFields.length && <tr><td colSpan={5} className="settings-hint">No fields yet.</td></tr>}
                        </tbody>
                      </table>
                    </>)}
                  </div>
                  <div className="jc-rows">
                    {gridNode ? (
                      tablePreview?.loading ? <div className="settings-hint" role="status">Loading rows…</div>
                        : tablePreview?.error ? <div className="join-error" role="alert">{tablePreview.error}</div>
                        : tablePreview && <PreviewTable columns={tablePreview.columns} rows={tablePreview.data.slice(0, rowLimit)}
                                                       describe={resultColumn} label={`${gridNode.title} rows`} />
                    ) : previewing ? (
                      <div className="join-preview-progress" role="status" aria-label="Preview progress">
                        {previewJob ? <JobProgress job={previewJob.job} receivedAt={previewJob.receivedAt} /> : "Previewing…"}
                        <button type="button" className="quiet" onClick={() => {
                          previewRequest.current += 1; previewAbort.current?.abort(); setPreviewing(false);
                          setPreviewErr("Preview cancelled."); }}>Cancel preview</button>
                      </div>
                    ) : preview ? (<>
                      <div className="join-funnel" aria-label="Row counts">
                        <span>{preview.sample_only
                          ? (preview.base_rows != null && preview.steps.some((st) => st.estimated)
                            ? `~${preview.base_rows.toLocaleString()} rows (estimated)` : "Sample preview · full counts not calculated")
                          : `${preview.base_rows?.toLocaleString() ?? "Unknown"} rows`}</span>
                        {preview.steps.map((st, i) => (
                          <span key={i}>→ {HOW_LABEL[steps[i]?.how ?? "left"].toLowerCase()} {steps[i]?.title}:{" "}
                            <strong>{st.estimated ? "~" : ""}{st.rows.toLocaleString()}</strong>
                            {st.fanout && <span className="join-warn join-fanout" title="Rows multiplied: the join key repeats on the joined side."> ×{st.growth} fan-out</span>}
                          </span>
                        ))}
                      </div>
                      {preview.notes.map((n) => <div key={n} className="settings-hint">{n}</div>)}
                      <PreviewTable columns={preview.columns} rows={preview.sample.slice(0, rowLimit)} describe={resultColumn}
                                    label="Joined result rows" />
                      {preview.sample.length < rowLimit && (
                        <div className="settings-hint">The joined preview is a sample of {preview.sample.length} rows; the full result opens in Explore.</div>
                      )}
                    </>) : (
                      <div className="jc-grid-empty settings-hint">
                        {previewErr ? <span className="join-error">{previewErr}</span>
                          : disabledReason ?? "Press Preview to see sample rows of the joined result."}
                        {!disabledReason && !previewErr && (
                          <button type="button" className="quiet" disabled={!canPreview} onClick={() => void runPreview()}>Preview</button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </section>
          )}
        </div>
      </div>

      {filtersOpen && (
        <div className="jc-dialog-backdrop" onClick={(e) => { if (e.target === e.currentTarget) setFiltersOpen(false); }}>
          <div className="jc-dialog" role="dialog" aria-modal="true" aria-label="Filters"
               onKeyDown={(e) => { if (e.key === "Escape") setFiltersOpen(false); }}>
            <div className="jc-bottom-head">
              <h3>Filters</h3>
              <span className="settings-hint">Keep only some rows of a table before it is joined.</span>
              <span className="jc-spacer" />
              <button type="button" className="quiet" aria-label="Close filters" onClick={() => setFiltersOpen(false)}>✕</button>
            </div>
            <label className="jc-field">Table
              <select aria-label="Filter table" value={filterTable} onChange={(e) => setFilterTable(e.target.value)}>
                {nodes.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.title} ({sentFilters(n.filterRows, n.dataset?.columns ?? []).length})
                  </option>
                ))}
              </select>
            </label>
            {ids.get(filterTable) && nodeFilterEditor(ids.get(filterTable)!)}
            <div className="jc-bottom-foot">
              <span className="jc-spacer" />
              <button type="button" className="primary" onClick={() => setFiltersOpen(false)}>Done</button>
            </div>
          </div>
        </div>
      )}

      {showSql && validation?.generated_sql && (
        <div className="jc-dialog-backdrop" onClick={(e) => { if (e.target === e.currentTarget) setShowSql(false); }}>
          <div className="jc-dialog wide" role="dialog" aria-modal="true" aria-label="Generated SQL dialog"
               onKeyDown={(e) => { if (e.key === "Escape") setShowSql(false); }}>
            <div className="jc-bottom-head">
              <h3>Generated SQL</h3>
              <span className="settings-hint">Engine: {validation.generated_sql.engine === "aurora" ? "Aurora" : "DuckDB"}</span>
              <span className="jc-spacer" />
              <button type="button" className="quiet" aria-label="Close SQL" onClick={() => setShowSql(false)}>✕</button>
            </div>
            {validation.generated_sql.staged_inputs?.length ? (
              <div className="settings-hint">Staged inputs: {validation.generated_sql.staged_inputs.join(", ")}</div>
            ) : null}
            <pre aria-label="Generated SQL" className="generated-sql-code">
              {validation.generated_sql.display_sql ?? validation.generated_sql.copyable_sql ?? validation.generated_sql.sql}
            </pre>
            <div className="jc-bottom-foot">
              {copyStatus && <span role="status">{copyStatus}</span>}
              {!validation.generated_sql.copyable_sql && validation.generated_sql.copyable_sql_error && (
                <span className="settings-hint">{validation.generated_sql.copyable_sql_error}</span>
              )}
              <span className="jc-spacer" />
              <button type="button" className="quiet" disabled={!validation.generated_sql.copyable_sql}
                      onClick={() => void copySql()}>Copy SQL</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function PreviewTable({ columns, rows, describe, label }: {
  columns: string[]; rows: unknown[][]; label: string;
  describe: (name: string) => { table: string; field: string; column?: ColumnProfile };
}) {
  return (
    <div className="jc-rows-scroll">
      <table className="jc-rows-table" aria-label={label}>
        <thead>
          <tr>
            {columns.map((c) => {
              const info = describe(c);
              return (
                <th key={c} scope="col">
                  <span className="jc-col-table">{info.table}</span>
                  <span className="jc-col-name"><TypeIcon column={info.column} /> {info.field}</span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r}>{row.map((v, c) => (
              <td key={c}>{v == null ? <span className="jc-null">null</span>
                : typeof v === "object" ? JSON.stringify(v) : String(v)}</td>
            ))}</tr>
          ))}
          {!rows.length && <tr><td colSpan={Math.max(1, columns.length)} className="settings-hint">No rows.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
