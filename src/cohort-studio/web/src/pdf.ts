import { jsPDF } from "jspdf";
import autoTable from "jspdf-autotable";
import type { Dataset, Filter } from "./types";

function describeFilters(filters: Filter[]): string {
  if (filters.length === 0) return "none (full cohort)";
  return filters.map((f) =>
    f.kind === "categorical"
      ? `${f.column} ∈ {${(f.values ?? []).join(", ")}}`
      : `${f.column} ∈ [${f.min}, ${f.max}]`).join("  ·  ");
}

const safeName = (s: string) =>
  s.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_-]+/g, "_").slice(0, 60)
   || "cohort";

export interface ChartImage { title: string; dataUrl: string }

// Snapshot every rendered chart on the page as a PNG. ECharts draws to a
// <canvas>, so toDataURL gives us a crisp image without touching the
// chart instances (which live inside ChartCard).
export function captureCharts(): ChartImage[] {
  const cards = document.querySelectorAll<HTMLElement>(
    ".chart-grid .chart-card");
  const out: ChartImage[] = [];
  cards.forEach((card) => {
    const canvas = card.querySelector("canvas");
    const title = card.querySelector(".title")?.textContent?.trim() ?? "";
    if (canvas) out.push({ title, dataUrl: canvas.toDataURL("image/png") });
  });
  return out;
}

// Build a one-click report: header, active filters, every chart, and a
// page of the filtered rows. All client-side — the charts only exist here.
export function exportDatasetPdf(dataset: Dataset, charts: ChartImage[]) {
  const doc = new jsPDF({ unit: "pt", format: "a4" });
  const pageW = doc.internal.pageSize.getWidth();
  const pageH = doc.internal.pageSize.getHeight();
  const margin = 40;
  let y = margin;

  doc.setFontSize(16);
  doc.text(`Cohort Studio — ${dataset.title}`, margin, y);
  y += 20;

  const r = dataset.result;
  doc.setFontSize(10);
  doc.setTextColor(95);
  if (r) {
    doc.text(
      `${r.filtered.toLocaleString()} of ${r.total.toLocaleString()} rows`
      + `  ·  ${dataset.source}`, margin, y);
    y += 15;
  }
  const filterLines = doc.splitTextToSize(
    `Filters: ${describeFilters(dataset.filters)}`, pageW - 2 * margin);
  doc.text(filterLines, margin, y);
  y += filterLines.length * 13 + 8;
  doc.setTextColor(0);

  const imgW = pageW - 2 * margin;
  for (const img of charts) {
    const props = doc.getImageProperties(img.dataUrl);
    const imgH = (props.height / props.width) * imgW;
    if (y + imgH + 24 > pageH - margin) { doc.addPage(); y = margin; }
    doc.setFontSize(11);
    doc.text(img.title || "chart", margin, y);
    y += 8;
    doc.addImage(img.dataUrl, "PNG", margin, y, imgW, imgH);
    y += imgH + 20;
  }

  if (r && r.rows.data.length) {
    autoTable(doc, {
      startY: y + 4,
      margin: { left: margin, right: margin },
      head: [r.rows.columns],
      body: r.rows.data.map((row) =>
        row.map((c) => (c === null ? "–" : String(c)))),
      styles: { fontSize: 7, cellPadding: 2, overflow: "ellipsize" },
      headStyles: { fillColor: [63, 81, 181] },
      didDrawPage: () => {
        const n = doc.getNumberOfPages();
        doc.setFontSize(8);
        doc.setTextColor(150);
        doc.text(`page ${n}`, pageW - margin, pageH - 20,
                 { align: "right" });
      },
    });
  }

  doc.save(`${safeName(dataset.title)}.pdf`);
}
