import type { BoxPlotStats, HistogramBin } from "../types";

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
