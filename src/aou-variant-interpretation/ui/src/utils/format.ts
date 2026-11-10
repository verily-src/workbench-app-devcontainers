/**
 * A byte count the way BigQuery's console shows one: binary units (1 GB = 1,024 MB), one decimal
 * from MB up, whole numbers below. "0 B" for nothing.
 */
export function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit >= 2 ? 1 : 0;
  return `${value.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: digits })} ${units[unit]}`;
}

/** US dollars to the cent, with amounts under a cent shown as such rather than as $0.00. */
export function formatUsd(amount: number): string {
  if (amount > 0 && amount < 0.005) return "< $0.01";
  return `$${amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatInt(value: number): string {
  return value.toLocaleString("en-US");
}

export function formatAcAn(ac: number, an: number): string {
  return `${formatInt(ac)} / ${formatInt(an)}`;
}

/** Below this, four decimals would round a real frequency down to "0.0000". */
const SMALLEST_FIXED_AF = 0.0001;

/**
 * An allele frequency to four decimals. A rare variant's (most pathogenic ones, at around 1 in
 * 100,000) reads "< 0.0001" rather than rounding to "0.0000", which would claim none were seen --
 * keeping the column narrow, with the exact figure in exactAf and the counts beside it in AC/AN.
 * A true zero stays "0.0000".
 */
export function formatAf(af: number): string {
  if (af === 0 || af >= SMALLEST_FIXED_AF) return af.toFixed(4);
  return `< ${SMALLEST_FIXED_AF.toFixed(4)}`;
}

/**
 * The exact figure behind a frequency formatAf abbreviates, for a tooltip: plain decimals to two
 * significant digits, e.g. "0.0000043". Undefined when formatAf already shows it.
 */
export function exactAf(af: number): string | undefined {
  if (af === 0 || af >= SMALLEST_FIXED_AF) return undefined;
  // Decimals up to and including the second significant digit: 0.0000043's first is in the 6th
  // place (floor(log10) = -6), so it needs 7.
  return af.toFixed(1 - Math.floor(Math.log10(af)));
}

/** e.g. "2024-02-14" -> "14 Feb 2024". */
export function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** p-values for display: "< 0.001", "0.003", "0.42", "1.0". */
export function formatPValue(p: number): string {
  if (p < 0.001) return "< 0.001";
  if (p >= 0.995) return "1.0";
  return p.toFixed(p < 0.01 ? 3 : 2);
}

/**
 * A number to two significant figures, with thousands separators above 999: "0.083", "2.1", "26",
 * "310", "1,800". Always significant figures, never a cap on decimal places, so a tiny but
 * positive bound never rounds to "0"; below 0.0001 it takes exponent form ("3.2e-7") to stay short.
 */
export function formatSig(value: number): string {
  if (value === 0) return "0";
  if (!Number.isFinite(value)) return "∞";
  if (Math.abs(value) < 1e-4) return value.toExponential(1);
  return value.toLocaleString("en-US", { maximumSignificantDigits: 2 });
}

/** A fold change for display: "26×", "0.31×", "∞". Two significant figures, never truncated. */
export function formatRatio(ratio: number): string {
  if (!Number.isFinite(ratio)) return "∞";
  return `${formatSig(ratio)}×`;
}

/** An interval for display: "13 – 83", "0 – 1,800", "120 – ∞". */
export function formatInterval([low, high]: [number, number]): string {
  return `${formatSig(low)} – ${formatSig(high)}`;
}

/** Expected counts for display: "< 0.001", "0.002", "0.23", "9.1", "120". */
export function formatExpected(expected: number): string {
  if (expected >= 10) return expected.toFixed(0);
  if (expected >= 1) return expected.toFixed(1);
  if (expected >= 0.01) return expected.toFixed(2);
  return expected < 0.001 ? "< 0.001" : expected.toFixed(3);
}
