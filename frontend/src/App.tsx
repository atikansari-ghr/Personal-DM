import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout";
import { Skeleton } from "./components/ui";
import ArchivePage from "./pages/Archive";
import { ChangePassword, ForcedTwoFactor, ForgotPassword, Login, ResetPassword } from "./pages/Auth";
import Dashboard from "./pages/Dashboard";
import DocumentPage from "./pages/DocumentPage";
import FoldersPage from "./pages/Folders";
import HelpPage from "./pages/Help";
import ImportWizard from "./pages/ImportWizard";
import NotificationsPage from "./pages/Notifications";
import OfflinePage from "./pages/Offline";
import SearchPage from "./pages/Search";
import SettingsPage from "./pages/Settings";
import Setup from "./pages/Setup";
import SharedPage from "./pages/Shared";
import UploadShared from "./pages/UploadShared";
import { useSession } from "./session";
import AssistantPage from "./pages/Assistant";

export default function App() {
  const { session, offline } = useSession();
  const loc = useLocation();
  if (!session) return <div style={{ padding: 40 }}><Skeleton /></div>;
  const publicRoutes = (
    <Routes>
      <Route path="/setup" element={<Setup />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/login" element={<Login />} />
      <Route path="*" element={<Navigate to={session.setup_complete ? `/login?next=${encodeURIComponent(loc.pathname + loc.search)}` : "/setup"} replace />} />
    </Routes>
  );
  if (!session.user) return publicRoutes;
  if (offline) {
    return (
      <Layout>
        <Routes>
          <Route path="*" element={<OfflinePage />} />
        </Routes>
      </Layout>
    );
  }
  if (session.user.must_change_password) return <ChangePassword forced />;
  if (session.user.two_factor_setup_required) return <ForcedTwoFactor />;
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/folders" element={<FoldersPage />} />
        <Route path="/folders/:folderId" element={<FoldersPage />} />
        <Route path="/folders/:folderId/:docId" element={<FoldersPage />} />
        <Route path="/documents/:id" element={<DocumentPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/shared" element={<SharedPage />} />
        <Route path="/offline" element={<OfflinePage />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/archive" element={<ArchivePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/settings/:section" element={<SettingsPage />} />
        <Route path="/imports/new" element={<ImportWizard />} />
        <Route path="/imports/:id" element={<ImportWizard />} />
        <Route path="/assistant" element={<AssistantPage />} />
        <Route path="/help" element={<HelpPage />} />
        <Route path="/help/:slug" element={<HelpPage />} />
        <Route path="/upload-shared" element={<UploadShared />} />
        <Route path="/login" element={<Navigate to={new URLSearchParams(loc.search).get("next") || "/"} replace />} />
        <Route path="/setup" element={<Navigate to="/" replace />} />
        <Route path="*" element={<div className="empty"><h1>Page not found</h1></div>} />
      </Routes>
    </Layout>
  );
}
