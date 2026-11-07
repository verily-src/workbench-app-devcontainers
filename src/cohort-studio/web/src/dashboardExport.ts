import { jsPDF } from "jspdf";
import { echarts } from "./echarts";
import { describeFilter } from "./filterText";
import { PARTNER_LOGO } from "./brand";
import type { Dataset } from "./types";

const SCALE = 2;
const PAD = 24;

interface Theme {
  surface: string; card: string; ink: string; soft: string; muted: string; border: string;
  accent: string; verily: string; warn: string; font: string;
}

function theme(): Theme {
  const root = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string) => root.getPropertyValue(name).trim() || fallback;
  const dark = root.colorScheme === "dark";
  const mark = document.querySelector(".brandmark");
  return {
    surface: v("--surface", "#fafafa"), card: v("--card", "#ffffff"), ink: v("--ink", "#17181a"),
    soft: v("--ink-soft", "#3c4043"), muted: v("--ink-muted", "#6b6f76"), border: v("--border-strong", "#dcdbdd"),
    accent: v("--accent", "#087a6a"),
    verily: mark ? getComputedStyle(mark).color : dark ? "#55c5b0" : "#087a6a",
    warn: dark ? "#f2b84b" : "#8a5300",
    font: getComputedStyle(document.body).fontFamily || "sans-serif",
  };
}

export const safeName = (s: string) =>
  s.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60) || "cohort";

/** The cohort size line as the tab shows it. */
export function cohortLine(dataset: Dataset): string {
  const r = dataset.result;
  if (!r) return "";
  const scope = (r.scope ?? dataset.queryScope) === "database" ? "full database"
    : r.sampled ? "capped loaded sample" : "in memory";
  const e = dataset.entityColumn ? r.entity : null;
  if (e) {
    const label = dataset.columns.find((c) => c.name === e.column)?.label || e.column;
    return `${e.filtered.toLocaleString()} of ${e.total.toLocaleString()} unique ${label} · ${scope}`;
  }
  return r.filtered === r.total ? `${r.filtered.toLocaleString()} rows · ${scope}`
    : `${r.filtered.toLocaleString()} of ${r.total.toLocaleString()} rows · ${scope}`;
}

/** Warnings an exported image must carry so it is not read as more than it is. */
export function exportNotes(dataset: Dataset): string[] {
  const r = dataset.result;
  const notes: string[] = [];
  if (r?.sampled) notes.push("Counts and charts use the capped loaded sample. They do not describe the full source population.");
  else if (r?.charts.some((c) => c?.sampled)) notes.push("Charts marked Sampled use sampled data.");
  return notes;
}

interface Header { title: string; lines: { text: string; kind: "source" | "cohort" | "filters" | "note" }[] }

function headerFor(dataset: Dataset): Header {
  const filters = dataset.filters.length
    ? dataset.filters.map((f) => describeFilter(f, true)).join("; ") : "none (full cohort)";
  const source = [dataset.source === dataset.title ? "" : dataset.source,
    dataset.publishedRevision ? `published rev ${dataset.publishedRevision}` : ""].filter(Boolean).join(" · ");
  const lines: Header["lines"] = [
    { text: source, kind: "source" },
    { text: cohortLine(dataset), kind: "cohort" },
    { text: `Filters: ${filters}`, kind: "filters" },
    ...exportNotes(dataset).map((text) => ({ text, kind: "note" as const })),
  ];
  return { title: dataset.title, lines: lines.filter((line) => line.text) };
}

function wrap(ctx: CanvasRenderingContext2D, text: string, width: number): string[] {
  const out: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/)) {
    const next = line ? `${line} ${word}` : word;
    if (ctx.measureText(next).width <= width || !line) line = next;
    else { out.push(line); line = word; }
  }
  if (line) out.push(line);
  return out;
}

function fit(ctx: CanvasRenderingContext2D, text: string, width: number): string {
  if (ctx.measureText(text).width <= width) return text;
  let s = text;
  while (s.length > 1 && ctx.measureText(`${s}…`).width > width) s = s.slice(0, -1);
  return `${s}…`;
}

