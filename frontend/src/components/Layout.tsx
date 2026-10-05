import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { onSignOut } from "../offline";
import { useSession } from "../session";
import { Avatar, Icon } from "./ui";
import { useAiStatus } from "../ai";

const NAV = [
  ["/", "home", "Overview"],
  ["/folders", "folder", "Folders"],
  ["/shared", "users", "Shared with me"],
  ["/offline", "download", "Offline files"],
  ["/notifications", "bell", "Notifications"],
  ["/archive", "archive", "Archive"],
  ["/settings", "settings", "Settings"],
];

export function SearchBox() {
  const nav = useNavigate();
  const loc = useLocation();
  const [q, setQ] = useState(new URLSearchParams(loc.search).get("q") || "");
  const [sugs, setSugs] = useState<string[]>([]);
  const [sel, setSel] = useState(-1);
  const timer = useRef<number>();
  useEffect(() => {
    window.clearTimeout(timer.current);
    if (q.trim().length < 2) {
      setSugs([]);
      return;
    }
    timer.current = window.setTimeout(() => {
      api<{ suggestions: string[] }>("search/autocomplete", { query: { q } }).then((r) => setSugs(r.suggestions)).catch(() => setSugs([]));
    }, 180);
  }, [q]);
  const go = (term: string) => {
    setSugs([]);
    nav(`/search?q=${encodeURIComponent(term)}`);
  };
  return (
    <form className="search" role="search" onSubmit={(e) => { e.preventDefault(); go(sel >= 0 ? sugs[sel] : q); }}>
      <Icon name="search" className="lead" size={18} />
      <label className="sr-only" htmlFor="global-search">Search your documents</label>
      <input id="global-search" type="search" placeholder="Search your documents" value={q} autoComplete="off"
        role="combobox" aria-expanded={sugs.length > 0} aria-controls="search-suggest" aria-autocomplete="list"
        onChange={(e) => { setQ(e.target.value); setSel(-1); }}
        onBlur={() => setTimeout(() => setSugs([]), 150)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(sugs.length - 1, s + 1)); }
          if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(-1, s - 1)); }
          if (e.key === "Escape") setSugs([]);
        }} />
      {sugs.length > 0 && (
        <div className="suggest" id="search-suggest" role="listbox">
          {sugs.map((s, i) => (
            <button type="button" role="option" aria-selected={i === sel} key={s} onMouseDown={() => go(s)}>{s}</button>
          ))}
        </div>
      )}
    </form>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const { session, offline, refresh } = useSession();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [views, setViews] = useState<{ id: number; name: string; query: any; show_in_sidebar: boolean; count: number }[]>([]);
  const [menu, setMenu] = useState(false);
  const loc = useLocation();
  const nav = useNavigate();
  const user = session?.user;
  const ai = useAiStatus();

  useEffect(() => setOpen(false), [loc.pathname]);
  useEffect(() => {
    if (offline) return;
    api<{ unread: number }>("notifications", { query: { unread: 1 } }).then((r) => setUnread(r.unread)).catch(() => undefined);
    api<{ views: any[] }>("views").then((r) => setViews(r.views.filter((v) => v.show_in_sidebar))).catch(() => undefined);
  }, [loc.pathname, offline]);

  const signOut = async () => {
    if (user) await onSignOut(user.id);
    await api("auth/logout", { method: "POST" }).catch(() => undefined);
    await refresh();
    nav("/login");
  };

  return (
    <div className="shell">
      <aside className={`sidebar ${open ? "open" : ""}`} aria-label="Main navigation">
        <Link to="/" className="brand"><Icon name="shield" size={26} /> {session?.app_name || "Personal Documents"}</Link>
        <nav className="nav">
          {NAV.filter(([p]) => p !== "/archive" || user?.is_main_admin).map(([path, icon, label]) => (
            <NavLink key={path} to={path} end={path === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              <Icon name={icon} /> {label}
              {path === "/notifications" && unread > 0 && <span className="count" aria-label={`${unread} unread`}>{unread}</span>}
            </NavLink>
          ))}
          {ai?.assistant && <NavLink to="/assistant" className={({ isActive }) => (isActive ? "active" : "")}><Icon name="sparkle" /> Ask AI</NavLink>}
          {views.length > 0 && <div className="side-section">Saved views</div>}
          {views.map((v) => (
            <NavLink key={v.id} to={`/search?${new URLSearchParams(v.query).toString()}&view=${v.id}`}>
              <Icon name="list" size={18} /> {v.name} <span className="muted small" style={{ marginLeft: "auto" }}>{v.count}</span>
            </NavLink>
          ))}
          <NavLink to="/help"><Icon name="help" /> Help</NavLink>
        </nav>
        {user && (
          <div className="side-user">
            <Avatar user={user as any} />
            <div className="grow">
              <div style={{ fontWeight: 650 }}>{user.display_name}</div>
              <div className="muted small">{user.is_main_admin ? "Main administrator" : user.role_label || "Family member"}</div>
            </div>
            <button className="icon-btn" onClick={signOut} aria-label="Sign out" title="Sign out"><Icon name="logout" /></button>
          </div>
        )}
      </aside>
      <div className="main">
        <header className="topbar">
          <button className="icon-btn menu-btn" aria-label="Open menu" aria-expanded={open} onClick={() => setOpen(!open)}><Icon name="menu" /></button>
          <SearchBox />
          <div className="row" style={{ marginLeft: "auto", gap: "0.4rem" }}>
            <Link to="/notifications" className="icon-btn" style={{ position: "relative" }} aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}>
              <Icon name="bell" />
              {unread > 0 && <span className="dot" />}
            </Link>
            <div style={{ position: "relative" }}>
              <button className="icon-btn" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu(!menu)} aria-label="Account menu">
                <Avatar user={user as any} size="sm" />
              </button>
              {menu && (
                <div className="suggest" role="menu" style={{ right: 0, left: "auto", minWidth: 200 }} onMouseLeave={() => setMenu(false)}>
                  <button role="menuitem" onClick={() => { setMenu(false); nav("/settings/account"); }}>My profile</button>
                  <button role="menuitem" onClick={() => { setMenu(false); nav("/settings/account?tab=appearance"); }}>Appearance</button>
                  <button role="menuitem" onClick={() => { setMenu(false); nav("/help"); }}>Help</button>
                  <button role="menuitem" onClick={signOut}>Sign out</button>
                </div>
              )}
            </div>
          </div>
        </header>
        {offline && <div className="alert warn" style={{ margin: "0.8rem 1.4rem 0" }}>You are offline. Only files you saved for offline use on this device are available.</div>}
        <main className="content" id="main">{children}</main>
      </div>
      {open && <div className="modal-backdrop" style={{ zIndex: 50, background: "rgba(0,0,0,.25)" }} onClick={() => setOpen(false)} />}
    </div>
  );
}
