import { Icon } from "./ui";

// Change Set X: shared by the Overview and Backup & Recovery, in its own small file so the Overview does not load the
// whole Backup & Recovery screen.
export const STATE_CLASS: Record<string, string> = { healthy: "ok", attention: "warn", critical: "danger", verified: "ok", partial: "warn", warning: "warn",
  failed: "danger", running: "neutral", stored_verified: "ok", stored_warning: "warn", retry_pending: "warn", auth_required: "danger",
  unavailable: "danger", insufficient_storage: "danger", uploading: "neutral", deleted: "neutral" };

export function HealthBadge({ state, label }: { state: string; label: string }) {
  return <span className={`badge ${STATE_CLASS[state] || "neutral"}`} data-health={state}><Icon name={state === "healthy" || state === "verified" ? "check" : "alert"} size={14} /> {label}</span>;
}
