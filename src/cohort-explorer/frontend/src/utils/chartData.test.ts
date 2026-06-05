import { describe, it, expect } from "vitest";
import { computeHistogramBins, computeBoxPlotStats } from "./chartData";

describe("computeHistogramBins", () => {
  it("returns empty array for empty input", () => {
    expect(computeHistogramBins([])).toEqual([]);
  });

  it("returns single bin when all values are equal", () => {
    const bins = computeHistogramBins([5, 5, 5]);
    expect(bins).toHaveLength(1);
    expect(bins[0].count).toBe(3);
    expect(bins[0].binStart).toBe(5);
  });

  it("distributes values across bins", () => {
    const values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
    const bins = computeHistogramBins(values, 5);
    expect(bins).toHaveLength(5);
    const totalCount = bins.reduce((sum, b) => sum + b.count, 0);
    expect(totalCount).toBe(10);
  });

  it("respects explicit bin count", () => {
    const values = Array.from({ length: 100 }, (_, i) => i);
    const bins = computeHistogramBins(values, 10);
    expect(bins).toHaveLength(10);
  });

  it("places max value in the last bin", () => {
    const values = [0, 5, 10];
    const bins = computeHistogramBins(values, 2);
    expect(bins).toHaveLength(2);
    expect(bins[1].count).toBeGreaterThanOrEqual(1);
  });

  it("bins have contiguous ranges", () => {
    const bins = computeHistogramBins([1, 2, 3, 4, 5], 3);
    for (let i = 1; i < bins.length; i++) {
      expect(bins[i].binStart).toBeCloseTo(bins[i - 1].binEnd, 10);
    }
  });
});

describe("computeBoxPlotStats", () => {
  it("returns null for empty input", () => {
    expect(computeBoxPlotStats([])).toBeNull();
  });

  it("computes correct quartiles for simple dataset", () => {
    const values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
    const stats = computeBoxPlotStats(values)!;
    expect(stats.median).toBeCloseTo(5.5);
    expect(stats.q1).toBeCloseTo(3.25);
    expect(stats.q3).toBeCloseTo(7.75);
    expect(stats.count).toBe(10);
  });

  it("identifies outliers beyond 1.5×IQR", () => {
    const values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 100];
    const stats = computeBoxPlotStats(values)!;
    expect(stats.outliers).toContain(100);
  });

  it("sets whiskers to nearest data points within range", () => {
    const values = [2, 4, 6, 8, 10];
    const stats = computeBoxPlotStats(values)!;
    expect(stats.min).toBeGreaterThanOrEqual(values[0]);
    expect(stats.max).toBeLessThanOrEqual(values[values.length - 1]);
  });

  it("handles single value", () => {
    const stats = computeBoxPlotStats([42])!;
    expect(stats.median).toBe(42);
    expect(stats.q1).toBe(42);
    expect(stats.q3).toBe(42);
    expect(stats.min).toBe(42);
    expect(stats.max).toBe(42);
    expect(stats.outliers).toEqual([]);
  });
});
