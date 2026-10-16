import { useEffect, useState } from "react";
import { api } from "./api";

export type AiStatus = { enabled: boolean; allowed: boolean; ocr_assist: boolean; smart_organization: boolean; semantic_search: boolean; assistant: boolean };

let cached: { at: number; value: AiStatus } | null = null;

/** Which AI features the signed-in person may use (cached for a minute). */
export function useAiStatus(): AiStatus | null {
  const [s, setS] = useState<AiStatus | null>(cached?.value || null);
  useEffect(() => {
    if (cached && Date.now() - cached.at < 60000) return;
    api<AiStatus>("ai/status").then((v) => { cached = { at: Date.now(), value: v }; setS(v); }).catch(() => setS(null));
  }, []);
  return s;
}

export function resetAiStatus() { cached = null; }

// Change Set Y: one wording for an AI job's state everywhere (Settings → Local AI jobs, a document's AI panel).
export type AiJobInfo = { status: string; stage?: string; stage_label?: string; error?: string; error_category?: string;
  attempts?: number; max_attempts?: number; next_retry_at?: string | null; detail?: Record<string, any> };

/** The part of the pipeline a stage belongs to: OCR or AI analysis. */
export function stageGroup(stage?: string, category?: string): string {
  if ((category || "").startsWith("ocr") || ["ocr_queued", "ocr_running", "validating_ocr"].includes(stage || "")) return "OCR";
  if (["ai_running", "validating_ai"].includes(stage || "")) return "AI analysis";
  if (stage === "saving") return "Saving";
  if (stage === "preparing") return "Preparing";
  return "";
}

/** e.g. "failed · AI analysis: HTTP 400 — …", "queued · retry 2 of 3 at 18:40", "queued · waiting for OCR". */
export function aiJobText(j: AiJobInfo, time: (iso: string) => string): string {
  const group = stageGroup(j.stage, j.error_category);
  if (j.status === "failed") return `failed · ${group ? `${group}: ` : ""}${j.error || "unknown error"}`;
  if (j.status === "queued" && j.next_retry_at) return `queued · retry ${(j.attempts || 0) + 1} of ${j.max_attempts || 3} at ${time(j.next_retry_at)}`;
  if (j.status === "queued" && (j.stage === "ocr_queued" || j.stage === "ocr_running")) return `queued · ${j.stage === "ocr_running" ? "OCR running" : "waiting for OCR"}`;
  if (j.status === "running") return `running · ${j.stage_label || "working"}`;
  if (j.status === "skipped") return `skipped${j.error ? ` · ${j.error}` : ""}`;
  return j.status;
}

/** Content-free facts about a job (engine, character count, model, fallback, HTTP status). */
export function aiJobFacts(d?: Record<string, any>): string {
  if (!d) return "";
  const out: string[] = [];
  if (d.ocr_engine) out.push(`OCR: ${d.ocr_engine === "paddleocr" ? "PaddleOCR" : d.ocr_engine === "tesseract" ? "Tesseract" : d.ocr_engine}${d.ocr_reused ? " (existing text)" : ""}`);
  if (typeof d.ocr_chars === "number") out.push(`${d.ocr_chars.toLocaleString()} characters`);
  if (d.ocr_pages) out.push(`${d.ocr_pages} page${d.ocr_pages > 1 ? "s" : ""}`);
  if (d.parts > 1) out.push(`analysed in ${d.parts} parts`);
  if (d.truncated) out.push(`only the first ${Number(d.analyzed_chars).toLocaleString()} of ${Number(d.total_chars).toLocaleString()} characters analysed`);
  if (d.structured_output) out.push(d.structured_output === "schema" ? "structured output" : "JSON by prompt" + (d.fallback ? " (server has no structured output)" : ""));
  if (d.http_status) out.push(`HTTP ${d.http_status}`);
  return out.join(" · ");
}
