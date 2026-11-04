import type { TableInfo } from "./types";

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });

export function formatCount(value: number): string {
  return value < 10_000 ? value.toLocaleString("en") : compact.format(value);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 100 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

export function formatElapsed(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  if (whole < 60) return `${whole}s`;
  const minutes = Math.floor(whole / 60);
  if (minutes < 60) return `${minutes}m ${String(whole % 60).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

export function rowsLabel(info: Pick<TableInfo, "rows" | "rows_estimated">): string | null {
  if (info.rows == null) return null;
  return `${info.rows_estimated ? "~" : ""}${formatCount(info.rows)} rows`;
}

/** "~32.4M rows · 6.1 GB · 22 cols" — only the parts the listing knows. */
export function tableStats(info: TableInfo): string {
  return [
    rowsLabel(info),
    info.bytes != null ? formatBytes(info.bytes) : null,
    info.columns != null ? `${info.columns} cols` : null,
  ].filter(Boolean).join(" · ");
}

export function formatTimestamp(value: string): string {
  const date = new Date(value.includes("T") || value.endsWith("Z") ? value : value.replace(" ", "T"));
  if (Number.isNaN(date.valueOf())) return value;
  return date.toLocaleString("en", { year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit" });
}
