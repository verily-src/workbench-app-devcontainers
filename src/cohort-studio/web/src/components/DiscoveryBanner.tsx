import "./DiscoveryBanner.css";
import { useState } from "react";
import type { DiscoveryStatus } from "../api";

export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  const at = iso ? Date.parse(iso) : NaN;
  if (Number.isNaN(at)) return "an earlier session";
  const seconds = Math.max(0, Math.round((now - at) / 1000));
  if (seconds < 60) return "moments ago";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} days ago`;
}

/** Whether polling may stop: discovery has settled (absent means an older server). */
export function discoverySettled(d: DiscoveryStatus | undefined): boolean {
  return !d || d.status === "fresh" || d.status === "unavailable";
}

/**
 * Non-blocking notice above the source picker when the workspace resource
 * list is served from an older snapshot or the last refresh failed. Nothing
 * renders when discovery is fresh (or the CLI is absent, as in local dev).
 */
export function DiscoveryBanner({ discovery, onRetry }: {
  discovery: DiscoveryStatus | undefined;
  onRetry: () => Promise<unknown>;
}) {
  const [retrying, setRetrying] = useState(false);
  if (!discovery || discovery.status === "fresh" || discovery.status === "unavailable") return null;
  const { status, error, updated_at, from_cache } = discovery;
  if (status === "refreshing") {
    // A first connect is covered by "Connecting to workspace…"; only a
    // cached list (or a retry after a failure) needs a word here.
    if (!from_cache && !error) return null;
    return (
      <div className="discovery-status" role="status">
        <span className="pulse" />
        {error ? "Retrying datasource discovery…" : "Refreshing datasources…"}
      </div>
    );
  }
  const retry = () => {
    setRetrying(true);
    void onRetry().finally(() => setRetrying(false));
  };
  const reason = error || "the Workbench CLI could not list resources.";
  return (
    <div className="discovery-banner" role="status" data-status={status}>
      <div className="discovery-banner-text">
        {status === "stale"
          ? <>Showing datasources from {relativeTime(updated_at)}; refresh failed: {reason}</>
          : <>Workspace datasources could not be listed: {reason}</>}
      </div>
      <button type="button" className="quiet discovery-retry" onClick={retry} disabled={retrying}>
        {retrying ? "Retrying…" : "Retry"}
      </button>
    </div>
  );
}
