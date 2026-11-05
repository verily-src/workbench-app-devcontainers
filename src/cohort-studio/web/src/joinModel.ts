/** Visual join canvas model and its 1:1 mapping to the join request.
 *
 * The canvas is a tree. The root node is the join's base table; every other
 * node is one join step that joins its table to the rows built so far. A
 * step's conditions name a column of an earlier table by node id, so renaming
 * an alias never breaks a condition. Pure functions only (no React, no I/O). */
import type {
  Dataset, JoinFilter, JoinHow, JoinOp, JoinStep, SourceRef,
} from "./types";
import type { FilterRow } from "./components/JoinPanel";
import { ARROW, addsColumns, aliasOf, fromFilter, sentFilters } from "./components/JoinPanel";

/** Additional tables a join can carry (same limit as the step builder). */
export const MAX_JOINED = 6;

export interface CanvasCond {
  /** Node whose column is on the left; normally the parent. */
  leftNode: string;
  left: string;
  op: JoinOp;
  right: string;
}

export interface CanvasNode {
  id: string;
  title: string;
  /** Short source label shown on the card, e.g. "Aurora", "S3", "Open tab". */
  badge: string;
  /** Opened input; undefined while the table is still opening. */
  dataset?: Dataset;
  /** True when the canvas opened this input and should close it on removal. */
  owned: boolean;
  rows?: number;
  rowsEstimated?: boolean;
  /** Column count known from the table listing before the table opens. */
  columnCount?: number;
  alias: string;
  /** Output columns of this table (null = all). The root always keeps all columns. */
  columns: string[] | null;
  filterRows: FilterRow[];
  parentId?: string;
  how: JoinHow;
  conditions: CanvasCond[];
  /** The link was applied at least once; validation problems are shown only then. */
  touched: boolean;
}

export interface JoinPlan {
  baseId: string;
  steps: JoinStep[];
  baseFilters: JoinFilter[];
}

export const rootOf = (nodes: CanvasNode[]) => nodes.find((n) => !n.parentId);

export const byNodeId = (nodes: CanvasNode[]) => new Map(nodes.map((n) => [n.id, n]));

export const isCompleteCond = (c: CanvasCond) => Boolean(c.left && c.right);
export const isBlankCond = (c: CanvasCond) => !c.left && !c.right;

/** Ids of `id` and every node below it. */
export function subtree(nodes: CanvasNode[], id: string): Set<string> {
  const out = new Set([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const n of nodes) {
      if (n.parentId && out.has(n.parentId) && !out.has(n.id)) { out.add(n.id); grew = true; }
    }
  }
  return out;
}

/** Join steps in order: a parent always comes before its children; otherwise
 * nodes keep the order they were added (so a reopened join keeps its step order). */
export function orderedSteps(nodes: CanvasNode[]): CanvasNode[] {
  const root = rootOf(nodes);
  if (!root) return [];
  const placed = new Set([root.id]);
  const out: CanvasNode[] = [];
  let progress = true;
  while (progress) {
    progress = false;
    for (const n of nodes) {
      if (!placed.has(n.id) && n.parentId && placed.has(n.parentId)) {
        placed.add(n.id); out.push(n); progress = true;
        break;   // restart so earlier-added nodes whose parent just appeared go first
      }
    }
  }
  return out;
}

/** Columns a node offers to tables joined to it (its own column names). */
export function offeredColumns(node: CanvasNode): string[] {
  const all = node.dataset?.columns.map((c) => c.name) ?? [];
  if (!node.parentId) return all;
  if (!addsColumns(node.how)) return [];
  return node.columns ?? all;
}

/** The request's left reference for a canvas condition. */
export function leftRef(nodes: CanvasNode[], cond: CanvasCond): string {
  const node = nodes.find((n) => n.id === cond.leftNode);
  if (!node || !node.parentId) return cond.left;
  return `${node.alias.trim()}${ARROW}${cond.left}`;
}

/** Canvas → join request (base id, ordered steps, base filters). Only complete
 * conditions and filters are sent, like the step builder. */
