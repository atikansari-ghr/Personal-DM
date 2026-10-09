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

// Browser/OS chrome colour (address bar, installed-app title bar) per theme.
const THEME_COLOR: Record<string, string> = { green: "#1f5135", blue: "#1d4e89", mono: "#111111", dark: "#0f1513", glass_light: "#eef4f1", glass_dark: "#0b1411" };

export function applyThemeAttr(theme: string) {
  document.documentElement.dataset.theme = theme || "green";
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLOR[theme] || THEME_COLOR.green);
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
        const s: Session = { setup_complete: true, app_name: "Personal Documents Management System", version: "", google_enabled: false, pending_2fa: false,
          user: last ? ({ ...last, initials: "", avatar_color: "#ddd", role_label: "", is_main_admin: false, is_active: true, is_head: false } as any) : null };
        setSession(s);
        return s;
      }
      throw e;
    }
  }, []);

  useEffect(() => {
    refresh().catch(() => setSession({ setup_complete: true, app_name: "Personal Documents Management System", version: "", google_enabled: false, pending_2fa: false, user: null }));
    const out = () => refresh();
    window.addEventListener("pd:signed-out", out);
    window.addEventListener("online", out);
    window.addEventListener("pd:settings-saved", out);
    window.addEventListener("pd:2fa-setup", out);
    // Account preferences (theme, dashboard widgets, layout…) live on the server; pick up changes made on another
    // device when this one comes back to the foreground (at most once a minute).
    let last = Date.now();
    const visible = () => {
      if (document.visibilityState === "visible" && Date.now() - last > 60_000) { last = Date.now(); refresh().catch(() => undefined); }
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      document.removeEventListener("visibilitychange", visible);
      window.removeEventListener("pd:settings-saved", out);
      window.removeEventListener("pd:signed-out", out);
      window.removeEventListener("pd:2fa-setup", out);
      window.removeEventListener("online", out);
    };
  }, [refresh]);

  return <SessionContext.Provider value={{ session, offline, refresh, applyTheme: applyThemeAttr }}>{children}</SessionContext.Provider>;
}

export const useSession = () => useContext(SessionContext);
