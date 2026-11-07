import { useEffect, useState } from "react";
import { api } from "../api";
import type { ExtractInfo, ExtractSchedule } from "../types";
import { Popover } from "./Popover";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function browserZone(): string {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch { return "UTC"; }
}

const pad = (n: number | undefined) => String(n ?? 0).padStart(2, "0");

/** "Hourly at :15", "Daily at 06:00", "Mondays at 09:30" (+ zone when not the browser's). */
export function scheduleSummary(s: ExtractSchedule): string {
  const at = `${pad(s.hour)}:${pad(s.minute)}`;
  const text = s.every === "hourly" ? `Hourly at :${pad(s.minute)}`
    : s.every === "daily" ? `Daily at ${at}`
    : s.every === "weekly" ? `${DAYS[s.weekday ?? 0]}s at ${at}` : "Off";
  return s.tz && s.tz !== browserZone() ? `${text} ${s.tz}` : text;
}

function span(ms: number): string {
  const minutes = Math.round(ms / 60000);
  if (minutes < 1) return "<1m";
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)}h`;
  return `${Math.round(minutes / 1440)}d`;
}

export function nextText(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const ms = Date.parse(iso) - now;
  return ms <= 0 ? "due now" : `next in ${span(ms)}`;
}

function agoText(iso: string, now = Date.now()): string {
  return `${span(Math.max(0, now - Date.parse(iso)))} ago`;
}

/** The last scheduled run failed and nothing has refreshed the extract since. */
export function scheduledFailure(info: ExtractInfo): string | null {
  if (info.last_run_status !== "failed" || !info.last_run_at) return null;
  if (Date.parse(info.last_run_at) < Date.parse(info.refreshed_at)) return null;
  return info.last_run_error || "The scheduled refresh failed.";
}

function lastRunText(info: ExtractInfo): string | null {
  if (!info.last_run_at || !info.last_run_status) return null;
  const when = agoText(info.last_run_at);
  switch (info.last_run_status) {
    case "ok": return `Last scheduled run: ok, ${when}`;
    case "running": return `Scheduled run started ${when}`;
    case "skipped": return `Last scheduled run skipped ${when}: ${info.last_run_error ?? ""}`.trim();
    default: return `Last scheduled run failed ${when}: ${info.last_run_error ?? "unknown error"}`;
  }
}

/** Compact schedule editor beside Refresh extract. */
export function ExtractScheduleControl({ info, kind, resourceId, table, disabled, onSaved }: {
  info: ExtractInfo; kind: string; resourceId: string; table: string; disabled?: boolean;
  onSaved: (info: ExtractInfo) => void;
}) {
  const current = info.schedule ?? { every: "off" as const };
  const [every, setEvery] = useState<ExtractSchedule["every"]>(current.every);
  const [time, setTime] = useState(`${pad(current.hour ?? 6)}:${pad(current.minute)}`);
  const [minute, setMinute] = useState(current.minute ?? 0);
  const [weekday, setWeekday] = useState(current.weekday ?? 0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [, setNow] = useState(0);
  useEffect(() => {
    if (!info.schedule) return;
    const id = window.setInterval(() => setNow(Date.now()), 30000);
    return () => window.clearInterval(id);
  }, [info.schedule]);

  // Editing keeps the zone the schedule was set in; a new schedule uses this browser's.
  const zone = current.tz ?? browserZone();
  const save = async (close: () => void) => {
    const [hour, min] = time.split(":").map((v) => Number(v));
    const schedule: ExtractSchedule = every === "off" ? { every }
      : every === "hourly" ? { every, minute, tz: zone }
      : { every, hour, minute: min, tz: zone,
          ...(every === "weekly" ? { weekday } : {}) };
    setSaving(true);
    setError(null);
    try {
      const out = await api.setExtractSchedule(kind, resourceId, table, schedule);
      onSaved(out.extract);
      close();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const label = info.schedule
    ? <>{scheduleSummary(info.schedule)}{info.next_run_at && <> · {nextText(info.next_run_at)}</>}</>
    : "Schedule";
  const last = lastRunText(info);
  return (
    <Popover label={<>{label} <span aria-hidden>▾</span></>} ariaLabel="Refresh schedule"
             className="extract-schedule" align="right">
      {(close) => <>
        <div className="popover-row">
          <label className="inline-field">Repeat
            <select aria-label="Repeat" value={every} disabled={disabled || saving}
                    onChange={(e) => setEvery(e.target.value as ExtractSchedule["every"])}>
              <option value="off">Off</option>
              <option value="hourly">Hourly</option>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
            </select>
          </label>
          {every === "weekly" && <select aria-label="Day" value={weekday} disabled={saving}
                    onChange={(e) => setWeekday(Number(e.target.value))}>
            {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
          </select>}
          {(every === "daily" || every === "weekly") && <input type="time" aria-label="Time" required
                 value={time} disabled={saving} onChange={(e) => setTime(e.target.value || "00:00")} />}
          {every === "hourly" && <label className="inline-field">at :
            <input type="number" aria-label="Minute past the hour" min={0} max={59} value={minute}
                   disabled={saving} style={{ width: 56 }}
                   onChange={(e) => setMinute(Math.min(59, Math.max(0, Number(e.target.value) || 0)))} />
          </label>}
        </div>
        <div className="popover-row">
          <button type="button" disabled={disabled || saving} onClick={() => void save(close)}>
            {saving ? "Saving…" : "Save schedule"}
          </button>
        </div>
        {error && <div className="derive-error" role="alert">{error}</div>}
        {last && <div className="extract-schedule-note">{last}</div>}
        <div className="extract-schedule-note">
          Times are in {zone}. Schedules run only while this app is running.
        </div>
      </>}
    </Popover>
  );
}