export function toPlan(nodes: CanvasNode[]): JoinPlan | null {
  const root = rootOf(nodes);
  if (!root?.dataset) return null;
  const steps: JoinStep[] = [];
  for (const node of orderedSteps(nodes)) {
    if (!node.dataset) return null;
    const filters = sentFilters(node.filterRows, node.dataset.columns).map((f) => f.filter);
    steps.push({
      right_id: node.dataset.id, how: node.how, columns: node.columns, alias: node.alias.trim(),
      conditions: node.conditions.filter(isCompleteCond).map((c) => ({
        left: leftRef(nodes, c), op: c.op, right: c.right })),
      ...(filters.length ? { filters } : {}),
    });
  }
  return {
    baseId: root.dataset.id, steps,
    baseFilters: sentFilters(root.filterRows, root.dataset.columns).map((f) => f.filter),
  };
}

/** Join request → canvas. `node(datasetId)` supplies the card details of each
 * input. A condition's left reference is resolved to the earlier step whose
 * alias prefixes it (longest alias first), otherwise to the base table; the
 * step's parent is the table its first condition refers to. */
export function fromPlan(plan: JoinPlan,
                         node: (datasetId: string, index: number) => Pick<CanvasNode,
                           "id" | "title" | "badge" | "dataset" | "owned" | "rows" | "rowsEstimated">,
                         ): CanvasNode[] {
  const root: CanvasNode = {
    ...node(plan.baseId, 0), alias: "", columns: null, how: "left", conditions: [],
    filterRows: plan.baseFilters.map(fromFilter), touched: true,
  };
  root.alias = aliasOf(root.dataset ?? ({ title: root.title } as Dataset));
  const out: CanvasNode[] = [root];
  plan.steps.forEach((step, i) => {
    const info = node(step.right_id, i + 1);
    const earlier = out.slice(1).map((n, j) => ({ n, alias: plan.steps[j].alias.trim() }))
      .sort((a, b) => b.alias.length - a.alias.length);
    const conditions = step.conditions.map((c): CanvasCond => {
      const match = earlier.find((e) => e.alias && c.left.startsWith(`${e.alias}${ARROW}`));
      return match
        ? { leftNode: match.n.id, left: c.left.slice(match.alias.length + ARROW.length), op: c.op, right: c.right }
        : { leftNode: root.id, left: c.left, op: c.op, right: c.right };
    });
    out.push({
      ...info, alias: step.alias, columns: step.columns ?? null, how: step.how,
      parentId: conditions[0]?.leftNode ?? root.id, conditions,
      filterRows: (step.filters ?? []).map(fromFilter), touched: true,
    });
  });
  return out;
}

/** Recipe of the canvas as a join source reference (for Save), or a reason it can't be saved. */
export function toJoinRef(nodes: CanvasNode[], allowLoaded: boolean):
    { ref: Extract<SourceRef, { kind: "join" }> } | { reason: string } {
  const plan = toPlan(nodes);
  const root = rootOf(nodes);
  if (!plan || !root) return { reason: "Add tables to the canvas first." };
  const steps = orderedSteps(nodes);
  const missing = [root, ...steps].find((n) => !n.dataset?.sourceRef);
  if (missing) return { reason: `${missing.title} is an uploaded file and can't be reopened later.` };
  return { ref: {
    kind: "join", base: root.dataset!.sourceRef!,
    ...(plan.baseFilters.length ? { base_filters: plan.baseFilters } : {}),
    ...(allowLoaded ? { allow_loaded: true } : {}),
    steps: plan.steps.map(({ right_id: _id, ...step }, i) => ({
      ...step, source: steps[i].dataset!.sourceRef!,
    })),
  } };
}

/** An alias not used by another node. */
export function uniqueAlias(name: string, nodes: CanvasNode[], except?: string): string {
  const base = name.replace(/\.(parquet|csv|tsv|txt|json|ndjson)$/i, "").split("/").pop() || "joined";
  const used = new Set(nodes.filter((n) => n.id !== except).map((n) => n.alias.trim()));
  if (!used.has(base)) return base;
  for (let k = 2; ; k++) if (!used.has(`${base}_${k}`)) return `${base}_${k}`;
}

