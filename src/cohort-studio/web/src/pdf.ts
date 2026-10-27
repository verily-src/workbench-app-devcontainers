import * as echarts from "echarts";
import { jsPDF } from "jspdf";
import autoTable from "jspdf-autotable";
import type { Dataset, Filter } from "./types";

function describeFilters(filters: Filter[]): string {
  if (filters.length === 0) return "none (full cohort)";
  return filters.map((f) => f.kind === "categorical"
    ? `${f.column}: ${(f.values ?? []).join(", ")}`
    : f.max === Number.MAX_VALUE ? `${f.column}: at least ${f.min}` : `${f.column}: ${f.min} to ${f.max}`).join("; ");
}

const safeName = (s: string) =>
  s.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_-]+/g, "_").slice(0, 60) || "cohort";

export interface ChartImage { title: string; dataUrl: string }

export function captureCharts(): ChartImage[] {
  const cards = document.querySelectorAll<HTMLElement>(".chart-grid .chart-card");
  const out: ChartImage[] = [];
  cards.forEach((card) => {
    const plot = card.querySelector<HTMLElement>(".chart-plot");
    const chart = plot && echarts.getInstanceByDom(plot);
    if (!chart) return;
    const original = chart.getOption();
    const printAxes = (axes: unknown) => (Array.isArray(axes) ? axes : []).map((axis) => {
      const item = axis as Record<string, unknown>;
      return { ...item, axisLabel: { ...(item.axisLabel as object), color: "#36434a" },
        axisLine: { ...(item.axisLine as object), lineStyle: { color: "#b6c3c5" } },
        splitLine: { ...(item.splitLine as object), lineStyle: { color: "#e1e8e8" } } };
    });
    try {
      chart.setOption({ xAxis: printAxes(original.xAxis), yAxis: printAxes(original.yAxis) },
        { silent: true });
      out.push({ title: card.querySelector(".title")?.textContent?.trim() ?? "Chart",
        dataUrl: chart.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#ffffff" }) });
    } finally {
      chart.setOption(original, { notMerge: true, silent: true });
    }
  });
  return out;
}

export function exportDatasetPdf(dataset: Dataset, charts: ChartImage[]) {
  const doc = new jsPDF({ unit: "pt", format: "a4" });
  const pageW = doc.internal.pageSize.getWidth();
  const pageH = doc.internal.pageSize.getHeight();
  const margin = 42;
  const contentW = pageW - 2 * margin;
  let y = margin;
  const writeWrapped = (text: string, size: number, color: number) => {
    doc.setFontSize(size); doc.setTextColor(color);
    const lines = doc.splitTextToSize(text, contentW) as string[];
    doc.text(lines, margin, y); y += lines.length * (size + 3) + 5;
  };
  writeWrapped(dataset.title, 17, 25);
  writeWrapped("Cohort Studio", 9, 100);
  const r = dataset.result;
  if (r) writeWrapped(`${r.filtered.toLocaleString()} of ${r.total.toLocaleString()} rows - ${dataset.source}`, 10, 75);
  writeWrapped(`Filters: ${describeFilters(dataset.filters)}`, 9, 75);
  y += 8;

  for (const img of charts) {
    const props = doc.getImageProperties(img.dataUrl);
    const imgW = Math.min(contentW, 245 * props.width / props.height);
    const imgH = imgW * props.height / props.width;
    const titleLines = doc.splitTextToSize(img.title || "Chart", contentW) as string[];
    const titleHeight = titleLines.length * 14;
    if (y + titleHeight + imgH + 14 > pageH - margin - 20) { doc.addPage(); y = margin; }
    doc.setFontSize(11); doc.setTextColor(35); doc.text(titleLines, margin, y);
    y += titleHeight;
    doc.addImage(img.dataUrl, "PNG", margin, y, imgW, imgH);
    y += imgH + 22;
  }

  if (r && r.rows.data.length) {
    const columns = r.rows.columns;
    const groups = Math.ceil(columns.length / 6);
    for (let group = 0; group < groups; group++) {
      doc.addPage(); y = margin;
      doc.setFontSize(12); doc.setTextColor(35);
      doc.text(`Displayed rows${groups > 1 ? ` - columns ${group + 1} of ${groups}` : ""}`, margin, y);
      y += 16;
      doc.setFontSize(9); doc.setTextColor(90);
      doc.text(`${r.rows.data.length} rows from the current table page`, margin, y);
      const start = group * 6;
      autoTable(doc, { startY: y + 10, margin: { left: margin, right: margin, bottom: margin },
        head: [columns.slice(start, start + 6)],
        body: r.rows.data.map((row) => row.slice(start, start + 6).map((c) => c === null ? "-" : String(c))),
        styles: { fontSize: 8, cellPadding: 4, overflow: "linebreak" },
        headStyles: { fillColor: [9, 114, 98], textColor: 255 },
        rowPageBreak: "avoid" });
    }
  }
  const totalPages = doc.getNumberOfPages();
  for (let page = 1; page <= totalPages; page++) {
    doc.setPage(page); doc.setFontSize(8); doc.setTextColor(120);
    doc.text(`${page} / ${totalPages}`, pageW - margin, pageH - 20, { align: "right" });
  }
  doc.save(`${safeName(dataset.title)}.pdf`);
}
