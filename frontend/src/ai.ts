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
