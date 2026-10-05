import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setDateFormat } from "./api";
import type { Session } from "./types";

interface Ctx {
  session: Session | null;
  offline: boolean;
  refresh: () => Promise<Session | null>;
  applyTheme: (t: string) => void;
}
const SessionContext = createContext<Ctx>(null as any);

export function applyThemeAttr(theme: string) {
  document.documentElement.dataset.theme = theme || "green";
  try {
    localStorage.setItem("pd-theme", theme || "green");
  } catch {
    /* storage unavailable */
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [offline, setOffline] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const s = await api<Session>("session");
      setSession(s);
      setOffline(false);
      if (s.user) {
        applyThemeAttr(s.preferences?.theme || "green");
        setDateFormat(s.date_format || "");
        try {
          localStorage.setItem("pd-last-user", JSON.stringify({ id: s.user.id, display_name: s.user.display_name }));
        } catch {
          /* ignore */
        }
      }
      document.title = s.app_name;
      return s;
    } catch (e: any) {
      if (e.status === 0 || !navigator.onLine) {
        setOffline(true);
        // Offline mode: only the last signed-in user's explicitly saved files are shown.
        let last: any = null;
        try {
          last = JSON.parse(localStorage.getItem("pd-last-user") || "null");
        } catch {
          last = null;
        }
        const s: Session = { setup_complete: true, app_name: "Personal Documents", version: "", google_enabled: false, pending_2fa: false,
          user: last ? ({ ...last, initials: "", avatar_color: "#ddd", role_label: "", is_main_admin: false, is_active: true, is_head: false } as any) : null };
        setSession(s);
        return s;
      }
      throw e;
    }
  }, []);

  useEffect(() => {
    refresh().catch(() => setSession({ setup_complete: true, app_name: "Personal Documents", version: "", google_enabled: false, pending_2fa: false, user: null }));
    const out = () => refresh();
    window.addEventListener("pd:signed-out", out);
    window.addEventListener("online", out);
    window.addEventListener("pd:settings-saved", out);
    window.addEventListener("pd:2fa-setup", out);
    return () => {
      window.removeEventListener("pd:settings-saved", out);
      window.removeEventListener("pd:signed-out", out);
      window.removeEventListener("pd:2fa-setup", out);
      window.removeEventListener("online", out);
    };
  }, [refresh]);

  return <SessionContext.Provider value={{ session, offline, refresh, applyTheme: applyThemeAttr }}>{children}</SessionContext.Provider>;
}

export const useSession = () => useContext(SessionContext);