function loadImage(src: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

const BRAND_H = 22;

/** Draws the header brand ("[partner] × [mark] verily Cohort Browser") and returns its width. */
function drawBrand(ctx: CanvasRenderingContext2D, t: Theme, x: number, y: number, partner: HTMLImageElement | null | undefined) {
  let cx = x;
  ctx.textBaseline = "middle";
  const mid = y + BRAND_H / 2;
  if (partner !== undefined) {
    if (partner) {
      const w = partner.naturalWidth && partner.naturalHeight ? BRAND_H * partner.naturalWidth / partner.naturalHeight : BRAND_H * 3.5;
      ctx.drawImage(partner, cx, y, w, BRAND_H);
      cx += w + 6;
    } else {
      ctx.font = `600 14px ${t.font}`; ctx.fillStyle = t.ink;
      ctx.fillText("partner", cx, mid); cx += ctx.measureText("partner").width + 6;
    }
    ctx.font = `400 14px ${t.font}`; ctx.fillStyle = t.muted;
    ctx.fillText("×", cx, mid); cx += ctx.measureText("×").width + 6;
  }
  const s = 18 / 100;
  ctx.save();
  ctx.translate(cx, mid - 82 * s / 2);
  ctx.scale(s, s);
  ctx.fillStyle = t.verily;
  ctx.beginPath(); ctx.roundRect(4, 9, 92, 64, 6); ctx.fill();
  ctx.fillStyle = "#ffffff";
  ctx.beginPath(); ctx.moveTo(35, 9); ctx.lineTo(35, 46); ctx.lineTo(47, 58); ctx.lineTo(90, 15); ctx.lineTo(90, 9);
  ctx.closePath(); ctx.fill();
  ctx.restore();
  cx += 18 + 6;
  ctx.font = `700 14px ${t.font}`; ctx.fillStyle = t.verily;
  ctx.fillText("verily", cx, mid); cx += ctx.measureText("verily ").width;
  ctx.fillStyle = t.ink;
  ctx.fillText("Cohort Browser", cx, mid); cx += ctx.measureText("Cohort Browser").width;
  return cx - x;
}

const LINE_FONT: Record<Header["lines"][number]["kind"], [string, number]> = {
  source: ["400 12px", 17], cohort: ["600 15px", 21], filters: ["400 12px", 17], note: ["600 12px", 17],
};

/** Header height in CSS px; draws it when ctx is given. */
function header(ctx: CanvasRenderingContext2D, t: Theme, h: Header, width: number, generated: Date,
                partner: HTMLImageElement | null | undefined, draw: boolean): number {
  let y = PAD;
  const inner = width - 2 * PAD;
  if (draw) {
    drawBrand(ctx, t, PAD, y, partner);
    ctx.font = `400 12px ${t.font}`; ctx.fillStyle = t.muted; ctx.textAlign = "right";
    ctx.fillText(`Generated ${generated.toLocaleString()}`, width - PAD, y + BRAND_H / 2);
    ctx.textAlign = "left";
  }
  y += BRAND_H + 14;
  ctx.textBaseline = "top";
  ctx.font = `700 20px ${t.font}`;
  for (const line of wrap(ctx, h.title, inner)) {
    if (draw) { ctx.fillStyle = t.ink; ctx.fillText(line, PAD, y); }
    y += 26;
  }
  y += 2;
  for (const line of h.lines) {
    const [font, height] = LINE_FONT[line.kind];
    ctx.font = `${font} ${t.font}`;
    for (const text of wrap(ctx, line.kind === "note" ? `Note: ${line.text}` : line.text, inner)) {
      if (draw) {
        ctx.fillStyle = line.kind === "cohort" ? t.ink : line.kind === "note" ? t.warn : t.soft;
        ctx.fillText(text, PAD, y);
      }
      y += height;
    }
  }
  y += 10;
  if (draw) { ctx.fillStyle = t.border; ctx.fillRect(PAD, y, inner, 1); }
  return y + 14;
}

type Instance = NonNullable<ReturnType<typeof echarts.getInstanceByDom>>;

async function settle(instances: Instance[]) {
  const deadline = Date.now() + 2000;
  const busy = () => instances.some((chart) => {
    const animation = (chart.getZr() as unknown as { animation?: { isFinished?: () => boolean } }).animation;
    return animation?.isFinished ? !animation.isFinished() : false;
  });
  while (busy() && Date.now() < deadline) await new Promise((r) => setTimeout(r, 50));
}

export interface Composed { canvas: HTMLCanvasElement; breaks: number[] }

/** Draws the header and the given chart cards, placed as they sit in `frame`. Breaks are safe page cuts in canvas px. */
async function compose(frame: HTMLElement, cards: HTMLElement[], h: Header): Promise<Composed> {
  const t = theme();
  const frameRect = frame.getBoundingClientRect();
  const zoom = frame.offsetWidth ? frameRect.width / frame.offsetWidth : 1;
  const rel = (el: Element) => {
    const r = el.getBoundingClientRect();
    return { x: (r.left - frameRect.left) / zoom, y: (r.top - frameRect.top) / zoom, w: r.width / zoom, h: r.height / zoom };
  };
  const plots = cards.map((card) => card.querySelector<HTMLElement>(".chart-plot"));
  const instances = plots.map((plot) => (plot ? echarts.getInstanceByDom(plot) : undefined));
  await settle(instances.filter((i): i is Instance => Boolean(i)));

  const partner = document.documentElement.dataset.brand === "partner" ? await loadImage(PARTNER_LOGO) : undefined;
  const width = Math.max(Math.ceil(frame.offsetWidth) + 2 * PAD, 640);
  const measure = document.createElement("canvas").getContext("2d")!;
  const generated = new Date();
  const top = header(measure, t, h, width, generated, partner, false);
  const boxes = cards.map(rel);
  const bottom = Math.max(0, ...boxes.map((b) => b.y + b.h));
  const height = Math.ceil(top + bottom + PAD);

  const canvas = document.createElement("canvas");
  // Browsers refuse canvases past about 32k px a side or 268M px; long dashboards draw at a lower scale.
  const scale = Math.min(SCALE, 32000 / height, Math.sqrt(250e6 / (width * height)));
  canvas.width = Math.floor(width * scale); canvas.height = Math.floor(height * scale);
  const ctx = canvas.getContext("2d")!;
  ctx.scale(scale, scale);
  ctx.fillStyle = t.surface; ctx.fillRect(0, 0, width, height);
  header(ctx, t, h, width, generated, partner, true);

  const left = PAD + (width - 2 * PAD - frame.offsetWidth) / 2;
  const images = await Promise.all(instances.map((chart) => chart
    ? loadImage(chart.getDataURL({ type: "png", pixelRatio: SCALE, backgroundColor: t.card })) : Promise.resolve(null)));
  cards.forEach((card, i) => {
    const b = boxes[i];
    const x = left + b.x, y = top + b.y;
    ctx.fillStyle = t.card; ctx.strokeStyle = t.border; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.roundRect(x + 0.5, y + 0.5, b.w - 1, b.h - 1, 8); ctx.fill(); ctx.stroke();
    ctx.textBaseline = "middle";
    const title = card.querySelector(".head .title, .head input");
    const badge = card.querySelector(".head .badge")?.textContent?.trim();
    const head = card.querySelector(".head");
    if (head) {
      const hb = rel(head);
      const tb = title ? rel(title) : hb;
      const mid = top + tb.y + tb.h / 2;
      const text = title instanceof HTMLInputElement ? title.value : title?.textContent?.trim() ?? "";
      ctx.font = `600 11px ${t.font}`;
      const badgeW = badge ? ctx.measureText(badge).width + 10 : 0;
      ctx.font = `600 12px ${t.font}`; ctx.fillStyle = t.soft;
      const shown = fit(ctx, text, Math.max(40, b.x + b.w - 12 - tb.x - badgeW));
      ctx.fillText(shown, left + tb.x, mid);
      if (badge) {
        const bx = left + tb.x + ctx.measureText(shown).width + 10;
        ctx.font = `600 11px ${t.font}`; ctx.fillStyle = t.warn;
        ctx.fillText(badge, bx, mid);
      }
    }
    card.querySelectorAll(".axis-scale-note").forEach((note) => {
      const nb = rel(note);
      ctx.font = `400 11px ${t.font}`; ctx.fillStyle = t.muted;
      ctx.fillText(fit(ctx, note.textContent?.trim() ?? "", b.w - 24), left + nb.x, top + nb.y + nb.h / 2);
    });
    const plot = plots[i];
    if (!plot) return;
    const pb = rel(plot);
    const img = images[i];
    if (img) ctx.drawImage(img, left + pb.x, top + pb.y, pb.w, pb.h);
    else {
      ctx.font = `400 12px ${t.font}`; ctx.fillStyle = t.muted; ctx.textAlign = "center";
      ctx.fillText("Chart not drawn", left + pb.x + pb.w / 2, top + pb.y + pb.h / 2);
      ctx.textAlign = "left";
    }
  });

  const rowTops = Array.from(new Set(boxes.map((b) => Math.round(b.y)))).sort((a, b) => a - b);
  const breaks = [top - 8, ...rowTops.slice(1).map((y) => top + y - 6), height].map((y) => Math.min(canvas.height, Math.round(y * scale)));
  return { canvas, breaks };
}

function chartCards(): { grid: HTMLElement; cards: HTMLElement[] } {
  const grid = document.querySelector<HTMLElement>(".chart-grid");
  if (!grid) throw new Error("No charts to export.");
  return { grid, cards: Array.from(grid.querySelectorAll<HTMLElement>(":scope > .chart-card")) };
}

function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

const toBlob = (canvas: HTMLCanvasElement) => new Promise<Blob>((resolve, reject) =>
  canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Could not draw the image."))), "image/png"));

export async function exportDashboardPng(dataset: Dataset) {
  const { grid, cards } = chartCards();
  const { canvas } = await compose(grid, cards, headerFor(dataset));
  download(await toBlob(canvas), `${safeName(dataset.title)}-dashboard.png`);
}

export async function exportChartPng(dataset: Dataset, card: HTMLElement) {
  const title = card.querySelector(".head .title")?.textContent?.trim() || "Chart";
  const { canvas } = await compose(card, [card], headerFor(dataset));
  download(await toBlob(canvas), `${safeName(title)}.png`);
}

/** A4 landscape (US Letter in the US and Canada); pages break between chart rows. */
export async function exportDashboardPdf(dataset: Dataset) {
  const { grid, cards } = chartCards();
  const { canvas, breaks } = await compose(grid, cards, headerFor(dataset));
  const letter = /^en-(US|CA)$/i.test(navigator.language);
  const doc = new jsPDF({ unit: "pt", format: letter ? "letter" : "a4", orientation: "landscape" });
  const pageW = doc.internal.pageSize.getWidth(), pageH = doc.internal.pageSize.getHeight();
  const margin = 24, footer = 16;
  const contentW = pageW - 2 * margin, contentH = pageH - 2 * margin - footer;
  const scale = contentW / canvas.width;
  const room = contentH / scale;
  const slices: [number, number][] = [];
  let start = 0;
  while (start < canvas.height) {
    const fits = breaks.filter((b) => b > start && b - start <= room);
    const end = fits.length ? fits[fits.length - 1] : breaks.find((b) => b > start) ?? canvas.height;
    slices.push([start, end]);
    start = end;
  }
  const surface = theme().surface;
  slices.forEach(([from, to], index) => {
    if (index) doc.addPage();
    doc.setFillColor(surface); doc.rect(0, 0, pageW, pageH, "F");
    const part = document.createElement("canvas");
    part.width = canvas.width; part.height = to - from;
    part.getContext("2d")!.drawImage(canvas, 0, from, canvas.width, to - from, 0, 0, canvas.width, to - from);
    const s = Math.min(scale, contentH / part.height);
    const w = part.width * s, h = part.height * s;
    doc.addImage(part, "PNG", margin + (contentW - w) / 2, margin, w, h, undefined, "FAST");
  });
  const pages = doc.getNumberOfPages();
  const stamp = new Date().toLocaleString();
  for (let page = 1; page <= pages; page++) {
    doc.setPage(page); doc.setFontSize(8); doc.setTextColor(128);
    doc.text(`${dataset.title} · Cohort Browser · ${stamp}`, margin, pageH - margin + 4);
    doc.text(`${page} / ${pages}`, pageW - margin, pageH - margin + 4, { align: "right" });
  }
  doc.save(`${safeName(dataset.title)}-dashboard.pdf`);
}
