import type { BoxPlotStats, HistogramBin, KdePoint } from "../types";

function percentile(sorted: number[], p: number): number {
  const idx = (p / 100) * (sorted.length - 1);
  const lower = Math.floor(idx);
  const upper = Math.ceil(idx);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (idx - lower);
}

export function computeHistogramBins(
  values: number[],
  binCount?: number,
): HistogramBin[] {
  if (values.length === 0) return [];

  const sorted = [...values].sort((a, b) => a - b);
  const min = sorted[0];
  const max = sorted[sorted.length - 1];

  if (min === max) {
    return [{ binStart: min, binEnd: max, label: String(min), count: values.length }];
  }

  const k = binCount ?? Math.max(5, Math.min(30, Math.ceil(Math.log2(values.length) + 1)));
  const binWidth = (max - min) / k;

  const bins: HistogramBin[] = Array.from({ length: k }, (_, i) => ({
    binStart: min + i * binWidth,
    binEnd: min + (i + 1) * binWidth,
    label: `${(min + i * binWidth).toFixed(1)}–${(min + (i + 1) * binWidth).toFixed(1)}`,
    count: 0,
  }));

  for (const v of values) {
    const idx = Math.min(Math.floor((v - min) / binWidth), k - 1);
    bins[idx].count++;
  }

  return bins;
}

export function computeBoxPlotStats(values: number[]): BoxPlotStats | null {
  if (values.length === 0) return null;

  const sorted = [...values].sort((a, b) => a - b);
  const q1 = percentile(sorted, 25);
  const median = percentile(sorted, 50);
  const q3 = percentile(sorted, 75);
  const iqr = q3 - q1;

  const whiskerLow = q1 - 1.5 * iqr;
  const whiskerHigh = q3 + 1.5 * iqr;

  const min = sorted.find((v) => v >= whiskerLow) ?? sorted[0];
  const max = sorted.findLast((v) => v <= whiskerHigh) ?? sorted[sorted.length - 1];

  const outliers = sorted.filter((v) => v < min || v > max);

  return { min, q1, median, q3, max, outliers, count: sorted.length };
}

export function computeKde(
  values: number[],
  points = 100,
): { kde: KdePoint[]; bins: HistogramBin[] } {
  if (values.length === 0) return { kde: [], bins: [] };

  const sorted = [...values].sort((a, b) => a - b);
  const n = sorted.length;
  const min = sorted[0];
  const max = sorted[n - 1];

  if (min === max) {
    return {
      kde: [{ x: min, density: 1 }],
      bins: computeHistogramBins(values),
    };
  }

  // Silverman bandwidth
  const std = Math.sqrt(
    sorted.reduce((sum, v) => sum + (v - sorted.reduce((s, x) => s + x, 0) / n) ** 2, 0) / n,
  );
  const iqr = percentile(sorted, 75) - percentile(sorted, 25);
  const h = 0.9 * Math.min(std, iqr / 1.34) * n ** -0.2;

  const padding = (max - min) * 0.05;
  const step = (max - min + 2 * padding) / (points - 1);
  const xStart = min - padding;

  const kde: KdePoint[] = [];
  for (let i = 0; i < points; i++) {
    const x = xStart + i * step;
    let density = 0;
    for (const v of sorted) {
      const z = (x - v) / h;
      density += Math.exp(-0.5 * z * z) / (h * Math.sqrt(2 * Math.PI));
    }
    density /= n;
    kde.push({ x, density });
  }

  return { kde, bins: computeHistogramBins(values) };
}
