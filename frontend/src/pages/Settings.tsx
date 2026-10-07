import { Link, useParams, useSearchParams } from "react-router-dom";
import { useSession } from "../session";
import AccountSettings from "./settings/Account";
import { ActivityPanel, AuthPanel, ConnectionsPanel, DocumentsPanel, NotificationsAdmin, ProcessingPanel, StoragePanel } from "./settings/Admin";
import FamilyPanel from "./settings/Family";
import LocalAIPanel from "./settings/LocalAI";
import OverviewAdminPanel from "./settings/OverviewAdmin";
import { LoginAuditPanel, TrafficPanel } from "./settings/Security";
import SecurityCenter from "./settings/SecurityCenter";
import SettingsForm from "../components/SettingsForm";

const ADMIN_TABS: [string, string][] = [
  ["general", "General"], ["family", "Family & access"], ["documents", "Documents & folders"], ["processing", "OCR & processing"],
  ["notifications", "Notifications"], ["connections", "Connections"], ["authentication", "Authentication"], ["storage", "Storage & backup"],
  ["security", "Security"], ["activity", "Activity & health"], ["ai", "Local AI"], ["overview", "Overview & sign-in"],
];

export default function SettingsPage() {
  const { section } = useParams();
  const { session } = useSession();
  const admin = !!session?.user?.is_main_admin;
  const delegate = (session?.delegations || []).length > 0;
  const secAdmin = !admin && !!session?.user?.is_admin;  // Administrator role: security and operations only
  const tabs: [string, string][] = [["account", "My account"], ...(admin ? ADMIN_TABS : [...(delegate ? [["family", "Family & access"] as [string, string]] : []), ...(secAdmin ? [["security", "Security"] as [string, string]] : [])]), ["help", "Help & documentation"]];
  const active = section || (admin ? "general" : "account");
  return (
    <div>
      <div className="page-head"><div><h1>Settings</h1><p className="muted">{admin ? "Manage your family workspace" : "Manage your account"}</p></div></div>
      <nav className="tabs" aria-label="Settings sections">
        {tabs.map(([k, l]) => <Link key={k} to={k === "help" ? "/help" : `/settings/${k}`} className={active === k ? "active" : ""} aria-current={active === k ? "page" : undefined}>{l}</Link>)}
      </nav>
      {active === "account" && <AccountSettings />}
      {active === "general" && admin && <SettingsForm section="general" title="General" />}
      {active === "family" && (admin || delegate) && <FamilyPanel />}
      {active === "documents" && admin && <DocumentsPanel />}
      {active === "processing" && admin && <ProcessingPanel />}
      {active === "notifications" && admin && <NotificationsAdmin />}
      {active === "connections" && admin && <ConnectionsPanel />}
      {active === "authentication" && admin && <AuthPanel />}
      {active === "storage" && admin && <StoragePanel />}
      {active === "security" && (admin || secAdmin) && <SecurityCenter />}
      {active === "activity" && admin && <ActivityTabs />}
      {active === "ai" && admin && <LocalAIPanel />}
      {active === "overview" && admin && <OverviewAdminPanel />}
    </div>
  );
}

function ActivityTabs() {
  const [params, setParams] = useSearchParams();
  const view = params.get("view") || "health";
  const views: [string, string][] = [["health", "Health & audit log"], ["logins", "Login audit"], ["traffic", "Traffic analytics"]];
  return (
    <div className="stack">
      <nav className="tabs sub" aria-label="Activity views">
        {views.map(([k, l]) => <button key={k} type="button" className={view === k ? "active" : ""} aria-current={view === k ? "page" : undefined} onClick={() => setParams(k === "health" ? {} : { view: k })}>{l}</button>)}
      </nav>
      {view === "health" && <ActivityPanel />}
      {view === "logins" && <LoginAuditPanel />}
      {view === "traffic" && <TrafficPanel />}
    </div>
  );
}
