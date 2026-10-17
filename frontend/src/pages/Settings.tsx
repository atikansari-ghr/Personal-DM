import { Suspense } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";
import { Skeleton } from "../components/ui";
import { lazyPage } from "../lazy";
import { useSession } from "../session";

// Change Set X: Settings loads only the section being shown. Each section is its own file and asks the server only
// for its own data; sections already opened switch instantly (their files are loaded, their data is shown at once
// and refreshed in the background).
const AccountSettings = lazyPage(() => import("./settings/Account"));
const adminMod = () => import("./settings/Admin");
const ActivityPanel = lazyPage(() => adminMod().then((m) => ({ default: m.ActivityPanel })));
const AuthPanel = lazyPage(() => adminMod().then((m) => ({ default: m.AuthPanel })));
const ConnectionsPanel = lazyPage(() => adminMod().then((m) => ({ default: m.ConnectionsPanel })));
const DocumentsPanel = lazyPage(() => adminMod().then((m) => ({ default: m.DocumentsPanel })));
const NotificationsAdmin = lazyPage(() => adminMod().then((m) => ({ default: m.NotificationsAdmin })));
const ProcessingPanel = lazyPage(() => adminMod().then((m) => ({ default: m.ProcessingPanel })));
const FamilyPanel = lazyPage(() => import("./settings/Family"));
const LocalAIPanel = lazyPage(() => import("./settings/LocalAI"));
const OverviewAdminPanel = lazyPage(() => import("./settings/OverviewAdmin"));
const OfflineAdminPanel = lazyPage(() => import("./settings/OfflineAdmin"));
const securityMod = () => import("./settings/Security");
const LoginAuditPanel = lazyPage(() => securityMod().then((m) => ({ default: m.LoginAuditPanel })));
const TrafficPanel = lazyPage(() => securityMod().then((m) => ({ default: m.TrafficPanel })));
const SecurityCenter = lazyPage(() => import("./settings/SecurityCenter"));
const SettingsForm = lazyPage(() => import("../components/SettingsForm"));
const BackupPanel = lazyPage(() => import("./settings/Backup"));
const SigninAdmin = lazyPage(() => import("./settings/Signins").then((m) => ({ default: m.SigninAdmin })));
const PerformancePanel = lazyPage(() => import("./settings/Performance"));

const ADMIN_TABS: [string, string][] = [
  ["general", "General"], ["family", "Family & access"], ["documents", "Documents & folders"], ["processing", "OCR & processing"],
  ["notifications", "Notifications"], ["connections", "Connections"], ["authentication", "Authentication"], ["backup", "Backup & Recovery"],
  ["security", "Security"], ["activity", "Activity & health"], ["performance", "Performance"], ["ai", "AI"], ["offline", "Offline & PWA"], ["overview", "Overview & sign-in"],
];

export default function SettingsPage() {
  const { section } = useParams();
  const { session } = useSession();
  const admin = !!session?.user?.is_main_admin;
  const delegate = (session?.delegations || []).length > 0;
  const secAdmin = !admin && !!session?.user?.is_admin;  // Administrator role: security and operations only
  const tabs: [string, string][] = [["account", "My account"], ...(admin ? ADMIN_TABS : [...(delegate || secAdmin ? [["family", secAdmin && !delegate ? "Users" : "Family & access"] as [string, string]] : []), ...(secAdmin ? [["security", "Security"] as [string, string], ["performance", "Performance"] as [string, string]] : [])]), ["help", "Help & documentation"]];
  const active = section || (admin ? "general" : "account");
  // Change Set V: the former Storage & NAS page is now Backup & Recovery → Destinations (old links still arrive)
  if (section === "storage") return <Navigate to="/settings/backup?view=destinations" replace />;
  return (
    <div>
      <div className="page-head"><div><h1>Settings</h1><p className="muted">{admin ? "Manage your family workspace" : "Manage your account"}</p></div></div>
      <nav className="tabs" aria-label="Settings sections">
        {tabs.map(([k, l]) => <Link key={k} to={k === "help" ? "/help" : `/settings/${k}`} className={active === k ? "active" : ""} aria-current={active === k ? "page" : undefined}>{l}</Link>)}
      </nav>
      <Suspense fallback={<Skeleton />}>
      {active === "account" && <AccountSettings />}
      {active === "general" && admin && <SettingsForm section="general" title="General" />}
      {active === "family" && (admin || delegate || secAdmin) && <FamilyPanel />}
      {active === "documents" && admin && <DocumentsPanel />}
      {active === "processing" && admin && <ProcessingPanel />}
      {active === "notifications" && admin && <NotificationsAdmin />}
      {active === "connections" && admin && <ConnectionsPanel />}
      {active === "authentication" && admin && <AuthPanel />}
      {active === "backup" && admin && <BackupPanel />}
      {active === "security" && (admin || secAdmin) && <SecurityCenter />}
      {active === "activity" && admin && <ActivityTabs />}
      {active === "ai" && admin && <LocalAIPanel />}
      {active === "offline" && admin && <OfflineAdminPanel />}
      {active === "overview" && admin && <OverviewAdminPanel />}
      {active === "performance" && (admin || secAdmin) && <PerformancePanel />}
      </Suspense>
    </div>
  );
}

function ActivityTabs() {
  const [params, setParams] = useSearchParams();
  const view = params.get("view") || "health";
  const views: [string, string][] = [["health", "Health & audit log"], ["logins", "Login audit"], ["map", "Sign-in map & Trusted Zones"], ["traffic", "Traffic analytics"]];
  return (
    <div className="stack">
      <nav className="tabs sub" aria-label="Activity views">
        {views.map(([k, l]) => <button key={k} type="button" className={view === k ? "active" : ""} aria-current={view === k ? "page" : undefined} onClick={() => setParams(k === "health" ? {} : { view: k })}>{l}</button>)}
      </nav>
      <Suspense fallback={<Skeleton />}>
      {view === "health" && <ActivityPanel />}
      {view === "logins" && <LoginAuditPanel />}
      {view === "map" && <SigninAdmin />}
      {view === "traffic" && <TrafficPanel />}
      </Suspense>
    </div>
  );
}