/** Problems found without the server, per non-root node id, in plain language. */
export function localProblems(nodes: CanvasNode[]): Map<string, string[]> {
  const ids = byNodeId(nodes);
  const out = new Map<string, string[]>();
  for (const node of orderedSteps(nodes)) {
    const parent = ids.get(node.parentId!)!;
    const problems: string[] = [];
    if (!node.alias.trim()) problems.push(`Give ${node.title} a name for its joined columns.`);
    else if (nodes.some((n) => n.id !== node.id && n.parentId && n.alias.trim() === node.alias.trim()))
      problems.push(`Another table is also named “${node.alias.trim()}”; choose a different name.`);
    if (parent.parentId && !addsColumns(parent.how))
      problems.push(`${parent.title} uses a match-only join and adds no columns, so ${node.title} can't be joined to it. Join it to another table.`);
    if (node.conditions.some((c) => !isBlankCond(c) && !isCompleteCond(c)))
      problems.push("Finish or remove the incomplete join clause.");
    for (const c of node.conditions.filter(isCompleteCond)) {
      const left = ids.get(c.leftNode);
      if (left && left.dataset && !offeredColumns(left).includes(c.left) && addsColumns(left.how))
        problems.push(`${c.left} is not included from ${left.title}; include it or pick another field.`);
    }
    if (problems.length) out.set(node.id, problems);
  }
  return out;
}

export const NODE_W = 216;
export const NODE_H = 76;
const GAP_X = 104;
const GAP_Y = 28;
const PAD = 32;

/** Tree layout: root on the left, children in columns to the right, each
 * parent centred on its children. Deterministic from the node list. */
export function layout(nodes: CanvasNode[]): { pos: Map<string, { x: number; y: number }>; width: number; height: number } {
  const pos = new Map<string, { x: number; y: number }>();
  const root = rootOf(nodes);
  if (!root) return { pos, width: 0, height: 0 };
  let cursor = PAD;
  let maxDepth = 0;
  const place = (node: CanvasNode, depth: number): number => {
    maxDepth = Math.max(maxDepth, depth);
    const kids = nodes.filter((n) => n.parentId === node.id);
    let y: number;
    if (!kids.length) { y = cursor; cursor += NODE_H + GAP_Y; }
    else {
      const ys = kids.map((k) => place(k, depth + 1));
      y = (ys[0] + ys[ys.length - 1]) / 2;
    }
    pos.set(node.id, { x: PAD + depth * (NODE_W + GAP_X), y });
    return y;
  };
  place(root, 0);
  return { pos, width: PAD * 2 + (maxDepth + 1) * NODE_W + maxDepth * GAP_X, height: cursor - GAP_Y + PAD };
}

/** Orthogonal connector from a parent's right edge to a child's left edge, with
 * rounded elbows; `badge` is where the join-type badge sits on the link. */
export function connector(from: { x: number; y: number }, to: { x: number; y: number }):
    { d: string; badge: { x: number; y: number } } {
  const x1 = from.x + NODE_W, y1 = from.y + NODE_H / 2;
  const x2 = to.x, y2 = to.y + NODE_H / 2;
  const mid = x1 + (x2 - x1) / 2;
  const dy = y2 - y1;
  const r = Math.min(10, Math.abs(dy) / 2, (x2 - x1) / 4);
  const d = Math.abs(dy) < 1
    ? `M ${x1} ${y1} H ${x2}`
    : `M ${x1} ${y1} H ${mid - r} Q ${mid} ${y1} ${mid} ${y1 + Math.sign(dy) * r} `
      + `V ${y2 - Math.sign(dy) * r} Q ${mid} ${y2} ${mid + r} ${y2} H ${x2}`;
  return { d, badge: { x: Math.abs(dy) < 1 ? mid : (mid + x2) / 2, y: y2 } };
}
