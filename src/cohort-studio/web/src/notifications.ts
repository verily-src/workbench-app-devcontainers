const KEY = "cohort-studio-notifications";

export function notificationsEnabled(): boolean {
  try { return localStorage.getItem(KEY) === "on"; } catch { return false; }
}

export async function setNotifications(enabled: boolean): Promise<boolean> {
  if (!enabled) {
    try { localStorage.removeItem(KEY); } catch { }
    return false;
  }
  if (!("Notification" in window) || await Notification.requestPermission() !== "granted") return false;
  try { localStorage.setItem(KEY, "on"); return true; } catch { return false; }
}

export function notifyDataReady(kind: string, id: string): void {
  if (!notificationsEnabled() || document.visibilityState !== "hidden" ||
      !("Notification" in window) || Notification.permission !== "granted") return;
  try {
    const notification = new Notification(kind === "join" ? "Join is ready" : "Data is ready", {
      body: "Open Cohort Studio to view the result.", tag: `cohort-data-${id}`,
    });
    notification.onclick = () => { window.focus(); notification.close(); };
  } catch { }
}
