import { Suspense, useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { safeNext } from "./api";
import { Skeleton } from "./components/ui";
import { ChangePassword, ForcedTwoFactor, ForgotPassword, Login, ResetPassword } from "./pages/Auth";
import Setup from "./pages/Setup";
import { useSession } from "./session";
import { clearChunkReloadFlag, lazyPage, prefetchWhenIdle } from "./lazy";

// Change Set X: sign-in, setup and password screens stay in the main file (they must work at once); every other
// screen loads when first opened, and the likely next ones are fetched in the background when the browser is idle.
const load = {
  layout: () => import("./components/Layout"),
  dashboard: () => import("./pages/Dashboard"),
  folders: () => import("./pages/Folders"),
  document: () => import("./pages/DocumentPage"),
  search: () => import("./pages/Search"),
  settings: () => import("./pages/Settings"),
  notifications: () => import("./pages/Notifications"),
};
const Layout = lazyPage(load.layout);
const Dashboard = lazyPage(load.dashboard);
const FoldersPage = lazyPage(load.folders);
const DocumentPage = lazyPage(load.document);
const SearchPage = lazyPage(load.search);
const SettingsPage = lazyPage(load.settings);
const NotificationsPage = lazyPage(load.notifications);
const OcrReviewPage = lazyPage(() => import("./pages/OcrReview"));
const ArchivePage = lazyPage(() => import("./pages/Archive"));
const HelpPage = lazyPage(() => import("./pages/Help"));
const ImportWizard = lazyPage(() => import("./pages/ImportWizard"));
const OfflinePage = lazyPage(() => import("./pages/Offline"));
const SharedPage = lazyPage(() => import("./pages/Shared"));
const UploadShared = lazyPage(() => import("./pages/UploadShared"));
const AssistantPage = lazyPage(() => import("./pages/Assistant"));
const RecoveryPage = lazyPage(() => import("./pages/Recovery"));

const Loading = () => <div style={{ padding: 40 }}><Skeleton /></div>;

export default function App() {
  const { session, offline } = useSession();
  const loc = useLocation();
  const signedIn = !!session?.user;
  useEffect(() => {
    clearChunkReloadFlag();
    // on the sign-in page: the first screen after signing in; when signed in: the screens people open next
    prefetchWhenIdle(signedIn ? [load.folders, load.document, load.search, load.settings, load.notifications] : [load.layout, load.dashboard]);
  }, [signedIn]);
  if (!session) return <Loading />;
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
      <Suspense fallback={<Loading />}><Layout>
        <Routes>
          <Route path="*" element={<OfflinePage />} />
        </Routes>
      </Layout></Suspense>
    );
  }
  if (session.user.must_change_password) return <ChangePassword forced />;
  if (session.user.two_factor_setup_required) return <ForcedTwoFactor />;
  return (
    <Suspense fallback={<Loading />}><Layout><Suspense fallback={<Skeleton />}>
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
        <Route path="/recovery" element={<RecoveryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/settings/:section" element={<SettingsPage />} />
        <Route path="/imports/new" element={<ImportWizard />} />
        <Route path="/imports/:id" element={<ImportWizard />} />
        <Route path="/assistant" element={<AssistantPage />} />
        <Route path="/ocr-review" element={<OcrReviewPage />} />
        <Route path="/help" element={<HelpPage />} />
        <Route path="/help/:slug" element={<HelpPage />} />
        <Route path="/upload-shared" element={<UploadShared />} />
        <Route path="/login" element={<Navigate to={safeNext(new URLSearchParams(loc.search).get("next"))} replace />} />
        <Route path="/setup" element={<Navigate to="/" replace />} />
        <Route path="*" element={<div className="empty"><h1>Page not found</h1></div>} />
      </Routes>
    </Suspense></Layout></Suspense>
  );
}
