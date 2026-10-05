// File-type badge: a document shape with a readable type label (PDF, JPG, DOC…). The type comes from the server,
// which derives it from the file's validated content, not just its name. Colour is never the only cue.
const SHORT: Record<string, string> = {
  pdf: "PDF", jpeg: "JPG", png: "PNG", webp: "WEBP", image: "IMG", text: "TXT", word: "DOC", excel: "XLS",
  powerpoint: "PPT", archive: "ZIP", dicom: "DCM", other: "FILE",
};

export default function FileTypeIcon({ kind, label, size }: { kind?: string | null; label?: string; size?: "sm" | "lg" }) {
  const k = kind && SHORT[kind] ? kind : "other";
  return (
    <span className={`ftype ftype-${k} ${size || ""}`} role="img" aria-label={label || SHORT[k]} title={label}>
      <svg viewBox="0 0 32 40" aria-hidden="true" focusable="false">
        <path className="ftype-sheet" d="M3 1h18l8 8v28a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V3a2 2 0 0 1 2-2z" />
        <path className="ftype-fold" d="M21 1v6a2 2 0 0 0 2 2h6" />
      </svg>
      <span className="ftype-label" aria-hidden="true">{SHORT[k]}</span>
    </span>
  );
}

/** Best-effort type for items saved offline (their MIME type was validated by the server when uploaded). */
export function kindFromMime(mime: string, name = ""): string {
  const m = (mime || "").toLowerCase();
  const ext = name.toLowerCase().split(".").pop() || "";
  if (m === "application/pdf") return "pdf";
  if (m === "image/jpeg") return "jpeg";
  if (m === "image/png") return "png";
  if (m === "image/webp") return "webp";
  if (m.startsWith("image/")) return "image";
  if (m.startsWith("text/plain")) return "text";
  if (m === "application/dicom") return "dicom";
  if (m.includes("word") || m.includes("excel") || m.includes("powerpoint") || m.includes("officedocument") || m.includes("opendocument") || m === "application/rtf" || m === "text/csv") return officeKind(m, ext);
  if (m.includes("zip") || m.includes("compressed") || m.includes("rar")) return "archive";
  return "other";
}
function officeKind(m: string, ext: string): string {
  if (m.includes("word") || m.includes("text.document") || m.includes("opendocument.text") || ext === "doc" || ext === "docx" || m === "application/rtf") return "word";
  if (m.includes("sheet") || m.includes("excel") || m === "text/csv") return "excel";
  if (m.includes("presentation") || m.includes("powerpoint")) return "powerpoint";
  return "other";
}
