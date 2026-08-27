import { useState } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";
import { LiveDiagnosis } from "./components/LiveDiagnosis";
import { ExperimentResults } from "./components/ExperimentResults";
import { ConnectPage } from "./pages/ConnectPage";
import { ConnectCallbackPage } from "./pages/ConnectCallbackPage";
import { RepoOverviewPage } from "./pages/RepoOverviewPage";
import { RepoDetailPage } from "./pages/RepoDetailPage";
import { SettingsPage } from "./pages/SettingsPage";
import { useSession } from "./session";

type DemoTab = "diagnosis" | "experiments";

function DemoPage() {
  const [tab, setTab] = useState<DemoTab>("diagnosis");
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-6 py-4">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold">
            SERA <span className="font-normal text-slate-500">— research demo (dark mode)</span>
          </h1>
          <Link to="/" className="text-xs text-indigo-400 hover:underline">
            ← multi-tenant dashboard
          </Link>
        </div>
        <nav className="mt-3 flex gap-1 text-sm">
          <button
            className={`rounded-md px-3 py-1.5 ${
              tab === "diagnosis" ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"
            }`}
            onClick={() => setTab("diagnosis")}
          >
            Live diagnosis
          </button>
          <button
            className={`rounded-md px-3 py-1.5 ${
              tab === "experiments" ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"
            }`}
            onClick={() => setTab("experiments")}
          >
            Experiment results
          </button>
        </nav>
      </header>
      <main className="mx-auto max-w-4xl px-6 py-6">
        {tab === "diagnosis" ? <LiveDiagnosis /> : <ExperimentResults />}
      </main>
    </div>
  );
}

function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { session } = useSession();
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <div className="flex items-center justify-between">
          <Link to="/" className="text-lg font-semibold text-slate-800">
            SERA
          </Link>
          <nav className="flex items-center gap-4 text-sm">
            {session && (
              <span className="text-xs text-slate-400">{session.githubUsername}</span>
            )}
            <Link to="/demo" className="text-slate-500 hover:text-slate-700">
              Research demo (dark mode) →
            </Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-6 py-6">{children}</main>
    </div>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/demo" element={<DemoPage />} />
      <Route
        path="/connect"
        element={
          <DashboardLayout>
            <ConnectPage />
          </DashboardLayout>
        }
      />
      <Route
        path="/connect/callback"
        element={
          <DashboardLayout>
            <ConnectCallbackPage />
          </DashboardLayout>
        }
      />
      <Route
        path="/"
        element={
          <DashboardLayout>
            <RepoOverviewPage />
          </DashboardLayout>
        }
      />
      <Route
        path="/repos/:id"
        element={
          <DashboardLayout>
            <RepoDetailPage />
          </DashboardLayout>
        }
      />
      <Route
        path="/repos/:id/settings"
        element={
          <DashboardLayout>
            <SettingsPage />
          </DashboardLayout>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
