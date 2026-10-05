/** Folder view modes and sort orders. Saved per account (me.doc_view / me.doc_sort) so every device matches. */
export type DocView = "list" | "thumbnails" | "details";
export const DOC_VIEWS: [DocView, string, string][] = [
  ["list", "List", "list"],
  ["thumbnails", "Thumbnails", "grid"],
  ["details", "Details", "table"],
];
export const SORT_LABELS: Record<string, string> = {
  "-added": "Newest first", added: "Oldest first", name: "Name A–Z", "-name": "Name Z–A",
  "-size": "Largest first", size: "Smallest first", expiry: "Expiry date (soonest first)", "-expiry": "Expiry date (latest first)",
  type: "Type A–Z", "-type": "Type Z–A",
};
export const VIEW_LABELS: Record<string, string> = { list: "List", thumbnails: "Thumbnails", details: "Details" };

export function normaliseView(v: string | null | undefined): DocView {
  if (v === "grid") return "thumbnails"; // earlier versions stored "grid" in this browser
  return v === "thumbnails" || v === "details" ? v : "list";
}
