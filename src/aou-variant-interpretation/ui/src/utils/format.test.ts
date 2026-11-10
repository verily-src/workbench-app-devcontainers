import { describe, expect, it } from "vitest";
import { formatBytes, formatUsd } from "./format";

describe("formatBytes", () => {
  it("uses binary units with one decimal from MB up", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(10 * 1024 * 1024)).toBe("10 MB");
    expect(formatBytes(2516582400)).toBe("2.3 GB");
    expect(formatBytes(1.5 * 1024 ** 4)).toBe("1.5 TB");
  });
});

describe("formatUsd", () => {
  it("shows cents, and says when there is less than one", () => {
    expect(formatUsd(0)).toBe("$0.00");
    expect(formatUsd(0.0146)).toBe("$0.01");
    expect(formatUsd(0.004)).toBe("< $0.01");
    expect(formatUsd(12.5)).toBe("$12.50");
  });
});
import {
  exactAf,
  formatAcAn,
  formatAf,
  formatDate,
  formatExpected,
  formatInt,
  formatInterval,
  formatPValue,
  formatRatio,
  formatSig,
} from "./format";

describe("format utils", () => {
  it("formats integers with en-US grouping", () => {
    expect(formatInt(0)).toBe("0");
    expect(formatInt(1234)).toBe("1,234");
    expect(formatInt(1234567)).toBe("1,234,567");
  });

  it("formats AC/AN values using grouped integers", () => {
    expect(formatAcAn(12, 3456)).toBe("12 / 3,456");
    expect(formatAcAn(1234, 567890)).toBe("1,234 / 567,890");
  });

  it("formats allele frequencies to four decimal places", () => {
    expect(formatAf(0)).toBe("0.0000");
    expect(formatAf(0.123456)).toBe("0.1235");
    expect(formatAf(1)).toBe("1.0000");
    expect(formatAf(0.0001)).toBe("0.0001");
  });

  it("shows a rare-variant frequency as below 0.0001 rather than rounding it to zero", () => {
    expect(formatAf(0.0000123)).toBe("< 0.0001");
    expect(formatAf(0.0000043)).toBe("< 0.0001");
    expect(formatAf(0.0001)).toBe("0.0001");
  });

  it("gives the exact figure behind an abbreviated frequency, and nothing otherwise", () => {
    expect(exactAf(0.0000123)).toBe("0.000012");
    expect(exactAf(0.0000043)).toBe("0.0000043");
    expect(exactAf(0.00000207)).toBe("0.0000021");
    expect(exactAf(0.0123)).toBeUndefined();
    expect(exactAf(0)).toBeUndefined();
  });

  it("formats ISO dates in UTC as day month year", () => {
    expect(formatDate("2024-02-14")).toBe("14 Feb 2024");
    expect(formatDate("2023-12-01")).toBe("1 Dec 2023");
  });
});

describe("formatting", () => {
  it("shows two significant figures and never truncates a large value", () => {
    expect(formatSig(0.0834)).toBe("0.083");
    expect(formatSig(0.98)).toBe("0.98");
    expect(formatSig(2.11)).toBe("2.1");
    expect(formatSig(25.7)).toBe("26");
    expect(formatSig(312)).toBe("310");
    expect(formatSig(1837)).toBe("1,800");
    expect(formatSig(Infinity)).toBe("∞");
    // Significant figures all the way down: a positive bound never shows as zero.
    expect(formatSig(0.00032)).toBe("0.00032");
    expect(formatSig(0.000121)).toBe("0.00012");
    expect(formatSig(3.2e-7)).toBe("3.2e-7");
    expect(formatSig(0)).toBe("0");
    expect(formatRatio(25.7)).toBe("26×");
    expect(formatRatio(0.33)).toBe("0.33×");
    expect(formatRatio(Infinity)).toBe("∞");
    expect(formatInterval([0.0834, 0.98])).toBe("0.083 – 0.98");
    expect(formatInterval([120, Infinity])).toBe("120 – ∞");
    // An exact lower bound this small is real, and must not read as touching zero.
    expect(formatInterval([4.7e-7, 0.21])).toBe("4.7e-7 – 0.21");
  });

  it("formats p-values and expected counts", () => {
    expect(formatPValue(0.0001)).toBe("< 0.001");
    expect(formatPValue(0.0034)).toBe("0.003");
    expect(formatPValue(0.42)).toBe("0.42");
    expect(formatPValue(1)).toBe("1.0");
    expect(formatExpected(0.0016)).toBe("0.002");
    expect(formatExpected(9.13)).toBe("9.1");
    expect(formatExpected(123.4)).toBe("123");
  });
});
