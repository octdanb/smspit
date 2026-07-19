const STORAGE_KEY = "smspit-notify";

export function notificationsEnabled(): boolean {
  return (
    localStorage.getItem(STORAGE_KEY) === "on" &&
    typeof Notification !== "undefined" &&
    Notification.permission === "granted"
  );
}

export async function setNotificationsEnabled(
  enabled: boolean,
): Promise<boolean> {
  if (!enabled) {
    localStorage.setItem(STORAGE_KEY, "off");
    return false;
  }
  if (typeof Notification === "undefined") return false;
  const permission =
    Notification.permission === "granted"
      ? "granted"
      : await Notification.requestPermission();
  localStorage.setItem(STORAGE_KEY, permission === "granted" ? "on" : "off");
  return permission === "granted";
}

/** Desktop notification for a new message when the tab is hidden. */
export function notifyNewMessage(number: string, body: string): void {
  if (!notificationsEnabled() || !document.hidden) return;
  new Notification(`smspit — ${number}`, {
    body: body.slice(0, 120) || "(no body)",
    tag: "smspit-new-message",
  });
}
